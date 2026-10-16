"""Git revisions remain immutable and separate from live files/source caches."""
import json
import os
from pathlib import Path
import shutil
import shlex
import subprocess
import sys

import pytest

import navcom_history as history
import navcom_sources


@pytest.fixture
def historical_repo(tmp_path):
    root=tmp_path / "quartz"
    root.mkdir()
    env=dict(os.environ,GIT_CONFIG_GLOBAL=os.devnull,GIT_CONFIG_NOSYSTEM="1")
    def git(*args, extra=None):
        result=subprocess.run(["git","-C",str(root),"-c","user.name=Fixture","-c","user.email=fixture@example.invalid",
                               "-c","commit.gpgsign=false","-c","core.hooksPath="+os.devnull,*args],
                              env=dict(env,**(extra or {})),capture_output=True,text=True,check=True)
        return result.stdout.strip()
    git("init","-q","-b","main")
    commits=[]
    for name,month,mechanism in [("quartz-classic","01","Password"),("quartz-cloud","06","Cognito")]:
        (root / "README.md").write_text("# "+name+"\n\n"+mechanism+" login\n")
        (root / "package.json").write_text(json.dumps(dict(name=name,description=mechanism+" login",scripts=dict(start="python app.py"))))
        (root / "app.py").write_text("\n".join(
            [f'"""{mechanism} login for the historical product."""',f'def {mechanism.lower()}_login(value):']
            + [f'    step_{i} = value + {i}' for i in range(22)] + ['    return step_21','']))
        git("add",".")
        git("commit","-qm",name,extra={"GIT_AUTHOR_DATE":f"2025-{month}-01T10:00:00Z","GIT_COMMITTER_DATE":f"2025-{month}-02T11:00:00Z"})
        commits.append(git("rev-parse","HEAD"))
    for filename in ("README.md","package.json","app.py"):
        with (root / filename).open("a") as target:target.write("\nCURRENT_ONLY_DIRTY_MARKER\n")
        os.utime(root / filename,(978307200,978307200))
    return root,commits,git


def test_full_commit_timeline_and_old_tree_ignore_dirty_files(historical_repo,tmp_path):
    repo,commits,git=historical_repo
    before=git("status","--porcelain")
    result=history.timeline(repo,limit=1)
    assert result["truncated"] and not result["shallow"]
    assert result["commits"][0]["commit"]==commits[1]
    assert len(result["commits"][0]["tree"])==40
    assert result["commits"][0]["authored_at"].startswith("2025-06-01")
    assert result["commits"][0]["committed_at"].startswith("2025-06-02")
    prepared=history.prepare(repo,commits[0],tmp_path / "history")
    snapshot=Path(prepared["snapshot_path"])
    assert prepared["commit"]==commits[0] and prepared["kind"]=="git_revision"
    assert prepared["coverage"]["complete"] and prepared["coverage"]["files"]==3
    assert json.loads((snapshot / "package.json").read_text())["name"]=="quartz-classic"
    assert "password_login" in (snapshot / "app.py").read_text()
    for target in snapshot.iterdir():
        assert "Cognito" not in target.read_text() and "CURRENT_ONLY_DIRTY_MARKER" not in target.read_text()
    assert history.prepare(repo,commits[0],tmp_path / "history")["cache_hit"]
    assert git("status","--porcelain")==before
    assert git("rev-parse","HEAD")==commits[1]
    assert not (snapshot / ".git").exists()


def test_scope_and_budgets_never_use_current_fallback(historical_repo,tmp_path):
    repo,commits,git=historical_repo
    cache=tmp_path / "history"
    result=history.prepare(repo,commits[0],cache,include=["README.md","future.md"])
    assert [r["path"] for r in result["files"]]==["README.md"]
    assert not result["coverage"]["complete"]
    assert result["coverage"]["rejected"]==[dict(path="future.md",reason="missing at selected revision")]
    (repo / "future.md").write_text("Current file must never fill missing history")
    with pytest.raises(history.HistoryError,match="No supported committed files") as error:
        history.prepare(repo,commits[0],cache,include=["future.md"])
    assert error.value.coverage["rejected"]
    with pytest.raises(history.HistoryError,match="budget"):
        history.prepare(repo,commits[0],cache,max_bytes=1)
    assert not list(cache.glob(".history-*"))
    with pytest.raises(history.HistoryError,match="inside"):
        history.prepare(repo,commits[0],cache,include=["../escape"])
    with pytest.raises(history.HistoryError,match="outside"):
        history.prepare(repo,commits[0],repo / "cache")


