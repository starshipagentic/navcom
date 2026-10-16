"""Intake resumes tool-produced inventory without holding a SQLite writer."""
import json
import sys
import threading
import time

import pytest
import navcom_chart_refresh as refresh
import navcom_web


def setup(tmp_path, monkeypatch, projects=3):
    index=tmp_path/'index.sqlite'; index.touch()
    chart=tmp_path/'space.json'; cache=tmp_path/'sources'
    calls=[]
    rows=[dict(label=f'/fixture/project-{i}',collection=f'projects:{i}') for i in range(projects)]
    def run(request, seconds, cancel=None, progress=None):
        calls.append(request)
        if request['action']=='index': return dict(discovered=0,indexed=0,deferred=0,oversized=0)
        if request['action']=='inventory': return dict(projects=list(rows),jobs=[dict(root=r['label'],projects=[r]) for r in rows],grouping={},truncated=False)
        if request['action']=='runtime': return sys.executable
        if request['action']=='intake':return dict(analyzed_sources=1,published=True,skipped=[])
        chart.write_text('{}');return dict(destinations=projects,published=time.time())
    monkeypatch.setattr(refresh,'_run',run)
    return index,chart,cache,calls,rows,run


def test_resume_pins_inventory_and_warm_automatic_reads_do_no_work(tmp_path,monkeypatch):
    index,chart,cache,calls,rows,_=setup(tmp_path,monkeypatch)
    first=refresh.refresh(index,chart,cache,limit=1)
    assert first['visited']==1 and first['more'] and first['next_command']
    assert first['stop_reason']=='page_limit'
    assert not any(call['action']=='index' for call in calls), 'A selected-index CLI sweep must not ingest unrelated home logs.'
    rows.insert(0,dict(label='/new/project',collection='projects:new'))
    second=refresh.refresh(index,chart,cache,limit=2)
    assert second['complete'] and second['total']==3
    assert [r['job']['root'] for r in calls if r['action']=='intake']==[f'/fixture/project-{i}' for i in range(3)]
    assert len([r for r in calls if r['action']=='inventory'])==1
    count=len(calls)
    warm=refresh.refresh(index,chart,cache,automatic=True)
    assert warm['cached'] and len(calls)==count
    assert warm['stop_reason']=='cached'
    fresh=refresh.refresh(index,chart,cache,restart=True,limit=1)
    assert fresh['total']==4 and fresh['visited']==1


def test_failed_project_does_not_starve_later_sources(tmp_path,monkeypatch):
    index,chart,cache,calls,rows,run=setup(tmp_path,monkeypatch)
    def flaky(request,*args):
        if request['action']=='intake' and request['job']['projects']==[rows[0]]:raise ValueError('Offline source')
        return run(request,*args)
    monkeypatch.setattr(refresh,'_run',flaky)
    result=refresh.refresh(index,chart,cache)
    assert result['complete'] and result['visited']==3 and len(result['failures'])==1
    assert result['harvested']==2 and chart.exists()


def test_pause_preserves_current_job_and_releases_cross_process_lock(tmp_path,monkeypatch):
    index,chart,cache,calls,rows,run=setup(tmp_path,monkeypatch)
    cancel=threading.Event(); cancel.set()
    result=refresh.refresh(index,chart,cache,cancel=cancel)
    assert result['paused'] and result['visited']==0
    cancel.clear()
    result=refresh.refresh(index,chart,cache,cancel=cancel)
    assert result['complete'] and not result['paused']


def test_automatic_reload_keeps_saved_pause_until_explicit_continue(tmp_path,monkeypatch):
    index,chart,cache,calls,rows,run=setup(tmp_path,monkeypatch)
    refresh.refresh(index,chart,cache,limit=1)
    cancel=threading.Event();cancel.set()
    paused=refresh.refresh(index,chart,cache,cancel=cancel)
    assert paused['paused'] and paused['stop_reason']=='paused'
    before=refresh.state_path(cache, index_path=index, space_cache=chart).read_bytes(); count=len(calls)
    reloaded=refresh.refresh(index,chart,cache,automatic=True)
    assert reloaded['paused'] and reloaded['visited']==1
    assert len(calls)==count and refresh.state_path(cache, index_path=index, space_cache=chart).read_bytes()==before
    continued=refresh.refresh(index,chart,cache)
    assert continued['complete'] and continued['stop_reason']=='complete'


