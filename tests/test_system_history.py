"""Dated system charts preserve addresses and use only immutable Git objects."""
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

import pytest

import navcom_history as history
import navcom_system_history as system


def repository(root, versions):
    root.mkdir()
    def git(*args, date=None):
        env=dict(os.environ,GIT_CONFIG_GLOBAL=os.devnull,GIT_CONFIG_NOSYSTEM="1")
        if date:env.update(GIT_AUTHOR_DATE="2024-01-01T00:00:00Z",GIT_COMMITTER_DATE=date)
        return subprocess.run(["git","-C",str(root),"-c","user.name=Fixture","-c","user.email=fixture@example.invalid",
                               "-c","commit.gpgsign=false","-c","core.hooksPath="+os.devnull,*args],
                              env=env,capture_output=True,text=True,check=True).stdout.strip()
    git("init","-q","-b","main")
    commits=[]
    for name,date,strategy in versions:
        (root/"package.json").write_text(json.dumps(dict(name=name,description=strategy+" login")))
        (root/"README.md").write_text("# "+name+"\n\n"+strategy+" login evidence\n")
        (root/"login.py").write_text('"""'+strategy+' login research."""\ndef '+strategy.lower()+'_login(value):\n'+
                                     '\n'.join(f'    phase_{i} = value + {i}' for i in range(22))+'\n    return phase_21\n')
        git("add",".");git("commit","-qm",name,date=date);commits.append(git("rev-parse","HEAD"))
    return root,commits,git


@pytest.fixture
def constellation(tmp_path):
    quartz=repository(tmp_path/"a-quartz",[("quartz-classic","2025-01-02T00:00:00Z","Password"),("quartz-cloud","2025-06-02T00:00:00Z","Cognito")])
    basalt=repository(tmp_path/"b-basalt",[("basalt-archive","2025-03-02T00:00:00Z","Archive"),("basalt-graph","2025-08-02T00:00:00Z","Graph")])
    galaxy=dict(id="galaxy:owner",kind="galaxy",label="Fixture galaxy",parent_id=None,position=dict(x=0,y=0),locations=[],evidence=[])
    suite=dict(id="system:coast",kind="system",label="Coastal tools",parent_id=galaxy["id"],position=dict(x=100,y=100),locations=[],evidence=[])
    nodes=[galaxy,suite]
    for index,(name,path) in enumerate([("quartz",quartz[0]),("basalt",basalt[0]),("missing",tmp_path/"not-here"),("renamed",quartz[0]/"new-only")]):
        nodes.append(dict(id="planet:"+name,kind="planet",label="CURRENT DISPLAY "+name,parent_id=suite["id"],position=dict(x=200+index,y=300+index),locations=[dict(path=str(path))],evidence=[]))
    space=tmp_path/"space.json"
    space.write_text(json.dumps(dict(schema_version=1,published=123,entities=nodes,edges=[],coverage={})))
    for repo,_,_ in (quartz,basalt):
        (repo/"README.md").write_text("DIRTY_FUTURE_CONTENT\n")
        (repo/"new-only").mkdir();(repo/"new-only/README.md").write_text("UNCOMMITTED_NEW_PATH\n")
    return dict(space_cache=space,cache_path=tmp_path/"history-cache",quartz=quartz,basalt=basalt,nodes=nodes)


def args(fixture):
    return {key:fixture[key] for key in ("space_cache","cache_path")}


def find(data,identity):
    return next(n for n in data["nodes"] if n["id"]==identity)


