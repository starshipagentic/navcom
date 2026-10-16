"""Local, dependency-free browser interface for NavCom. No external assets or services."""
import json
import os
from pathlib import Path
import secrets
import signal
import subprocess
import sqlite3
import threading
import tempfile
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
import webbrowser
from navcom_discovery import Discovery, refresh as refresh_discovery
import navcom_research as research


class WebApp:
    def __init__(self, api, index_path):
        self.api, self.index_path = api, Path(index_path)
        self.token = secrets.token_urlsafe(32)
        self.mutation = threading.Lock()
        self.catalog_lock = threading.Lock()
        self.catalog = None
        self.catalog_at = 0
        self.task = {'running': False, 'message': 'Ready', 'error': False}
        self.refresh_cancel = threading.Event()
        self.atlas = Discovery(api)

    def connect(self):
        from navcom_navigation import conversation_connection
        conn = conversation_connection(self.index_path, timeout=.3)
        return conn

    def key(self, conn, value):
        if not isinstance(value, str) or not conn.execute('SELECT 1 FROM file_state WHERE file=?', (value,)).fetchone():
            raise ValueError('Conversation not found. Refresh the list.')
        return value

    def recent(self, conn, query='', refresh=False):
        api = self.api
        annotations = api._ui_read(conn, 'annotations')
        with self.catalog_lock:
            if refresh or self.catalog is None or time.monotonic() - self.catalog_at > 30:
                self.catalog = api._recent_families(conn, api.list_logs(api.ALL_PROVIDERS), annotations)
                conn.commit()
                self.catalog_at = time.monotonic()
            nodes, roots = self.catalog
        focus, matches = api._recent_matches(conn, nodes, annotations, query)
        display_nodes = {key: dict(node, project=api.pretty_project(node['project'])) for key, node in nodes.items()}
        for node in display_nodes.values():
            family=research.family(node['project'])
            if family:
                p=research.PROFILES[family]
                node['research']=dict(family=family,label=p['label'],question=p['question'],approach=p['approach'],distinction=p['distinction'])
        return dict(nodes=display_nodes, roots=roots, annotations=annotations, focus=focus,
                    matches=sorted(matches), query=query)

    def get(self, conn, route, params):
        api = self.api
        value = lambda name, default='': params.get(name, [default])[0]
        if route == '/api/voice':
            import navcom_voice
            return navcom_voice.status()
        if route == '/api/history/conversations':
            import navcom_navigation as navigation
            import navcom_historical_conversations
            space_cache,_=navigation.paths(self.index_path)
            return navcom_historical_conversations.view(api,conn,within=value('within'),as_of=value('at'),
                space_cache=space_cache,query=value('q'),limit=int(value('limit','20')))
        if route == '/api/recent':
            return self.recent(conn, value('q'), value('refresh') == '1')
        if route == '/api/source':
            import navcom_navigation as navigation
            from navcom_source_reader import read_source
            _,source_cache=navigation.paths(self.index_path)
            return read_source(value('source'),value('path'),line=int(value('line','1')),limit=int(value('limit','80')),
                cache_path=source_cache,history_cache=Path(os.environ.get('NAVCOM_HISTORY_CACHE',str(self.index_path.parent/'navcom-history'))),
                history=value('history'),snapshot=value('snapshot'),published=float(value('published')) if value('published') else None)
        if route == '/api/space/inspect':
            import navcom_navigation as navigation
            space_cache,_=navigation.paths(self.index_path)
            return navigation.inspect(space_cache=space_cache,within=value('within'),refresh=value('refresh')=='1',observe=value('observe')=='1')
        if route == '/api/space/context':
            import navcom_navigation as navigation
            space_cache,_=navigation.paths(self.index_path)
            return navigation.context(space_cache,value('within'),action=value('action','inspect'),query=value('q'),ref=value('ref'),
                turn=int(value('turn')) if value('turn') else None,offset=int(value('offset','0')),limit=int(value('limit','10')),max_chars=int(value('max_chars','2000')),expected_catalog=value('catalog'))
        if route == '/api/space/files':
            import navcom_navigation as navigation
            import navcom_place_files
            space_cache,source_cache=navigation.paths(self.index_path)
            return navcom_place_files.files(space_cache,source_cache,value('within'),query=value('q'),
                limit=int(value('limit','40')),offset=int(value('offset','0')),generation=value('generation'))
        if route == '/api/space/related':
            import navcom_navigation as navigation
            import navcom_relationships
            space_cache,source_cache=navigation.paths(self.index_path)
            return navcom_relationships.related(space_cache,source_cache,value('within'),query=value('q'),
                limit=int(value('limit','20')),seconds=float(value('seconds','15')),offset=int(value('offset','0')))
        if route == '/api/history':
            import navcom_navigation as navigation
            import navcom_history
            if value('action','timeline')!='timeline':raise ValueError('Use the history explorer to prepare a selected revision.')
            if not value('within'):raise ValueError('Select a repository-backed destination for its history.')
            space_cache,source_cache=navigation.paths(self.index_path)
            return navcom_history.view(value('within'),action='timeline',space_cache=space_cache,
                source_cache=source_cache,cache_path=Path(os.environ.get('NAVCOM_HISTORY_CACHE',str(self.index_path.parent/'navcom-history'))),limit=int(value('limit','50')))
        if route == '/api/space':
            import navcom_navigation as navigation
            space_cache,source_cache=navigation.paths(self.index_path)
            return navigation.view(api,conn,space_cache=space_cache,source_cache=source_cache,
                action=value('action','explore'),kind=value('kind'),within=value('within'),query=value('q'),
                limit=int(value('limit','80')),offset=int(value('offset','0')),include_evidence=value('evidence')=='1')
        if route == '/api/navigate':
            import navcom_navigation as navigation
            space_cache,source_cache=navigation.paths(self.index_path)
            return navigation.navigate(api,conn,space_cache=space_cache,source_cache=source_cache,
                text=value('q'),within=value('within'),local=value('local','1')!='0',limit=int(value('limit','20')),scope_choice=value('choose'))
        if route == '/api/atlas':
            return self.atlas.view(conn, params)
        if route == '/api/status':
            stats = api._read_dashboard_cache(conn)
            if stats is None:
                stats = api.dashboard_stats(conn)
                api._write_dashboard_cache(conn, stats)
            return dict(stats=stats, task=dict(self.task))
        if route == '/api/task':
            return dict(self.task)
        if route == '/api/harnesses':
            return api.fresh_harnesses(value('provider') or None)
        if route == '/api/session':
            key = self.key(conn, value('key'))
            provider = api._key_provider(conn, key)
            start = max(1, int(value('start', '1')))
            last = api.max_msg_index(conn, key)
            project, title = api.session_meta(conn, key, provider)
            annotation = api._ui_read(conn, 'annotations').get(key, {})
            plan = api.resume_plan(conn, key, provider)
            _, nickname = api._session_parent(conn, key, provider)
            return dict(key=key, provider=provider, title=annotation.get('name') or title or nickname,
                        project=api.pretty_project(project),
                        annotation=annotation, last=last, start=start,
                        turns=api.fetch_window_rows(conn, key, [(start, start + 79)]),
                        plan=plan, preview=api._launch_preview(plan, key),
                        last_reply=api._recent_last_words(conn, key))
        if route == '/api/plan':
            key = self.key(conn, value('key'))
            harness = value('harness')
            if harness:
                if harness not in api.REVIVE_AGENTS:
                    raise ValueError('Unknown harness')
                return api.revive_plan(conn, key, harness)
            return api.resume_plan(conn, key)
        if route == '/api/state':
            return api._ui_read(conn, 'web')
        raise ValueError('Unknown request')

    def post(self, conn, route, data):
        api = self.api
        if route in ('/api/space/ask','/api/space/board'):
            import navcom_navigation as navigation
            for field in ('within','question','review_token'):
                if not isinstance(data.get(field,''),str):raise ValueError('The selected destination, question and review identity must be text.')
            for field in ('launch','validate'):
                if field in data and not isinstance(data[field],bool):raise ValueError('Action switches must be booleans.')
            space_cache,_=navigation.paths(self.index_path)
            return navigation.interact(api,space_cache=space_cache,within=data.get('within',''),
                action=route.rsplit('/',1)[-1],question=data.get('question',''),launch=data.get('launch') is True,
                review_token=data.get('review_token',''),validate=data.get('validate') is True)
        if route == '/api/voice':
            import navcom_voice
            return navcom_voice.transcribe_request(data)
        if route == '/api/history/land':
            import navcom_historical_landing
            for field in ('within','cursor','result_key'):
                if not isinstance(data.get(field),str) or not data[field]:raise ValueError('Historical landing needs a saved place, cursor and result key.')
            if not isinstance(data.get('q',''),str):raise ValueError('Historical query must be text.')
            if data.get('group') is not None and not isinstance(data['group'],str):raise ValueError('Historical district must be text.')
            limit=data.get('limit',20)
            if not isinstance(limit,int) or isinstance(limit,bool):raise ValueError('Historical search limit must be an integer.')
            return navcom_historical_landing.landing(data['cursor'],data['within'],result_key=data['result_key'],
                group_id=data.get('group'),query=data.get('q',''),limit=limit,seconds=15,
                cache_path=Path(os.environ.get('NAVCOM_HISTORY_CACHE',str(self.index_path.parent/'navcom-history'))))
        if route == '/api/history/system':
            import navcom_navigation as navigation
            import navcom_system_history
            for field in ('within','at','q'):
                if not isinstance(data.get(field,''),str):raise ValueError('Historical place, date and query must be text.')
            cursor=data.get('cursor')
            if cursor is not None and not isinstance(cursor,str):raise ValueError('Historical cursor must be text.')
            retry_larger=data.get('retry_larger',False)
            if not isinstance(retry_larger,bool):raise ValueError('Historical retry_larger must be a boolean.')
            if retry_larger and not cursor:raise ValueError('A larger historical retry requires an existing pinned cursor.')
            space_cache,source_cache=navigation.paths(self.index_path)
            return navcom_system_history.view(data.get('within',''),data.get('at',''),space_cache=space_cache,
                source_cache=source_cache,cache_path=Path(os.environ.get('NAVCOM_HISTORY_CACHE',str(self.index_path.parent/'navcom-history'))),
                query=data.get('q',''),cursor=cursor,limit=int(data.get('limit',4)),seconds=30,retry_larger=retry_larger)
        if route == '/api/history/explore':
            import navcom_navigation as navigation
            import navcom_history
            if not isinstance(data.get('within'),str) or not data['within']:raise ValueError('Select a repository-backed destination for its history.')
            if not isinstance(data.get('revision'),str) or not data['revision']:raise ValueError('Select an exact Git revision.')
            if not isinstance(data.get('q',''),str):raise ValueError('Historical query must be text.')
            space_cache,source_cache=navigation.paths(self.index_path)
            return navcom_history.view(data['within'],data['revision'],action='explore',space_cache=space_cache,
                source_cache=source_cache,cache_path=Path(os.environ.get('NAVCOM_HISTORY_CACHE',str(self.index_path.parent/'navcom-history'))),query=data.get('q',''),limit=int(data.get('limit',50)))
        if route == '/api/space/refresh':
            if self.task.get('running') and self.task.get('kind')=='chart':
                return dict(self.task)
            if not self.mutation.acquire(blocking=False):
                raise sqlite3.OperationalError('database is busy: refresh already running')
            self.task=dict(kind='chart',running=True,message='Discovering source material and geographic evidence',error=False)
            self.refresh_cancel.clear()
            threading.Thread(target=self.refresh_space,args=(data.get('automatic') is True,),daemon=True,name='navcom-space-refresh').start()
            return dict(self.task)
        if route == '/api/space/refresh/pause':
            self.refresh_cancel.set()
            return dict(self.task, message='Pausing chart intake; published evidence stays available')
        if route == '/api/suggest':
            import navcom_intelligence
            key = self.key(conn, data.get('key'))
            last = api.max_msg_index(conn, key)
            turns = api.fetch_window_rows(conn, key, [(1, 3), (max(4, last - 10), last)])
            text = '\n'.join(f'{role}: {text[:1200]}' for _, role, text in turns if role in ('user', 'assistant'))
            return navcom_intelligence.suggest(text)
        if route == '/api/upkeep':
            if not self.mutation.acquire(blocking=False):
                raise sqlite3.OperationalError('database is busy: upkeep is already running')
            self.task = dict(running=True, message='Checking index availability', error=False)
            threading.Thread(target=self.upkeep, daemon=True, name='navcom-web-upkeep').start()
            return dict(self.task)
        if not self.mutation.acquire(blocking=False):
            raise sqlite3.OperationalError('database is busy: upkeep is running; try again when it finishes')
        try:
            if route == '/api/state':
                state = {k: data[k] for k in ('query', 'favorites', 'selected', 'expanded', 'collapsed', 'scroll', 'start') if k in data}
                if not api._ui_write(conn, 'web', state):
                    raise sqlite3.OperationalError('database is locked; view position could not be saved')
                return {'saved': True}
            key = self.key(conn, data.get('key'))
            if route == '/api/annotation':
                annotations = api._ui_read(conn, 'annotations')
                entry = dict(annotations.get(key, {}))
                for field in ('name', 'note'):
                    if field in data:
                        if not isinstance(data[field], str): raise ValueError('Name and note must be text')
                        entry[field] = api._one_line(data[field], 240)
                if 'favorite' in data: entry['favorite'] = bool(data['favorite'])
                annotations[key] = entry
                if not api._ui_write(conn, 'annotations', annotations):
                    raise sqlite3.OperationalError('database is locked; changes were not saved')
                self.catalog_at = 0
                return entry
            if route == '/api/launch':
                harness = data.get('harness')
                if harness and harness not in api.REVIVE_AGENTS: raise ValueError('Unknown harness')
                plan = api.revive_plan(conn, key, harness) if harness else api.resume_plan(conn, key)
                if not plan: raise ValueError('Original unavailable. Choose a fresh harness.')
                ok, message = api.ensure_resumable(conn, plan)
                if not ok: raise ValueError(message)
                if plan['cwd'] and not os.path.isdir(plan['cwd']): raise ValueError('The working folder no longer exists.')
                if not (api.shutil.which(plan['argv'][0]) or os.path.isfile(plan['argv'][0])):
                    raise ValueError('That harness is not installed. Copy the command to use it elsewhere.')
                ok, message = api.resume_in_new_tab(plan)
                return dict(ok=ok, message=message, command=plan['line'])
            raise ValueError('Unknown request')
        finally:
            self.mutation.release()

    def upkeep(self):
        conn = self.connect()
        try:
            conn.execute('BEGIN IMMEDIATE')
            conn.execute('UPDATE file_state SET size=size WHERE 0')
            conn.commit()
            api = self.api
            api.INDEX_READ_ONLY = False
            self.task = dict(running=True, message='Discovering conversations', error=False)
            logs = api.list_logs(api.ALL_PROVIDERS)
            self.task['message'] = 'Indexing new and changed conversations'
            changed = api._index_logs(conn, logs, progress=False, upgrade=False)
            self.task['message'] = 'Updating older transcript parsers'
            upgraded = api.upgrade_stale_parses(conn, logs, budget=None)
            self.task['message'] = 'Preserving raw transcript archives'
            files, raw = api.archive_logs(conn, logs, budget=None)
            conn.commit()
            self.task['message'] = 'Refreshing discovery evidence'
            refresh_discovery(conn)
            self.catalog_at = 0
            self.task = dict(running=False, error=False,
                             message=f'Complete: {changed} indexed, {upgraded} updated, {files} archived ({raw / 1e6:.1f} MB).')
        except Exception as exc:
            conn.rollback()
            message = str(exc)
            if any(word in message.lower() for word in ('locked', 'busy')):
                message = 'Index busy in another process. Close/reopen older NavCom windows, then retry. This page is still usable.'
            self.task = dict(running=False, error=True, message=message)
        finally:
            conn.close()
            self.mutation.release()


    def refresh_space(self, automatic=False):
        import navcom_navigation as navigation
        import navcom_chart_refresh
        space_cache,source_cache=navigation.paths(self.index_path)
        deadline=time.monotonic()+120
        try:
            while True:
                result=navcom_chart_refresh.refresh(self.index_path,space_cache,source_cache,
                    automatic=automatic,sync_index=True,seconds=max(1,min(60,deadline-time.monotonic())),
                    cancel=self.refresh_cancel,progress=lambda message:self.task.update(message=message))
                self.task.update(coverage=result)
                if result['complete'] or result['paused'] or result.get('runtime_error') or result.get('index_error'):
                    break
                if time.monotonic()>=deadline-2:
                    result = dict(result, stop_reason='time_budget')
                    break
            suffix=(' · paused; Continue chart resumes' if result['paused'] else
                    ' · two-minute work limit reached; progress saved, Continue chart resumes' if result.get('stop_reason')=='time_budget' else
                    ' · more remain; progress saved' if result['more'] else
                    ' · cached' if result['cached'] else ' · complete')
            gaps=len(result['failures'])+len(result['skipped'])
            oversized=(result.get('indexing') or {}).get('oversized',0)
            self.task=dict(kind='chart',running=False,error=False,coverage=result,
                message=f"Chart intake {result['visited']}/{result['total']} projects"+suffix+(f' · {gaps} unavailable or skipped' if gaps else '')+(' · Starforge unavailable; chart uses existing evidence' if result.get('runtime_error') else '')+(' · conversation indexing incomplete; using saved index' if result.get('index_error') else '')+(f' · {oversized} large conversations deferred to Upkeep' if oversized else ''))
        except navcom_chart_refresh.Interrupted as exc:
            self.task=dict(running=False,error=False,message=str(exc))
        except Exception as exc:
            self.task=dict(running=False,error=True,message=str(exc))
        finally:
            self.mutation.release()


