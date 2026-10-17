"""Bounded federation of the installed native reader over exact carried ships.

The caller supplies already-scoped ship entities. This module never expands a
place, substitutes a stored copy, reads host conversations, or starts a captain.
It caches native results (including zero hits); matching remains Starship's.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import uuid

import navcom_ship_context as context
from navcom_ship_inspection import _text
from navcom_space import kill_group


VERSION = 1
MAX_ENTITIES = 256
METADATA_BYTES = 8 * 1024 * 1024
METADATA_RECORDS = 4096
CACHE_BYTES = 4 * 1024 * 1024
POLICY = ('Only the exact allowed ships are searched, using the installed Starship carried-history reader. '
          'Recorded dialogue is not current host history; this does not board, restore or resume a ship.')


def _hash(value):
    return hashlib.sha256(value if isinstance(value, bytes) else json.dumps(
        value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _mini(entity):
    physical = entity.get('physical') if isinstance(entity.get('physical'), dict) else {}
    return dict(id=entity['id'], label=_text(entity.get('label'), 200), kind='ship',
                form=_text(entity.get('form'), 100),
                physical={key: physical.get(key) for key in ('host', 'path')})


def _local(entity):
    host = entity['physical'].get('host')
    return isinstance(host, str) and host.casefold().rstrip('.') in {
        'localhost', '127.0.0.1', '::1', socket.gethostname().casefold().rstrip('.')}


def _stamp(info):
    return dict(device=info.st_dev, inode=info.st_ino, size=info.st_size,
                mtime_ns=info.st_mtime_ns, ctime_ns=info.st_ctime_ns)


def _adapter_identity():
    # These are NavCom's installed dependencies, not paths supplied by a ship.
    import navcom_ship_boarding
    import navcom_ship_inspection
    import navcom_source_reader
    paths = [Path(mod.__file__) for mod in (context, navcom_ship_boarding,
             navcom_ship_inspection, navcom_source_reader)] + [Path(__file__)]
    return {path.name: _hash(path.read_bytes()) for path in paths}


@contextmanager
def _cache_directory(value):
    """A private operator-selected cache directory; files never follow links.

    Resolve the existing parent (including macOS /tmp aliases), then create and
    open the cache itself relative to that directory. The cache leaf must never
    be a symlink, shared directory, or a ship-supplied location.
    """
    path = Path(value).expanduser().absolute()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    parent = os.open(path.parent.resolve(), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    fd = None
    try:
        try:
            os.mkdir(path.name, 0o700, dir_fd=parent)
        except FileExistsError:
            pass
        fd = os.open(path.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
        info = os.fstat(fd)
        if info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError('Carried-search cache must be an owned private directory (0700).')
        yield fd
    finally:
        if fd is not None:
            os.close(fd)
        os.close(parent)


def _cached(fd, name):
    try:
        with context._open(fd, name) as leaf:
            info = os.fstat(leaf)
            if info.st_uid != os.getuid() or info.st_mode & 0o077 or info.st_size > CACHE_BYTES:
                return None
            with os.fdopen(os.dup(leaf), 'rb') as stream:
                raw = stream.read(CACHE_BYTES + 1)
        if len(raw) > CACHE_BYTES:
            return None
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _write(fd, name, data):
    raw = json.dumps(data, ensure_ascii=False, separators=(',', ':')).encode()
    if len(raw) > CACHE_BYTES:
        raise ValueError('Carried search cache result exceeds its output bound.')
    temporary = '.' + uuid.uuid4().hex + '.tmp'
    leaf = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
    try:
        with os.fdopen(leaf, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, name, src_dir_fd=fd, dst_dir_fd=fd)
    finally:
        try:
            os.unlink(temporary, dir_fd=fd)
        except FileNotFoundError:
            pass


def _drop(fd, name):
    try:
        os.unlink(name, dir_fd=fd)
    except FileNotFoundError:
        pass


class _Deferred(ValueError):
    pass


def _pin(entity, budget, deadline, max_record_bytes, max_total_bytes, tool_root):
    """Read only the public catalog and no-follow record stats on cache hits."""
    if time.monotonic() >= deadline:
        raise _Deferred('Sweep time budget reached before catalog validation.')
    if budget['metadata_bytes'] + context.CATALOG_BYTES > METADATA_BYTES:
        raise _Deferred('Sweep catalog metadata byte bound reached.')
    root = context._selection(entity)
    raw, catalog = context._catalog(root)
    budget['metadata_bytes'] += len(raw)
    if budget['metadata_bytes'] > METADATA_BYTES:
        raise _Deferred('Sweep catalog metadata byte bound reached.')
    records, seen, total = [], set(), 0
    anchor = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        with context._open(anchor, root.relative_to('/'), directory=True) as root_fd:
            root_stat = _stamp(os.fstat(root_fd))
            for record in catalog['sessions']:
                if time.monotonic() >= deadline or budget['metadata_records'] >= METADATA_RECORDS:
                    raise _Deferred('Sweep record-metadata or time bound reached.')
                relative = record['file']
                if relative in seen:
                    raise ValueError('Distinct carried session identities share one record.')
                seen.add(relative)
                with context._open(root_fd, relative) as leaf:
                    info = os.fstat(leaf)
                    total += info.st_size
                    if info.st_size > max_record_bytes or total > max_total_bytes:
                        raise ValueError('Carried dialogue exceeds the configured per-record or per-ship byte bound.')
                    records.append(dict(id=record['id'], file=relative, stat=_stamp(info)))
                budget['metadata_records'] += 1
    finally:
        os.close(anchor)
    _, identity = context._tool(root, tool_root)
    return dict(root=str(root), root_stat=root_stat, catalog_sha256=_hash(raw), records=records,
                record_bytes=total, sessions=len(records), tool=identity)


_SCRIPT = """import json,sys
sys.path.insert(0,sys.argv[1])
import navcom_ship_context as reader
request=json.load(sys.stdin)
reader.RECORD_BYTES=request.pop('max_record_bytes')
reader.TOTAL_BYTES=request.pop('max_total_bytes')
entity=request.pop('entity')
print(json.dumps(reader.read_context(entity,**request),ensure_ascii=False))
"""


def _run_native(entity, query, pin, *, limit, max_chars, max_record_bytes, max_total_bytes,
                tool_root, seconds):
    """Bound the existing reader and its native grandchild by one deadline."""
    request = dict(entity=entity, query=query, expected_catalog=pin['catalog_sha256'],
                   limit=limit, max_chars=max_chars, max_record_bytes=max_record_bytes,
                   max_total_bytes=max_total_bytes, tool_root=str(tool_root) if tool_root else None)
    with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
        process = subprocess.Popen([sys.executable, '-I', '-B', '-c', _SCRIPT,
            str(Path(__file__).resolve().parent)], stdin=subprocess.PIPE, stdout=output, stderr=errors,
            cwd='/', env={'PATH': os.defpath}, start_new_session=True)
        try:
            process.communicate(json.dumps(request).encode(), timeout=seconds)
        except subprocess.TimeoutExpired:
            kill_group(process)
            raise _Deferred('Native carried search reached the sweep time budget.') from None
        if process.returncode or os.fstat(output.fileno()).st_size > CACHE_BYTES:
            raise ValueError('Native carried search could not complete within its output bound.')
        output.seek(0)
        result = json.loads(output.read(CACHE_BYTES + 1))
    return result


def _validate(result, entity, pin, limit, max_chars):
    if (not isinstance(result, dict) or result.get('state') != 'available'
            or result.get('ship_id') != entity['id']
            or result.get('provenance', {}).get('catalog_sha256') != pin['catalog_sha256']):
        raise ValueError((result.get('reason') if isinstance(result, dict) else '') or
                         'Native carried search is unavailable for this exact ship.')
    messages = result.get('messages')
    allowed = {item['id'] for item in pin['records']}
    if not isinstance(messages, list) or len(messages) > limit:
        raise ValueError('Native carried search returned an unsupported message envelope.')
    for item in messages:
        if (not isinstance(item, dict) or item.get('id') not in allowed
                or type(item.get('index')) is not int or item['index'] < 0
                or not isinstance(item.get('text'), str) or len(item['text']) > max_chars):
            raise ValueError('Native carried search returned an invalid exact turn.')
    return result


def _hit(entity, item, result):
    catalog = result['provenance']['catalog_sha256']
    record = next((r for r in result['provenance'].get('records', []) if r.get('id') == item['id']), {})
    return dict(ship=entity, ship_id=entity['id'], session_id=item['id'], index=item['index'],
                provider=item.get('provider'), role=item.get('role'), text=item['text'],
                text_chars=item.get('text_chars'), text_truncated=bool(item.get('text_truncated')),
                title=item.get('title', ''), project=item.get('project', ''), catalog_sha256=catalog,
                record_sha256=record.get('sha256'), context_ref=dict(ship_id=entity['id'],
                    session_id=item['id'], index=item['index'], catalog_sha256=catalog))


def _retain(pool, entity, result, limit):
    """Keep at most one output page in memory, preserving native ship order."""
    pool.append([_hit(entity, item, result) for item in result['messages']])
    retained = [[] for _ in pool]
    count = 0
    for n in range(limit):
        for i, rows in enumerate(pool):
            if n < len(rows) and count < limit:
                retained[i].append(rows[n]); count += 1
    pool[:] = [rows for rows in retained if rows]


def _flatten(pool, limit):
    return [rows[n] for n in range(limit) for rows in pool if n < len(rows)][:limit]


def search(entities, query, cache_path, *, limit=20, max_chars=1200, max_ships=8, seconds=10,
           max_record_bytes=8 * 1024 * 1024, max_total_bytes=32 * 1024 * 1024, tool_root=None):
    """Search exact caller-scoped ships with a private, per-query result cache.

    ``cache_path`` is a dedicated directory; ``tool_root`` is trusted operator
    configuration, never metadata. ``max_ships`` bounds fresh native calls, not
    cached zero-hit results. A small pending-ID cursor prevents one timeout or
    metadata budget from starving later allowed ships across repeated queries.
    """
    if not isinstance(query, str) or not query.strip() or len(query) > 500:
        raise ValueError('Enter a nonempty carried-context query of at most 500 characters.')
    context._bounds(0, limit, max_chars)
    if (type(max_ships) is not int or not 1 <= max_ships <= 32
            or isinstance(seconds, bool) or not isinstance(seconds, (int, float))
            or not math.isfinite(seconds) or not 0 < seconds <= 30
            or type(max_record_bytes) is not int or not 1 <= max_record_bytes <= context.RECORD_BYTES
            or type(max_total_bytes) is not int or not 1 <= max_total_bytes <= context.TOTAL_BYTES):
        raise ValueError('Require 1–32 native ships, >0–30 seconds and bounded carried record bytes.')
    if not isinstance(entities, (list, tuple)) or len(entities) > MAX_ENTITIES:
        raise ValueError('Supply at most 256 exact scoped ship entities.')
    selected, seen = [], set()
    for entity in entities:
        if (not isinstance(entity, dict) or entity.get('kind') != 'ship'
                or not isinstance(entity.get('id'), str) or not entity['id'] or len(entity['id']) > 256
                or entity['id'] in seen):
            raise ValueError('Supply distinct exact ship identities; place expansion belongs to the caller.')
        seen.add(entity['id']); selected.append(_mini(entity))
    started = time.monotonic(); deadline = started + seconds
    args = dict(query=query, limit=limit, max_chars=max_chars, max_record_bytes=max_record_bytes,
                max_total_bytes=max_total_bytes, version=VERSION)
    request_key = _hash(dict(args, entities=selected))
    budget = dict(metadata_bytes=0, metadata_records=0)
    states, pending, timed_out = {}, [], []
    cached_hits, fresh_hits = [], []
    matched = 0
    native_more = False
    native_calls = cached_ships = 0
    adapters = None
    with _cache_directory(cache_path) as cache:
        progress_name = request_key + '.pending.json'
        progress = _cached(cache, progress_name) or {}
        saved_pending = progress.get('pending', [])
        if not isinstance(saved_pending, list) or len(saved_pending) > MAX_ENTITIES:
            saved_pending = []
        priorities = {identity: i for i, identity in enumerate(saved_pending)
                      if isinstance(identity, str) and identity in seen}
        ordered = sorted(selected, key=lambda e: priorities.get(e['id'], len(priorities)))
        for entity in ordered:
            identity = entity['id']
            state = dict(ship=entity, ship_id=identity, state='unavailable', cached=False)
            launched = False
            states[identity] = state
            name = _hash(dict(args, ship_id=identity, physical=entity['physical'])) + '.json'
            if not _local(entity):
                _drop(cache, name)
                state['reason'] = 'Remote or unspecified ship location; no local path or reader was probed.'
                continue
            try:
                pin = _pin(entity, budget, deadline, max_record_bytes, max_total_bytes, tool_root)
                if adapters is None:
                    adapters = _adapter_identity()
                fingerprint = _hash(dict(args, pin=pin, adapters=adapters))
                saved = _cached(cache, name)
                result = None
                if saved and saved.get('fingerprint') == fingerprint:
                    try:
                        result = _validate(saved.get('result'), entity, pin, limit, max_chars)
                    except ValueError:
                        pass
                if result is not None:
                    state['cached'] = True
                    cached_ships += 1
                else:
                    _drop(cache, name)
                    if native_calls >= max_ships or time.monotonic() >= deadline:
                        raise _Deferred('Fresh native ship or sweep time bound reached.')
                    native_calls += 1
                    launched = True
                    result = _run_native(entity, query, pin, limit=limit, max_chars=max_chars,
                        max_record_bytes=max_record_bytes, max_total_bytes=max_total_bytes,
                        tool_root=tool_root, seconds=max(0.001, deadline-time.monotonic()))
                    _validate(result, entity, pin, limit, max_chars)
                    after = _pin(entity, budget, deadline, max_record_bytes, max_total_bytes, tool_root)
                    if after != pin:
                        raise ValueError('Carried catalog, record metadata or installed reader changed during search; retry.')
                    # Omit shell commands from federation cache; only reader data is retained.
                    result.pop('native_command', None)
                    _write(cache, name, dict(fingerprint=fingerprint, result=result))
                matched += len(result['messages'])
                native_more = native_more or result.get('next_offset') is not None
                _retain(cached_hits if state['cached'] else fresh_hits, entity, result, limit)
                state.update(state='available', catalog_sha256=pin['catalog_sha256'],
                    observed_at=result.get('observed_at'), returned=len(result['messages']),
                    next_offset=result.get('next_offset'), coverage=result.get('coverage', {}))
            except _Deferred as error:
                state.update(state='unsearched', reason=str(error))
                (timed_out if launched else pending).append(identity)
            except (OSError, ValueError) as error:
                _drop(cache, name)
                # Errors contain metadata paths at most; subprocess stderr/record contents are never surfaced.
                state['reason'] = str(error)[:500]
        next_ids = pending + timed_out
        _write(cache, progress_name, dict(pending=next_ids))
    # Cached hits precede newly read hits; round-robin preserves native order
    # within each ship without inventing another relevance/ranking algorithm.
    all_hits = _flatten(cached_hits, limit) + _flatten(fresh_hits, limit)
    unavailable = [e['id'] for e in selected if states[e['id']]['state'] == 'unavailable']
    truncated = matched > limit or native_more
    return dict(schema_version=VERSION, query=query, hits=all_hits[:limit],
        ships=[states[e['id']] for e in selected], cached=native_calls == 0 and not next_ids,
        next_ship_ids=next_ids, policy=POLICY,
        coverage=dict(complete=not next_ids and not unavailable and not truncated,
            eligible=len(selected), searched=sum(s['state']=='available' for s in states.values()),
            cached_ships=cached_ships, native_calls=native_calls,
            unavailable_ids=unavailable, unsearched_ids=next_ids, truncated=truncated,
            limit=limit, max_chars=max_chars, max_ships=max_ships, seconds=seconds,
            elapsed_seconds=round(time.monotonic()-started, 4), **budget,
            max_metadata_bytes=METADATA_BYTES, max_metadata_records=METADATA_RECORDS,
            max_record_bytes=max_record_bytes, max_total_bytes=max_total_bytes,
            cache_validation='Public catalog bytes plus no-follow inode/size/mtime/ctime and installed reader identity; '
                             'native reads validate dialogue content hashes.'))