@pytest.mark.skipif(not shutil.which("starforge"),reason="Optional native Starforge required")
def test_two_repo_early_late_chart_search_unknowns_and_cache(constellation):
    fixture=constellation
    before=[r[2]("status","--porcelain") for r in (fixture["quartz"],fixture["basalt"])]
    progress=[]
    early=system.view("system:coast","2025-04-01",query="Password",progress=progress.append,**args(fixture))
    assert find(early,"planet:quartz")["label"]=="quartz-classic"
    assert find(early,"planet:basalt")["label"]=="basalt-archive"
    assert find(early,"planet:missing")["historical_state"]=="unknown"
    assert find(early,"planet:renamed")["historical_state"]=="unknown"
    assert not early["coverage"]["complete"] and not early["conversations"]
    assert not early["date_coverage"]["complete"]  # The unavailable repository's dates are not known.
    assert early["available_dates"]==["2025-01-02T00:00:00Z","2025-03-02T00:00:00Z","2025-06-02T00:00:00Z","2025-08-02T00:00:00Z"]
    assert progress[0]["stage"]=="pin" and progress[-1]["stage"]=="reconstruct"
    repo_data=next(r["data"] for r in early["repositories"] if r.get("data",{}).get("repository")==str(fixture["quartz"][0]))
    assert Path(repo_data["snapshot"]["snapshot_path"]).parent.parent==fixture["cache_path"]/"revisions"
    assert repo_data["evidence"]["concept_hits"] and repo_data["evidence"]["text_hits"]
    for candidate in early["nodes"]:
        for file in candidate.get("files",[]):
            text=(Path(candidate["snapshot_path"])/file).read_text()
            assert "Cognito" not in text and "Graph" not in text and "DIRTY_FUTURE_CONTENT" not in text and "UNCOMMITTED_NEW_PATH" not in text
    repeated=system.view("system:coast","2025-04-01",query="Password",**args(fixture))
    assert repeated["session_id"]==early["session_id"]
    assert all(r["data"]["snapshot"]["cache_hit"] for r in repeated["repositories"] if r.get("data"))
    assert all(r["data"]["evidence"]["query_cache_hit"] for r in repeated["repositories"] if r.get("data"))
    late=system.view("system:coast","2025-09-01T00:00:00Z",**args(fixture))
    assert find(late,"planet:quartz")["label"]=="quartz-cloud"
    assert find(late,"planet:basalt")["label"]=="basalt-graph"
    assert [(n["id"],n["position"]) for n in early["nodes"]]==[(n["id"],n["position"]) for n in late["nodes"]]
    assert before==[r[2]("status","--porcelain") for r in (fixture["quartz"],fixture["basalt"])]


@pytest.mark.skipif(not shutil.which("starforge"),reason="Optional native Starforge required")
def test_pagination_keeps_all_anchors_and_pinned_heads(constellation):
    fixture=constellation
    first=system.view("system:coast","2025-09-01",limit=1,**args(fixture))
    assert len(first["nodes"])==5  # System plus every selected planet, including unvisited/unknown.
    assert find(first,"planet:basalt")["historical_state"]=="unknown" and first["next_cursor"]
    root,commits,git=fixture["basalt"]
    (root/"package.json").write_text('{"name":"LATER_UNPINNED_PRODUCT"}')
    git("add","package.json");git("commit","-qm","new tip after page one",date="2025-08-15T00:00:00Z")
    second=system.view(cursor=first["next_cursor"],limit=1,**args(fixture))
    assert second["session_id"]==first["session_id"] and second["next_cursor"] is None
    assert find(second,"planet:basalt")["label"]=="basalt-graph"
    assert find(second,"planet:basalt")["commit"]==commits[1]
    assert find(second,"planet:quartz")["historical_state"]=="committed"


def test_time_bound_accounts_for_every_anchor_without_later_repinning(constellation,monkeypatch):
    fixture=constellation
    original=system._run
    def no_time(*_args,**_kwargs):
        raise history.HistoryError("No pin within fixture time budget")
    monkeypatch.setattr(system,"_run",no_time)
    result=system.view("system:coast","2025-04-01",seconds=.1,**args(fixture))
    assert result["coverage"]["eligible_scopes"]==4
    assert result["coverage"]["completed_scopes"]==0
    assert len(result["coverage"]["unknown_scope_ids"])==4
    assert not result["next_cursor"] and not result["coverage"]["complete"]
    monkeypatch.setattr(system,"_run",original)
    repeat=system.view(cursor=result["cursor"],**args(fixture))
    assert repeat["coverage"]["pinned_repositories"]==0


