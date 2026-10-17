"""Resumable, bounded orchestration of native discovery, harvest and geography.

The saved queue is produced by NavCom's project inventory. Source bytes and
analysis belong to Starforge; this service only schedules those existing tools.
"""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shlex
import sqlite3
import subprocess
import sys
import tempfile
import time

import navcom_space as space

VERSION = 2
FRESH_SECONDS = 600
MAX_PROJECTS = 2000
INDEX_SESSION_LIMIT = 100
INDEX_FILE_BYTES = 8 * 1024 * 1024
INDEX_BATCH_BYTES = 32 * 1024 * 1024
MAX_CHART_SECONDS = 45
MAX_INTAKE_SECONDS = 20


def _sync_index(api, index, *, seconds=8):
    """Use native parsers incrementally; never run archival or full reindexing."""
    deadline = time.monotonic() + seconds
    print('Discovering recent conversation logs', file=sys.stderr, flush=True)
    logs = api.list_logs(api.ALL_PROVIDERS)
    conn = api.open_index(Path(index))
    try:
        known = {f: (m, z) for f, m, z in conn.execute('SELECT file,mtime,size FROM file_state')}
        changed = [log for log in reversed(logs) if known.get(log[0]) != (log[1], log[2])]
        eligible = [log for log in changed if log[2] <= INDEX_FILE_BYTES]
        selected = []
        byte_count = 0
        for log in eligible:
            if (len(selected) >= INDEX_SESSION_LIMIT or time.monotonic() >= deadline or
                    byte_count + log[2] > INDEX_BATCH_BYTES):
                break
            selected.append(log)
            byte_count += log[2]
        print(f'Indexing {len(selected)} new or changed conversations', file=sys.stderr, flush=True)
        # The native helper commits each session. Its subprocess deadline also
        # bounds parsing; completed sessions survive a timed-out batch.
        updated = api._index_logs(conn, selected, progress=False, upgrade=False)
        visited = len(selected)
        return dict(discovered=len(logs), changed=len(changed), indexed=updated,
                    visited=visited, deferred=len(eligible)-visited,
                    oversized=len(changed)-len(eligible), complete=visited == len(eligible),
                    bounds=dict(seconds=seconds, sessions=INDEX_SESSION_LIMIT,
                                file_bytes=INDEX_FILE_BYTES, batch_bytes=INDEX_BATCH_BYTES),
                    coverage='Native incremental conversation indexing; oversized sessions require normal upkeep.')
    finally:
        conn.close()


class Interrupted(ValueError):
    pass


def _worker(request):
    import navcom
    action = request['action']
    if action == 'runtime':
        import navcom_sources
        return navcom_sources.runtime()
    if action == 'index':
        return _sync_index(navcom, request['index'], seconds=request.get('seconds', 8))
    if action == 'intake':
        root = Path(request['job']['root']).expanduser()
        cache = Path(request['sources']).expanduser().resolve()
        # Match the native harvest worker's containment policy before an
        # automatic container walk can ingest its own snapshots and receipts.
        # Explicit source harvest/refresh still enforces its existing rejection.
        if root.is_absolute() and cache.is_relative_to(root.resolve()):
            return dict(sources=0, analyzed_sources=0, cached_sources=0, published=False,
                        skipped=[dict(path=str(root), reason='Source root contains the source cache; '
                                      'automatic intake omitted by the native harvest containment policy.')])
        from navcom_source_discovery import discover
        selection = discover(navcom, Path(request['index']), Path(request['sources']),
                             projects=request['job']['projects'], limit=200,
                             project_boundaries=request['boundaries'])
        result = dict(skipped=selection['coverage']['skipped'], sources=0)
        if selection['sources']:
            import navcom_sources
            process = subprocess.run(navcom_sources.worker_argv(request['runtime']),
                input=json.dumps(dict(action='harvest', cache=request['sources'], sources=selection['sources'])),
                text=True, stdout=subprocess.PIPE, check=True)
            result.update(json.loads(process.stdout))
        return result
    with sqlite3.connect(Path(request['index']).as_uri() + '?mode=ro', uri=True, timeout=.3) as conn:
        if action == 'inventory':
            from navcom_discovery import Discovery
            conn.execute('BEGIN')  # One read snapshot for every inventory page.
            discovery = Discovery(navcom)
            projects = []
            for offset in range(0, MAX_PROJECTS, 200):
                page = discovery.view(conn, dict(action=['list'], grouping=['projects'],
                                                offset=[str(offset)], limit=['200']))
                projects.extend(dict(label=n['label'], collection=n['collection']) for n in page['nodes'])
                if not page.get('more'):
                    break
            from navcom_source_discovery import group_projects
            grouped = group_projects(projects)
            return dict(projects=projects, jobs=grouped['jobs'], grouping=grouped['coverage'],
                        truncated=bool(page.get('more')))
        if action == 'chart':
            result = space.refresh(navcom, conn, Path(request['space']), source_cache=Path(request['sources']),
                progress=lambda done,total: print(f'Charting destinations {done}/{total}', file=sys.stderr, flush=True))
            return dict(destinations=len(result['entities']), published=result['published'])
    raise ValueError('Unknown chart refresh operation')


