"""Authored product generations resolve without changing evidence membership."""
import json

import pytest

import navcom_space as space
from test_space import API, database, git, isolated_fleet, package, source_cache


@pytest.fixture(autouse=True)
def no_expert_observation(monkeypatch):
    monkeypatch.setattr(space, "_star_inventory", lambda *args: ([], {}))


def declare(root, identity, **fields):
    value = dict(id=identity, label=root.name, **fields)
    (root / ".navcom-space.json").write_text(json.dumps(value))
    return root


def by_path(data, root):
    return next(node for node in data["entities"] if any(location["path"] == str(root)
                for location in node.get("locations", [])))


def links(data):
    return [edge for edge in data["edges"] if edge["relation"] == "supersedes"]


def test_root_successors_are_exact_one_hop_and_do_not_merge_apps_or_search_scope(tmp_path):
    old = declare(git(tmp_path / "clients" / "Reef" / "old"), "reef-old")
    current = declare(git(tmp_path / "clients" / "Kite" / "current"), "reef-current")
    future = declare(git(tmp_path / "clients" / "Kite" / "next"), "reef-next")
    package(current, name="container", workspaces=["apps/*"])
    app = package(current / "apps" / "survey", name="Survey app", scripts={"start": "node app.js"})
    conn = database([(old, "Old-only discussion"), (current, "Current-only discussion"),
                     (future, "Next-only discussion"), (app, "Nested app discussion")])
    sources = source_cache(tmp_path, [old, current, future], [])
    cache = tmp_path / "space.json"
    before = space.refresh(API, conn, cache, sources)
    declare(current, "reef-current", supersedes=["reef-old"])
    declare(future, "reef-next", supersedes=["reef-current"])
    after = space.refresh(API, conn, cache, sources)
    previous, product, successor = [by_path(after, root) for root in (old, current, future)]
    assert {(edge["source"], edge["target"]) for edge in links(after)} == {
        (product["id"], previous["id"]), (successor["id"], product["id"])}
    for root in (old, current, future, app):
        for field in ("id", "parent_id", "position", "source_ids", "source_scopes", "conversation_collections", "conversation_count"):
            assert by_path(after, root)[field] == by_path(before, root)[field], (root, field)
    assert "declared_id" not in by_path(after, app)
    assert "product_declarations" not in by_path(after, app)
    edge = next(edge for edge in links(after) if edge["source"] == product["id"])
    assert edge["status"] == "declared" and not edge["evidence"]["stale"]
    record = edge["evidence"]["declarations"][0]
    assert record["path"] == str(current / ".navcom-space.json")
    assert record["declared_id"] == "reef-current" and record["supersedes"] == ["reef-old"]
    assert 0 < record["observed_at"] <= after["published"]
    assert "effective" not in record and "valid_from" not in record
    assert after["coverage"]["product_succession"]["resolved_edges"] == 2
    assert not after["coverage"]["product_succession"]["diagnostics"]
    assert not space.view(cache, action="search", within=product["id"], query="Old-only")["nodes"]
    assert space.view(cache, action="show", within=product["id"])["center"]["declared_id"] == "reef-current"
    conn.close()


def test_declared_identity_survives_move_without_git_origin(tmp_path):
    old = declare(git(tmp_path / "old"), "alder-original")
    current = declare(git(tmp_path / "exp7"), "alder-current", supersedes=["alder-original"])
    conn = database([(old, "Old"), (current, "Current")])
    cache = tmp_path / "space.json"
    before = space.refresh(API, conn, cache)
    node = by_path(before, current)
    assert node["kind"] == "planet"  # Omitted kind in a product claim defaults to planet.
    moved = current.with_name("moved-product")
    current.rename(moved)
    conn.execute("UPDATE file_meta SET project=? WHERE project=?", (str(moved), str(current)))
    conn.commit()
    after = space.refresh(API, conn, cache)
    same = by_path(after, moved)
    assert (same["id"], same["position"], same["parent_id"]) == (node["id"], node["position"], node["parent_id"])
    assert links(after)[0]["source"] == same["id"]
    assert same["product_declarations"][0]["path"] == str(moved / ".navcom-space.json")
    assert not after["coverage"]["product_succession"]["diagnostics"]
    conn.close()