def test_symlinks_submodules_lfs_and_hidden_paths_are_disclosed(historical_repo,tmp_path):
    repo,_,git=historical_repo
    (repo / "link.md").symlink_to("README.md")
    (repo / "model.bin").write_text("version https://git-lfs.github.com/spec/v1\noid sha256:"+"a"*64+"\nsize 123456\n")
    (repo / ".private.md").write_text("private metadata")
    git("add","link.md","model.bin",".private.md")
    git("update-index","--add","--cacheinfo","160000,"+git("rev-parse","HEAD")+",nested-module")
    git("commit","-qm","Unsupported object examples")
    result=history.prepare(repo,"HEAD",tmp_path / "history")
    rejected={r["path"]:r["reason"] for r in result["coverage"]["rejected"]}
    assert rejected["link.md"]=="symlink" and rejected["nested-module"]=="submodule"
    assert rejected["model.bin"].startswith("Git LFS pointer")
    assert rejected[".private.md"]=="hidden path"
    assert not result["coverage"]["complete"]
    assert {r["path"] for r in result["files"]}=={"README.md","package.json","app.py"}


def test_modified_historical_snapshot_is_not_trusted(historical_repo,tmp_path):
    repo,commits,_=historical_repo
    first=history.prepare(repo,commits[0],tmp_path / "history")
    (Path(first["snapshot_path"]) / "README.md").write_text("Injected present day content")
    with pytest.raises(history.HistoryError,match="changed"):
        history.prepare(repo,commits[0],tmp_path / "history")


def test_native_batch_skips_dependency_blobs_and_checks_relevant_lfs(historical_repo,tmp_path,monkeypatch):
    repo,_,git=historical_repo
    # A tracked dependency tree must remain excluded without thousands of LFS
    # probes. Relevant unknown-extension and source-extension pointers still
    # retain the existing pointer coverage rather than fetching their payload.
    dependency=repo/"node_modules/unfamiliar-library"
    dependency.mkdir(parents=True)
    for i in range(100):
        (dependency/f"part-{i}.js").write_text("module.exports = 1;\n")
    pointer="version https://git-lfs.github.com/spec/v1\noid sha256:"+"a"*64+"\nsize 999999999\n"
    (dependency/"carried.json").write_text(pointer.replace("a"*64,"b"*64))
    (repo/"model.bin").write_text(pointer)
    (repo/"records.json").write_text(pointer)
    big=repo/"source with spaces\nand newline.py"
    contents='"""Large committed source."""\n'+'# measured code evidence\n'*20000
    big.write_text(contents)
    git("add",".");git("commit","-qm","Batch reader fixture")
    dependency_oids=set(git("ls-tree","-r","--format=%(objectname)","HEAD","--","node_modules").splitlines())
    read=history._GitBlobs.read;requests=[]
    def observe(self,oid,*args,**kwargs):
        requests.append(oid)
        assert oid not in dependency_oids
        return read(self,oid,*args,**kwargs)
    monkeypatch.setattr(history._GitBlobs,"read",observe)
    original_git=history._git
    def metadata_only(repo,*args,**kwargs):
        assert not args or args[0]!="cat-file", "Per-blob Git subprocess regression"
        return original_git(repo,*args,**kwargs)
    monkeypatch.setattr(history,"_git",metadata_only)
    snapshot=history.prepare(repo,"HEAD",tmp_path/"history")
    assert (Path(snapshot["snapshot_path"])/big.name).read_text()==contents
    rejected={r["path"]:r["reason"] for r in snapshot["coverage"]["rejected"]}
    assert rejected["model.bin"].startswith("Git LFS pointer")
    assert rejected["records.json"].startswith("Git LFS pointer")
    assert rejected["node_modules/unfamiliar-library/carried.json"]=="Starforge skipped directory"
    assert len(requests)==6  # Four ordinary source files and the two relevant pointers.


