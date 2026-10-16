"""Native carried-dialogue federation, cached generations and bounded progress."""
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import time

import pytest

import navcom_carried_search as carried
import navcom_ship_context as context
from test_ship_context import ship, require_native, TOOL


def copy_ship(ship, tmp_path, name):
    entity, root, _ = ship
    other = tmp_path / name
    shutil.copytree(root, other)
    result = copy.deepcopy(entity)
    result.update(id='fleet:ship:'+name, label=name, form='archive')
    result['physical']['path'] = str(other)
    return result


def rewrite(ship, text, *, change_catalog=True):
    _, root, catalog = ship
    data = json.loads(catalog.read_text())
    record = data['sessions'][0]
    path = root / record['file']
    payload = json.loads(path.read_text())
    payload['messages'][0]['text'] = text
    raw = json.dumps(payload).encode(); path.write_bytes(raw)
    if change_catalog:
        record['sha256'] = hashlib.sha256(raw).hexdigest()
        catalog.write_text(json.dumps(data))


def test_native_search_exact_open_and_cache_avoid_dialogue_reads(ship, tmp_path, monkeypatch):
    require_native()
    entity, root, catalog = ship
    cache = tmp_path/'query-cache'
    found = carried.search([entity], 'amber', cache)
    assert [h['index'] for h in found['hits']] == [3, 7]
    assert found['coverage']['native_calls'] == 1 and found['coverage']['complete']
    assert found['hits'][0]['ship']['physical'] == entity['physical']
    hit = found['hits'][0]
    ref = hit['context_ref']
    assert ref == dict(ship_id=entity['id'], session_id='session-0', index=3,
                       catalog_sha256=hashlib.sha256(catalog.read_bytes()).hexdigest())
    opened = context.read_context(entity, action='open', ref=ref['session_id'], turn=ref['index'],
                                  expected_catalog=ref['catalog_sha256'])
    assert opened['messages'][0]['text'] == hit['text']
    monkeypatch.setattr(carried, '_run_native', lambda *a, **k: pytest.fail('Cached hit invoked native reader'))
    real_read = context._read
    def metadata_only(root, relative, maximum):
        assert str(relative) == str(context.CATALOG)
        return real_read(root, relative, maximum)
    monkeypatch.setattr(context, '_read', metadata_only)
    again = carried.search([entity], 'amber', cache)
    assert again['cached'] and again['coverage']['native_calls'] == 0
    assert again['coverage']['cached_ships'] == 1 and again['hits'] == found['hits']
    assert all(p.stat().st_mode & 0o777 == 0o600 for p in cache.iterdir())
    assert cache.stat().st_mode & 0o777 == 0o700


def test_zero_hit_cache_and_repeats_advance_unsearched_exact_ships(ship, tmp_path):
    require_native()
    second = copy_ship(ship, tmp_path, 'Second')
    third = copy_ship(ship, tmp_path, 'Third')
    entities = [ship[0], second, third]
    cache = tmp_path/'zero-cache'
    for expected in (1, 2, 3):
        data = carried.search(entities, '--help absent', cache, max_ships=1)
        assert not data['hits'] and data['coverage']['native_calls'] == 1
        assert data['coverage']['searched'] == expected
        assert len(data['next_ship_ids']) == 3-expected
    final = carried.search(entities, '--help absent', cache, max_ships=1)
    assert final['cached'] and final['coverage']['complete'] and final['coverage']['cached_ships'] == 3


def test_native_literal_matching_is_not_replaced_by_another_algorithm(ship, tmp_path):
    require_native()
    for query, indexes in [('storage amber', [3, 7]), ('"amber storage"', []), ('amber OR login', [])]:
        result = carried.search([ship[0]], query, tmp_path/'literal-cache')
        assert [hit['index'] for hit in result['hits']] == indexes