@pytest.mark.parametrize("fields", [
    {"supersedes": "alder-old"}, {"supersedes": [7]}, {"supersedes": [""]},
    {"supersedes": [" alder-old"]}, {"supersedes": ["alder-old"] * 65},
    {"kind": "moon", "supersedes": ["alder-old"]},
    {"id": "", "supersedes": ["alder-old"]},
    {"id": None, "supersedes": ["alder-old"]},
])
def test_invalid_claim_reports_gap_without_inventing_relation(tmp_path, fields):
    old = declare(git(tmp_path / "old"), "alder-old")
    current = git(tmp_path / "current")
    (current / ".navcom-space.json").write_text(json.dumps(dict({"id": "alder-new"}, **fields)))
    conn = database([(old, "Old"), (current, "Current")])
    data = space.refresh(API, conn, tmp_path / "space.json")
    assert links(data) == []
    assert any(item["code"] == "invalid" for item in data["coverage"]["product_succession"]["diagnostics"])
    assert by_path(data, old)["conversation_count"] == by_path(data, current)["conversation_count"] == 1
    conn.close()


def test_missing_target_self_and_cycles_do_not_become_edges(tmp_path):
    roots = [declare(git(tmp_path / name), name, supersedes=targets) for name, targets in (
        ("birch", ["cedar"]), ("cedar", ["birch"]), ("maple", ["missing", "maple"]),
        ("spruce", ["birch"]), ("ash", []), ("elm", ["ash"]))]
    conn = database([(root, root.name) for root in roots])
    data = space.refresh(API, conn, tmp_path / "space.json")
    assert [(edge["evidence"]["declared_id"], edge["evidence"]["target_declared_id"]) for edge in links(data)] == [("elm", "ash")]
    codes = {item["code"] for item in data["coverage"]["product_succession"]["diagnostics"]}
    assert codes == {"missing", "self", "cycle"}
    assert all(by_path(data, root)["conversation_count"] == 1 for root in roots)
    conn.close()


def test_overlapping_cycles_block_every_cyclic_product_claim(tmp_path):
    # c is reached after b has finished in a single DFS; it still participates
    # in a -> c -> b -> a, so its independent-looking claim is not authoritative.
    roots = [declare(git(tmp_path / name), name, supersedes=targets) for name, targets in (
        ("a", ["b", "c"]), ("b", ["a"]), ("c", ["b", "d"]), ("d", []))]
    conn = database([(root, root.name) for root in roots])
    data = space.refresh(API, conn, tmp_path / "space.json")
    assert not links(data)
    assert {item["declared_id"] for item in data["coverage"]["product_succession"]["diagnostics"]
            if item["code"] == "cycle"} == {"a", "b", "c"}
    conn.close()


def test_explicit_shared_product_id_preserves_existing_multi_repository_union(tmp_path):
    old = declare(git(tmp_path / "old"), "original")
    first = declare(git(tmp_path / "first", "git@example.test:one/a.git"), "duplicate", supersedes=["original"])
    second = declare(git(tmp_path / "second", "git@example.test:two/b.git"), "duplicate", supersedes=["original"])
    conn = database([(old, "Old"), (first, "First"), (second, "Second")])
    sources = source_cache(tmp_path, [old, first, second], [])
    data = space.refresh(API, conn, tmp_path / "space.json", sources)
    left, right = by_path(data, first), by_path(data, second)
    assert left["id"] == right["id"]
    assert left["declared_id"] == right["declared_id"] == "duplicate"
    assert set(left["source_ids"]) == {"1", "2"}
    assert len(left["conversation_collections"]) == 2
    assert left["conversation_count"] == right["conversation_count"] == 2
    assert set(left["source_ids"]).isdisjoint(by_path(data, old)["source_ids"])
    assert len(links(data)) == 1 and len(links(data)[0]["evidence"]["declarations"]) == 2
    assert not data["coverage"]["product_succession"]["diagnostics"]
    conn.close()


