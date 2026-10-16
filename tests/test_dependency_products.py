"""Native dependency evidence qualifies products without hiding retained code."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

import navcom_space as space
from test_space import API, database, git, package, source_cache


ROOT = Path(__file__).resolve().parents[1]


def dependency_candidate(relative, name, **extra):
    return dict(root=relative, manifest=relative + "/package.json", name=name,
                entry_points=[dict(type="npm-script", name="npm run start", file="package.json")],
                dependency_evidence=[dict(type="declared_dependency", package=name,
                    declaring_manifest="package.json", candidate_manifest=relative + "/package.json",
                    relationship="nonlocal_package_dependency")], **extra)


@pytest.fixture(autouse=True)
def isolated_native_context(tmp_path, monkeypatch):
    monkeypatch.setenv("NAVCOM_STARSHIP_ROOT", str(tmp_path / "no-fleet"))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "no-hermes"))
    monkeypatch.delenv("NAVCOM_FLEET_SNAPSHOT", raising=False)
    monkeypatch.delenv("NAVCOM_FLEET_CONFIG", raising=False)


def test_dependency_components_preserve_declared_and_independent_products(tmp_path):
    root = git(tmp_path / "clients" / "Zephyr" / "campaign")
    package(root, name="campaign", workspaces=["apps/declared"])
    candidates = []
    for name in ("component", "declared", "private", "separate"):
        path = package(root / "apps" / name, name=name, scripts={"start": "not executed"})
        if name == "separate":
            git(path)
        candidates.append(dependency_candidate("apps/" + name, name,
            local_declaration="private_package" if name == "private" else ""))
    cache = source_cache(tmp_path, [root])
    (cache / "artifacts" / "0" / "structure.json").write_text(json.dumps(dict(
        application_candidates=candidates, token_groups=[])))
    chart = space.refresh(API, None, tmp_path / "space.json", source_cache=cache)
    planets = {node["label"]: node for node in chart["entities"] if node["kind"] == "planet"}
    assert "component" not in planets
    assert {"campaign", "declared", "private", "separate"} <= planets.keys()
    assert planets["separate"]["source_scopes"] == [dict(source_id="0", paths=["apps/separate"])]
    skipped = chart["coverage"]["native_applications"]["dependency_components"]
    assert {row["label"] for row in skipped} == {"component", "declared"}
    # Declared workspace detection can restore a native candidate from a source
    # harvested explicitly without automatic discovery workspace metadata.
    assert any(row["type"] == "workspace_application" for row in planets["declared"]["evidence"])


@pytest.mark.skipif(not shutil.which("starforge"), reason="Optional installed Starforge required")
def test_public_cli_native_dependency_evidence_keeps_source_search_and_cache(navcom, tmp_path, monkeypatch):
    from test_atlas import add
    monkeypatch.setattr(navcom, "INDEX_READ_ONLY", False)
    root = git(tmp_path / "clients" / "Aster" / "instrument-suite")
    dependencies = {"moth-ui": "^2.0.0", "docs-kit": "https://reader:SECRET_SENTINEL@example.test/package.tgz",
                    "local-desk": "workspace:*", "file-desk": "file:./apps/file-desk",
                    "private-desk": "1.0.0", "declared-desk": "1.0.0", "git-desk": "1.0.0"}
    package(root, name="instruments", dependencies=dependencies, workspaces=["apps/declared-desk"])
    (root / "README.md").write_text("# Instrument suite\nAster optical instrument products.\n")
    code = '\n'.join(['"""Marmot optical calibration policy and sensor authentication."""',
        'def marmot_calibration(sensor, instrument, campaign, policy, authentication, measurement):'] +
        [f'    calibration_{i} = sensor + instrument + campaign + policy + authentication + measurement + {i}' for i in range(24)] +
        ['    return calibration_23', '', 'class OpticalInstrument:',
         '    def read_sensor(self): return self.measurement',
         '    def calibrate_measurement(self): return self.calibration_policy',
         '    def authorize_campaign(self): return self.authentication_policy',
         '    def measure_spectrum(self): return self.optical_campaign', ''])
    for name in dependencies:
        path = package(root / "apps" / name, name=name, scripts={"start": "do not execute"},
                       **({"private": True} if name == "private-desk" else {}))
        (path / "README.md").write_text(f"# {name}\nMarmot optical reference retained within its owning product.\n")
        (path / "sensor.py").write_text(code)
        if name == "git-desk":
            git(path)
    index = tmp_path / "index.sqlite"
    conn = navcom.open_index(index)
    add(navcom, conn, tmp_path / "session.jsonl", "Instrument suite", "calibration", str(root))
    conn.close()
    source_cache_path, chart_cache = tmp_path / "sources", tmp_path / "space.json"
    def call(*args):
        result = subprocess.run([sys.executable, str(ROOT / "navcom.py"), *map(str, args), "--json"],
            capture_output=True, text=True, timeout=60, env=os.environ.copy())
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)
    first = call("sources", "discover", "--harvest", "--index", index, "--cache", source_cache_path)
    assert first["analyzed_sources"] == 1
    state = json.loads((source_cache_path / "current.json").read_text())
    source = state["sources"][0]
    structure = json.loads((Path(source["artifact"]) / "structure.json").read_text())
    native = {candidate["name"]: candidate for candidate in structure["application_candidates"]}
    assert native["moth-ui"]["dependency_evidence"][0]["engine"] == "starforge.dep_conflicts.extract_versioned_deps"
    assert native["docs-kit"]["dependency_evidence"]
    assert not native["local-desk"]["dependency_evidence"]
    assert not native["file-desk"]["dependency_evidence"]
    assert native["declared-desk"]["local_declaration"] == "workspace_member"
    assert native["private-desk"]["local_declaration"] == "private_package"
    assert "SECRET_SENTINEL" not in json.dumps(structure)
    repeated = call("sources", "discover", "--harvest", "--index", index, "--cache", source_cache_path)
    assert repeated["analyzed_sources"] == 0 and repeated["cached_sources"] == 1
    call("atlas", "refresh", "--space", "--index", index, "--source-cache", source_cache_path, "--space-cache", chart_cache)
    listed = call("atlas", "list", "planets", "--space-cache", chart_cache, "--limit", 100)
    names = {node["label"] for node in listed["nodes"]}
    assert "moth-ui" not in names and "docs-kit" not in names
    assert {"local-desk", "file-desk", "private-desk", "declared-desk", "git-desk"} <= names
    matches = call("sources", "search", "marmot", "--within", source["id"], "--path", "apps/moth-ui", "--cache", source_cache_path)
    assert matches["concept_hits"] and matches["text_hits"]
    assert all(hit["relative_path"].startswith("apps/moth-ui/") for hit in matches["concept_hits"] + matches["text_hits"])
    assert "SECRET_SENTINEL" not in chart_cache.read_text()
    # Ordinary tools recompute changed declarations; no chart/profile syncing.
    manifest = json.loads((root / "package.json").read_text())
    manifest["dependencies"].pop("moth-ui")
    (root / "package.json").write_text(json.dumps(manifest))
    changed = call("sources", "discover", "--harvest", "--index", index, "--cache", source_cache_path)
    assert changed["analyzed_sources"] == 1
    call("atlas", "refresh", "--space", "--index", index, "--source-cache", source_cache_path, "--space-cache", chart_cache)
    updated = call("atlas", "list", "planets", "--space-cache", chart_cache, "--limit", 100)
    assert "moth-ui" in {node["label"] for node in updated["nodes"]}