def test_batch_rejects_tree_size_and_object_digest_mismatch(historical_repo,monkeypatch):
    repo,commits,git=historical_repo
    oid=git("rev-parse",commits[0]+":README.md")
    contents=git("show",commits[0]+":README.md").encode()+b"\n"
    reader=history._GitBlobs(repo)
    try:
        with pytest.raises(history.HistoryError,match="selected tree"):
            reader.read(oid,len(contents)+1,1024)
    finally:
        reader.close()
    reader=history._GitBlobs(repo)
    exact=reader._exact
    def corrupt(count,deadline):
        data=exact(count,deadline)
        return b"X"+data[1:] if count==len(contents) else data
    monkeypatch.setattr(reader,"_exact",corrupt)
    try:
        with pytest.raises(history.HistoryError,match="object ID"):
            reader.read(oid,len(contents),1024)
    finally:
        reader.close()


def test_shallow_history_is_explicit(historical_repo,tmp_path):
    repo,_,_=historical_repo
    clone=tmp_path / "shallow"
    subprocess.run(["git","clone","-q","--depth","1",repo.as_uri(),str(clone)],check=True,capture_output=True)
    assert history.timeline(clone)["shallow"]
    result=history.prepare(clone,"HEAD",tmp_path / "history")
    assert result["coverage"]["shallow"] and not result["coverage"]["complete"]


@pytest.mark.skipif(not shutil.which("starforge"),reason="Optional installed Starforge required")
def test_historical_harvest_uses_existing_both_search_paths(historical_repo,tmp_path):
    repo,commits,git=historical_repo
    before=git("status","--porcelain")
    prepared=history.harvest_revision(repo,commits[0],tmp_path / "history")
    assert prepared["harvest"]["analyzed_sources"]==1
    repeated=history.harvest_revision(repo,commits[0],tmp_path / "history")
    assert repeated["cache_hit"] and repeated["harvest"]["analyzed_sources"]==0
    worker=Path(navcom_sources.__file__).with_name("navcom_sources_worker.py")
    def search(query):
        request=dict(action="search",cache=prepared["source_cache"],query=query,mode="both",limit=20)
        result=subprocess.run([navcom_sources.runtime(),str(worker)],input=json.dumps(request),capture_output=True,text=True)
        assert result.returncode==0,result.stderr
        return json.loads(result.stdout)
    old=search("Password")
    assert old["concept_hits"] and old["text_hits"]
    assert all(prepared["snapshot_path"] in h["source_path"] for field in ("concept_hits","text_hits") for h in old[field])
    for query in ("Cognito","CURRENT_ONLY_DIRTY_MARKER"):
        absent=search(query)
        assert not absent["concept_hits"] and not absent["text_hits"]
    assert search("Password")["query_cache_hit"]
    assert git("status","--porcelain")==before


def space_fixture(root, path, locations=None):
    galaxy=dict(id="galaxy:owner",label="Fixture galaxy",kind="galaxy",parent_id=None,locations=[],evidence=[])
    planet=dict(id="planet:quartz",label="Current Quartz",kind="planet",parent_id=galaxy["id"],
                locations=locations or [dict(path=str(root))],evidence=[])
    path.write_text(json.dumps(dict(schema_version=1,published=0,entities=[galaxy,planet],edges=[],coverage={})))
    return planet


def cli(*args, success=True):
    entry=Path(history.__file__).with_name("navcom.py")
    proc=subprocess.run([sys.executable,str(entry),"history",*map(str,args)],capture_output=True,text=True,timeout=120)
    assert (proc.returncode==0)==success,proc.stderr
    return proc


