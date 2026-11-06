"""Nested product declarations keep native CLI/API evidence on the exact app."""
import json
import os
from pathlib import Path
import shlex
import shutil
import sqlite3
import subprocess
import sys

import pytest

from test_atlas import add
from test_relationships import harvest
from test_space import git, isolated_fleet, package


ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(not shutil.which("starforge"), reason="Optional native Starforge runtime required")


def declare(path, identity, label, **fields):
    (path / ".navcom-space.json").write_text(json.dumps(dict(id=identity, label=label, **fields)))


def command(*args, ok=True):
    result = subprocess.run(
        [sys.executable, str(ROOT / "navcom.py"), *map(str, args)], cwd=ROOT,
        capture_output=True, text=True, timeout=30,
        env=dict(os.environ, NAVCOM_NO_SKILLS="1"),
    )
    assert (result.returncode == 0) is ok, result.stderr
    return json.loads(result.stdout) if ok else result


def by_path(chart, path):
    return next(node for node in chart["entities"] if any(
        item["path"] == str(path) for item in node.get("locations", [])))


@pytest.fixture
def suite(tmp_path, navcom, monkeypatch, request):
    root = git(tmp_path / "clients" / "Aurora" / "suite")
    metadata = dict(name="Aurora suite")
    if getattr(request, "param", True):
        metadata["workspaces"] = ["apps/*"]
    package(root, **metadata)
    declare(root, "aurora-suite", "Aurora suite")
    apps = {}
    for name, identity, label in (
        ("admin", "aurora-admin", "Aurora Admin"),
        ("mobile-v1", "aurora-mobile-one", "Aurora Mobile One"),
        ("mobile-v2", "aurora-mobile-two", "Aurora Mobile Two"),
    ):
        path = package(root / "apps" / name, name=label, scripts={"start": "python worker.py"})
        declare(path, identity, label)
        (path / "README.md").write_text("# " + label + "\nMarmot calibration belongs to " + name + ".\n")
        (path / "worker.py").write_text(
            '"""Marmot optical calibration workflow."""\n'
            "def calibrate(value):\n"
            + "".join(f"    step_{i} = value + {i}\n" for i in range(25))
            + "    return step_24\n"
        )
        apps[name] = path
    index = tmp_path / "index.sqlite"
    monkeypatch.setenv("NAVCOM_INDEX", str(index))
    monkeypatch.setattr(navcom, "INDEX_READ_ONLY", False)
    conn = navcom.open_index(index)
    keys = {}
    for name, path in {"root": root, **apps}.items():
        keys[name] = add(navcom, conn, tmp_path / (name + ".jsonl"), name + " decisions", "marmot calibration", str(path))
    conn.close()
    source_cache, chart = tmp_path / "sources", tmp_path / "space.json"
    source = dict(id="aurora-suite-source", root=str(root), label="Aurora suite", include=["."])
    harvest([source], source_cache)
    common = ["--space-cache", chart, "--source-cache", source_cache, "--index", index, "--json"]
    before = command("atlas", "refresh", "--space", *common)
    declare(apps["mobile-v2"], "aurora-mobile-two", "Aurora Mobile Two", supersedes=["aurora-mobile-one"])
    after = command("atlas", "refresh", "--space", *common)
    monkeypatch.setenv("NAVCOM_SPACE_CACHE", str(chart))
    monkeypatch.setenv("NAVCOM_SOURCES_CACHE", str(source_cache))
    return dict(root=root, apps=apps, keys=keys, index=index, sources=source_cache,
                source=source, chart=chart, common=common, before=before, after=after)


@pytest.mark.parametrize("suite", [True, False], indirect=True, ids=["workspace", "native-apps"])
def test_refresh_related_show_and_search_keep_each_product_independent(suite, navcom):
    from navcom_web import WebApp

    before, after = suite["before"], suite["after"]
    apps, common = suite["apps"], suite["common"]
    root = by_path(after, suite["root"])
    nodes = {name: by_path(after, path) for name, path in apps.items()}
    old, current = nodes["mobile-v1"], nodes["mobile-v2"]
    assert len({root["id"], *(node["id"] for node in nodes.values())}) == 4
    assert current["declared_id"] == "aurora-mobile-two"
    assert old["declared_id"] == "aurora-mobile-one"
    assert current["label"] == "Aurora Mobile Two"
    for name, node in nodes.items():
        initial = by_path(before, apps[name])
        for field in ("id", "position", "parent_id", "conversation_collections", "conversation_count", "source_scopes"):
            assert node[field] == initial[field], (name, field)
        assert node["conversation_count"] == 1
        assert node["source_scopes"] == [dict(source_id="aurora-suite-source", paths=["apps/" + name])]
    assert len({tuple(node["conversation_collections"]) for node in nodes.values()}) == 3
    edges = [edge for edge in after["edges"] if edge["relation"] == "supersedes"]
    assert [(edge["source"], edge["target"]) for edge in edges] == [(current["id"], old["id"])]

    related = command("atlas", "related", old["id"], *common)
    assert len(related["declared_relations"]) == 1
    relation = related["declared_relations"][0]
    assert relation["successor"]["id"] == current["id"]
    assert relation["predecessor"]["id"] == old["id"]
    assert relation["evidence"]["declarations"][0]["path"] == str(apps["mobile-v2"] / ".navcom-space.json")
    shown = command(*shlex.split(relation["successor"]["show_command"])[1:], "--json")
    assert shown["center"]["id"] == current["id"]
    for unrelated in (root, nodes["admin"]):
        assert not command("atlas", "related", unrelated["id"], *common)["declared_relations"]

    cached = command("atlas", "related", old["id"], *common)
    assert cached["cached"] and cached["harvest_invocations"] == 0
    app = WebApp(navcom, suite["index"])
    assert app.get(None, "/api/space/related", {"within": [old["id"]]}) == cached

    files = command("atlas", "files", current["id"], *common)
    assert not files["errors"] and files["files"]
    assert all(row["relative_path"].startswith("apps/mobile-v2/") for row in files["files"])
    assert app.get(None, "/api/space/files", {"within": [current["id"]]}) == files
    found = command("atlas", "search", "marmot", "--within", current["id"], "--evidence", *common)
    evidence = found["evidence"]
    assert not evidence["errors"]
    assert evidence["sources"] and evidence["sources"][0]["concept_hits"] and evidence["sources"][0]["text_hits"]
    assert all(Path(hit["source_path"]).is_relative_to(apps["mobile-v2"])
               for source in evidence["sources"] for kind in ("concept_hits", "text_hits") for hit in source[kind])
    assert [node["key"] for node in evidence["conversations"]] == [suite["keys"]["mobile-v2"]]
    with sqlite3.connect(suite["index"]) as conn:
        web = app.get(conn, "/api/space", dict(action=["search"], q=["marmot"], within=[current["id"]],
                                               evidence=["1"], limit=[str(found["limit"])]))
    assert web["center"] == found["center"]
    assert web["evidence"]["conversations"] == evidence["conversations"]
    for kind in ("concept_hits", "text_hits"):
        assert web["evidence"]["sources"][0][kind] == evidence["sources"][0][kind]


