"""Real metadata fixtures for cached spatial navigation, without client-name rules."""
import fcntl
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
from types import SimpleNamespace

import pytest

import navcom_space as space


API = SimpleNamespace(pretty_project=lambda path: str(path))


@pytest.fixture(autouse=True)
def isolated_fleet(tmp_path, monkeypatch):
    monkeypatch.setenv("NAVCOM_STARSHIP_ROOT", str(tmp_path / "no-fleet"))
    monkeypatch.delenv("NAVCOM_FLEET_SNAPSHOT", raising=False)
    monkeypatch.delenv("NAVCOM_FLEET_CONFIG", raising=False)
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "no-native-profiles"))


def database(projects):
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE file_state(file TEXT)")
    conn.execute("CREATE TABLE file_meta(file TEXT,project TEXT,title TEXT)")
    for i, (project, title) in enumerate(projects):
        conn.execute("INSERT INTO file_state VALUES (?)", (str(i),))
        conn.execute("INSERT INTO file_meta VALUES (?,?,?)", (str(i), str(project), title))
    conn.commit()
    return conn


def git(root, origin=None):
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    if origin:
        subprocess.run(["git", "-C", str(root), "remote", "add", "origin", origin], check=True)
    return root


def package(root, **metadata):
    root.mkdir(parents=True, exist_ok=True)
    (root / "package.json").write_text(json.dumps(metadata))
    return root


def source_cache(tmp_path, roots, groups=None):
    cache = tmp_path / "sources"
    cache.mkdir()
    sources = []
    for i, root in enumerate(roots):
        artifact = cache / "artifacts" / str(i)
        artifact.mkdir(parents=True)
        sources.append(dict(id=str(i), root=str(root), artifact=str(artifact), include=["."]))
        if groups is not None:
            (artifact / "structure.json").write_text(json.dumps(dict(schema_version=1, token_groups=groups)))
    (cache / "current.json").write_text(json.dumps(dict(published=1234, sources=sources)))
    return cache


def test_unfamiliar_suite_has_apps_labs_and_exact_conversation_scopes(tmp_path):
    suite = git(tmp_path / "clients" / "Northwind" / "suite", "git@example.test:northwind/suite.git")
    package(suite, name="suite", workspaces=["apps/*", "packages/*"])
    quartz = package(suite / "apps" / "quartz", name="Quartz", description="Scheduling product", scripts={"start": "node index.js"})
    topaz = package(suite / "apps" / "topaz", name="Topaz", description="Payment product", scripts={"dev": "vite"})
    package(suite / "packages" / "shared", name="Shared helper", scripts={"build": "tsc"})
    lab = quartz / "LABS" / "planner-experiment"
    lab.mkdir(parents=True)
    conn = database([(suite, "Suite setup"), (quartz, "login design"), (topaz, "quartz migration mentioned"), (lab, "Planner benchmark")])
    cache = tmp_path / "space.json"
    data = space.refresh(API, conn, cache)
    nodes = {n["label"]: n for n in data["entities"]}
    system = nodes["Northwind"]
    assert system["kind"] == "system" and system["status"] == "suggested"
    assert nodes["Quartz"]["parent_id"] == system["id"]
    assert nodes["Topaz"]["parent_id"] == system["id"]
    assert "Shared helper" not in nodes
    assert nodes["planner-experiment"]["kind"] == "moon"
    assert nodes["planner-experiment"]["parent_id"] == nodes["Quartz"]["id"]
    assert nodes["Quartz"]["conversation_count"] == 2
    assert nodes["Topaz"]["conversation_count"] == 1
    assert nodes["Topaz"]["conversation_collections"] != nodes["Quartz"]["conversation_collections"]
    assert space.view(cache, action="list", kind="planets", within=system["id"])["total"] == 3
    scoped = space.view(cache, action="search", within=nodes["Quartz"]["id"], query="migration")
    assert scoped["nodes"] == []  # Mentioning Quartz in another app does not create ownership.
    assert [b["label"] for b in space.view(cache, action="explore", within=nodes["Quartz"]["id"])["breadcrumbs"]] == ["Your galaxy", "Northwind", "Quartz"]
    conn.close()


def test_remote_identity_merges_copies_and_survives_moves_without_secret_origin(tmp_path):
    first = git(tmp_path / "clients" / "Nova" / "product", "https://user:secret-token@example.test/nova/product.git?access=hidden")
    duplicate = git(tmp_path / "copies" / "other-name", "git@example.test:nova/product.git")
    conn = database([(first, "Main"), (duplicate, "Child task")])
    cache = tmp_path / "space.json"
    data = space.refresh(API, conn, cache)
    planets = [n for n in data["entities"] if n["kind"] == "planet"]
    assert len(planets) == 1 and planets[0]["conversation_count"] == 2
    assert len(planets[0]["locations"]) == 2
    assert not [n for n in data["entities"] if n["kind"] == "moon"]
    assert "secret-token" not in cache.read_text() and "hidden" not in cache.read_text()
    identity, position = planets[0]["id"], planets[0]["position"]
    moved = first.with_name("renamed")
    first.rename(moved)
    conn.execute("UPDATE file_meta SET project=? WHERE project=?", (str(moved), str(first)))
    conn.commit()
    after = space.refresh(API, conn, cache)
    same = next(n for n in after["entities"] if n["id"] == identity)
    assert same["position"] == position
    assert next(n for n in after["entities"] if n["id"] == same["parent_id"])["label"] == "Nova"
    conn.close()


def test_native_cached_apps_without_workspaces_keep_exact_scope_and_offline_identity(tmp_path, monkeypatch):
    root = git(tmp_path / "clients" / "Aurora" / "observing-suite")
    package(root, name="suite")
    first = package(root / "apps" / "first", name="Cobalt", scripts={"start": "node a.js"})
    second = package(root / "apps" / "second", name="Helium", scripts={"dev": "vite"})
    shared = package(root / "packages" / "shared", name="Helper", scripts={"build": "tsc"})
    conn = database([(root, "Suite"), (first, "Calibration"), (second, "Sibling only")])
    cache = tmp_path / "space.json"
    # No new live traversal recognizes these; published native evidence does.
    initial = space.refresh(API, conn, cache)
    assert not any(node["label"] == "Cobalt" for node in initial["entities"])
    sources = source_cache(tmp_path, [root], groups=[])
    candidates = []
    for app, script in ((first, "start"), (second, "dev"), (shared, "build")):
        relative = str(app.relative_to(root))
        candidates.append(dict(root=relative, manifest=relative + "/package.json", name=json.loads((app / "package.json").read_text())["name"],
                               entry_points=[dict(type="npm-script", name="npm run " + script, file="package.json")]))
    candidates.append(dict(root="../outside", manifest="../outside/package.json"))
    artifact = sources / "artifacts" / "0" / "structure.json"
    artifact.write_text(json.dumps(dict(application_candidates=candidates, token_groups=[])))
    data = space.refresh(API, conn, cache, source_cache=sources)
    cobalt = next(node for node in data["entities"] if node["label"] == "Cobalt")
    assert cobalt["status"] == "candidate" and cobalt["conversation_count"] == 1
    assert cobalt["source_scopes"] == [dict(source_id="0", paths=["apps/first"])]
    assert not any(node["label"] == "Helper" for node in data["entities"])
    assert data["coverage"]["warnings"]
    assert not space.view(cache, action="search", within=cobalt["id"], query="Sibling only")["nodes"]
    root.rename(root.with_name("unavailable"))
    after = space.refresh(API, conn, cache, source_cache=sources)
    preserved = next(node for node in after["entities"] if node["id"] == cobalt["id"])
    assert preserved["position"] == cobalt["position"]
    assert not preserved["locations"][0]["available"]
    monkeypatch.setattr(space, "_boundaries", lambda *_: pytest.fail("cached navigation scanned source"))
    assert space.view(cache, action="show", within=cobalt["id"])["center"]["id"] == cobalt["id"]
    conn.close()


