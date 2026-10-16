"""Cached native lineage suggestions and literal documented place references.

These are evidence about retained source paths, never ownership, ancestry, or
historical succession. All analysis runs against immutable harvest snapshots.
"""
import argparse
from collections import defaultdict
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
import time

VERSION = 1
SOURCE_PAGE = 8
MAX_FILES = 20000
MAX_DIRECTORIES = 2000
MAX_GROUPS = 128
MAX_OUTPUT = 4 * 1024 * 1024


def _safe(value):
    return isinstance(value, str) and bool(value) and not Path(value).is_absolute() and '..' not in Path(value).parts


def _inside(path, scopes):
    return any(Path(scope) == path or Path(scope) in path.parents for scope in scopes)


def _files(source, scopes, cache):
    snapshot = Path(source['artifact']) / 'source'
    base = cache.resolve()
    if not snapshot.is_relative_to(base) or snapshot.is_symlink():
        raise ValueError('Harvest snapshot is outside the configured source cache.')
    relative = snapshot.relative_to(base)
    if any(base.joinpath(*relative.parts[:i]).is_symlink() for i in range(1, len(relative.parts) + 1)):
        raise ValueError('Harvest snapshot contains a linked path.')
    if not snapshot.is_dir():
        raise ValueError('Harvest snapshot is unavailable.')
    files = []
    omitted = ['Saved scope is absent from the current snapshot: ' + scope
               for scope in scopes if not (snapshot / scope).exists()]
    for folder, directories, names in os.walk(snapshot, followlinks=False):
        parent = Path(folder)
        directories[:] = sorted(name for name in directories if not name.startswith('.')
            and not (parent / name).is_symlink()
            and any(_inside((parent / name).relative_to(snapshot), scopes)
                    or (parent / name).relative_to(snapshot) in Path(scope).parents for scope in scopes))
        for name in sorted(names):
            path = parent / name
            relative = path.relative_to(snapshot)
            if name.startswith('.') or path.is_symlink() or not _inside(relative, scopes):
                continue
            if len(files) >= MAX_FILES:
                omitted.append('Retained file inventory exceeded the relationship file budget.')
                return snapshot, files, omitted
            files.append(relative)
    return snapshot, files, omitted


def _version_families(source, scopes, cache):
    from navcom_native_families import detect
    from navcom_sources_worker import EXT
    snapshot, files, omitted = _files(source, scopes, cache)
    directories = {parent for file in files for parent in file.parents if str(parent) != '.'}
    if len(directories) > MAX_DIRECTORIES:
        return [], dict(files=len(files), directories=len(directories), omitted=omitted +
                        ['Retained directory inventory exceeded the relationship directory budget.'])
    native = detect([str(path) for path in directories], source['label'])
    omitted.extend(native['omitted'])
    result = []
    for family in native['families']:
        members = []
        for member in family['members']:
            path = Path(member['path'])
            retained = [str(file) for file in files if file == path or path in file.parents]
            documents = sorted((file for file in retained if Path(file).name.lower() == 'readme.md'),
                               key=lambda file: (len(Path(file).parts), file))
            code = [file for file in retained if Path(file).suffix.lower() in EXT - {'.md', '.toml', '.yaml', '.yml', '.json'}]
            representatives = list(dict.fromkeys(documents[:1] + code + retained))[:3]
            member_scopes = [str(path)] if _inside(path, scopes) else [scope for scope in scopes
                if _inside(Path(scope), [str(path)])]
            members.append(dict(member, relative_path=str(path), retained_files=len(retained),
                                document=documents[0] if documents else None, scope_paths=member_scopes,
                                representative_files=[dict(relative_path=file) for file in representatives]))
        result.append(dict(family, kind='version_family_suggestion', source_id=source['id'],
            source_snapshot=Path(source['artifact']).name, members=members,
            meaning='Native name-family suggestion. Score is not a probability; order is heuristic, not dated succession.'))
    return result, dict(files=len(files), directories=len(directories), omitted=omitted,
                       snapshot=str(snapshot), scope=scopes)


