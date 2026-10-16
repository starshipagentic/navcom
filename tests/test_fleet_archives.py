"""Automatic archive destinations use native metadata, not copied catalogs."""
import hashlib
import json
from pathlib import Path
import socket

import pytest

import navcom_commission_archives as archives
import navcom_fleet


TOOL = Path.home()/'.codex/skills/ship-commission/scripts'


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))
    return path


def fixture(tmp_path, names=('orchard',)):
    project=tmp_path/'starship'
    rows=[]
    for name in names:
        record=project/'.starship/commission'/name
        root=record/'archive'
        write(record/'RESULT.json',dict(state='recorded',target=name+'/working',private='DO_NOT_EXPOSE'))
        write(record/'capture/receipt.json',dict(state='passed',origin={'host':socket.gethostname()},private='RECEIPT_SECRET'))
        manifest=write(root/'.starship/manifest.json',{'repositories':[{'name':'orchard'}]})
        raw=manifest.read_bytes();metadata=manifest.stat()
        write(root/'.starship/descriptor.json',dict(schema=1,repository_count=1,materialized_count=1,
            manifest_sha256=hashlib.sha256(raw).hexdigest(),manifest_size=len(raw),
            manifest_mtime_ns=metadata.st_mtime_ns,generated_at=1.0))
        write(root/'.starship/seal.json',{})
        rows.append(dict(id=name,name=name.title(),sources=['/recorded/source/'+name],destination=name+'/working',
                         evidence='.starship/commission/'+name+'/RESULT.json'))
    snapshot=write(project/'bridge/data.json',dict(ships=rows,base='/remote/fleet',generated='2026-10-16'))
    config=write(project/'fleet.json',dict(ssh_host='remote.example',remote_root='/remote/fleet'))
    return project,snapshot,config,tmp_path/'cache/archives.json'


def observe(snapshot,config,cache,**kwargs):
    return navcom_fleet.read_fleet(snapshot,config,archive_cache=cache,**kwargs)


def fake_native(monkeypatch):
    calls=[]
    monkeypatch.setattr(archives,'_tool_identity',lambda root:dict(root=str(root),files={'fleet.py':'one'}))
    def native(candidates,tool,seconds):
        calls.append([str(c['root']) for c in candidates])
        return [dict(path=str(c['root']),state='recorded-descriptor',descriptor_binding='stat-match-only',
                     capture_evidence='seal-present-unverified',repositories=1) for c in candidates]
    monkeypatch.setattr(archives,'_observe_batch',native)
    return calls


def test_native_archive_is_separate_cached_ship_with_unknown_readiness(tmp_path):
    if not (TOOL/'fleet.py').is_file():pytest.skip('Installed native Starship observer required')
    project,snapshot,config,cache=fixture(tmp_path)
    first=observe(snapshot,config,cache)
    remote,archive=[r for r in first['entities'] if r['kind']=='ship']
    assert remote['physical']['host']=='remote.example'
    assert remote['physical']['path']=='/remote/fleet/orchard/working'
    assert archive['id']!=remote['id'] and archive['related_ship_id']==remote['id']
    assert archive['form']=='archive' and archive['art_role']=='archive'
    assert archive['parent_id'] is None
    assert archive['physical']['host']==socket.gethostname()
    assert archive['physical']['path']==str(project/'.starship/commission/orchard/archive')
    assert archive['physical']['metadata_state']=='recorded-descriptor'
    assert archive['readiness']['status']=='unknown'
    assert archive['integrity']==dict(status='not checked',descriptor_binding='stat-match-only',capture_evidence='seal-present-unverified')
    assert first['coverage']['archives']['native_processes']==1
    assert first['coverage']['ships']==2 and first['coverage']['recorded_ships']==1
    text=json.dumps(first)
    assert 'DO_NOT_EXPOSE' not in text and 'RECEIPT_SECRET' not in text
    again=observe(snapshot,config,cache)
    assert again['coverage']['archives']['cached']==1
    assert again['coverage']['archives']['native_processes']==0
    assert again['entities']==first['entities']


def test_one_batch_and_metadata_tool_changes_invalidate_cache(tmp_path,monkeypatch):
    project,snapshot,config,cache=fixture(tmp_path,('orchard','cedar'))
    calls=fake_native(monkeypatch)
    first=observe(snapshot,config,cache)
    assert len(calls)==1 and len(calls[0])==2
    observe(snapshot,config,cache);assert len(calls)==1
    descriptor=project/'.starship/commission/orchard/archive/.starship/descriptor.json'
    data=json.loads(descriptor.read_text());data['generated_at']=2.0;write(descriptor,data)
    changed=observe(snapshot,config,cache)
    assert len(calls)==2 and len(calls[-1])==1
    assert changed['coverage']['archives']['cached']==1
    monkeypatch.setattr(archives,'_tool_identity',lambda root:dict(root=str(root),files={'fleet.py':'two'}))
    observe(snapshot,config,cache)
    assert len(calls)==3 and len(calls[-1])==2
    old_ids=[r['id'] for r in first['entities']]
    assert [r['id'] for r in changed['entities']]==old_ids


