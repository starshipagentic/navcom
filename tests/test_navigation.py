"""The copied CLI journey and federated evidence keep exact, bounded scopes."""
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest

import navcom_navigation as navigation
import navcom_sources
from test_atlas import add


ROOT = Path(__file__).resolve().parents[1]


def catalog(tmp_path, *, child_scopes=True, source_count=1):
    def node(identity, kind, parent, scopes, ids):
        return dict(id=identity, kind=kind, label=identity, parent_id=parent,
                    source_scopes=scopes, source_ids=ids, conversation_collections=[],
                    position=dict(x=0, y=0), locations=[], evidence=[], examples=[])
    ids = [str(i) for i in range(source_count)]
    nodes = [node("galaxy:owner", "galaxy", None, [], []),
             node("planet:fixture", "planet", "galaxy:owner", [dict(source_id=s, paths=["."]) for s in ids], ids),
             node("district:fixture", "district", "planet:fixture", [dict(source_id=s, paths=["auth/login.py"]) for s in ids] if child_scopes else [], ids)]
    path = tmp_path / "space.json"
    path.write_text(json.dumps(dict(schema_version=1, published=123, entities=nodes, edges=[], coverage={})))
    return path


def fake_search(monkeypatch, *, fail=False, truncated=False, timed_out=False):
    import navcom_discovery
    requests = []
    monkeypatch.setattr(navcom_sources, "runtime", lambda: "fake-starforge-python")
    def run(argv, **kwargs):
        request=json.loads(kwargs["input"])
        requests.append(request)
        scopes=request["scopes"]
        searched=scopes[:-1] if timed_out else scopes
        return SimpleNamespace(returncode=1 if fail else 0, stderr="forced worker error" if fail else "",
                               stdout=json.dumps(dict(sources=[dict(source_id=s["source_id"],concept_hits=[],text_hits=[],potentially_truncated=truncated) for s in searched],errors=[],coverage=dict(
                                   source_scopes=len(scopes),searched_source_scopes=len(searched),
                                   unsearched_source_ids=[scopes[-1]["source_id"]] if timed_out else [],
                                   complete=not truncated and not timed_out))))
    monkeypatch.setattr(navigation.subprocess, "run", run)
    class Discovery:
        def __init__(self, api):
            pass
        def view(self, conn, params):
            return dict(nodes=[])
    monkeypatch.setattr(navcom_discovery, "Discovery", Discovery)
    return requests


def test_district_search_never_inherits_broader_parent_source_scope(tmp_path, monkeypatch):
    cache = catalog(tmp_path)
    requests = fake_search(monkeypatch)
    result = navigation.evidence(None, None, cache, tmp_path / "sources", "district:fixture", "marmot")
    assert len(requests) == 1
    assert requests[0]["scopes"] == [dict(source_id="0", paths=["auth/login.py"])]
    assert requests[0]["action"] == "batch-search" and requests[0]["mode"] == "both"
    assert result["coverage"]["complete"]


@pytest.mark.parametrize('entrypoint',['evidence','view','navigate'])
def test_metadata_and_evidence_share_one_publication_during_atomic_refresh(tmp_path,monkeypatch,entrypoint):
    import navcom_space
    cache=catalog(tmp_path)
    requests=fake_search(monkeypatch)
    original=navcom_space._read
    reads=[]
    def replaced_after_read(path,*args,**kwargs):
        data=original(path,*args,**kwargs)
        reads.append(str(path))
        new=json.loads(json.dumps(data))
        new['published']=456
        new['entities'][-1]['source_scopes'][0]['paths']=['future/secrets.py']
        cache.write_text(json.dumps(new))
        return data
    monkeypatch.setattr(navcom_space,'_read',replaced_after_read)
    if entrypoint=='evidence':
        proof=navigation.evidence(None,None,cache,tmp_path/'sources','district:fixture','marmot')
    else:
        kwargs=dict(space_cache=cache,source_cache=tmp_path/'sources',within='district:fixture')
        result=(navigation.navigate(None,None,text='find marmot',**kwargs) if entrypoint=='navigate' else
                navigation.view(None,None,action='search',query='marmot',include_evidence=True,**kwargs))
        assert result['published']==123
        proof=result['evidence']
    assert len(reads)==1
    assert proof['coverage']['catalog_published']==123
    assert requests[0]['scopes']==[dict(source_id='0',paths=['auth/login.py'])]