def _native(request):
    import navcom_sources_worker as native
    from navcom_native_families import signature as family_signature
    cache = Path(request['source_cache']).resolve()
    state = native.read(cache / 'current.json')
    sources = {source['id']: source for source in state['sources']}
    selected = []
    for scope in request['scopes']:
        source = sources.get(scope['source_id'])
        if source is None:
            raise ValueError('A saved source scope is no longer published; refresh the chart.')
        selected.append((source, scope['paths']))
    engine = native.extractor_signature()
    fingerprint = native.digest(json.dumps([VERSION, request, state, engine, native.query_signature(), family_signature(),
        native.digest(Path(__file__).read_bytes())], sort_keys=True).encode())
    memo = cache / 'relationships' / (fingerprint + '.json')
    if memo.exists():
        return dict(native.read(memo), cached=True)
    root_targets = defaultdict(list)
    container_roots = set(request.get('container_roots', []))
    for source in state['sources']:
        root = str(Path(source['root']).expanduser())
        root_targets[root].append(source['id'])
        if source.get('discovery_coverage', {}).get('container_policy', {}).get('enabled'):
            container_roots.add(root)
    # Discovery already distinguishes broad containers from repository/product
    # roots. A reference to an unknown child is not a reference to its container.
    pattern = '|'.join(re.escape(root) + (r'(?=$|[\s`)\]#])' if root in container_roots
        else r'(?=$|[/\s`)\]#])') for root in sorted(root_targets, key=len, reverse=True))
    references = []
    families = []
    evidence = []
    coverage = []
    for source, paths in selected:
        found, inspected = _version_families(source, paths, cache)
        families.extend(found)
        inspected['source_id'] = source['id']
        inspected['harvest_coverage'] = dict(files=source.get('coverage', {}).get('files'),
            bytes=source.get('coverage', {}).get('bytes'), full_repository=False,
            discovery_limits=source.get('discovery_coverage', {}).get('limits', []))
        inspected['reference_container_roots'] = len(container_roots)
        inspected['reference_policy'] = 'Known broad containers match only their exact path, never an unknown descendant.'
        coverage.append(inspected)
        if pattern and len(pattern) <= 32768:
            hits = native.combined_search(dict(query=pattern, regex=True, ext='md', mode='text',
                within=source['id'], paths=paths, limit=100), cache, state=state, extractor=engine)
            inspected['reference_hits_truncated'] = hits['potentially_truncated']
            for hit in hits['text_hits']:
                # Alternatives are longest-first: a literal nested repository
                # reference must not also become a reference to every container.
                for root in dict.fromkeys(match.group(0) for match in re.finditer(pattern, hit['match'])):
                    target_ids = root_targets[root]
                    for target in target_ids:
                        if target != source['id']:
                            references.append(dict(kind='documented_path_reference', source_id=source['id'],
                                source_snapshot=Path(source['artifact']).name,
                                path=hit['relative_path'], relative_path=hit['relative_path'], line=hit['line'],
                                excerpt=root, excerpt_kind='matched_target_root',
                                target_source_id=target, target_root=root,
                                engine='starforge code-search',
                                meaning='This retained document literally references the target path; no ancestry or ownership is inferred.'))
        elif pattern:
            inspected['omitted'].append('Known-root reference pattern exceeded 32768 characters.')
        if request['query']:
            evidence.append(dict(source_id=source['id'], **native.combined_search(dict(query=request['query'],
                mode='both', within=source['id'], paths=paths, limit=min(request['limit'], 20)),
                cache, state=state, extractor=engine)))
    result = dict(schema_version=VERSION, families=families, references=references, evidence=evidence,
                  coverage=coverage, published=state['published'], fingerprint=fingerprint,
                  source_roots={source['id']: source['root'] for source, paths in selected},
                  cached=False, harvest_invocations=0)
    native.write(memo, result)
    return result


SCRIPT = '''import json,sys
sys.path.insert(0,sys.argv[1])
import navcom_relationships
try: print(json.dumps(navcom_relationships._native(json.load(sys.stdin))))
except Exception as exc:
 print(str(exc),file=sys.stderr);sys.exit(1)
'''


def _run(request, seconds):
    from navcom_sources import runtime
    interpreter = runtime()
    with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
        process = subprocess.Popen([interpreter, '-I', '-B', '-c', SCRIPT, str(Path(__file__).parent)],
            stdin=subprocess.PIPE, stdout=output, stderr=errors)
        try:
            process.stdin.write(json.dumps(request).encode())
            process.stdin.close()
            deadline = time.monotonic() + seconds
            while process.poll() is None:
                if time.monotonic() >= deadline:
                    raise TimeoutError('Relationship analysis reached its time budget; cached navigation remains available.')
                if output.tell() > MAX_OUTPUT or errors.tell() > 256 * 1024:
                    raise ValueError('Native relationship output exceeded its byte budget.')
                time.sleep(.025)
            if output.tell() > MAX_OUTPUT or errors.tell() > 256 * 1024:
                raise ValueError('Native relationship output exceeded its byte budget.')
            output.seek(0); errors.seek(0)
            if process.returncode:
                raise ValueError(errors.read(2048).decode(errors='replace').strip() or 'Native relationship analysis failed.')
            return json.loads(output.read())
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()


