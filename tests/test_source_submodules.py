"""Native parent and submodule policies stay independent during source intake."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

import navcom_source_discovery as discovery


def git(root, *arguments):
    return subprocess.run(["git", "-C", str(root), *arguments], check=True,
                          capture_output=True, text=True).stdout


@pytest.fixture
def submodule(tmp_path):
    upstream = tmp_path / "source-library"
    upstream.mkdir()
    git(upstream, "init", "-q")
    (upstream / ".gitignore").write_text("*.py\n!visible.py\n")
    (upstream / "README.md").write_text("# Maintained calibration engine\n")
    (upstream / "tracked.py").write_text("def calibration(): return 17\n")
    git(upstream, "add", "-f", ".gitignore", "README.md", "tracked.py")
    git(upstream, "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
        "commit", "-qm", "Initial library")
    root = tmp_path / "unfamiliar-observation-product"
    root.mkdir()
    git(root, "init", "-q")
    git(root, "-c", "protocol.file.allow=always", "submodule", "add", "-q", str(upstream), "engine")
    # Parent-only policy must not leak into the nested repository.
    (root / ".gitignore").write_text("parent-ignored.py\nvisible.py\n")
    (root / "README.md").write_text("# Observation product\n")
    (root / "parent.py").write_text("def parent(): return 23\n")
    (root / "parent-ignored.py").write_text("Should not be automatically selected\n")
    child = root / "engine"
    (child / "visible.py").write_text("def locally_allowed(): return 29\n")
    (child / "omitted.py").write_text("Child policy excludes this file\n")
    later = root / "z-laboratory"
    later.mkdir()
    (later / "later.py").write_text("def later_measurement(): return 31\n")
    (later / "parent-ignored.py").write_text("Inherited parent exclusion\n")
    return root, child


def test_real_git_submodule_uses_own_policy_and_preserves_registered_scope(submodule, tmp_path):
    root, child = submodule
    # This is the native failure that formerly killed the entire parent stream.
    failed = subprocess.run(["git", "-C", str(root), "check-ignore", "engine/visible.py"],
                            capture_output=True, text=True)
    assert failed.returncode == 128 and "is in submodule" in failed.stderr
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "current.json").write_text(json.dumps({"sources": [dict(
        root=str(root), id="registered", include=["engine/omitted.py"])]}))
    projects = [dict(label=str(root), collection="projects:observations")]
    result = discovery.discover(None, None, cache, projects=projects)
    source = result["sources"][0]
    assert set(source["discovery_include"]) == {
        "README.md", "parent.py", "engine/README.md", "engine/tracked.py",
        "engine/visible.py", "z-laboratory/later.py"}
    assert "engine/omitted.py" in source["include"]
    policy = source["discovery_coverage"]["git_ignore"]
    assert policy["status"] == "available" and policy["unknown_paths"] == 0
    assert policy["commands"] == 2
    assert {owner["path"] for owner in policy["owners"]} == {".", "engine"}
    # Stable coverage and scope give the existing harvest cache identical input.
    assert discovery.discover(None, None, cache, projects=projects) == result


@pytest.mark.parametrize("missing_marker", [False, True])
def test_unavailable_submodule_does_not_poison_parent_paths(submodule, monkeypatch, missing_marker):
    root, child = submodule
    original = discovery._GitIgnore.check
    if missing_marker:
        (child / ".git").unlink()
    else:
        def fail_child(self, payload, timeout):
            if self.root == child:
                raise subprocess.TimeoutExpired("git check-ignore", timeout)
            return original(self, payload, timeout)
        monkeypatch.setattr(discovery._GitIgnore, "check", fail_child)
    selected, coverage = discovery._metadata(root)
    assert "z-laboratory/later.py" in selected and "parent.py" in selected
    assert "parent-ignored.py" not in selected
    assert not any(path.startswith("engine/") for path in selected)
    policy = coverage["git_ignore"]
    assert policy["status"] == "partial" and policy["unknown_paths"] > 0
    owners = {owner["path"]: owner for owner in policy["owners"]}
    assert owners["."]["status"] == "available"
    assert owners["engine"]["status"] == "unavailable"
    assert "Git ignore policy unavailable; unchecked automatic paths omitted" in coverage["limits"]


def test_failed_parent_batch_restarts_before_later_parent_paths(submodule, monkeypatch):
    root, child = submodule
    early = root / "a-laboratory"
    early.mkdir()
    (early / "first.py").write_text("def first(): return 1\n")
    original = discovery._GitIgnore.check
    failed = []
    instances = []
    def fail_one_batch(self, payload, timeout):
        if self.root == root:
            instances.append(self)
            if b"a-laboratory/first.py\0" in payload and not failed:
                failed.append(True)
                # Simulate a stream that Git closed partway through a batch.
                self.close()
                raise ValueError("native Git closed its output before the batch completed")
        return original(self, payload, timeout)
    monkeypatch.setattr(discovery._GitIgnore, "check", fail_one_batch)
    selected, coverage = discovery._metadata(root)
    assert failed and "a-laboratory/first.py" not in selected
    assert "z-laboratory/later.py" in selected and "engine/visible.py" in selected
    owners = {owner["path"]: owner for owner in coverage["git_ignore"]["owners"]}
    assert owners["."]["status"] == "partial" and owners["."]["restarts"] == 1
    assert owners["engine"]["status"] == "available"
    assert len({id(instance) for instance in instances}) == 2
    assert all(instance.process is None or instance.process.poll() is not None for instance in instances)


def test_parent_ignored_nested_repository_is_not_traversed(submodule):
    root, _ = submodule
    nested = root / "discarded-repository"
    nested.mkdir()
    git(nested, "init", "-q")
    (nested / "visible.py").write_text("def hidden_repository(): return 1\n")
    with (root / ".gitignore").open("a") as stream:
        stream.write("discarded-repository/\n")
    selected, coverage = discovery._metadata(root)
    assert "discarded-repository/visible.py" not in selected
    assert "discarded-repository" not in {owner["path"] for owner in coverage["git_ignore"]["owners"]}


def test_shared_owner_deadline_omits_unknown_inputs(submodule, monkeypatch):
    root, _ = submodule
    monkeypatch.setattr(discovery, "MAX_IGNORE_SECONDS", 0)
    selected, coverage = discovery._metadata(root)
    assert selected == []
    assert coverage["git_ignore"]["commands"] == 0
    assert coverage["git_ignore"]["unknown_paths"] > 0
    assert coverage["git_ignore"]["status"] == "unavailable"


def test_broken_root_git_marker_is_not_treated_as_unversioned(tmp_path):
    (tmp_path / ".git").write_text("gitdir: missing-git-directory\n")
    (tmp_path / "core.py").write_text("def maintained_code(): return 1\n")
    selected, coverage = discovery._metadata(tmp_path)
    assert selected == []
    assert coverage["git_ignore"]["status"] == "unavailable"
    assert coverage["git_ignore"]["unknown_paths"] == 1


@pytest.mark.skipif(not shutil.which("starforge"), reason="Optional installed Starforge required")
def test_cli_submodule_intake_cache_and_changed_child_policy(navcom, submodule, tmp_path, monkeypatch):
    from test_atlas import add
    root, child = submodule
    monkeypatch.setattr(navcom, "INDEX_READ_ONLY", False)
    index = tmp_path / "index.sqlite"
    conn = navcom.open_index(index)
    add(navcom, conn, tmp_path / "session.jsonl", "calibration product", "parent and engine", str(root))
    conn.close()
    cache = tmp_path / "source-cache"
    cli = Path(__file__).resolve().parents[1] / "navcom.py"
    def run(*arguments):
        result = subprocess.run([sys.executable, str(cli), *map(str, arguments), "--json"],
            capture_output=True, text=True, timeout=45,
            env=dict(os.environ, NAVCOM_STARSHIP_ROOT=str(tmp_path / "no-fleet")))
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)
    first = run("sources", "discover", "--harvest", "--index", index, "--cache", cache)
    assert first["analyzed_sources"] == 1
    cached = run("sources", "discover", "--harvest", "--index", index, "--cache", cache)
    assert cached["cached_sources"] == 1 and cached["analyzed_sources"] == 0
    source = json.loads((cache / "current.json").read_text())["sources"][0]
    assert "engine/visible.py" in source["include"]
    matches = run("sources", "search", "calibration", "--within", source["id"], "--cache", cache)
    assert any("engine/README.md" in json.dumps(hit) for hit in matches["text_hits"])
    # The installed native policy changes what automatic tools harvest; no
    # hand-edited catalog or manually synchronized include list is involved.
    with (child / ".gitignore").open("a") as stream:
        stream.write("visible.py\n")
    changed = run("sources", "discover", "--harvest", "--index", index, "--cache", cache)
    assert changed["analyzed_sources"] == 1
    source = json.loads((cache / "current.json").read_text())["sources"][0]
    assert "engine/visible.py" not in source["include"]
    assert "z-laboratory/later.py" in source["include"]
    assert run("sources", "discover", "--harvest", "--index", index, "--cache", cache)["cached_sources"] == 1
