import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import threading
from urllib.request import Request, urlopen
from urllib.error import HTTPError

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import navcom_web
import navcom_intelligence as intelligence


@pytest.fixture
def web(navcom, tmp_path, monkeypatch):
    path = tmp_path / 'index.sqlite'
    key = tmp_path / 'rollout-2026-10-12T16-36-33-01a126c8-331b-7aa2-8783-d9ff30c38f32.jsonl'
    key.write_text(json.dumps({'type':'session_meta','payload':{'id':'01a126c8-331b-7aa2-8783-d9ff30c38f32','cwd':str(tmp_path)}})+'\n'+
                   json.dumps({'type':'response_item','payload':{'type':'message','role':'user','content':[{'type':'input_text','text':'Find the zebracorn and fix it'}]}})+'\n')
    logs = [(str(key), 1, key.stat().st_size, 'codex')]
    conn = navcom.open_index(path); navcom.index_logs(conn, logs, progress=False); conn.close()
    monkeypatch.setattr(navcom, 'list_logs', lambda *_: logs)
    server = navcom_web.make_server(navcom, path)
    worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
    def request(route, data=None, token=True, extra=None):
        headers = {'X-Navcom-Token':server.app.token} if token else {}
        headers.update(extra or {})
        if data is not None: headers['Content-Type']='application/json'
        req = Request(f'http://127.0.0.1:{server.server_port}'+route,
                      data=json.dumps(data).encode() if data is not None else None,headers=headers)
        with urlopen(req, timeout=5) as response:
            raw=response.read().decode()
            return json.loads(raw) if route.startswith('/api/') else raw
    yield server, request, str(key), path
    server.shutdown();server.server_close();worker.join()


def test_web_security_and_render(web):
    server, request, key, path=web
    html=request('/',token=False)
    assert 'Mission control' in html and '__NAVCOM_TOKEN__' not in html
    assert 'https://' not in html and 'src="http' not in html
    assert '<script src="/navcom_atlas.js">' in html
    assert 'Conversation Atlas' in request('/navcom_atlas.js', token=False)
    assert '.atlas-node' in request('/navcom_atlas.css', token=False)
    for headers in ({}, {'Origin':'https://example.com'}, {'Host':'evil.example'}):
        with pytest.raises(HTTPError) as caught:
            request('/api/recent',token=bool(headers),extra=headers)
        assert caught.value.code==403


def test_web_search_read_annotate_state_and_plan(web):
    server, request, key, path=web
    catalog=request('/api/recent?q=zebracorn')
    assert key in catalog['matches']
    from urllib.parse import quote
    detail=request('/api/session?key='+quote(key))
    assert detail['turns'][0][2]=='Find the zebracorn and fix it'
    assert detail['plan']['argv'][0]=='codex'
    assert request('/api/annotation',{'key':key,'name':'My favorite','note':'Review next','favorite':True})['favorite']
    assert request('/api/recent?q=favorite')['annotations'][key]['name']=='My favorite'
    request('/api/state',{'selected':key,'query':'favorite','expanded':[key]})
    assert request('/api/state')['selected']==key
    with pytest.raises(HTTPError) as caught:request('/api/session?key=/etc/passwd')
    assert caught.value.code==400


def test_web_busy_write_does_not_kill_reads(web):
    server, request, key, path=web
    blocker=sqlite3.connect(path);blocker.execute('BEGIN IMMEDIATE')
    try:
        with pytest.raises(HTTPError) as caught:request('/api/annotation',{'key':key,'note':'blocked'})
        assert caught.value.code==409
        assert request('/api/task')['running'] is False
    finally:blocker.rollback();blocker.close()
    assert request('/api/annotation',{'key':key,'note':'saved'})['note']=='saved'


def test_web_upkeep_lock_error_can_retry(web, monkeypatch):
    import time
    server, request, key, path=web
    blocker=sqlite3.connect(path);blocker.execute('BEGIN IMMEDIATE')
    request('/api/upkeep',{})
    deadline=time.monotonic()+3
    while request('/api/task')['running'] and time.monotonic()<deadline:time.sleep(.03)
    assert request('/api/task')['error']
    blocker.rollback();blocker.close()
    monkeypatch.setattr(server.app.api,'_index_logs',lambda *a,**kw:1)
    monkeypatch.setattr(server.app.api,'upgrade_stale_parses',lambda *a,**kw:0)
    monkeypatch.setattr(server.app.api,'archive_logs',lambda *a,**kw:(0,0))
    request('/api/upkeep',{})
    deadline=time.monotonic()+3
    while request('/api/task')['running'] and time.monotonic()<deadline:time.sleep(.03)
    assert request('/api/task')['error'] is False
    assert 'Complete' in request('/api/task')['message']


def test_web_launch_uses_selected_plan(web, monkeypatch):
    server, request, key, _=web
    launched=[]
    monkeypatch.setattr(server.app.api.shutil,'which',lambda _: '/bin/true')
    monkeypatch.setattr(server.app.api,'resume_in_new_tab',lambda plan:(launched.append(plan) or True,'opened'))
    assert request('/api/launch',{'key':key})['ok']
    assert launched[0]['argv'][0:2]==['codex','resume']
    with pytest.raises(HTTPError): request('/api/launch',{'key':key,'harness':'sh; echo bad'})


