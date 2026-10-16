"""Runnable lab facilities keep their exact scope and native application identity."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

import navcom_space as space
from test_space import API, database, git, package, source_cache


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def isolated_providers(tmp_path, monkeypatch):
    monkeypatch.setenv('NAVCOM_STARSHIP_ROOT', str(tmp_path/'no-fleet'))
    monkeypatch.setenv('HERMES_HOME', str(tmp_path/'no-hermes'))
    monkeypatch.delenv('NAVCOM_FLEET_SNAPSHOT', raising=False)
    monkeypatch.delenv('NAVCOM_FLEET_CONFIG', raising=False)


def native_app(relative, label):
    return dict(root=relative, manifest=relative+'/package.json', name=label,
                entry_points=[dict(type='npm-script', name='npm run dev', file='package.json')])


def fixture(tmp_path, *, workspace=False, nested_git=False):
    root=git(tmp_path/'clients'/'Lyra'/'observing-suite')
    package(root, name='suite', workspaces=['apps/*'] + (['LABS/trial/*'] if workspace else []))
    mobile=package(root/'apps'/'mobile', name='Field mobile', scripts={'start':'not executed'})
    lab=root/'LABS'/'trial'
    editor=package(lab/'editor', name='Calibration editor', scripts={'dev':'not executed'})
    if nested_git:
        git(editor, 'git@example.test:independent/editor.git')
    sources=source_cache(tmp_path,[root])
    groups=[dict(paths=['LABS/trial/editor/calibration.py','LABS/trial/editor/measurement.py'],
                 shared_tokens=['calibration','instrument'],cohesion=.7)]
    structure=dict(application_candidates=[] if workspace else [native_app('LABS/trial/editor','Calibration editor')],
                   token_groups=groups)
    (sources/'artifacts/0/structure.json').write_text(json.dumps(structure))
    conn=database([(root,'Suite work'),(mobile,'Mobile work'),(editor,'Marmot calibration')])
    return root,mobile,lab,editor,sources,conn


def node_at(data,path):
    found=[node for node in data['entities'] if any(loc['path']==str(path) for loc in node.get('locations',[]))]
    assert len(found)==1
    return found[0]


@pytest.mark.parametrize('workspace',[False,True])
def test_existing_app_reclassified_with_same_id_position_native_groups_and_exact_scopes(tmp_path,monkeypatch,workspace):
    root,mobile,lab,editor,sources,conn=fixture(tmp_path,workspace=workspace)
    cache=tmp_path/'space.json'
    # Simulate the previous published service behavior, not a hand-edited chart.
    with monkeypatch.context() as previous:
        previous.setattr(space,'_place_lab_applications',lambda *_:[])
        old=space.refresh(API,conn,cache,source_cache=sources)
    old_app=node_at(old,editor)
    old_group=next(n for n in old['entities'] if n['kind']=='district' and n['parent_id']==old_app['id'])
    assert old_app['kind']=='planet'
    new=space.refresh(API,conn,cache,source_cache=sources)
    app=node_at(new,editor); experiment=node_at(new,lab); product=node_at(new,root)
    assert app['kind']=='district' and app['form']=='application'
    assert app['id']==old_app['id'] and app['position']==old_app['position']
    assert app['parent_id']==experiment['id'] and experiment['parent_id']==product['id']
    assert app['source_scopes']==old_app['source_scopes']
    assert app['conversation_collections']==old_app['conversation_collections']
    assert app['direct_conversation_count']==old_app['direct_conversation_count']==1
    assert all(e in app['evidence'] for e in old_app['evidence'])
    group=next(n for n in new['entities'] if n['id']==old_group['id'])
    assert group['parent_id']==app['id'] and group['position']==old_group['position']
    assert group['source_scopes']==old_group['source_scopes']
    assert node_at(new,mobile)['kind']=='planet'
    planets=space.view(cache,action='list',kind='planets')['entities']
    assert app['id'] not in {n['id'] for n in planets}
    explored=space.view(cache,action='explore',within=experiment['id'])
    assert app['id'] in {n['id'] for n in explored['entities']}
    shown=space.view(cache,action='show',within=app['id'])
    assert [n['label'] for n in shown['breadcrumbs']]==['Your galaxy','Lyra','observing-suite','trial','Calibration editor']
    assert next(n for n in new['entities'] if n['kind']=='galaxy')['conversation_count']==3
    again=space.refresh(API,conn,cache,source_cache=sources)
    assert node_at(again,editor)['id']==app['id'] and node_at(again,editor)['position']==app['position']
    assert all(edge['source']==next(n for n in again['entities'] if n['id']==edge['target'])['parent_id']
               for edge in again['edges'] if edge['relation']=='contains')
    conn.close()


@pytest.mark.parametrize('workspace',[False,True])
def test_independent_nested_git_application_remains_product(tmp_path,workspace):
    root,mobile,lab,editor,sources,conn=fixture(tmp_path,workspace=workspace,nested_git=True)
    data=space.refresh(API,conn,tmp_path/'space.json',source_cache=sources)
    app=node_at(data,editor)
    assert app['kind']=='planet' and not app.get('form')
    assert next(n for n in data['entities'] if n['id']==app['parent_id'])['kind']=='system'
    assert app['source_scopes'] and any(e.get('basis')=='Git origin' for e in app['evidence'])
    conn.close()


@pytest.mark.parametrize('change',['missing','symlink'])
def test_unavailable_application_retains_verified_lab_placement_without_following_link(tmp_path,monkeypatch,change):
    root,mobile,lab,editor,sources,conn=fixture(tmp_path)
    cache=tmp_path/'space.json'
    before=space.refresh(API,conn,cache,source_cache=sources);app=node_at(before,editor)
    editor.rename(tmp_path/'parked-editor')
    if change=='symlink':
        outside=git(tmp_path/'foreign-product')
        editor.symlink_to(outside,target_is_directory=True)
    original=space._repository
    def checked(path):
        assert change!='symlink' or path!=editor, 'Unavailable application must not be resolved through a link'
        return original(path)
    # Existing inventory resolves its indexed cwd at intake; isolate the source-only
    # continuity path so no live indexed symlink redirection enters this test.
    monkeypatch.setattr(space,'_repository',checked)
    after=space.refresh(API,None,cache,source_cache=sources)
    same=node_at(after,editor)
    assert same['id']==app['id'] and same['kind']=='district' and same['form']=='application'
    assert same['position']==app['position'] and same['parent_id']==app['parent_id']
    assert not same['locations'][0]['available']
    assert any(e.get('type')=='experiment_application' and e['basis']=='previous_verified_containment' for e in same['evidence'])
    conn.close()


@pytest.mark.skipif(not shutil.which('starforge'),reason='Installed native Starforge required')
def test_public_cli_harvest_places_lab_application_and_searches_only_its_native_files(navcom,tmp_path,monkeypatch):
    from test_atlas import add
    monkeypatch.setattr(navcom,'INDEX_READ_ONLY',False)
    root=git(tmp_path/'clients'/'Polaris'/'survey-suite')
    package(root,name='survey-suite')
    editor=package(root/'LABS'/'calibration-trial'/'editor',name='Prism calibration',scripts={'dev':'do not execute'})
    mobile=package(root/'apps'/'mobile',name='Prism mobile',scripts={'start':'do not execute'})
    code='\n'.join(['"""Marmot optical calibration and instrument measurements."""',
        'def marmot_calibration(sensor, instrument, measurement, policy):']+
        [f'    reading_{i}=sensor+instrument+measurement+policy+{i}' for i in range(25)]+['    return reading_24',''])
    for target in (editor,mobile):
        (target/'README.md').write_text('# '+target.name+'\nMarmot calibration context in this application.\n')
        (target/'calibration.py').write_text(code)
    index=tmp_path/'index.sqlite';conn=navcom.open_index(index)
    add(navcom,conn,tmp_path/'editor.jsonl','Marmot lab choices','marmot calibration',str(editor))
    add(navcom,conn,tmp_path/'mobile.jsonl','Marmot mobile choices','marmot mobile',str(mobile))
    conn.close()
    sources=tmp_path/'sources';chart=tmp_path/'space.json'
    def call(*args):
        result=subprocess.run([sys.executable,str(ROOT/'navcom.py'),*map(str,args),'--json'],
            capture_output=True,text=True,timeout=60,env=os.environ.copy())
        assert result.returncode==0,result.stderr
        return json.loads(result.stdout)
    common=['--space-cache',chart,'--source-cache',sources,'--index',index]
    harvest=call('sources','discover','--harvest','--index',index,'--cache',sources)
    assert harvest['analyzed_sources']==1
    call('atlas','refresh','--space',*common)
    data=json.loads(chart.read_text());app=node_at(data,editor);experiment=node_at(data,editor.parent)
    assert app['kind']=='district' and app['form']=='application'
    assert any(e['type']=='native_application' and e['entry_points'] for e in app['evidence'])
    listed=call('atlas','list','planets',*common,'--limit',100)
    assert app['id'] not in {n['id'] for n in listed['nodes']}
    assert node_at(data,mobile)['id'] in {n['id'] for n in listed['nodes']}
    explored=call('atlas','explore',experiment['id'],*common)
    assert app['id'] in {n['id'] for n in explored['nodes']}
    found=call('atlas','search','marmot','--within',app['id'],'--evidence',*common)
    assert not found['evidence']['errors']
    assert any(s['concept_hits'] for s in found['evidence']['sources'])
    assert any(s['text_hits'] for s in found['evidence']['sources'])
    for source in found['evidence']['sources']:
        assert all(Path(hit['source_path']).is_relative_to(editor) for hit in source['concept_hits']+source['text_hits'])
    assert len(found['evidence']['conversations'])==1
    assert found['evidence']['conversations'][0]['project']==str(editor)
    call('atlas','refresh','--space',*common)
    repeated=call('atlas','show',app['id'],*common)['center']
    assert repeated['position']==app['position'] and repeated['source_scopes']==app['source_scopes']
