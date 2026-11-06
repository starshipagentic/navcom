"""CLI and browser share full-fleet berths even when only a page is returned."""
import copy
import json
from pathlib import Path
import subprocess
import sys

import navcom_space
from navcom_web import WebApp


def fleet_chart(tmp_path):
    def node(identity, kind, label, parent, **extra):
        return dict(id=identity, kind=kind, label=label, parent_id=parent,
                    locations=[], evidence=[], examples=[], source_ids=[],
                    source_scopes=[], conversation_collections=[],
                    position={"x": len(identity), "y": len(label)}, **extra)
    nodes = [node("galaxy:owner", "galaxy", "Your galaxy", None),
             node("base:one", "starbase", "Test base", "galaxy:owner"),
             node("system:orchard", "system", "Orchard", "galaxy:owner"),
             node("product:orchard", "planet", "Orchard app", "system:orchard")]
    nodes += [node(f"ship:{i:03}", "ship", f"Vessel {i:03}", "base:one",
                   source_roots=[f"/work/source-{i}"]) for i in range(107)]
    # Product association applies to the whole family, regardless of page order.
    edges = [dict(source=f"ship:{i:03}", target="product:orchard", relation="relates_to",
                  evidence={"type": "fleet_source_reference"}) for i in range(25)]
    nodes.append(node("archive:one", "ship", "Stored elsewhere", "galaxy:owner", form="archive"))
    data = dict(schema_version=1, published=123, entities=nodes, edges=edges, coverage={})
    path = tmp_path / "space.json"
    path.write_text(json.dumps(data))
    return path, data


def test_pages_search_and_cli_keep_the_full_fleet_partition(tmp_path, monkeypatch):
    path, catalog = fleet_chart(tmp_path)
    original = copy.deepcopy(catalog)
    first = navcom_space.view(path, action="explore", within="base:one", limit=80)
    last = navcom_space.view(path, action="explore", within="base:one", limit=80, offset=80)
    assert first["total"] == last["total"] == 107
    assert len(first["nodes"]) == 80 and len(last["nodes"]) == 27
    ids = [n["id"] for n in first["nodes"] + last["nodes"]]
    assert len(set(ids)) == 107 and "archive:one" not in ids
    full = first["fleet_layout"]["assignments"]
    assert full == last["fleet_layout"]["assignments"]
    assert [g["members"] for g in first["fleet_layout"]["groups"]] == [
        g["members"] for g in last["fleet_layout"]["groups"]]
    assert sum(g["visible_count"] for g in first["fleet_layout"]["groups"]) == 80
    assert sum(g["visible_count"] for g in last["fleet_layout"]["groups"]) == 27
    search = navcom_space.view(path, action="search", within="base:one", query="Vessel 099")
    assert [n["id"] for n in search["nodes"]] == ["ship:099"]
    assert search["nodes"][0]["berth"] == full["ship:099"]
    assert search["fleet_layout"]["assignments"] == full
    assert sum(g["matched_count"] for g in search["fleet_layout"]["groups"]) == 1
    assert json.loads(path.read_text()) == original  # Reading never rewrites the saved chart.

    monkeypatch.setenv("NAVCOM_SPACE_CACHE", str(path))
    app = WebApp(None, tmp_path / "unused.sqlite")
    api = app.get(None, "/api/space", dict(action=["explore"], within=["base:one"], limit=["80"]))
    assert api["fleet_layout"] == first["fleet_layout"]
    root = Path(__file__).resolve().parents[1]
    command = [sys.executable, str(root / "navcom.py"), "atlas", "list", "ships", "--within", "base:one",
               "--limit", "80", "--space-cache", str(path), "--index", str(tmp_path / "unused.sqlite")]
    result = subprocess.run(command + ["--json"], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    cli = json.loads(result.stdout)
    assert cli["fleet_layout"] == first["fleet_layout"]
    assert [n["id"] for n in cli["nodes"]] == ids[:80]
    result = subprocess.run(command, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert "Berth:" in result.stdout and "Orchard" in result.stdout
    assert not (tmp_path / "unused.sqlite").exists()