def test_cached_native_app_does_not_scan_replaced_symlink(tmp_path):
    root = package(tmp_path / "suite", name="suite")
    outside = tmp_path / "outside"
    (outside / "LABS" / "must-not-discover").mkdir(parents=True)
    (root / "apps").mkdir()
    (root / "apps" / "linked").symlink_to(outside, target_is_directory=True)
    warnings = []
    native = [dict(path=str(root / "apps" / "linked"), label="Previously recorded app", description="",
                   evidence=dict(type="native_application", path=str(root / "apps" / "linked" / "package.json")))]
    _, boundaries, _ = space._boundaries(root, warnings, 30, native)
    assert [boundary["relative"] for boundary in boundaries] == ["apps/linked"]
    assert any("Skipped linked application" in warning for warning in warnings)


@pytest.mark.parametrize("ancestor_only", [False, True])
def test_native_app_owner_is_unique_with_overlapping_ancestor_inventory_and_sources(tmp_path, monkeypatch, ancestor_only):
    container = tmp_path / "workspace"
    root = git(container / "clients" / "Orion" / "suite", "git@example.test:orion/suite.git")
    app = package(root / "apps" / "mobile", name="Mobile", scripts={"start": "never run"})
    indexed = [(container, "Workspace planning")]
    if not ancestor_only:
        indexed += [(container / "clients", "Clients"), (container / "clients" / "Orion", "Suite family"),
                    (root, "Product"), (app, "Mobile calibration")]
    conn = database(indexed)
    roots = [container] if ancestor_only else [container, root]
    sources = source_cache(tmp_path, roots)
    for number, source_root in enumerate(roots):
        relative = str(app.relative_to(source_root))
        structure = dict(application_candidates=[dict(root=relative, manifest=relative + "/package.json", name="Mobile",
                         entry_points=[dict(type="npm-script", name="npm run start", file="package.json")])],
                         token_groups=[dict(paths=[relative + "/auth.ts", relative + "/login.ts"],
                                            shared_tokens=["authorization", "mobile"], cohesion=.7)])
        (sources / "artifacts" / str(number) / "structure.json").write_text(json.dumps(structure))
    cache = tmp_path / "space.json"
    old = None
    if not ancestor_only:
        # Simulate a prior publication before canonical owner filtering.
        original = space._boundaries
        def unbound(root, warnings, maximum, native_apps=()):
            return original(root, warnings, maximum, [dict(app, owner_root="") for app in native_apps])
        with monkeypatch.context() as previous:
            previous.setattr(space, "_boundaries", unbound)
            old = space.refresh(API, conn, cache, source_cache=sources)
        assert len([node for node in old["entities"] if node["label"] == "Mobile"]) > 1
    data = space.refresh(API, conn, cache, source_cache=sources)
    apps = [node for node in data["entities"] if node["label"] == "Mobile"]
    assert len(apps) == 1
    node = apps[0]
    assert next(n for n in data["entities"] if n["id"] == node["parent_id"])["label"] == "Orion"
    assert dict(source_id="0", paths=["clients/Orion/suite/apps/mobile"]) in node["source_scopes"]
    if not ancestor_only:
        assert dict(source_id="1", paths=["apps/mobile"]) in node["source_scopes"]
        assert node["conversation_count"] == 1
        assert node["position"] == next(n for n in old["entities"] if n["id"] == node["id"])["position"]
    districts = [n for n in data["entities"] if n["kind"] == "district"]
    assert len(districts) == 1 and districts[0]["parent_id"] == node["id"]
    assert set(districts[0]["source_ids"]) == {str(number) for number in range(len(roots))}
    assert data["coverage"]["native_applications"]["candidates"] == len(roots)
    if ancestor_only:
        root.rename(root.with_name("offline"))
        after = space.refresh(API, conn, cache, source_cache=sources)
        same = next(n for n in after["entities"] if n["id"] == node["id"])
        assert same["parent_id"] == node["parent_id"] and same["position"] == node["position"]
    conn.close()


def test_legacy_ancestor_snapshot_keeps_only_retained_app_subtree(tmp_path):
    container = tmp_path / "workspace"
    root = git(container / "clients" / "Orion" / "suite")
    mobile = package(root / "apps" / "mobile", name="Mobile")
    package(root / "apps" / "dashboard", name="Dashboard")
    sources = source_cache(tmp_path, [container, root])
    candidates = [dict(root="apps/" + name, manifest="apps/" + name + "/package.json", name=label,
        entry_points=[dict(type="npm-script", name="npm run start", file="package.json")])
        for name, label in (("mobile", "Mobile"), ("dashboard", "Dashboard"))]
    relative = "clients/Orion/suite/apps/mobile"
    legacy = sources / "artifacts" / "0"
    retained = legacy / "source" / relative
    retained.mkdir(parents=True)
    (retained / "README.md").write_text("Retained legacy app document")
    (legacy / "structure.json").write_text(json.dumps(dict(token_groups=[dict(
        paths=[relative + "/auth.ts", relative + "/login.ts"], shared_tokens=["authorization", "mobile"], cohesion=.7)])))
    (sources / "artifacts" / "1" / "structure.json").write_text(json.dumps(dict(application_candidates=candidates, token_groups=[])))
    data = space.refresh(API, None, tmp_path / "space.json", source_cache=sources)
    apps = {node["label"]: node for node in data["entities"] if node["kind"] == "planet"}
    assert dict(source_id="0", paths=[relative]) in apps["Mobile"]["source_scopes"]
    assert "0" not in apps["Dashboard"]["source_ids"]
    districts = [node for node in data["entities"] if node["kind"] == "district"]
    assert len(districts) == 1 and districts[0]["parent_id"] == apps["Mobile"]["id"]


