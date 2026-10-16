"""Dated product/group navigation reads only an existing pinned native result."""
import json
import io
import os
from pathlib import Path
import shlex
import shutil
import subprocess

import pytest

import navcom_historical_landing as landing
import navcom_history as history
import navcom_source_reader as reader
import navcom_system_history as system


def create_landing_fixture(root):
    """Reusable native CLI/API fixture: two product scopes in one dated repo."""
    repo = root / "orchard"
    repo.mkdir(parents=True)
    def git(*args, date="2025-03-01T00:00:00Z"):
        env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1", GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date)
        return subprocess.run(["git", "-C", str(repo), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
            "-c", "commit.gpgsign=false", "-c", "core.hooksPath="+os.devnull, *args], env=env,
            capture_output=True, text=True, check=True).stdout.strip()
    git("init", "-q", "-b", "main")
    (repo / "package.json").write_text(json.dumps(dict(name="orchard-suite", workspaces=["apps/*"])))
    for app in ("lantern", "radar"):
        folder = repo / "apps" / app
        (folder / "auth").mkdir(parents=True)
        (folder / "package.json").write_text(json.dumps(dict(name=app+"-classic", scripts={"start":"python auth/signin.py"})))
        (folder / "README.md").write_text("# "+app+" classic\n\nPassword identity and access research.\n")
        for filename in ("signin", "tokens", "permissions"):
            text='"""Password identity authentication token permission evidence '+app+'."""\n'
            text+='def authenticate_identity_password_session_token_permissions_credentials_policy_'+filename+'(identity, token):\n'
            text+=''.join(f'    permission_{i} = identity + token + {i}\n' for i in range(24))
            text+='    return permission_23\n'
            (folder / "auth" / (filename+".py")).write_text(text)
    git("add", "."); git("commit", "-qm", "Old products")
    commit = git("rev-parse", "HEAD")
    galaxy=dict(id="galaxy:owner",kind="galaxy",label="Owner",parent_id=None,position=dict(x=0,y=0),locations=[],evidence=[])
    suite=dict(id="system:orchard",kind="system",label="Orchard tools",parent_id=galaxy["id"],position=dict(x=100,y=100),locations=[],evidence=[])
    nodes=[galaxy,suite]
    for number,app in enumerate(("lantern","radar")):
        nodes.append(dict(id="planet:"+app,kind="planet",label="CURRENT "+app,parent_id=suite["id"],
                          position=dict(x=200+number*100,y=200),locations=[dict(path=str(repo/"apps"/app))],evidence=[]))
    chart=root/"space.json"; chart.write_text(json.dumps(dict(schema_version=1,published=1,entities=nodes,edges=[],coverage={})))
    cache=root/"history"
    result=system.view("galaxy:owner","2025-04-01",space_cache=chart,cache_path=cache,seconds=30)
    return dict(root=root,repo=repo,git=git,commit=commit,space_cache=chart,cache_path=cache,result=result,product_id="planet:lantern")


@pytest.fixture
def landing_fixture(tmp_path):
    if not shutil.which("starforge"):
        pytest.skip("Optional native Starforge required")
    return create_landing_fixture(tmp_path)


def kwargs(fixture):
    result=fixture["result"]
    return dict(cursor=result["cursor"],place_id=fixture["product_id"],result_key=result["result_key"],cache_path=fixture["cache_path"])


