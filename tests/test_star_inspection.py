import json
from pathlib import Path

import navcom_star_inspection as inspect


def center():
    star=dict(id='star-candidate:fixture', provider='hermes-compose', name='Tidal research',
              qualification='declared_candidate', description='Maintains tidal evidence',
              physical_binding=dict(repository='/research/tides',compose='/research/tides/hermes/compose.yml',
                                    service='worker',container_name='tidal-worker',image='local-tidal:7'),
              gaps=['Runtime unobserved'],interfaces=[])
    return dict(id=star['id'],kind='star',label=star['name'],star=star)


def test_browsing_never_observes_and_status_has_separate_cache(tmp_path,monkeypatch):
    calls=[]
    def observation(candidate):
        calls.append(candidate['id'])
        return dict(observed_at=inspect.time.time(),state='container_running',model_readiness='unverified')
    monkeypatch.setattr(inspect,'observe',observation)
    first=inspect.inspect_star(center(),tmp_path)
    assert first['observation'] is None and calls==[]
    second=inspect.inspect_star(center(),tmp_path,observe_status=True)
    assert second['observation']['model_readiness']=='unverified' and len(calls)==1
    third=inspect.inspect_star(center(),tmp_path)
    assert third['cached'] and len(calls)==1
    inspect.inspect_star(center(),tmp_path,observe_status=True)
    assert len(calls)==2
    changed=center();changed['star']['physical_binding']['image']='new-image'
    assert inspect.inspect_star(changed,tmp_path)['observation'] is None


def test_container_identity_does_not_become_readiness(monkeypatch):
    calls=[]
    monkeypatch.setattr(inspect.shutil,'which',lambda _: '/usr/bin/docker')
    def run(argv,request=None):
        calls.append(argv)
        return dict(running=True,status='running',image='local-tidal:7',
                    compose_directory='/unrelated',compose_service='worker')
    monkeypatch.setattr(inspect,'_run_json',run)
    result=inspect.observe(center()['star'])
    assert result['state']=='binding_unverified' and not result['binding_matches']
    assert not result['started_services'] and result['model_readiness']=='unverified'
    assert calls[0][:3]==['/usr/bin/docker','context','inspect']
    assert calls[1][:4]==['/usr/bin/docker','inspect','--type','container']
    assert calls[1][-1]=='tidal-worker'


def test_missing_docker_does_not_report_offline(monkeypatch):
    monkeypatch.setattr(inspect.shutil,'which',lambda _: None)
    result=inspect.observe(center()['star'])
    assert result['state']=='unknown'
    assert not result['started_services']


def test_status_cache_changes_with_docker_runtime(tmp_path,monkeypatch):
    calls=[]
    monkeypatch.setattr(inspect,'observe',lambda candidate:calls.append(candidate) or dict(observed_at=inspect.time.time(),state='unknown'))
    monkeypatch.setenv('DOCKER_CONFIG',str(tmp_path/'docker'))
    monkeypatch.setenv('DOCKER_CONTEXT','coast')
    initial=inspect.inspect_star(center(),tmp_path/'status',observe_status=True)
    assert not initial['cached'] and len(calls)==1
    monkeypatch.setenv('DOCKER_CONTEXT','mountain')
    assert inspect.inspect_star(center(),tmp_path/'status')['observation'] is None
    inspect.inspect_star(center(),tmp_path/'status',observe_status=True)
    assert len(calls)==2
    config=tmp_path/'docker/config.json';config.parent.mkdir();config.write_text('{"currentContext":"new"}')
    assert inspect.inspect_star(center(),tmp_path/'status')['observation'] is None


def test_observation_records_sanitized_runtime_location(monkeypatch):
    monkeypatch.setenv('DOCKER_HOST','ssh://private:secret@example.test:23/path?token=hidden')
    monkeypatch.delenv('DOCKER_CONTEXT',raising=False)
    monkeypatch.setattr(inspect.shutil,'which',lambda _: '/usr/bin/docker')
    monkeypatch.setattr(inspect,'_run_json',lambda *a,**k:dict(name='default',host='unix:///var/run/docker.sock'))
    result=inspect.observe(center()['star'])
    assert result['runtime']['endpoint']=='ssh://example.test:23'
    assert result['runtime']['selection']=='DOCKER_HOST'
    assert 'secret' not in json.dumps(result) and 'hidden' not in json.dumps(result)
    assert result['state']=='unknown' and result['model_readiness']=='unverified'


