"""Landing at a place exposes only its retained, pinned source files."""
import json
from pathlib import Path
import shlex
import subprocess
import sys

import pytest

import navcom_place_files as service
from navcom_source_reader import read_source
from test_source_reader import publish


@pytest.fixture
def landing(tmp_path):
    root=tmp_path/'deleted-original'
    cache=tmp_path/'sources'
    artifact,state=publish(cache,root,{'engine/jobs.py':b'old job code\n','engine/config.py':b'configuration\n',
                                      'docs/README.md':b'# retained docs\n','other/private.py':b'unrelated\n'})
    district=dict(id='district:jobs',label='jobs',kind='district',parent_id='planet:one',
                  source_scopes=[dict(source_id='quartz',paths=['engine/jobs.py'])])
    planet=dict(id='planet:one',label='One',kind='planet',parent_id='galaxy:owner',
                source_scopes=[dict(source_id='quartz',paths=['engine','docs'])])
    space=tmp_path/'space.json'
    nodes=[dict(id='galaxy:owner',label='Galaxy',kind='galaxy',parent_id=None),planet,district]
    for n in nodes: n.update(locations=[],evidence=[],examples=[])
    space.write_text(json.dumps(dict(schema_version=1,published=123,entities=nodes,edges=[],coverage={})))
    return space,cache,artifact,state


def test_exact_district_and_product_scope_have_readable_snapshot_refs(landing):
    space,cache,artifact,state=landing
    district=service.files(space,cache,'district:jobs')
    assert [f['relative_path'] for f in district['files']]==['engine/jobs.py']
    ref=district['files'][0]['source_ref']
    read=read_source(ref['source_id'],ref['relative_path'],cache_path=cache,snapshot=ref['snapshot'],published=ref['published'])
    assert read['lines'][0]['text']=='old job code' and not read['provenance']['current_file_read']
    product=service.files(space,cache,'planet:one')
    assert product['total']==3 and product['coverage']['harvest_invocations']==0
    assert all('private' not in f['relative_path'] for f in product['files'])


def test_path_filter_pages_and_unrelated_registry_changes(landing):
    space,cache,artifact,state=landing
    first=service.files(space,cache,'planet:one',query='engine',limit=1)
    assert first['total']==2 and first['more'] and first['next_command']
    state['published']+=1
    (cache/'current.json').write_text(json.dumps(state))
    second=service.files(space,cache,'planet:one',query='engine',limit=1,offset=1,generation=first['generation'])
    assert not second['more'] and second['files'][0]['relative_path']=='engine/jobs.py'
    publish(cache,Path(state['sources'][0]['root']),{'engine/jobs.py':b'new job\n'})
    with pytest.raises(ValueError,match='inventory changed'):
        service.files(space,cache,'planet:one',offset=1,generation=first['generation'])


def test_missing_invalid_and_linked_artifacts_never_expand_scope(landing,tmp_path):
    space,cache,artifact,state=landing
    (artifact/'source/engine/jobs.py').unlink()
    (artifact/'source/engine/jobs.py').symlink_to('/etc/passwd')
    result=service.files(space,cache,'district:jobs')
    assert not result['files'] and result['coverage']['omitted_entries']==1
    assert not result['coverage']['complete']
    state['sources'][0]['signature']='f'*64
    (cache/'current.json').write_text(json.dumps(state))
    invalid=service.files(space,cache,'planet:one')
    assert not invalid['files'] and invalid['errors']
    with pytest.raises(ValueError,match='product, experiment or district'):
        service.files(space,cache,'galaxy:owner')


def test_inventory_budget_discloses_partial_results(landing,monkeypatch):
    monkeypatch.setattr(service,'MAX_FILES',1)
    result=service.files(*landing[:2],'planet:one')
    assert result['coverage']['limited'] and not result['coverage']['complete']
    assert result['total']==1


