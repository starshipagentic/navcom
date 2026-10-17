"""Shared navigation orchestration. Geography and source matching have one CLI/web contract."""
import json
import os
import re
from collections import OrderedDict
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
import shlex
import sqlite3
import subprocess
import threading
import time

# Browser requests use separate SQLite connections, but can reuse Atlas's existing
# short-lived metadata catalog. Keep only four indexes in memory, never on disk.
_ATLAS_POOL = OrderedDict()
_ATLAS_POOL_LOCK = threading.Lock()
_ATLAS_POOL_LIMIT = 4


class _ConversationConnection(sqlite3.Connection):
    """A newly opened connection with observed pathname provenance."""


def conversation_connection(index_path, *, timeout=.3):
    """Open once for a web request; unknown or replaced handles never share Atlas."""
    path=Path(index_path).resolve()
    def identity():
        try:
            stat=path.stat()
            return (str(path),stat.st_dev,stat.st_ino)
        except OSError:
            return None
    before=identity()
    conn=sqlite3.connect(str(path),timeout=timeout,factory=_ConversationConnection)
    after=identity()
    conn._atlas_open_identity=before if before is not None and before==after else None
    return conn


def _atlas_entry(api, conn):
    from navcom_atlas import Atlas
    db = next((row[2] for row in conn.execute('PRAGMA database_list') if row[1] == 'main'), '')
    # Temporary stand-ins and uncommitted data belong to this connection only.
    opened=getattr(conn,'_atlas_open_identity',None)
    if not opened or not db or conn.in_transaction or conn.execute('SELECT 1 FROM sqlite_temp_master LIMIT 1').fetchone():
        return Atlas(api), threading.Lock()
    path = Path(db).resolve()
    try:
        stat = path.stat()
    except OSError:
        return Atlas(api), threading.Lock()
    current=(str(path),stat.st_dev,stat.st_ino)
    if opened!=current:
        return Atlas(api), threading.Lock()
    key = (id(api), *opened)
    with _ATLAS_POOL_LOCK:
        entry = _ATLAS_POOL.pop(key, None)
        if entry is None:
            entry = Atlas(api), threading.Lock()
        _ATLAS_POOL[key] = entry
        while len(_ATLAS_POOL) > _ATLAS_POOL_LIMIT:
            _ATLAS_POOL.popitem(last=False)
        return entry


@contextmanager
def _conversation_atlas(api, conn, deadline):
    atlas, guard = _atlas_entry(api, conn)
    if not guard.acquire(timeout=max(0, deadline-time.monotonic())):
        raise ValueError('Conversation metadata is busy; retry this search.')
    started = False
    try:
        # Hold the entire Discovery use, not only catalog(): signature, trail
        # hits and fleet date must stay on this request's catalog generation.
        atlas._read_generation=atlas.database_generation(conn)
        if not conn.in_transaction:
            conn.execute('BEGIN')
            started = True
        yield atlas
    finally:
        try:
            if started:
                conn.rollback()
        finally:
            atlas.__dict__.pop('_read_generation',None)
            guard.release()


def paths(index, space=None, sources=None):
    """The chart and source caches beside an index; explicit paths, then env, win."""
    return (Path(space or os.environ.get('NAVCOM_SPACE_CACHE', str(index)+'.space.json')).expanduser(),
            Path(sources or os.environ.get('NAVCOM_SOURCES_CACHE',str(Path(index).parent/'navcom-sources'))).expanduser())


def history_cache(index):
    """The historical snapshot cache: NAVCOM_HISTORY_CACHE, else beside the index."""
    return Path(os.environ.get('NAVCOM_HISTORY_CACHE', str(Path(index).parent/'navcom-history')))