def related(space_cache, source_cache, within, *, query='', limit=20, seconds=15, offset=0):
    import navcom_space as space
    space_cache = Path(space_cache).expanduser().resolve()
    source_cache = Path(source_cache).expanduser().resolve()
    if not isinstance(query, str) or len(query) > 500:
        raise ValueError('Query must be text of at most 500 characters.')
    if not 1 <= int(limit) <= 100 or not 1 <= float(seconds) <= 30 or int(offset) < 0:
        raise ValueError('Use limit 1–100, seconds 1–30 and a nonnegative source offset.')
    chart = space._read(Path(space_cache).expanduser())
    selected = space.view(space_cache, action='show', within=within, catalog=chart)['center']
    scopes = defaultdict(set)
    for scope in selected.get('source_scopes', []):
        paths = scope.get('paths')
        if not isinstance(paths, list) or not paths or not all(_safe(path) for path in paths):
            raise ValueError('Saved source scope is missing or invalid; refresh the chart.')
        scopes[scope['source_id']].update(paths)
    ordered = [dict(source_id=key, paths=space._minimal_paths(paths)) for key, paths in sorted(scopes.items())]
    container_roots = set()
    for node in chart['entities']:
        evidence = node.get('evidence', [])
        product_evidence = any(item.get('type') in {'owner_declaration', 'package_manifest'} or
            (item.get('type') == 'repository_identity' and item.get('basis') != 'Local path fallback')
            for item in evidence)
        if not product_evidence:
            container_roots.update(item['path'] for item in evidence if item.get('type') == 'repository_identity'
                and item.get('basis') == 'Local path fallback' and item.get('path'))
    page = ordered[int(offset):int(offset) + SOURCE_PAGE]
    if page:
        result = _run(dict(source_cache=str(Path(source_cache).expanduser().resolve()), scopes=page,
                          query=query, limit=int(limit), container_roots=sorted(container_roots)), float(seconds))
    else:
        result = dict(schema_version=VERSION, families=[], references=[], evidence=[], coverage=[],
                      published=None, cached=True, harvest_invocations=0)
    for family in result['families']:
        root = result['source_roots'][family['source_id']]
        for member in family['members']:
            member['source_id'] = family['source_id']
            path = str(Path(root) / member['path'])
            member['destination_ids'] = sorted(node['id'] for node in chart['entities']
                if any(location.get('path') == path for location in node.get('locations', [])))
            search_command = ['navcom', 'sources', 'search', query or member['label'], '--within', family['source_id']]
            for scope in member['scope_paths']:
                search_command += ['--path', scope]
            member['search_command'] = shlex.join(search_command + ['--mode', 'both', '--cache', str(source_cache)])
            if member.get('document'):
                member['source_ref'] = dict(source_id=family['source_id'], relative_path=member['document'],
                    line=1, snapshot=family['source_snapshot'], published=result['published'])
                member['read_command'] = shlex.join(['navcom', 'sources', 'read', family['source_id'], member['document'],
                    '--cache', str(source_cache), '--published', str(result['published']), '--snapshot', family['source_snapshot']])
            for file in member.get('representative_files', []):
                file['source_ref'] = dict(source_id=family['source_id'], relative_path=file['relative_path'],
                    line=1, snapshot=family['source_snapshot'], published=result['published'])
                file['read_command'] = shlex.join(['navcom', 'sources', 'read', family['source_id'], file['relative_path'],
                    '--cache', str(source_cache), '--published', str(result['published']), '--snapshot', family['source_snapshot']])
    for reference in result['references']:
        reference['source_ref'] = dict(source_id=reference['source_id'], relative_path=reference['relative_path'],
            line=reference['line'], snapshot=reference['source_snapshot'], published=result['published'])
        reference['destination_ids'] = sorted(node['id'] for node in chart['entities']
            if any(location.get('path') == reference['target_root'] for location in node.get('locations', [])))
        reference['read_command'] = shlex.join(['navcom', 'sources', 'read', reference['source_id'], reference['path'],
            '--line', str(reference['line']), '--limit', '8', '--cache', str(source_cache),
            '--published', str(result['published']), '--snapshot', reference['source_snapshot']])
    all_families = result['families']
    if query:
        terms = query.casefold().split()
        all_families = [family for family in all_families if all(term in
            ' '.join([family['label'], family['parent_path'], *[member['path'] for member in family['members']]]).casefold()
            for term in terms)]
    family_count, reference_count = len(all_families), len(result['references'])
    result['families'] = all_families[:int(limit)]
    result['references'] = result['references'][:int(limit)]
    result.update(center=selected, query=query, chart_published=chart['published'], source_offset=int(offset), source_total=len(ordered),
        source_page_size=SOURCE_PAGE, next_offset=int(offset) + SOURCE_PAGE if int(offset) + SOURCE_PAGE < len(ordered) else None,
        result_limits=dict(families=family_count, references=reference_count, limit=int(limit),
                           truncated=family_count > int(limit) or reference_count > int(limit)),
        meaning='Retained source evidence only. Families are suggestions, references are literal, and neither changes the chart or establishes historical succession.')
    command = ['navcom', 'atlas', 'related', selected['id'], '--space-cache', str(space_cache),
               '--source-cache', str(source_cache), '--limit', str(limit), '--seconds', str(seconds)]
    if query: command += ['--query', query]
    if offset: command += ['--offset', str(offset)]
    result['cli_command'] = shlex.join(command)
    if result['next_offset'] is not None:
        if '--offset' in command: command[command.index('--offset') + 1] = str(result['next_offset'])
        else: command += ['--offset', str(result['next_offset'])]
        result['continue_command'] = shlex.join(command)
    return result


