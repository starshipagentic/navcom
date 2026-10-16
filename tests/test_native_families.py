"""Reuse native lineage; isolate and bound the optional provider runtime."""
import json
from pathlib import Path
import shutil
import time

import pytest

import navcom_native_families as families


@pytest.mark.skipif(not shutil.which('starforge'), reason='Optional native Starforge required')
def test_native_contextual_family_namespace_exclusions_and_disk_cache(tmp_path):
    paths = ['engines/v1', 'engines/v2', 'engines/v3', 'LABS/exp91', 'LABS/exp92']
    cache = tmp_path / 'families'
    first = families.analyze(paths, 'unfamiliar-optics', cache)
    assert first['status'] == 'available' and not first['cached']
    assert len(first['families']) == 1
    assert [m['path'] for m in first['families'][0]['members']] == paths[:3]
    assert first['families'][0]['engine'] == families.ENGINE
    memo = cache / (first['fingerprint'] + '.json')
    before = memo.stat().st_mtime_ns
    second = families.analyze(paths, 'unfamiliar-optics', cache)
    assert second['cached'] and second['fingerprint'] == first['fingerprint']
    assert memo.stat().st_mtime_ns == before
    third = families.analyze(paths + ['engines/v4'], 'unfamiliar-optics', cache)
    assert not third['cached'] and third['fingerprint'] != first['fingerprint']
    assert len(third['families'][0]['members']) == 4


def test_native_input_budget_has_no_fallback_classifier(tmp_path):
    data = families.analyze(['engine/v' + str(i) for i in range(families.MAX_DIRECTORIES + 1)], 'Bounded', tmp_path)
    assert data['status'] == 'unavailable' and data['families'] == []
    assert not list(tmp_path.iterdir())


def test_total_deadline_includes_native_runtime_resolution(tmp_path, monkeypatch):
    launcher = tmp_path / 'slow-runtime'
    launcher.write_text('#!/bin/sh\nsleep 30\n')
    launcher.chmod(0o700)
    monkeypatch.setenv('NAVCOM_STARFORGE_PYTHON', str(launcher))
    started = time.monotonic()
    data = families.analyze(['engine/v1', 'engine/v2'], 'Bounded', tmp_path / 'cache', seconds=.2)
    assert time.monotonic() - started < 2
    assert data['status'] == 'unavailable' and data['families'] == []
    assert 'TimeoutExpired' in data['omitted'][0]
    assert not (tmp_path / 'cache').exists()
