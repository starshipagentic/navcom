"""Historical native app addresses reuse the original pinned source receipts."""
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

import pytest

import navcom_history as history
import navcom_historical_landing as landing
import navcom_source_reader as reader
import navcom_system_history as system


def create_application_fixture(root, *, file_scope=False):
    """Public CLI fixture retained under /tmp for installed journey acceptance."""
    root.mkdir(parents=True, exist_ok=True)
    repo = root / "orchard"
    repo.mkdir()
    def git(*args, date="2025-02-01T00:00:00Z"):
        env=dict(os.environ,GIT_CONFIG_GLOBAL=os.devnull,GIT_CONFIG_NOSYSTEM="1",
                 GIT_AUTHOR_DATE=date,GIT_COMMITTER_DATE=date)
        return subprocess.run(["git","-C",str(repo),"-c","user.name=Fixture","-c","user.email=fixture@example.invalid",
            "-c","commit.gpgsign=false","-c","core.hooksPath="+os.devnull,*args],
            env=env,capture_output=True,text=True,check=True).stdout.strip()
    def app(path, name, marker, private=True):
        folder=repo/path; (folder/"auth").mkdir(parents=True)
        (folder/"package.json").write_text(json.dumps(dict(name=name,private=private,scripts={"start":"python auth/signin.py"})))
        (folder/"README.md").write_text("# "+name+"\n"+marker+" access research.\n")
        for name in ("signin","tokens","permissions"):
            text='"""'+marker+' authentication identity token permission research."""\n'
            text+='def authenticate_identity_password_token_permission_policy_'+name+'(identity, token):\n'
            text+=''.join(f'    permission_{i} = identity + token + {i}\n' for i in range(24))
            (folder/"auth"/(name+".py")).write_text(text+'    return permission_23\n')
    git("init","-q","-b","main")
    (repo/"package.json").write_text(json.dumps(dict(name="orchard-suite",workspaces=["apps/*"],dependencies={"harbor-helper":"^1.2.0"})))
    app("apps/old","ember-classic","Password")
    app("LABS/trial/editor","trial-editor","Trial")
    app("tools/helper","harbor-helper","Dependency",private=False)
    git("add",".");git("commit","-qm","Historical applications")
    old=git("rev-parse","HEAD")
    shutil.rmtree(repo/"apps/old")
    app("apps/current","ember-next","Cognito")
    git("add","-A");git("commit","-qm","Different application address",date="2025-06-01T00:00:00Z")
    new=git("rev-parse","HEAD")
    (repo/"apps/current/README.md").write_text("DIRTY_FUTURE_MATERIAL\n")
    galaxy=dict(id="galaxy:owner",kind="galaxy",label="Owner",parent_id=None,position=dict(x=0,y=0),locations=[],evidence=[])
    suite=dict(id="system:orchard",kind="system",label="Orchard tools",parent_id=galaxy["id"],position=dict(x=100,y=100),locations=[],evidence=[])
    def node(identity, kind, label, path, parent=suite["id"]):
        return dict(id=identity,kind=kind,label=label,parent_id=parent,position=dict(x=200,y=200),
                    locations=[dict(path=str(repo/path))],evidence=[])
    nodes=[galaxy,suite]
    sources=None
    if file_scope:
        selected=node("planet:files","planet","Current selected files",".")
        selected["locations"]=[]
        selected["source_scopes"]=[dict(source_id="saved",paths=["apps/old/package.json","apps/old/auth/signin.py"])]
        nodes.append(selected)
        sources=root/"sources";sources.mkdir()
        (sources/"current.json").write_text(json.dumps(dict(sources=[dict(id="saved",root=str(repo))])))
    else:
        nodes.extend([node("planet:suite","planet","Current suite","."),
                      node("planet:current","planet","Current Ember","apps/current"),
                      node("moon:trial","moon","Trial","LABS/trial",parent="planet:suite")])
    chart=root/"space.json"
    chart.write_text(json.dumps(dict(schema_version=1,published=1,entities=nodes,edges=[],coverage={})))
    return dict(root=root,repo=repo,git=git,old=old,new=new,space_cache=chart,source_cache=sources,cache_path=root/"history")


def view_args(fixture):
    return {key:fixture[key] for key in ("space_cache","source_cache","cache_path")}


def candidate(result, root="apps/old"):
    return next(node for node in result["nodes"] if node.get("application_root")==root)


def land_args(fixture,result,node):
    return dict(cursor=result["cursor"],place_id=node["id"],result_key=result["result_key"],cache_path=fixture["cache_path"])


@pytest.fixture
def old_apps(tmp_path):
    if not shutil.which("starforge"):
        pytest.skip("Optional native Starforge required")
    return create_application_fixture(tmp_path)


