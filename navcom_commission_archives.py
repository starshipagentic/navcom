"""Bounded local archive observation anchored in existing commission records.

The sibling ``archive`` path is the recorded commission layout, not an archive
path asserted by capture/receipt.json. Native descriptor binding is a stat check,
never an integrity, restored application, or captain readiness certificate.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import socket
import stat
import subprocess
import sys
import time

from navcom_ship_context import _read
from navcom_ship_inspection import _safe_path, _tool_identity, _write, _writer, commission_tools
from navcom_source_reader import _open


VERSION = 1
RECORD_BYTES = 64 * 1024
DESCRIPTOR_BYTES = 4096
TOTAL_BYTES = 4 * 1024 * 1024
CACHE_BYTES = 2 * 1024 * 1024


def _hash(value):
    return hashlib.sha256(value).hexdigest()


def _json(path, limit):
    raw = _read(path.parent, path.name, limit)
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError('Expected metadata object')
    return data, raw


def _stat(path, *, directory=False):
    """Get regular metadata stats without following any component symlink."""
    anchor = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        with _open(anchor, path.relative_to('/'), directory=directory) as fd:
            value = os.fstat(fd)
            return dict(size=value.st_size, mtime_ns=value.st_mtime_ns,
                        ctime_ns=value.st_ctime_ns, inode=value.st_ino, device=value.st_dev)
    finally:
        os.close(anchor)


def _observe_batch(candidates, tool_root, seconds):
    # Independently selected installed code only. Pass bounded descriptors so the
    # native inspector cannot fall back to reading a large carried manifest.
    script = """import json,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import fleet
assert Path(fleet.__file__).resolve()==(Path(sys.argv[1])/'fleet.py').resolve()
out=[]
for item in json.load(sys.stdin):
 root=Path(item['root'])
 try:
  row=fleet.inspect_ship(root,descriptor_index={str(root):item['descriptor']})
  out.append({k:row.get(k) for k in ['path','state','repositories','descriptor_binding','capture_evidence']})
 except Exception as error:
  out.append({'path':str(root),'error':type(error).__name__})