def context(space_cache, within, *, action='inspect', query='', ref='', turn=None, offset=0, limit=10, max_chars=2000, expected_catalog=''):
    import navcom_space
    import navcom_ship_context
    node=navcom_space.view(space_cache,action='show',within=within)['center']
    if node['kind']!='ship':raise ValueError('Choose a ship to read its carried context.')
    if action=='inspect':result=navcom_ship_context.inspect_context(node,offset=offset,limit=limit,expected_catalog=expected_catalog)
    else:result=navcom_ship_context.read_context(node,action=action,query=query,ref=ref,turn=turn,offset=offset,limit=limit,max_chars=max_chars,expected_catalog=expected_catalog)
    command=['navcom','atlas','context',node['id'],'--space-cache',str(space_cache),'--offset',str(offset),'--limit',str(limit),'--max-chars',str(max_chars)]
    if action=='search':command+=['--query',query]
    elif action=='open':command+=['--session',ref]
    elif action=='handover':command+=['--handover']
    if turn is not None:command+=['--turn',str(turn)]
    catalog=result.get('provenance',{}).get('catalog_sha256') or expected_catalog
    if catalog:command+=['--catalog',catalog]
    result['catalog']=catalog
    result['cli_command']=shlex.join(command)
    if result.get('next_offset') is not None:
        following=list(command);following[following.index('--offset')+1]=str(result['next_offset'])
        result['continue_command']=shlex.join(following)
    for message in result.get('messages',[]):
        opening=['navcom','atlas','context',node['id'],'--space-cache',str(space_cache),'--session',message['id'],
                 '--turn',str(message['index']),'--max-chars',str(max_chars),'--catalog',catalog]
        message['open_command']=shlex.join(opening)
    return result


def _place_evidence(api, nodes, result, selected=None):
    """Retain exact saved product path memberships after federated retrieval."""
    from navcom_atlas import identity
    places=[n for n in nodes if n['kind'] in ('planet','moon')]
    if not places and selected and selected['kind']=='district':places=[selected]
    groups={n['id']:dict(id=n['id'],kind=n['kind'],label=n['label'],
        source_refs=[],conversation_refs=[],concept_hits=0,text_hits=0,conversation_hits=0,
        source_scope_count=len(n.get('source_scopes',[]))) for n in places}
    sources={source['source_id']:source for source in result['sources']}
    unassigned=0
    for sid,source in sources.items():
        for field in ('concept_hits','text_hits'):
            for index,hit in enumerate(source.get(field,[])):
                relative=hit.get('relative_path')
                memberships=[]
                if relative and not PurePosixPath(relative).is_absolute() and '..' not in PurePosixPath(relative).parts:
                    path=PurePosixPath(relative)
                    memberships=[n for n in places if any(scope.get('source_id')==sid and
                        any(value=='.' or path==PurePosixPath(value) or PurePosixPath(value) in path.parents
                            for value in scope.get('paths',[])) for scope in n.get('source_scopes',[]))]
                hit['place_ids']=[n['id'] for n in memberships]
                hit['place_labels']=[n['label'] for n in memberships]
                hit['place_basis']='Saved current source paths; overlapping memberships remain explicit.'
                if not memberships:unassigned+=1
                for node in memberships:
                    group=groups[node['id']]
                    group[field]+=1
                    group['source_refs'].append(dict(source_id=sid,path=relative,line=hit.get('line'),
                                                     engine=field,index=index,shared=len(memberships)>1))
    for index,hit in enumerate(result['conversations']):
        project=hit.get('project')
        collection='projects:'+identity(api.pretty_project(project)) if api and project else None
        memberships=[n for n in places if collection in n.get('conversation_collections',[])]
        hit['place_ids']=[n['id'] for n in memberships]
        hit['place_labels']=[n['label'] for n in memberships]
        for node in memberships:
            groups[node['id']]['conversation_hits']+=1
            groups[node['id']]['conversation_refs'].append(dict(key=hit.get('key'),index=index,shared=len(memberships)>1))
    for node in places:
        group=groups[node['id']]
        expected={scope['source_id'] for scope in node.get('source_scopes',[])}
        group['source_complete']=bool(expected) and all(sid in sources and not sources[sid].get('potentially_truncated') for sid in expected)
        group['has_evidence']=bool(group['source_refs'] or group['conversation_refs'])
        group['state']='evidence_found' if group['has_evidence'] else 'no_matches_in_scanned_source_scope' if group['source_complete'] else 'coverage_unknown'
    result['places']=sorted(groups.values(),key=lambda n:(not n['has_evidence'],n['label'].casefold(),n['id']))
    result['coverage']['source_hits_without_place_membership']=unassigned
    result['coverage']['place_membership_complete']=not places or not unassigned
    result['place_policy']='Evidence grouped by current saved product paths and project conversation memberships. Matches are clues, not proof of implementation or equivalent behavior. No matches is not proof of absence.'