def test_dates_selection_bounds_and_non_monotonic_history(constellation,tmp_path):
    fixture=constellation
    root,commits,_git=fixture["quartz"]
    request=dict(action="explore",repository=str(root),tip=commits[-1],as_of="2025-04-01T00:00:00Z",max_commits=1)
    with pytest.raises(history.HistoryError,match="ancestry budget"):
        system._worker(request)
    request.update(max_commits=10,as_of="2024-01-01T00:00:00Z")
    with pytest.raises(history.HistoryError,match="No recorded"):
        system._worker(request)
    odd=repository(tmp_path/"odd-dates",[("future-parent","2025-06-01T00:00:00Z","Old"),("backdated-child","2025-01-01T00:00:00Z","New")])
    request.update(repository=str(odd[0]),tip=odd[1][-1],as_of="2025-09-01T00:00:00Z")
    with pytest.raises(history.HistoryError,match="Non-monotonic"):
        system._worker(request)
    assert system._utc("2025-04-01")=="2025-04-01T00:00:00Z"
    with pytest.raises(history.HistoryError,match="UTC offset"):
        system._utc("2025-04-01T10:00:00")
    with pytest.raises(history.HistoryError,match="Invalid system history cursor"):
        system.view(cursor="../../bad:1",**args(fixture))


@pytest.mark.skipif(not shutil.which("starforge"),reason="Optional native Starforge required")
def test_timeout_retries_same_pinned_repository(constellation,monkeypatch):
    fixture=constellation
    original=system._run
    def transient(request, seconds):
        if request["action"]=="explore":
            raise history.HistoryError("System history time budget reached; this scope remains unknown")
        return original(request,seconds)
    monkeypatch.setattr(system,"_run",transient)
    failed=system.view("system:coast","2025-04-01",limit=1,**args(fixture))
    assert failed["next_cursor"]==failed["cursor"]
    assert failed["repositories"][0]["retryable"]
    assert failed["date_coverage"]["repositories_observed"]==0
    monkeypatch.setattr(system,"_run",original)
    recovered=system.view(cursor=failed["next_cursor"],limit=1,**args(fixture))
    assert recovered["session_id"]==failed["session_id"]
    assert find(recovered,"planet:quartz")["label"]=="quartz-classic"
    assert recovered["next_cursor"]!=failed["next_cursor"]


def test_copyable_command_preserves_literal_query_and_nondefault_budgets(tmp_path):
    import navcom_history_cli
    query="-Password $(touch NEVER_EXECUTE); ' quoted"
    plan=dict(selected=dict(id="system:coast"),as_of="2025-04-01T00:00:00Z",max_commits=25,
              budgets=dict(max_files=17,max_bytes=40000,max_file_bytes=10000))
    command=system._command(plan,"a"*64+":2",cache=tmp_path/"cache with spaces",space_cache=tmp_path/"space file.json",
                            source_cache=tmp_path/"source registry",query=query,limit=2,seconds=8.5,search_limit=7)
    arguments=shlex.split(command)
    assert arguments[:3]==["navcom","history","system"]
    parsed=navcom_history_cli.parser().parse_args(arguments[2:])
    assert parsed.query==query and parsed.cursor=="a"*64+":2"
    assert parsed.max_files==17 and parsed.max_bytes==40000 and parsed.max_file_bytes==10000
    assert parsed.search_limit==7 and parsed.seconds==8.5 and parsed.limit==2
    assert parsed.cache==tmp_path/"cache with spaces"


@pytest.mark.skipif(not shutil.which("starforge"),reason="Optional native Starforge required")
def test_real_system_cli_plain_output_replay_and_continue(constellation):
    fixture=constellation
    entry=Path(system.__file__).with_name("navcom.py")
    def cli(arguments):
        result=subprocess.run([sys.executable,str(entry),*map(str,arguments)],capture_output=True,text=True,timeout=60)
        assert result.returncode==0,result.stderr
        return result
    initial=cli(["history","system","system:coast","--at","2025-04-01","--space-cache",fixture["space_cache"],
                 "--cache",fixture["cache_path"],"--query","Password","--limit","1","--json"])
    data=json.loads(initial.stdout)
    assert "Inspecting address 1/4" in initial.stderr
    assert "Reading dated repository 1/2" in initial.stderr
    assert "{'stage'" not in initial.stderr
    replay=cli(shlex.split(data["cli_command"])[1:])
    assert "quartz-classic · planet · planet:quartz" in replay.stdout
    assert "Commit "+fixture["quartz"][1][0] in replay.stdout
    assert "Unknown:" in replay.stdout and "Coverage: 1/4 places reconstructed; 3 unknown." in replay.stdout
    assert "Replay this pinned page:" in replay.stdout and "Continue:" in replay.stdout
    assert "\n  {}" not in replay.stdout and "Historical search" in replay.stdout
    continued=cli([*shlex.split(data["continue_command"])[1:],"--json"])
    next_data=json.loads(continued.stdout)
    assert next_data["session_id"]==data["session_id"]
    assert find(next_data,"planet:basalt")["label"]=="basalt-archive"
    assert next_data["continue_command"] is None
    help_text=cli(["history","system","--help"]).stdout
    assert "midnight UTC" in help_text and "--search-limit" in help_text
    assert "omit with --repo" not in help_text


