"""Published product declarations, native suggestions and document references.

Native analysis runs against immutable harvest snapshots and does not establish
product succession. Explicit supersession is read separately from the chart;
it records current declarations, never a reconstructed historical fact.
"""
from collections import defaultdict
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import time
from urllib.parse import unquote

VERSION = 1
SOURCE_PAGE = 8
MAX_FILES = 20000
MAX_DIRECTORIES = 2000
MAX_GROUPS = 128
MAX_OUTPUT = 4 * 1024 * 1024
MAX_REPOSITORIES = 2000
URL_TOKEN = re.compile(r"(?:https?|ssh|git)://[^\s<>\[\](){}\"'`]+|git@[^\s<>\[\](){}\"'`]+", re.I)


def _repository_targets(chart):
    """Use recorded Git identities, not manifest names or guessed hosting paths."""
    from navcom_space import sanitize_origin
    targets = {}
    for node in chart['entities']:
        if node.get('kind') not in ('planet', 'moon'):
            continue
        for evidence in node.get('evidence', []):
            value, root = evidence.get('origin'), evidence.get('path')
            if evidence.get('type') != 'repository_identity' or not isinstance(value, str) or not isinstance(root, str):
                continue
            # Saved origins are already canonical host/path identities. Local
            # remotes remain covered by the existing literal-path references.
            if value.startswith('file:') or len(value) > 4096 or len(root) > 4096 or not Path(root).is_absolute():
                continue
            try:
                origin = sanitize_origin('https://' + value)
            except ValueError:
                continue
            if origin != value or '/' not in origin or any(part in ('.', '..') for part in origin.split('/')):
                continue
            key = (origin, node['id'])
            row = dict(origin=origin, root=root, destination_id=node['id'])
            if key not in targets or root < targets[key]['root']:
                targets[key] = row
    return sorted(targets.values(), key=lambda row: (row['origin'], row['destination_id']))


def _repository_pattern(targets):
    patterns = []
    for origin in sorted({row['origin'] for row in targets}, key=lambda value: (-len(value), value)):
        host, path = origin.split('/', 1)
        # URL remotes may carry an explicit numeric port; SCP-style Git
        # addresses still use the single colon immediately before the path.
        patterns.append(r'(?i:' + re.escape(host) + r')(?::[0-9]+)?[/:]' + re.escape(path) +
                        r'(?:\.git)?(?=$|[/#?\s<>\[\](){}\"\x27`,;.])')
    return '|'.join(patterns)


def _repository_matches(text, targets):
    """Validate complete URL tokens; never emit credentials/query values."""
    from navcom_space import sanitize_origin
    origins = sorted({row['origin'] for row in targets}, key=lambda value: (-len(value), value))
    seen = set()
    for token in URL_TOKEN.findall(text):
        try:
            canonical = sanitize_origin(token.rstrip('.,;'))
        except ValueError:
            continue
        if any(part in ('.', '..') for part in unquote(canonical).split('/')):
            continue
        for origin in origins:
            if canonical not in (origin, origin + '.git') and not canonical.startswith((origin + '/', origin + '.git/')):
                continue
            # A nested known origin wins over an enclosing address. The whole
            # canonical URL remains evidence, never a declaration of ancestry.
            key = (origin, canonical)
            if key not in seen:
                seen.add(key)
                yield origin, canonical
            break


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
    repository_targets = request.get('repository_targets', [])
    repository_pattern = _repository_pattern(repository_targets) if len(repository_targets) <= MAX_REPOSITORIES else ''
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
        inspected['repository_reference_targets'] = len(repository_targets)
        if len(repository_targets) > MAX_REPOSITORIES:
            inspected['omitted'].append('Known repository identities exceeded the 2000-target reference budget.')
        if repository_pattern and len(repository_pattern) <= 32768:
            hits = native.combined_search(dict(query=repository_pattern, regex=True, ext='md', mode='text',
                within=source['id'], paths=paths, limit=100), cache, state=state, extractor=engine)
            inspected['repository_reference_hits_truncated'] = hits['potentially_truncated']
            for hit in hits['text_hits']:
                for origin, url in _repository_matches(hit['match'], repository_targets):
                    for target in repository_targets:
                        if target['origin'] != origin or target['root'] == source['root']:
                            continue
                        references.append(dict(kind='documented_repository_reference', source_id=source['id'],
                            source_snapshot=Path(source['artifact']).name,
                            path=hit['relative_path'], relative_path=hit['relative_path'], line=hit['line'],
                            excerpt=url, excerpt_kind='canonical_repository_url', target_origin=origin,
                            target_source_id=next(iter(root_targets.get(target['root'], [])), None),
                            target_root=target['root'], destination_ids=[target['destination_id']],
                            engine='starforge code-search',
                            meaning='This retained document links to the recorded Git repository address; no shared product identity, current synchronization, ancestry or succession is inferred.'))
        elif repository_pattern:
            inspected['omitted'].append('Known-repository URL pattern exceeded 32768 characters.')
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