@pytest.mark.parametrize('query,mode',[
    ('How do Aurora and Radar handle login?','question_terms'),
    ('where apps/Aurora/README.md',None),
    ('"login protocol"',None),
    ('back',None),('fly to Aurora',None),('home',None),
])
def test_search_replay_preserves_question_style_without_reinterpreting_commands(tmp_path,monkeypatch,query,mode):
    import navcom_navigation_intent
    cache=catalog(tmp_path)
    requests=fake_search(monkeypatch)
    monkeypatch.setattr(navcom_navigation_intent,'interpret',lambda *a,**kw:pytest.fail('Replayed search became a command'))
    result=navigation.view(None,None,space_cache=cache,source_cache=tmp_path/'sources',action='search',
                           within='district:fixture',query=query,include_evidence=True)
    assert result['action']=='search' and result['query']==query
    assert requests[0]['query']==query and requests[0].get('text_mode')==mode


def test_stale_narrow_place_without_paths_fails_closed(tmp_path, monkeypatch):
    cache = catalog(tmp_path, child_scopes=False)
    requests = fake_search(monkeypatch)
    result = navigation.evidence(None, None, cache, tmp_path / "sources", "district:fixture", "marmot")
    assert not requests, "Missing narrow scope must not silently search the whole source."
    assert result["errors"] and not result["coverage"]["complete"]


def test_empty_district_path_list_never_widens_to_entire_source(tmp_path,monkeypatch):
    cache=catalog(tmp_path)
    data=json.loads(cache.read_text())
    district=data['entities'][-1]
    district['source_scopes'][0]['paths']=[]
    district['conversation_basis']=dict(type='project_query_context',query='old suggested query',file_relationship='unproven')
    cache.write_text(json.dumps(data))
    requests=fake_search(monkeypatch)
    result=navigation.evidence(None,None,cache,tmp_path/'sources','district:fixture','new actual query')
    assert not requests
    assert not result['coverage']['complete']
    assert result['conversation_basis']['query']=='new actual query'


def test_federation_discloses_limits_failures_and_truncated_engine_results(tmp_path, monkeypatch):
    cache = catalog(tmp_path, source_count=13)
    requests = fake_search(monkeypatch)
    result = navigation.evidence(None, None, cache, tmp_path / "sources", "district:fixture", "marmot")
    assert len(requests) == 1
    assert len(requests[0]["scopes"]) == 13
    assert result["coverage"]["source_scopes"] == 13
    assert result["coverage"]["complete"]
    fake_search(monkeypatch, timed_out=True)
    limited = navigation.evidence(None, None, cache, tmp_path / "sources", "district:fixture", "marmot")
    assert not limited["coverage"]["complete"]
    assert limited["coverage"]["unsearched_source_ids"] and limited["errors"]
    cache = catalog(tmp_path)
    fake_search(monkeypatch, fail=True)
    failed = navigation.evidence(None, None, cache, tmp_path / "sources", "district:fixture", "marmot")
    assert failed["errors"] and not failed["coverage"]["complete"]
    fake_search(monkeypatch, truncated=True)
    truncated = navigation.evidence(None, None, cache, tmp_path / "sources", "district:fixture", "marmot")
    assert not truncated["coverage"]["complete"]