def test_compose_file_and_image_are_part_of_status_identity(monkeypatch):
    monkeypatch.setattr(inspect.shutil,'which',lambda _: '/usr/bin/docker')
    state=dict(running=True,status='running',image='local-tidal:7',compose_directory='/research/tides/hermes',compose_service='worker',compose_files='/research/tides/hermes/other.yml')
    monkeypatch.setattr(inspect,'_run_json',lambda *args,**kwargs:state)
    candidate=center()['star']
    assert inspect.observe(candidate)['state']=='binding_unverified'
    state['compose_files']='/research/tides/hermes/compose.yml'
    assert inspect.observe(candidate)['state']=='container_running'
    candidate['physical_binding']['image']=''
    assert inspect.observe(candidate)['state']=='binding_unverified'
    assert inspect.observe(candidate)['image_evidence']=='undeclared'


def test_selected_metadata_refresh_persists_until_chart_changes(tmp_path,monkeypatch):
    import navcom_stars
    current=center();fresh=center()['star'];fresh['description']='New maintained evidence'
    calls=[]
    def discover(*args,**kwargs):
        calls.append(1)
        return dict(candidates=[fresh],observed_at=123,gaps=[])
    monkeypatch.setattr(navcom_stars,'discover',discover)
    updated=inspect.inspect_star(current,tmp_path,refresh=True)
    assert updated['description']=='New maintained evidence' and not updated['metadata_cached']
    returned=inspect.inspect_star(current,tmp_path)
    assert returned['description']=='New maintained evidence' and returned['metadata_observed_at']==123
    assert returned['metadata_cached'] and len(calls)==1
    current['star']['description']='Newer chart publication'
    assert inspect.inspect_star(current,tmp_path)['description']=='Newer chart publication'


def test_untrusted_interface_argv_is_not_executed(monkeypatch):
    candidate=center()['star'];candidate['interfaces']=[dict(effect='observe_status',argv=['touch','/tmp/untrusted'])]
    calls=[]
    monkeypatch.setattr(inspect.shutil,'which',lambda _: '/usr/bin/docker')
    monkeypatch.setattr(inspect,'_run_json',lambda argv,request=None:calls.append(argv))
    assert inspect.observe(candidate)['state']=='unknown'
    assert calls and 'touch' not in calls[0]


def test_cli_and_web_share_cached_star_dossier(tmp_path):
    import subprocess,sys,sqlite3
    import navcom,navcom_web
    cache=tmp_path/'space.json';star=center()
    galaxy=dict(id='galaxy:owner',kind='galaxy',label='Your galaxy',parent_id=None,locations=[],examples=[],description='',evidence=[])
    star['parent_id']='galaxy:owner'
    star.update(locations=[],examples=[],description=star['star']['description'],evidence=[])
    cache.write_text(json.dumps(dict(schema_version=1,entities=[galaxy,star],edges=[],coverage={},published=1)))
    env=dict(inspect.os.environ,NAVCOM_SPACE_CACHE=str(cache))
    root=Path(__file__).resolve().parents[1]
    result=subprocess.run([sys.executable,str(root/'navcom.py'),'atlas','inspect',star['id'],'--space-cache',str(cache),'--index',str(tmp_path/'missing'),'--json'],capture_output=True,text=True,env=env)
    assert result.returncode==0,result.stderr
    cli=json.loads(result.stdout)
    previous=inspect.os.environ.get('NAVCOM_SPACE_CACHE');inspect.os.environ['NAVCOM_SPACE_CACHE']=str(cache)
    try:
        web=navcom_web.WebApp(navcom,tmp_path/'index')
        with sqlite3.connect(':memory:') as conn:
            api=web.get(conn,'/api/space/inspect',{'within':[star['id']]})
    finally:
        if previous is None:inspect.os.environ.pop('NAVCOM_SPACE_CACHE',None)
        else:inspect.os.environ['NAVCOM_SPACE_CACHE']=previous
    assert api['inspection']==cli['inspection']
    assert cli['inspection']['observation'] is None
