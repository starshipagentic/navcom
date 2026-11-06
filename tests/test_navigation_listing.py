"""Navigator lists use the existing cached CLI scope, without evidence retrieval."""
import json
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

import navcom_navigation as navigation
import navcom_space


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def chart(tmp_path):
    def node(identity, kind, parent):
        return dict(id=identity, label=identity, kind=kind, parent_id=parent,
                    position=dict(x=0, y=0), locations=[], evidence=[], examples=[],
                    source_scopes=[], source_ids=[], conversation_collections=[])
    rows = [('galaxy:owner', 'galaxy', None), ('system:orchard', 'system', 'galaxy:owner'),
            ('planet:lantern', 'planet', 'system:orchard'), ('moon:alpha', 'moon', 'planet:lantern'),
            ('moon:beta', 'moon', 'planet:lantern'), ('district:login', 'district', 'planet:lantern'),
            ('system:coast', 'system', 'galaxy:owner'), ('moon:outside', 'moon', 'system:coast')]
    path = tmp_path / 'space.json'
    path.write_text(json.dumps(dict(schema_version=1, published=123, entities=[node(*row) for row in rows],
                                    edges=[], coverage={})))
    return path


def call(chart, **kwargs):
    return navigation.navigate(None, None, space_cache=chart, source_cache=chart.parent/'sources',
                               text='show the experiments', within='system:orchard', **kwargs)


def test_lists_exact_descendant_kind_without_retrieval_or_writes(chart, monkeypatch):
    monkeypatch.setattr(navigation, 'evidence', lambda *a, **kw: pytest.fail('Listing performed evidence retrieval'))
    monkeypatch.setattr(navigation, '_brief_place', lambda *a, **kw: pytest.fail('Listing generated a briefing'))
    before = chart.read_bytes()
    result = call(chart)
    ordinary = navigation.view(None, None, space_cache=chart, source_cache=chart.parent/'sources',
                               action='list', kind='moons', within='system:orchard', limit=20)
    assert result['nodes'] == ordinary['nodes']
    assert {n['id'] for n in result['nodes']} == {'moon:alpha', 'moon:beta'}
    assert result['action'] == 'list' and result['listing_kind'] == 'moons'
    assert result['query'] == '' and result['destination'] is None and 'evidence' not in result
    assert result['list_command'] == ordinary['cli_command']
    assert result['steps'][0]['matches'] == 2
    assert chart.read_bytes() == before


def test_widening_is_explicit_and_empty_scope_does_not_fall_back(chart):
    global_list = call(chart, local=False)
    assert {n['id'] for n in global_list['nodes']} == {'moon:alpha', 'moon:beta', 'moon:outside'}
    empty = navigation.navigate(None, None, space_cache=chart, source_cache=chart.parent/'sources',
                                text='list the products', within='moon:alpha')
    assert empty['nodes'] == [] and empty['center']['id'] == 'moon:alpha'
    assert empty['total'] == 0 and not empty['more']
    with pytest.raises(ValueError, match='not found'):
        navigation.navigate(None, None, space_cache=chart, source_cache=chart.parent/'sources',
                            text='show the experiments', within='system:missing')


def test_untyped_legacy_child_list_is_not_labelled_as_a_typed_listing(chart):
    result = navigation.view(None, None, space_cache=chart, source_cache=chart.parent/'sources',
                             action='list', within='planet:lantern', limit=1)
    assert result['total'] == 3 and result['more']
    assert not {'listing_kind', 'list_command', 'next_command'} & result.keys()


def test_one_publication_is_reused_through_scope_resolution_and_listing(chart, monkeypatch):
    read = navcom_space._read
    reads = []
    def replace_after_read(path, *args, **kwargs):
        result = read(path, *args, **kwargs)
        reads.append(str(path))
        updated = dict(result, published=456, entities=[n for n in result['entities'] if n['kind'] != 'moon'])
        chart.write_text(json.dumps(updated))
        return result
    monkeypatch.setattr(navcom_space, '_read', replace_after_read)
    result = call(chart)
    assert result['published'] == 123 and result['total'] == 2
    assert len(reads) == 1


def cli(*args):
    result = subprocess.run([sys.executable, str(ROOT/'navcom.py'), *args], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_cli_listing_and_returned_page_command_preserve_scope(chart, tmp_path):
    args = ('atlas', 'navigate', 'show the experiments', '--within', 'system:orchard',
            '--space-cache', str(chart), '--source-cache', str(tmp_path/'sources'),
            '--index', str(tmp_path/'missing.sqlite'), '--limit', '1')
    first = json.loads(cli(*args, '--json'))
    assert first['listing_kind'] == 'moons' and first['total'] == 2 and first['more']
    continuation = shlex.split(first['next_command'])
    assert continuation[:4] == ['navcom', 'atlas', 'list', 'moons']
    second = json.loads(cli(*continuation[1:], '--json'))
    assert first['center']['id'] == second['center']['id'] == 'system:orchard'
    assert {first['nodes'][0]['id'], second['nodes'][0]['id']} == {'moon:alpha', 'moon:beta'}
    assert second['offset'] == 1 and not second['more']
    printed = cli(*args)
    assert first['next_command'] in printed
    assert 'More destinations available with --offset' not in printed
    assert not (tmp_path/'missing.sqlite').exists()


def test_back_cli_reports_request_without_claiming_an_executed_flight(tmp_path):
    result = json.loads(cli('atlas', 'navigate', 'take me back', '--space-cache', str(tmp_path/'absent.json'),
                            '--index', str(tmp_path/'absent.sqlite'), '--json'))
    assert result['action'] == 'back' and result['destination'] is None
    assert result['steps'][0]['status'] == 'requested'
