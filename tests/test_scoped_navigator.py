"""Named-place plans resolve before scanning and preserve their allowed boundary."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

import navcom_navigation as navigation
from navcom_navigation_intent import interpret
from test_navigator_journey import geography


@pytest.mark.parametrize('command,place,query,travel',[
    ('find matrix in EXP32','EXP32','matrix',False),
    ('search for login within Mobile','Mobile','login',False),
    ('take me to EXP32 and search matrix','EXP32','matrix',True),
    ('fly to One then find rare matrix','One','rare matrix',True),
])
def test_scoped_command_plan(command,place,query,travel):
    result=interpret(command,'system:alpha')
    assert result['scope_query']==place and result['query']==query
    assert result['navigate_first'] is travel
    assert result['within']=='system:alpha'


@pytest.mark.parametrize('command',['find "matrix in One"','find matrix in src/One','find `in One`'])
def test_literal_or_path_queries_do_not_become_scope_commands(command):
    assert 'scope_query' not in interpret(command,'system:alpha')


def proof_calls(monkeypatch):
    calls=[]
    def evidence(api,conn,space,source,within,query,limit,**kwargs):
        calls.append((within,query))
        return dict(sources=[],conversations=[],errors=[],coverage=dict(complete=True))
    monkeypatch.setattr(navigation,'evidence',evidence)
    return calls


def run(geography,**kwargs):
    return navigation.navigate(None,None,space_cache=geography,source_cache=geography.parent/'sources',**kwargs)


def test_named_place_search_only_scans_resolved_scope(geography,monkeypatch):
    calls=proof_calls(monkeypatch)
    result=run(geography,text='find matrix in One',within='system:alpha')
    assert calls==[('planet:one','matrix')]
    assert result['scope_status']=='resolved' and result['scope_target']['id']=='planet:one'
    assert result['intent']['within']=='planet:one' and result['destination'] is None
    assert result['steps'][0]['status']=='resolved'


def test_ambiguous_missing_and_outside_places_never_trigger_global_scan(geography,monkeypatch):
    calls=proof_calls(monkeypatch)
    for text,within,status in [('find matrix in One','','choose'),('find matrix in missing','','not_found'),
                              ('find matrix in Beta','system:alpha','not_found')]:
        result=run(geography,text=text,within=within)
        assert result['scope_status']==status and 'evidence' not in result
        if status=='choose':
            assert all('--choose '+node['id'] in result['scope_choice_commands'][node['id']] for node in result['scope_candidates'])
    assert calls==[]
    result=run(geography,text='find matrix in One',scope_choice='planet:three')
    assert result['scope_target']['id']=='planet:three' and calls==[('planet:three','matrix')]
    with pytest.raises(ValueError,match='allowed scope'):
        run(geography,text='find matrix in One',within='system:alpha',scope_choice='planet:three')
    with pytest.raises(ValueError,match='requires'):
        run(geography,text='matrix',scope_choice='planet:one')


def test_travel_search_returns_destination_and_query_in_one_shared_plan(geography,monkeypatch):
    calls=proof_calls(monkeypatch)
    result=run(geography,text='fly to One then find matrix',within='system:alpha')
    assert result['destination']=='planet:one' and result['intent']['navigate_first']
    assert result['intent']['query']=='matrix' and calls==[('planet:one','matrix')]


def test_name_tokens_win_over_inherited_path_mentions_without_guessing_aliases(geography,monkeypatch):
    data=json.loads(geography.read_text())
    data['entities'][2]['label']='exp47-orchard'
    data['entities'][3]['label']='side-lab'
    data['entities'][3]['locations']=[dict(path='/dev/exp47-orchard/LABS/side-lab')]
    geography.write_text(json.dumps(data))
    calls=proof_calls(monkeypatch)
    result=run(geography,text='find matrix in exp47')
    assert result['scope_target']['id']=='planet:one'
    assert calls==[('planet:one','matrix')]
    direct=run(geography,text='fly to exp47')
    assert direct['destination']=='planet:one' and len(calls)==1


def test_public_cli_and_api_share_scope_choices(geography,navcom,monkeypatch):
    from navcom_web import WebApp
    monkeypatch.setenv('NAVCOM_SPACE_CACHE',str(geography))
    monkeypatch.setenv('NAVCOM_SOURCES_CACHE',str(geography.parent/'sources'))
    index=geography.parent/'empty.sqlite'
    conn=navcom.open_index(index)
    try:
        app=WebApp(navcom,index)
        web=app.get(conn,'/api/navigate',{'q':['find matrix in One'],'choose':['planet:three']})
        cmd=[sys.executable,str(Path(__file__).resolve().parents[1]/'navcom.py'),'atlas','navigate',
             'find matrix in One','--choose','planet:three','--index',str(index),'--json']
        cli=json.loads(subprocess.run(cmd,capture_output=True,text=True,check=True).stdout)
        assert web['scope_target']==cli['scope_target']==dict(id='planet:three',label='One',kind='planet')
        assert web['intent']==cli['intent']
    finally:
        conn.close()