SCRIPT = """import json,sys
sys.path.insert(0,sys.argv[1])
import navcom_chart_refresh as service
try:
 result={'ok':True,'value':service._worker(json.load(sys.stdin))}
except Exception as exc:
 result={'ok':False,'error':str(exc)[:1000]}
print(json.dumps(result))
"""


def _run(request, seconds, cancel=None, progress=None):
    """Bound wall time, output, and the whole process group, including harvest."""
    with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
        process = subprocess.Popen([sys.executable, '-I', '-B', '-c', SCRIPT, str(Path(__file__).parent)],
            stdin=subprocess.PIPE, stdout=output, stderr=errors, start_new_session=True)
        deadline = time.monotonic() + seconds
        observed = 0
        try:
            process.stdin.write(json.dumps(request).encode()); process.stdin.close()
            while process.poll() is None:
                if cancel and cancel.is_set():
                    raise Interrupted('Charting paused; saved progress will resume next time')
                if time.monotonic() >= deadline:
                    raise TimeoutError('Operation reached its time budget; prior published snapshots remain available')
                size = os.fstat(errors.fileno()).st_size
                if os.fstat(output.fileno()).st_size > 4*1024*1024 or size > 1024*1024:
                    raise ValueError('Refresh worker exceeded its output budget')
                if progress and size > observed:
                    start = max(observed, size-2000)
                    lines = os.pread(errors.fileno(), size-start, start).decode('utf-8', 'replace').splitlines()
                    observed = size
                    human = [line for line in lines if line.startswith((
                        'navcom sources ▸ ', 'Charting destinations ',
                        'Discovering recent conversation logs', 'Indexing '))]
                    if human:
                        progress(human[-1][-350:])
                try:
                    process.wait(timeout=.05)
                except subprocess.TimeoutExpired:
                    pass
            if process.returncode or os.fstat(output.fileno()).st_size > 4*1024*1024 or os.fstat(errors.fileno()).st_size > 1024*1024:
                raise ValueError('Refresh worker failed or exceeded its output budget')
            output.seek(0); result = json.load(output)
            if not result.get('ok'):
                raise ValueError(result.get('error', 'Refresh worker unavailable'))
            return result['value']
        finally:
            space.kill_group(process)


def state_path(source_cache, *, index_path=None, space_cache=None):
    """One cursor per index/chart, with the old path retained for migration.

    Sources and their native artifacts may be shared by several charts. Their
    pending publications, pinned inventories and explicit pauses are separate.
    Resolve OS aliases before hashing so /tmp and /private/tmp share a cursor.
    """
    source_cache = Path(source_cache).expanduser().resolve()
    if index_path is None and space_cache is None:
        return source_cache / 'chart-intake.json'
    if index_path is None or space_cache is None:
        raise ValueError('An intake state needs both index and chart paths')
    identity = dict(index=str(Path(index_path).expanduser().resolve()),
                    space=str(Path(space_cache).expanduser().resolve()), sources=str(source_cache))
    key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    return source_cache / 'chart-intakes' / (key + '.json')


def _chart_seconds(state):
    observed = state.get('chart_seconds', 0)
    return observed if isinstance(observed, (int, float)) and 0 <= observed <= MAX_CHART_SECONDS else 0