def _carried_candidates(entities, nodes, selected):
    """Select native physical copies without inferring ownership from a match."""
    if selected['kind'] == 'ship':
        return [selected]
    by_id = {node['id']: node for node in entities}
    chosen = {node['id'] for node in nodes if node['kind'] == 'ship'}
    associated = set()
    for node in nodes:
        if node['kind'] not in ('planet', 'moon'):
            continue
        associated.update(link['id'] for link in node.get('ship_links', [])
                          if link.get('relation') == 'source_context'
                          and by_id.get(link.get('id'), {}).get('kind') == 'ship')
    chosen.update(associated)
    # A recorded source association may also have a separate stored copy. This
    # one hop never travels back through a ship to another product or client.
    for identity in associated:
        chosen.update(link['id'] for link in by_id[identity].get('ship_links', [])
                      if link.get('relation') == 'stored_copy'
                      and by_id.get(link.get('id'), {}).get('kind') == 'ship'
                      and by_id[link['id']].get('form') == 'archive')
    return [by_id[identity] for identity in sorted(chosen)]


def evidence(api, conn, space_cache, source_cache, within, query, limit=12, *, query_style='literal', catalog=None):
    """Fan out existing search engines within the saved place; never infer ownership from hits."""
    import navcom_space
    import navcom_sources
    from navcom_discovery import Discovery
    catalog=catalog if catalog is not None else (navcom_space.load_catalog(space_cache) or {})
    selected=navcom_space.view(space_cache,action='show',within=within,catalog=catalog)['center']
    entities=catalog['entities']
    if isinstance(entities,dict):entities=list(entities.values())
    eligible=navcom_space.subtree(entities,selected['id']) if within else {n['id'] for n in entities}
    nodes=[n for n in entities if n['id'] in eligible]
    scopes={};collections=set();missing_scopes=[]
    for node in nodes:
        collections.update(node.get('conversation_collections',[]))
        for scope in node.get('source_scopes',[]):
            if not scope.get('paths'):
                missing_scopes.append('Missing explicit file paths for '+node['label']+'; refresh geography before searching this place.')
                continue
            sid=scope['source_id']; current=scopes.setdefault(sid,set())
            current.update(scope['paths'])
        if node.get('source_ids') and not node.get('source_scopes'):
            missing_scopes.append('Missing saved file scope for '+node['label']+'; refresh geography before searching this place.')
    results=dict(sources=[],conversations=[],errors=missing_scopes,coverage={},
                 query_plan=dict(style=query_style,concept_query=query,text_terms=[],
                                 text_policy='Literal phrase' if query_style=='literal' else 'Native Starforge content terms; any matching term is evidence, not an answer.'))
    if selected and selected.get('conversation_basis'):
        results['conversation_basis']=dict(selected['conversation_basis'],query=query)
    results['coverage']=dict(catalog_published=catalog['published'],source_scopes=len(scopes),searched_source_scopes=0,
                            unsearched_source_ids=sorted(scopes),
                            conversation_collections=len(collections),searched_collections=0,
                            complete=True)
    if scopes:
        try:
            request=dict(action='batch-search',cache=str(Path(source_cache).resolve()),query=query,
                scopes=[dict(source_id=sid,paths=[] if '.' in relative else sorted(relative))
                        for sid,relative in sorted(scopes.items())],
                mode='both',limit=min(limit,50),time_budget_seconds=20)
            if query_style=='question':request['text_mode']='question_terms'
            p=subprocess.run(navcom_sources.worker_argv(),input=json.dumps(request),capture_output=True,text=True,timeout=30)
            if p.returncode:
                results['errors'].append(p.stderr.strip()[-400:] or 'Source search worker failed.')
            else:
                data=json.loads(p.stdout)
                results['sources']=data['sources']
                results['query_plan']['text_terms']=list(dict.fromkeys(term for source in data['sources'] for term in source.get('text_terms',[])))
                results['errors'].extend(str(e['source_id'])+': '+e['error'] for e in data.get('errors',[]))
                results['coverage'].update(data['coverage'])
                if data['coverage'].get('unsearched_source_ids'):
                    results['errors'].append('Source search reached its time budget; unsearched source IDs are listed in coverage.')
        except (OSError,ValueError,subprocess.SubprocessError) as exc:
            results['errors'].append('Source search unavailable: '+str(exc))
    if conn is None and collections:
        results['errors'].append('Conversation index unavailable; source evidence remains searchable.')
    elif collections:
        # Existing Discovery ranks once across the union of eligible memberships.
        # Only the collection adapter changes; its catalog, filters, FTS retrieval,
        # ancestry routing, enrichment and result ranking stay unchanged.
        registered_collections=set()
        class PlaceDiscovery(Discovery):
            def registry(self, connection, records):
                registry, cache=super().registry(connection,records)
                keys=set()
                for collection in sorted(collections):
                    if collection not in registry:
                        results['errors'].append('Conversation collection no longer indexed: '+collection)
                        continue
                    registered_collections.add(collection)
                    group=registry[collection]
                    keys.update(group['keys'] & set(self.hits(connection,records,group,cache)))
                registry['navcom-navigation-scope']=dict(id='navcom-navigation-scope',label='Selected places',
                    grouping='projects',keys=keys,reason='Saved place conversation memberships')
                return registry,cache
        deadline=time.monotonic()+20
        try:
            conn.set_progress_handler(lambda: int(time.monotonic()>deadline),10000)
            with _conversation_atlas(api,conn,deadline) as atlas:
                discovery=PlaceDiscovery(api)
                discovery.atlas=atlas
                data=discovery.view(conn,{'action':['search'],'within':['navcom-navigation-scope'],
                    'q':[query],'limit':[str(min(limit,200))]})
            results['conversations']=data['nodes']
            results['coverage']['searched_collections']=len(registered_collections)
            results['coverage']['conversation_matches']=data.get('total',len(data['nodes']))
            results['coverage']['conversation_results_truncated']=bool(data.get('more'))
            if data.get('more'):results['coverage']['complete']=False
        except (ValueError,sqlite3.Error) as exc:
            results['errors'].append('Conversation search unavailable: '+str(exc))
        finally:
            conn.set_progress_handler(None,0)
    if len(results['conversations'])>limit or results['errors'] or any(r.get('potentially_truncated') for r in results['sources']):results['coverage']['complete']=False
    results['conversations']=results['conversations'][:limit]
    candidates = _carried_candidates(entities, nodes, selected)
    if candidates:
        import navcom_carried_search
        try:
            carried = navcom_carried_search.search(candidates, query, Path(str(space_cache)+'.carried-search'),
                                                   limit=min(limit, 50), max_chars=1200, seconds=10)
        except (OSError, ValueError) as exc:
            results['errors'].append('Carried context search unavailable: '+str(exc))
            carried = dict(hits=[], ships=[], next_ship_ids=[],
                           coverage=dict(complete=False, eligible=len(candidates), searched=0,
                                         unavailable_ids=[], unsearched_ids=[n['id'] for n in candidates]))
        by_id = {node['id']: node for node in candidates}
        for hit in carried['hits']:
            node = by_id[hit['ship_id']]
            hit['ship'] = {key: node[key] for key in ('id','kind','label','form','physical') if key in node}
            opening = ['navcom','atlas','context',node['id'],'--space-cache',str(space_cache),
                       '--session',hit['session_id'],'--turn',str(hit['index']),
                       '--catalog',hit['catalog_sha256'],'--max-chars','8000']
            hit['open_command'] = shlex.join(opening)
        results['carried'] = carried
        results['coverage']['carried'] = carried['coverage']
        results['coverage']['complete'] = results['coverage']['complete'] and carried['coverage']['complete']
    _place_evidence(api,nodes,results,selected)
    return results