@pytest.mark.skipif(not shutil.which("starforge"),reason="Optional native Starforge required")
def test_system_api_cli_parity_and_server_owned_caches(constellation,monkeypatch,navcom,tmp_path):
    from navcom_web import WebApp
    fixture=constellation
    sources=tmp_path/"configured-sources"
    monkeypatch.setenv("NAVCOM_SPACE_CACHE",str(fixture["space_cache"]))
    monkeypatch.setenv("NAVCOM_SOURCES_CACHE",str(sources))
    monkeypatch.setenv("NAVCOM_HISTORY_CACHE",str(fixture["cache_path"]))
    index=tmp_path/"configured-index.sqlite"
    app=WebApp(navcom,index)
    unwanted=tmp_path/"client-selected-cache"
    body=dict(within="system:coast",at="2025-04-01",q="Password",limit=1,
              cache=str(unwanted),cache_path=str(unwanted),history_cache=str(unwanted),
              space_cache=str(unwanted/"fake-space.json"),source_cache=str(unwanted/"fake-sources"),
              index=str(unwanted/"fake.sqlite"),repo=str(unwanted/"fake-repo"),include=["wrong-path"],seconds=120,max_files=1)
    api_result=app.post(None,"/api/history/system",body)
    assert not unwanted.exists()
    entry=Path(system.__file__).with_name("navcom.py")
    process=subprocess.run([sys.executable,str(entry),"history","system","system:coast","--at","2025-04-01",
                            "--query","Password","--limit","1","--index",str(index),"--json"],
                           capture_output=True,text=True,check=True,timeout=60)
    cli_result=json.loads(process.stdout)
    def signature(result):
        return [(n["id"],n["label"],n["historical_state"],n.get("commit"),n["position"])
                for n in result["nodes"]]
    assert api_result["session_id"]==cli_result["session_id"]
    assert api_result["as_of"]==cli_result["as_of"] and api_result["next_cursor"]==cli_result["next_cursor"]
    assert signature(api_result)==signature(cli_result)
    assert api_result["completed_scope_ids"]==cli_result["completed_scope_ids"]
    assert api_result["coverage"]["unknown_scope_ids"]==cli_result["coverage"]["unknown_scope_ids"]
    for output in (api_result,cli_result):
        replay=shlex.split(output["cli_command"])
        assert replay[replay.index("--cache")+1]==str(fixture["cache_path"].resolve())
        assert replay[replay.index("--source-cache")+1]==str(sources.resolve())
        assert replay[replay.index("--space-cache")+1]==str(fixture["space_cache"].resolve())
        assert float(replay[replay.index("--seconds")+1])==30
        completed=next(r["data"] for r in output["repositories"] if r.get("data"))
        assert completed["snapshot"]["coverage"]["files"]==3
        assert completed["evidence"]["concept_hits"] and completed["evidence"]["text_hits"]
        assert Path(completed["snapshot"]["snapshot_path"]).is_relative_to(fixture["cache_path"].resolve())
    resumed=app.post(None,"/api/history/system",dict(body,cursor=api_result["next_cursor"]))
    assert resumed["session_id"]==api_result["session_id"]
    assert find(resumed,"planet:basalt")["label"]=="basalt-archive"
    assert resumed["next_cursor"] is None and not unwanted.exists()


def test_finished_worker_stderr_is_still_bounded(monkeypatch):
    import io
    class FinishedWorker:
        returncode=0
        stdin=io.BytesIO()
        def poll(self):return 0
    def completed(_argv,**options):
        options["stdout"].write(b'{"ok":true,"value":{}}')
        options["stderr"].write(b"x"*65537)
        return FinishedWorker()
    monkeypatch.setattr(system.subprocess,"Popen",completed)
    with pytest.raises(history.HistoryError,match="output budget"):
        system._run({},1)
