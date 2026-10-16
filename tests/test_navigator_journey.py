"""Navigator resolves real scope and reports execution without inventing a trip."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

import navcom_navigation as navigation


@pytest.fixture
def geography(tmp_path):
    def node(identity, label, parent, kind):
        return dict(id=identity,label=label,parent_id=parent,kind=kind,locations=[],evidence=[],examples=[],source_ids=[],source_scopes=[],conversation_collections=[])
    path=tmp_path/'space.json'
    nodes=[node('galaxy:owner','Your galaxy',None,'galaxy'),
           node('system:alpha','Alpha','galaxy:owner','system'),
           node('planet:one','One','system:alpha','planet'),
           node('planet:two','One prototype','system:alpha','planet'),
           node('system:beta','Beta','galaxy:owner','system'),
           node('planet:three','One','system:beta','planet')]
    path.write_text(json.dumps(dict(schema_version=1,published=123,entities=nodes,edges=[],coverage={})))
    return path


def test_unique_destination_needs_no_source_scan(geography,monkeypatch):
    def no_scan(*args,**kwargs):raise AssertionError('Unnecessary evidence search')
    monkeypatch.setattr(navigation,'evidence',no_scan)
    result=navigation.navigate(None,None,space_cache=geography,source_cache=geography.parent/'sources',text='fly to One',within='system:alpha')
    assert result['destination']=='planet:one'
    assert result['intent']['within']=='system:alpha'
    assert result['steps'][-1]['status']=='resolved'
    assert 'evidence' not in result


def test_ambiguous_global_names_return_choices_and_preserve_search_vocabulary(geography,monkeypatch):
    calls=[]
    def proof(api,conn,space,source,within,query,limit,**kwargs):
        calls.append((within,query))
        return dict(sources=[],conversations=[],errors=[],coverage=dict(complete=True))
    monkeypatch.setattr(navigation,'evidence',proof)
    result=navigation.navigate(None,None,space_cache=geography,source_cache=geography.parent/'sources',text='fly to One',within='system:alpha',local=False)
    assert result['destination'] is None
    assert len(result['nodes'])==2
    assert calls==[]
    assert result['intent']['within']==''
    assert result['steps'][-1]['status']=='choose'
    searched=navigation.navigate(None,None,space_cache=geography,source_cache=geography.parent/'sources',text='find rare matrix',within='system:alpha')
    assert calls==[('system:alpha','rare matrix')]
    assert searched['steps'][-1]['status']=='complete'


def test_invalid_scope_fails_before_search(geography,monkeypatch):
    monkeypatch.setattr(navigation,'evidence',lambda *a,**k:pytest.fail('Scope broadened'))
    with pytest.raises(ValueError,match='not found'):
        navigation.navigate(None,None,space_cache=geography,source_cache=geography.parent/'sources',text='matrix',within='moon:missing')


def test_exact_destination_outside_first_page_and_opaque_id_resolve(geography,monkeypatch):
    data=json.loads(geography.read_text())
    data['entities'][2]['label']='Alpha project'
    geography.write_text(json.dumps(data))
    monkeypatch.setattr(navigation,'evidence',lambda *a,**k:pytest.fail('Exact destination was lost to pagination'))
    for query in ('fly to Alpha','fly to system:alpha'):
        result=navigation.navigate(None,None,space_cache=geography,source_cache=geography.parent/'sources',text=query,limit=1)
        assert result['destination']=='system:alpha'


def test_back_is_a_request_not_a_completed_browser_action(geography):
    result=navigation.navigate(None,None,space_cache=geography,source_cache=geography.parent/'sources',text='go back',within='system:alpha')
    assert result['action']=='back' and result['destination'] is None
    assert result['steps'][0]['status']=='requested'


def test_cli_and_web_use_the_same_navigator_contract(geography,navcom,monkeypatch):
    from navcom_web import WebApp
    index=geography.parent/'absent.sqlite'
    sources=geography.parent/'sources'
    monkeypatch.setenv('NAVCOM_SPACE_CACHE',str(geography))
    monkeypatch.setenv('NAVCOM_SOURCES_CACHE',str(sources))
    params=dict(q=['fly to One'],within=['system:alpha'])
    web=WebApp(navcom,index).get(None,'/api/navigate',params)
    command=[sys.executable,str(Path(__file__).resolve().parents[1]/'navcom.py'),'atlas','navigate','fly to One','--within','system:alpha','--index',str(index),'--limit','20','--json']
    run=subprocess.run(command,capture_output=True,text=True)
    assert run.returncode==0,run.stderr
    cli=json.loads(run.stdout)
    assert cli==web
    assert not index.exists()


def test_question_executes_upstream_term_plan_and_reports_actual_terms(geography,monkeypatch):
    calls=[]
    def proof(api,conn,space,source,within,query,limit,**kwargs):
        calls.append((within,query,{key:value for key,value in kwargs.items() if key!='catalog'}))
        return dict(sources=[],conversations=[],errors=[],coverage=dict(complete=True),
                    query_plan=dict(style='question',text_terms=['protocol','goals']))
    monkeypatch.setattr(navigation,'evidence',proof)
    question='Where are protocol goals discussed?'
    result=navigation.navigate(None,None,space_cache=geography,source_cache=geography.parent/'sources',text=question,within='system:alpha')
    assert calls==[('system:alpha',question,{'query_style':'question'})]
    assert any(step.get('terms')==['protocol','goals'] for step in result['steps'])
    assert result['destination'] is None


def test_shared_repository_hits_keep_exact_product_path_memberships():
    def place(name,paths):
        return dict(id='planet:'+name,label=name,kind='planet',source_scopes=[dict(source_id='shared',paths=paths)],conversation_collections=[])
    nodes=[place('Aurora',['apps/aurora']),place('Radar',['apps/radar'])]
    result=dict(sources=[dict(source_id='shared',concept_hits=[],text_hits=[
        dict(relative_path='apps/aurora/README.md',line=2,match='token login'),
        dict(relative_path='apps/radar/README.md',line=4,match='password login'),
        dict(relative_path='apps/aurora-old/README.md',line=1,match='unrelated')])],conversations=[],coverage={})
    navigation._place_evidence(None,nodes,result)
    hits=result['sources'][0]['text_hits']
    assert hits[0]['place_ids']==['planet:Aurora']
    assert hits[1]['place_ids']==['planet:Radar']
    assert hits[2]['place_ids']==[]
    assert all(p['text_hits']==1 for p in result['places'])
    assert result['coverage']['source_hits_without_place_membership']==1
    assert 'not proof of implementation' in result['place_policy']


def test_unsearched_product_is_not_reported_as_no_evidence():
    node=dict(id='planet:missing',label='Missing',kind='planet',source_scopes=[dict(source_id='offline',paths=['.'])],conversation_collections=[])
    result=dict(sources=[],conversations=[],coverage={})
    navigation._place_evidence(None,[node],result)
    assert result['places'][0]['state']=='coverage_unknown'
    assert not result['places'][0]['source_complete']