def view(api, conn, *, space_cache, source_cache, action='list', kind='', within='', query='',limit=50,offset=0,include_evidence=False,catalog=None):
    import navcom_space
    from navcom_navigation_intent import retrieval_style
    catalog=catalog if catalog is not None else (navcom_space.load_catalog(space_cache) or {})
    result=navcom_space.view(space_cache,action=action,kind=kind,within=within,query=query,limit=limit,offset=offset,catalog=catalog)
    if include_evidence and query:
        # History replay restores a query, not a new command. Classify only its
        # retrieval syntax; never interpret back/home/fly here.
        style=retrieval_style(query) if action=='search' else 'literal'
        result['evidence']=evidence(api,conn,space_cache,source_cache,within,query,limit,query_style=style,catalog=catalog)
    command=['navcom','atlas',action]
    if action=='list':command.append(kind or 'systems')
    elif action in ('explore','show'):command.append(within)
    elif action=='search':command.extend([query,'--space'])
    if within and action in ('list','search'):command+=['--within',within]
    if query and action!='search':command+=['--query',query]
    if include_evidence:command+=['--evidence']
    command+=['--space-cache',str(space_cache),'--source-cache',str(source_cache),'--limit',str(limit)]
    if offset:command+=['--offset',str(offset)]
    db=conn.execute('PRAGMA database_list').fetchone()[2] if conn is not None else ''
    if db:command+=['--index',db]
    result['cli_command']=shlex.join(command)
    _place_commands([result['center'], *result['nodes']],space_cache,source_cache,db)
    return result