print(json.dumps(out))
"""
    payload = [{'root':str(c['root']), 'descriptor':c['descriptor']} for c in candidates]
    result = subprocess.run([sys.executable, '-I', '-B', '-c', script, str(tool_root)],
                            input=json.dumps(payload), capture_output=True, text=True, timeout=seconds)
    if result.returncode or len(result.stdout.encode()) > 128 * 1024:
        raise ValueError('Native archive metadata observation failed')
    rows = json.loads(result.stdout)
    if not isinstance(rows, list) or len(rows) != len(candidates):
        raise ValueError('Native archive observation count did not match')
    expected = {str(c['root']) for c in candidates}
    if {r.get('path') for r in rows if isinstance(r, dict)} != expected:
        raise ValueError('Native archive observation location did not match')
    return rows


def _public_observation(row):
    if row.get('state') not in {'recorded-descriptor', 'descriptor-invalid', 'descriptor-stale', 'descriptor-missing-manifest'}:
        raise ValueError('Native archive descriptor state unavailable')
    if row.get('descriptor_binding') not in {'stat-match-only', 'invalid', 'stale', 'missing-manifest'}:
        raise ValueError('Native archive descriptor binding unavailable')
    capture = row.get('capture_evidence')
    if capture not in {'seal-present-unverified','no-seal-file','unsafe-metadata','unsafe-seal-path','unreadable-seal-path'}:
        raise ValueError('Native archive capture metadata unavailable')
    count = row.get('repositories')
    return dict(state=row['state'], descriptor_binding=row['descriptor_binding'],
                capture_evidence=capture,
                repositories=count if type(count) is int and 0 <= count <= 100000 else None)


def discover(entities, snapshot_path, *, cache_path=None, tool_root=None, limit=128, seconds=5):
    """Return separate archive entities and coverage; never mutate fleet rows.

    No traversal: each exact existing bridge commission RESULT.json reference
    permits three sibling metadata reads and only native no-live inspection.
    All remote working paths are retained as data and never probed.
    """
    if type(limit) is not int or not 1 <= limit <= 256 or not 0.1 <= seconds <= 15:
        raise ValueError('Archive discovery requires limit 1–256 and seconds 0.1–15.')
    started = time.monotonic()
    deadline = started + seconds
    snapshot = Path(snapshot_path).expanduser().absolute()
    hostname = socket.gethostname()
    coverage = dict(available=False, complete=True, anchors=0, candidates=0, archives=0,
                    cached=0, native_observations=0, native_processes=0, metadata_bytes=0,
                    omitted=0, gaps=[], limit=limit, seconds=seconds,
                    basis='Exact bridge commission evidence and sibling archive layout; local receipt origin required.',
                    live_checks=False, integrity_verified=False)
    if snapshot.parent.name != 'bridge':
        coverage['reason'] = 'No bridge-relative commission layout is declared.'
        return dict(entities=[], coverage=coverage)
    project = snapshot.parent.parent
    commission = project / '.starship' / 'commission'
    selected_tool = Path(tool_root or commission_tools()).expanduser()
    cache = Path(cache_path or os.environ.get('NAVCOM_FLEET_CACHE', '~/.cache/navcom/fleet-archives.json')).expanduser().absolute()
    # Caller-configured cache folders can use the OS /tmp alias; its leaf still
    # must be an ordinary file and is never followed through a symlink.
    cache = cache.parent.resolve()/cache.name
    candidates = []
    seen = set()
    rows = [e for e in entities if e.get('kind') == 'ship' and e.get('form') != 'archive']
    def gap(record, reason):
        coverage['complete'] = False
        coverage['gaps'].append(dict(ship_id=record.get('id'), record_id=record.get('record_id'), reason=reason))
    def read_metadata(path, bound):
        remaining=TOTAL_BYTES-coverage['metadata_bytes']
        if remaining<=0:raise ValueError('Metadata byte budget reached')
        raw=_read(path.parent,path.name,min(bound,remaining))
        coverage['metadata_bytes']+=len(raw)
        data=json.loads(raw)
        if not isinstance(data,dict):raise ValueError('Expected metadata object')
        return data,raw
    for index, record in enumerate(rows):
        if coverage['anchors'] >= limit or time.monotonic() >= deadline or coverage['metadata_bytes']>=TOTAL_BYTES:
            coverage['omitted'] += len(rows)-index
            coverage['complete'] = False
            break
        # Evidence must name one exact, immediate commission record. Do not use
        # row IDs as arbitrary paths and do not traverse arbitrary JSON links.
        references=[]
        for evidence in record.get('evidence', [])[:8]:
            value=evidence.get('path') if isinstance(evidence,dict) else None
            if not isinstance(value,str):continue
            try:relative=Path(value).relative_to(commission)
            except ValueError:continue
            if len(relative.parts)==2 and relative.name=='RESULT.json' and relative.parts[0] not in {'.','..'}:
                references.append(commission/relative)
        references=list(dict.fromkeys(references))
        if not references:continue
        if len(references)!=1:
            gap(record,'Multiple commission anchors are declared; archive association is ambiguous.');continue
        evidence=references[0]
        if evidence in seen:continue
        seen.add(evidence);coverage['anchors']+=1
        root=evidence.parent/'archive'
        # An evidence root overlapping a remote physical namespace is not an
        # independent local metadata copy and must never be traversed.
        physical=record.get('physical') or {}
        remote=physical.get('path')
        if physical.get('host','') not in {'localhost','127.0.0.1','::1',hostname} and isinstance(remote,str) and remote.startswith('/'):
            remote_path=Path(remote)
            if root.is_relative_to(remote_path) or project.is_relative_to(remote_path):
                gap(record,'Commission evidence overlaps the unobserved remote physical location.');continue
        try:
            if not _safe_path(root):raise ValueError('Linked or private archive metadata path')
            # Missing siblings are ordinary incomplete commission records, not
            # a reason to read any alternative directory or recorded command.
            _stat(root,directory=True)
            coverage['candidates']+=1
            result,result_raw=read_metadata(evidence,RECORD_BYTES)
            receipt_path=evidence.parent/'capture/receipt.json'
            receipt,receipt_raw=read_metadata(receipt_path,RECORD_BYTES)
            origin=receipt.get('origin')
            recorded_host=origin.get('host') if isinstance(origin,dict) else None
            if not isinstance(recorded_host,str) or recorded_host.casefold().rstrip('.')!=hostname.casefold().rstrip('.'):
                gap(record,'Capture origin is missing or belongs to another host; this archive was not promoted.');continue
            descriptor_path=root/'.starship/descriptor.json'
            descriptor,descriptor_raw=read_metadata(descriptor_path,DESCRIPTOR_BYTES)
            if not descriptor:raise ValueError('Archive descriptor is empty')
            metadata={'.':_stat(root,directory=True), '.starship':_stat(root/'.starship',directory=True)}
            for relative in ['.starship/descriptor.json','.starship/manifest.json','.starship/seal.json','.starship/HANDOVER.md']:
                try:metadata[relative]=_stat(root/relative)
                except (OSError,ValueError):metadata[relative]=None
            # Reject links/FIFOs for the exact metadata native inspect touches.
            for relative in ['.starship/descriptor.json','.starship/manifest.json','.starship/HANDOVER.md']:
                item=root/relative
                if not _safe_path(item) or (item.exists() and not stat.S_ISREG(item.lstat().st_mode)):
                    raise ValueError('Archive metadata requires regular no-follow files')
            signature=dict(version=VERSION,related_ship_id=record['id'],host=hostname,root=str(root),
                           anchor=_hash(result_raw),receipt=_hash(receipt_raw),descriptor=_hash(descriptor_raw),metadata=metadata)
            candidates.append(dict(root=root,record=record,descriptor=descriptor,signature=signature,
                                   evidence=evidence,receipt=receipt_path,origin=recorded_host,
                                   capture_state=receipt.get('state') if receipt.get('state') in {'passed','failed','running','blocked','interrupted'} else 'unknown'))
        except (OSError,ValueError):
            gap(record,'Archive sibling or required public commission/descriptor metadata is unavailable or unsafe.')
    if not candidates:
        return dict(entities=[],coverage=coverage)
    try:tool=_tool_identity(selected_tool)
    except (OSError,ValueError):
        coverage['complete']=False;coverage['gaps'].append(dict(reason='Installed native Starship observer unavailable.'))
        return dict(entities=[],coverage=coverage)
    try:saved,_=_json(cache,CACHE_BYTES)
    except (OSError,ValueError):saved={}
    saved=saved.get('records',{}) if isinstance(saved.get('records'),dict) else {}
    ready={};pending=[]
    for candidate in candidates:
        candidate['signature']['tool']=tool
        key=str(candidate['root']);old=saved.get(key,{})
        if isinstance(old,dict) and old.get('signature')==candidate['signature']:
            try:
                ready[key]=dict(observation=_public_observation(old['observation']),observed_at=old['observed_at'])
                coverage['cached']+=1;continue
            except (KeyError,TypeError,ValueError):pass
        pending.append(candidate)
    if pending:
        remaining=deadline-time.monotonic()
        if remaining<=0:
            coverage['complete']=False;coverage['omitted']+=len(pending)
        else:
            try:
                coverage['native_processes']=1
                observations=_observe_batch(pending,selected_tool,remaining)
                now=time.time()
                for candidate,row in zip(pending,observations):
                    key=str(candidate['root'])
                    if row.get('path')!=key:raise ValueError('Native observation order changed')
                    try:observation=_public_observation(row)
                    except ValueError:
                        gap(candidate['record'],'Native observer could not bind this archive descriptor.');continue
                    ready[key]=dict(observation=observation,observed_at=now)
                    coverage['native_observations']+=1
            except (OSError,ValueError,subprocess.SubprocessError):
                coverage['complete']=False;coverage['gaps'].append(dict(reason='Bounded native archive metadata batch unavailable.'))
    output=[];next_cache={}
    from navcom_fleet import _key
    for candidate in candidates:
        root=candidate['root'];value=ready.get(str(root))
        if value is None:continue
        observation=value['observation'];record=candidate['record'];observed_at=value['observed_at']
        next_cache[str(root)]=dict(signature=candidate['signature'],**value)
        archive_id=_key('ship',record['id'],'archive',hostname,str(root))
        output.append(dict(id=archive_id,kind='ship',form='archive',
            label=record.get('label',record['id'])+' · archive',parent_id=None,related_ship_id=record['id'],
            record_id=record.get('record_id'),source_roots=list(record.get('source_roots',[])),
            description='Local commission archive; separate from its recorded working ship.',
            physical=dict(host=hostname,path=str(root),availability='present',observed_at=observed_at,
                          metadata_state=observation['state'],repositories=observation['repositories']),
            readiness=dict(status='unknown',basis='metadata-only',message='Restoration, application checks and captain takeover have not been performed.'),
            integrity=dict(status='not checked',descriptor_binding=observation['descriptor_binding'],capture_evidence=observation['capture_evidence']),
            provenance=dict(snapshot=str(snapshot),commission_evidence=str(candidate['evidence']),capture_receipt=str(candidate['receipt']),
                            source_host=candidate['origin'],recorded_capture_state=candidate['capture_state'],observed_at=observed_at,
                            basis='Sibling archive in the exact referenced commission layout; native descriptor observation.',tool=tool),
            evidence=[dict(type='commission_archive_sibling',path=str(candidate['evidence']),archive=str(root),
                           basis='Sibling layout association; capture receipt does not assert this archive path.')],
            gaps=['Descriptor binding is stat-only; archive integrity and working-copy equivalence are unverified.',
                  'Archive reading does not resume the working ship or its captain.']))
    if next_cache and next_cache!=saved:
        try:
            if not _safe_path(cache):raise ValueError('Unsafe archive cache')
            with _writer(cache):_write(cache,dict(schema_version=VERSION,records=next_cache))
        except (OSError,ValueError):
            coverage['gaps'].append(dict(reason='Archive metadata cache could not be saved; observation remains usable.'))
    coverage.update(available=bool(output),archives=len(output),elapsed_seconds=round(time.monotonic()-started,3))
    return dict(entities=output,coverage=coverage)