@pytest.mark.skipif(not shutil.which("starforge"),reason="Optional installed Starforge required")
def test_real_cli_historical_journey_preserves_old_and_new_identity(historical_repo,tmp_path):
    repo,commits,git=historical_repo
    space=tmp_path / "space.json"
    space_fixture(repo,space)
    common=["--space-cache",space,"--json"]
    before=git("status","--porcelain")
    rows=json.loads(cli("timeline","planet:quartz",*common).stdout)
    assert rows["selected_place"]["id"]=="planet:quartz"
    assert [c["commit"] for c in rows["commits"]]==commits[::-1]
    cache=tmp_path / "history"
    def explore(revision,query):
        return json.loads(cli("explore","Current Quartz",revision,"--cache",cache,"--query",query,*common).stdout)
    old=explore(commits[0],"Password")
    assert old["manifests"][0]["metadata"]["name"]=="quartz-classic"
    assert old["evidence"]["concept_hits"] and old["evidence"]["text_hits"]
    assert old["structure"]["engine"]=="starforge.similarity.find_token_groups"
    assert old["conversations"]==[] and old["selected_place"]["label"]=="Current Quartz"
    assert "CURRENT_ONLY_DIRTY_MARKER" not in json.dumps(old)
    assert "Cognito" not in json.dumps(old)
    assert any("quartz-classic" in c["text"] for c in old["product_clues"])
    replay=shlex.split(old["cli_command"])
    assert replay[:3]==["navcom","history","explore"] and commits[0] in replay
    assert replay[replay.index("--query")+1]=="Password"
    assert replay[replay.index("--include")+1]=="."
    assert json.loads(cli(*replay[2:],"--json").stdout)["commit"]==commits[0]
    repeated=explore(commits[0],"Password")
    assert repeated["snapshot"]["cache_hit"] and repeated["evidence"]["query_cache_hit"]
    assert repeated["snapshot"]["harvest"]["analyzed_sources"]==0
    new=explore(commits[1],"Cognito")
    assert new["manifests"][0]["metadata"]["name"]=="quartz-cloud"
    assert new["evidence"]["concept_hits"] and new["evidence"]["text_hits"]
    assert "Password" not in json.dumps(new) and "CURRENT_ONLY_DIRTY_MARKER" not in json.dumps(new)
    absent=explore(commits[0],"Cognito")
    assert absent["evidence"]["concept_hits"]==absent["evidence"]["text_hits"]==[]
    explicit=json.loads(cli("explore",commits[0],"--repo",repo,"--cache",cache,"--json").stdout)
    assert explicit["commit"]==commits[0] and explicit["selected_place"] is None
    assert git("status","--porcelain")==before and git("rev-parse","HEAD")==commits[1]


def test_nested_place_and_district_do_not_widen_to_repository(historical_repo,tmp_path):
    repo,commits,git=historical_repo
    app=repo / "apps" / "flight"
    app.mkdir(parents=True)
    (app / "README.md").write_text("FlightOnly historical content")
    git("add","apps")
    git("commit","-qm","Nested application")
    space=tmp_path / "space.json"
    space_fixture(app,space)
    resolved=history.resolve_place("planet:quartz",space_cache=space)
    assert resolved["repository"]==str(repo) and resolved["include"]==["apps/flight"]
    with pytest.raises(history.HistoryError,match="stay within"):
        history.resolve_place("planet:quartz",space_cache=space,include=["README.md"])
    sources=tmp_path / "sources"
    sources.mkdir()
    (sources / "current.json").write_text(json.dumps(dict(sources=[dict(id="registered",root=str(repo))])))
    data=json.loads(space.read_text())
    data["entities"].append(dict(id="district:flight",label="Flight",kind="district",parent_id="planet:quartz",
                                 locations=[],evidence=[],source_scopes=[dict(source_id="registered",paths=["apps/flight/README.md"])]))
    space.write_text(json.dumps(data))
    district=history.resolve_place("district:flight",space_cache=space,source_cache=sources)
    assert district["include"]==["apps/flight/README.md"]
    with pytest.raises(history.HistoryError,match="saved source scopes"):
        history.resolve_place("district:flight",space_cache=space)
    data["entities"][-1]["source_scopes"][0]["paths"]=[]
    space.write_text(json.dumps(data))
    with pytest.raises(history.HistoryError,match="scope has no paths"):
        history.resolve_place("district:flight",space_cache=space,source_cache=sources)
    view=history.view("planet:quartz","HEAD",action="explore",space_cache=space,cache_path=tmp_path / "history",query="Password")
    assert [f["path"] for f in view["snapshot"]["files"]]==["apps/flight/README.md"]
    assert view["evidence"]["concept_hits"]==view["evidence"]["text_hits"]==[]


