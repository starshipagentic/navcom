"""The public CLI and web API share native carried-context recovery and pins."""
import json
from pathlib import Path
import shlex
import subprocess
import sys

import pytest

from navcom_web import WebApp
from test_ship_context import require_native, ship


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def journey(ship, tmp_path, monkeypatch, navcom):
    entity, root, catalog = ship
    chart = tmp_path/'space.json'
    galaxy=dict(id='galaxy:owner',kind='galaxy',label='Galaxy',parent_id=None,position={},locations=[],evidence=[],examples=[])
    remote=dict(entity,id='fleet:ship:remote',label='Remote Orchard',physical=dict(host='remote.invalid',path=str(root)))
    chart.write_text(json.dumps(dict(schema_version=1,published=123,entities=[galaxy,entity,remote],edges=[],coverage={})))
    index=tmp_path/'no-conversation-index.sqlite'
    monkeypatch.setenv('NAVCOM_SPACE_CACHE',str(chart))
    monkeypatch.setenv('NAVCOM_INDEX',str(index))
    app=WebApp(navcom,index)
    def cli(*args, code=0):
        result=subprocess.run([sys.executable,str(ROOT/'navcom.py'),'atlas','context',entity['id'],
            '--space-cache',str(chart),'--index',str(index),*map(str,args),'--json'],capture_output=True,text=True)
        assert result.returncode==code,result.stderr
        return json.loads(result.stdout)
    def api(**args):
        params=dict(within=entity['id'],**args)
        return app.get(None,'/api/space/context',{k:[str(v)] for k,v in params.items()})
    def replay(command,code=0):
        argv=shlex.split(command)
        assert argv[0]=='navcom'
        result=subprocess.run([sys.executable,str(ROOT/'navcom.py'),*argv[1:],'--index',str(index),'--json'],capture_output=True,text=True)
        assert result.returncode==code,result.stderr
        return json.loads(result.stdout)
    return dict(entity=entity,root=root,catalog=catalog,chart=chart,index=index,app=app,cli=cli,api=api,replay=replay)


def test_public_native_cli_and_api_search_open_and_pinned_command_replay(journey):
    require_native()
    cli,api,replay=journey['cli'],journey['api'],journey['replay']
    found=cli('--query','amber','--limit','1','--max-chars','20')
    web=api(action='search',q='amber',limit=1,max_chars=20)
    assert found['messages']==web['messages'] and found['catalog']==web['catalog']
    assert found['messages'][0]['text_truncated'] and found['next_offset']==1
    assert '--catalog '+found['catalog'] in found['continue_command']
    second=replay(found['continue_command'])
    assert second['messages'][0]['index']==7 and second['next_offset'] is None
    original=found['messages'][0]
    opened=cli('--session',original['id'],'--turn',original['index'],'--catalog',found['catalog'])
    web_open=api(action='open',ref=original['id'],turn=original['index'],catalog=found['catalog'])
    assert opened['messages']==web_open['messages']
    assert opened['messages'][0]['text']=='Why did Orchard choose amber storage?'
    assert replay(original['open_command'])['messages'][0]['index']==3
    assert not journey['index'].exists()


def test_public_catalog_and_handover_have_bounded_continuations(journey):
    cli,api,replay=journey['cli'],journey['api'],journey['replay']
    inventory=cli('--limit','1')
    assert inventory['sessions']==api(limit=1)['sessions']
    assert inventory['next_offset']==1 and not inventory['coverage']['dialogue_read']
    assert replay(inventory['continue_command'])['sessions'][0]['id']=='session-1'
    handover=cli('--handover','--max-chars','12')
    assert handover['text']==api(action='handover',max_chars=12)['text']
    assert handover['catalog']=='' and '--catalog' not in handover['continue_command']
    next_page=replay(handover['continue_command'])
    assert next_page['offset']==12 and next_page['context_kind']=='handover'


@pytest.mark.parametrize('action',['inspect','search','open'])
def test_public_cli_and_api_reject_catalog_changes_between_actions(journey,action):
    require_native()
    initial=journey['cli']('--query','amber')
    path=journey['catalog'];data=json.loads(path.read_text());data['activated_at']='later';path.write_text(json.dumps(data))
    args=['--catalog',initial['catalog']]
    query=dict(action=action,catalog=initial['catalog'])
    if action=='search':args+=['--query','amber'];query['q']='amber'
    elif action=='open':args+=['--session','session-0','--turn','3'];query.update(ref='session-0',turn=3)
    cli=journey['cli'](*args,code=2)
    web=journey['api'](**query)
    assert cli['state']==web['state']=='unavailable'
    assert 'catalog changed' in cli['reason'] and not cli['coverage']['complete']
    assert cli['messages']==web['messages']==[]


def test_remote_context_is_unavailable_in_main_cli_and_web(journey):
    command=['navcom','atlas','context','fleet:ship:remote','--query','amber','--space-cache',str(journey['chart'])]
    result=journey['replay'](shlex.join(command),code=2)
    web=journey['app'].get(None,'/api/space/context',dict(within=['fleet:ship:remote'],action=['search'],q=['amber']))
    assert result['state']==web['state']=='unavailable'
    assert 'remote or unspecified' in result['reason'] and result['messages']==[]


def test_context_help_and_human_output_are_usable_without_index(journey):
    result=subprocess.run([sys.executable,str(ROOT/'navcom.py'),'atlas','context','--help'],capture_output=True,text=True)
    assert result.returncode==0 and '--catalog' in result.stdout and 'exact original native message' in result.stdout
    result=subprocess.run([sys.executable,str(ROOT/'navcom.py'),'atlas','context',journey['entity']['id'],
        '--handover','--space-cache',str(journey['chart']),'--index',str(journey['index'])],capture_output=True,text=True)
    assert result.returncode==0 and 'Recover amber storage decisions' in result.stdout
    assert not journey['index'].exists()