def test_nested_git_app_uses_nearest_repo_with_overlapping_native_sources(tmp_path):
    outer = git(tmp_path / "clients" / "Orion" / "suite")
    nested = git(outer / "LABS" / "experiment")
    app = package(nested / "apps" / "mobile", name="Mobile")
    sources = source_cache(tmp_path, [outer, nested])
    for number, source_root in enumerate((outer, nested)):
        relative = str(app.relative_to(source_root))
        structure = dict(application_candidates=[dict(root=relative, manifest=relative + "/package.json", name="Mobile",
            entry_points=[dict(type="npm-script", name="npm run start", file="package.json")])], token_groups=[])
        (sources / "artifacts" / str(number) / "structure.json").write_text(json.dumps(structure))
    data = space.refresh(API, None, tmp_path / "space.json", source_cache=sources)
    apps = [node for node in data["entities"] if node["label"] == "Mobile"]
    assert len(apps) == 1 and set(apps[0]["source_ids"]) == {"0", "1"}
    assert dict(source_id="0", paths=["LABS/experiment/apps/mobile"]) in apps[0]["source_scopes"]


def test_source_harvested_at_nested_app_keeps_native_root_candidate(tmp_path):
    root = git(tmp_path / "clients" / "Orion" / "suite")
    app = package(root / "apps" / "mobile", name="Mobile", scripts={"start": "never run"})
    sources = source_cache(tmp_path, [app])
    structure = dict(application_candidates=[dict(root=".", manifest="package.json", name="Mobile",
        entry_points=[dict(type="npm-script", name="npm run start", file="package.json")])], token_groups=[
        dict(paths=["auth.ts", "login.ts"], shared_tokens=["authorization", "mobile"], cohesion=.7)])
    (sources / "artifacts" / "0" / "structure.json").write_text(json.dumps(structure))
    conn = database([(app, "Mobile calibration")])
    data = space.refresh(API, conn, tmp_path / "space.json", source_cache=sources)
    mobile = next(node for node in data["entities"] if node["label"] == "Mobile")
    assert mobile["conversation_count"] == 1 and mobile["status"] == "candidate"
    assert dict(source_id="0", paths=["."]) in mobile["source_scopes"]
    districts = [node for node in data["entities"] if node["kind"] == "district"]
    assert len(districts) == 1 and districts[0]["parent_id"] == mobile["id"]
    conn.close()


def test_cached_native_app_link_cannot_discover_outside_git_owner(tmp_path):
    container = tmp_path / "container"
    container.mkdir()
    outside = git(tmp_path / "outside")
    package(outside, name="Must not inspect")
    (container / "linked").symlink_to(outside, target_is_directory=True)
    sources = source_cache(tmp_path, [container])
    structure = dict(application_candidates=[dict(root="linked", manifest="linked/package.json", name="Saved app",
        entry_points=[dict(type="npm-script", name="npm run start", file="package.json")])], token_groups=[])
    (sources / "artifacts" / "0" / "structure.json").write_text(json.dumps(structure))
    data = space.refresh(API, None, tmp_path / "space.json", source_cache=sources)
    assert data["coverage"]["inspected_roots"] == 1
    assert not any(location["path"] == str(outside) for node in data["entities"] for location in node["locations"])
    saved = next(node for node in data["entities"] if node["label"] == "Saved app")
    assert saved["locations"] and not saved["locations"][0]["available"]


@pytest.mark.parametrize("outer_git", [False, True])
@pytest.mark.parametrize("unavailable", ["missing", "linked"])
def test_ancestor_source_replaced_app_link_keeps_recorded_owner(tmp_path, outer_git, unavailable):
    container = tmp_path / "workspace"
    if outer_git:
        git(container)
    root = git(container / "clients" / "Orion" / "suite")
    app = package(root / "apps" / "mobile", name="Mobile")
    sources = source_cache(tmp_path, [container])
    relative = str(app.relative_to(container))
    structure = dict(application_candidates=[dict(root=relative, manifest=relative + "/package.json", name="Mobile",
        entry_points=[dict(type="npm-script", name="npm run start", file="package.json")])], token_groups=[])
    (sources / "artifacts" / "0" / "structure.json").write_text(json.dumps(structure))
    cache = tmp_path / "space.json"
    before = space.refresh(API, None, cache, source_cache=sources)
    mobile = next(node for node in before["entities"] if node["label"] == "Mobile")
    outside = git(tmp_path / "outside")
    if unavailable == "linked":
        app.rename(app.with_name("unavailable"))
        app.symlink_to(outside, target_is_directory=True)
    else:
        root.rename(root.with_name("unavailable"))
    after = space.refresh(API, None, cache, source_cache=sources)
    same = next(node for node in after["entities"] if node["id"] == mobile["id"])
    assert same["parent_id"] == mobile["parent_id"] and same["position"] == mobile["position"]
    assert not same["locations"][0]["available"]
    assert not any(location["path"] == str(outside) for node in after["entities"] for location in node["locations"])


