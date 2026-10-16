"""Slow native publication gets its own continuation without resetting intake."""

import json
import threading
import time
from types import SimpleNamespace

import pytest

import navcom_chart_refresh as refresh
from test_space_refresh_worker import setup


def slow_schedule(tmp_path, monkeypatch, *, chart_seconds=25, intake_seconds=20,
                  runtime_seconds=0, inventory_seconds=0):
    index, chart, cache, calls, rows, run = setup(tmp_path, monkeypatch, projects=5)
    chart.write_text('{"previous_chart":true}')
    clock = [1000.0]
    budgets = []
    monkeypatch.setattr(refresh, 'time', SimpleNamespace(
        monotonic=lambda: clock[0], time=lambda: clock[0]))
    def timed(request, seconds, cancel=None, progress=None):
        if cancel and cancel.is_set():
            raise refresh.Interrupted('Paused')
        duration = {'intake': intake_seconds, 'chart': chart_seconds,
                    'runtime': runtime_seconds, 'inventory': inventory_seconds}.get(request['action'], 0)
        budgets.append((request['action'], seconds))
        clock[0] += min(seconds, duration)
        if seconds < duration:
            raise TimeoutError('Operation reached its time budget')
        return run(request, seconds, cancel, progress)
    monkeypatch.setattr(refresh, '_run', timed)
    return index, chart, cache, calls, rows, clock, budgets


def test_slow_chart_gets_publication_first_continuation_then_measured_reserve(tmp_path, monkeypatch):
    index, chart, cache, calls, rows, clock, budgets = slow_schedule(tmp_path, monkeypatch)
    first = refresh.refresh(index, chart, cache, seconds=60, limit=2)
    assert first['visited'] == 2 and first['harvested'] == 2
    assert first['chart_pending'] and first['chart_error']
    assert first['seconds'] == 60 and budgets[-1] == ('chart', 20)
    assert json.loads(chart.read_text()) == {'previous_chart': True}
    pinned = json.loads(refresh.state_path(cache, index_path=index, space_cache=chart).read_text())

    # A changing inventory cannot replace the queue during publication retry.
    rows.insert(0, dict(label='/fixture/new-project', collection='projects:new'))
    count = len(budgets)
    second = refresh.refresh(index, chart, cache, seconds=60)
    assert budgets[count:] == [('chart', 45)]
    assert second['visited'] == first['visited'] and second['harvested'] == 2
    assert second['more'] and second['stop_reason'] == 'chart_published'
    assert not second['chart_pending'] and second['chart_error'] is None
    assert second['seconds'] == 25
    assert second['chart_schedule']['measured_seconds'] == 25
    assert second['chart_schedule']['publication_first']
    saved = json.loads(refresh.state_path(cache, index_path=index, space_cache=chart).read_text())
    assert saved['jobs'] == pinned['jobs'] and saved['projects'] == pinned['projects']
    assert saved['next'] == pinned['next']

    # Once a normal chart checkpoint is due, learned publication cost leaves
    # enough time after the next bounded source job instead of repeating failure.
    clock[0] += 61
    third = refresh.refresh(index, chart, cache, seconds=60, limit=1)
    assert third['visited'] == 3 and third['harvested'] == 3
    assert third['chart_schedule']['reserved_seconds'] == 31
    assert not third['chart_schedule']['publication_first']
    assert not third['chart_pending'] and third['chart_error'] is None
    assert third['seconds'] == 45
    assert [call['job']['root'] for call in calls if call['action'] == 'intake'] == [
        '/fixture/project-0', '/fixture/project-1', '/fixture/project-2']
    assert len([call for call in calls if call['action'] == 'inventory']) == 1


def test_short_publication_retry_stays_bounded_and_does_not_advance_sources(tmp_path, monkeypatch):
    index, chart, cache, calls, rows, clock, budgets = slow_schedule(tmp_path, monkeypatch)
    first = refresh.refresh(index, chart, cache, seconds=60, limit=2)
    count = len(budgets)
    second = refresh.refresh(index, chart, cache, seconds=10)
    assert budgets[count:] == [('chart', 10)]
    assert second['seconds'] == 10 and second['visited'] == first['visited']
    assert second['chart_pending'] and second['chart_error']
    assert second['more'] and second['stop_reason'] == 'chart_unavailable'
    assert json.loads(chart.read_text()) == {'previous_chart': True}


def test_total_deadline_without_chart_error_also_prioritizes_publication(tmp_path, monkeypatch):
    index, chart, cache, calls, rows, clock, budgets = slow_schedule(tmp_path, monkeypatch)
    refresh.refresh(index, chart, cache, seconds=60, limit=2)
    path = refresh.state_path(cache, index_path=index, space_cache=chart)
    state = json.loads(path.read_text())
    state.pop('chart_error')
    state['stop_reason'] = 'time_budget'
    path.write_text(json.dumps(state))
    count = len(budgets)
    result = refresh.refresh(index, chart, cache, seconds=60)
    assert budgets[count:] == [('chart', 45)]
    assert result['visited'] == 2 and not result['chart_pending']