def test_reused_declared_id_with_different_kinds_cannot_resolve_succession(tmp_path):
    old = declare(git(tmp_path / "old"), "original")
    first = declare(git(tmp_path / "first"), "duplicate", supersedes=["original"])
    second = declare(git(tmp_path / "second"), "duplicate", kind="moon")
    conn = database([(old, "Old"), (first, "Product"), (second, "Experiment")])
    data = space.refresh(API, conn, tmp_path / "space.json")
    assert by_path(data, first)["id"] != by_path(data, second)["id"]
    assert not links(data)
    assert any(item["code"] == "conflicting" and item["declared_id"] == "duplicate"
               for item in data["coverage"]["product_succession"]["diagnostics"])
    conn.close()


def test_actual_git_copies_agree_then_conflicting_copy_blocks_claim(tmp_path):
    old = declare(git(tmp_path / "old"), "original")
    first = declare(git(tmp_path / "first", "git@example.test:alder/current.git"), "current", supersedes=["original"])
    second = declare(git(tmp_path / "second", "https://example.test/alder/current.git"), "current", supersedes=["original"])
    conn = database([(old, "Old"), (first, "First copy"), (second, "Second copy")])
    cache = tmp_path / "space.json"
    before = space.refresh(API, conn, cache)
    assert len(links(before)) == 1
    assert len(links(before)[0]["evidence"]["declarations"]) == 2
    assert by_path(before, first)["id"] == by_path(before, second)["id"]
    declare(second, "current", supersedes=[])
    after = space.refresh(API, conn, cache)
    assert not links(after)
    assert any(item["code"] == "conflicting" for item in after["coverage"]["product_succession"]["diagnostics"])
    assert by_path(after, first)["conversation_count"] == 2  # Exact existing Git-copy identity stays intact.
    conn.close()


def test_offline_declaration_retains_exact_original_observation_as_stale(tmp_path):
    old = declare(git(tmp_path / "old"), "original")
    current = declare(git(tmp_path / "current"), "current", supersedes=["original"])
    conn = database([(old, "Old"), (current, "Current")])
    cache = tmp_path / "space.json"
    before = space.refresh(API, conn, cache)
    original_record = by_path(before, current)["product_declarations"][0]
    current.rename(current.with_name("unavailable"))
    after = space.refresh(API, conn, cache)
    node = by_path(after, current)
    assert node["id"] == by_path(before, current)["id"]
    assert node["product_declarations"] == [dict(original_record, stale=True)]
    assert links(after)[0]["evidence"]["stale"] is True
    assert after["coverage"]["product_succession"]["stale_declarations"] == 1
    # A fresh catalog cannot invent the absent declaration from a directory name.
    fresh = space.refresh(API, conn, tmp_path / "fresh.json")
    assert not links(fresh) and "declared_id" not in by_path(fresh, current)
    conn.close()


def test_live_copy_replaces_old_offline_claim_but_preserves_stale_evidence(tmp_path):
    old = declare(git(tmp_path / "old"), "original")
    first = declare(git(tmp_path / "first", "git@example.test:alder/current.git"), "current", supersedes=["original"])
    second = declare(git(tmp_path / "second", "git@example.test:alder/current.git"), "current", supersedes=["original"])
    conn = database([(old, "Old"), (first, "First"), (second, "Second")])
    cache = tmp_path / "space.json"
    before = space.refresh(API, conn, cache)
    first.rename(first.with_name("offline"))
    declare(second, "current", supersedes=[])
    after = space.refresh(API, conn, cache)
    assert not links(after)
    records = by_path(after, second)["product_declarations"]
    assert {record["stale"] for record in records} == {True, False}
    assert not after["coverage"]["product_succession"]["diagnostics"]
    assert by_path(after, second)["id"] == by_path(before, second)["id"]
    conn.close()


def test_no_relation_from_names_and_no_stale_claim_when_live_file_is_removed(tmp_path):
    old = declare(git(tmp_path / "alder-v1"), "original")
    current = declare(git(tmp_path / "alder-v2"), "current")
    conn = database([(old, "Old"), (current, "Current")])
    cache = tmp_path / "space.json"
    assert not links(space.refresh(API, conn, cache))
    declare(current, "current", supersedes=["original"])
    assert links(space.refresh(API, conn, cache))
    (current / ".navcom-space.json").unlink()
    after = space.refresh(API, conn, cache)
    assert not links(after) and "product_declarations" not in by_path(after, current)
    conn.close()
