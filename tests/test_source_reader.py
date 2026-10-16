"""Source reads remain inside published immutable artifacts and bounded windows."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from navcom_source_reader import read_source, SourceReadError, MAX_WINDOW_BYTES


def publish(cache, root, files, source_id="quartz", include=None, provenance=None):
    source = dict(id=source_id, label="Quartz", root=str(root), include=include or ["."],
                  max_file_bytes=4 * 1024 * 1024)
    if provenance:
        source["provenance"] = provenance
    signature = hashlib.sha256(json.dumps([(name, hashlib.sha256(data).hexdigest())
                                         for name, data in sorted(files.items())]).encode()).hexdigest()
    extractor = "e" * 64
    key = hashlib.sha256(json.dumps([source, signature, extractor], sort_keys=True).encode()).hexdigest()
    artifact = cache / "artifacts" / key
    for name, content in files.items():
        target = artifact / "source" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    receipt = dict(source=source, signature=signature, extractor=extractor)
    (artifact / "receipt.json").write_text(json.dumps(receipt))
    state = dict(published=1700000000.25, sources=[dict(source, artifact=str(artifact),
                                                   signature=signature, extractor=extractor)])
    (cache / "current.json").write_text(json.dumps(state))
    return artifact, state


@pytest.fixture
def saved(tmp_path):
    live = tmp_path / "live"
    live.mkdir()
    files = {"docs/start.md": "# Quartz\nA real café.\nKeep the source.\n".encode(),
             "large.py": "".join(f"line_{n} = {n}\n" for n in range(1, 701)).encode()}
    cache = tmp_path / "cache"
    artifact, state = publish(cache, live, files)
    return live, cache, artifact, state, files


def test_exact_snapshot_bytes_provenance_and_live_address_is_display_only(saved):
    live, cache, artifact, state, files = saved
    (live / "docs").mkdir()
    (live / "docs/start.md").write_text("UNINDEXED FUTURE CONTENT")
    result = read_source("quartz", str(live / "docs/start.md"), line=2, limit=1, cache_path=cache,
                         published=state["published"])
    assert result["lines"] == [dict(number=2, text="A real café.", truncated=False)]
    assert result["sha256"] == hashlib.sha256(files["docs/start.md"]).hexdigest()
    assert result["original_path"] == str(live / "docs/start.md")
    assert result["snapshot_path"] == str(artifact / "source/docs/start.md")
    assert result["provenance"]["current_file_read"] is False
    assert result["window"]["previous_line"] == 1 and result["window"]["next_line"] == 3
    assert "--snapshot " + artifact.name in result["cli_command"]
    assert "--published 1700000000.25" in result["cli_command"]
    (live / "docs/start.md").unlink()
    assert read_source("quartz", "docs/start.md", cache_path=cache)["lines"][0]["text"] == "# Quartz"


def test_large_file_windows_have_true_line_numbers_and_stable_pinning(saved):
    _, cache, artifact, state, _ = saved
    result = read_source("quartz", "large.py", line=400, limit=200, cache_path=cache,
                         snapshot=artifact.name, published=state["published"])
    assert len(result["lines"]) == 200
    assert result["lines"][0]["text"] == "line_400 = 400"
    assert result["lines"][-1]["number"] == 599
    assert result["window"]["total_lines"] == 700
    assert result["window"]["next_line"] == 600
    assert result["window"]["previous_line"] == 200
    assert result["window"]["bytes"] <= MAX_WINDOW_BYTES


def test_source_resolves_exact_id_then_unique_label_or_root(saved):
    live, cache, _, state, _ = saved
    assert read_source("Quartz", "large.py", cache_path=cache)["source_id"] == "quartz"
    assert read_source(str(live), "large.py", cache_path=cache)["ref"]["source"] == "quartz"
    assert "sources read quartz large.py" in read_source("Quartz", "large.py", cache_path=cache)["cli_command"]
    state["sources"].append(dict(state["sources"][0], id="other"))
    (cache / "current.json").write_text(json.dumps(state))
    with pytest.raises(SourceReadError, match="exactly one"):
        read_source("Quartz", "large.py", cache_path=cache)
    assert read_source("quartz", "large.py", cache_path=cache)["source_id"] == "quartz"


@pytest.mark.parametrize("path", ["../escape", "docs/../../escape", "/etc/passwd", "docs\\escape", "", "docs\x00name"])
def test_untrusted_paths_cannot_escape_source(saved, path):
    with pytest.raises(SourceReadError):
        read_source("quartz", path, cache_path=saved[1])


@pytest.mark.parametrize("line,limit", [(0, 80), (-1, 1), (True, 1), (1, 201), (1, 0), (1, False), ("1", 80)])
def test_limits_are_enforced_before_read(saved, line, limit):
    with pytest.raises(SourceReadError, match="Line must"):
        read_source("quartz", "large.py", line=line, limit=limit, cache_path=saved[1])


def test_stale_generation_and_wrong_source_never_silently_switch_snapshots(saved):
    _, cache, _, _, _ = saved
    with pytest.raises(SourceReadError, match="generation changed"):
        read_source("quartz", "large.py", cache_path=cache, published=123)
    with pytest.raises(SourceReadError, match="snapshot changed"):
        read_source("quartz", "large.py", cache_path=cache, snapshot="f" * 64)
    with pytest.raises(SourceReadError, match="exactly one"):
        read_source("other", "large.py", cache_path=cache)
    with pytest.raises(SourceReadError, match="past the end"):
        read_source("quartz", "large.py", line=701, cache_path=cache)


def test_exact_snapshot_survives_other_source_publication_but_unpinned_result_does_not(saved, tmp_path):
    _, cache, artifact, first, files = saved
    original = first["sources"][0]
    _, current = publish(cache, tmp_path / "other-live", {"README.md": b"Another source\n"}, source_id="other")
    current["sources"].insert(0, original)
    current["published"] = first["published"] + 1
    (cache / "current.json").write_text(json.dumps(current))
    result = read_source("quartz", "docs/start.md", cache_path=cache,
                         snapshot=artifact.name, published=first["published"])
    assert result["sha256"] == hashlib.sha256(files["docs/start.md"]).hexdigest()
    assert result["snapshot"] == result["ref"]["snapshot"] == artifact.name
    assert result["published"] == result["ref"]["published"] == current["published"]
    assert result["provenance"]["requested_published"] == first["published"]
    assert result["provenance"]["publication_changed"] is True
    assert result["provenance"]["pin_validation"] == "exact currently published artifact"
    assert result["provenance"]["captured_at"] is None
    assert result["provenance"]["current_file_read"] is False
    assert "--published " + str(current["published"]) in result["cli_command"]
    with pytest.raises(SourceReadError, match="generation changed"):
        read_source("quartz", "docs/start.md", cache_path=cache, published=first["published"])
    with pytest.raises(SourceReadError, match="snapshot changed"):
        read_source("quartz", "docs/start.md", cache_path=cache,
                    snapshot="f" * 64, published=first["published"])
    # An exact pin never bypasses the source receipt's identity validation.
    receipt_path = artifact / "receipt.json"
    receipt = json.loads(receipt_path.read_text())
    receipt["source"]["id"] = "other"
    receipt_path.write_text(json.dumps(receipt))
    with pytest.raises(SourceReadError, match="receipt does not match"):
        read_source("quartz", "docs/start.md", cache_path=cache,
                    snapshot=artifact.name, published=first["published"])


@pytest.mark.skipif(not shutil.which("starforge"), reason="Optional native Starforge runtime required")
def test_public_cli_pin_survives_native_unrelated_harvest_and_rejects_changed_source(tmp_path):
    cli = Path(__file__).resolve().parents[1] / "navcom.py"
    cache = tmp_path / "cache"
    roots = [tmp_path / name for name in ("quartz", "violet")]
    for root in roots:
        root.mkdir()
        (root / "README.md").write_text("# " + root.name + "\nOriginal retained evidence.\n")
    env = dict(os.environ, NAVCOM_NO_SKILLS="1")

    def command(*args, ok=True):
        result = subprocess.run([sys.executable, str(cli), "sources", *map(str, args), "--cache", str(cache), "--json"],
                                capture_output=True, text=True, env=env, timeout=25)
        assert (result.returncode == 0) is ok, result.stderr
        return json.loads(result.stdout) if ok else result

    command("harvest", roots[0], "--include", "README.md", "--index", tmp_path / "absent.sqlite")
    first = command("read", roots[0], "README.md")
    pinned = ["read", first["source_id"], "README.md", "--snapshot", first["snapshot"], "--published", first["published"]]
    command("harvest", roots[1], "--include", "README.md", "--index", tmp_path / "absent.sqlite")
    kept = command(*pinned)
    assert kept["published"] != first["published"]
    assert kept["snapshot"] == first["snapshot"] and kept["sha256"] == first["sha256"]
    assert kept["lines"] == first["lines"]
    assert kept["provenance"]["publication_changed"] is True
    stale = command("read", first["source_id"], "README.md", "--published", first["published"], ok=False)
    assert "generation changed" in stale.stderr
    (roots[0] / "README.md").write_text("# Quartz changed\nNew captured evidence.\n")
    command("harvest", roots[0], "--include", "README.md", "--index", tmp_path / "absent.sqlite")
    changed = command(*pinned, ok=False)
    assert "snapshot changed" in changed.stderr
    assert not (tmp_path / "absent.sqlite").exists()


@pytest.mark.parametrize("target", ["file", "parent", "snapshot", "registry"])
def test_symlinks_are_rejected_at_every_untrusted_component(saved, tmp_path, target):
    _, cache, artifact, _, _ = saved
    if target == "file":
        original = artifact / "source/docs/start.md"
        original.unlink()
        original.symlink_to(tmp_path / "secret.md")
        (tmp_path / "secret.md").write_text("not part of the harvest")
    elif target == "parent":
        original = artifact / "source/docs"
        original.rename(artifact / "source/old-docs")
        original.symlink_to(artifact / "source/old-docs", target_is_directory=True)
    elif target == "snapshot":
        original = artifact / "source"
        original.rename(artifact / "old-source")
        original.symlink_to(artifact / "old-source", target_is_directory=True)
    else:
        original = cache / "current.json"
        original.rename(cache / "old-current.json")
        original.symlink_to(cache / "old-current.json")
    with pytest.raises(SourceReadError, match="symlink"):
        read_source("quartz", "docs/start.md", cache_path=cache)


def test_fifo_cannot_block_the_reader(saved):
    _, cache, artifact, _, _ = saved
    target = artifact / "source/large.py"
    target.unlink()
    os.mkfifo(target)
    with pytest.raises(SourceReadError, match="regular"):
        read_source("quartz", "large.py", cache_path=cache)


def test_registry_cannot_redirect_reader_to_an_arbitrary_artifact(saved, tmp_path):
    _, cache, artifact, state, _ = saved
    state["sources"][0]["artifact"] = str(tmp_path / "outside" / artifact.name)
    (cache / "current.json").write_text(json.dumps(state))
    with pytest.raises(SourceReadError, match="outside"):
        read_source("quartz", "large.py", cache_path=cache)


def test_long_unicode_line_is_bounded_and_disclosed(tmp_path):
    cache = tmp_path / "cache"
    publish(cache, tmp_path / "missing-live", {"wide.md": ("é" * 100000 + "\nlast line\n").encode()})
    result = read_source("quartz", "wide.md", cache_path=cache)
    assert len(result["lines"]) == 1
    assert result["window"]["byte_truncated"] and result["lines"][0]["truncated"]
    assert len(result["lines"][0]["text"].encode()) <= MAX_WINDOW_BYTES
    assert result["window"]["total_lines"] == 2
    assert result["window"]["next_line"] == 2
    assert read_source("quartz", "wide.md", line=2, cache_path=cache)["lines"][0]["text"] == "last line"


@pytest.mark.parametrize("contents", [b"one\0two", b"\xff\xfe invalid"])
def test_binary_and_non_utf8_are_not_presented_as_source(tmp_path, contents):
    cache = tmp_path / "cache"
    publish(cache, tmp_path / "missing", {"binary.md": contents})
    with pytest.raises(SourceReadError):
        read_source("quartz", "binary.md", cache_path=cache)


def test_scope_rejects_files_added_outside_published_selection(tmp_path):
    cache = tmp_path / "cache"
    artifact, _ = publish(cache, tmp_path / "missing", {"docs/start.md": b"hello\n"}, include=["docs"])
    (artifact / "source/extra.py").write_text("not selected")
    with pytest.raises(SourceReadError, match="selected paths"):
        read_source("quartz", "extra.py", cache_path=cache)


def test_history_reads_cached_harvest_and_verifies_exact_git_bytes_without_runtime(tmp_path):
    history = tmp_path / "history"
    identity, commit, tree = "a" * 64, "b" * 40, "c" * 40
    folder = history / "revisions" / identity
    snapshot = folder / "snapshot"
    snapshot.mkdir(parents=True)
    files = {"README.md": b"# Earlier product\nPassword login\n"}
    receipt = dict(id=identity, kind="git_revision", repository=str(tmp_path / "deleted-repo"),
                   snapshot_path=str(snapshot), source_cache=str(folder / "harvest"),
                   commit=commit, tree=tree, observed_at=1600000000,
                   files=[dict(path=p, bytes=len(b), sha256=hashlib.sha256(b).hexdigest()) for p, b in files.items()])
    (folder / "receipt.json").write_text(json.dumps(receipt))
    artifact, _ = publish(folder / "harvest", snapshot, files, source_id=identity,
                          provenance=dict(commit=commit, tree=tree))
    result = read_source(identity, str(snapshot / "README.md"), history=identity, history_cache=history)
    assert result["provenance"]["commit"] == commit
    assert result["provenance"]["file_hash_verification"] == "pinned Git receipt"
    assert result["original_path"] == str(tmp_path / "deleted-repo/README.md")
    assert "--history " + identity in result["cli_command"]
    (artifact / "source/README.md").write_text("Wrong historical bytes\n")
    with pytest.raises(SourceReadError, match="pinned Git content hash"):
        read_source(identity, "README.md", history=identity, history_cache=history)


def test_missing_cache_and_receipt_errors_are_actionable(saved, tmp_path):
    with pytest.raises(SourceReadError, match="required"):
        read_source("quartz", "file.py")
    with pytest.raises(SourceReadError, match="unavailable"):
        read_source("quartz", "file.py", cache_path=tmp_path / "missing")
    (saved[2] / "receipt.json").write_text("{}")
    with pytest.raises(SourceReadError, match="content identity"):
        read_source("quartz", "large.py", cache_path=saved[1])