def test_native_landing_groups_search_reader_and_deleted_current_catalog(landing_fixture):
    f=landing_fixture
    product=next(n for n in f["result"]["nodes"] if n["id"]==f["product_id"])
    assert "--result-key" in product["land_command"]
    landed=landing.landing(**kwargs(f))
    assert landed["cursor"]==f["result"]["cursor"] and landed["result_key"]==f["result"]["result_key"]
    assert landed["center"]["id"]==product["id"] and landed["center"]["position"]==product["position"]
    assert landed["center"]["label"]=="lantern-classic" and landed["commit"]==f["commit"]
    assert [n["id"] for n in landed["breadcrumbs"]]==["galaxy:owner","system:orchard","planet:lantern"]
    assert all(x["path"].startswith("apps/lantern/") for x in landed["files"])
    assert "files" not in landed["snapshot"]
    assert "application_candidates" not in landed["product"]["structure"]
    assert isinstance(landed["coverage"]["complete"],bool) and "native_grouping" in landed["coverage"]
    groups=[n for n in landed["nodes"] if n["kind"]=="district"]
    assert groups
    group=next(n for n in groups if "apps/lantern/auth/signin.py" in n["files"])
    assert "--group" in group["land_command"]
    original_ids=[n["id"] for n in landed["nodes"]]

    # Everything living can change or disappear without changing this landing.
    (f["repo"]/"apps/lantern/package.json").write_text('{"name":"FUTURE PRODUCT"}')
    f["git"]("add","."); f["git"]("commit","-qm","Newer HEAD before cutoff",date="2025-03-15T00:00:00Z")
    (f["repo"]/"apps/lantern/auth/signin.py").write_text("DIRTY CONTENT\n")
    f["space_cache"].unlink()
    shutil.rmtree(f["repo"])
    repeated=landing.landing(**kwargs(f))
    assert [n["id"] for n in repeated["nodes"]]==original_ids
    assert repeated["center"]["label"]=="lantern-classic" and repeated["commit"]==f["commit"]
    selected=landing.landing(**kwargs(f),group_id=group["id"],query="Password")
    assert selected["center"]["id"]==group["id"] and selected["product"]["id"]==f["product_id"]
    assert selected["allowed_paths"]==group["files"]
    assert selected["evidence"]["concept_hits"] and selected["evidence"]["text_hits"]
    for engine in ("concept_hits","text_hits"):
        for hit in selected["evidence"][engine]:
            assert hit["relative_path"] in group["files"] and "apps/radar/" not in hit["relative_path"]
            assert hit["source_ref"]["history"]==selected["snapshot"]["id"]
    ref=selected["files"][0]["source_ref"]
    read=reader.read_source(ref["source_id"],ref["relative_path"],history=ref["history"],snapshot=ref["snapshot"],history_cache=f["cache_path"],limit=3)
    assert read["provenance"]["commit"]==f["commit"]
    warm=landing.landing(**kwargs(f),group_id=group["id"],query="Password")
    assert warm["evidence"]["query_cache_hit"] and warm["coverage"]["harvest_invocations"]==0
    assert not warm["coverage"]["current_catalog_read"] and not warm["coverage"]["current_repository_read"]
    assert "FUTURE PRODUCT" not in json.dumps(warm) and "DIRTY CONTENT" not in json.dumps(warm)


@pytest.mark.parametrize("changes",[dict(cursor="../bad:0"),dict(result_key="../../bad"),dict(limit=True),dict(seconds=float("nan")),dict(query="x"*501)])
def test_invalid_landing_inputs_fail_before_process(tmp_path,monkeypatch,changes):
    def forbidden(*args,**kwargs):pytest.fail("Invalid input started a worker")
    monkeypatch.setattr(landing.subprocess,"Popen",forbidden)
    values=dict(cursor="a"*64+":0",place_id="planet:one",result_key="b"*64,cache_path=tmp_path)
    values.update(changes)
    with pytest.raises(history.HistoryError):landing.landing(**values)


def test_wrong_scope_group_result_and_changed_snapshot_fail_closed(landing_fixture):
    f=landing_fixture
    with pytest.raises(history.HistoryError,match="unique pinned"):
        landing.landing(**dict(kwargs(f),place_id="planet:absent"))
    with pytest.raises(history.HistoryError,match="selected historical group"):
        landing.landing(**kwargs(f),group_id="historical-district:unknown")
    with pytest.raises(history.HistoryError,match="unavailable"):
        landing.landing(**dict(kwargs(f),result_key="a"*64))
    result=landing.landing(**kwargs(f)); snapshot=Path(result["snapshot"]["snapshot_path"])
    target=snapshot/result["files"][0]["path"]
    target.write_text("CORRUPTED IMMUTABLE CONTENT")
    with pytest.raises(history.HistoryError,match="snapshot content changed"):
        landing.landing(**kwargs(f))


