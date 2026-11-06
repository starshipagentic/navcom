"""Bounded, attributed context for one saved place; never scans a live project.

This is a context seed, not a new search engine or a statement of current runtime.
Questions retain the native search results; optional synthesis consumes only the
same cited evidence returned to the CLI and browser.
"""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shlex
import sqlite3
import time

MAX_CONVERSATIONS = 3
MAX_EVIDENCE = 14
MAX_TEXT = 800
MAX_TOTAL_TEXT = 8000
MAX_SOURCES = 4
MAX_DOCUMENTS = 2
MAX_DOCUMENT_ATTEMPTS = 12
MAX_DOCUMENT_BYTES = 256 * 1024
DOCUMENT_NAMES = ('README.md', 'readme.md', 'README.rst', 'README.txt', 'package.json', 'pyproject.toml')


def _inside(path, scopes):
    return any(scope == PurePosixPath('.') or path == scope or scope in path.parents for scope in scopes)


def _scopes(node):
    result = {}
    for scope in node.get('source_scopes', []):
        paths = scope.get('paths')
        if not isinstance(paths, list) or not paths:
            raise ValueError('Missing saved file scope; refresh geography before reading this place.')
        for value in paths:
            if not isinstance(value, str) or not value or '\x00' in value or '\\' in value:
                raise ValueError('Invalid saved file scope.')
            path = PurePosixPath(value)
            if path.is_absolute() or '..' in path.parts:
                raise ValueError('Saved file scope must stay inside its published source.')
            result.setdefault(scope['source_id'], set()).add(path)
    return result


