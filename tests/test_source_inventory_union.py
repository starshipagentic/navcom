"""Native harvests enter the same queue without invented place ownership."""
import json
import sqlite3
from pathlib import Path

import pytest

import navcom_chart_refresh as refresh
import navcom_source_discovery as discovery


def fixture(monkeypatch, tmp_path):
    root = tmp_path / 'saved-project'
    root.mkdir()
    (root / 'README.md').write_text('# Preserved project\n')
    index = tmp_path / 'index.sqlite'
    sqlite3.connect(index).close()
    origin = dict(kind='starforge', name='saved-project', galaxy='original-account', last_scan='2026-01-01')
    native = dict(label=str(root), collection=None, source_origin=origin)
    monkeypatch.setattr('navcom_starforge_inventory.inventory', lambda: dict(nodes=[native], coverage=dict(available=True, rows=1)))
    class Indexed:
        def __init__(self, api): pass
        def view(self, conn, params):
            return dict(nodes=[dict(label=str(root), collection='projects:exact')], more=False)
    monkeypatch.setattr(discovery, 'Discovery', Indexed)
    return root, index, native


def test_native_and_conversation_rows_share_root_and_keep_exact_membership(monkeypatch, tmp_path):
    root, index, native = fixture(monkeypatch, tmp_path)
    result = discovery.project_inventory(None, index)
    grouped = discovery.group_projects(result['nodes'])
    assert len(grouped['jobs']) == 1
    source = discovery.discover(None, index, tmp_path/'cache', projects=grouped['jobs'][0]['projects'])['sources'][0]
    assert source['source_origins'] == [native['source_origin']]
    assert source['conversation_collection'] == 'projects:exact'
    assert source['conversation_collections'] == ['projects:exact']
    assert source['conversation_projects'] == [dict(path=str(root), collection='projects:exact')]


def test_native_only_discovery_needs_no_index_and_does_not_invent_collections(monkeypatch, tmp_path):
    root, index, native = fixture(monkeypatch, tmp_path)
    result = discovery.discover(None, tmp_path/'absent', tmp_path/'cache', inventory_kind='starforge')
    source = result['sources'][0]
    assert source['root'] == str(root)
    assert source['conversation_collection'] is None
    assert source['conversation_collections'] == []
    assert source['conversation_projects'] == []
    assert source['source_origins'] == [native['source_origin']]
    assert result['coverage']['inventory_origins']['starforge']['available']


def test_collection_scope_never_imports_unassigned_native_roots(monkeypatch, tmp_path):
    root, index, native = fixture(monkeypatch, tmp_path)
    monkeypatch.setattr('navcom_starforge_inventory.inventory', lambda: pytest.fail('Scoped discovery read unrelated inventory'))
    result = discovery.discover(None, index, tmp_path/'cache', within='projects:exact', inventory_kind='all')
    assert result['sources'][0]['conversation_collections'] == ['projects:exact']
    assert 'source_origins' not in result['sources'][0]
    with pytest.raises(ValueError, match='collection scope'):
        discovery.project_inventory(None, index, within='projects:exact', inventory='starforge')


def test_chart_worker_pins_same_combined_inventory(monkeypatch, tmp_path):
    root, index, native = fixture(monkeypatch, tmp_path)
    result = refresh._worker(dict(action='inventory', index=str(index)))
    assert result['projects'][0] == native
    assert len(result['jobs']) == 1
    assert result['grouping']['inventory_origins']['starforge']['available']


def test_upgraded_policy_keeps_explicit_pause(monkeypatch, tmp_path):
    from test_space_refresh_worker import setup
    index, chart, cache, calls, rows, run = setup(tmp_path, monkeypatch)
    result = refresh.refresh(index, chart, cache, limit=1)
    path = Path(result['state_path'])
    state = json.loads(path.read_text())
    state.update(paused=True, version=refresh.VERSION-1)
    path.write_text(json.dumps(state))
    before = len(calls)
    assert refresh.refresh(index, chart, cache, automatic=True)['paused']
    assert len(calls) == before
    assert not refresh.refresh(index, chart, cache, limit=1)['paused']


def test_unavailable_inventories_never_claim_full_coverage(monkeypatch, tmp_path):
    monkeypatch.setattr('navcom_starforge_inventory.inventory', lambda: dict(nodes=[], coverage=dict(available=False)))
    result = discovery.discover(None, tmp_path/'absent', tmp_path/'cache', inventory_kind='all')
    assert not result['coverage']['full_inventory']
    assert not result['sources']


def test_legacy_paused_policy_upgrade_remains_paused(monkeypatch, tmp_path):
    from test_space_refresh_worker import setup
    index, chart, cache, calls, rows, run = setup(tmp_path, monkeypatch)
    result = refresh.refresh(index, chart, cache, limit=1)
    path = Path(result['state_path'])
    state = json.loads(path.read_text())
    state.update(paused=True, version=refresh.VERSION-1)
    refresh.state_path(cache).write_text(json.dumps(state))
    path.unlink()
    before = len(calls)
    assert refresh.refresh(index, chart, cache, automatic=True)['paused']
    assert len(calls) == before
    assert not refresh.refresh(index, chart, cache, limit=1)['paused']
