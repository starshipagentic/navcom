"""Local, dependency-free browser interface for NavCom. No external assets or services.

A thin HTTP adapter (docs/architecture.md, layer 4): each route validates its
request, derives cache paths with navcom_navigation, and calls the same service
function a CLI command reaches. tests/test_architecture.py keeps the route table.
"""
import json
from pathlib import Path
import secrets
import signal
import sqlite3
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
import webbrowser
from navcom_discovery import Discovery
import navcom_navigation as navigation
import navcom_research as research


def _turn(value):
    """An optional turn number (REF:TURN in `navcom --resume REF:TURN --with HARNESS`)."""
    if value in (None, ''):
        return None
    if isinstance(value, bool) or not str(value).isdigit() or int(value) < 1:
        raise ValueError('Turn must be a positive whole number.')
    return int(value)


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
        return navigation.conversation_connection(self.index_path, timeout=.3)

    def caches(self):
        """Chart, source and historical caches for this index, read per request (env may change)."""
        space_cache, source_cache = navigation.paths(self.index_path)
        return space_cache, source_cache, navigation.history_cache(self.index_path)

    def key(self, conn, value):
        if not isinstance(value, str) or not conn.execute('SELECT 1 FROM file_state WHERE file=?', (value,)).fetchone():
            raise ValueError('Conversation not found. Refresh the list.')
        return value

    def plan(self, conn, key, harness, turn):
        """The plan `navcom --resume REF[:TURN] [--with HARNESS]` uses; a turn focuses a fresh harness."""
        if harness and harness not in self.api.REVIVE_AGENTS:
            raise ValueError('Unknown harness')
        focus = _turn(turn)
        return self.api.revive_plan(conn, key, harness, focus=focus) if harness else self.api.resume_plan(conn, key)

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
        number = lambda name, default: int(value(name, str(default)))
        space_cache, source_cache, history_cache = self.caches()
        if route == '/api/voice':
            import navcom_voice
            return navcom_voice.status()
        if route == '/api/history/conversations':
            import navcom_historical_conversations
            return navcom_historical_conversations.view(api,conn,within=value('within'),as_of=value('at'),
                space_cache=space_cache,query=value('q'),limit=number('limit',20))
        if route == '/api/recent':
            return self.recent(conn, value('q'), value('refresh') == '1')
        if route == '/api/source':
            from navcom_source_reader import read_source
            return read_source(value('source'),value('path'),line=number('line',1),limit=number('limit',80),
                cache_path=source_cache.resolve(),history_cache=history_cache,
                history=value('history'),snapshot=value('snapshot'),published=float(value('published')) if value('published') else None)
        if route == '/api/sources':
            import navcom_sources
            return navcom_sources.sources_list(source_cache.resolve())
        if route == '/api/sources/search':
            import navcom_sources
            if not value('q').strip():raise ValueError('Search needs words.')
            return navcom_sources.search(source_cache.resolve(),value('q'),within=value('within') or None,
                paths=params.get('path',[]),mode=value('mode','both'),regex=value('regex')=='1',ext=value('ext') or None,
                limit=number('limit',20))
        if route == '/api/space/inspect':
            return navigation.inspect(space_cache=space_cache,within=value('within'),refresh=value('refresh')=='1',observe=value('observe')=='1')
        if route == '/api/space/context':
            return navigation.context(space_cache,value('within'),action=value('action','inspect'),query=value('q'),ref=value('ref'),
                turn=int(value('turn')) if value('turn') else None,offset=number('offset',0),limit=number('limit',10),max_chars=number('max_chars',2000),expected_catalog=value('catalog'))
        if route == '/api/space/files':
            import navcom_place_files
            return navcom_place_files.files(space_cache,source_cache,value('within'),query=value('q'),
                limit=number('limit',40),offset=number('offset',0),generation=value('generation'))
        if route == '/api/space/related':
            import navcom_relationships
            return navcom_relationships.related(space_cache,source_cache,value('within'),query=value('q'),
                limit=number('limit',20),seconds=float(value('seconds','15')),offset=number('offset',0))
        if route == '/api/history':
            import navcom_history
            if value('action','timeline')!='timeline':raise ValueError('Use the history explorer to prepare a selected revision.')
            if not value('within'):raise ValueError('Select a repository-backed destination for its history.')
            return navcom_history.view(value('within'),action='timeline',repo=Path(value('repo')) if value('repo') else None,space_cache=space_cache,
                source_cache=source_cache,include=params.get('include') or None,limit=number('limit',50))
        if route == '/api/space':
            return navigation.view(api,conn,space_cache=space_cache,source_cache=source_cache,
                action=value('action','explore'),kind=value('kind'),within=value('within'),query=value('q'),
                limit=number('limit',80),offset=number('offset',0),include_evidence=value('evidence')=='1')
        if route == '/api/navigate':
            return navigation.navigate(api,conn,space_cache=space_cache,source_cache=source_cache,
                text=value('q'),within=value('within'),local=value('local','1')!='0',limit=number('limit',20),scope_choice=value('choose'))
        if route == '/api/atlas':
            return self.atlas.view(conn, params)
        if route == '/api/status':
            return dict(stats=api.dashboard_snapshot(conn), task=dict(self.task))
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
        if route == '/api/session/search':
            key = self.key(conn, value('key'))
            limit = number('limit', api.DEFAULT_LIMIT)
            if not value('q').strip():raise ValueError('Search needs words.')
            if not 1 <= limit <= 200:raise ValueError('Search limit must be between 1 and 200.')
            hits, cooked, note = api.search_hits(conn, value('q'), keys=[key], limit=limit)
            return api.search_json(conn, api._group_hits(conn, hits), cooked, note)  # `WORDS --file REF --json`
        if route == '/api/recap':
            key = self.key(conn, value('key'))
            budget = number('max_chars', 0)
            if budget < 0:raise ValueError('max_chars must not be negative.')
            return dict(key=key, recap=api.session_recap(conn, key, budget=budget or api.RECAP_BUDGET))
        if route == '/api/plan':
            return self.plan(conn, self.key(conn, value('key')), value('harness'), value('turn'))
        if route == '/api/state':
            return api._ui_read(conn, 'web')
        raise ValueError('Unknown request')

    def post(self, conn, route, data):
        api = self.api
        space_cache, source_cache, history_cache = self.caches()
        if route in ('/api/space/ask','/api/space/board'):
            for field in ('within','question','review_token'):
                if not isinstance(data.get(field,''),str):raise ValueError('The selected destination, question and review identity must be text.')
            for field in ('launch','validate'):
                if field in data and not isinstance(data[field],bool):raise ValueError('Action switches must be booleans.')
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
                group_id=data.get('group'),query=data.get('q',''),limit=limit,seconds=15,cache_path=history_cache)
        if route == '/api/history/system':
            import navcom_system_history
            for field in ('within','at','q'):
                if not isinstance(data.get(field,''),str):raise ValueError('Historical place, date and query must be text.')
            cursor=data.get('cursor')
            if cursor is not None and not isinstance(cursor,str):raise ValueError('Historical cursor must be text.')
            retry_larger=data.get('retry_larger',False)
            if not isinstance(retry_larger,bool):raise ValueError('Historical retry_larger must be a boolean.')
            if retry_larger and not cursor:raise ValueError('A larger historical retry requires an existing pinned cursor.')
            return navcom_system_history.view(data.get('within',''),data.get('at',''),space_cache=space_cache,
                source_cache=source_cache,cache_path=history_cache,
                query=data.get('q',''),cursor=cursor,limit=int(data.get('limit',4)),seconds=30,retry_larger=retry_larger)
        if route == '/api/history/explore':
            import navcom_history
            if not isinstance(data.get('within'),str) or not data['within']:raise ValueError('Select a repository-backed destination for its history.')
            if not isinstance(data.get('revision'),str) or not data['revision']:raise ValueError('Select an exact Git revision.')
            if not isinstance(data.get('q',''),str):raise ValueError('Historical query must be text.')
            if data.get('repo') is not None and not isinstance(data['repo'],str):raise ValueError('Git copy must be text.')
            return navcom_history.view(data['within'],data['revision'],action='explore',repo=Path(data['repo']) if data.get('repo') else None,space_cache=space_cache,
                source_cache=source_cache,cache_path=history_cache,query=data.get('q',''),limit=int(data.get('limit',50)))
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
            return navcom_intelligence.suggest_for(api, conn, self.key(conn, data.get('key')))
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
                entry = api.annotate(conn, key, name=data.get('name'), note=data.get('note'), favorite=data.get('favorite'))
                self.catalog_at = 0
                return entry
            if route == '/api/launch':
                plan = self.plan(conn, key, data.get('harness'), data.get('turn'))
                if not plan: raise ValueError('Original unavailable. Choose a fresh harness.')
                ok, message, plan = api.prepare_launch(conn, plan)
                if not ok: raise ValueError(message)
                ok, message = api.resume_in_new_tab(plan)
                return dict(ok=ok, message=message, command=plan['line'])
            raise ValueError('Unknown request')
        finally:
            self.mutation.release()

    def upkeep(self):
        conn = self.connect()
        try:
            self.api.claim_index_writer(conn)
            done = self.api.maintain(conn, progress=lambda message: self.task.update(message=message))
            self.catalog_at = 0
            self.task = dict(running=False, error=False,
                             message=f"Complete: {done['changed']} indexed, {done['upgraded']} updated, {done['files']} archived ({done['raw'] / 1e6:.1f} MB).")
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
        import navcom_chart_refresh
        space_cache, source_cache, _ = self.caches()
        try:
            result=navcom_chart_refresh.drive(self.index_path,space_cache,source_cache,automatic=automatic,sync_index=True,
                cancel=self.refresh_cancel,progress=lambda message:self.task.update(message=message),
                on_pass=lambda result:self.task.update(coverage=result))
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
        def local(self):
            """Only this loopback address may load the page or call the API (no DNS rebinding)."""
            return self.headers.get('Host') == f'127.0.0.1:{self.server.server_port}'
        def authorized(self):
            if not self.local(): return False
            origin = self.headers.get('Origin')
            if origin and origin != f'http://127.0.0.1:{self.server.server_port}': return False
            return secrets.compare_digest(self.headers.get('X-Navcom-Token', ''), app.token)
        def do_GET(self):
            route = urlparse(self.path)
            view = route.path in ('/navcom_atlas.js', '/navcom_atlas.css', '/navcom_space.js', '/navcom_space.css', '/navcom_voice.js', '/navcom_voice_worklet.js')
            if (view or route.path == '/' or route.path.startswith('/assets/starship/')) and not self.local():
                self.send(403, {'error': 'Local access only'}); return
            if view:
                path = Path(__file__).with_name(route.path[1:])
                self.send(200, path.read_text(), 'text/javascript' if path.suffix == '.js' else 'text/css'); return
            if route.path.startswith('/assets/starship/'):
                name=route.path.removeprefix('/assets/starship/')
                if name not in {'starbase.png','dock.png','archive.png','lab.png','navcom.png','observatory.png','city.png','ship.png'}:
                    self.send(404,{'error':'Unknown asset'});return
                path=Path(__file__).parent/'assets'/'starship'/name
                self.send(200,path.read_bytes(),'image/png');return
            if route.path == '/':
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