def _document_evidence(node, source_cache, add, coverage):
    """Try declared retained document names; never walk a source directory."""
    from navcom_source_reader import _json, _open, _source_record, read_source
    from navcom_space import _minimal_paths
    scopes = _scopes(node)
    coverage['source_scopes'] = len(scopes)
    if not scopes:
        coverage['limitations'].append('No harvested source is associated with this place; saved conversations may still describe it.')
        return
    alias = Path(source_cache).expanduser().absolute()
    cache = alias.resolve()
    fd = os.open(cache, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    attempts = found = available = 0
    seen_files = set()
    deadline = time.monotonic() + 3
    try:
        state = _json(fd, 'current.json')
        for sid, paths in sorted(scopes.items())[:MAX_SOURCES]:
            try:
                source, recorded, _root, snapshot, published = _source_record(fd, cache, alias, sid, state=state)
                allowed = [PurePosixPath(p) for p in recorded.get('include', [])]
                paths = {PurePosixPath(p) for p in _minimal_paths(str(path) for path in paths)}
                retained = {path for path in paths if _inside(path, allowed) or any(path in value.parents for value in allowed)}
                if not allowed or not retained:
                    raise ValueError('Saved scope is outside the retained harvest.')
                if retained != paths:
                    coverage['limitations'].append('Some saved source paths have no overlap with the retained harvest: '+sid)
                paths = retained
                available += 1
                # Existing explicit include paths are already the harvest's inventory.
                # Broad directory includes try a fixed document-name list only.
                candidates = {p for p in allowed if p.name in DOCUMENT_NAMES and _inside(p, paths)}
                for path in sorted(paths, key=str):
                    if path.name in DOCUMENT_NAMES:
                        candidates.add(path)
                    elif not path.suffix:
                        candidates.update(path / name for name in DOCUMENT_NAMES)
                candidates = [p for p in candidates if _inside(p, paths) and _inside(p, allowed)]
                candidates.sort(key=lambda p: (p.name not in DOCUMENT_NAMES[:4], len(p.parts), str(p)))
                for path in candidates:
                    if attempts >= MAX_DOCUMENT_ATTEMPTS or found >= MAX_DOCUMENTS or time.monotonic() > deadline:
                        break
                    attempts += 1
                    try:
                        with _open(fd, 'artifacts/'+snapshot+'/source/'+str(path)) as document_fd:
                            metadata = os.fstat(document_fd)
                            file_identity = (metadata.st_dev, metadata.st_ino)
                            if file_identity in seen_files:
                                continue
                            if metadata.st_size > MAX_DOCUMENT_BYTES:
                                coverage['limitations'].append('A retained document exceeded the 256 KiB briefing input bound: '+str(path))
                                continue
                        doc = read_source(sid, str(path), line=1, limit=30, cache_path=cache,
                                          snapshot=snapshot, published=published)
                    except (ValueError, OSError):
                        continue
                    content = '\n'.join(row['text'] for row in doc['lines']).strip()
                    if not content:
                        continue
                    seen_files.add(file_identity)
                    ref = dict(source_id=sid, relative_path=str(path), line=1,
                               snapshot=doc['snapshot'], published=doc['published'])
                    add('source', str(path), content, source_ref=ref,
                        open_command=doc['cli_command'],
                        basis='harvested_readme' if path.name in DOCUMENT_NAMES[:4] and (path.parent in paths or path in paths) else 'retained_document',
                        temporal_basis='Retained harvested document; current files were not read.')
                    found += 1
            except (ValueError, OSError):
                coverage['limitations'].append('A saved source is unavailable or its published receipt no longer matches: '+sid)
        coverage.update(source_available=bool(available), retained_documents=found)
        if len(scopes) > MAX_SOURCES or attempts >= MAX_DOCUMENT_ATTEMPTS or time.monotonic() > deadline:
            coverage['limitations'].append('Document context reached its bounded source/name sampling limit.')
    finally:
        os.close(fd)


def _conversations(api, conn, node, add, coverage, retrieval, atlas_context):
    from navcom_discovery import Discovery
    collections = set(node.get('conversation_collections', []))
    if not collections:
        return
    if api is None or conn is None:
        coverage['limitations'].append('Conversation index is unavailable.')
        return
    deadline = time.monotonic() + 5
    conn.set_progress_handler(lambda: int(time.monotonic() > deadline), 10000)
    try:
        with atlas_context(api, conn, deadline) as atlas:
            discovery = Discovery(api)
            discovery.atlas = atlas
            records = atlas.catalog(conn)
            registry, cache = discovery.registry(conn, records)
            eligible = set()
            for cid in sorted(collections):
                if cid not in registry:
                    coverage['limitations'].append('Saved conversation collection is no longer indexed: '+cid)
                    continue
                group = registry[cid]
                eligible.update(group['keys'] & set(discovery.hits(conn, records, group, cache)))
            coverage['indexed_conversations'] = len(eligible)
            ordered = sorted(eligible, key=lambda key: (bool(records[key]['parent_id']), -records[key]['mtime'], key))
            matches = []
            for hit in (retrieval or {}).get('conversations', []):
                key = hit.get('open_key') or hit.get('evidence_key') or hit.get('key')
                if key in eligible and key not in matches:
                    matches.append(key)
            selected = (matches + [key for key in ordered if key not in matches])[:MAX_CONVERSATIONS]
            coverage['selected_conversations'] = len(selected)
            snippets = []
            for hit in (retrieval or {}).get('conversations', []):
                key = hit.get('open_key') or hit.get('evidence_key') or hit.get('key')
                turn = hit.get('start')
                if key not in selected or not isinstance(turn, int) or isinstance(turn, bool) or turn < 1:
                    continue
                row = conn.execute("SELECT l.msg_index,f.role,substr(f.text,1,?) FROM turn_loc l "
                    "JOIN session_fts f ON f.rowid=l.rid WHERE l.file=? AND l.msg_index=? "
                    "AND f.role IN ('user','assistant') LIMIT 1",(MAX_TEXT,key,turn)).fetchone()
                if row and row[2].strip(): snippets.append((0,key,records[key],row))
            # Same indexed turn schema as fetch_window_rows, with SQL substr and
            # LIMIT so a huge tool/transcript row never enters the context pack.
            for key in selected:
                record = records[key]
                for role, order in [('assistant', 'DESC'), ('user', 'ASC')]:
                    row = conn.execute("SELECT l.msg_index,f.role,substr(f.text,1,?) FROM turn_loc l "
                        "JOIN session_fts f ON f.rowid=l.rid WHERE l.file=? AND f.role=? "
                        "ORDER BY l.msg_index "+order+" LIMIT 1", (MAX_TEXT, key, role)).fetchone()
                    if row and row[2].strip():
                        snippets.append((1 if role=='assistant' else 2, key, record, row))
            # Give each selected session's outcome a chance before boilerplate
            # first requests; the content itself is never scored or reclassified.
            excerpted = set()
            for _priority, key, record, row in sorted(snippets, key=lambda value: value[0]):
                role=row[1]
                excerpted.add(key)
                command = ['navcom','--open',api.session_ref(key)+':'+str(row[0]),'--window-turns','0']
                db = conn.execute('PRAGMA database_list').fetchone()[2]
                if db: command += ['--index',db]
                add('conversation', record['title'], row[2],
                    retrieved=_priority==0,
                    conversation_ref=dict(key=key, ref=api.session_ref(key), turn=row[0], project=record['project']),
                    open_command=shlex.join(command),role=role,
                    temporal_basis='Indexed '+role+' statement; not current code or runtime verification.')
            coverage['excerpted_conversations'] = len(excerpted)
            if len(eligible) > len(selected):
                coverage['limitations'].append('Conversation context samples '+str(len(selected))+' of '+str(len(eligible))+' exact-scope records.')
            if node.get('conversation_basis'):
                coverage['conversation_basis'] = node['conversation_basis']
                coverage['limitations'].append('These conversations are related through the recorded project collection; file-level relevance is unproven.')
    finally:
        conn.set_progress_handler(None, 0)


def briefing(api, conn, *, center, catalog_published, source_cache, retrieval=None, atlas_context=None):
    """Return a bounded context seed for exactly one supplied saved destination."""
    evidence = []
    retrieved_evidence = []
    used = 0
    seen = set()
    coverage = dict(source_scopes=len(center.get('source_scopes', [])), source_available=False,
                    indexed_conversations=0, selected_conversations=0, excerpted_conversations=0,
                    current_location_available=any(location.get('available') is True for location in center.get('locations', [])),
                    complete=False, limitations=[], current_files_read=False, harvest_invocations=0)
    def add(kind, label, text, *, retrieved=False, **refs):
        nonlocal used
        if not isinstance(text, str) or not text.strip() or len(evidence) >= MAX_EVIDENCE or used >= MAX_TOTAL_TEXT:
            return
        text = text.strip()[:min(MAX_TEXT, MAX_TOTAL_TEXT-used)]
        key = hashlib.sha256(json.dumps([kind, text, refs], sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
        if key in seen:
            return
        seen.add(key)
        evidence.append(dict(id='E'+key, kind=kind, label=str(label)[:180], text=text, **refs))
        if retrieved:
            retrieved_evidence.append(evidence[-1])
        used += len(text)
    from navcom_space import _clean_clue, _description_priority
    description = center.get('description', '')
    if description:
        author = max((clue for clue in center.get('clues', []) if clue.get('text')==description),
                     key=_description_priority,default={})
        add('description', center['label'], description,
            basis=author.get('basis','recorded_metadata'),
            temporal_basis='Saved place description; not a current runtime check.')
    for clue in center.get('clues', [])[:3]:
        if clue.get('text') != description:
            add('description', center['label'], clue.get('text', ''),
                basis=clue.get('basis','recorded_metadata'),
                temporal_basis='Saved '+str(clue.get('basis', 'place clue'))+'; not a current runtime check.')
    scopes = {}
    try:
        scopes = _scopes(center)
    except ValueError as exc:
        coverage['limitations'].append(str(exc))
    # Retain only native source hits inside this exact destination's paths.
    for source in (retrieval or {}).get('sources', []):
        sid = source.get('source_id')
        if sid not in scopes:
            continue
        for field in ('concept_hits', 'text_hits'):
            for hit in source.get(field, [])[:4]:
                ref = hit.get('source_ref')
                path = hit.get('relative_path')
                if not isinstance(ref, dict) or not isinstance(path, str) or '..' in PurePosixPath(path).parts or PurePosixPath(path).is_absolute():
                    continue
                if ref.get('source_id') != sid or ref.get('relative_path') != path or not _inside(PurePosixPath(path), scopes[sid]):
                    continue
                add('source', path, hit.get('match') or hit.get('description') or hit.get('name') or '',
                    retrieved=True,
                    source_ref=ref, open_command=shlex.join(['navcom','sources','read',sid,path,'--line',str(ref.get('line',1)),
                        '--snapshot',str(ref.get('snapshot','')),'--cache',str(source_cache)]),
                    temporal_basis='Native Starforge '+field+' from the retained source snapshot.')
    try:
        _document_evidence(center, source_cache, add, coverage)
    except (OSError, ValueError) as exc:
        coverage['limitations'].append('Retained document context is unavailable: '+str(exc))
    # Optional README sampling can be partial or fail independently of the
    # already admitted, exact-scope native source excerpts in this response.
    coverage['source_available'] = coverage['source_available'] or any(item['kind']=='source' for item in evidence)
    if atlas_context is None:
        from navcom_navigation import _conversation_atlas
        atlas_context = _conversation_atlas
    try:
        _conversations(api, conn, center, add, coverage, retrieval, atlas_context)
    except (ValueError, sqlite3.Error) as exc:
        coverage['limitations'].append('Scoped conversation context is unavailable: '+str(exc))
    if not coverage['current_location_available']:
        coverage['limitations'].append('The recorded project location is unavailable or unverified; saved evidence does not verify its current state.')
    if retrieval is not None:
        coverage['retrieval_complete'] = bool(retrieval.get('coverage', {}).get('complete'))
        if not coverage['retrieval_complete']:
            coverage['limitations'].append('Native question retrieval is partial; inspect its coverage and errors for unsearched inputs.')
    if used >= MAX_TOTAL_TEXT or len(evidence) >= MAX_EVIDENCE:
        coverage['limitations'].append('Context excerpts reached their size/count bound.')
    # The fallback is an attributed excerpt, never a fabricated answer.
    # A question keeps native match order. Generic metadata and sampled README
    # context remain available, but must not displace an admitted query match.
    question = (retrieval or {}).get('query_plan', {}).get('style') == 'question'
    authored = [item for item in evidence if _description_priority(item)>0]
    summary_item = retrieved_evidence[0] if question and retrieved_evidence else None
    summary_item = summary_item or max(authored,key=_description_priority,default=None)
    summary_item = summary_item or next((item for item in evidence if item['kind'] in ('source','conversation')), None)
    summary = dict(text=_clean_clue(api,summary_item['text'],280) if summary_item else 'The retained metadata does not establish what this place does. Open its available evidence or restore its source context.',
                   basis='attributed_excerpts' if summary_item and summary_item['kind']!='description' else 'recorded_description' if summary_item else 'unavailable',
                   evidence_ids=[summary_item['id']] if summary_item else [])
    coverage['complete'] = not coverage['limitations']
    return dict(schema_version=1, place={key:center[key] for key in ('id','label','kind')},
                catalog_published=catalog_published, summary=summary, evidence=evidence, coverage=coverage)
