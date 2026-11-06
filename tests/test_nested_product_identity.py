"""Declared products reuse one identity inside or outside a repository."""
import json
from pathlib import Path

import pytest

import navcom_space as space
from test_space import API, database, git, isolated_fleet, package, source_cache
from test_product_succession import by_path, links


def declare(root, identity, **fields):
    (root / ".navcom-space.json").write_text(json.dumps(dict({"id": identity, "label": root.name}, **fields)))
    return root


@pytest.fixture(autouse=True)
def no_expert_observation(monkeypatch):
    monkeypatch.setattr(space, "_star_inventory", lambda *args: ([], {}))


def suite(tmp_path, *, native=False):
    root = git(tmp_path / "clients" / "Aster" / "suite")
    package(root, name="suite", workspaces=[] if native else ["apps/*"])
    apps = [package(root / "apps" / name, name=name, scripts={"start": "not executed"})
            for name in ("mobile-v1", "mobile-v2", "billing")]
    sources = source_cache(tmp_path, [root], [])
    if native:
        candidates = [dict(root=str(app.relative_to(root)), manifest=str(app.relative_to(root)) + "/package.json",
                           name=app.name, entry_points=[dict(type="npm-script", name="npm run start")])
                      for app in apps]
        (sources / "artifacts/0/structure.json").write_text(json.dumps(dict(application_candidates=candidates, token_groups=[])))
    conn = database([(root, "Suite work")] + [(app, app.name + " only") for app in apps])
    return root, apps, sources, conn


@pytest.mark.parametrize("native", [False, True])
def test_nested_products_have_exact_declarations_and_unchanged_evidence_scopes(tmp_path, native):
    root, (old, current, billing), sources, conn = suite(tmp_path, native=native)
    declare(root, "suite", supersedes=["unavailable-root-predecessor"])
    cache = tmp_path / "space.json"
    before = space.refresh(API, conn, cache, sources)
    declare(old, "mobile-classic", label="Mobile Classic")
    declare(current, "mobile-current", label="Mobile Current", description="Current field workflow", supersedes=["mobile-classic"])
    data = space.refresh(API, conn, cache, sources)
    left, right = by_path(data, old), by_path(data, current)
    assert left["id"] == space._id("planet", "mobile-classic::.")
    assert right["id"] == space._id("planet", "mobile-current::.")
    assert (left["label"], right["label"], right["description"]) == ("Mobile Classic", "Mobile Current", "Current field workflow")
    assert left["status"] == right["status"] == "established"
    for path in (root, old, current, billing):
        for field in ("parent_id", "position", "source_ids", "source_scopes", "conversation_collections", "conversation_count"):
            assert by_path(data, path)[field] == by_path(before, path)[field], (path, field)
    assert "declared_id" not in by_path(data, billing)
    assert len(links(data)) == 1
    assert (links(data)[0]["source"], links(data)[0]["target"]) == (right["id"], left["id"])
    record = right["product_declarations"][0]
    assert record["path"] == str(current / ".navcom-space.json")
    assert record["repository_root"] == str(root) and not record["stale"]
    assert record["supersedes"] == ["mobile-classic"]
    assert right["source_scopes"] == [dict(source_id="0", paths=["apps/mobile-v2"])]
    assert not space.view(cache, action="search", within=right["id"], query="billing")["nodes"]
    conn.close()


def test_identity_and_position_survive_move_within_then_outside_repository(tmp_path):
    root, (old, current, _), sources, conn = suite(tmp_path)
    declare(old, "mobile-classic")
    declare(current, "mobile-current", supersedes=["mobile-classic"])
    cache = tmp_path / "space.json"
    first = by_path(space.refresh(API, conn, cache, sources), current)
    for moved in (root / "apps" / "renamed", tmp_path / "standalone-product"):
        current.rename(moved)
        conn.execute("UPDATE file_meta SET project=? WHERE project=?", (str(moved), str(current)))
        conn.commit()
        if moved.parent == tmp_path:
            git(moved)
        data = space.refresh(API, conn, cache, sources)
        same = by_path(data, moved)
        assert (same["id"], same["position"], same["parent_id"]) == (first["id"], first["position"], first["parent_id"])
        assert any(record["path"] == str(moved / ".navcom-space.json") and not record["stale"]
                   for record in same["product_declarations"])
        assert links(data)[0]["source"] == same["id"]
        current = moved
    conn.close()


