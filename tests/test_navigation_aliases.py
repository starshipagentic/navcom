"""Explicit destination spelling aliases preserve numbers, scope and choices."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

import navcom_navigation as navigation


def chart(tmp_path, *, ambiguous=False):
    def node(identity, kind, label, parent, **extra):
        return dict(id=identity, kind=kind, label=label, parent_id=parent, source_scopes=[], source_ids=[],
                    conversation_collections=[], position=dict(x=0, y=0), locations=[], evidence=[], examples=[], **extra)
    nodes = [node('galaxy:owner', 'galaxy', 'Owner', None),
             node('system:first', 'system', 'First suite', 'galaxy:owner'),
             node('system:second', 'system', 'Second suite', 'galaxy:owner'),
             node('planet:experiment', 'planet', 'exp47-sensors', 'system:first'),
             node('planet:other-number', 'planet', 'exp470', 'system:first'),
             node('district:child', 'district', 'Sensor history', 'planet:experiment',
                  description='Experimental notes within experiment 47 at exp47-sensors')]
    if ambiguous:
        nodes.append(node('planet:second-experiment', 'planet', 'experiment-47', 'system:second'))
    path = tmp_path / 'space.json'
    path.write_text(json.dumps(dict(schema_version=1, published=123, entities=nodes, edges=[], coverage={})))
    return path


def add_district_clue(cache, *, exact=False):
    data=json.loads(cache.read_text())
    for node in data['entities']:
        if node['id']=='planet:experiment':node['kind']='moon'
        if node['id']=='district:child':
            node['label']='exp47' if exact else 'exp47 / rating context · signal lab / rating context (2 files)'
    cache.write_text(json.dumps(data))


def evidence_spy(monkeypatch):
    calls = []
    def evidence(api, conn, space, sources, within, query, *args, **kwargs):
        calls.append((within, query))
        return dict(sources=[], conversations=[], places=[], coverage=dict(complete=True))
    monkeypatch.setattr(navigation, 'evidence', evidence)
    return calls


@pytest.mark.parametrize('destination', ['experiment 47', 'EXP 47', 'exp-47', 'experiment_47', 'exp47'])
def test_complete_experiment_phrase_resolves_name_not_inherited_description(tmp_path, monkeypatch, destination):
    cache = chart(tmp_path)
    calls = evidence_spy(monkeypatch)
    result = navigation.navigate(None, None, space_cache=cache, source_cache=tmp_path / 'sources',
                                 text='find matrix in ' + destination)
    assert result['scope_status'] == 'resolved'
    assert result['scope_target']['id'] == 'planet:experiment'
    assert result['intent']['query'] == 'matrix'
    assert calls == [('planet:experiment', 'matrix')]
    current = navigation.navigate(None, None, space_cache=cache, source_cache=tmp_path / 'sources',
                                  within='planet:experiment', text='find matrix in ' + destination)
    assert current['scope_target']['id'] == 'planet:experiment'


@pytest.mark.parametrize('destination', ['experiment 47', 'exp47', 'experiment-47'])
def test_separate_alias_destinations_remain_ambiguous_and_scoped(tmp_path, monkeypatch, destination):
    cache = chart(tmp_path, ambiguous=True)
    calls = evidence_spy(monkeypatch)
    kwargs = dict(space_cache=cache, source_cache=tmp_path / 'sources', text='find matrix in ' + destination)
    result = navigation.navigate(None, None, **kwargs)
    assert result['scope_status'] == 'choose' and not calls
    assert {node['id'] for node in result['scope_candidates']} == {'planet:experiment', 'planet:second-experiment'}
    scoped = navigation.navigate(None, None, within='system:first', **kwargs)
    assert scoped['scope_status'] == 'resolved' and calls == [('planet:experiment', 'matrix')]
    chosen = navigation.navigate(None, None, scope_choice='planet:second-experiment', **kwargs)
    assert chosen['scope_target']['id'] == 'planet:second-experiment'
    with pytest.raises(ValueError, match='not one of the matching'):
        navigation.navigate(None, None, within='system:first', scope_choice='planet:second-experiment', **kwargs)


def test_alias_does_not_rewrite_content_or_longer_destination_phrase(tmp_path, monkeypatch):
    cache = chart(tmp_path)
    calls = evidence_spy(monkeypatch)
    navigation.navigate(None, None, space_cache=cache, source_cache=tmp_path / 'sources', text='find experiment 47')
    assert calls == [('', 'experiment 47')]
    nodes, more = navigation._destination_candidates(cache, 'experiment 47 notes', '', json.loads(cache.read_text()))
    assert [node['id'] for node in nodes] == ['district:child'] and not more


@pytest.mark.parametrize('destination', ['exp47', 'experiment 47'])
def test_numbered_alias_prefers_experiment_over_path_derived_district_label(tmp_path, monkeypatch, destination):
    cache=chart(tmp_path)
    add_district_clue(cache)
    calls=evidence_spy(monkeypatch)
    result=navigation.navigate(None,None,space_cache=cache,source_cache=tmp_path/'sources',
                               text='find primitive in '+destination)
    assert result['scope_status']=='resolved'
    assert result['scope_target']['id']=='planet:experiment' and result['scope_target']['kind']=='moon'
    assert result['intent']['query']=='primitive'
    assert calls==[('planet:experiment','primitive')]
    # The full, exact district label still directly addresses the district.
    nodes,more=navigation._destination_candidates(cache,
        'exp47 / rating context · signal lab / rating context (2 files)','',json.loads(cache.read_text()))
    assert [node['id'] for node in nodes]==['district:child'] and not more


@pytest.mark.parametrize('exact_district', [False, True])
def test_numbered_moons_and_true_exact_district_names_remain_choices(tmp_path, monkeypatch, exact_district):
    cache=chart(tmp_path,ambiguous=True)
    add_district_clue(cache,exact=exact_district)
    data=json.loads(cache.read_text())
    for node in data['entities']:
        if node['id']=='planet:second-experiment':node['kind']='moon'
    cache.write_text(json.dumps(data))
    calls=evidence_spy(monkeypatch)
    result=navigation.navigate(None,None,space_cache=cache,source_cache=tmp_path/'sources',
                               text='find primitive in exp47')
    expected={'planet:experiment','planet:second-experiment'}
    if exact_district:expected.add('district:child')
    assert result['scope_status']=='choose' and not calls
    assert {node['id'] for node in result['scope_candidates']}==expected
    assert result['intent']['query']=='primitive'


def test_public_cli_spoken_experiment_alias(tmp_path):
    cache = chart(tmp_path)
    add_district_clue(cache)
    result = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1] / 'navcom.py'),
        'atlas', 'navigate', 'find matrix in experiment 47', '--space-cache', str(cache),
        '--source-cache', str(tmp_path / 'sources'), '--index', str(tmp_path / 'absent.sqlite'), '--json'],
        capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data['scope_target']['id'] == 'planet:experiment'
    assert data['intent']['query'] == 'matrix' and data['scope_status'] == 'resolved'