@pytest.mark.parametrize('change', ['catalog', 'record', 'tool', 'bounds'])
def test_changed_native_inputs_or_output_bounds_never_replay_stale_hits(ship, tmp_path, monkeypatch, change):
    require_native()
    tool_dir = tmp_path/'installed-reader'; tool_dir.mkdir()
    shutil.copy2(TOOL, tool_dir/'navcom.py')
    cache = tmp_path/'mutation-cache'
    original = carried.search([ship[0]], 'amber', cache, tool_root=tool_dir)
    assert original['hits']
    kwargs = dict(tool_root=tool_dir)
    if change == 'catalog':
        rewrite(ship, 'Orchard chose teal storage.')
    elif change == 'record':
        rewrite(ship, 'Orchard chose teal storage.', change_catalog=False)
    elif change == 'tool':
        with (tool_dir/'navcom.py').open('a') as f: f.write('\n# New installed reader revision.\n')
    else:
        kwargs.update(limit=1, max_chars=12)
    data = carried.search([ship[0]], 'amber', cache, **kwargs)
    assert data['coverage']['cached_ships'] == 0
    assert data['coverage']['native_calls'] == 1
    if change == 'catalog': assert [h['index'] for h in data['hits']] == [7]
    elif change == 'record':
        assert not data['hits'] and data['coverage']['unavailable_ids'] == [ship[0]['id']]
        assert 'catalog hash' in data['ships'][0]['reason']
    elif change == 'bounds': assert len(data['hits']) == 1 and len(data['hits'][0]['text']) == 12
    else: assert data['hits'] == original['hits']


@pytest.mark.parametrize('change', ['missing', 'record-link', 'catalog-link', 'fifo'])
def test_unavailable_or_redirected_cargo_drops_cached_hit_without_native_read(ship, tmp_path, monkeypatch, change):
    require_native()
    entity, root, catalog = ship; cache=tmp_path/'gone-cache'
    assert carried.search([entity], 'amber', cache)['hits']
    record = root/json.loads(catalog.read_text())['sessions'][0]['file']
    if change == 'missing': record.unlink()
    elif change == 'record-link':
        other = record.with_name('moved.json'); record.rename(other); record.symlink_to(other)
    elif change == 'catalog-link':
        other = catalog.with_name('moved.json'); catalog.rename(other); catalog.symlink_to(other)
    else: record.unlink(); os.mkfifo(record)
    monkeypatch.setattr(carried, '_run_native', lambda *a, **k: pytest.fail('Unsafe cargo reached native reader'))
    result = carried.search([entity], 'amber', cache)
    assert not result['hits'] and result['coverage']['unavailable_ids'] == [entity['id']]
    assert not [p for p in cache.iterdir() if not p.name.endswith('.pending.json')]


@pytest.mark.parametrize('host', ['remote.invalid', None, ''])
def test_remote_identity_never_probes_ship_path_or_loads_tools(ship, tmp_path, monkeypatch, host):
    entity = copy.deepcopy(ship[0]); entity['physical']['host'] = host
    monkeypatch.setattr(carried, '_pin', lambda *a, **k: pytest.fail('Remote path was probed'))
    monkeypatch.setattr(carried, '_adapter_identity', lambda: pytest.fail('Remote loaded tool identity'))
    data = carried.search([entity], 'amber', tmp_path/'remote-cache')
    assert data['coverage']['native_calls'] == 0 and data['coverage']['unavailable_ids'] == [entity['id']]
    assert not data['coverage']['complete'] and 'no local path' in data['ships'][0]['reason']


def test_only_supplied_ship_is_searched_without_archive_substitution(ship, tmp_path):
    require_native()
    archive = copy_ship(ship, tmp_path, 'Stored copy')
    entity = copy.deepcopy(ship[0]); entity['physical']['host'] = 'remote.invalid'
    entity['ship_links'] = [dict(id=archive['id'], relation='archive_of', physical=archive['physical'])]
    result = carried.search([entity], 'amber', tmp_path/'scope-cache')
    assert not result['hits'] and len(result['ships']) == 1
    result = carried.search([archive], 'amber', tmp_path/'scope-cache')
    assert {h['ship_id'] for h in result['hits']} == {archive['id']}
    assert all(h['ship']['form'] == 'archive' for h in result['hits'])


def test_duplicate_or_nonship_entities_are_rejected_before_read(ship, tmp_path, monkeypatch):
    monkeypatch.setattr(carried, '_pin', lambda *a, **k: pytest.fail('Invalid scope reached records'))
    for entities in ([ship[0], ship[0]], [dict(ship[0], kind='planet')]):
        with pytest.raises(ValueError, match='distinct exact ship'):
            carried.search(entities, 'amber', tmp_path/'invalid-cache')