def test_cached_source_only_cli_does_not_require_conversation_index(tmp_path):
    cache = catalog(tmp_path)
    result = subprocess.run([sys.executable, str(ROOT / "navcom.py"), "atlas", "list", "planets", "--space-cache", str(cache),
                             "--index", str(tmp_path / "missing.sqlite"), "--json"], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["nodes"][0]["id"] == "planet:fixture"
    assert not (tmp_path / "missing.sqlite").exists()


@pytest.mark.skipif(not shutil.which("starforge"), reason="Optional installed Starforge required")
def test_actual_cli_refresh_flight_scoped_native_search_and_copy_replay(navcom, tmp_path, monkeypatch):
    monkeypatch.setattr(navcom, "INDEX_READ_ONLY", False)
    suite = tmp_path / "clients" / "Polaris" / "suite"
    suite.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(suite)], check=True)
    (suite / "package.json").write_text(json.dumps(dict(name="suite", workspaces=["apps/*"])))
    alpha, beta = [suite / "apps" / name for name in ("Alpha", "Beta")]
    code = "\n".join(['"""Marmot authentication orchestration."""', "def marmot_policy(value):"] +
                       [f"    step_{i} = value + {i}" for i in range(22)] + ["    return step_21", ""])
    for root in (alpha, beta):
        root.mkdir(parents=True)
        (root / "package.json").write_text(json.dumps(dict(name=root.name, scripts=dict(start="python worker.py"))))
        (root / "worker.py").write_text(code)
        (root / "README.md").write_text("# Marmot decisions and architectural notes\n" +
                                       ("Alpha uses expiring token sessions for marmot login.\n" if root == alpha else "Beta uses passkeys for marmot login.\n"))
    index = tmp_path / "custom.sqlite"
    conn = navcom.open_index(index)
    add(navcom, conn, tmp_path / "alpha.jsonl", "Alpha marmot decisions", "marmot login", str(alpha))
    add(navcom, conn, tmp_path / "beta.jsonl", "Beta marmot decisions", "marmot payment", str(beta))
    conn.close()
    sources, space = tmp_path / "sources", tmp_path / "space.json"
    env = dict(os.environ, NAVCOM_STARSHIP_ROOT=str(tmp_path / "no-fleet"))
    env.pop("NAVCOM_FLEET_SNAPSHOT", None)
    env.pop("NAVCOM_FLEET_CONFIG", None)
    def cli(*args):
        result = subprocess.run([sys.executable, str(ROOT / "navcom.py"), *map(str, args)], capture_output=True, text=True, env=env)
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)
    common = ["--space-cache", space, "--source-cache", sources, "--index", index, "--json"]
    intake = cli("atlas", "refresh", "--space", "--harvest", *common)
    assert intake["complete"] and not intake["failures"]
    published = json.loads(space.read_text())
    repeat = cli("atlas", "refresh", "--space", "--harvest", *common)
    assert repeat["complete"] and repeat["harvested"] == 0 and repeat["reused"] >= 1
    systems = cli("atlas", "list", "systems", *common)
    system = next(n for n in systems["nodes"] if n["label"] == "Polaris")
    planets = cli("atlas", "list", "planets", "--within", system["id"], *common)
    planet = next(n for n in planets["nodes"] if n["label"] == "Alpha")
    explored = cli("atlas", "explore", planet["id"], *common)
    assert explored["center"]["id"] == planet["id"]
    searched = cli("atlas", "search", "marmot", "--within", planet["id"], "--evidence", *common)
    evidence = searched["evidence"]
    assert not evidence["errors"]
    assert evidence["sources"][0]["concept_hits"] and evidence["sources"][0]["text_hits"]
    for field in ("concept_hits", "text_hits"):
        assert all(Path(hit["source_path"]).is_relative_to(alpha) for source in evidence["sources"] for hit in source[field])
    assert len(evidence["conversations"]) == 1
    assert evidence["conversations"][0]["project"] == str(alpha)
    assert str(index) in shlex.split(searched["cli_command"])
    replay = cli(*shlex.split(searched["cli_command"])[1:], "--json")
    assert [n["key"] for n in replay["evidence"]["conversations"]] == [n["key"] for n in evidence["conversations"]]
    assert replay["evidence"]["sources"][0]["query_cache_hit"]
    assert cli("atlas", "list", "planets", "--within", system["id"], *common)["nodes"] == planets["nodes"]
    assert any(n["id"] == planet["id"] for n in published["entities"])
    question="How do Alpha and Beta handle marmot login?"
    investigated=cli("atlas","navigate",question,"--within",system['id'],*common)
    proof=investigated['evidence']
    assert investigated['intent']['retrieval_style']=='question'
    assert 'marmot' in proof['query_plan']['text_terms'] and 'login' in proof['query_plan']['text_terms']
    assert any(source['concept_hits'] for source in proof['sources'])
    docs=[hit for source in proof['sources'] for hit in source['text_hits'] if hit['source_path'].endswith('README.md')]
    assert {hit['source_path'] for hit in docs}=={str(alpha/'README.md'),str(beta/'README.md')}
    assert all(hit['place_ids'] and hit['relative_path'].endswith('README.md') for hit in docs)
    alpha_place=next(p for p in proof['places'] if p['label']=='Alpha')
    beta_place=next(p for p in proof['places'] if p['label']=='Beta')
    assert all(ref['path'].startswith('apps/Alpha/') for ref in alpha_place['source_refs'])
    assert all(ref['path'].startswith('apps/Beta/') for ref in beta_place['source_refs'])
    assert alpha_place['conversation_hits']==beta_place['conversation_hits']==1
    assert cli("atlas","navigate",question,"--within",system['id'],*common)['evidence']['coverage']['query_cache_hits']>=1
    restored=cli('atlas','search',question,'--within',system['id'],'--evidence',*common)['evidence']
    assert restored['query_plan']==proof['query_plan']
    assert restored['coverage']['query_cache_hits']>=1
    assert [(h['source_path'],h['line'],h['place_ids']) for s in restored['sources'] for h in s['text_hits']]==[(h['source_path'],h['line'],h['place_ids']) for s in proof['sources'] for h in s['text_hits']]
    for literal in ('"marmot login"','where apps/Alpha/README.md'):
        retained=cli("atlas","navigate",literal,"--within",system['id'],*common)
        assert retained['intent']['query']==literal and retained['intent']['retrieval_style']=='literal'
        assert all(source['text_mode']=='literal' and not source['text_terms'] for source in retained['evidence']['sources'])