def _place_commands(nodes, space_cache, source_cache, db):
    """Every returned place offers the chart's current commands, pinned to these caches."""
    import navcom_space
    for node in {id(node):node for node in nodes}.values():
        node['commands']=navcom_space.commands(node)
        for name,value in node['commands'].items():
            for argv in (value if value and isinstance(value[0],list) else [value]):
                _pin_caches(argv,name,space_cache,source_cache,db)


# The cache options each emitted command accepts (atlas, history and sources parsers);
# everything else takes all three. Conversation collection searches take only --index.
_CACHE_OPTIONS = {('sources','list'):('cache',),('sources','search'):('cache',),
                  ('atlas','context'):('space','index'),('atlas','inspect'):('space','index'),
                  ('atlas','ask'):('space','index'),('atlas','board'):('space','index'),
                  ('history','conversations'):('space','index')}


def _pin_caches(argv, name, space_cache, source_cache, db):
    """Append this chart's caches so a copied command reads the same evidence."""
    if not argv or '--index' in argv or '--space-cache' in argv or '--cache' in argv:return
    accepted=('index',) if name=='conversation_search' else _CACHE_OPTIONS.get(tuple(argv[1:3]),('space','sources','index'))
    if 'cache' in accepted:argv+=['--cache',str(source_cache)]
    if 'space' in accepted:argv+=['--space-cache',str(space_cache)]
    if 'sources' in accepted:argv+=['--source-cache',str(source_cache)]
    if 'index' in accepted and db:argv+=['--index',db]


