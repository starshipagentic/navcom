"""Read carried ship dialogue through the installed native Starship reader.

This is context recovery, not captain resume. Only the exact selected local
ship's documented dialogue catalog/records and HANDOVER.md are eligible. Native
search/open runs against a bounded temporary view of unchanged carried bytes;
project-carried code, credential files and current host conversations are absent.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shlex
import subprocess
import sys
import tempfile
import time

from navcom_ship_boarding import BoardingError, _installed_path, _selection
from navcom_ship_inspection import _text
from navcom_source_reader import _open


VERSION = 1
CATALOG = PurePosixPath('.starship/navcom/index.json')
HANDOVER = PurePosixPath('.starship/HANDOVER.md')
RECORDS = PurePosixPath('.starship/secrets/navcom')
CATALOG_BYTES = 1024 * 1024
RECORD_BYTES = 8 * 1024 * 1024
TOTAL_BYTES = 64 * 1024 * 1024
SESSION_LIMIT = 1000
HANDOVER_BYTES = 256 * 1024
TOOL_BYTES = 256 * 1024
POLICY = ('Carried dialogue is a recorded context snapshot, not current host history or a native captain session. '
          'Reading it does not resume a captain, restore a ship, or prove readiness.')


class ContextError(ValueError):
    pass


def _hash(data):
    return hashlib.sha256(data).hexdigest()


def _bounds(offset, limit, max_chars):
    if (type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 50
            or type(max_chars) is not int or not 1 <= max_chars <= 8000):
        raise ContextError('Require offset >= 0, limit 1–50, max_chars 1–8000.')


def _read(root, relative, maximum):
    """Read one declared file without following a component link, within a cap."""
    relative = PurePosixPath(relative)
    if relative.is_absolute() or '..' in relative.parts:
        raise ContextError('Context path is outside the selected ship.')
    anchor = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        # Reuse the source reader's descriptor-relative traversal: every
        # directory is opened no-follow and the leaf uses O_NONBLOCK, so a FIFO
        # or a swapped ancestor cannot escape or stall the bounded read.
        with _open(anchor, root.relative_to('/'), directory=True) as root_fd:
            with _open(root_fd, relative) as fd:
                if os.fstat(fd).st_size > maximum:
                    raise ContextError('Carried context exceeds its regular-file read bound.')
                with os.fdopen(os.dup(fd), 'rb') as stream:
                    data = stream.read(maximum + 1)
                if len(data) > maximum:
                    raise ContextError('Carried context exceeds its read bound.')
    finally:
        os.close(anchor)
    return data


def _catalog(root):
    raw = _read(root, CATALOG, CATALOG_BYTES)
    try:
        catalog = json.loads(raw)
    except (ValueError, UnicodeError):
        raise ContextError('The carried conversation catalog is not valid JSON.') from None
    sessions = catalog.get('sessions') if isinstance(catalog, dict) else None
    if not isinstance(sessions, list) or len(sessions) > SESSION_LIMIT:
        raise ContextError('Carried catalog requires at most 1000 explicit session records.')
    seen = set()
    for item in sessions:
        if not isinstance(item, dict) or not isinstance(item.get('id'), str) or not item['id'] or item['id'] in seen:
            raise ContextError('Carried catalog session identities are missing or duplicated.')
        if len(item['id']) > 200 or any(ord(c) < 32 for c in item['id']):
            raise ContextError('Carried session identity is invalid.')
        seen.add(item['id'])
        value = item.get('file')
        if (not isinstance(value, str) or '\\' in value or '\x00' in value
                or PurePosixPath(value).is_absolute() or '..' in PurePosixPath(value).parts):
            raise ContextError('Carried session path is outside its documented history store.')
        relative = PurePosixPath(value)
        if relative.parent != RECORDS or relative.suffix != '.json':
            raise ContextError('Only catalog-declared dialogue records in .starship/secrets/navcom are supported.')
    return raw, catalog


def _tool(root, tool_root):
    directory = Path(tool_root or Path.home() / '.codex/skills/ship-commission/scripts').expanduser()
    if not directory.is_absolute() or '.starship' in directory.parts:
        raise ContextError('Use independently installed ship-commission tools.')
    value, identity = _installed_path(str(directory / 'navcom.py'), root)
    if Path(value).stat().st_size > TOOL_BYTES:
        raise ContextError('Installed native history reader exceeds its source bound.')
    identity['sha256'] = _hash(Path(value).read_bytes())
    return value, identity


def _base(entity, action):
    return dict(schema_version=VERSION, ship_id=entity.get('id'), label=_text(entity.get('label'), 200),
                action=action, state='unavailable', read_only=True, observed_at=time.time(),
                policy=POLICY, messages=[], coverage=dict(complete=False), provenance={})


def _unavailable(result, error):
    result['reason'] = (str(error) if isinstance(error, (ContextError, BoardingError)) else
                        'The exact carried context or installed native reader is unavailable.')
    return result


def inspect_context(entity, *, offset=0, limit=50, expected_catalog=''):
    """List bounded catalog metadata only, without reading private dialogue."""
    _bounds(offset, limit, 1)
    if expected_catalog and (not isinstance(expected_catalog, str) or len(expected_catalog) != 64
                             or any(c not in '0123456789abcdef' for c in expected_catalog)):
        raise ContextError('Expected catalog must be its SHA-256.')
    result = _base(entity, 'inspect')
    try:
        root = _selection(entity)
        raw, catalog = _catalog(root)
        if expected_catalog and _hash(raw) != expected_catalog:
            raise ContextError('The carried catalog changed; reopen its current session inventory.')
        sessions = catalog['sessions']
        items = []
        for record in sessions[offset:offset + limit]:
            item = {k: _text(record.get(k), 300) for k in ('id', 'provider', 'project', 'title')}
            item['messages'] = record.get('messages') if type(record.get('messages')) is int else None
            items.append(item)
        next_offset = offset + len(items) if offset + len(items) < len(sessions) else None
        result.update(state='available', sessions=items, total_sessions=len(sessions), offset=offset,
                      next_offset=next_offset, context_kind='carried_dialogue',
                      coverage=dict(complete=next_offset is None, catalog_only=True, dialogue_read=False),
                      provenance=dict(root=str(root), catalog=str(root / CATALOG), catalog_sha256=_hash(raw)))
    except (OSError, ValueError) as exc:
        return _unavailable(result, exc)
    return result


def _records(root, sessions):
    contents, provenance = {}, []
    total = 0
    for record in sessions:
        relative = record['file']
        if relative in contents:
            raise ContextError('Distinct session identities share one dialogue record.')
        payload = _read(root, relative, min(RECORD_BYTES, TOTAL_BYTES - total))
        total += len(payload)
        signature = _hash(payload)
        expected = record.get('sha256')
        if expected is not None and expected != signature:
            raise ContextError('Carried dialogue differs from its catalog hash; no current history was substituted.')
        try:
            data = json.loads(payload)
        except (ValueError, UnicodeError):
            raise ContextError('A carried dialogue record is invalid JSON.') from None
        if (not isinstance(data, dict) or data.get('id') != record['id']
                or data.get('provider') != record.get('provider') or not isinstance(data.get('messages'), list)):
            raise ContextError('Carried dialogue identity does not match its catalog.')
        for message in data['messages']:
            if (not isinstance(message, dict) or type(message.get('index')) is not int
                    or not isinstance(message.get('text'), str)):
                raise ContextError('Carried dialogue has an invalid native message.')
        contents[relative] = payload
        provenance.append(dict(id=record['id'], file=relative, sha256=signature, bytes=len(payload),
                               catalog_hash_verified=expected is not None))
    return contents, provenance, total


def read_context(entity, *, action='search', query='', ref='', turn=None, offset=0, limit=10,
                 max_chars=2000, expected_catalog='', tool_root=None):
    """Search/open native carried dialogue or read the documented handover.

    ``tool_root`` is operator configuration; never take it from a catalog entity
    or browser request. Search/open preserve native original-turn indices and
    pagination. Only bounded copies are passed to the installed native reader.
    """
    _bounds(offset, limit, max_chars)
    if action not in ('search', 'open', 'handover'):
        raise ContextError('Choose search, open or handover.')
    if action == 'search' and (not isinstance(query, str) or not query.strip() or len(query) > 500):
        raise ContextError('Enter a nonempty carried-context query of at most 500 characters.')
    if action == 'open' and (not isinstance(ref, str) or not ref or len(ref) > 200):
        raise ContextError('Choose an exact carried session ID from the catalog.')
    if turn is not None and (type(turn) is not int or turn < 0 or action != 'open'):
        raise ContextError('An exact original turn must be a nonnegative integer for open.')
    if expected_catalog and (not isinstance(expected_catalog, str) or len(expected_catalog) != 64
                             or any(c not in '0123456789abcdef' for c in expected_catalog) or action == 'handover'):
        raise ContextError('Expected catalog must be its SHA-256 for a dialogue search/open.')
    result = _base(entity, action)
    try:
        root = _selection(entity)
        if action == 'handover':
            raw = _read(root, HANDOVER, HANDOVER_BYTES)
            document = raw.decode('utf-8')
            excerpt = document[offset:offset + max_chars]
            next_offset = offset + len(excerpt) if offset + len(excerpt) < len(document) else None
            result.update(state='available', context_kind='handover', text=excerpt, offset=offset,
                          next_offset=next_offset, text_chars=len(document), text_truncated=next_offset is not None,
                          coverage=dict(complete=next_offset is None, offset_unit='characters', max_chars=max_chars),
                          provenance=dict(root=str(root), path=str(root / HANDOVER), sha256=_hash(raw)))
            return result
        catalog_raw, catalog = _catalog(root)
        if expected_catalog and _hash(catalog_raw) != expected_catalog:
            raise ContextError('The carried catalog changed; search again before opening its current context.')
        selected = [record for record in catalog['sessions'] if action != 'open' or record['id'] == ref]
        if action == 'open' and len(selected) != 1:
            raise ContextError('The session ID is absent from this exact ship catalog.')
        files, records, total = _records(root, selected)
        tool, identity = _tool(root, tool_root)
        # Native argparse options must precede the positional -- separator.
        suffix = [action, '--offset', str(offset), '--limit', str(limit), '--max-chars', str(max_chars)]
        if turn is not None:
            suffix += ['--turn', str(turn)]
        suffix += ['--', query if action == 'search' else ref]
        with tempfile.TemporaryDirectory(prefix='navcom-ship-context-') as folder:
            snapshot = Path(folder)
            for relative, payload in {str(CATALOG): catalog_raw, **files}.items():
                destination = snapshot / relative
                destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(payload)
            completed = subprocess.run([sys.executable, '-I', '-B', tool, '--ship', str(snapshot), *suffix],
                cwd=str(Path(tool).parent), env={'PATH': os.defpath}, capture_output=True, text=True, timeout=15)
        if completed.returncode or len(completed.stdout) > 4 * 1024 * 1024:
            raise ContextError('The installed native carried-history reader could not complete its bounded read.')
        native = json.loads(completed.stdout)
        if not isinstance(native, dict) or not isinstance(native.get('messages'), list) or len(native['messages']) > limit:
            raise ContextError('Native reader returned an unsupported message envelope.')
        allowed = {record['id']: record for record in selected}
        for item in native['messages']:
            if (not isinstance(item, dict) or item.get('id') not in allowed
                    or item.get('provider') != allowed[item['id']].get('provider')
                    or not isinstance(item.get('text'), str) or len(item['text']) > max_chars):
                raise ContextError('Native reader returned a message outside the selected context.')
            record = allowed[item['id']]
            item['title'] = _text(record.get('title'), 300)
            item['project'] = _text(record.get('project'), 1000)
        result.update(native, state='available', context_kind='carried_dialogue', query=query if action == 'search' else '',
                      ref=ref if action == 'open' else '', turn=turn,
                      coverage=dict(complete=native.get('next_offset') is None, sessions_considered=len(selected),
                                    record_bytes=total, max_record_bytes=RECORD_BYTES, max_total_bytes=TOTAL_BYTES,
                                    full_history=False, meaning='Only dialogue retained in this ship catalog.'),
                      provenance=dict(root=str(root), catalog=str(root / CATALOG), catalog_sha256=_hash(catalog_raw),
                                      records=records, tool=identity, isolation='Bounded unchanged catalog/record bytes; no project code.'),
                      native_command=shlex.join([sys.executable, '-B', tool, '--ship', str(root), *suffix]))
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        return _unavailable(result, exc)
    return result


def render(data):
    """Human CLI output keeps provenance and native turn addresses visible."""
    print((data.get('label') or data.get('ship_id') or 'Ship')+' · carried context · '+data['state'])
    if data['state'] != 'available':
        print(data.get('reason', 'Carried context is unavailable.'))
        print(data['policy'])
        return
    if data.get('context_kind') == 'handover':
        print('\n'+data['text'])
        print('\nHandover file: '+data['provenance']['path'])
    elif data['action'] == 'inspect':
        print(str(data['total_sessions'])+' carried sessions')
        for session in data.get('sessions', []):
            print(session['id']+' · '+session['provider']+' · '+(session['title'] or session['project']))
    else:
        for message in data.get('messages', []):
            print('\n'+message['id']+' · turn '+str(message['index'])+' · '+str(message.get('role','')))
            print(message['text'])
            if message.get('text_truncated'):
                print('[Original message clipped to the requested character limit.]')
        if not data.get('messages'):
            print('No matching carried messages in this window.')
    if data.get('next_offset') is not None:
        print('\nContinue: '+data['continue_command'] if data.get('continue_command') else
              '\nContinue with --offset '+str(data['next_offset']))
    if data['provenance'].get('catalog_sha256'):
        print('\nCarried catalog: '+data['provenance']['catalog_sha256'])
    if data.get('cli_command'):
        print('\nReplay: '+data['cli_command'])
    print('\n'+data['policy'])


def main(argv=None):
    """Small CLI proof surface; the main atlas CLI can call this shared API."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--space-cache', required=True, type=Path)
    parser.add_argument('--within', required=True, help='Exact catalog ship ID or unique name.')
    parser.add_argument('--offset', type=int, default=0)
    parser.add_argument('--limit', type=int, default=10)
    parser.add_argument('--max-chars', type=int, default=2000)
    parser.add_argument('--expected-catalog', default='', help='Keep the exact catalog generation from a prior search.')
    sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('inspect')
    sub.add_parser('search').add_argument('query')
    opening = sub.add_parser('open')
    opening.add_argument('ref')
    opening.add_argument('--turn', type=int)
    sub.add_parser('handover')
    args = parser.parse_args(argv)
    try:
        import navcom_space
        entity = navcom_space.view(args.space_cache, action='show', within=args.within)['center']
        if args.action == 'inspect':
            result = inspect_context(entity, offset=args.offset, limit=args.limit, expected_catalog=args.expected_catalog)
        else:
            result = read_context(entity, action=args.action, query=getattr(args, 'query', ''),
                                  ref=getattr(args, 'ref', ''), turn=getattr(args, 'turn', None),
                                  offset=args.offset, limit=args.limit, max_chars=args.max_chars,
                                  expected_catalog=args.expected_catalog)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result['state'] == 'available' else 2
    except (OSError, ValueError) as exc:
        parser.error(str(exc))


if __name__ == '__main__':
    raise SystemExit(main())
