"""Local, dependency-free browser interface for NavCom. No external assets or services."""
import json
import os
from pathlib import Path
import secrets
import sqlite3
import threading
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
        self.atlas = Discovery(api)

    def connect(self):
        conn = sqlite3.connect(str(self.index_path), timeout=.3)
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
        if route == '/api/recent':
            return self.recent(conn, value('q'), value('refresh') == '1')
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


def make_server(api, index_path, port=0):
    app = WebApp(api, index_path)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def send(self, status, body, content_type='application/json'):
            raw = body.encode() if isinstance(body, str) else json.dumps(body).encode()
            self.send_response(status)
            self.send_header('Content-Type', content_type + '; charset=utf-8')
            self.send_header('Content-Length', str(len(raw)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            try: self.wfile.write(raw)
            except (BrokenPipeError, ConnectionResetError): pass
        def authorized(self):
            expected = f'127.0.0.1:{self.server.server_port}'
            if self.headers.get('Host') != expected: return False
            origin = self.headers.get('Origin')
            if origin and origin != 'http://' + expected: return False
            return secrets.compare_digest(self.headers.get('X-Navcom-Token', ''), app.token)
        def do_GET(self):
            route = urlparse(self.path)
            if route.path in ('/navcom_atlas.js', '/navcom_atlas.css'):
                if self.headers.get('Host') != f'127.0.0.1:{self.server.server_port}':
                    self.send(403, {'error': 'Local access only'}); return
                path = Path(__file__).with_name(route.path[1:])
                self.send(200, path.read_text(), 'text/javascript' if path.suffix == '.js' else 'text/css'); return
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
                if not 0 < size <= 65536: raise ValueError('Invalid request size')
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
                conn.rollback(); self.send(400, {'error': str(exc)})
            except Exception:
                conn.rollback(); self.send(500, {'error': 'This operation failed. Refresh or retry; the server is still running.'})
            finally:
                conn.close()
    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    server.daemon_threads = True
    server.app = app
    return server


def serve(api, index_path, open_browser=True):
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