@pytest.mark.parametrize("boundary", ["lab", "application", "native"])
def test_nested_git_boundary_keeps_existing_place_and_exact_evidence(tmp_path, monkeypatch, boundary):
    parent = git(tmp_path / "clients" / "Meridian" / "navigation", "git@example.test:meridian/navigation.git")
    relative = "LABS/tidal-cycle" if boundary == "lab" else "apps/tidal-cycle"
    child = git(parent / relative, "git@example.test:meridian/tidal-cycle.git")
    if boundary != "lab":
        package(parent, **({"workspaces": ["apps/*"]} if boundary == "application" else {}))
        package(child, name="Tidal measurements", scripts={"start": "node app.js"})
    other = git(tmp_path / "unrelated")
    conn = database([(parent, "Suite planning"), (child, "Cycle calibration"), (other, "Unrelated calibration")])
    cache = tmp_path / "space.json"
    sources = source_cache(tmp_path, [parent, child, other])
    for number, prefix in [(0, relative + "/"), (1, "")]:
        structure = dict(token_groups=[dict(paths=[prefix + "auth.py", prefix + "policy.py"],
                                           shared_tokens=["tidal", "access"], cohesion=.6)])
        if number == 0 and boundary == "native":
            structure["application_candidates"] = [dict(root=relative, manifest=relative + "/package.json",
                name="Tidal measurements", entry_points=[dict(type="npm-script", name="npm run start", file="package.json")])]
        (sources / "artifacts" / str(number) / "structure.json").write_text(json.dumps(structure))
    # Upgrade a publication created before reconciliation, including both old
    # places and both independently harvested districts.
    with monkeypatch.context() as before_fix:
        before_fix.setattr(space, "_reconcile_places", lambda *_: dict(merged=[], conflicts=[]))
        before = space.refresh(API, conn, cache, source_cache=sources)
    candidates = [n for n in before["entities"] if any(l["path"] == str(child) for l in n["locations"])]
    assert len(candidates) == 2
    destination = next(n for n in candidates if any(e["type"] in {"experiment_directory", "workspace_application", "native_application"} for e in n["evidence"]))
    previous_district = next(n for n in before["entities"] if n["kind"] == "district" and n["parent_id"] == destination["id"])
    data = space.refresh(API, conn, cache, source_cache=sources)
    candidates = [n for n in data["entities"] if any(l["path"] == str(child) for l in n["locations"])]
    assert len(candidates) == 1
    place = candidates[0]
    assert place["id"] == destination["id"] and place["position"] == destination["position"]
    assert place["parent_id"] == destination["parent_id"]
    assert place["kind"] == ("moon" if boundary == "lab" else "planet")
    assert place["conversation_count"] == 1 and len(place["conversation_collections"]) == 1
    assert len(place["locations"]) == 1 and set(place["source_ids"]) == {"0", "1"}
    assert dict(source_id="0", paths=[relative]) in place["source_scopes"]
    assert dict(source_id="1", paths=["."]) in place["source_scopes"]
    assert any(e.get("basis") == "Git origin" for e in place["evidence"])
    assert "unassigned" not in place.get("ownership", "")
    districts = [n for n in data["entities"] if n["kind"] == "district"]
    assert len(districts) == 1
    assert districts[0]["id"] == previous_district["id"] and districts[0]["position"] == previous_district["position"]
    assert set(districts[0]["source_ids"]) == {"0", "1"}
    assert {tuple(command[-2:]) for command in districts[0]["commands"]["source_search"]} == {
        ("--path", relative + "/policy.py"), ("--path", "policy.py")}
    assert next(n for n in data["entities"] if n["id"] == space.GALAXY)["conversation_count"] == 3
    assert not space.view(cache, action="search", within=place["id"], query="Unrelated")["nodes"]
    assert all(edge["source"] == next(n for n in data["entities"] if n["id"] == edge["target"])["parent_id"]
               for edge in data["edges"] if edge["relation"] == "contains")
    after = space.refresh(API, conn, cache, source_cache=sources)
    same = next(n for n in after["entities"] if n["id"] == place["id"])
    assert same["position"] == place["position"] and same["conversation_count"] == 1
    conn.close()


def test_exact_suite_container_receives_its_conversations_without_product_guess(tmp_path):
    suite = tmp_path / "clients" / "Meridian"
    product = git(suite / "navigation")
    other = git(tmp_path / "different" / "Meridian")
    conn = database([(suite, "Suite strategy"), (product, "Product work"), (other, "Same name elsewhere")])
    cache = tmp_path / "space.json"
    data = space.refresh(API, conn, cache)
    system = next(n for n in data["entities"] if n["kind"] == "system" and n["label"] == "Meridian")
    assert system["direct_conversation_count"] == 1 and system["conversation_count"] == 2
    assert system["examples"] == ["Suite strategy"]
    assert not any(n["kind"] == "planet" and any(l["path"] == str(suite) for l in n["locations"]) for n in data["entities"])
    assert len([n for n in data["entities"] if n["kind"] == "planet"]) == 2
    assert len(system["conversation_collections"]) == 2
    assert not space.view(cache, action="search", within=system["id"], query="Same name elsewhere")["nodes"]
    assert data["coverage"]["reconciliation"]["merged"][0]["basis"] == "exact_client_container"
    conn.close()


@pytest.mark.parametrize("evidence", ["git", "package", "declaration"])
def test_suite_named_product_is_preserved_when_it_has_product_evidence(tmp_path, evidence):
    suite = tmp_path / "clients" / "Meridian"
    git(suite / "nested")
    if evidence == "git":
        git(suite)
    elif evidence == "package":
        package(suite, name="Suite portal", scripts={"start": "node app.js"})
    else:
        (suite / ".navcom-space.json").write_text(json.dumps(dict(label="Declared product")))
    conn = database([(suite, "Suite context"), (suite / "nested", "Nested context")])
    data = space.refresh(API, conn, tmp_path / "space.json")
    assert any(n["kind"] == "planet" and any(l["path"] == str(suite) for l in n["locations"]) for n in data["entities"])
    assert not data["coverage"]["reconciliation"]["merged"]
    conn.close()


def test_conflicting_nested_owner_declaration_remains_visible(tmp_path):
    root = git(tmp_path / "suite")
    child = git(root / "LABS" / "experiment")
    (child / ".navcom-space.json").write_text(json.dumps(dict(label="Independent product", id="declared-product", kind="planet")))
    conn = database([(root, "Parent"), (child, "Owner defined")])
    data = space.refresh(API, conn, tmp_path / "space.json")
    assert len([n for n in data["entities"] if any(l["path"] == str(child) for l in n["locations"])]) == 2
    assert len(data["coverage"]["reconciliation"]["conflicts"]) == 1
    assert not data["coverage"]["reconciliation"]["merged"]
    assert any(n["label"] == "Independent product" and n["status"] == "established" for n in data["entities"])
    conn.close()


def test_cross_contained_repository_copies_do_not_create_reconciliation_cycle(tmp_path):
    first = git(tmp_path / "first", "git@example.test:unfamiliar/first.git")
    second = git(tmp_path / "second", "git@example.test:unfamiliar/second.git")
    second_copy = git(first / "LABS" / "second", "git@example.test:unfamiliar/second.git")
    first_copy = git(second / "LABS" / "first", "git@example.test:unfamiliar/first.git")
    conn = database([(first, "First"), (second, "Second"), (second_copy, "Second experiment"), (first_copy, "First experiment")])
    data = space.refresh(API, conn, tmp_path / "space.json")
    assert len(data["coverage"]["reconciliation"]["conflicts"]) == 2
    assert not data["coverage"]["reconciliation"]["merged"]
    assert all("cycle" in conflict["reason"] for conflict in data["coverage"]["reconciliation"]["conflicts"])
    assert next(n for n in data["entities"] if n["id"] == space.GALAXY)["conversation_count"] == 4
    conn.close()


def test_reconciled_lab_keeps_recorded_parent_when_nested_repository_goes_offline(tmp_path):
    root = git(tmp_path / "navigation")
    child = git(root / "LABS" / "cycle")
    conn = database([(root, "Parent"), (child, "Cycle investigation")])
    cache = tmp_path / "space.json"
    before = space.refresh(API, conn, cache)
    moon = next(n for n in before["entities"] if n["kind"] == "moon")
    child.rename(tmp_path / "offline-cycle")
    after = space.refresh(API, conn, cache)
    same = next(n for n in after["entities"] if n["id"] == moon["id"])
    assert same["parent_id"] == moon["parent_id"] and same["position"] == moon["position"]
    assert same["conversation_count"] == 1 and same["locations"][0]["available"] is False
    assert any(e["type"] == "previous_boundary" and e["status"] == "unavailable" for e in same["evidence"])
    assert "unassigned" not in same.get("ownership", "")
    again = space.refresh(API, conn, cache)
    still_offline = next(n for n in again["entities"] if n["id"] == moon["id"])
    assert still_offline["parent_id"] == moon["parent_id"]
    assert next(e for e in still_offline["evidence"] if e["type"] == "previous_boundary")["observed_at"] == before["published"]
    conn.close()