def test_id_only_product_split_into_experiment_named_repo_stays_same_planet(tmp_path):
    _, (_, current, _), sources, conn = suite(tmp_path)
    declare(current, "mobile-current")
    cache = tmp_path / "space.json"
    before = by_path(space.refresh(API, conn, cache, sources), current)
    moved = tmp_path / "exp7"
    current.rename(moved)
    git(moved)
    conn.execute("UPDATE file_meta SET project=? WHERE project=?", (str(moved), str(current)))
    conn.commit()
    data = space.refresh(API, conn, cache, sources)
    same = by_path(data, moved)
    assert (same["id"], same["kind"], same["position"]) == (before["id"], "planet", before["position"])
    assert [node["id"] for node in data["entities"] if node.get("declared_id") == "mobile-current"] == [same["id"]]
    conn.close()


@pytest.mark.parametrize("native", [False, True])
@pytest.mark.parametrize("change", ["missing", "linked"])
def test_unavailable_app_retains_only_its_exact_stale_declaration(tmp_path, monkeypatch, native, change):
    root, (old, current, _), sources, conn = suite(tmp_path, native=native)
    declare(old, "mobile-classic")
    declare(current, "mobile-current", supersedes=["mobile-classic"])
    cache = tmp_path / "space.json"
    before = space.refresh(API, None, cache, sources)
    original = by_path(before, current)
    current.rename(tmp_path / "parked-mobile")
    if change == "linked":
        outside = declare(git(tmp_path / "foreign"), "foreign", supersedes=["mobile-classic"])
        current.symlink_to(outside, target_is_directory=True)
    read = space._declaration
    def guarded(path, *args, **kwargs):
        assert path != current, "Unavailable app declaration must not be reread"
        return read(path, *args, **kwargs)
    monkeypatch.setattr(space, "_declaration", guarded)
    data = space.refresh(API, None, cache, sources)
    same = by_path(data, current)
    assert same["id"] == original["id"] and same["position"] == original["position"]
    assert same["product_declarations"] == [dict(original["product_declarations"][0], stale=True)]
    assert not same["locations"][0]["available"]
    assert links(data)[0]["evidence"]["stale"]
    assert "foreign" not in {node.get("declared_id") for node in data["entities"]}
    conn.close()


def test_nested_independent_git_owner_uses_one_canonical_declared_node(tmp_path):
    root, (old, current, billing), sources, conn = suite(tmp_path)
    git(current, "git@example.test:independent/mobile.git")
    declare(old, "mobile-classic")
    declare(current, "mobile-current", supersedes=["mobile-classic"])
    data = space.refresh(API, conn, tmp_path / "space.json", sources)
    found = [node for node in data["entities"] if any(loc["path"] == str(current) for loc in node["locations"])]
    assert len(found) == 1
    current_node = found[0]
    assert current_node["id"] == space._id("planet", "mobile-current::.")
    assert len(current_node["product_declarations"]) == 1
    assert current_node["product_declarations"][0]["repository_root"] == str(current)
    assert current_node["conversation_count"] == 1
    assert current_node["conversation_collections"] != by_path(data, billing)["conversation_collections"]
    assert len(links(data)) == 1 and not data["coverage"]["reconciliation"]["conflicts"]
    conn.close()