def _declared_relations(chart, selected, space_cache, source_cache):
    """Project exact authored edges; do not inherit a root claim in its apps."""
    from navcom_space import subtree
    nodes = {node['id']: node for node in chart['entities']}
    inside = subtree(nodes.values(), selected['id'])

    def endpoint(identity):
        node = nodes[identity]
        command = ['navcom', 'atlas', 'show', identity, '--space-cache', str(space_cache),
                   '--source-cache', str(source_cache)]
        return dict(id=identity, label=node['label'], declared_id=node.get('declared_id'),
                    show_command=shlex.join(command))

    result = []
    for edge in chart.get('edges', []):
        if (edge.get('relation') != 'supersedes' or edge.get('status') != 'declared'
                or edge.get('source') not in nodes or edge.get('target') not in nodes
                or not inside.intersection((edge['source'], edge['target']))):
            continue
        result.append(dict(kind='declared_supersession', status='declared',
            successor=endpoint(edge['source']), predecessor=endpoint(edge['target']),
            evidence=edge.get('evidence', {}),
            meaning='Current recorded declaration. No replacement date, deployment state or historical ownership is inferred.'))
    result.sort(key=lambda item: (item['successor']['label'].casefold(), item['predecessor']['label'].casefold(),
                                  item['successor']['id'], item['predecessor']['id']))
    return result


def related(space_cache, source_cache, within, *, query='', limit=20, seconds=15, offset=0):
    import navcom_space as space
    space_cache = Path(space_cache).expanduser().resolve()
    source_cache = Path(source_cache).expanduser().resolve()
    if not isinstance(query, str) or len(query) > 500:
        raise ValueError('Query must be text of at most 500 characters.')
    if not 1 <= int(limit) <= 100 or not 1 <= float(seconds) <= 30 or int(offset) < 0:
        raise ValueError('Use limit 1–100, seconds 1–30 and a nonnegative source offset.')
    chart = space.load_catalog(space_cache)
    selected = space.view(space_cache, action='show', within=within, catalog=chart)['center']
    declared = _declared_relations(chart, selected, space_cache, source_cache)
    inside = space.subtree(chart['entities'], selected['id'])
    declared_ids = {node['declared_id'] for node in chart['entities']
                    if node['id'] in inside and node.get('declared_id')}
    declaration_paths = {item['path'] for node in chart['entities'] if node['id'] in inside
                         for item in node.get('evidence', [])
                         if item.get('type') == 'owner_declaration' and item.get('path')}
    diagnostics = [item for item in chart.get('coverage', {}).get('product_succession', {}).get('diagnostics', [])
                   if selected['id'] == space.GALAXY or item.get('declared_id') in declared_ids
                   or item.get('target_declared_id') in declared_ids
                   or declaration_paths.intersection(item.get('paths', []))]
    if query:
        terms = query.casefold().split()
        declared = [item for item in declared if all(term in ' '.join(
            str(item[side].get(field) or '') for side in ('successor', 'predecessor')
            for field in ('label', 'declared_id')).casefold() for term in terms)]
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
    repository_targets = _repository_targets(chart)
    source_errors = []
    result = dict(schema_version=VERSION, families=[], references=[], evidence=[], coverage=[],
                  published=None, cached=True, harvest_invocations=0)
    if page:
        try:
            result = _run(dict(source_cache=str(Path(source_cache).expanduser().resolve()), scopes=page,
                              query=query, limit=int(limit), container_roots=sorted(container_roots),
                              repository_targets=repository_targets), float(seconds))
        except (ValueError, TimeoutError, OSError) as exc:
            if not declared and not diagnostics:
                raise
            source_errors.append(str(exc))
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
        if reference['kind'] != 'documented_repository_reference':
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
        declared_relations=declared[:int(limit)],
        declaration_diagnostics=diagnostics, source_errors=source_errors,
        result_limits=dict(families=family_count, references=reference_count, declared_relations=len(declared), limit=int(limit),
                           truncated=family_count > int(limit) or reference_count > int(limit) or len(declared) > int(limit)),
        meaning='Explicit product declarations are separate from native evidence. Families are suggestions, references are literal, and neither changes the chart or establishes historical succession. Current declarations do not establish past ownership or replacement dates.')
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