@pytest.mark.skipif(not shutil.which("starforge"), reason="Optional installed Starforge required")
def test_native_federation_finds_source_and_conversation_beyond_twelve(navcom, tmp_path, monkeypatch):
    from navcom_atlas import identity
    monkeypatch.setattr(navcom, "INDEX_READ_ONLY", False)
    index=tmp_path / "all.sqlite"
    conn=navcom.open_index(index)
    scopes=[]
    sources=[]
    collections=[]
    marker="zirconium flight protocol"
    for i in range(15):
        root=tmp_path / f"source-{i:02}"
        (root / "auth").mkdir(parents=True)
        text=marker if i==14 else "ordinary documentation"
        (root / "auth" / "README.md").write_text(text)
        # This match belongs to the same source but outside the saved place.
        (root / "outside.md").write_text(marker)
        sid=f"source-{i:02}"
        collection="projects:"+identity(str(root))
        sources.append(dict(id=sid,root=str(root),label=sid,include=["."],conversation_collection=collection))
        scopes.append(dict(source_id=sid,paths=["auth"]))
        collections.append(collection)
        add(navcom,conn,tmp_path / f"chat-{i:02}.jsonl",f"Project {i:02} notes",text,str(root))
    cache=tmp_path / "sources"
    interpreter=navcom_sources.runtime()
    worker=ROOT / "navcom_sources_worker.py"
    harvested=subprocess.run([interpreter,str(worker)],input=json.dumps(dict(action="harvest",cache=str(cache),sources=sources)),capture_output=True,text=True)
    assert harvested.returncode==0,harvested.stderr
    assert json.loads(harvested.stdout)["analyzed_sources"]==15
    space=tmp_path / "space.json"
    nodes=[dict(id="galaxy:all",kind="galaxy",label="All",parent_id=None,source_scopes=scopes,
                source_ids=[s["id"] for s in sources],conversation_collections=collections,
                position=dict(x=0,y=0),locations=[],evidence=[],examples=[])]
    space.write_text(json.dumps(dict(schema_version=1,published=123,entities=nodes,edges=[],coverage={})))
    result=navigation.evidence(navcom,conn,space,cache,"galaxy:all",marker)
    assert not result["errors"]
    assert result["coverage"]["searched_source_scopes"]==15
    assert result["coverage"]["searched_collections"]==15
    hits=[hit for source in result["sources"] for field in ("concept_hits","text_hits") for hit in source[field]]
    assert hits and {hit["source_id"] for hit in hits}=={"source-14"}
    assert all(hit["source_path"].endswith("auth/README.md") for hit in hits)
    assert len(result["conversations"])==1
    assert result["conversations"][0]["project"]==str(tmp_path / "source-14")
    # One place now scopes both engines to the first source; the fifteenth may
    # not leak back in through global source or conversation ranking.
    nodes[0]["source_scopes"]=scopes[:1]
    nodes[0]["conversation_collections"]=collections[:1]
    space.write_text(json.dumps(dict(schema_version=1,published=123,entities=nodes,edges=[],coverage={})))
    scoped=navigation.evidence(navcom,conn,space,cache,"galaxy:all",marker)
    assert not scoped["errors"]
    assert not scoped["conversations"]
    assert not scoped["sources"][0]["concept_hits"] and not scoped["sources"][0]["text_hits"]
    assert scoped["sources"][0]["query_cache_hit"]
    conn.close()


@pytest.mark.skipif(not shutil.which("starforge"), reason="Optional installed Starforge required")
def test_batch_budget_and_generation_remain_explicit(tmp_path):
    script='''
import json, sys
from pathlib import Path
import navcom_sources_worker as worker
cache=Path(sys.argv[1])
cache.mkdir()
worker.write(cache/'current.json',{'published':42})
clock=[0.0]
worker.time.monotonic=lambda:clock[0]
worker.extractor_signature=lambda:'test-extractor'
def search(request,cache,*,state,extractor):
    assert state['published']==42
    worker.write(cache/'current.json',{'published':99})
    clock[0]+=.6
    return {'concept_hits':[],'text_hits':[],'query_cache_hit':True,'potentially_truncated':False}
worker.combined_search=search
print(json.dumps(worker.batch_search({'query':'x','scopes':[{'source_id':str(i)} for i in range(3)],'time_budget_seconds':1},cache)))
'''
    run=subprocess.run([navcom_sources.runtime(),"-c",script,str(tmp_path / "cache")],cwd=ROOT,capture_output=True,text=True)
    assert run.returncode==0,run.stderr
    result=json.loads(run.stdout)
    assert result["coverage"]["published"]==42
    assert result["coverage"]["searched_source_scopes"]==2
    assert result["coverage"]["unsearched_source_ids"]==["2"]
    assert result["coverage"]["query_cache_hits"]==2
    assert not result["coverage"]["complete"]
