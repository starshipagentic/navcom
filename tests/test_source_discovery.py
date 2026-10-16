"""Source discovery uses indexed projects, bounded real code and existing scope."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys

import pytest

from navcom_source_discovery import discover


def inventory(monkeypatch, tmp_path, rows, more=False):
    index = tmp_path / "index.sqlite"
    sqlite3.connect(index).close()
    seen = []

    class FakeDiscovery:
        def __init__(self, api):
            pass

        def view(self, conn, params):
            seen.append(params)
            return {"nodes": rows, "more": more, "freshness": {"stale": False}}

    monkeypatch.setattr("navcom_source_discovery.Discovery", FakeDiscovery)
    return index, seen


def test_unfamiliar_monorepo_git_grouping_and_registered_scope(monkeypatch, tmp_path):
    root = tmp_path / "cedar-suite"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    (root / "README.md").write_text("# Cedar suite\n")
    (root / "package.json").write_text(json.dumps({"workspaces": ["apps/*", "packages/*"]}))
    for relative in ("apps/quartz", "apps/topaz", "packages/shared"):
        directory = root / relative
        directory.mkdir(parents=True)
        (directory / "package.json").write_text(json.dumps({"name": relative}))
        (directory / "README.md").write_text("# " + relative)
    (root / "docs").mkdir()
    (root / "docs" / "architecture.md").write_text("Decisions")
    (root / "∑ship.md").write_text("---\nfleets: []\n---\n")
    index, _ = inventory(monkeypatch, tmp_path, [
        {"label": str(root / "apps/quartz"), "collection": "projects:quartz"},
        {"label": str(root), "collection": "projects:cedar"},
        {"label": str(root / "apps/topaz"), "collection": "projects:topaz"},
    ])
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "current.json").write_text(json.dumps({"sources": [{
        "root": str(root), "id": "old", "include": ["apps/quartz/src"],
        "max_files": 500, "max_bytes": 999999, "label": "Cedar", "artifact": "old-cache",
    }]}))
    result = discover(None, index, cache)
    assert len(result["sources"]) == 1
    source = result["sources"][0]
    assert source["id"] == hashlib.sha256(str(root).encode()).hexdigest()[:16]
    assert source["label"] == "Cedar" and source["max_files"] == 500
    assert "apps/quartz/src" in source["include"]
    assert "apps/topaz/package.json" in source["include"]
    assert "packages/shared/README.md" in source["include"]
    assert "docs/architecture.md" in source["include"]
    assert "∑ship.md" in source["include"]
    assert source["conversation_collection"] == "projects:cedar"
    assert source["conversation_collections"] == ["projects:cedar", "projects:quartz", "projects:topaz"]
    assert "artifact" not in source
    assert not (cache / "artifacts").exists()


def test_symlinks_hidden_paths_missing_and_metadata_limits(monkeypatch, tmp_path):
    root = tmp_path / "safe"
    root.mkdir()
    (root / "package.json").write_text(json.dumps({"workspaces": ["*", "../escape"]}))
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "README.md").write_text("Outside material")
    (root / "escape").symlink_to(outside, target_is_directory=True)
    (root / "README.md").symlink_to(outside / "README.md")
    (root / ".private").mkdir()
    (root / ".private" / "package.json").write_text("{}")
    (root / "docs").mkdir()
    (root / "docs" / ".secret.md").write_text("Private")
    (root / "docs" / "oversize.md").write_bytes(b"x" * (1024 * 1024 + 1))
    empty = tmp_path / "empty"
    empty.mkdir()
    index, _ = inventory(monkeypatch, tmp_path, [
        {"label": str(root), "collection": "projects:safe"},
        {"label": str(empty), "collection": "projects:empty"},
        {"label": str(tmp_path / "missing"), "collection": "projects:gone"},
        {"label": "Unknown project", "collection": "projects:unknown"},
    ])
    result = discover(None, index, tmp_path / "cache")
    assert result["sources"][0]["include"] == ["package.json"]
    scope = next(s for s in result["coverage"]["scopes"] if s["root"] == str(root))
    assert {e["path"] for e in scope["excluded"]} >= {"README.md", "escape", ".private", "docs/.secret.md", "docs/oversize.md"}
    assert "unsupported workspace pattern: ../escape" in scope["limits"]
    assert len(result["coverage"]["skipped"]) == 3


def test_pagination_and_collection_scope_are_forwarded(monkeypatch, tmp_path):
    index, seen = inventory(monkeypatch, tmp_path, [], more=True)
    result = discover(None, index, tmp_path / "cache", limit=7, offset=14, within="districts:cedar")
    assert seen[0]["within"] == ["districts:cedar"]
    assert seen[0]["offset"] == ["14"] and seen[0]["limit"] == ["7"]
    assert result["coverage"]["next_offset"] == 21
    assert result["coverage"]["more"] and not result["coverage"]["full_inventory"]
    with pytest.raises(ValueError, match="limit"):
        discover(None, index, tmp_path, limit=201)


def test_toml_declared_members_include_code(monkeypatch, tmp_path):
    pytest.importorskip("tomllib")
    root = tmp_path / "crystal"
    app = root / "components" / "optics"
    app.mkdir(parents=True)
    (root / "pyproject.toml").write_text('[tool.uv.workspace]\nmembers = ["components/*"]\n')
    (app / "pyproject.toml").write_text('[project]\nname = "optics"\n')
    (app / "main.py").write_text("print('optical sensor processing')")
    index, _ = inventory(monkeypatch, tmp_path, [{"label": str(root), "collection": "projects:crystal"}])
    result = discover(None, index, tmp_path / "cache")
    assert result["sources"][0]["include"] == ["components/optics/main.py", "components/optics/pyproject.toml", "pyproject.toml"]


def test_bounded_metadata_reports_omitted_inputs(monkeypatch, tmp_path):
    root = tmp_path / "bounded"
    root.mkdir()
    (root / "README.md").write_text("# Bounded metadata")
    (root / "package.json").write_text("{}")
    monkeypatch.setattr("navcom_source_discovery.MAX_METADATA_FILES", 1)
    index, _ = inventory(monkeypatch, tmp_path, [{"label": str(root), "collection": "projects:bounded"}])
    result = discover(None, index, tmp_path / "cache")
    assert len(result["sources"][0]["include"]) == 1
    assert result["coverage"]["scopes"][0]["limits"] == ["metadata file/byte budget exceeded"]


def test_code_budget_is_fair_deterministic_and_excludes_unsafe_inputs(monkeypatch, tmp_path):
    root = tmp_path / "unfamiliar-suite"
    root.mkdir()
    (root / "package.json").write_text(json.dumps({"workspaces": ["apps/*"]}))
    for name in ("zinnia", "aster"):
        app = root / "apps" / name
        app.mkdir(parents=True)
        (app / "package.json").write_text(json.dumps({"name": name}))
        for i in reversed(range(5)):
            (app / f"sensor{i}.py").write_text(f"def read_sensor_{i}(): return {i}\n")
    outside = tmp_path / "outside.py"
    outside.write_text("SECRET_OUTSIDE = 'never copied'")
    (root / "linked.py").symlink_to(outside)
    for relative in (".env", "credentials.json", "node_modules/not_ours.py", "secrets/private.py",
                     "generated/api.py", ".private/hidden.py", "vendor/a.py", "dist/bundle.js"):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("private or generated")
    (root / "oversized.py").write_bytes(b"x" * (2 * 1024 * 1024 + 1))
    (root / "bundle.min.js").write_text("generated")
    monkeypatch.setattr("navcom_source_discovery.MAX_CODE_FILES", 4)
    index, _ = inventory(monkeypatch, tmp_path, [{"label": str(root), "collection": "projects:suite"}])
    progress = []
    first = discover(None, index, tmp_path / "cache", progress=lambda *event: progress.append(event))
    second = discover(None, index, tmp_path / "cache")
    assert first == second
    source = first["sources"][0]
    code = [path for path in source["include"] if path.endswith(".py")]
    assert code == [f"apps/{app}/sensor{i}.py" for app in ("aster", "zinnia") for i in (0, 1)]
    scope = first["coverage"]["scopes"][0]
    assert scope["code_files"] == 4 and scope["selected_files"] == 7
    assert scope["excluded_counts"]["code file/byte budget"] == 6
    assert "code file/byte budget exceeded" in scope["limits"]
    assert {entry["path"] for entry in scope["excluded"]} >= {"linked.py", "oversized.py", "bundle.min.js", "secrets", "node_modules", ".env", "credentials.json"}
    assert progress == [(1, 1, str(root))]


def test_code_only_repo_and_auto_scope_replacement_preserve_registered_inputs(monkeypatch, tmp_path):
    root = tmp_path / "code-only"
    root.mkdir()
    (root / "sensor.py").write_text("def read_sensor(): return 42\n")
    index, _ = inventory(monkeypatch, tmp_path, [{"label": str(root), "collection": "projects:sensor"}])
    cache = tmp_path / "cache"
    first = discover(None, index, cache)
    assert first["sources"][0]["include"] == ["sensor.py"]
    source = first["sources"][0]
    source["include"].append("custom-notes.txt")
    (root / "custom-notes.txt").write_text("User's manually selected scope")
    cache.mkdir()
    (cache / "current.json").write_text(json.dumps({"sources": [source]}))
    (root / "sensor.py").unlink()
    (root / "optics.py").write_text("def read_optics(): return 42\n")
    second = discover(None, index, cache)["sources"][0]
    assert second["include"] == ["custom-notes.txt", "optics.py"]
    assert second["discovery_include"] == ["optics.py"]


@pytest.mark.skipif(not shutil.which("starforge"), reason="Optional native Starforge required")
def test_native_version_families_sample_fairly_with_ignores_and_explicit_scope(monkeypatch, tmp_path):
    import navcom_source_discovery as discovery
    root = tmp_path / 'unfamiliar-research'
    root.mkdir()
    subprocess.run(['git', 'init', '-q', str(root)], check=True)
    (root / '.gitignore').write_text('ignored.py\nmanual.py\n')
    (root / 'README.md').write_text('# Unfamiliar research\n')
    for version in ['v1', 'v2', 'v3']:
        folder = root / 'engines' / version
        folder.mkdir(parents=True)
        for n in range(8):
            (folder / f'calibration{n}.py').write_text(f'def sensor_{n}(): return {n}\n')
        (folder / 'ignored.py').write_text('private ignored content\n')
    for name in ['exp91', 'exp92']:
        folder = root / 'LABS' / name
        folder.mkdir(parents=True)
        (folder / 'sensor.py').write_text('def separate_experiment(): return 1\n')
    (root / 'manual.py').write_text('Explicitly registered ignored input\n')
    (root / 'engines/v4').symlink_to(root / 'engines/v3', target_is_directory=True)
    monkeypatch.setattr(discovery, 'MAX_CODE_FILES', 8)
    index, _ = inventory(monkeypatch, tmp_path, [dict(label=str(root), collection='projects:research')])
    cache = tmp_path / 'cache'
    cache.mkdir()
    (cache / 'current.json').write_text(json.dumps(dict(sources=[dict(root=str(root), id='old', include=['manual.py'])])))
    first = discover(None, index, cache)
    source = first['sources'][0]
    assert source['discovery_coverage']['version_roots'] == ['engines/v1', 'engines/v2', 'engines/v3']
    assert source['discovery_coverage']['version_sampling']['status'] == 'available'
    assert source['discovery_coverage']['code_files'] == 8
    assert 'manual.py' in source['include'] and 'manual.py' not in source['discovery_include']
    for version in ['v1', 'v2', 'v3']:
        assert len([path for path in source['discovery_include'] if path.startswith('engines/' + version + '/')]) == 2
    assert not any('ignored.py' in path or '/v4/' in path for path in source['discovery_include'])
    assert discover(None, index, cache) == first
    assert list((cache / 'discovery-families').glob('*.json'))


def test_native_family_unavailable_preserves_existing_sampling_and_discloses(monkeypatch, tmp_path):
    import navcom_source_discovery as discovery
    root = tmp_path / 'unavailable-families'
    for version in ['v1', 'v2']:
        folder = root / 'engine' / version
        folder.mkdir(parents=True)
        (folder / 'main.py').write_text('def retained(): return 1\n')
    monkeypatch.setattr('navcom_native_families.analyze', lambda *a: dict(status='unavailable', families=[],
        omitted=['Native version-family sampling unavailable; existing app sampling retained.']))
    selected, coverage = discovery._metadata(root)
    assert selected == ['engine/v1/main.py', 'engine/v2/main.py']
    assert coverage['version_roots'] == [] and coverage['version_sampling']['status'] == 'unavailable'
    assert 'Native version-family sampling unavailable' in coverage['limits'][0]


@pytest.mark.skipif(not shutil.which('starforge'), reason='Optional native Starforge required')
def test_public_cli_native_version_sampling_and_repeat_cache(navcom, tmp_path, monkeypatch):
    from test_atlas import add
    monkeypatch.setattr(navcom, 'INDEX_READ_ONLY', False)
    root = tmp_path / 'unfamiliar-calibration-family'
    root.mkdir()
    subprocess.run(['git', 'init', '-q', str(root)], check=True)
    (root / 'README.md').write_text('# Calibration family\n')
    for version in ['v1', 'v2', 'v3']:
        folder = root / 'engine' / version
        folder.mkdir(parents=True)
        for number in range(200):
            (folder / f'sensor_{number:03}.py').write_text(f'def observed_{number}(): return {number}\n')
    index = tmp_path / 'index.sqlite'
    conn = navcom.open_index(index)
    add(navcom, conn, tmp_path / 'session.jsonl', 'Calibration versions', 'sensor experiments', str(root))
    conn.close()
    cache = tmp_path / 'sources'
    command = [sys.executable, str(Path(__file__).resolve().parents[1] / 'navcom.py'), 'sources',
        'discover', '--harvest', '--index', str(index), '--cache', str(cache), '--json']
    first = subprocess.run(command, capture_output=True, text=True, timeout=30)
    assert first.returncode == 0, first.stderr
    result = json.loads(first.stdout)
    assert result['analyzed_sources'] == 1
    source = json.loads((cache / 'current.json').read_text())['sources'][0]
    assert source['discovery_coverage']['code_files'] == 400
    counts = [sum(path.startswith('engine/' + version + '/') for path in source['discovery_include'])
              for version in ['v1', 'v2', 'v3']]
    assert min(counts) >= 133 and max(counts) - min(counts) <= 1
    repeated = subprocess.run(command, capture_output=True, text=True, timeout=30)
    assert repeated.returncode == 0, repeated.stderr
    data = json.loads(repeated.stdout)
    assert data['analyzed_sources'] == 0 and data['cached_sources'] == 1


def test_byte_depth_entry_and_registered_limits_are_disclosed(monkeypatch, tmp_path):
    import navcom_source_discovery as discovery
    root = tmp_path / "bounded-code"
    deep = root / "one" / "two" / "three"
    deep.mkdir(parents=True)
    (root / "a.py").write_text("x" * 9)
    (root / "b.py").write_text("x" * 9)
    (deep / "deep.py").write_text("x")
    monkeypatch.setattr(discovery, "MAX_CODE_BYTES", 10)
    monkeypatch.setattr(discovery, "MAX_DEPTH", 1)
    selected, scope = discovery._metadata(root)
    assert selected == ["a.py"]
    assert scope["limits"] == ["code depth budget exceeded", "code file/byte budget exceeded"]
    assert scope["code_bytes"] == 9
    monkeypatch.setattr(discovery, "MAX_ENTRIES", 1)
    selected, scope = discovery._metadata(root)
    assert selected == []  # No arbitrary readdir-order subset of an oversized directory.
    assert "directory entry budget exceeded" in scope["limits"]
    monkeypatch.setattr(discovery, "MAX_ENTRIES", 100)
    monkeypatch.setattr(discovery, "MAX_CODE_BYTES", 100)
    selected, scope = discovery._metadata(root, max_files=1)
    assert selected == ["a.py"] and "registered source file/byte budget exceeded" in scope["limits"]


def test_native_git_ignore_large_tracked_core_and_explicit_scope(monkeypatch, tmp_path):
    root = tmp_path / "unfamiliar-instrument"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    (root / ".gitignore").write_text("experiments/copied-material/\n*.py\n!ordinary.py\n")
    (root / "core.py").write_text("# Large maintained core\n" + "# implementation detail\n" * 26000)
    subprocess.run(["git", "-C", str(root), "add", "-f", "core.py"], check=True)
    (root / "ordinary.py").write_text("def measure_sensor(): return 42\n")
    copied = root / "experiments" / "copied-material"
    copied.mkdir(parents=True)
    (copied / "README.md").write_text("Private duplicate context")
    (copied / "copied.py").write_text("def copied_measurement(): return 42\n")
    explicit = root / "manual.py"
    explicit.write_text("Explicitly requested ignored input")
    index, _ = inventory(monkeypatch, tmp_path, [{"label": str(root), "collection": "projects:instrument"}])
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "current.json").write_text(json.dumps({"sources": [{"id": "old", "root": str(root), "include": ["manual.py", "experiments/copied-material"]}]}))
    result = discover(None, index, cache)
    source = result["sources"][0]
    assert source["discovery_include"] == ["core.py", "ordinary.py"]
    assert set(source["include"]) == {"core.py", "ordinary.py", "manual.py", "experiments/copied-material"}
    scope = source["discovery_coverage"]
    assert scope["code_bytes"] > 500000 and scope["git_ignore"]["status"] == "available"
    assert scope["git_ignore"]["ignored_paths"] >= 2
    assert {row["path"] for row in scope["excluded"] if row["reason"] == "Git ignored automatic input"} >= {"manual.py", "experiments/copied-material"}
    assert discover(None, index, cache) == result


def test_git_ignore_unavailable_is_disclosed_and_unchecked_auto_paths_omitted(monkeypatch, tmp_path):
    import navcom_source_discovery as discovery
    root = tmp_path / "git-failed"
    root.mkdir()
    (root / "core.py").write_text("def core(): return 1\n")
    original = discovery.subprocess.Popen
    def fail_ignore(argv, **kwargs):
        if "check-ignore" in argv:
            raise subprocess.TimeoutExpired(argv, 2)
        return original(argv, **kwargs)
    monkeypatch.setattr(discovery.subprocess, "Popen", fail_ignore)
    selected, scope = discovery._metadata(root)
    assert selected == []
    assert scope["git_ignore"]["status"] == "unavailable"
    assert "Git ignore policy unavailable; unchecked automatic paths omitted" in scope["limits"]


def test_streaming_native_git_is_reused_and_handles_negations_and_tracked_files(tmp_path):
    import navcom_source_discovery as discovery
    root = tmp_path / "dense-research"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    (root / ".gitignore").write_text("*.py\n!allowed.py\n")
    (root / "tracked.py").write_text("def observed(): return 1\n")
    subprocess.run(["git", "-C", str(root), "add", "-f", "tracked.py"], check=True)
    for i in range(40):
        folder = root / f"nested-{i:02}"
        folder.mkdir()
        (folder / "allowed.py").write_text("def measured(): return 1\n")
        (folder / "omitted.py").write_text("Should remain ignored")
    selected, scope = discovery._metadata(root)
    assert selected == [f"nested-{i:02}/allowed.py" for i in range(40)] + ["tracked.py"]
    assert scope["git_ignore"]["commands"] == 1
    assert scope["git_ignore"]["status"] == "available"
    assert scope["git_ignore"]["ignored_paths"] == 40
    assert not scope["limits"]


def test_unsupported_assets_do_not_consume_native_ignore_queries(tmp_path):
    import navcom_source_discovery as discovery
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_text("*.png\nignored.py\n")
    for i in range(100):
        (tmp_path / f"image-{i:03}.png").write_bytes(b"asset")
    (tmp_path / "README.md").write_text("# Usable source\n")
    (tmp_path / "main.py").write_text("def usable(): return 1\n")
    (tmp_path / "ignored.py").write_text("private omitted code\n")
    selected, scope = discovery._metadata(tmp_path)
    assert selected == ["README.md", "main.py"]
    assert scope["git_ignore"]["checked_paths"] == 3
    assert scope["git_ignore"]["ignored_paths"] == 1
    assert scope["git_ignore"]["commands"] == 1
    assert not scope["limits"]


def test_streaming_native_git_large_batch_does_not_deadlock_and_preserves_paths(tmp_path):
    import navcom_source_discovery as discovery
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_text("*.py\n!folder/0001*\n")
    names = [f"folder/{i:04}-" + "x" * 75 + ".py" for i in range(4000)]
    payload = b"".join(os.fsencode(name) + b"\0" for name in names)
    assert len(payload) > 256 * 1024
    with discovery._GitIgnore(tmp_path) as policy:
        ignored = policy.check(payload, 2)
        assert len(ignored) == 3999 and os.fsencode(names[1]) not in ignored
        unusual = "space and\nnewline.py"
        assert policy.check(os.fsencode(unusual) + b"\0", 2) == {os.fsencode(unusual)}
        assert policy.starts == 1
        process = policy.process
    assert process.poll() is not None


def test_streaming_native_git_output_budget_closes_process(tmp_path, monkeypatch):
    import navcom_source_discovery as discovery
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_text("*" * 300 + ".py\n")
    monkeypatch.setattr(discovery, "MAX_IGNORE_BATCH_BYTES", 64)
    with pytest.raises(ValueError, match="response exceeds"):
        with discovery._GitIgnore(tmp_path) as policy:
            policy.check(b"core.py\0", 2)
    assert policy.process.poll() is not None


def test_pinned_project_page_uses_same_intake_without_reading_index(tmp_path, monkeypatch):
    import navcom_source_discovery as discovery
    root = tmp_path / "unfamiliar-pinned-product"
    root.mkdir()
    (root / "README.md").write_text("# Pinned product\n")
    (root / "instrument.py").write_text("def measure(): return 1\n")
    monkeypatch.setattr(discovery, "Discovery", lambda *_: pytest.fail("Pinned intake re-read changing inventory"))
    result = discover(None, None, tmp_path / "cache", limit=4, offset=12,
                      projects=[dict(label=str(root), collection="projects:pinned", ignored_extra="not a classification")])
    assert result["sources"][0]["include"] == ["README.md", "instrument.py"]
    assert result["sources"][0]["conversation_collections"] == ["projects:pinned"]
    assert result["coverage"]["offset"] == 12
    assert result["coverage"]["selection_input"] == "pinned_project_page"
    assert not result["coverage"]["full_inventory"]
    assert result["coverage"]["next_offset"] is None  # The pinned session owns its cursor.
    with pytest.raises(ValueError, match="at most"):
        discover(None, None, tmp_path / "cache", limit=1, projects=[dict(label=str(root))] * 2)
    with pytest.raises(ValueError, match="collection"):
        discover(None, None, tmp_path / "cache", projects=[dict(label=str(root), collection=["invalid"])])


def test_pinned_inventory_groups_native_git_roots_and_keeps_all_associations(tmp_path):
    from navcom_source_discovery import group_projects
    root = tmp_path / "unfamiliar-suite"
    app = root / "apps" / "studio"
    app.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    (root / "README.md").write_text("# Studio suite\n")
    (app / "main.py").write_text("def measure(): return 2\n")
    nested = app / "independent"
    nested.mkdir()
    subprocess.run(["git", "init", "-q", str(nested)], check=True)
    nodes = [dict(label=str(path), collection="projects:" + name) for path, name in
             [(root, "suite"), (app, "studio"), (nested, "independent"), (tmp_path / "missing", "missing")]]
    plan = group_projects(nodes)
    assert [job["root"] for job in plan["jobs"]] == [str(root), str(nested), str(tmp_path / "missing")]
    assert plan["jobs"][0]["projects"] == nodes[:2]
    source = discover(None, None, tmp_path / "cache", projects=plan["jobs"][0]["projects"],
                      project_boundaries=nodes)["sources"][0]
    assert source["conversation_collections"] == ["projects:studio", "projects:suite"]
    assert source["conversation_collection"] == "projects:suite"
    assert plan["coverage"]["inventory_rows"] == 4 and not plan["coverage"]["split_groups"]


def test_pinned_group_overflow_is_split_without_dropping_projects(tmp_path):
    from navcom_source_discovery import group_projects
    nodes = [dict(label=str(tmp_path), collection=f"projects:{i}") for i in range(201)]
    plan = group_projects(nodes)
    assert [len(job["projects"]) for job in plan["jobs"]] == [200, 1]
    assert [node for job in plan["jobs"] for node in job["projects"]] == nodes
    assert plan["coverage"]["split_groups"] == [dict(root=str(tmp_path), projects=201, jobs=2)]
    with pytest.raises(ValueError, match="at most 2000"):
        group_projects(nodes * 10)


def test_container_keeps_own_docs_and_explicit_scope_but_delegates_child_projects(tmp_path):
    root = tmp_path / "work-area"
    indexed = root / "unversioned-product"
    nested = root / "team" / "repository"
    copied = root / "copied-product"
    indexed.mkdir(parents=True); nested.mkdir(parents=True); copied.mkdir()
    (copied / "package.json").write_text(json.dumps(dict(name="copied-product")))
    subprocess.run(["git", "init", "-q", str(nested)], check=True)
    (root / "README.md").write_text("# Work-area context\n")
    (root / "own.py").write_text("def own(): return 1\n")
    (root / "docs").mkdir()
    (root / "docs" / "strategy.md").write_text("Cross-project strategy\n")
    for child in (indexed, nested, copied):
        (child / "README.md").write_text("# Separately owned child\n")
        (child / "main.py").write_text("def child(): return 2\n")
    nodes = [dict(label=str(path), collection="projects:" + path.name) for path in (root, indexed)]
    cache = tmp_path / "cache"; cache.mkdir()
    (cache / "current.json").write_text(json.dumps(dict(sources=[dict(root=str(root),
        include=["unversioned-product/README.md", "team/repository/main.py"],
        discovery_include=["unversioned-product/README.md"])])))
    result = discover(None, None, cache, projects=nodes[:1], project_boundaries=nodes)
    source = result["sources"][0]
    assert source["discovery_include"] == ["README.md", "docs/strategy.md", "own.py"]
    assert "team/repository/main.py" in source["include"]  # Explicit user scope survives.
    scope = source["discovery_coverage"]
    assert scope["container_policy"]["enabled"]
    assert scope["container_policy"]["indexed_boundaries"] == ["unversioned-product"]
    excluded = {row["path"]: row["reason"] for row in scope["excluded"]}
    assert excluded["unversioned-product"] == "indexed child project delegated to its own source"
    assert excluded["team/repository"] == "nested Git repository omitted from container scope"
    assert excluded["copied-product"] == "nested product manifest omitted from container scope"


@pytest.mark.parametrize("declaration", ["git", "manifest"])
def test_real_repository_or_manifest_preserves_indexed_descendant_scope(tmp_path, declaration):
    root = tmp_path / "declared-suite"
    child = root / "apps" / "desk"
    child.mkdir(parents=True)
    (child / "main.py").write_text("def desk(): return 1\n")
    if declaration == "git":
        subprocess.run(["git", "init", "-q", str(root)], check=True)
    else:
        (root / "package.json").write_text(json.dumps(dict(name="declared-suite", workspaces=["apps/*"])))
    nodes = [dict(label=str(path)) for path in (root, child)]
    result = discover(None, None, tmp_path / "cache", projects=nodes[:1], project_boundaries=nodes)
    assert "apps/desk/main.py" in result["sources"][0]["include"]
    assert not result["sources"][0]["discovery_coverage"]["container_policy"]["enabled"]


@pytest.mark.parametrize("project,readme,charter", [
    ("tidal-instrument", "README.md", "SOUL.md"),
    ("canopy-observer", "ReadMe.agent.MD", "soul.md"),
])
def test_nested_expertise_docs_share_existing_safe_intake(monkeypatch, tmp_path, project, readme, charter):
    root = tmp_path / project
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    (root / ".gitignore").write_text("workers/copied-context/\n")
    files = {
        "workers/resident/" + readme: "# Maintained measurements\nInspect evidence and document uncertainty.\n",
        "workers/resident/home/" + charter: "# Charter\nMaintain this domain's measured evidence.\n",
        "workers/resident/agent.py": "def inspect_measurement(): return 1\n",
        "workers/resident/config.yaml": "api_key: CONFIG_SENTINEL\n",
        "workers/resident/compose.yaml": "environment: INLINE_SECRET_SENTINEL\n",
        "workers/resident/.private/SOUL.md": "PRIVATE_SENTINEL",
        "workers/resident/secrets/README.md": "PRIVATE_SENTINEL",
        "workers/copied-context/README.md": "IGNORED_SENTINEL",
        "workers/copied-context/home/SOUL.md": "IGNORED_SENTINEL",
    }
    for relative, body in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
    index, _ = inventory(monkeypatch, tmp_path, [{"label": str(root), "collection": "projects:worker"}])
    result = discover(None, index, tmp_path / "cache")
    source = result["sources"][0]
    assert set(source["include"]) == {"workers/resident/" + readme, "workers/resident/home/" + charter,
                                      "workers/resident/agent.py"}
    scope = source["discovery_coverage"]
    assert scope["metadata_files"] == 2 and scope["code_files"] == 1
    assert scope["git_ignore"]["status"] == "available"
    excluded = {row["path"]: row["reason"] for row in scope["excluded"]}
    assert excluded["workers/copied-context"] == "Git ignored automatic input"
    assert excluded["workers/resident/.private"] == "hidden, secret or generated path"
    assert excluded["workers/resident/config.yaml"] == "not an automatic code or metadata input"
    assert excluded["workers/resident/compose.yaml"] == "not an automatic code or metadata input"
    assert discover(None, index, tmp_path / "cache") == result


def test_nested_expertise_docs_use_metadata_budget_and_workspace_round_robin(monkeypatch, tmp_path):
    import navcom_source_discovery as discovery
    root = tmp_path / "measurement-suite"
    root.mkdir()
    (root / "package.json").write_text(json.dumps({"workspaces": ["apps/*"]}))
    for name in ("coast", "forest"):
        app = root / "apps" / name
        (app / "resident" / "home").mkdir(parents=True)
        (app / "package.json").write_text(json.dumps({"name": name}))
        (app / "resident" / "README.md").write_text("Maintained observations")
        (app / "resident" / "home" / "SOUL.md").write_text("Evidence charter")
    # Three workspace manifests plus one nested README from each app fit. Both
    # later charters are omitted explicitly, without the first app taking both.
    monkeypatch.setattr(discovery, "MAX_METADATA_FILES", 5)
    selected, scope = discovery._metadata(root)
    assert {path for path in selected if path.endswith("README.md")} == {
        "apps/coast/resident/README.md", "apps/forest/resident/README.md"}
    assert not any(path.endswith("SOUL.md") for path in selected)
    assert scope["metadata_files"] == 5 and scope["code_files"] == 0
    assert scope["excluded_counts"]["metadata file/byte budget"] == 2
    assert "metadata file/byte budget exceeded" in scope["limits"]


@pytest.mark.skipif(not shutil.which("starforge"), reason="Optional installed Starforge required")
@pytest.mark.parametrize("declared_workspace", [True, False])
def test_fresh_cli_discovery_harvest_groups_both_search_paths_and_cache(navcom, tmp_path, monkeypatch, declared_workspace):
    """No hand-curated includes: an unfamiliar suite becomes navigable from its index."""
    from test_atlas import add
    monkeypatch.setattr(navcom, "INDEX_READ_ONLY", False)
    root = tmp_path / "clients" / "Juniper" / "Optical-suite"
    root.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    metadata = {"name": "optics"}
    if declared_workspace:
        metadata["workspaces"] = ["apps/*"]
    (root / "package.json").write_text(json.dumps(metadata))
    (root / "README.md").write_text("# Optical suite\nCoordinate optical instrument campaigns.\n")
    code = '\n'.join(['"""Marmot sensor authentication and optical calibration policy orchestration."""',
                      'def marmot_calibration(sensor, instrument, campaign, policy, authentication, measurement):'] +
                    [f'    calibration_step_{i} = sensor + instrument + campaign + policy + authentication + measurement + {i}' for i in range(24)] +
                    ['    return calibration_step_23', '', 'class OpticalInstrument:',
                     '    def read_sensor(self): return self.measurement',
                     '    def calibrate_measurement(self): return self.calibration_policy',
                     '    def authorize_campaign(self): return self.authentication_policy',
                     '    def measure_spectrum(self): return self.optical_campaign', ''])
    for name in ("Prism", "Spectra"):
        app = root / "apps" / name
        app.mkdir(parents=True)
        (app / "package.json").write_text(json.dumps({"name": name, "scripts": {"start": "python sensor.py"}}))
        (app / "README.md").write_text(f"# {name}\nMarmot instrument measurements and optical calibration.\n")
        (app / "sensor.py").write_text(code)
        (app / "calibration.py").write_text(code)
    (root / "docs").mkdir()
    (root / "docs" / "decisions.md").write_text("Marmot uses quartz prisms; docs-only spectroscopy note.\n")
    index = tmp_path / "index.sqlite"
    conn = navcom.open_index(index)
    for name in ("Prism", "Spectra"):
        add(navcom, conn, tmp_path / f"{name}.jsonl", f"{name} marmot calibration", "instrument policy", str(root / "apps" / name))
    conn.close()
    source_cache, space_cache = tmp_path / "sources", tmp_path / "space.json"
    cli = Path(__file__).resolve().parents[1] / "navcom.py"
    env = dict(os.environ, NAVCOM_STARSHIP_ROOT=str(tmp_path / "no-fleet"))
    env.pop("NAVCOM_FLEET_SNAPSHOT", None)
    env.pop("NAVCOM_FLEET_CONFIG", None)
    def run(*args):
        completed = subprocess.run([sys.executable, str(cli), *map(str, args), "--json"], env=env,
                                   text=True, capture_output=True, timeout=60)
        assert completed.returncode == 0, completed.stderr
        return json.loads(completed.stdout)
    harvest = run("sources", "discover", "--harvest", "--index", index, "--cache", source_cache)
    assert harvest["analyzed_sources"] == 1
    assert harvest["discovery_coverage"]["scopes"][0]["code_files"] == 4
    cached = run("sources", "discover", "--harvest", "--index", index, "--cache", source_cache)
    assert cached["analyzed_sources"] == 0 and cached["cached_sources"] == 1
    state = json.loads((source_cache / "current.json").read_text())
    source = state["sources"][0]
    structure = json.loads((Path(source["artifact"]) / "structure.json").read_text())
    assert {candidate["root"] for candidate in structure["application_candidates"]} == {"apps/Prism", "apps/Spectra"}
    assert len(structure["token_groups"]) == 2  # Identical code cannot bridge two declared products.
    assert {g["application_root"] for g in structure["token_groups"]} == {"apps/Prism", "apps/Spectra"}
    run("atlas", "refresh", "--space", "--index", index, "--source-cache", source_cache, "--space-cache", space_cache)
    planets = run("atlas", "list", "planets", "--index", index, "--source-cache", source_cache, "--space-cache", space_cache)
    prism = next(n for n in planets["nodes"] if n["label"] == "Prism")
    districts = run("atlas", "list", "cities", "--within", prism["id"], "--index", index,
                    "--source-cache", source_cache, "--space-cache", space_cache)
    assert districts["total"] == 1
    district = districts["nodes"][0]
    assert district["conversation_basis"]["type"] == "project_query_context"
    native = run("sources", "search", "marmot", "--within", source["id"], "--cache", source_cache,
                 "--path", "apps/Prism")
    assert native["concept_hits"] and native["text_hits"]
    assert all("apps/Prism" in json.dumps(hit) for hit in native["text_hits"])
    docs = run("sources", "search", "docs-only spectroscopy", "--within", source["id"], "--cache", source_cache)
    assert docs["text_hits"]
    evidence = run("atlas", "search", "marmot", "--space", "--evidence", "--within", district["id"],
                   "--index", index, "--source-cache", source_cache, "--space-cache", space_cache)
    assert evidence["evidence"]["conversations"]
    assert all(hit["project"] == str(root / "apps" / "Prism") for hit in evidence["evidence"]["conversations"])
    assert evidence["evidence"]["sources"]


def test_nested_manifests_without_workspaces_balance_code_and_keep_ignore_boundaries(tmp_path, monkeypatch):
    import navcom_source_discovery as discovery
    root = tmp_path / "unfamiliar-suite"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    (root / "package.json").write_text('{"name":"suite"}')
    (root / ".gitignore").write_text("copied/\n")
    for name in ("apps/cobalt", "apps/helium", "copied/other", ".private/hidden"):
        app = root / name
        app.mkdir(parents=True)
        (app / "package.json").write_text(json.dumps({"name": name, "scripts": {"start": "arbitrary command never run"}}))
        for number in range(8):
            (app / f"module{number}.py").write_text("def instrument(): return 'calibration'\n")
    monkeypatch.setattr(discovery, "MAX_CODE_FILES", 4)
    selected, coverage = discovery._metadata(root)
    assert coverage["application_roots"] == ["."]
    assert coverage["manifest_roots"] == [".", "apps/cobalt", "apps/helium"]
    assert {path for path in selected if path.endswith("package.json")} == {
        "package.json", "apps/cobalt/package.json", "apps/helium/package.json"}
    assert [path for path in selected if path.endswith(".py")] == [
        f"apps/{name}/module{i}.py" for name in ("cobalt", "helium") for i in (0, 1)]
    assert coverage["excluded_counts"]["code file/byte budget"] == 12
    assert "code file/byte budget exceeded" in coverage["limits"]
    assert discovery._metadata(root) == (selected, coverage)