def test_byte_preflight_prevents_native_oversized_record_reads(ship, tmp_path, monkeypatch):
    monkeypatch.setattr(carried, '_run_native', lambda *a, **k: pytest.fail('Over-budget data read'))
    result = carried.search([ship[0]], 'amber', tmp_path/'small-cache', max_record_bytes=30)
    assert not result['hits'] and 'byte bound' in result['ships'][0]['reason']
    assert result['coverage']['native_calls'] == 0


def test_result_generation_change_during_native_call_is_not_cached(ship, tmp_path, monkeypatch):
    require_native()
    original = carried._run_native
    def mutate(*args, **kwargs):
        data = original(*args, **kwargs)
        rewrite(ship, 'New generation of amber storage.')
        return data
    monkeypatch.setattr(carried, '_run_native', mutate)
    result = carried.search([ship[0]], 'amber', tmp_path/'race-cache')
    assert not result['hits'] and 'changed during search' in result['ships'][0]['reason']
    assert not result['coverage']['complete']


def test_global_page_bound_reports_truncation_and_prioritizes_cached_hits(ship, tmp_path):
    require_native()
    other = copy_ship(ship, tmp_path, 'Other')
    cache = tmp_path/'page-cache'
    first = carried.search([ship[0]], 'amber', cache, limit=1)
    assert first['coverage']['truncated'] and first['ships'][0]['next_offset'] == 1
    data = carried.search([other, ship[0]], 'amber', cache, limit=1)
    assert len(data['hits']) == 1 and data['hits'][0]['ship_id'] == ship[0]['id']
    assert data['coverage']['cached_ships'] == 1 and data['coverage']['native_calls'] == 1


def test_timeout_rotates_before_later_pending_ships(ship, tmp_path, monkeypatch):
    require_native()
    other = copy_ship(ship, tmp_path, 'Later')
    original = carried._run_native
    def timeout(entity, *args, **kwargs):
        if entity['id'] == ship[0]['id']:
            raise carried._Deferred('Native carried search reached the sweep time budget.')
        return original(entity, *args, **kwargs)
    monkeypatch.setattr(carried, '_run_native', timeout)
    cache=tmp_path/'progress-cache'
    first=carried.search([ship[0], other], 'amber', cache, max_ships=1)
    assert first['next_ship_ids'] == [other['id'], ship[0]['id']]
    second=carried.search([ship[0], other], 'amber', cache, max_ships=1)
    assert {h['ship_id'] for h in second['hits']} == {other['id']}


def test_real_native_timeout_terminates_child_within_sweep_deadline(ship, tmp_path, monkeypatch):
    # The trusted wrapper is substituted by this fixture only; no ship command
    # is ever accepted by production. The child must not finish a delayed write.
    marker=tmp_path/'should-not-exist'
    delayed = 'import time; time.sleep(1.2); open('+repr(str(marker))+',"w").write("late")'
    monkeypatch.setattr(carried, '_SCRIPT',
        'import subprocess,sys,time; subprocess.Popen([sys.executable,"-c",'+repr(delayed)+']); time.sleep(5)')
    started=time.monotonic()
    data=carried.search([ship[0]], 'amber', tmp_path/'deadline-cache', seconds=0.2)
    assert time.monotonic()-started < 1
    assert data['coverage']['native_calls'] == 1 and data['next_ship_ids'] == [ship[0]['id']]
    time.sleep(1.3)
    assert not marker.exists()


def test_cache_symlink_and_public_cache_permissions_are_rejected(ship, tmp_path):
    target=tmp_path/'target'; target.mkdir()
    link=tmp_path/'linked'; link.symlink_to(target, target_is_directory=True)
    with pytest.raises(OSError): carried.search([ship[0]], 'amber', link)
    with pytest.raises(ValueError, match='private directory'):
        carried.search([ship[0]], 'amber', target)


def test_linked_cache_record_is_not_read_or_overwritten_outside_cache(ship, tmp_path, monkeypatch):
    require_native()
    cache=tmp_path/'linked-record-cache'
    first=carried.search([ship[0]], 'amber', cache)
    record=next(p for p in cache.iterdir() if not p.name.endswith('.pending.json'))
    outside=tmp_path/'outside.json'; outside.write_text('private unrelated bytes')
    record.unlink(); record.symlink_to(outside)
    next_result=carried.search([ship[0]], 'amber', cache)
    assert next_result['coverage']['native_calls'] == 1 and next_result['hits'] == first['hits']
    assert outside.read_text() == 'private unrelated bytes' and not record.is_symlink()