def test_index_batch_continues_before_repinning_inventory(tmp_path,monkeypatch):
    index,chart,cache,calls,rows,run=setup(tmp_path,monkeypatch,1)
    pending=[1,0]
    def partial(request,*args):
        if request['action']=='index':
            return dict(discovered=2,indexed=1,deferred=pending.pop(0),oversized=0)
        return run(request,*args)
    monkeypatch.setattr(refresh,'_run',partial)
    first=refresh.refresh(index,chart,cache,automatic=True,sync_index=True)
    assert first['more'] and not first['complete'] and first['stop_reason']=='index_batch_limit'
    second=refresh.refresh(index,chart,cache,automatic=True,sync_index=True)
    assert second['complete'] and not second['cached'] and pending==[]


def test_pause_during_first_index_is_durable_without_a_chart(tmp_path,monkeypatch):
    index,chart,cache,calls,rows,run=setup(tmp_path,monkeypatch,1)
    def interrupted(request,*args):
        if request['action']=='index':raise refresh.Interrupted('Paused during indexing')
        return run(request,*args)
    monkeypatch.setattr(refresh,'_run',interrupted)
    result=refresh.refresh(index,chart,cache,automatic=True,sync_index=True)
    assert result['paused'] and not chart.exists() and result['visited']==0
    monkeypatch.setattr(refresh,'_run',lambda *args,**kwargs:pytest.fail('Automatic reload resumed a paused first chart'))
    assert refresh.refresh(index,chart,cache,automatic=True,sync_index=True)['paused']
    monkeypatch.setattr(refresh,'_run',run)
    assert refresh.refresh(index,chart,cache,sync_index=True)['complete']
    count=len(calls)
    assert refresh.refresh(index,chart,cache,automatic=True,sync_index=True)['cached']
    assert len(calls)==count


def test_native_index_batch_discovers_fresh_project_and_reuses_unchanged_logs(navcom,tmp_path,monkeypatch):
    index=tmp_path/'index.sqlite';project=tmp_path/'clients'/'Quartz'/'instrument';project.mkdir(parents=True)
    key=tmp_path/'rollout-12345678-1234-1234-1234-123456789012.jsonl'
    key.write_text(json.dumps({'type':'session_meta','payload':{'cwd':str(project)}})+'\n'+
        json.dumps({'type':'response_item','timestamp':'2026-10-16T09:00:00Z','payload':{
            'type':'message','role':'user','content':[{'type':'input_text','text':'Calibrate instrument sensors'}]}})+'\n')
    logs=[(str(key),key.stat().st_mtime,key.stat().st_size,'codex')]
    monkeypatch.setattr(navcom,'list_logs',lambda providers:logs)
    first=refresh._sync_index(navcom,index)
    assert first['indexed']==1 and first['complete']
    conn=navcom.open_index(index)
    assert conn.execute('SELECT project FROM file_meta WHERE file=?',(str(key),)).fetchone()[0]==str(project)
    assert conn.execute('SELECT text FROM session_fts').fetchone()[0]=='Calibrate instrument sensors'
    conn.close()
    second=refresh._sync_index(navcom,index)
    assert second['indexed']==0 and second['changed']==0


def test_index_batch_bounds_and_oversized_disclosure(navcom,tmp_path,monkeypatch):
    logs=[(f'/fixture/session-{i}.jsonl',i,5,'codex') for i in range(4)]
    logs.append(('/fixture/large.jsonl',10,100,'codex'))
    monkeypatch.setattr(navcom,'list_logs',lambda providers:logs)
    monkeypatch.setattr(refresh,'INDEX_SESSION_LIMIT',2)
    monkeypatch.setattr(refresh,'INDEX_FILE_BYTES',20)
    seen=[]
    monkeypatch.setattr(navcom,'_index_logs',lambda conn,selected,**kw:seen.extend(selected) or len(selected))
    result=refresh._sync_index(navcom,tmp_path/'index.sqlite')
    assert result['indexed']==2 and result['deferred']==2 and result['oversized']==1
    assert [row[0] for row in seen]==['/fixture/session-3.jsonl','/fixture/session-2.jsonl']


def test_progress_ignores_native_parser_warnings(monkeypatch):
    monkeypatch.setattr(refresh,'SCRIPT',"import json,sys,time;print('navcom sources ▸ checking selected code',file=sys.stderr,flush=True);print('<unknown>:241: SyntaxWarning: invalid escape sequence',file=sys.stderr,flush=True);time.sleep(.2);print(json.dumps({'ok':True,'value':{}}))")
    seen=[]
    refresh._run({},3,progress=seen.append)
    assert seen==['navcom sources ▸ checking selected code']