def _chart_reserve(state, seconds):
    """Keep native publication's measured cost inside the caller's total budget."""
    observed = _chart_seconds(state)
    return min(seconds, MAX_CHART_SECONDS,
               max(min(20, seconds/3), observed*1.2+1 if observed else 0))


def refresh(index_path, space_cache, source_cache, *, seconds=60, limit=20,
            restart=False, automatic=False, sync_index=False, cancel=None, progress=None):
    """Resume a pinned project sweep. Completed automatic sweeps rest ten minutes.

    Failed projects are disclosed and do not starve later ones. A fresh sweep
    retries them. Pausing or a total deadline retains the current project.
    A failed/deferred publication gets a dedicated continuation before more
    source work; measured chart time reserves enough of later intake pages.
    """
    if not 1 <= seconds <= 120 or not isinstance(limit, int) or not 1 <= limit <= 200:
        raise ValueError('Chart refresh needs seconds 1–120 and limit 1–200')
    index, chart, sources = (Path(p).expanduser().resolve() for p in (index_path, space_cache, source_cache))
    if not index.is_file():
        raise ValueError('No conversation index. Run navcom --maintain first.')
    path = state_path(sources, index_path=index, space_cache=chart)
    sources.mkdir(parents=True, exist_ok=True)
    started = time.monotonic(); deadline = started + seconds
    # Keep the existing shared lock, including compatibility with older tools:
    # independent chart cursors must not publish shared source artifacts at once.
    with state_path(sources).with_suffix('.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('Another chart intake is running; cached browsing remains available') from None
        context = dict(index=str(index), space=str(chart), sources=str(sources))
        state = space._read(path, {})
        if not path.exists():
            legacy = space._read(state_path(sources), {})
            if legacy and legacy.get('version') == VERSION and legacy.get('context') == context:
                state = legacy
                # Leave legacy bytes intact for another context or an older
                # reader. Only this matching context may adopt its saved cursor.
                space._atomic(path, state)
        if state and (state.get('version') != VERSION or state.get('context') != context):
            state = {}
        # A browser reload is not consent to undo an explicit Pause. Continue
        # and manual refresh deliberately clear it below.
        if automatic and state.get('paused') and not restart:
            return _result(state, context, started)
        cached = bool(automatic and state.get('complete') and chart.exists() and
                      (not sync_index or state.get('indexing') is not None) and
                      not state.get('indexing', {}).get('deferred') and not state.get('index_error') and
                      time.time()-state.get('finished_at', 0) < FRESH_SECONDS and not restart)
        if cached:
            return _result(state, context, started, cached=True)
        if not state or restart or state.get('complete'):
            chart_seconds = _chart_seconds(state)
            state = dict(version=VERSION, context=context, started_at=time.time(),
                         projects=[], jobs=[], grouping={}, inventory_pending=True,
                         truncated=False, next=0,
                         complete=False, failures=[], skipped=[], harvested=0, reused=0,
                         chart_pending=True, chart_seconds=chart_seconds)
            space._atomic(path, state)
        request = dict(context)
        state.pop('paused', None)
        publication_first = bool(not state.get('inventory_pending') and state.get('chart_pending') and
                                 (state.get('chart_error') or state.get('publication_first') or
                                  state.get('chart_deferred_for_intake') or
                                  state.get('stop_reason') == 'time_budget'))
        state['stop_reason'] = 'page_limit'

        def publish():
            remaining = deadline-time.monotonic()
            if remaining < 2:
                state['stop_reason'] = 'time_budget'
                return False
            if progress: progress('Publishing the current chart from harvested evidence')
            began = time.monotonic()
            state['chart_attempt_budget'] = min(MAX_CHART_SECONDS, remaining)
            try:
                result = _run(dict(action='chart', **context), state['chart_attempt_budget'], cancel, progress)
                observed = min(MAX_CHART_SECONDS, max(0, time.monotonic()-began))
                state.update(chart_pending=False, charted_at=time.time(), destinations=result['destinations'],
                             chart_seconds=max(_chart_seconds(state), observed))
            except (ValueError, TimeoutError) as exc:
                if isinstance(exc, Interrupted): raise
                state['chart_error'] = str(exc)
                return False
            state.pop('chart_error', None)
            return True

        try:
            if publication_first:
                # Do not repeatedly spend this page on runtime/harvest and then
                # offer the same too-small remainder to a known pending chart.
                # The pinned inventory and exact source cursor remain untouched.
                state['publication_first'] = True
                state['chart_deferred_for_intake'] = False
                state['chart_reserved_seconds'] = min(MAX_CHART_SECONDS, max(0, deadline-time.monotonic()))
                if publish():
                    state['stop_reason'] = 'chart_published'
                state['complete'] = state['next'] == len(state['jobs']) and not state['chart_pending']
                if state['complete']: state['finished_at'] = time.time()
                return _result(state, context, started)
            state['publication_first'] = False
            if state.get('inventory_pending'):
                if sync_index:
                    if progress: progress('Refreshing the conversation index before discovering projects')
                    available = min(10, max(.1, (deadline-time.monotonic())/3))
                    try:
                        state['indexing'] = _run(dict(action='index', seconds=max(.05, available-1), **context),
                                                 available, cancel, progress)
                        state.pop('index_error', None)
                    except (ValueError, TimeoutError) as exc:
                        if isinstance(exc, Interrupted): raise
                        state['index_error'] = str(exc)
                if progress: progress('Pinning the current project inventory')
                inventory = _run(dict(action='inventory', **context), min(30, max(.1, deadline-time.monotonic())), cancel, progress)
                state.update(projects=inventory['projects'], jobs=inventory['jobs'], grouping=inventory['grouping'],
                             truncated=inventory['truncated'], inventory_pending=False)
                space._atomic(path, state)
            if state['next'] < len(state['jobs']):
                try:
                    request['runtime'] = _run(dict(action='runtime'), min(10, max(.1, deadline-time.monotonic())), cancel, progress)
                except (ValueError, TimeoutError) as exc:
                    if isinstance(exc, Interrupted): raise
                    state['runtime_error'] = str(exc)
                else:
                    state.pop('runtime_error', None)
            stop = min(len(state['jobs']), state['next']+limit)
            # Leave time for a usable chart before the source sweep is finished.
            reserve = _chart_reserve(state, seconds)
            available = max(0, deadline-time.monotonic())
            # A large learned reserve must not starve a source that needs its
            # full native job budget. If the phases cannot fit together after
            # setup, alternate them explicitly instead of timing out that same
            # source forever or retrying a chart in a known-short remainder.
            defer_chart = bool(state['next'] < stop and request.get('runtime') and
                               available-reserve < MAX_INTAKE_SECONDS)
            state['chart_deferred_for_intake'] = defer_chart
            state['chart_reserved_seconds'] = 0 if defer_chart else reserve
            intake_deadline = deadline - state['chart_reserved_seconds']
            while state['next'] < stop and request.get('runtime'):
                if cancel and cancel.is_set():
                    raise Interrupted('Charting paused; saved progress will resume next time')
                remaining = intake_deadline-time.monotonic()
                if remaining < 2:
                    state['stop_reason'] = 'time_budget'
                    break
                job = state['jobs'][state['next']]
                if progress: progress(f"Harvesting project {state['next']+1}/{len(state['jobs'])} · {job['root']}")
                # Publication can win the race with cancellation. Persist the
                # obligation to chart before invoking the mutating worker, even
                # if the retry later reports the source as already cached.
                state['chart_pending'] = True
                space._atomic(path, state)
                try:
                    result = _run(dict(action='intake', job=job, boundaries=state['projects'], **request), min(MAX_INTAKE_SECONDS, remaining), cancel, progress)
                    state['harvested'] += result.get('analyzed_sources', 0)
                    state['reused'] += result.get('cached_sources', 0)
                    state['skipped'].extend(result.get('skipped', []))
                    state['chart_pending'] |= bool(result.get('published'))
                except TimeoutError as exc:
                    if remaining < MAX_INTAKE_SECONDS:  # A total budget is not a failed project.
                        state['stop_reason'] = 'time_budget'
                        break
                    state['failures'].append(dict(project=job['root'], error=str(exc)))
                except ValueError as exc:
                    if isinstance(exc, Interrupted): raise
                    state['failures'].append(dict(project=job['root'], error=str(exc)))
                state['next'] += 1
                space._atomic(path, state)
            # Checkpoint only at sweep end or once per minute. Reading/searching
            # the previously published chart remains available throughout.
            remaining = deadline-time.monotonic()
            if remaining < 2 and state['chart_pending']:
                state['stop_reason'] = 'time_budget'
            due = state['next'] == len(state['jobs']) or not chart.exists() or time.time()-state.get('charted_at', 0) >= 60
            if state['chart_pending'] and defer_chart:
                state['stop_reason'] = 'chart_pending'
                if progress: progress('Source progress saved; next continuation publishes the pending chart before more intake')
            elif state['chart_pending'] and due and remaining >= 2:
                publish()
            state['complete'] = state['next'] == len(state['jobs']) and not state['chart_pending']
            if state['complete']: state['finished_at'] = time.time()
        except Interrupted:
            state['paused'] = True
        finally:
            space._atomic(path, state)
        return _result(state, context, started)


def drive(index_path, space_cache, source_cache, *, seconds=120, slice_seconds=60, passes=None,
          on_pass=None, **options):
    """Repeat bounded refresh passes until complete, paused, unavailable or out of time.

    Each pass gets at most slice_seconds of the total budget; the result says
    stop_reason='time_budget' when the budget, not the work, ended the run.
    passes=1 is exactly one ordinary refresh (the CLI); the browser's Continue
    chart keeps going for two minutes. on_pass(result) observes every pass;
    options (limit, restart, automatic, sync_index, cancel, progress) go to refresh().
    """
    deadline = time.monotonic() + seconds
    done = 0
    while True:
        budget = min(slice_seconds, seconds) if not done else max(1, min(slice_seconds, deadline - time.monotonic()))
        result = refresh(index_path, space_cache, source_cache, seconds=budget, **options)
        done += 1
        if on_pass:
            on_pass(result)
        if result['complete'] or result['paused'] or result.get('runtime_error') or result.get('index_error'):
            return result
        if passes is not None and done >= passes:
            return result
        if time.monotonic() >= deadline - 2:
            return dict(result, stop_reason='time_budget')


def _result(state, context, started, cached=False):
    more = not state['complete'] or bool(state.get('indexing', {}).get('deferred')) or bool(state.get('index_error'))
    reason = ('paused' if state.get('paused') else 'cached' if cached else
              'runtime_unavailable' if state.get('runtime_error') else
              'index_unavailable' if state.get('index_error') else
              'chart_unavailable' if state.get('chart_error') else
              'index_batch_limit' if state['complete'] and more else
              'complete' if not more else state.get('stop_reason', 'page_limit'))
    command = ['navcom', 'atlas', 'refresh', '--space', '--harvest', '--index', context['index'],
               '--space-cache', context['space'], '--source-cache', context['sources']]
    return dict(schema_version=1, complete=not more, more=more, cached=cached, stop_reason=reason,
        state_path=str(state_path(context['sources'], index_path=context['index'], space_cache=context['space'])),
        seconds=round(time.monotonic()-started, 3), visited=state['next'], total=len(state['jobs']),
        inventory_rows=len(state['projects']), grouping=state['grouping'],
        harvested=state['harvested'], reused=state['reused'], failures=state['failures'],
        skipped=state['skipped'], inventory_truncated=state['truncated'], paused=state.get('paused', False),
        chart_pending=state['chart_pending'], chart_error=state.get('chart_error'),
        chart_schedule=dict(publication_first=state.get('publication_first', False),
                            publication_deferred=state.get('chart_deferred_for_intake', False),
                            reserved_seconds=state.get('chart_reserved_seconds'),
                            measured_seconds=state.get('chart_seconds'),
                            last_attempt_budget=state.get('chart_attempt_budget'),
                            maximum_seconds=MAX_CHART_SECONDS),
        runtime_error=state.get('runtime_error'),
        indexing=state.get('indexing'), index_error=state.get('index_error'),
        destinations=state.get('destinations'), next_command=shlex.join(command) if more else None,
        coverage='Pinned indexed projects; bounded source scopes, not a full disk inventory')