def inspect(*, space_cache, within, refresh=False, observe=False):
    """One exact destination, with the same read-only dossier for CLI and web."""
    import navcom_space
    import navcom_ship_inspection
    center=navcom_space.view(space_cache,action='show',within=within)['center']
    if center['kind']=='star':
        from navcom_star_inspection import inspect_star
        data=inspect_star(center,Path(str(space_cache)+'.star-inspections'),refresh=refresh,observe_status=observe)
    elif center['kind']=='ship':
        if observe:raise ValueError('--observe checks a star provider process; ship inspection already reports its metadata observation.')
        data=navcom_ship_inspection.inspect_ship(center,Path(str(space_cache)+'.inspections'),refresh=refresh)
    elif center['kind'] in ('planet','moon','district'):
        if observe:raise ValueError('--observe checks a star provider process; use --refresh to recheck code locations.')
        from navcom_place_inspection import inspect_place
        data=inspect_place(center,Path(str(space_cache)+'.place-inspections'),refresh=refresh)
    else:
        raise ValueError('Inspect a product, experiment, district, ship or star; explore a system to choose a destination.')
    command=['navcom','atlas','inspect',center['id'],'--space-cache',str(space_cache)]
    if refresh:command.append('--refresh')
    if observe:command.append('--observe')
    return dict(schema_version=1,center=center,inspection=data,cli_command=shlex.join(command))


def interact(api, *, space_cache, within, action, question='', launch=False, review_token='', route_path=None, validate=False):
    """Review native actions from current provider records; only an explicit launch dispatches."""
    import navcom_space
    center=navcom_space.view(space_cache,action='show',within=within)['center']
    def launcher(*, argv, cwd, env):
        if not Path(cwd).is_dir():raise ValueError('The selected native workspace is unavailable; nothing was launched.')
        command=(['/usr/bin/env']+[key+'='+value for key,value in sorted(env.items())] if env else [])+argv
        ok,message=api.resume_in_new_tab(dict(argv=command,cwd=cwd,provider='hermes' if action=='ask' else 'codex'))
        if not ok:raise ValueError(message)
        return True
    if action=='ask':
        import navcom_star_chat
        cache=Path(str(space_cache)+'.star-inspections')
        if launch:
            result=navcom_star_chat.handoff(center,question,cache,review_token=review_token)
            spec=result['handoff'];launcher(argv=spec['argv'],cwd=spec['cwd'],env=spec['env'])
            result.update(state='dispatched',terminal_dispatched=True,expert_reply_verified=False)
            # Sending occurs in the native process. Terminal dispatch cannot prove receipt.
            result['execution'].update(question_sent=None,agent_started=None)
        else:result=navcom_star_chat.prepare(center,question,cache)
    elif action=='board':
        import navcom_ship_boarding as boarding
        if launch:result=boarding.launch_boarding(center,approved_fingerprint=review_token,launcher=launcher,route_path=route_path)
        elif validate:result=boarding.validate_boarding(center,route_path=route_path)
        else:result=boarding.plan_boarding(center,route_path=route_path)
    else:raise ValueError('Choose ask or board.')
    return dict(schema_version=1,center=center,interaction=result)