def test_paused_publication_retry_keeps_priority_and_requires_explicit_continue(tmp_path, monkeypatch):
    index, chart, cache, calls, rows, clock, budgets = slow_schedule(tmp_path, monkeypatch)
    refresh.refresh(index, chart, cache, seconds=60, limit=2)
    path = refresh.state_path(cache, index_path=index, space_cache=chart)
    state = json.loads(path.read_text())
    state.pop('chart_error')
    state['stop_reason'] = 'time_budget'
    path.write_text(json.dumps(state))
    cancel = threading.Event()
    cancel.set()
    paused = refresh.refresh(index, chart, cache, cancel=cancel)
    assert paused['paused'] and paused['visited'] == 2 and paused['chart_pending']
    count = len(budgets)
    assert refresh.refresh(index, chart, cache, automatic=True)['paused']
    assert len(budgets) == count
    cancel.clear()
    resumed = refresh.refresh(index, chart, cache, cancel=cancel)
    assert budgets[count:] == [('chart', 45)]
    assert not resumed['paused'] and resumed['visited'] == 2 and not resumed['chart_pending']


def test_measured_reserve_survives_new_sweep_but_never_exceeds_total_budget(tmp_path, monkeypatch):
    index, chart, cache, calls, rows, clock, budgets = slow_schedule(tmp_path, monkeypatch)
    refresh.refresh(index, chart, cache, seconds=60, limit=2)
    refresh.refresh(index, chart, cache, seconds=60)
    result = refresh.refresh(index, chart, cache, seconds=10, restart=True)
    assert result['visited'] == 0 and result['seconds'] <= 10
    assert result['chart_schedule']['reserved_seconds'] == 0
    assert result['chart_schedule']['publication_deferred']
    assert result['chart_schedule']['measured_seconds'] == 25


def test_slow_chart_and_native_job_alternate_without_starving_either_phase(tmp_path, monkeypatch):
    index, chart, cache, calls, rows, clock, budgets = slow_schedule(
        tmp_path, monkeypatch, chart_seconds=40, intake_seconds=18, runtime_seconds=3)
    first = refresh.refresh(index, chart, cache, seconds=60, limit=2)
    assert first['visited'] == 2 and first['chart_pending'] and first['chart_error']
    published = refresh.refresh(index, chart, cache, seconds=60)
    assert published['visited'] == 2 and published['chart_schedule']['measured_seconds'] == 40
    assert not published['chart_pending']
    for expected_cursor in range(3, 6):
        count = len(budgets)
        intake = refresh.refresh(index, chart, cache, seconds=60, limit=1)
        assert budgets[count:] == [('runtime', 10), ('intake', 20)]
        assert intake['visited'] == expected_cursor and intake['seconds'] == 21
        assert intake['chart_pending'] and intake['chart_schedule']['publication_deferred']
        assert intake['chart_schedule']['reserved_seconds'] == 0
        assert not intake['failures']
        count = len(budgets)
        publication = refresh.refresh(index, chart, cache, seconds=60)
        assert budgets[count:] == [('chart', 45)]
        assert publication['visited'] == expected_cursor and publication['seconds'] == 40
        assert not publication['chart_pending']
    assert publication['complete'] and publication['harvested'] == 5
    assert [call['job']['root'] for call in calls if call['action'] == 'intake'] == [
        f'/fixture/project-{index}' for index in range(5)]
    assert len([call for call in calls if call['action'] == 'inventory']) == 1


def test_inventory_and_runtime_cost_cannot_consume_the_reserved_job_window(tmp_path, monkeypatch):
    index, chart, cache, calls, rows, clock, budgets = slow_schedule(
        tmp_path, monkeypatch, intake_seconds=18, runtime_seconds=9, inventory_seconds=25)
    result = refresh.refresh(index, chart, cache, seconds=60, limit=1)
    assert budgets == [('inventory', 30), ('runtime', 10), ('intake', 20)]
    assert result['visited'] == 1 and result['seconds'] == 52 and not result['failures']
    assert result['chart_pending'] and result['chart_schedule']['publication_deferred']
    assert result['chart_schedule']['reserved_seconds'] == 0
    retry = refresh.refresh(index, chart, cache, seconds=60)
    assert budgets[-1] == ('chart', 45)
    assert retry['visited'] == 1 and not retry['chart_pending']


def test_real_chart_worker_pause_terminates_and_preserves_saved_cursor(tmp_path, monkeypatch):
    actual_run = refresh._run
    index, chart, cache, calls, rows, run = setup(tmp_path, monkeypatch, projects=2)
    refresh.refresh(index, chart, cache, limit=1)
    path = refresh.state_path(cache, index_path=index, space_cache=chart)
    state = json.loads(path.read_text())
    state.update(chart_pending=True, chart_error='Prior chart timeout')
    path.write_text(json.dumps(state))
    monkeypatch.setattr(refresh, '_run', actual_run)
    monkeypatch.setattr(refresh, 'SCRIPT', 'import time;time.sleep(10)')
    cancel = threading.Event()
    timer = threading.Timer(.1, cancel.set)
    timer.start()
    began = time.monotonic()
    try:
        result = refresh.refresh(index, chart, cache, seconds=3, cancel=cancel)
    finally:
        timer.cancel()
        timer.join()
    assert time.monotonic()-began < 2
    assert result['paused'] and result['visited'] == 1 and result['chart_pending']
    assert json.loads(path.read_text())['next'] == 1
