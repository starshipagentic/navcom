"""Authored replacements travel through ordinary refresh, CLI and related API."""
import json
import os
from pathlib import Path
import shlex
import sqlite3
import subprocess
import sys

import pytest

import navcom_relationships as relationships
import navcom_space as space
from test_space import API, database, git, package


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def products(tmp_path, monkeypatch):
    monkeypatch.setenv('NAVCOM_STARSHIP_ROOT', str(tmp_path / 'no-fleet'))
    monkeypatch.setenv('HERMES_HOME', str(tmp_path / 'no-hermes'))
    monkeypatch.delenv('NAVCOM_FLEET_SNAPSHOT', raising=False)
    monkeypatch.delenv('NAVCOM_FLEET_CONFIG', raising=False)
    roots = []
    for identity, label, prior in [('aurora-v1', 'Aurora Classic', []), ('aurora-v2', 'Aurora Next', ['aurora-v1'])]:
        root = git(tmp_path / 'clients' / 'Orchard' / identity, 'git@example.test:orchard/' + identity + '.git')
        (root / '.navcom-space.json').write_text(json.dumps(dict(id=identity, label=label, kind='planet', supersedes=prior)))
        roots.append(root)
    package(roots[1], name='suite', workspaces=['apps/*'])
    app = package(roots[1] / 'apps' / 'viewer', name='Viewer', scripts={'start': 'node server.js'})
    conn = database([(roots[0], 'Classic scheduling'), (roots[1], 'Next scheduling'), (app, 'Viewer details')])
    index = tmp_path / 'index.sqlite'
    with sqlite3.connect(index) as output:
        conn.backup(output)
    cache = tmp_path / 'space.json'
    catalog = space.refresh(API, conn, cache)
    conn.close()
    return dict(roots=roots, app=app, chart=cache, sources=tmp_path / 'sources', index=index,
                nodes={node['label']: node for node in catalog['entities']})


def cli(*args):
    result = subprocess.run([sys.executable, str(ROOT / 'navcom.py'), *map(str, args)],
                            text=True, capture_output=True, timeout=30,
                            env=dict(os.environ, NAVCOM_NO_SKILLS='1'))
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_cli_refresh_related_and_follow_keep_products_separate(products, navcom, monkeypatch):
    p = products
    before_index = p['index'].read_bytes()
    refreshed = json.loads(cli('atlas', 'refresh', '--space', '--space-cache', p['chart'],
                              '--source-cache', p['sources'], '--index', p['index'], '--json'))
    assert refreshed['coverage']['product_succession']['resolved_edges'] == 1
    before_chart = p['chart'].read_bytes()
    args = ('atlas', 'related', 'Aurora Classic', '--space-cache', p['chart'],
            '--source-cache', p['sources'], '--index', p['index'])
    related = json.loads(cli(*args, '--json'))
    assert related['families'] == [] and related['references'] == []
    assert related['source_total'] == 0 and related['harvest_invocations'] == 0
    relation, = related['declared_relations']
    assert relation['successor']['label'] == 'Aurora Next'
    assert relation['predecessor']['label'] == 'Aurora Classic'
    assert relation['successor']['id'] != relation['predecessor']['id']
    assert relation['evidence']['declarations'][0]['path'].endswith('aurora-v2/.navcom-space.json')
    follow = shlex.split(relation['successor']['show_command'])
    shown = json.loads(cli(*follow[1:], '--index', p['index'], '--json'))
    assert shown['center']['id'] == relation['successor']['id']
    assert set(shown['center']['conversation_collections']).isdisjoint(
        related['center']['conversation_collections'])
    text = cli(*args)
    assert 'Aurora Next supersedes Aurora Classic' in text and 'No replacement date' in text
    from navcom_web import WebApp
    monkeypatch.setenv('NAVCOM_SPACE_CACHE', str(p['chart']))
    monkeypatch.setenv('NAVCOM_SOURCES_CACHE', str(p['sources']))
    assert WebApp(navcom, p['index']).get(None, '/api/space/related', {'within': ['Aurora Classic']}) == related
    assert p['chart'].read_bytes() == before_chart and p['index'].read_bytes() == before_index
    assert not p['sources'].exists()


def test_exact_child_scope_does_not_inherit_parent_replacement(products, monkeypatch):
    p = products
    monkeypatch.setattr(relationships, '_run', lambda *a: pytest.fail('No native analysis needed'))
    child = relationships.related(p['chart'], p['sources'], 'Viewer')
    assert child['declared_relations'] == []
    parent = relationships.related(p['chart'], p['sources'], 'Aurora Next')
    assert len(parent['declared_relations']) == 1
    assert relationships.related(p['chart'], p['sources'], 'Aurora Next', query='unrelated')['declared_relations'] == []
    assert len(relationships.related(p['chart'], p['sources'], 'Aurora Next', query='aurora-v1')['declared_relations']) == 1


def test_native_failure_leaves_declared_links_readable_and_discloses_gap(products, monkeypatch):
    p = products
    chart = json.loads(p['chart'].read_text())
    node = next(n for n in chart['entities'] if n['label'] == 'Aurora Next')
    node['source_scopes'] = [dict(source_id='unavailable', paths=['.'])]
    p['chart'].write_text(json.dumps(chart))
    def unavailable(*args):
        raise ValueError('Retained source is unavailable')
    monkeypatch.setattr(relationships, '_run', unavailable)
    result = relationships.related(p['chart'], p['sources'], node['id'])
    assert len(result['declared_relations']) == 1
    assert result['source_errors'] == ['Retained source is unavailable']
    assert result['families'] == [] and result['references'] == []


def test_missing_target_is_unresolved_without_manufacturing_a_place(products):
    p = products
    path = p['roots'][1] / '.navcom-space.json'
    value = json.loads(path.read_text())
    value['supersedes'] = ['never-seen']
    path.write_text(json.dumps(value))
    with sqlite3.connect(p['index']) as conn:
        catalog = space.refresh(API, conn, p['chart'])
    result = relationships.related(p['chart'], p['sources'], 'Aurora Next')
    assert result['declared_relations'] == []
    assert result['declaration_diagnostics'][0]['target_declared_id'] == 'never-seen'
    assert not any(n.get('declared_id') == 'never-seen' for n in catalog['entities'])


def test_invalid_declaration_without_identity_reports_its_exact_place(products):
    p = products
    path = p['roots'][1] / '.navcom-space.json'
    path.write_text(json.dumps(dict(label='Incomplete replacement', supersedes=['aurora-v1'])))
    with sqlite3.connect(p['index']) as conn:
        space.refresh(API, conn, p['chart'])
    result = relationships.related(p['chart'], p['sources'], 'Incomplete replacement')
    assert result['declared_relations'] == []
    issue, = result['declaration_diagnostics']
    assert issue['code'] == 'invalid' and issue['paths'] == [str(path)]
    child = relationships.related(p['chart'], p['sources'], 'Viewer')
    assert child['declaration_diagnostics'] == []