def test_moved_app_keeps_identity_and_qualifies_retained_source_evidence(suite):
    original_path = suite["apps"]["mobile-v2"]
    original = by_path(suite["after"], original_path)
    moved_path = original_path.with_name("mobile-renamed")
    original_path.rename(moved_path)
    (moved_path / "README.md").write_text("# Aurora Mobile Two\nNEW_MOBILE_LOCATION_ONLY\n")
    with sqlite3.connect(suite["index"]) as conn:
        conn.execute("UPDATE file_meta SET project=? WHERE project=?", (str(moved_path), str(original_path)))
    before_harvest = command("atlas", "refresh", "--space", *suite["common"])
    moved = by_path(before_harvest, moved_path)
    assert moved["id"] == original["id"]
    assert moved["position"] == original["position"]
    assert {path for scope in moved["source_scopes"] for path in scope["paths"]} == {
        "apps/mobile-v2", "apps/mobile-renamed"}
    declarations = {record["path"]: record for record in moved["product_declarations"]}
    assert declarations[str(original_path / ".navcom-space.json")]["stale"] is True
    assert declarations[str(moved_path / ".navcom-space.json")]["stale"] is False
    locations = {location["path"]: location for location in moved["locations"]}
    assert locations[str(original_path)]["available"] is False
    assert locations[str(moved_path)]["available"] is True
    retained = command("atlas", "files", moved["id"], *suite["common"])
    assert retained["files"] and all(row["relative_path"].startswith("apps/mobile-v2/") for row in retained["files"])
    assert retained["errors"]  # The existing harvest has no bytes at the new path yet.
    assert retained["coverage"]["current_files_read"] is False
    # Earlier content is retained as the same declared product's previous
    # address, never silently relabelled as bytes from its newly moved folder.
    assert all(Path(row["original_path"]).is_relative_to(original_path) for row in retained["files"])
    old_readme = next(row for row in retained["files"] if row["relative_path"].endswith("/README.md"))

    harvest([suite["source"]], suite["sources"])
    refreshed = command("atlas", "refresh", "--space", *suite["common"])
    current = by_path(refreshed, moved_path)
    assert current["id"] == original["id"]
    assert current["conversation_count"] == 1
    assert current["source_scopes"] == [dict(source_id="aurora-suite-source", paths=["apps/mobile-renamed"])]
    files = command("atlas", "files", current["id"], *suite["common"])
    assert not files["errors"] and files["files"]
    assert all(row["relative_path"].startswith("apps/mobile-renamed/") for row in files["files"])
    readme = next(row for row in files["files"] if row["relative_path"].endswith("/README.md"))
    read = command(*shlex.split(readme["read_command"])[1:], "--json")
    assert any(line["text"] == "NEW_MOBILE_LOCATION_ONLY" for line in read["lines"])
    assert read["provenance"]["current_file_read"] is False
    rejected = command(*shlex.split(old_readme["read_command"])[1:], "--json", ok=False)
    assert "snapshot changed" in rejected.stderr
    found = command("atlas", "search", "NEW_MOBILE_LOCATION_ONLY", "--within", current["id"],
                    "--evidence", *suite["common"])["evidence"]
    assert not found["errors"] and found["sources"][0]["text_hits"]
    assert all(hit["relative_path"] == "apps/mobile-renamed/README.md"
               for source in found["sources"] for hit in source["text_hits"])
    related = command("atlas", "related", current["id"], *suite["common"])
    assert related["declared_relations"][0]["successor"]["id"] == current["id"]
    assert related["declared_relations"][0]["predecessor"]["declared_id"] == "aurora-mobile-one"