def test_source_scope_and_result_receipt_mismatch_are_rejected(landing_fixture):
    f=landing_fixture; r=f["result"]
    folder=f["cache_path"]/"systems"/r["session_id"]
    plan=json.loads((folder/"plan.json").read_bytes());job=plan["jobs"][0]
    outcome_path=folder/"results"/r["result_key"]/(job["id"]+".json")
    outcome=json.loads(outcome_path.read_bytes()); outcome["data"]["include"]=["."]
    outcome_path.write_text(json.dumps(outcome))
    with pytest.raises(history.HistoryError,match="compatible completed snapshot"):
        landing.landing(**kwargs(f))


def test_landing_commands_quote_queries_without_execution(landing_fixture):
    f=landing_fixture
    request=dict(kwargs(f),cache_path=str(f["cache_path"]),query="-term $(touch NEVER_RUN); ' quote",limit=3,seconds=15)
    args=shlex.split(landing._command(request,"historical-district:test"))
    assert args[:4]==["navcom","history","land",f["product_id"]]
    assert "--query="+request["query"] in args and args[args.index("--group")+1]=="historical-district:test"


def test_saved_result_symlink_is_not_followed(landing_fixture,tmp_path):
    f=landing_fixture; r=f["result"]
    folder=f["cache_path"]/"systems"/r["session_id"]
    plan=json.loads((folder/"plan.json").read_bytes());job=plan["jobs"][0]
    result=folder/"results"/r["result_key"]/(job["id"]+".json")
    outside=tmp_path/"outside.json";result.rename(outside);result.symlink_to(outside)
    with pytest.raises(history.HistoryError,match="symlink was rejected"):
        landing.landing(**kwargs(f))


def test_search_rejects_changed_harvest_bytes_even_when_git_receipt_is_intact(landing_fixture):
    f=landing_fixture
    view=landing.landing(**kwargs(f))
    snapshot=view["snapshot"]
    state=json.loads((Path(snapshot["source_cache"])/"current.json").read_bytes())
    path=Path(state["sources"][0]["artifact"])/"source/apps/lantern/auth/signin.py"
    path.write_text(path.read_text()+"\n# Password ALTERED_HARVEST_CONTENT\n")
    with pytest.raises(history.HistoryError,match="pinned Git|snapshot|receipt"):
        landing.landing(**kwargs(f),query="Password")


def test_native_search_output_is_bounded_before_worker_finishes(landing_fixture,monkeypatch):
    import navcom_sources
    f=landing_fixture
    monkeypatch.setattr(navcom_sources,"runtime",lambda:"never-run")
    stopped=[]
    class Worker:
        stdin=io.BytesIO()
        returncode=None
        def poll(self):return self.returncode
        def kill(self):stopped.append(True);self.returncode=-9
        def wait(self,timeout=None):return self.returncode
    def oversized(_argv,**options):
        options["stderr"].write(b"x"*65537);options["stderr"].flush()
        return Worker()
    monkeypatch.setattr(landing.subprocess,"Popen",oversized)
    request=dict(kwargs(f),cache_path=str(f["cache_path"].resolve()),group_id=None,query="Password",limit=20,seconds=15)
    with pytest.raises(history.HistoryError,match="scoped search exceeded its output bound"):
        landing._execute(request)
    assert stopped==[True]


def test_completed_outer_worker_output_is_bounded(tmp_path,monkeypatch):
    class Worker:
        stdin=io.BytesIO()
        returncode=0
        def poll(self):return 0
    def oversized(_argv,**options):
        options["stdout"].write(b'{"ok":true,"value":{}}')
        options["stderr"].write(b"x"*65537)
        return Worker()
    monkeypatch.setattr(landing.subprocess,"Popen",oversized)
    with pytest.raises(history.HistoryError,match="output budget"):
        landing.landing("a"*64+":0","planet:one",result_key="b"*64,cache_path=tmp_path)
