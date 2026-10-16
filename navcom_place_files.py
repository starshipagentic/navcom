"""Browse retained harvested files at a place, without source scans or inference."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shlex
import stat
import time

from navcom_source_reader import SourceReadError, _json, _open, _relative, _source_record

MAX_FILES = 20000
MAX_DIRECTORIES = 2000
MAX_ENTRIES = 50000
MAX_SECONDS = 3


def _inside(path, scopes):
    return any(path == scope or scope in path.parents for scope in scopes)


def _inventory(fd, scopes, budget, seen, prefix=PurePosixPath('.')):
    """Walk only the published artifact through no-follow directory descriptors."""
    if budget['files'] >= MAX_FILES or budget['directories'] >= MAX_DIRECTORIES or time.monotonic() > budget['deadline']:
        budget['limited'] = True
        return
    budget['directories'] += 1
    seen.update(scope for scope in scopes if scope == prefix)
    names = []
    # Bound directory fanout before sorting; listdir could allocate an arbitrary
    # number of entries before either the file or time budget was checked.
    with os.scandir(fd) as entries:
        for entry in entries:
            if budget['entries'] >= MAX_ENTRIES or time.monotonic() > budget['deadline']:
                budget['limited'] = True
                break
            budget['entries'] += 1
            names.append(entry.name)
    for name in sorted(names):
        if budget['files'] >= MAX_FILES or time.monotonic() > budget['deadline']:
            budget['limited'] = True
            return
        path = prefix / name
        relevant = _inside(path, scopes)
        if not relevant and not any(path in scope.parents for scope in scopes):
            continue
        try:
            metadata = os.stat(name, dir_fd=fd, follow_symlinks=False)
            if stat.S_ISDIR(metadata.st_mode):
                with _open(fd, name, directory=True) as child:
                    yield from _inventory(child, scopes, budget, seen, path)
            elif stat.S_ISREG(metadata.st_mode) and relevant:
                # Confirm the counted leaf itself, not only its earlier name
                # lookup. A swap to a symlink/FIFO cannot become a file result.
                with _open(fd, name) as leaf:
                    metadata = os.fstat(leaf)
                budget['files'] += 1
                seen.update(scope for scope in scopes if scope == path)
                yield str(path), metadata.st_size
            else:
                budget['omitted'] += 1
        except (SourceReadError, OSError):
            budget['omitted'] += 1


def files(space_cache, source_cache, within, *, query='', limit=40, offset=0, generation=''):
    import navcom_space
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 200 or not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
        raise ValueError('File limit must be 1–200 and offset must be nonnegative.')
    if not isinstance(query, str) or len(query) > 500:
        raise ValueError('File filter must be at most 500 characters.')
    catalog = navcom_space._read(Path(space_cache).expanduser()) or {}
    center = navcom_space.view(space_cache, action='show', within=within, catalog=catalog)['center']
    if center['kind'] not in ('planet', 'moon', 'district'):
        raise ValueError('Choose a product, experiment or district to browse its retained files.')
    scopes = {}
    for scope in center.get('source_scopes', []):
        paths = scope.get('paths')
        if not isinstance(paths, list) or not paths:
            raise ValueError('Missing saved file scope; refresh the chart before browsing files.')
        for value in paths:
            path = _relative(value)
            if path.is_absolute():
                raise ValueError('Saved file scopes must be relative to their source.')
            scopes.setdefault(scope['source_id'], set()).add(path)
    if len(scopes) > 32:
        raise ValueError('This place has more than 32 sources; choose a narrower district.')
    alias = Path(source_cache).expanduser().absolute()
    cache = alias.resolve()
    rows, errors, sources, identities = [], [], [], []
    budget = dict(files=0, directories=0, entries=0, deadline=time.monotonic()+MAX_SECONDS, limited=False, omitted=0)
    stamp = None
    if scopes:
        try:
            fd = os.open(cache, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        except OSError as error:
            raise SourceReadError('Published source cache is unavailable; harvest this place first.') from error
        try:
            state = _json(fd, 'current.json')
            stamp = state.get('published')
            for sid, paths in sorted(scopes.items()):
                try:
                    source, recorded, root, key, stamp = _source_record(fd, cache, alias, sid, state=state)
                    selected = [str(p) for p in sorted(paths)]
                    identities.append([sid, key, selected])
                    allowed = [_relative(p) for p in recorded.get('include', [])]
                    if not allowed or any(not _inside(p, allowed) and not any(p in a.parents for a in allowed) for p in paths):
                        raise SourceReadError('Saved place scope is outside the published harvest.')
                    seen = set()
                    with _open(fd, 'artifacts/'+key+'/source', directory=True) as snapshot_fd:
                        for relative, size in _inventory(snapshot_fd, paths, budget, seen):
                            if not _inside(PurePosixPath(relative), allowed):
                                continue
                            ref = dict(source_id=sid, relative_path=relative, line=1, snapshot=key, published=stamp)
                            command = ['navcom', 'sources', 'read', sid, relative, '--snapshot', key, '--published', str(stamp), '--cache', str(alias)]
                            rows.append(dict(source_ref=ref, source_id=sid, relative_path=relative, original_path=str(root/relative),
                                             bytes=size, read_command=shlex.join(command)))
                    if not budget['limited']:
                        for missing in sorted(paths - seen):
                            errors.append(dict(source_id=sid, path=str(missing),
                                message='Saved path is missing or unreadable in the published snapshot: '+str(missing)))
                    sources.append(dict(source_id=sid, root=str(root), snapshot=key, scopes=selected,
                                        harvest_coverage=source.get('coverage', {})))
                except (SourceReadError, OSError) as error:
                    errors.append(dict(source_id=sid, message=str(error)))
                    identities.append([sid, 'unavailable'])
        finally:
            os.close(fd)
    current = hashlib.sha256(json.dumps([center['id'], identities], sort_keys=True).encode()).hexdigest()
    if generation and generation != current:
        raise ValueError('The saved file inventory changed; reopen the first page before continuing.')
    if offset and budget['limited']:
        raise ValueError('This retained inventory reached its scan budget; later pages are unstable. Choose a narrower district and reopen its first page.')
    terms = query.casefold().split()
    rows = sorted((r for r in rows if all(term in r['relative_path'].casefold() for term in terms)),
                  key=lambda r:(r['relative_path'].casefold(), r['source_id']))
    result = dict(schema_version=1, center={k:center[k] for k in ('id','label','kind')}, query=query,
                  generation=current, published=stamp, files=rows[offset:offset+limit], total=len(rows), offset=offset,
                  limit=limit, more=not budget['limited'] and offset+limit<len(rows), sources=sources, errors=errors,
                  coverage=dict(retained_only=True, current_files_read=False, harvest_invocations=0,
                                inventoried_files=budget['files'], directories=budget['directories'], limited=budget['limited'],
                                inspected_entries=budget['entries'], max_entries=MAX_ENTRIES,
                                omitted_entries=budget['omitted'], complete=not errors and not budget['limited'] and not budget['omitted']))
    if budget['limited']:
        result['coverage']['continuation'] = 'Choose a narrower district; bounded partial inventories cannot be paged.'
    command = ['navcom','atlas','files',center['id'],'--space-cache',str(space_cache),'--source-cache',str(alias),'--limit',str(limit)]
    if query: command += ['--query',query]
    result['cli_command'] = shlex.join(command+['--offset',str(offset),'--generation',current])
    result['next_command'] = shlex.join(command+['--offset',str(offset+limit),'--generation',current]) if result['more'] else None
    return result


def render(data):
    print(data['center']['label']+' · retained files')
    for file in data['files']:
        print(file['relative_path']+' · '+str(file['bytes'])+' bytes\n  '+file['read_command'])
    print(str(data['offset']+1 if data['files'] else 0)+'–'+str(data['offset']+len(data['files']))+' of '+str(data['total'])+' matching retained files.')
    print('Published harvest only; current source files were not read. Coverage is bounded, not a full-repository inventory.')
    for error in data['errors']: print(error['source_id']+': '+error['message'])
    if not data['coverage']['complete']: print('Inventory coverage is incomplete: '+json.dumps(data['coverage']))
    if data['next_command']: print('More: '+data['next_command'])
