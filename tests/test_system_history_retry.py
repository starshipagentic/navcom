"""Bounded recovery derives a new historical session without moving its pins."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

import navcom_history as history
import navcom_system_history as system


def make_repo(root, *, large=False):
    root.mkdir()
    def git(*args, date="2025-03-01T00:00:00Z"):
        env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1",
                   GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date)
        return subprocess.run(["git", "-C", str(root), "-c", "user.name=Fixture", "-c",
                               "user.email=fixture@example.invalid", "-c", "commit.gpgsign=false",
                               "-c", "core.hooksPath="+os.devnull, *args],
                              env=env, capture_output=True, text=True, check=True).stdout.strip()
    git("init", "-q", "-b", "main")
    (root/"package.json").write_text(json.dumps(dict(name=root.name+"-original")))
    (root/"README.md").write_text("# Orchard field observations\n\nRecorded seasonal evidence.\n")
    (root/"notes").mkdir()
    size = 1024*1024 if large else 64
    for index in range(18 if large else 1):
        prefix = "# Orchard observations\n\n"
        line = "The coastal orchard records seasonal water and soil measurements.\n"
        (root/"notes"/f"field-{index:02}.md").write_text(prefix + line*((size-len(prefix))//len(line)))
    git("add", "."); git("commit", "-qm", "Recorded field research")
    return root, git("rev-parse", "HEAD"), git


@pytest.fixture
def retry_fixture(tmp_path):
    small = make_repo(tmp_path/"a-lantern")
    large = make_repo(tmp_path/"z-orchard", large=True)
    galaxy = dict(id="galaxy:owner", kind="galaxy", label="Owner", parent_id=None,
                  position=dict(x=0,y=0), locations=[], evidence=[])
    nodes = [galaxy]
    for index, (name, root) in enumerate((("lantern",small[0]),("orchard",large[0]),("notes",large[0]/"notes"))):
        nodes.append(dict(id="planet:"+name,kind="planet",label="CURRENT "+name,parent_id=galaxy["id"],
                          position=dict(x=100+index*30,y=200),locations=[dict(path=str(root))],evidence=[]))
    chart = tmp_path/"space.json"
    chart.write_text(json.dumps(dict(schema_version=1,published=1,entities=nodes,edges=[],coverage={})))
    return dict(space_cache=chart, cache_path=tmp_path/"history", small=small, large=large)


def args(fixture):
    return {key:fixture[key] for key in ("space_cache","cache_path")}


def saved_files(folder):
    return {str(path.relative_to(folder)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in folder.rglob("*") if path.is_file()}


@pytest.mark.skipif(not shutil.which("starforge"), reason="Optional native Starforge required")
def test_native_large_snapshot_recovery_keeps_pins_and_reuses_valid_success(retry_fixture, monkeypatch):
    fixture=retry_fixture
    initial = system.view("galaxy:owner", "2025-04-01", seconds=60, **args(fixture))
    assert initial["retry_larger_available"] and initial["retry_larger_command"].endswith(" --retry-larger")
    failure = next(row for row in initial["repositories"] if row.get("error"))
    assert failure["coverage"]["snapshot_budget_failure"]["dimensions"] == ["max_bytes"]
    assert initial["snapshot_budgets"] == system.DEFAULT_BUDGETS
    assert not initial["derived_from_session_id"]
    old_dir = fixture["cache_path"]/"systems"/initial["session_id"]
    old_files = saved_files(old_dir)
    old_plan = json.loads((old_dir/"plan.json").read_text())
    root, old_commit, git = fixture["large"]
    (root/"package.json").write_text('{"name":"NEW UNPINNED HEAD"}')
    git("add", "package.json"); git("commit", "-qm", "Later HEAD before cutoff", date="2025-03-15T00:00:00Z")
    assert git("rev-parse", "HEAD") != old_commit
    (root/"README.md").write_text("DIRTY FUTURE CONTENT\n")
    # Current ownership, labels and camera addresses must not enter the fork.
    current = json.loads(fixture["space_cache"].read_text())
    current["entities"][1]["position"] = dict(x=999,y=999)
    current["entities"][1]["label"] = "CHANGED CURRENT LABEL"
    fixture["space_cache"].write_text(json.dumps(current))
    original_run = system._run
    calls = []
    def observed(request, seconds):
        calls.append((request["action"], request.get("repository")))
        return original_run(request, seconds)
    monkeypatch.setattr(system, "_run", observed)
    recovered = system.view(cursor=initial["cursor"], retry_larger=True, seconds=60, **args(fixture))
    assert recovered["session_id"] != initial["session_id"]
    assert recovered["derived_from_session_id"] == initial["session_id"]
    assert recovered["as_of"] == initial["as_of"] and recovered["selected_place"] == initial["selected_place"]
    assert recovered["snapshot_budgets"] == dict(max_files=10000,max_bytes=64*1024*1024,max_file_bytes=2*1024*1024)
    assert not recovered["retry_larger_available"] and recovered["next_cursor"] is None
    assert recovered["coverage"]["reconstruction_complete"]
    assert recovered["coverage"]["reused_repositories"] == 1
    assert calls.count(("explore", str(root))) == 1
    assert not any(action == "pin" or (action == "explore" and repo == str(fixture["small"][0])) for action,repo in calls)
    assert saved_files(old_dir) == old_files
    new_plan = json.loads((fixture["cache_path"]/"systems"/recovered["session_id"]/"plan.json").read_text())
    for key in ("selected","as_of","anchors","parents","pins","jobs","catalog_fingerprint","max_commits"):
        assert new_plan[key] == old_plan[key]
    orchard = next(row for row in recovered["nodes"] if row["id"] == "planet:orchard")
    assert orchard["commit"] == old_commit and orchard["label"] == "z-orchard-original"
    notes = next(row for row in recovered["nodes"] if row["id"] == "planet:notes")
    assert notes["files"] and all(path.startswith("notes/") for path in notes["files"])
    assert "NEW UNPINNED HEAD" not in json.dumps(recovered) and "DIRTY FUTURE CONTENT" not in json.dumps(recovered)
    calls.clear()
    replay = system.view(cursor=recovered["cursor"], seconds=60, **args(fixture))
    assert replay["session_id"] == recovered["session_id"]
    assert all(action == "validate_snapshot" for action,_ in calls)
    assert replay["snapshot_budgets"] == recovered["snapshot_budgets"]
    for changes in (dict(max_files=2000), dict(max_bytes=16*1024*1024), dict(max_file_bytes=1)):
        with pytest.raises(history.HistoryError, match="same snapshot"):
            system.view(cursor=recovered["cursor"], **changes, **args(fixture))
    with pytest.raises(history.HistoryError, match="No eligible"):
        system.view(cursor=recovered["cursor"], retry_larger=True, **args(fixture))
    with pytest.raises(history.HistoryError, match="different place"):
        system.view("another-system", cursor=initial["cursor"], retry_larger=True, **args(fixture))
    with pytest.raises(history.HistoryError, match="different place"):
        system.view(as_of="2025-05-01", cursor=initial["cursor"], retry_larger=True, **args(fixture))
    # A corrupt reused snapshot must be revalidated, never shown as stale proof.
    small_data = next(row["data"] for row in recovered["repositories"] if row.get("data",{}).get("repository") == str(fixture["small"][0]))
    (Path(small_data["snapshot"]["snapshot_path"])/"README.md").write_text("CORRUPTED RETAINED SNAPSHOT")
    calls.clear()
    repaired = system.view(cursor=recovered["cursor"], seconds=60, **args(fixture))
    assert ("explore", str(fixture["small"][0])) in calls
    assert "CORRUPTED RETAINED SNAPSHOT" not in json.dumps(repaired)
    assert repaired["session_id"] == recovered["session_id"]
    assert saved_files(old_dir) == old_files


def test_retry_requires_exact_existing_cursor(tmp_path):
    with pytest.raises(history.HistoryError, match="existing pinned cursor"):
        system.view(retry_larger=True, space_cache=tmp_path/"absent", cache_path=tmp_path/"cache")
    with pytest.raises(history.HistoryError, match="Invalid system history cursor"):
        system.view(cursor="bad:0",retry_larger=True, space_cache=tmp_path/"absent", cache_path=tmp_path/"cache")
    assert not (tmp_path/"cache").exists()


@pytest.mark.parametrize("dimensions,available", [(["max_files"],True),(["max_bytes"],True),
                                                  (["max_files","max_bytes"],True),(["max_file_bytes"],False),
                                                  (["max_file_bytes","max_bytes"],False)])
def test_only_growable_native_limit_failures_offer_retry(dimensions, available):
    plan=dict(budgets=system.DEFAULT_BUDGETS,jobs=[dict(id="a",scope_ids=["planet:a"])])
    saved={"a":dict(error=system.BUDGET_ERROR+"notes.md",coverage=dict(snapshot_budget_failure=dict(dimensions=dimensions)))}
    budgets,jobs=system._larger_retry(plan,saved)
    assert bool(jobs) == available
    assert budgets["max_file_bytes"] == system.DEFAULT_BUDGETS["max_file_bytes"]
    plan["budgets"] = budgets
    assert not system._larger_retry(plan,saved)[1]


def test_old_generic_failure_is_qualified_and_nonbudget_errors_do_not_offer_retry():
    plan=dict(budgets=system.DEFAULT_BUDGETS,jobs=[dict(id="a",scope_ids=["planet:a"])])
    generic={"a":dict(error=system.BUDGET_ERROR+"old.md",coverage={})}
    assert system._larger_retry(plan,generic)[1][0]["exact_failure"] is False
    for error in ("System history time budget reached", "No available Git repository", "Non-monotonic first-parent dates"):
        assert not system._larger_retry(plan,{"a":dict(error=error)})[1]


def test_native_snapshot_failure_exposes_unchanged_per_file_limit(tmp_path):
    root,commit,_ = make_repo(tmp_path/"single-file-limit")
    with pytest.raises(history.HistoryError) as caught:
        history.prepare(root,commit,tmp_path/"cache",max_file_bytes=8)
    failure=caught.value.coverage["snapshot_budget_failure"]
    assert failure["dimensions"] == ["max_file_bytes"]
    assert failure["file_bytes"] > 8 and failure["limits"]["max_file_bytes"] == 8