def test_chart_failure_keeps_published_chart_and_retries_without_reharvest(tmp_path,monkeypatch):
    index,chart,cache,calls,rows,run=setup(tmp_path,monkeypatch,1)
    chart.write_text('{"old":true}')
    def flaky(request,*args):
        if request['action']=='chart':raise TimeoutError('Chart deadline')
        return run(request,*args)
    monkeypatch.setattr(refresh,'_run',flaky)
    result=refresh.refresh(index,chart,cache)
    assert result['more'] and result['chart_pending'] and result['chart_error']=='Chart deadline'
    assert json.loads(chart.read_text())=={'old':True}
    monkeypatch.setattr(refresh,'_run',run)
    result=refresh.refresh(index,chart,cache)
    assert result['complete'] and result['chart_error'] is None
    assert len([r for r in calls if r['action']=='intake'])==1


def test_large_output_does_not_deadlock_and_worker_timeout_is_bounded(monkeypatch):
    monkeypatch.setattr(refresh,'SCRIPT',"import json;print(json.dumps({'ok':True,'value':'x'*250000}))")
    assert len(refresh._run({},3))==250000
    monkeypatch.setattr(refresh,'SCRIPT',"import time;time.sleep(10)")
    start=time.monotonic()
    with pytest.raises(TimeoutError):refresh._run({},.15)
    assert time.monotonic()-start<2


def test_optional_starforge_failure_still_builds_metadata_chart(tmp_path,monkeypatch):
    index,chart,cache,calls,rows,run=setup(tmp_path,monkeypatch,1)
    def missing(request,*args):
        if request['action']=='runtime':raise ValueError('Starforge not installed')
        return run(request,*args)
    monkeypatch.setattr(refresh,'_run',missing)
    result=refresh.refresh(index,chart,cache)
    assert chart.exists() and result['visited']==0 and result['more']
    assert result['runtime_error']=='Starforge not installed' and not result['chart_pending']


def test_cancel_after_source_publication_still_recharts_on_cached_retry(tmp_path,monkeypatch):
    index,chart,cache,calls,rows,run=setup(tmp_path,monkeypatch,2)
    first=refresh.refresh(index,chart,cache,limit=1)
    assert not first['chart_pending']
    def interrupted(request,*args):
        if request['action']=='intake':raise refresh.Interrupted('Published but cancelled before receipt')
        return run(request,*args)
    monkeypatch.setattr(refresh,'_run',interrupted)
    paused=refresh.refresh(index,chart,cache)
    assert paused['paused'] and paused['chart_pending'] and paused['visited']==1
    def cached(request,*args):
        if request['action']=='intake':return dict(cached_sources=1,published=False,skipped=[])
        return run(request,*args)
    monkeypatch.setattr(refresh,'_run',cached)
    result=refresh.refresh(index,chart,cache)
    assert result['complete'] and len([r for r in calls if r['action']=='chart'])==2


def test_web_uses_shared_refresh_and_releases_lock(navcom,tmp_path,monkeypatch):
    index=tmp_path/'index.sqlite';navcom.open_index(index).close()
    app=navcom_web.WebApp(navcom,index)
    seen=[]
    def shared(*args,**kwargs):
        seen.append(kwargs)
        kwargs['progress']('Native harvest progress')
        return dict(complete=True,paused=False,more=False,cached=True,visited=3,total=3,failures=[],skipped=[])
    monkeypatch.setattr(refresh,'refresh',shared)
    app.mutation.acquire();app.refresh_space(True)
    assert not app.task['running'] and not app.task['error'] and not app.mutation.locked()
    assert seen[0]['automatic'] and seen[0]['sync_index'] and app.task['coverage']['cached']


def test_web_discloses_bounded_stop_instead_of_pause(navcom,tmp_path,monkeypatch):
    app=navcom_web.WebApp(navcom,tmp_path/'index.sqlite')
    clock=[0]
    monkeypatch.setattr(navcom_web.time,'monotonic',lambda:clock[0])
    def partial(*args,**kwargs):
        clock[0]+=60
        return dict(complete=False,paused=False,more=True,cached=False,visited=2,total=8,
                    failures=[],skipped=[],stop_reason='page_limit')
    monkeypatch.setattr(refresh,'refresh',partial)
    app.mutation.acquire();app.refresh_space(True)
    assert app.task['coverage']['stop_reason']=='time_budget'
    assert not app.task['coverage']['paused'] and not app.mutation.locked()
    assert 'two-minute work limit' in app.task['message'] and 'Continue chart resumes' in app.task['message']


def test_reloaded_bridge_reconnects_to_running_chart_and_can_pause(navcom,tmp_path):
    app=navcom_web.WebApp(navcom,tmp_path/'index.sqlite')
    app.task=dict(kind='chart',running=True,error=False,message='Harvesting source 4')
    app.mutation.acquire()
    try:
        assert app.post(None,'/api/space/refresh',{'automatic':True})==app.task
        app.post(None,'/api/space/refresh/pause',{})
        assert app.refresh_cancel.is_set()
    finally:
        app.mutation.release()