def test_same_identity_across_nested_and_standalone_copy_preserves_union_and_conflict_rules(tmp_path):
    root, (old, current, billing), sources, conn = suite(tmp_path)
    declare(old, "mobile-classic")
    declare(current, "mobile-current", supersedes=["mobile-classic"])
    separate = declare(git(tmp_path / "standalone"), "mobile-current", supersedes=["mobile-classic"])
    conn.execute("INSERT INTO file_state VALUES ('copy')")
    conn.execute("INSERT INTO file_meta VALUES ('copy', ?, 'Copy only')", (str(separate),))
    conn.commit()
    cache = tmp_path / "space.json"
    data = space.refresh(API, conn, cache, sources)
    same = by_path(data, current)
    assert same["id"] == by_path(data, separate)["id"]
    assert len(same["product_declarations"]) == 2 and same["conversation_count"] == 2
    assert set(same["conversation_collections"]).isdisjoint(by_path(data, billing)["conversation_collections"])
    assert len(links(data)) == 1
    declare(separate, "mobile-current", supersedes=[])
    conflict = space.refresh(API, conn, cache, sources)
    assert not links(conflict)
    assert any(item["code"] == "conflicting" for item in conflict["coverage"]["product_succession"]["diagnostics"])
    conn.close()


def test_declaration_is_not_discovery_and_linked_metadata_is_never_read(tmp_path):
    root, (_, current, _), sources, conn = suite(tmp_path)
    hidden = declare(package(root / "unlisted", name="unlisted"), "not-discovered")
    library = declare(package(root / "apps" / "library", name="library", scripts={"build": "tsc"}), "not-a-product")
    foreign = declare(package(tmp_path / "foreign", name="foreign", scripts={"start": "no"}), "foreign")
    (current / ".navcom-space.json").symlink_to(foreign / ".navcom-space.json")
    (root / "linked-parent").symlink_to(tmp_path, target_is_directory=True)
    package(root, name="suite", workspaces=["apps/*", "linked-parent/foreign", "../foreign"])
    data = space.refresh(API, conn, tmp_path / "space.json", sources)
    assert not any(node.get("declared_id") for node in data["entities"])
    assert not any(loc["path"] in {str(hidden), str(library), str(root / "linked-parent" / "foreign")}
                   for node in data["entities"] for loc in node["locations"])
    assert any("Linked declarations" in warning for warning in data["coverage"]["warnings"])
    assert any("invalid workspace pattern" in warning for warning in data["coverage"]["warnings"])
    conn.close()


@pytest.mark.parametrize("fields", [{"kind": "moon"}, {"kind": "star"}, {"id": " bad"}, {"id": 1}])
def test_invalid_nested_product_metadata_does_not_reclassify_discovered_boundary(tmp_path, fields):
    _, (_, current, _), sources, conn = suite(tmp_path)
    (current / ".navcom-space.json").write_text(json.dumps(dict({"id": "mobile"}, **fields)))
    data = space.refresh(API, conn, tmp_path / "space.json", sources)
    node = by_path(data, current)
    assert node["kind"] == "planet" and "declared_id" not in node
    assert data["coverage"]["product_succession"]["diagnostics"]
    conn.close()


def test_nested_explicit_system_is_local_and_live_removed_claim_is_not_retained(tmp_path):
    _, (old, current, billing), sources, conn = suite(tmp_path)
    declare(old, "mobile-classic")
    declare(current, "mobile-current", system={"id": "field", "label": "Field operations"}, supersedes=["mobile-classic"])
    cache = tmp_path / "space.json"
    data = space.refresh(API, conn, cache, sources)
    assert by_path(data, current)["parent_id"] == space._id("system", "declared:field")
    assert by_path(data, billing)["parent_id"] != by_path(data, current)["parent_id"]
    (current / ".navcom-space.json").unlink()
    fresh = space.refresh(API, conn, cache, sources)
    assert "declared_id" not in by_path(fresh, current) and not links(fresh)
    conn.close()