def render(data):
    print(data['center']['label'] + ' — related source evidence')
    for family in data['families']:
        print('\nSuggested version family: ' + family['label'])
        for member in family['members']:
            print('  ' + member['label'] + ' · ' + str(member['retained_files']) + ' retained files · ' + member['path'])
            print('    ' + member['search_command'])
    for reference in data['references']:
        print('\nDocumented reference: ' + reference['target_root'])
        print('  ' + reference['path'] + ':' + str(reference['line']) + ' — ' + reference['excerpt'])
        print('  ' + reference['read_command'])
    query_hits = 0
    for evidence in data.get('evidence', []):
        concepts, text = evidence.get('concept_hits', []), evidence.get('text_hits', [])
        query_hits += len(concepts) + len(text)
        print('\nSource query: ' + evidence['source_id'] + ' · ' + str(len(concepts)) + ' concept matches · ' + str(len(text)) + ' text matches')
        for label, hits in [('concept', concepts), ('text', text)]:
            for hit in hits[:5]:
                location = hit.get('relative_path', '')
                if hit.get('line') is not None:
                    location += ':' + str(hit['line'])
                print('  ' + label + ' · ' + location)
        if len(concepts) > 5 or len(text) > 5 or evidence.get('potentially_truncated'):
            print('  Bounded match preview; full returned evidence: ' + data['cli_command'] + ' --json')
    if not data['families'] and not data['references'] and not query_hits:
        print('No relationships found in the selected retained source scopes.')
    print('\n' + data['meaning'])
    if data.get('result_limits', {}).get('truncated'):
        print('Relationship result limit reached; use --limit up to 100 to see more returned evidence.')
    if data['next_offset'] is not None:
        print('More source scopes remain: ' + data['continue_command'])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('place')
    parser.add_argument('--space-cache', type=Path, required=True)
    parser.add_argument('--source-cache', type=Path, required=True)
    parser.add_argument('--query', default='')
    parser.add_argument('--limit', type=int, default=20)
    parser.add_argument('--seconds', type=float, default=15)
    parser.add_argument('--offset', type=int, default=0)
    parser.add_argument('--json', action='store_true')
    args = parser.parse_args(argv)
    try:
        result = related(args.space_cache, args.source_cache, args.place, query=args.query,
                         limit=args.limit, seconds=args.seconds, offset=args.offset)
        print(json.dumps(result, indent=2)) if args.json else render(result)
        return 0
    except (OSError, ValueError, TimeoutError) as exc:
        print('navcom: ' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
