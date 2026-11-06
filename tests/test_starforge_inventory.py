"""Native catalog inventory is optional, bounded and strictly read-only."""
import hashlib
import json
from pathlib import Path
import shutil
import time

import pytest

import navcom_starforge_inventory as adapter


@pytest.fixture
def native_catalog(tmp_path, monkeypatch):
    if not shutil.which('starforge'):
        pytest.skip('Optional native Starforge runtime required')
    directory = tmp_path / 'native'
    directory.mkdir()
    monkeypatch.setenv('STARFORGE_GLOBAL_DIR', str(directory))
    monkeypatch.delenv('NAVCOM_STARFORGE_PYTHON', raising=False)
    return directory / 'catalog.json'


def save_catalog(path, rows):
    path.write_text(json.dumps({'projects': {str(i + 1): row for i, row in enumerate(rows)},
                                'gems': {}}))


def test_native_inventory_unfamiliar_roots_provenance_and_no_writes(native_catalog, tmp_path):
    first = tmp_path / 'quartz-library'
    second = tmp_path / 'amber-app'
    first.mkdir(); second.mkdir()
    save_catalog(native_catalog, [
        {'name': 'Quartz', 'path': str(first), 'galaxy': 'native-libraries', 'last_scan': '2026-01-02',
         'summary': 'This field is intentionally not exported by intake.'},
        {'name': 'Amber', 'path': str(second), 'galaxy': 'native-tools', 'last_scan': '2026-01-03'},
    ])
    before = (native_catalog.stat().st_mtime_ns, hashlib.sha256(native_catalog.read_bytes()).hexdigest())
    result = adapter.inventory()
    assert result['coverage']['available'] and result['coverage']['complete']
    assert result['coverage']['engine'] == adapter.ENGINE
    assert [node['label'] for node in result['nodes']] == [str(second), str(first)]
    assert all(node['collection'] is None for node in result['nodes'])
    assert result['nodes'][0]['source_origin'] == {
        'kind': 'starforge', 'name': 'Amber', 'galaxy': 'native-tools', 'last_scan': '2026-01-03',
        'catalog': str(native_catalog), 'root_status': 'directory',
    }
    assert 'summary' not in json.dumps(result)
    again = adapter.inventory()
    assert again == result
    assert (native_catalog.stat().st_mtime_ns, hashlib.sha256(native_catalog.read_bytes()).hexdigest()) == before
    assert sorted(p.name for p in native_catalog.parent.iterdir()) == ['catalog.json']


def test_missing_catalog_or_native_directory_is_not_created(native_catalog, monkeypatch, tmp_path):
    result = adapter.inventory()
    assert not result['coverage']['available'] and result['nodes'] == []
    assert not native_catalog.exists()
    absent = tmp_path / 'not-created' / 'nested'
    monkeypatch.setenv('STARFORGE_GLOBAL_DIR', str(absent))
    result = adapter.inventory()
    assert not result['coverage']['available']
    assert not absent.parent.exists()


def test_invalid_paths_disclosed_missing_roots_preserved(native_catalog, tmp_path):
    missing = tmp_path / 'parked-device' / 'project'
    file = tmp_path / 'not-a-project'
    file.write_text('ordinary file')
    save_catalog(native_catalog, [
        {'name': 'a-missing', 'path': str(missing)},
        {'name': 'b-file', 'path': str(file)},
        {'name': 'c-relative', 'path': 'relative/project'},
        {'name': 'd-control', 'path': '/tmp/project\nunsafe'},
        {'name': 'e-invalid', 'path': ['not', 'a', 'path']},
        {'name': 'f-duplicate', 'path': str(missing)},
        {'name': 'g-too-long', 'path': '/' + 'a' * 4096},
    ])
    result = adapter.inventory()
    assert [node['label'] for node in result['nodes']] == [str(missing), str(file)]
    coverage = result['coverage']
    assert coverage['available'] and not coverage['complete']
    assert coverage['invalid_paths'] == 4 and coverage['duplicate_paths'] == 1
    assert coverage['missing_roots'] == 1 and coverage['non_directory_roots'] == 1
    assert result['nodes'][0]['source_origin']['root_status'] == 'missing'


def test_native_order_and_2000_row_budget(native_catalog, tmp_path):
    save_catalog(native_catalog, [dict(name=f'project-{i:04}', path=str(tmp_path)) for i in range(2000, -1, -1)])
    result = adapter.inventory()
    coverage = result['coverage']
    assert coverage['available'] and coverage['truncated'] and not coverage['complete']
    assert coverage['total_projects'] == 2001 and coverage['considered_projects'] == 2000
    assert result['nodes'][0]['source_origin']['name'] == 'project-0000'
    assert coverage['duplicate_paths'] == 1999
    with pytest.raises(ValueError, match='2000'):
        adapter.inventory(limit=2001)


@pytest.mark.parametrize('contents', ['{', '[]', '{"projects": []}', '{"projects":{"1":{"name":[]}}}'])
def test_bad_catalog_is_optional_and_unchanged(native_catalog, contents):
    native_catalog.write_text(contents)
    result = adapter.inventory()
    assert not result['coverage']['available'] and result['nodes'] == []
    assert native_catalog.read_text() == contents


def test_oversized_catalog_and_symlink_are_rejected_without_mutation(native_catalog, tmp_path):
    with native_catalog.open('wb') as handle:
        handle.truncate(adapter.MAX_CATALOG_BYTES + 1)
    result = adapter.inventory()
    assert not result['coverage']['available']
    assert native_catalog.stat().st_size == adapter.MAX_CATALOG_BYTES + 1
    native_catalog.unlink()
    elsewhere = tmp_path / 'other.json'
    save_catalog(elsewhere, [])
    native_catalog.symlink_to(elsewhere)
    assert not adapter.inventory()['coverage']['available']
    assert elsewhere.read_text() == '{"projects": {}, "gems": {}}'


def test_runtime_resolution_is_optional_and_inside_total_deadline(tmp_path, monkeypatch):
    launcher = tmp_path / 'slow-runtime'
    launcher.write_text('#!/bin/sh\nsleep 30\n')
    launcher.chmod(0o700)
    monkeypatch.setenv('NAVCOM_STARFORGE_PYTHON', str(launcher))
    started = time.monotonic()
    result = adapter.inventory(seconds=.2)
    assert time.monotonic() - started < 2
    assert not result['coverage']['available'] and result['nodes'] == []
    assert 'TimeoutError' in result['coverage']['limitations'][0]
    monkeypatch.setenv('NAVCOM_STARFORGE_PYTHON', str(tmp_path / 'not-installed'))
    assert not adapter.inventory()['coverage']['available']