@pytest.mark.parametrize('mode',['missing','foreign','unknown'])
def test_missing_or_nonlocal_capture_origin_is_visible_gap(tmp_path,monkeypatch,mode):
    project,snapshot,config,cache=fixture(tmp_path)
    calls=fake_native(monkeypatch)
    receipt=project/'.starship/commission/orchard/capture/receipt.json'
    if mode=='missing':receipt.unlink()
    else:write(receipt,dict(state='passed',origin={'host':'other.example'} if mode=='foreign' else {}))
    data=observe(snapshot,config,cache)
    assert not calls
    assert not [r for r in data['entities'] if r.get('form')=='archive']
    coverage=data['coverage']['archives']
    assert coverage['candidates']==1 and coverage['complete'] is False and coverage['gaps']
    assert data['entities'][-1]['physical']['host']=='remote.example'


@pytest.mark.parametrize('relative',['archive','archive/.starship','archive/.starship/descriptor.json','capture/receipt.json'])
def test_linked_archive_metadata_never_gets_inspected(tmp_path,monkeypatch,relative):
    project,snapshot,config,cache=fixture(tmp_path)
    calls=fake_native(monkeypatch)
    path=project/'.starship/commission/orchard'/relative
    original=path.with_name(path.name+'-original');path.rename(original);path.symlink_to(original,target_is_directory=original.is_dir())
    data=observe(snapshot,config,cache)
    assert calls==[]
    assert not [r for r in data['entities'] if r.get('form')=='archive']
    assert data['coverage']['archives']['gaps']


def test_native_stale_descriptor_is_not_ready_or_integrity_pass(tmp_path):
    if not (TOOL/'fleet.py').is_file():pytest.skip('Installed native Starship observer required')
    project,snapshot,config,cache=fixture(tmp_path)
    manifest=project/'.starship/commission/orchard/archive/.starship/manifest.json'
    manifest.write_text('{"repositories":[],"changed":true}')
    data=observe(snapshot,config,cache)
    archive=next(r for r in data['entities'] if r.get('form')=='archive')
    assert archive['integrity']['descriptor_binding']=='stale'
    assert archive['integrity']['status']=='not checked'
    assert archive['readiness']['status']=='unknown'


def test_missing_receipt_does_not_borrow_an_unrelated_history_ship(tmp_path,monkeypatch):
    project,snapshot,config,cache=fixture(tmp_path)
    calls=fake_native(monkeypatch)
    record=project/'.starship/commission/orchard'
    (record/'archive').rename(record/'history')
    data=observe(snapshot,config,cache)
    assert not calls
    assert not [r for r in data['entities'] if r.get('form')=='archive']


def test_anchor_limit_and_timeout_keep_remote_rows_with_partial_coverage(tmp_path,monkeypatch):
    project,snapshot,config,cache=fixture(tmp_path,('orchard','cedar','quartz'))
    calls=fake_native(monkeypatch)
    data=observe(snapshot,config,cache,archive_limit=1)
    assert len(calls[0])==1
    assert len([r for r in data['entities'] if r.get('form')!='archive' and r['kind']=='ship'])==3
    assert data['coverage']['archives']['omitted']==2
    assert data['coverage']['archives']['complete'] is False
    import subprocess
    monkeypatch.setattr(archives,'_observe_batch',lambda *_:(_ for _ in ()).throw(subprocess.TimeoutExpired('native',1)))
    data=observe(snapshot,config,tmp_path/'timeout-cache.json')
    assert data['coverage']['archives']['complete'] is False
    assert not [r for r in data['entities'] if r.get('form')=='archive']


def test_evidence_inside_remote_namespace_is_not_opened_locally(tmp_path,monkeypatch):
    project,snapshot,config,cache=fixture(tmp_path)
    config_data=json.loads(config.read_text());config_data['remote_root']=str(project);write(config,config_data)
    rows=json.loads(snapshot.read_text());rows['ships'][0]['destination']=str(project);write(snapshot,rows)
    fake_native(monkeypatch)
    monkeypatch.setattr(archives,'_stat',lambda *_args,**_kw:pytest.fail('remote namespace must not be probed'))
    data=observe(snapshot,config,cache)
    assert data['coverage']['archives']['gaps'][0]['reason'].startswith('Commission evidence overlaps')


def test_oversized_descriptor_and_fifo_metadata_remain_bounded(tmp_path,monkeypatch):
    import os
    project,snapshot,config,cache=fixture(tmp_path,('orchard','cedar'))
    calls=fake_native(monkeypatch)
    descriptor=project/'.starship/commission/orchard/archive/.starship/descriptor.json'
    descriptor.write_bytes(b' '*5000)
    receipt=project/'.starship/commission/cedar/capture/receipt.json';receipt.unlink();os.mkfifo(receipt)
    data=observe(snapshot,config,cache)
    assert not calls
    assert data['coverage']['archives']['candidates']==2
    assert len(data['coverage']['archives']['gaps'])==2


def test_rejected_host_metadata_also_consumes_byte_budget(tmp_path,monkeypatch):
    project,snapshot,config,cache=fixture(tmp_path,('orchard','cedar','quartz'))
    calls=fake_native(monkeypatch)
    for name in ('orchard','cedar','quartz'):
        write(project/'.starship/commission'/name/'capture/receipt.json',dict(origin={'host':'elsewhere'}))
    first_size=(project/'.starship/commission/orchard/RESULT.json').stat().st_size
    first_size+=(project/'.starship/commission/orchard/capture/receipt.json').stat().st_size
    monkeypatch.setattr(archives,'TOTAL_BYTES',first_size)
    data=observe(snapshot,config,cache)
    assert data['coverage']['archives']['metadata_bytes']==first_size
    assert data['coverage']['archives']['omitted']==2
    assert data['coverage']['archives']['anchors']==1
    assert not calls