def make_server(api, index_path, port=0):
    app = WebApp(api, index_path)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def send(self, status, body, content_type='application/json'):
            raw = body if isinstance(body,bytes) else body.encode() if isinstance(body, str) else json.dumps(body).encode()
            try:
                self.send_response(status)
                self.send_header('Content-Type', content_type + '; charset=utf-8')
                self.send_header('Content-Length', str(len(raw)))
                self.send_header('Cache-Control', 'no-store')
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.send_header('Content-Security-Policy', "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
                self.end_headers()
                self.wfile.write(raw)
            except (BrokenPipeError, ConnectionResetError): pass  # visitor left mid-response
        def authorized(self):
            expected = f'127.0.0.1:{self.server.server_port}'
            if self.headers.get('Host') != expected: return False
            origin = self.headers.get('Origin')
            if origin and origin != 'http://' + expected: return False
            return secrets.compare_digest(self.headers.get('X-Navcom-Token', ''), app.token)
        def do_GET(self):
            route = urlparse(self.path)
            if route.path in ('/navcom_atlas.js', '/navcom_atlas.css', '/navcom_space.js', '/navcom_space.css', '/navcom_voice.js', '/navcom_voice_worklet.js'):
                if self.headers.get('Host') != f'127.0.0.1:{self.server.server_port}':
                    self.send(403, {'error': 'Local access only'}); return
                path = Path(__file__).with_name(route.path[1:])
                self.send(200, path.read_text(), 'text/javascript' if path.suffix == '.js' else 'text/css'); return
            if route.path.startswith('/assets/starship/'):
                if self.headers.get('Host') != f'127.0.0.1:{self.server.server_port}':
                    self.send(403, {'error': 'Local access only'}); return
                name=route.path.removeprefix('/assets/starship/')
                if name not in {'starbase.png','dock.png','archive.png','lab.png','navcom.png','observatory.png','city.png','ship.png'}:
                    self.send(404,{'error':'Unknown asset'});return
                path=Path(__file__).parent/'assets'/'starship'/name
                self.send(200,path.read_bytes(),'image/png');return
            if route.path == '/':
                if self.headers.get('Host') != f'127.0.0.1:{self.server.server_port}':
                    self.send(403, {'error': 'Local access only'}); return
                template = Path(__file__).with_name('navcom_web.html').read_text()
                self.send(200, template.replace('__NAVCOM_TOKEN__', json.dumps(app.token)), 'text/html'); return
            if not self.authorized():
                self.send(403, {'error': 'Local session required'}); return
            self.dispatch(route.path, parse_qs(route.query), False)
        def do_POST(self):
            if not self.authorized():
                self.send(403, {'error': 'Local session required'}); return
            try:
                size = int(self.headers.get('Content-Length', 0))
                maximum = 950000 if urlparse(self.path).path == '/api/voice' else 65536
                if not 0 < size <= maximum: raise ValueError('Invalid request size')
                data = json.loads(self.rfile.read(size))
                if not isinstance(data, dict): raise ValueError('Expected an object')
            except (ValueError, TypeError):
                self.send(400, {'error': 'Invalid request'}); return
            self.dispatch(urlparse(self.path).path, data, True)
        def dispatch(self, route, data, post):
            conn = app.connect()
            try:
                result = app.post(conn, route, data) if post else app.get(conn, route, data)
                conn.commit()
                self.send(200, result)
            except sqlite3.OperationalError as exc:
                conn.rollback()
                message = str(exc)
                busy = any(w in message.lower() for w in ('locked', 'busy'))
                self.send(409 if busy else 500, {'error': ('Index busy in another process. Try again shortly; your page is still open.' if busy else message)})
            except (ValueError, TypeError) as exc:
                conn.rollback(); self.send(400, {'error': str(exc),**({'coverage':exc.coverage} if getattr(exc,'coverage',None) else {})})
            except Exception:
                conn.rollback(); self.send(500, {'error': 'This operation failed. Refresh or retry; the server is still running.'})
            finally:
                conn.close()
    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    server.daemon_threads = True
    server.app = app
    return server


def serve(api, index_path, open_browser=True):
    # The CLI dies quietly on broken pipes (`navcom ... | head`); a long-running
    # bridge must instead survive a browser that reloads mid-response.
    signal.signal(signal.SIGPIPE, signal.SIG_IGN)
    conn = api.open_index(index_path)
    conn.close()
    server = make_server(api, index_path)
    url = f'http://127.0.0.1:{server.server_port}/'
    print(f'navcom ▸ local mission control: {url}\nKeep this terminal open. Ctrl+C stops the web menu.', flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever(poll_interval=.2)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
