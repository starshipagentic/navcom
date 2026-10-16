"""Shared native sources never make one chart overwrite another chart's cursor."""

import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading

import pytest

import navcom_chart_refresh as refresh
from test_space_refresh_worker import setup


def shared_setup(tmp_path, monkeypatch):
    index, chart, cache, calls, rows, original = setup(tmp_path, monkeypatch)
    harvested = set()
    def run(request, *args):
        if request['action'] == 'intake':
            calls.append(request)
            root = request['job']['root']
            cached = root in harvested
            harvested.add(root)
            return dict(analyzed_sources=int(not cached), cached_sources=int(cached), published=not cached, skipped=[])
        if request['action'] == 'chart':
            calls.append(request)
            Path(request['space']).write_text('{}')
            return dict(destinations=3)
        return original(request, *args)
    monkeypatch.setattr(refresh, '_run', run)
    return index, chart, tmp_path/'other-chart.json', cache, calls, rows


def test_interleaved_charts_resume_independent_pinned_cursors_and_reuse_sources(tmp_path, monkeypatch):
    index, first, second, cache, calls, rows = shared_setup(tmp_path, monkeypatch)
    a1 = refresh.refresh(index, first, cache, limit=1)
    saved = Path(a1['state_path']).read_bytes()
    b1 = refresh.refresh(index, second, cache, limit=1)
    assert a1['state_path'] != b1['state_path']
    assert Path(a1['state_path']).read_bytes() == saved
    assert a1['visited'] == b1['visited'] == 1
    assert a1['harvested'] == 1 and b1['harvested'] == 0 and b1['reused'] == 1

    # Neither chart gets a fresh inventory just because the other one ran.
    rows.insert(0, dict(label='/fixture/new', collection='projects:new'))
    a2 = refresh.refresh(index, first, cache, limit=1)
    b2 = refresh.refresh(index, second, cache, limit=1)
    assert a2['visited'] == b2['visited'] == 2 and a2['total'] == b2['total'] == 3
    assert a2['harvested'] == 2 and b2['reused'] == 2
    assert [r['job']['root'] for r in calls if r['action']=='intake'] == [
        '/fixture/project-0', '/fixture/project-0', '/fixture/project-1', '/fixture/project-1']
    assert sum(r['action']=='inventory' for r in calls) == 2
    assert refresh.refresh(index, first, cache, limit=1)['complete']
    assert refresh.refresh(index, second, cache, limit=1)['complete']
    count = len(calls)
    assert refresh.refresh(index, first, cache, automatic=True)['cached']
    assert refresh.refresh(index, second, cache, automatic=True)['cached']
    assert len(calls) == count


def test_legacy_cursor_migrates_only_to_matching_context_and_keeps_pause(tmp_path, monkeypatch):
    index, first, second, cache, calls, rows = shared_setup(tmp_path, monkeypatch)
    refresh.refresh(index, first, cache, limit=1)
    cancel = threading.Event(); cancel.set()
    paused = refresh.refresh(index, first, cache, cancel=cancel)
    path = Path(paused['state_path'])
    legacy = refresh.state_path(cache)
    legacy.write_bytes(path.read_bytes()); original = legacy.read_bytes(); path.unlink()
    other = refresh.refresh(index, second, cache, limit=1)
    assert not other['paused'] and other['visited'] == 1
    assert not path.exists() and legacy.read_bytes() == original
    count = len(calls)
    restored = refresh.refresh(index, first, cache, automatic=True)
    assert restored['paused'] and restored['visited'] == 1
    assert len(calls) == count and path.read_bytes() == original and legacy.read_bytes() == original
    assert refresh.refresh(index, first, cache, limit=1)['visited'] == 2
    assert json.loads(Path(other['state_path']).read_text())['next'] == 1


def test_context_paths_resolve_aliases_and_index_identity_is_separate(tmp_path, monkeypatch):
    index, first, second, cache, calls, rows = shared_setup(tmp_path, monkeypatch)
    alias = tmp_path/'alias'; alias.symlink_to(tmp_path, target_is_directory=True)
    direct = refresh.refresh(index, first, cache, limit=1)
    resumed = refresh.refresh(alias/index.name, alias/first.name, alias/cache.name, limit=1)
    assert resumed['state_path'] == direct['state_path'] and resumed['visited'] == 2
    other_index = tmp_path/'other-index.sqlite'; other_index.touch()
    other = refresh.refresh(other_index, first, cache, limit=1)
    assert other['state_path'] != direct['state_path'] and other['visited'] == 1