def test_optional_model_uses_only_resident_small_model(monkeypatch):
    monkeypatch.setattr(intelligence,'capcom_route',lambda:dict(endpoint='http://127.0.0.1:11434',provider='ollama',model='gemma4:e4b'))
    calls=[]
    def request(endpoint,path,data=None,timeout=1):
        calls.append((path,data))
        if path=='/api/ps': return {'models':[{'name':'huge:70b','size_vram':40*1024**3},{'name':'gemma4:e4b','size_vram':3*1024**3}]}
        return {'message':{'content':'{"title":"Small title","note":"Review next"}'}}
    monkeypatch.setattr(intelligence,'_request',request)
    result=intelligence.suggest('test '*5000)
    assert result['model']=='gemma4:e4b'
    payload=calls[-1][1]
    assert len(payload['messages'][-1]['content'])<=6000
    assert payload['options']['num_ctx']==2048 and payload['options']['num_predict']==180
    assert all(path not in ('/api/pull','/api/create','/api/delete') for path,_ in calls)


def test_no_model_no_inference(monkeypatch):
    monkeypatch.setattr(intelligence,'capcom_route',lambda:None)
    calls=[]
    monkeypatch.setattr(intelligence,'_request',lambda endpoint,path,**kw:calls.append(path) or {'models':[]})
    assert intelligence.suggest('text')['available'] is False
    assert calls==['/api/ps']


def test_model_endpoint_cannot_redirect():
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    class Redirect(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(302)
            self.send_header('Location', 'https://example.com/private-excerpt')
            self.end_headers()
        def log_message(self, *args): pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Redirect)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        with pytest.raises(HTTPError) as caught:
            intelligence._request(f'http://127.0.0.1:{server.server_port}', '/api/ps')
        assert caught.value.code == 302
    finally:
        server.shutdown(); server.server_close(); worker.join()


def test_atlas_http_search_and_project_drilldown(web):
    server, request, key, _ = web
    from urllib.parse import quote
    atlas = request('/api/atlas?q=show%20me%20zebracorn&lens=project')
    assert atlas['indexed'] == 1 and atlas['matches'] == 1
    project = atlas['nodes'][0]['label']
    detail = request('/api/atlas?q=zebracorn&lens=project&group='+quote(project))
    assert detail['nodes'][0]['key'] == key
    assert detail['nodes'][0]['kind'] == 'conversation'
    with pytest.raises(HTTPError) as caught: request('/api/atlas?lens=invalid')
    assert caught.value.code == 400


def test_space_api_reuses_cli_contract_and_serves_only_packaged_art(web, monkeypatch, tmp_path):
    import navcom_navigation
    import navcom_space
    server, request, key, index = web
    cache=tmp_path/'space.json';sources=tmp_path/'sources'
    monkeypatch.setenv('NAVCOM_SPACE_CACHE',str(cache))
    monkeypatch.setenv('NAVCOM_SOURCES_CACHE',str(sources))
    monkeypatch.setenv('NAVCOM_STARSHIP_ROOT',str(tmp_path/'no-fleet'))
    with server.app.connect() as conn:
        navcom_space.refresh(server.app.api,conn,cache,source_cache=sources)
        cli=navcom_navigation.view(server.app.api,conn,space_cache=cache,source_cache=sources,action='explore',limit=80)
    response=request('/api/space?action=explore&limit=80')
    assert response==cli
    assert 'Galactic bridge' in request('/',token=False)
    for route in ['/api/space','/api/space/refresh']:
        with pytest.raises(HTTPError) as caught:request(route,{} if route.endswith('refresh') else None,token=False)
        assert caught.value.code==403
    with urlopen(f'http://127.0.0.1:{server.server_port}/assets/starship/city.png') as art:
        assert art.headers['Content-Type'].startswith('image/png')
        assert art.read(8)==b'\x89PNG\r\n\x1a\n'
    with pytest.raises(HTTPError) as caught:request('/assets/starship/../../navcom.py',token=False)
    assert caught.value.code==404


def test_space_refresh_retains_navigation_when_starforge_unavailable(web, monkeypatch, tmp_path):
    import navcom_sources
    import time
    server,request,_,_=web
    monkeypatch.setenv('NAVCOM_SPACE_CACHE',str(tmp_path/'space.json'))
    monkeypatch.setenv('NAVCOM_SOURCES_CACHE',str(tmp_path/'sources'))
    monkeypatch.setenv('NAVCOM_STARSHIP_ROOT',str(tmp_path/'no-fleet'))
    monkeypatch.setenv('NAVCOM_STARFORGE_PYTHON',str(tmp_path/'missing-starforge'))
    assert request('/api/space/refresh',{})['running']
    deadline=time.monotonic()+15
    while request('/api/task')['running'] and time.monotonic()<deadline:time.sleep(.03)
    task=request('/api/task')
    assert not task['running'] and not task['error']
    assert task['coverage']['runtime_error']
    assert task['coverage']['more']
    assert request('/api/space')['nodes']


def test_web_voice_size_limit_and_existing_local_provider(web, monkeypatch):
    import base64
    import navcom_voice
    _, request, _, _ = web
    monkeypatch.setattr(navcom_voice,'status',lambda:dict(available=True,model_loaded=False))
    seen=[]
    monkeypatch.setattr(navcom_voice,'transcribe',lambda audio:seen.append(audio) or dict(text='fly to example'))
    assert request('/api/voice')['model_loaded'] is False
    assert 'navcom-capture' in request('/navcom_voice_worklet.js',token=False)
    assert 'getUserMedia' in request('/navcom_voice.js',token=False)
    recording=b'x'*600000
    assert request('/api/voice',{'audio':base64.b64encode(recording).decode()})['text']=='fly to example'
    assert seen==[recording]
    with pytest.raises(HTTPError) as error:request('/api/voice',{'audio':''},extra={'Content-Length':'950001'})
    assert error.value.code==400
    with pytest.raises(HTTPError) as error:request('/api/state',{'query':''},extra={'Content-Length':'70000'})
    assert error.value.code==400
    with pytest.raises(HTTPError) as error:request('/api/voice',{'audio':'anything'},token=False)
    assert error.value.code==403