def test_ambiguous_git_copies_require_explicit_choice(historical_repo,tmp_path):
    repo,_,_=historical_repo
    clone=tmp_path / "copy"
    subprocess.run(["git","clone","-q",str(repo),str(clone)],check=True,capture_output=True)
    space=tmp_path / "space.json"
    space_fixture(repo,space,locations=[dict(path=str(repo)),dict(path=str(clone))])
    with pytest.raises(history.HistoryError,match="multiple Git copies") as error:
        history.resolve_place("planet:quartz",space_cache=space)
    assert len(error.value.coverage["repositories"])==2
    assert history.resolve_place("planet:quartz",space_cache=space,repo=clone)["repository"]==str(clone)
    with pytest.raises(history.HistoryError,match="one Git repository"):
        history.resolve_place("galaxy:owner",space_cache=space)


def test_current_symlink_cannot_redirect_saved_historical_address(historical_repo,tmp_path):
    repo,commits,git=historical_repo
    other=tmp_path / "other"
    subprocess.run(["git","clone","-q",str(repo),str(other)],check=True,capture_output=True)
    (repo / "README.md").unlink()
    (repo / "README.md").symlink_to(other / "package.json")
    space=tmp_path / "space.json"
    space_fixture(repo,space)
    data=json.loads(space.read_text())
    data["entities"].append(dict(id="district:readme",label="Docs",kind="district",parent_id="planet:quartz",
        locations=[],evidence=[],source_scopes=[dict(source_id="saved",paths=["README.md"])]))
    space.write_text(json.dumps(data))
    sources=tmp_path / "sources";sources.mkdir()
    (sources / "current.json").write_text(json.dumps(dict(sources=[dict(id="saved",root=str(repo))])))
    resolved=history.resolve_place("district:readme",space_cache=space,source_cache=sources)
    assert resolved["repository"]==str(repo) and resolved["include"]==["README.md"]
    old=history.prepare(resolved["repository"],commits[0],tmp_path / "history",include=resolved["include"])
    assert (Path(old["snapshot_path"])/"README.md").read_text()=="# quartz-classic\n\nPassword login\n"
    # Direct location leaves also remain literal, including directory symlinks.
    data["entities"][1]["locations"]=[dict(path=str(repo / "README.md"))]
    space.write_text(json.dumps(data))
    assert history.resolve_place("planet:quartz",space_cache=space)["include"]==["README.md"]
    (repo / "apps").mkdir();(repo / "apps" / "flight").symlink_to(other,target_is_directory=True)
    data["entities"][1]["locations"]=[dict(path=str(repo / "apps" / "flight"))]
    space.write_text(json.dumps(data))
    selected=history.resolve_place("planet:quartz",space_cache=space)
    assert selected["repository"]==str(repo) and selected["include"]==["apps/flight"]
    nested=other / "nested"
    subprocess.run(["git","clone","-q",str(repo),str(nested)],check=True,capture_output=True)
    data["entities"][1]["locations"]=[dict(path=str(repo / "apps" / "flight" / "nested"))]
    space.write_text(json.dumps(data))
    selected=history.resolve_place("planet:quartz",space_cache=space)
    assert selected["repository"]==str(repo) and selected["include"]==["apps/flight/nested"]


def test_existing_harvest_policy_skips_assets_before_size_budget(historical_repo,tmp_path):
    repo,_,git=historical_repo
    (repo / "giant.png").write_bytes(b"x" * (2 * 1024 * 1024 + 1))
    (repo / "node_modules").mkdir()
    (repo / "node_modules" / "vendor.js").write_text("generated dependency")
    (repo / "Dockerfile").write_text("FROM python:3.12\n")
    git("add","giant.png","node_modules","Dockerfile")
    git("commit","-qm","Artifacts should not block source history")
    result=history.prepare(repo,"HEAD",tmp_path / "history")
    exclusions={e["path"]:e["reason"] for e in result["coverage"]["rejected"]}
    assert "existing harvest policy" in exclusions["giant.png"]
    assert exclusions["node_modules/vendor.js"]=="Starforge skipped directory"
    assert "Dockerfile" in {f["path"] for f in result["files"]}


def test_history_help_never_requires_runtime():
    for command in ([],["timeline","--help"],["explore","--help"]):
        assert "navcom history" in cli(*command).stdout
    entry=Path(history.__file__).with_name("navcom.py")
    proc=subprocess.run([sys.executable,str(entry),"help","history"],capture_output=True,text=True)
    assert proc.returncode==0 and "timeline" in proc.stdout and "explore" in proc.stdout
