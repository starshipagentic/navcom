"""The CLI and HTTP landing entry points retain server-owned historical scope."""
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import pytest

import navcom_history_cli as cli
from navcom_web import WebApp


def test_landing_help_requires_saved_evidence_identity(capsys):
    with pytest.raises(SystemExit) as result:
        cli.parser().parse_args(['land','--help'])
    assert result.value.code == 0
    text=' '.join(capsys.readouterr().out.split())
    for phrase in ('--cursor','--result-key','--group','--query','never resolves current ownership','selects a new HEAD'):
        assert phrase in text
    with pytest.raises(SystemExit):
        cli.parser().parse_args(['land','planet:orchard'])


def test_landing_cli_does_not_resolve_current_catalog(navcom,tmp_path,monkeypatch,capsys):
    import navcom_historical_landing as landing
    import navcom_navigation
    def forbidden(*args,**kwargs):
        pytest.fail('Saved landing tried to resolve current catalog paths')
    monkeypatch.setattr(navcom_navigation,'paths',forbidden)
    calls=[]
    monkeypatch.setattr(landing,'landing',lambda *args,**kwargs: calls.append((args,kwargs)) or {'action':'fixture'})
    cursor='a'*64+':8';key='b'*64
    assert cli.run(navcom,['land','planet:orchard','--cursor',cursor,'--result-key',key,
        '--group','historical-district:auth','--query','login','--cache',str(tmp_path/'history'),'--json'])==0
    assert calls[0][0]==(cursor,'planet:orchard')
    options=calls[0][1]
    assert options['result_key']==key and options['group_id']=='historical-district:auth'
    assert options['query']=='login' and options['cache_path']==tmp_path/'history'
    assert json.loads(capsys.readouterr().out)=={'action':'fixture'}


@pytest.mark.parametrize('changes',[
    {'within':None},{'within':''},{'cursor':[]},{'result_key':None},
    {'group':2},{'q':False},{'limit':True},{'limit':'20'},
])
def test_landing_api_rejects_invalid_request_before_service(navcom,tmp_path,monkeypatch,changes):
    import navcom_historical_landing as landing
    def forbidden(*args,**kwargs):
        pytest.fail('Invalid landing reached the service')
    monkeypatch.setattr(landing,'landing',forbidden)
    body=dict(within='planet:orchard',cursor='a'*64+':0',result_key='b'*64)
    body.update(changes)
    with pytest.raises(ValueError):
        WebApp(navcom,tmp_path/'index.sqlite').post(None,'/api/history/land',body)


def test_landing_api_keeps_server_cache_and_deadline(navcom,tmp_path,monkeypatch):
    import navcom_historical_landing as landing
    cache=tmp_path/'history';monkeypatch.setenv('NAVCOM_HISTORY_CACHE',str(cache))
    calls=[]
    monkeypatch.setattr(landing,'landing',lambda *args,**kwargs: calls.append((args,kwargs)) or {'saved':True})
    body=dict(within='planet:orchard',cursor='a'*64+':4',result_key='b'*64,group='auth',q='login',limit=9,
              cache_path='/untrusted',seconds=120,repo='/untrusted',space_cache='/untrusted')
    assert WebApp(navcom,tmp_path/'index.sqlite').post(None,'/api/history/land',body)=={'saved':True}
    assert calls[0][0]==(body['cursor'],body['within'])
    assert calls[0][1]==dict(result_key=body['result_key'],group_id='auth',query='login',limit=9,seconds=15,cache_path=cache)


@pytest.mark.skipif(not shutil.which('starforge'), reason='Optional native Starforge required')
def test_public_landing_cli_api_and_reader_survive_deleted_live_sources(navcom,tmp_path,monkeypatch):
    from test_historical_landing import create_landing_fixture
    f=create_landing_fixture(tmp_path)
    monkeypatch.setenv('NAVCOM_HISTORY_CACHE',str(f['cache_path']))
    entry=Path(cli.__file__).with_name('navcom.py')
    product=next(n for n in f['result']['nodes'] if n['id']==f['product_id'])
    def invoke(command):
        args=shlex.split(command)[1:]
        result=subprocess.run([sys.executable,str(entry),*args,'--json'],capture_output=True,text=True,timeout=30)
        assert result.returncode==0,result.stderr
        return json.loads(result.stdout)
    first=invoke(product['land_command'])
    group=next(n for n in first['nodes'] if n['kind']=='district' and 'apps/lantern/auth/signin.py' in n['files'])
    # The public entry points must not need the original live chart or repository.
    f['space_cache'].unlink()
    shutil.rmtree(f['repo'])
    scoped=invoke(group['land_command']+' --query Password')
    assert scoped['cursor']==f['result']['cursor'] and scoped['commit']==f['commit']
    assert scoped['center']['id']==group['id'] and scoped['allowed_paths']==group['files']
    app=WebApp(navcom,tmp_path/'index.sqlite')
    api=app.post(None,'/api/history/land',dict(within=f['product_id'],cursor=first['cursor'],
        result_key=first['result_key'],group=group['id'],q='Password'))
    assert api['evidence']['query_cache_hit'] and api['coverage']['harvest_invocations']==0
    for field in ('concept_hits','text_hits'):
        assert api['evidence'][field]
        assert all(h['relative_path'] in group['files'] for h in api['evidence'][field])
    ref=next(file['source_ref'] for file in api['files'] if file['path']=='apps/lantern/auth/signin.py')
    import navcom_source_reader
    read=navcom_source_reader.read_source(ref['source_id'],ref['relative_path'],history=ref['history'],
        snapshot=ref['snapshot'],history_cache=f['cache_path'],limit=3)
    assert read['provenance']['commit']==f['commit']