def _destination_candidates(space_cache, query, within, catalog):
    """Reuse scoped catalog matching; prefer names over inherited path mentions."""
    import navcom_space
    # Explicit command-language spelling aliases, not lineage/classification.
    # Restrict them to a complete destination phrase and to destination names;
    # a child's inherited path or description cannot stand in for its parent.
    experiment = re.fullmatch(r'(?:exp|experiment)[\s_-]*([0-9]+)', query.strip(), re.IGNORECASE)
    if experiment:
        number = experiment.group(1)
        exact = navcom_space.destination_matches(space_cache, query, within, catalog=catalog)
        matched = navcom_space.view(space_cache, action='search', within=within,
                                   query='exp ' + number, limit=1000, catalog=catalog)
        named = list(exact)
        seen = {node['id'] for node in named}
        for node in [matched['center'], *matched['nodes']]:
            words = re.findall(r'[a-z]+|[0-9]+', node['label'].casefold())
            # A path-derived district clue can mention its experiment without
            # being that experiment. Numbered shortcuts favor product/lab names,
            # while genuinely exact names (of any kind) remain visible choices.
            complete_alias = re.fullmatch(r'(?:exp|experiment)[\s_-]*([0-9]+)', node['label'].strip(), re.IGNORECASE)
            eligible = node['kind'] in {'planet', 'moon'} or (complete_alias and complete_alias.group(1) == number)
            if node['id'] not in seen and eligible and any(prefix in {'exp', 'experiment'} and suffix == number
                   for prefix, suffix in zip(words, words[1:])):
                named.append(node)
                seen.add(node['id'])
        if named:
            return named, matched['more']  # Separate exact-name aliases remain a choice.
    exact = navcom_space.destination_matches(space_cache, query, within, catalog=catalog)
    if exact:
        return exact, False
    matched = navcom_space.view(space_cache, action='search', within=within,
                               query=query, limit=1000, catalog=catalog)
    terms = set(re.findall(r'\w+', query.casefold()))
    named = [node for node in matched['nodes'] if terms and terms <= set(re.findall(r'\w+', node['label'].casefold()))]
    # A truncated metadata page cannot prove uniqueness, even if one shown name
    # is stronger than its descendants' inherited path mentions.
    return named or matched['nodes'], matched['more']