def test_worktrees_without_remote_share_common_git_identity(tmp_path):
    root = git(tmp_path / "repository")
    subprocess.run(["git", "-C", str(root), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "--allow-empty", "-qm", "fixture"], check=True)
    worktree = tmp_path / "worktree"
    subprocess.run(["git", "-C", str(root), "worktree", "add", "--detach", "-q", str(worktree)], check=True)
    conn = database([(root, "Captain"), (worktree, "Provider child")])
    data = space.refresh(API, conn, tmp_path / "space.json")
    planets = [n for n in data["entities"] if n["kind"] == "planet"]
    assert len(planets) == 1 and len(planets[0]["locations"]) == 2
    assert all(n["kind"] != "moon" for n in data["entities"])
    conn.close()


def test_starforge_groups_make_scoped_districts_and_source_only_destinations(tmp_path):
    root = git(tmp_path / "dev" / "lighthouse")
    package(root, name="Lighthouse", workspaces=["apps/*"])
    app = package(root / "apps" / "public", name="Public portal", scripts={"start": "node app.js"})
    groups = [dict(paths=["apps/public/auth/login.ts", "apps/public/auth/policy.ts"], shared_tokens=["authentication", "policy"], cohesion=.5),
              dict(paths=["shared.ts", "apps/public/auth/login.ts"], shared_tokens=["mixed"], cohesion=.5),
              dict(paths=["a", "b"], shared_tokens=["weak"], cohesion=.001)]
    source = source_cache(tmp_path, [root], groups)
    cache = tmp_path / "space.json"
    data = space.refresh(API, None, cache, source_cache=source)
    nodes = {n["label"]: n for n in data["entities"]}
    district = nodes["policy · authentication"]
    assert district["parent_id"] == nodes["Public portal"]["id"]
    assert district["status"] == "suggested" and district["conversation_count"] == 0
    assert district["evidence"][0]["type"] == "starforge_token_group"
    assert district["commands"]["source_search"][0] == ["navcom", "sources", "search", "<query>", "--within", "0", "--path", "apps/public/auth/login.ts", "--path", "apps/public/auth/policy.ts"]
    assert nodes["Public portal"]["commands"]["source_search"][0][-2:] == ["--path", "apps/public"]
    assert data["coverage"]["rejected_token_groups"] == 2
    assert space.view(cache, kind="cities")["total"] == 1
    assert nodes["Public portal"]["locations"][0]["path"] == str(app)


