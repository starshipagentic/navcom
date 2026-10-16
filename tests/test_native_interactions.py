"""Shared CLI/web boundary: requests select identities, never executable commands."""
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace
import pytest
import navcom_navigation as navigation
import navcom_star_chat
import navcom_ship_boarding
import navcom_web

@pytest.fixture
def native(tmp_path, monkeypatch):
    nodes=[dict(id='galaxy:owner',kind='galaxy',label='Galaxy',parent_id=None,position={}),
           dict(id='star:test',kind='star',label='Expert',parent_id='galaxy:owner',position={}),
           dict(id='ship:test',kind='ship',label='Ship',parent_id='galaxy:owner',position={})]
    for node in nodes:node.update(locations=[],evidence=[],examples=[])
    cache=tmp_path/'space.json';cache.write_text(json.dumps(dict(schema_version=1,published=123,entities=nodes,edges=[],coverage={})))
    monkeypatch.setenv('NAVCOM_SPACE_CACHE',str(cache))
    launched=[]
    api=SimpleNamespace(resume_in_new_tab=lambda p:(launched.append(p) or True,'opened'))
    return api,cache,launched,tmp_path


def test_expert_preview_cannot_launch_and_handoff_revalidates(native,monkeypatch):
    api,cache,launched,folder=native
    spec=dict(argv=['/installed/hermes','chat','--query=literal $(touch nope)'],cwd=str(folder),env={'HERMES_HOME':str(folder/'profile')})
    calls=[]
    def prepare(center,question,path):calls.append((center['id'],question));return dict(state='review_required',review_token='token',handoff=spec)
    def handoff(center,question,path,*,review_token):
        assert review_token=='token';calls.append(('validated',question));return dict(state='ready_for_native_handoff',handoff=spec,execution={})
    monkeypatch.setattr(navcom_star_chat,'prepare',prepare);monkeypatch.setattr(navcom_star_chat,'handoff',handoff)
    navigation.interact(api,space_cache=cache,within='star:test',action='ask',question='literal')
    assert not launched
    result=navigation.interact(api,space_cache=cache,within='star:test',action='ask',question='literal',launch=True,review_token='token')['interaction']
    assert result['state']=='dispatched' and result['expert_reply_verified'] is False
    assert launched[0]['argv']==['/usr/bin/env','HERMES_HOME='+str(folder/'profile')]+spec['argv']
    assert calls==[('star:test','literal'),('validated','literal')]


def test_refused_terminal_does_not_report_success(native,monkeypatch):
    api,cache,_,folder=native
    api.resume_in_new_tab=lambda _: (False,'No terminal available')
    monkeypatch.setattr(navcom_star_chat,'handoff',lambda *a,**k:dict(handoff=dict(argv=['/hermes'],cwd=str(folder),env={}),execution={}))
    with pytest.raises(ValueError,match='No terminal'):
        navigation.interact(api,space_cache=cache,within='star:test',action='ask',question='hello',launch=True,review_token='token')


def test_web_board_ignores_client_commands_and_runtime(native,monkeypatch):
    api,cache,launched,folder=native
    app=navcom_web.WebApp(api,folder/'index.sqlite')
    called=[]
    monkeypatch.setattr(navcom_ship_boarding,'plan_boarding',lambda center,**kw:called.append((center['id'],kw)) or dict(state='blocked',reason='No route'))
    result=app.post(None,'/api/space/board',dict(within='ship:test',argv=['/evil'],route_path='/evil',trusted_runtime={'node':'/evil'}))
    assert called==[('ship:test',{'route_path':None})]
    assert not launched and result['interaction']['state']=='blocked'
    with pytest.raises(ValueError,match='booleans'):app.post(None,'/api/space/board',dict(within='ship:test',launch='false'))


def test_cli_actions_and_voice_help_do_not_open_index(navcom,tmp_path,monkeypatch,capsys):
    import sys
    monkeypatch.setitem(sys.modules,navcom.__name__,navcom)
    monkeypatch.setenv('NAVCOM_INDEX',str(tmp_path/'absent.sqlite'))
    for args in (['atlas','ask','--help'],['atlas','board','--help'],['voice','--help'],['help','voice']):
        try:result=navcom.run(args)
        except SystemExit as exc:result=exc.code
        assert result==0
        assert 'usage:' in capsys.readouterr().out
    assert not (tmp_path/'absent.sqlite').exists()