def test_each_chart_keeps_shared_source_lock_and_policy_version_invalidation(tmp_path, monkeypatch):
    index, first, second, cache, calls, rows = shared_setup(tmp_path, monkeypatch)
    old = refresh.refresh(index, first, cache, limit=1)
    count = len(calls)
    with refresh.state_path(cache).with_suffix('.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ValueError, match='Another chart intake'):
            refresh.refresh(index, second, cache)
    assert len(calls) == count
    # Context hashing doesn't hide a changed intake-policy/schema version.
    monkeypatch.setattr(refresh, 'VERSION', refresh.VERSION + 1)
    rows.insert(0, dict(label='/fixture/new', collection='projects:new'))
    reset = refresh.refresh(index, first, cache, limit=1)
    assert reset['state_path'] == old['state_path'] and reset['visited'] == 1 and reset['total'] == 4
    assert [r for r in calls if r['action']=='intake'][-1]['job']['root'] == '/fixture/new'


@pytest.mark.skipif(not shutil.which('starforge'), reason='Installed native Starforge required')
def test_public_cli_interleaves_two_charts_with_one_native_source_cache(navcom, tmp_path, monkeypatch):
    from test_atlas import add
    monkeypatch.setattr(navcom, 'INDEX_READ_ONLY', False)
    index = tmp_path/'index.sqlite'
    conn = navcom.open_index(index)
    for name in ('spectrometer', 'field-camera'):
        root = tmp_path/'projects'/name; root.mkdir(parents=True)
        subprocess.run(['git', 'init', '-q', str(root)], check=True)
        (root/'README.md').write_text('# '+name+'\nMarmot calibration and optical measurement.\n')
        (root/'instrument.py').write_text('"""Marmot calibration measurement."""\n'+
            'def calibrate(value):\n'+''.join(f'    reading_{i}=value+{i}\n' for i in range(25))+
            '    return reading_24\n')
        add(navcom, conn, tmp_path/(name+'.jsonl'), name+' calibration', 'marmot measurement', str(root))
    conn.close()
    cache = tmp_path/'sources'; first = tmp_path/'first.json'; second = tmp_path/'second.json'
    env = dict(os.environ, NAVCOM_STARSHIP_ROOT=str(tmp_path/'no-fleet'), HERMES_HOME=str(tmp_path/'no-hermes'))
    env.pop('NAVCOM_FLEET_SNAPSHOT', None); env.pop('NAVCOM_FLEET_CONFIG', None)
    def cli(chart):
        command = [sys.executable, str(Path(__file__).resolve().parents[1]/'navcom.py'),
            'atlas', 'refresh', '--space', '--harvest', '--limit', '1', '--seconds', '60',
            '--index', str(index), '--source-cache', str(cache), '--space-cache', str(chart), '--json']
        result = subprocess.run(command, capture_output=True, text=True, timeout=65, env=env)
        assert result.returncode == 0, result.stderr
        data = json.loads(result.stdout)
        assert not data['failures'] and not data['chart_error']
        return data
    a1 = cli(first); pointer = (cache/'current.json').read_bytes()
    b1 = cli(second)
    assert (cache/'current.json').read_bytes() == pointer
    assert a1['visited'] == b1['visited'] == 1 and a1['total'] == b1['total'] == 2
    assert a1['harvested'] == 1 and b1['harvested'] == 0 and b1['reused'] == 1
    a2 = cli(first); pointer = (cache/'current.json').read_bytes()
    b2 = cli(second)
    assert (cache/'current.json').read_bytes() == pointer
    assert a2['complete'] and b2['complete'] and a2['visited'] == b2['visited'] == 2
    assert a2['harvested'] == 2 and b2['harvested'] == 0 and b2['reused'] == 2
    assert a1['state_path'] == a2['state_path'] != b2['state_path'] == b1['state_path']
    for chart in (first, second):
        publication = json.loads(chart.read_text())
        assert publication['coverage']['harvested_sources'] == 2
        assert {'spectrometer','field-camera'} <= {n['label'] for n in publication['entities']}