def test_native_old_app_cli_landing_search_reader_and_pinned_replay(old_apps):
    f=old_apps
    before=f["git"]("status","--porcelain")
    result=system.view("system:orchard","2025-04-01",seconds=30,**view_args(f))
    old=candidate(result)
    assert old["label"]=="ember-classic" and old["historical_state"]=="committed"
    assert old["commit"]==f["old"] and old["status"]=="candidate"
    assert old["present_day_address"]==dict(id="planet:suite",kind="planet",label="Current suite")
    assert old["historical_scope"]==["apps/old"] and old["parent_id"]=="system:orchard"
    assert all(path.startswith("apps/old/") for path in old["files"])
    assert "application_candidates" not in old["structure"] and "application_coverage" not in old["structure"]
    assert all(path.startswith("apps/old/") for group in old["structure"]["token_groups"] for path in group["paths"])
    assert "succession" in old["historical_identity"]["meaning"]
    assert result["coverage"]["eligible_scopes"]==3 and result["coverage"]["completed_scopes"]==2
    assert result["coverage"]["derived_applications"]["derived"]==2
    trial=candidate(result,"LABS/trial/editor")
    assert trial["kind"]=="district" and trial["parent_id"]=="moon:trial"
    assert not any(node.get("application_root")=="apps/current" for node in result["nodes"])
    assert not any(node.get("application_root")=="tools/helper" for node in result["nodes"])
    assert f["git"]("status","--porcelain")==before
    plan=f["cache_path"]/"systems"/result["session_id"]/"plan.json"
    original_plan=plan.read_bytes()
    assert old["id"] not in json.loads(original_plan)["pins"]
    assert not any(node["id"]==old["id"] for node in json.loads(original_plan)["anchors"])

    command=shlex.split(old["land_command"])
    cli=subprocess.run([sys.executable,str(Path(__file__).parents[1]/"navcom.py"),*command[1:],"--query","Password","--json"],
                       capture_output=True,text=True,timeout=30)
    assert cli.returncode==0,cli.stderr
    landed=json.loads(cli.stdout)
    assert landed["center"]["id"]==old["id"] and landed["commit"]==f["old"]
    for engine in ("concept_hits","text_hits"):
        assert landed["evidence"][engine]
        assert all(hit["relative_path"] in old["files"] for hit in landed["evidence"][engine])
    assert landed["coverage"]["harvest_invocations"]==0
    ref=next(hit["source_ref"] for hit in landed["evidence"]["text_hits"] if hit["relative_path"].endswith("signin.py"))
    opened=reader.read_source(ref["source_id"],ref["relative_path"],line=ref["line"],history=ref["history"],
                              snapshot=ref["snapshot"],history_cache=f["cache_path"],limit=2)
    assert opened["provenance"]["commit"]==f["old"] and "Password" in json.dumps(opened)
    laboratory=landing.landing(**land_args(f,result,trial))
    assert [n["id"] for n in laboratory["breadcrumbs"]]==["system:orchard","planet:suite","moon:trial",trial["id"]]
    moon=landing.landing(**dict(land_args(f,result,trial),place_id="moon:trial"))
    child=next(node for node in moon["nodes"] if node["id"]==trial["id"])
    assert child["historical_identity"]==trial["historical_identity"]
    assert "--group" not in shlex.split(child["land_command"])
    late=system.view("system:orchard","2025-08-01",seconds=30,**view_args(f))
    later_trial=candidate(late,"LABS/trial/editor")
    assert later_trial["id"]!=trial["id"] and later_trial["position"]==trial["position"]
    assert not any(node.get("application_root")=="apps/old" for node in late["nodes"])
    warm=landing.landing(**land_args(f,result,old),query="Password")
    assert warm["evidence"]["query_cache_hit"]

    # Pagination/replay keeps the old tip and native IDs when current inputs change.
    f["git"]("add",".");f["git"]("commit","-qm","Unpinned later work",date="2025-07-01T00:00:00Z")
    f["space_cache"].unlink()
    repeated=system.view(cursor=result["cursor"],query="Password",seconds=30,**view_args(f))
    assert candidate(repeated)["id"]==old["id"] and candidate(repeated)["position"]==old["position"]
    assert plan.read_bytes()==original_plan
    assert "Cognito" not in json.dumps(candidate(repeated)) and "DIRTY_FUTURE" not in json.dumps(candidate(repeated))
    shutil.rmtree(f["repo"])
    offline=landing.landing(**land_args(f,repeated,candidate(repeated)),query="Password")
    assert offline["center"]["id"]==old["id"]
    assert not offline["coverage"]["current_catalog_read"] and not offline["coverage"]["current_repository_read"]


@pytest.mark.skipif(not shutil.which("starforge"),reason="Optional native Starforge required")
def test_file_only_scope_keeps_authored_label_and_never_admits_sibling_files(tmp_path):
    f=create_application_fixture(tmp_path,file_scope=True)
    result=system.view("system:orchard","2025-04-01",seconds=30,**view_args(f))
    old=candidate(result)
    expected=["apps/old/auth/signin.py","apps/old/package.json"]
    assert sorted(old["historical_scope"])==expected and sorted(old["files"])==expected
    assert old["label"]=="ember-classic"
    assert len([n for n in result["nodes"] if n.get("historical_identity")])==1
    landed=landing.landing(**land_args(f,result,old),query="Password")
    assert landed["allowed_paths"]==expected
    assert all(hit["relative_path"] in expected for engine in ("concept_hits","text_hits") for hit in landed["evidence"][engine])
    assert not any("tokens.py" in path or "LABS" in path for path in landed["allowed_paths"])


def test_derived_id_and_native_metadata_tampering_fail_closed(old_apps):
    f=old_apps
    result=system.view("system:orchard","2025-04-01",seconds=30,**view_args(f))
    old=candidate(result)
    invalid=old["id"][:-1]+("0" if old["id"][-1]!="0" else "1")
    with pytest.raises(history.HistoryError,match="not in this pinned"):
        landing.landing(**dict(land_args(f,result,old),place_id=invalid))
    job=old["historical_identity"]["job_id"]
    record=f["cache_path"]/"systems"/result["session_id"]/"results"/result["result_key"]/(job+".json")
    changed=json.loads(record.read_text())
    changed["data"]["structure"]["application_candidates"][0]["name"]="INJECTED PURPOSE"
    record.write_text(json.dumps(changed))
    with pytest.raises(history.HistoryError,match="native snapshot analysis"):
        landing.landing(**land_args(f,result,old))