def navigate(api, conn, *, space_cache, source_cache, text, within='', local=True, limit=20, scope_choice=''):
    """Execute the same bounded, read-only route for speech, typing and the CLI.

    Destination commands resolve only an exact unique match or a single result.
    Ambiguous requests return choices, never silently pick the first destination.
    Browser history remains browser-owned; the CLI prints a request, not a claim
    that a navigation action or external command has been executed.
    """
    from navcom_navigation_intent import interpret
    import navcom_space
    intent = interpret(text, within, local)
    catalog=(navcom_space.load_catalog(space_cache) or {}) if intent['within'] or intent['action'] not in ('home','back') else None
    if intent['within']:
        # Resolve/validate scope before any search; never fall back to global.
        intent['within'] = navcom_space.view(space_cache, action='show', within=intent['within'],catalog=catalog)['center']['id']
    action = intent['action']
    def finish(result, destination=None):
        command = ['navcom', 'atlas', 'navigate', text, '--space-cache', str(space_cache),
                   '--source-cache', str(source_cache), '--limit', str(limit)]
        if within: command += ['--within', within]
        if not local: command += ['--global']
        if scope_choice: command += ['--choose', scope_choice]
        db = conn.execute('PRAGMA database_list').fetchone()[2] if conn is not None else ''
        if db: command += ['--index', db]
        result['cli_command'] = shlex.join(command)
        _place_commands([node for node in (result.get('center'), *result['nodes'], *result.get('scope_candidates', [])) if node],
                        space_cache, source_cache, db)
        if result.get('scope_status')=='choose':
            result['scope_choice_commands']={node['id']:shlex.join(command+['--choose',node['id']]) for node in result['scope_candidates']}
        if destination:
            args=['navcom','atlas','explore',destination,'--space-cache',str(space_cache),'--source-cache',str(source_cache)]
            if db: args+=['--index',db]
            result['destination_command']=shlex.join(args)
        return result
    if scope_choice and not intent.get('scope_query'):
        raise ValueError('--choose requires a named-place search clause.')
    if action in ('home', 'back'):
        return finish(dict(schema_version=1, intent=intent, action=action,
                    destination='galaxy:owner' if action == 'home' else None,
                    steps=[dict(status='requested', description=intent['steps'][0])], nodes=[]))
    target = None
    scope_steps = []
    if intent.get('scope_query'):
        candidates, more = _destination_candidates(space_cache, intent['scope_query'], intent['within'], catalog)
        if scope_choice:
            chosen = [node for node in candidates if node['id'] == scope_choice]
            if len(chosen) != 1:
                raise ValueError('Chosen place is not one of the matching destinations inside the allowed scope.')
            target = chosen[0]
        elif len(candidates) == 1 and not more:
            target = candidates[0]
        if target is None:
            result = navcom_space.view(space_cache, action='show', within=intent['within'], catalog=catalog)
            shown = candidates[:limit]
            message = ('Choose the place to search; no code or conversations have been searched yet.' if candidates
                       else 'No matching place inside the allowed scope. Use an exact place name/ID or change the scope.')
            result.update(intent=intent, action=action, destination=None, scope_status='choose' if candidates else 'not_found',
                          scope_candidates=shown, scope_target=None, nodes=shown, entities=shown,
                          total=len(candidates), more=False, scope_candidates_limited=more or len(candidates)>limit,
                          steps=[dict(status='choose' if candidates else 'not_found', description=message, matches=len(candidates))])
            return finish(result)
        intent['within'] = target['id']
        scope_steps.append(dict(status='resolved', description='Resolved search place: '+target['label']+'.', destination=target['id']))
    result = view(api, conn, space_cache=space_cache, source_cache=source_cache,
                  action='search', within=intent['within'], query=intent['query'],
                  limit=limit, include_evidence=False,catalog=catalog)
    nodes = result['nodes']
    destination = None
    if action == 'navigate':
        # Exact identity/name resolution must inspect the catalog, not only the
        # first search page (a system can rank below its many product matches).
        exact, more = _destination_candidates(space_cache, intent['query'], intent['within'], catalog)
        if exact:
            nodes = exact[:limit]
            result.update(nodes=nodes, entities=nodes, total=len(exact), more=more or len(exact)>limit)
            destination = exact[0]['id'] if len(exact) == 1 and not more else None
        if destination is None and len(nodes) == 1 and not result.get('more'):
            destination = nodes[0]['id']
    steps = scope_steps + [dict(status='complete', description='Searched cached destinations.', matches=result['total'])]
    if destination:
        # Resolving a destination needs no whole-galaxy source scan.
        steps.append(dict(status='resolved', description='Resolved one destination.', destination=destination))
    elif action == 'navigate' and nodes:
        steps.append(dict(status='choose', description='Several destinations match. Select the intended place.', matches=len(nodes)))
    else:
        retrieval={'query_style':'question'} if intent.get('retrieval_style')=='question' else {}
        result['evidence'] = evidence(api, conn, space_cache, source_cache,
                                      intent['within'], intent['query'], limit, catalog=catalog, **retrieval)
        proof = result['evidence']
        plan=proof.get('query_plan',{})
        if plan.get('style')=='question':
            steps.append(dict(status='complete' if plan.get('text_terms') else 'partial',
                              description='Used Starforge question terms for code/document evidence; kept the original question for concept search.',
                              terms=plan.get('text_terms',[])))
        steps.append(dict(status='partial' if not proof.get('coverage',{}).get('complete') else 'complete',
                          description='Searched cached Starforge code/documents and indexed conversations.',
                          coverage=proof.get('coverage',{})))
        if proof.get('carried'):
            cargo = proof['carried']
            steps.append(dict(status='complete' if cargo['coverage']['complete'] else 'partial',
                              description='Searched recorded ship context through the native Starship reader.',
                              matches=len(cargo['hits']), coverage=cargo['coverage']))
        if proof.get('places'):
            steps.append(dict(status='complete' if proof['coverage'].get('place_membership_complete') else 'partial',description='Grouped retrieved clues by saved product paths and project conversation memberships; no comparative answer inferred.',
                              matches=sum(place['has_evidence'] for place in proof['places'])))
    if target and intent.get('navigate_first'):
        destination = target['id']
    result.update(intent=intent, action=action, destination=destination, steps=steps)
    if target:
        result.update(scope_status='resolved', scope_target={k:target[k] for k in ('id','label','kind')}, scope_candidates=[])
    return finish(result, destination)