def test_missing_saved_file_is_incomplete_but_an_existing_empty_directory_is_complete(landing):
    space,cache,artifact,_=landing
    (artifact/'source/engine/jobs.py').unlink()
    missing=service.files(space,cache,'district:jobs')
    assert not missing['files'] and not missing['coverage']['complete']
    assert missing['errors'][0]['path']=='engine/jobs.py'
    assert 'missing or unreadable' in missing['errors'][0]['message']
    (artifact/'source/engine/empty').mkdir()
    chart=json.loads(space.read_text())
    chart['entities'][-1]['source_scopes'][0]['paths']=['engine/empty']
    space.write_text(json.dumps(chart))
    empty=service.files(space,cache,'district:jobs')
    assert empty['files']==[] and not empty['errors'] and empty['coverage']['complete']


def test_limited_inventory_never_offers_or_accepts_offset_paging(landing,monkeypatch):
    monkeypatch.setattr(service,'MAX_FILES',2)
    first=service.files(*landing[:2],'planet:one',limit=1)
    assert first['coverage']['limited'] and first['total']==2
    assert not first['more'] and first['next_command'] is None
    assert 'cannot be paged' in first['coverage']['continuation']
    for generation in ('',first['generation']):
        with pytest.raises(ValueError,match='later pages are unstable'):
            service.files(*landing[:2],'planet:one',limit=1,offset=1,generation=generation)


def test_directory_entry_budget_bounds_fanout_before_sorting(landing,monkeypatch):
    monkeypatch.setattr(service,'MAX_ENTRIES',1)
    monkeypatch.setattr(service.os,'listdir',lambda *_:pytest.fail('Unbounded directory list was materialized'))
    result=service.files(*landing[:2],'planet:one')
    assert result['coverage']['inspected_entries']==1
    assert result['coverage']['limited'] and not result['coverage']['complete']
    assert not result['more']
    with pytest.raises(ValueError,match='later pages are unstable'):
        service.files(*landing[:2],'planet:one',offset=1)


def test_swapped_leaf_is_not_counted_as_a_retained_file(landing,monkeypatch,tmp_path):
    space,cache,artifact,_=landing
    target=tmp_path/'outside.txt';target.write_text('not source evidence')
    original=service.os.stat
    changed=[]
    def swapped(path,*args,**kwargs):
        metadata=original(path,*args,**kwargs)
        if path=='jobs.py' and not changed:
            assert kwargs.get('dir_fd') is not None and kwargs.get('follow_symlinks') is False
            leaf=artifact/'source/engine/jobs.py'
            leaf.unlink();leaf.symlink_to(target);changed.append(True)
        return metadata
    monkeypatch.setattr(service.os,'stat',swapped)
    result=service.files(space,cache,'district:jobs')
    assert changed and result['files']==[]
    assert result['coverage']['inventoried_files']==0
    assert result['coverage']['omitted_entries']==1 and not result['coverage']['complete']
    assert result['errors'][0]['path']=='engine/jobs.py'
    assert target.read_text()=='not source evidence'


def test_public_cli_api_and_returned_read_command_match(landing,navcom,monkeypatch):
    from navcom_web import WebApp
    space,cache,artifact,state=landing
    monkeypatch.setenv('NAVCOM_SPACE_CACHE',str(space))
    monkeypatch.setenv('NAVCOM_SOURCES_CACHE',str(cache))
    index=space.parent/'empty.sqlite'
    conn=navcom.open_index(index)
    try:
        web=WebApp(navcom,index).get(conn,'/api/space/files',{'within':['district:jobs']})
    finally:conn.close()
    prefix=[sys.executable,str(Path(__file__).resolve().parents[1]/'navcom.py')]
    output=subprocess.run(prefix+['atlas','files','district:jobs','--index',str(index),'--json'],capture_output=True,text=True,check=True)
    cli=json.loads(output.stdout)
    assert cli['files']==web['files']
    command=shlex.split(cli['files'][0]['read_command'])
    result=json.loads(subprocess.run(prefix+command[1:]+['--json'],capture_output=True,text=True,check=True).stdout)
    assert result['lines'][0]['text']=='old job code'