def test_cached_queries_keep_positions_and_never_touch_repositories(tmp_path, monkeypatch):
    root = git(tmp_path / "clients" / "Lyra" / "Maple")
    conn = database([(root, "Maple login")])
    cache = tmp_path / "space.json"
    data = space.refresh(API, conn, cache)
    before = {n["id"]: n["position"] for n in data["entities"]}
    monkeypatch.setattr(space, "_repository", lambda *_: pytest.fail("Cached navigation inspected Git"))
    monkeypatch.setattr(space, "_boundaries", lambda *_: pytest.fail("Cached navigation inspected source"))
    for query in ("Maple", "login", "missing"):
        for node in space.view(cache, action="search", query=query)["nodes"]:
            assert node["position"] == before[node["id"]]
    with cache.with_suffix(".json.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert space.view(cache, kind="planets")["total"] == 1
        with pytest.raises(RuntimeError, match="Another spatial refresh"):
            space.refresh(API, conn, cache)
        fcntl.flock(lock, fcntl.LOCK_UN)
    conn.close()


def test_harvested_clues_clean_titles_and_honest_product_history(tmp_path):
    root = git(tmp_path / "clients" / "Juniper" / "Beacon")
    package(root, name="internal-package", workspaces=["apps/*"])
    app = package(root / "apps" / "portal", name="Portal", scripts={"start": "node main.js"})
    other = package(root / "apps" / "ledger", name="Ledger", scripts={"start": "node main.js"})
    groups = [dict(paths=["apps/portal/login.py", "apps/portal/policy.py"], shared_tokens=["exist_ok", "prepare"], cohesion=.5)]
    sources = source_cache(tmp_path, [root], groups)
    artifact = sources / "artifacts" / "0"
    snapshot = artifact / "source"
    (snapshot / "apps" / "portal").mkdir(parents=True)
    (snapshot / "README.md").write_text("# Beacon\nCoordinates optical measurement campaigns.\n")
    (snapshot / "apps" / "portal" / "README.md").write_text("# Portal\nBook instruments and review sensor readings.\n")
    (artifact / "catalog.json").write_text(json.dumps({"projects": {"1": {"summary": "Native analysis of optical measurement orchestration.", "tech_stack": ["Python"]}}}))
    conn = database([(root, "<app-context>Tooling and account state</app-context> Calibrate instruments"),
                     (app, "<realtime_delegation><input>Plan login policy</input><transcript_delta>Noise</transcript_delta></realtime_delegation>"),
                     (other, "Ledger policy for unrelated product")])
    cache = tmp_path / "space.json"
    data = space.refresh(API, conn, cache, source_cache=sources)
    nodes = {n["label"]: n for n in data["entities"]}
    assert nodes["Beacon"]["examples"] == ["Calibrate instruments"]
    assert nodes["Portal"]["examples"] == ["Plan login policy"]
    assert "optical measurement" in nodes["Beacon"]["description"]
    assert "Book instruments" in nodes["Portal"]["description"]
    assert {clue["basis"] for clue in nodes["Beacon"]["clues"]} == {"harvested_readme", "starforge_project_analysis"}
    district = nodes["login · policy"]
    assert district["label_basis"] == "grouped_filenames"
    assert district["evidence"][0]["shared_tokens"] == ["exist_ok", "prepare"]
    assert "apps/portal/login.py" in district["description"]
    assert district["conversation_count"] == district["direct_conversation_count"] == 0
    assert nodes["Portal"]["conversation_count"] == 1
    assert district["conversation_collections"] == nodes["Portal"]["conversation_collections"]
    assert not set(district["conversation_collections"]) & set(nodes["Ledger"]["conversation_collections"])
    assert district["conversation_basis"]["file_relationship"] == "unproven"
    assert district["commands"]["conversation_search"][0][3] == "login policy"
    position = district["position"]
    assert space.view(cache, action="search", within=nodes["Portal"]["id"], query="login")["nodes"][0]["position"] == position
    assert next(n for n in space.refresh(API, conn, cache, source_cache=sources)["entities"] if n["id"] == district["id"])["position"] == position
    conn.close()


def test_empty_context_title_recovers_authored_indexed_excerpt(navcom, tmp_path, monkeypatch):
    from test_atlas import add
    monkeypatch.setattr(navcom, "INDEX_READ_ONLY", False)
    root = git(tmp_path / "optical-suite")
    conn = navcom.open_index(tmp_path / "index.sqlite")
    key = add(navcom, conn, tmp_path / "conversation.jsonl", "Inspect optical calibration", "for the next instrument campaign", str(root))
    conn.execute("UPDATE file_meta SET title=? WHERE file=?", ("<in-app-context>Application boilerplate that was truncated", key))
    conn.commit()
    data = space.refresh(navcom, conn, tmp_path / "space.json")
    planet = next(n for n in data["entities"] if n["kind"] == "planet")
    assert planet["examples"] == ["Inspect optical calibration for the next instrument campaign"]
    conn.close()


def test_offline_root_keeps_identity_and_discloses_limits_and_missing_structure(tmp_path):
    root = git(tmp_path / "dev" / "exp77-novel", "git@example.test:lab/novel.git")
    conn = database([(root, "Novel experiment")])
    source = source_cache(tmp_path, [root])
    cache = tmp_path / "space.json"
    data = space.refresh(API, conn, cache, source_cache=source)
    moon = next(n for n in data["entities"] if n["kind"] == "moon")
    assert moon["parent_id"] == space.INDEPENDENT
    assert "unassigned" in moon["ownership"]
    root.rename(root.with_name("offline"))
    after = space.refresh(API, conn, cache, source_cache=source)
    same = next(n for n in after["entities"] if n["id"] == moon["id"])
    assert same["locations"][0]["available"] is False
    assert str(root) in after["coverage"]["unavailable_roots"]
    assert after["coverage"]["missing_structure_sources"] == ["0"]
    assert "no historical" in after["coverage"]["history"]
    conn.close()


def test_declared_owner_override_and_validation_are_explicit(tmp_path):
    root = git(tmp_path / "dev" / "quartz")
    (root / ".navcom-space.json").write_text(json.dumps(dict(kind="planet", label="Quartz product", id="quartz", system=dict(id="venture", label="Venture suite"))))
    conn = database([(root, "Working")])
    cache = tmp_path / "space.json"
    data = space.refresh(API, conn, cache)
    assert all(n["status"] == "established" for n in data["entities"])
    assert space.view(cache, action="show", within="Quartz product")["nodes"][0]["label"] == "Quartz product"
    with pytest.raises(ValueError, match="not found"):
        space.view(cache, within="Quartz")
    with pytest.raises(ValueError, match="Unknown spatial kind"):
        space.view(cache, kind="unicorns")
    with pytest.raises(ValueError, match="limit"):
        space.view(cache, limit=0)
    with pytest.raises(ValueError, match="unavailable"):
        space.view(tmp_path / "missing.json")
    conn.close()


def test_fleet_records_keep_physical_plane_separate_and_readiness_unknown(tmp_path, monkeypatch):
    root = git(tmp_path / "dev" / "product")
    bridge = tmp_path / "starship" / "bridge"
    bridge.mkdir(parents=True)
    (bridge / "data.json").write_text(json.dumps(dict(base="/Volumes/TestFleet", destination="Archive base", generated="2026-10-01", ships=[dict(name="Context vessel", sources=[str(root)], destination="ships/context", state="passed historic receiving test")])))
    monkeypatch.setenv("NAVCOM_STARSHIP_ROOT", str(bridge.parent))
    conn = database([(root, "Product context")])
    data = space.refresh(API, conn, tmp_path / "space.json")
    ship = next(n for n in data["entities"] if n["kind"] == "ship")
    base = next(n for n in data["entities"] if n["kind"] == "starbase")
    product = next(n for n in data["entities"] if n["kind"] == "planet")
    assert ship["parent_id"] == base["id"] and base["parent_id"] == space.GALAXY
    assert product["parent_id"] != base["id"]
    assert ship["readiness"]["status"] == "unknown"
    assert ship["physical"]["availability"] == "unobserved"
    assert any(e["source"] == ship["id"] and e["target"] == product["id"] and e["relation"] == "relates_to" for e in data["edges"])
    assert "board" not in ship["commands"]
    assert data["coverage"]["fleet"]["live_checks"] is False
    conn.close()


def test_root_folder_is_primary_label_and_package_identity_stays_searchable(tmp_path):
    root = git(tmp_path / "clients" / "Aster" / "RecognizablePortal")
    package(root, name="internal-web-interface", description="Portal implementation")
    conn = database([(root, "Portal work")])
    cache = tmp_path / "space.json"
    data = space.refresh(API, conn, cache)
    product = next(n for n in data["entities"] if n["kind"] == "planet")
    assert product["label"] == "RecognizablePortal"
    assert product["package_name"] == "internal-web-interface"
    assert any(e.get("type") == "package_manifest" and e["name"] == "internal-web-interface" for e in product["evidence"])
    assert [n["id"] for n in space.view(cache, action="search", query="internal-web-interface")["nodes"]] == [product["id"]]
    (root / ".navcom-space.json").write_text(json.dumps(dict(kind="planet", label="Owner chosen name")))
    corrected = space.refresh(API, conn, cache)
    assert next(n for n in corrected["entities"] if n["kind"] == "planet")["label"] == "Owner chosen name"
    conn.close()


def test_removed_tool_worktrees_require_live_enclosing_git_evidence(tmp_path):
    root = git(tmp_path / "clients" / "Aster" / "Portal", "git@example.test:aster/portal.git")
    managed = root / ".claude" / "worktrees" / "agent-gone"
    peer = root / ".peerlab" / "peer-a-codex"
    arbitrary = root / "old-product"
    unverified = tmp_path / "no-repository" / ".claude" / "worktrees" / "agent-gone"
    conn = database([(root, "Current"), (managed, "Old agent"), (peer, "Old peer"), (arbitrary, "Other product"), (unverified, "Unknown")])
    data = space.refresh(API, conn, tmp_path / "space.json")
    planets = [n for n in data["entities"] if n["kind"] == "planet"]
    assert len(planets) == 3
    product = next(n for n in planets if n["label"] == "Portal")
    assert product["conversation_count"] == 3
    managed_evidence = [e for e in product["evidence"] if e["type"] == "managed_worktree_location"]
    assert {e["path"] for e in managed_evidence} == {str(managed), str(peer)}
    assert all(e["status"] == "suggested" and "unverified" in e["basis"] for e in managed_evidence)
    assert {loc["path"] for loc in product["locations"] if not loc["available"]} == {str(managed), str(peer)}
    assert any(n["label"] == "old-product" and "Unavailable" in n["description"] for n in planets)
    assert any(n["label"] == "agent-gone" and "Unavailable" in n["description"] for n in planets)
    conn.close()


def test_legacy_index_without_lazy_metadata_keeps_project_without_index_writes(navcom, tmp_path, monkeypatch):
    monkeypatch.setattr(navcom, "INDEX_READ_ONLY", False)
    root = tmp_path / "clients" / "Fresh" / "Product"
    root.mkdir(parents=True)
    log = tmp_path / "rollout-2026-10-16T01-00-00-fresh.jsonl"
    log.write_text(json.dumps(dict(type="session_meta", payload=dict(id="fresh", cwd=str(root)))) + "\n" +
                   json.dumps(dict(type="response_item", payload=dict(type="message", role="user", content=[dict(type="input_text", text="A freshly indexed product conversation")]))))
    conn = navcom.open_index(tmp_path / "index.sqlite")
    navcom.index_logs(conn, [(str(log), 1700000000, log.stat().st_size, "codex")], progress=False)
    # Simulate a pre-timestamp index whose lazy project metadata was never filled.
    conn.execute("DELETE FROM file_meta"); conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM file_meta").fetchone()[0] == 0
    data = space.refresh(navcom, conn, tmp_path / "space.json")
    assert any(n["label"] == "Product" and n["kind"] == "planet" for n in data["entities"])
    assert data["coverage"]["metadata_fallbacks"] == 1
    assert conn.execute("SELECT COUNT(*) FROM file_meta").fetchone()[0] == 0
    assert not conn.in_transaction
    conn.close()


def star_record(root, *, identity="star-candidate:unfamiliar", qualification="declared_candidate"):
    metadata = root / "expert"
    return dict(id=identity, kind="star_candidate", provider="hermes-compose", provider_identity=str(metadata / "compose.yaml") + "#expert",
                name="Tidal evidence expert", description="Maintains tidal measurement evidence", qualification=qualification,
                description_auto=False, evidence=[str(metadata / "compose.yaml")], charter_refs=[str(metadata / "SOUL.md")],
                physical_binding=dict(kind="compose_service", repository=str(root), compose=str(metadata / "compose.yaml"), service="expert"),
                interfaces=[dict(effect="inspect", transport="metadata"), dict(effect="ask_agent", transport="argv_template", argv=["docker", "exec", "tidal-worker", "hermes", "chat", "-q", "{question}"])],
                availability=dict(state="unknown", checked_at=None), gaps=["Runtime has not been observed"], source_ids=[])


def test_star_candidates_are_cross_system_destinations_with_exact_implementation_scope(tmp_path, monkeypatch):
    import navcom_stars
    suite = git(tmp_path / "clients" / "Arbor" / "suite")
    package(suite, workspaces=["apps/*"])
    first = package(suite / "apps" / "coast", name="Coastal measurements", scripts={"start": "node app.js"})
    second = package(suite / "apps" / "inland", name="Inland measurements", scripts={"start": "node app.js"})
    conn = database([(first, "Tidal calibration"), (second, "Tidal expert mentioned in a different product")])
    sources = source_cache(tmp_path, [suite])
    declared = star_record(first)
    incomplete = star_record(second, identity="star-candidate:incomplete", qualification="incomplete")
    calls = []
    def discover(roots, cache, **kwargs):
        calls.append((roots, cache, kwargs))
        return dict(candidates=[declared, incomplete], coverage=dict(complete=True), gaps=[], excluded=[],
                    observed_at=1234, fingerprint="metadata-fingerprint", cache_hit=True)
    monkeypatch.setattr(navcom_stars, "discover", discover)
    cache = tmp_path / "space.json"
    data = space.refresh(API, conn, cache, source_cache=sources)
    stars = [node for node in data["entities"] if node["kind"] == "star"]
    assert len(stars) == 1
    star = stars[0]
    coast = next(node for node in data["entities"] if node["label"] == "Coastal measurements")
    inland = next(node for node in data["entities"] if node["label"] == "Inland measurements")
    assert star["id"] == declared["id"] and star["parent_id"] == space.GALAXY
    assert star["status"] == "candidate" and star["qualification"] == "declared_candidate"
    assert star["availability"]["state"] == "unknown" and star["star"]["interfaces"] == declared["interfaces"]
    assert star["observed_at"] == 1234 and star["discovery_fingerprint"] == "metadata-fingerprint"
    assert star["source_scopes"] == [dict(source_id="0", paths=["apps/coast/expert"])]
    assert star["commands"]["source_search"][0][-2:] == ["--path", "apps/coast/expert"]
    assert star["related_product_ids"] == [coast["id"]]
    assert star["conversation_collections"] == coast["conversation_collections"]
    assert set(star["conversation_collections"]).isdisjoint(inland["conversation_collections"])
    assert star["conversation_count"] == star["direct_conversation_count"] == 0
    assert star["conversation_basis"]["file_relationship"] == "unproven"
    assert next(node for node in data["entities"] if node["id"] == space.GALAXY)["conversation_count"] == 2
    assert any(edge["source"] == star["id"] and edge["target"] == coast["id"] and edge["relation"] == "relates_to" for edge in data["edges"])
    assert data["coverage"]["stars"]["excluded"][0]["candidate"]["id"] == incomplete["id"]
    assert calls[0][2]["profile_home"] == tmp_path / "no-native-profiles"
    before = star["position"]
    refreshed = space.refresh(API, conn, cache, source_cache=sources)
    assert next(node for node in refreshed["entities"] if node["id"] == star["id"])["position"] == before
    monkeypatch.setattr(navcom_stars, "discover", lambda *_args, **_kwargs: pytest.fail("Cached chart attempted provider discovery"))
    assert space.view(cache, kind="stars")["nodes"][0]["position"] == before
    assert space.view(cache, action="search", query="tidal evidence")["nodes"][0]["id"] == star["id"]
    assert not space.view(cache, kind="stars", within=coast["id"])["nodes"]
    conn.close()


def test_star_discovery_pages_all_roots_and_native_profiles_once(tmp_path, monkeypatch):
    import navcom_stars
    roots = [str(tmp_path / ("source-" + str(i).zfill(3))) for i in range(125)]
    source_by_root = {roots[-1]: [dict(id="harvested", root=roots[-1])]}
    calls = []
    def discover(batch, cache, **kwargs):
        calls.append((batch, kwargs))
        return dict(candidates=[], coverage=dict(complete=True), gaps=[], excluded=[], observed_at=1, fingerprint="x")
    monkeypatch.setattr(navcom_stars, "discover", discover)
    records, coverage = space._star_inventory(roots, source_by_root, tmp_path / "space.json", {})
    assert not records and coverage["complete"]
    assert coverage["roots_attempted"] == 125 and not coverage["unvisited_roots"]
    assert len(calls) == 13 and calls[0][0][0] == dict(id="harvested", root=roots[-1])
    assert {row["root"] for batch, _ in calls for row in batch} == set(roots)
    assert sum(kwargs["profile_home"] is not None for _, kwargs in calls) == 1
    assert all(len(batch) <= space.STAR_BATCH_ROOTS for batch, _ in calls)


def test_star_discovery_deadline_resumes_and_preserves_unvisited_dated_evidence(tmp_path, monkeypatch):
    import navcom_stars
    roots = [str(tmp_path / ("root-" + str(i).zfill(3))) for i in range(25)]
    clock = [0.]
    monkeypatch.setattr(space, "STAR_DISCOVERY_SECONDS", .5)
    monkeypatch.setattr(space.time, "monotonic", lambda: clock[0])
    calls = []
    def discover(batch, cache, **kwargs):
        calls.append(batch)
        clock[0] += .4
        return dict(candidates=[], coverage=dict(complete=True), gaps=[], excluded=[], observed_at=1, fingerprint="x")
    monkeypatch.setattr(navcom_stars, "discover", discover)
    old = star_record(Path(roots[-1]))
    records, coverage = space._star_inventory(roots, {}, tmp_path / "space.json", dict(entities=[dict(star=old)]))
    assert coverage["roots_attempted"] == 10 and coverage["resume_root"] == roots[10]
    assert len(coverage["unvisited_roots"]) == 15 and not coverage["complete"]
    assert records[0]["id"] == old["id"] and records[0]["metadata_refresh"] == "not_refreshed"
    clock[0] = 0.
    _, continued = space._star_inventory(roots, {}, tmp_path / "space.json", dict(coverage=dict(stars=coverage)))
    assert calls[-1][0]["root"] == roots[10]
    assert continued["resume_root"] == roots[20]


def test_optional_provider_failure_keeps_dated_candidates_without_claiming_runtime(tmp_path, monkeypatch):
    import navcom_stars
    root = str(tmp_path / "coast")
    home = tmp_path / "no-native-profiles"
    compose = star_record(Path(root))
    profile = dict(star_record(Path(root), identity="star-candidate:profile"),
                   physical_binding=dict(kind="local_profile", path=str(home), hermes_home=str(home)))
    previous = dict(entities=[dict(star=compose), dict(star=profile)])
    monkeypatch.setattr(navcom_stars, "discover", lambda *_args, **_kwargs: dict(
        candidates=[], coverage=dict(complete=False), gaps=["Metadata runtime unavailable"], excluded=[]))
    records, coverage = space._star_inventory([root], {}, tmp_path / "space.json", previous)
    assert {record["id"] for record in records} == {compose["id"], profile["id"]}
    assert all(record["metadata_refresh"] == "not_refreshed" and record["availability"]["state"] == "unknown" for record in records)
    assert coverage["deferred_roots"] == [root] and coverage["resume_root"] is None
    assert not coverage["profile_metadata_refreshed"] and coverage["retained_unvisited_candidates"] == 2


def test_star_discovery_excludes_ancestor_containers_and_isolates_unreadable_root(tmp_path, monkeypatch):
    import navcom_stars
    cache = tmp_path / "published" / "space.json"
    good = str(tmp_path / "good-project")
    bad = str(tmp_path / "bad-project")
    broad = ["/", str(Path.home()), str(tmp_path)]
    calls = []
    candidate = star_record(Path(good))
    def discover(batch, cache_path, **kwargs):
        paths = [row["root"] for row in batch]
        calls.append(paths)
        assert not set(paths) & set(broad)
        if bad in paths:
            raise PermissionError("Fixture unavailable folder")
        return dict(candidates=[candidate] if good in paths else [], coverage=dict(complete=True), gaps=[], excluded=[])
    monkeypatch.setattr(navcom_stars, "discover", discover)
    records, coverage = space._star_inventory(broad + [bad, good], {}, cache, {})
    assert [record["id"] for record in records] == [candidate["id"]]
    assert coverage["roots_requested"] == 5 and coverage["roots_eligible"] == 2
    assert coverage["roots_attempted"] == 2 and coverage["isolated_batches"] == 1
    assert {row["path"] for row in coverage["excluded_roots"]} == set(broad)
    assert coverage["deferred_roots"] == [bad] and not coverage["unvisited_roots"]
    assert coverage["resume_root"] is None
    assert [good] in calls


def test_native_unfamiliar_expert_falls_out_of_normal_spatial_refresh(tmp_path):
    provider = Path.home() / ".hermes/hermes-agent"
    detectors = Path.home() / ".codex/skills/ship-commission/scripts/borrowed"
    if not (provider / "venv/bin/python").is_file() or not (detectors / "build_systems.py").is_file():
        pytest.skip("Optional installed Hermes and Starship metadata runtimes are absent")
    root = git(tmp_path / "unfamiliar-coast-lab")
    metadata = root / "expert"
    metadata.mkdir()
    (metadata / "compose.yaml").write_text("services:\n  observer:\n    build: .\n    container_name: unfamiliar-coastal-observer\n")
    (metadata / "Dockerfile").write_text('FROM nousresearch/hermes-agent:v1\nLABEL org.opencontainers.image.title="Coastal evidence" org.opencontainers.image.description="Maintains coastal measurements"\n')
    (metadata / "SOUL.md").write_text("# Coastal evidence\nMaintain measured observations and provenance.\n")
    sources = source_cache(tmp_path, [root])
    cache = tmp_path / "space.json"
    data = space.refresh(API, None, cache, source_cache=sources)
    star = next(node for node in data["entities"] if node["kind"] == "star")
    assert star["label"] == "Coastal evidence" and star["parent_id"] == space.GALAXY
    assert star["source_scopes"] == [dict(source_id="0", paths=["expert"])]
    assert star["availability"]["state"] == "unknown" and not data["coverage"]["stars"]["live_checks"]
    refreshed = space.refresh(API, None, cache, source_cache=sources)
    assert refreshed["coverage"]["stars"]["batches"][0]["cache_hit"]


@pytest.mark.parametrize("race", [ProcessLookupError, PermissionError])
def test_kill_group_tolerates_a_group_that_exits_first(monkeypatch, race):
    """macOS reports EPERM (zombie-only group) or ESRCH when the worker wins the race."""
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], start_new_session=True)
    def raced(pid, sig):
        os.kill(pid, signal.SIGKILL)  # the group dies just before our kill
        raise race()
    monkeypatch.setattr(space.os, "killpg", raced)
    space.kill_group(process)
    assert process.returncode is not None
    space.kill_group(process)  # already reaped: nothing to do
