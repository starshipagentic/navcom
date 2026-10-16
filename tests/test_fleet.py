"""Fleet records preserve historical evidence without claiming live boarding."""

import hashlib
import importlib.util
import json
from pathlib import Path
import struct

import navcom_fleet


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))
    return path


def test_fleet_preserves_location_evidence_and_unknown_readiness(tmp_path):
    snapshot = write(tmp_path / "bridge/data.json", {
        "generated": "2026-10-12T10:00:00Z", "destination": "Bertha SSD",
        "base": "/Volumes/Fleet/starship", "ships": [{
            "id": "cms", "name": "CMS work", "sources": ["~/clients/suite", "mobile"],
            "destination": "cms/uss-1", "state": "receiving-pass", "category": "tested",
            "detail": "Offline component passed", "gaps": ["Provider unproved"],
            "evidence": ".starship/commission/cms/RESULT.json", "basis": "Final result record",
            "resume": "do not expose or execute this", "secret": "never-copy"}]})
    config = write(tmp_path / "fleet.json", {"ssh_host": "bertha", "home": "/Users/captain",
        "remote_root": "/Volumes/Fleet/starship", "volume_uuid": "volume-123", "password_file": "private"})
    data = navcom_fleet.read_fleet(snapshot, config)
    base, ship = data["entities"]
    assert base["kind"] == "starbase" and ship["parent_id"] == base["id"]
    assert ship["physical"] == {"host": "bertha", "path": "/Volumes/Fleet/starship/cms/uss-1",
                                "volume_uuid": "volume-123", "availability": "unobserved"}
    assert ship["source_roots"] == ["/Users/captain/clients/suite"]
    assert ship["unresolved_source_references"] == ["mobile"]
    assert ship["readiness"]["status"] == "unknown"
    assert ship["readiness"]["recorded_state"] == "receiving-pass"
    assert ship["evidence"][0]["path"] == str(tmp_path / ".starship/commission/cms/RESULT.json")
    assert "Provider unproved" in ship["gaps"]
    assert data["coverage"]["live_checks"] is False
    assert "never-copy" not in json.dumps(data) and "resume" not in json.dumps(data)
    assert navcom_fleet.load(snapshot, config) == data
    # Changing a historical state does not change entity identity.
    record = json.loads(snapshot.read_text()); record["ships"][0]["state"] = "blocked"
    write(snapshot, record)
    assert navcom_fleet.read_fleet(snapshot, config)["entities"][1]["id"] == ship["id"]


def test_optional_missing_malformed_records_and_bad_destinations(tmp_path, monkeypatch):
    monkeypatch.setenv("NAVCOM_STARSHIP_ROOT", str(tmp_path))
    data = navcom_fleet.read_fleet()
    assert data["entities"] == [] and data["coverage"]["status"] == "unavailable"
    snapshot = write(tmp_path / "snapshot.json", {"ships": [None, {},
        {"id": "one", "destination": "../../outside"}, {"id": "one"}]})
    data = navcom_fleet.read_fleet(snapshot)
    assert len(data["entities"]) == 1
    assert data["entities"][0]["physical"]["path"] is None
    assert data["entities"][0]["physical"]["host"] is None
    assert len(data["coverage"]["problems"]) == 3
    write(snapshot, [])
    assert navcom_fleet.read_fleet(snapshot)["coverage"]["status"] == "unavailable"
    write(snapshot, {"ships": {}})
    assert navcom_fleet.read_fleet(snapshot)["coverage"]["problems"]


def test_art_import_is_exact_repeatable_and_contained(tmp_path):
    script = Path(__file__).resolve().parents[1] / "scripts/import_starship_art.py"
    spec = importlib.util.spec_from_file_location("import_starship_art", script)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    source, output = tmp_path / "source", tmp_path / "output"
    atlas = source / "art/atlas"; atlas.mkdir(parents=True)
    # Header fixture is sufficient for byte preservation and dimension metadata.
    png = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0dIHDR" + struct.pack(">II", 16, 32)
    (atlas / "fixture.png").write_bytes(png)
    catalog = [{"id": asset_id, "image": "fixture.png", "sheet": "sheet.png", "provenance": "fixture"}
               for asset_id in module.ROLES.values()]
    write(atlas / "catalog.json", catalog)
    assert module.import_art(source, output)["copied"] == 8
    manifest = json.loads((output / "manifest.json").read_text())
    before = {p.name: p.stat().st_mtime_ns for p in output.iterdir()}
    assert module.import_art(source, output)["unchanged"] == 8
    assert before == {p.name: p.stat().st_mtime_ns for p in output.iterdir()}
    assert all(a["sha256"] == hashlib.sha256(png).hexdigest() and a["width"] == 16 for a in manifest["assets"])
    for a in manifest["assets"]:
        assert (output / a["file"]).read_bytes() == png
    (source / "escape.png").write_bytes(png)
    catalog[0]["image"] = "../../escape.png"; write(atlas / "catalog.json", catalog)
    import pytest
    with pytest.raises(ValueError, match="escapes"):
        module.import_art(source, output)
