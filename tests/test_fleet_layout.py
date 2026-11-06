"""Cached fleet berths remain explainable across pages without moving ships."""
from copy import deepcopy
import json
import random

import pytest

import navcom_fleet_layout as layout


def node(identity, kind, label, parent=None, **extra):
    return dict(id=identity, kind=kind, label=label, parent_id=parent,
                evidence=[], position=dict(x=17, y=29), **extra)


def fixture():
    base = node('base:one', 'starbase', 'Recorded base', 'galaxy:owner')
    independent = node('system:independent', 'system', 'Arbitrary renamed unassigned', 'galaxy:owner')
    orchard = node('system:orchard', 'system', 'Orchard', 'galaxy:owner', status='established')
    orchard['evidence'] = [dict(type='client_folder', path='/home/alice/clients/Orchard')]
    quartz = node('system:quartz', 'system', 'Quartz', 'galaxy:owner', status='suggested')
    quartz['evidence'] = [dict(type='client_folder', path='/home/alice/clients/Quartz')]
    product = node('planet:lantern', 'planet', 'Lantern', orchard['id'], description='Product description')
    other = node('planet:radar', 'planet', 'Radar', quartz['id'])
    return dict(entities=[base, independent, orchard, quartz, product, other], edges=[])


def ship(data, identity, label, roots=(), **extra):
    value = node(identity, 'ship', label, 'base:one', source_roots=list(roots), **extra)
    data['entities'].append(value)
    return value


def link(data, ship_id, product_id, *, kind='fleet_source_reference'):
    data['edges'].append(dict(source=ship_id, target=product_id, relation='relates_to', evidence=dict(type=kind)))


def test_exact_system_and_unindexed_client_source_override_word_suggestions():
    data = fixture()
    ship(data, 'ship:one', 'Voice and models', ['/unindexed/lantern'])
    link(data, 'ship:one', 'planet:lantern')
    ship(data, 'ship:two', 'Research', ['/home/alice/clients/Quartz/unindexed-app'])
    result = layout.derive(data, 'base:one')
    first, second = (result['assignments'][identity] for identity in ('ship:one', 'ship:two'))
    assert first['label'] == 'Orchard' and first['status'] == 'recorded'
    assert first['basis'] == second['basis'] == 'cached_system_context'
    assert second['label'] == 'Quartz' and second['status'] == 'suggested'
    assert any(e['type'] == 'client_folder' and e['source_root'].endswith('unindexed-app') for e in second['evidence'])
    assert not any(e['type'] == 'atlas_classify' for a in (first, second) for e in a['evidence'])


def test_topic_words_and_receiving_reports_never_create_a_berth():
    data = fixture()
    product = node('planet:plain', 'planet', 'Plain', 'system:independent', description='speech microphone')
    data['entities'].append(product)
    ship(data, 'ship:plain', 'Image voice training', ['/recorded/voice'], description='receiving docker backup benchmark', readiness={'description': 'never-input'})
    link(data, 'ship:plain', product['id'])
    entry = layout.derive(data, 'base:one')['assignments']['ship:plain']
    assert (entry['label'], entry['basis'], entry['status']) == ('Unassigned context', 'no_grouped_context', 'unassigned')
    assert not any(e['type'] == 'atlas_classify' for e in entry['evidence'])
    assert 'receiving' not in json.dumps(entry)



def test_ambiguous_explicit_systems_keep_one_cross_context_without_merging_berths():
    data = fixture()
    for identity in ('ship:a', 'ship:b', 'ship:cross'):
        ship(data, identity, 'Same title', ['/shared/context'])
    link(data, 'ship:a', 'planet:lantern')
    link(data, 'ship:b', 'planet:radar')
    link(data, 'ship:cross', 'planet:lantern'); link(data, 'ship:cross', 'planet:radar')
    result = layout.derive(data, 'base:one')
    assignments = result['assignments']
    assert {a['label'] for a in assignments.values()} == {'Orchard', 'Quartz', 'Cross-system context'}
    assert len({a['id'] for a in assignments.values()}) == 3
    assert len({a['family_key'] for a in assignments.values()}) == 3
    cross = assignments['ship:cross']
    assert {e['system_id'] for e in cross['evidence'] if e['type'] == 'system_context'} == {'system:orchard', 'system:quartz'}
    assert cross['status'] == 'suggested'


def test_folder_containment_is_component_exact_specific_and_ties_stay_ambiguous():
    data = fixture()
    inner = node('system:inner', 'system', 'Inner', 'galaxy:owner')
    inner['evidence'] = [dict(type='client_folder', path='/home/alice/clients/Orchard/sub')]
    data['entities'].append(inner)
    ship(data, 'ship:inner', 'Zorblax', ['/home/alice/clients/Orchard/sub/app'])
    ship(data, 'ship:prefix', 'Zorblax', ['/home/alice/clients/Orchard-other/app'])
    ship(data, 'ship:escape', 'Zorblax', ['/home/alice/clients/Orchard/../Quartz/app', '~/clients/Orchard'])
    result = layout.derive(data, 'base:one')['assignments']
    assert result['ship:inner']['label'] == 'Inner'
    assert result['ship:prefix']['label'] == result['ship:escape']['label'] == 'Unassigned context'
    duplicate = deepcopy(inner);duplicate['id'] = 'system:duplicate';data['entities'].append(duplicate)
    assert layout.derive(data, 'base:one')['assignments']['ship:inner']['label'] == 'Cross-system context'


def test_shared_exact_product_or_source_context_is_adjacent_without_name_matching():
    data = fixture()
    for identity, title, roots in [('a', 'Alpha', ['/one']), ('b', 'Zulu', ['/two']), ('c', 'Middle', ['/other']), ('d', 'Alpha', ['/one'])]:
        ship(data, 'ship:'+identity, title, roots)
    link(data, 'ship:a', 'planet:lantern');link(data, 'ship:b', 'planet:lantern')
    link(data, 'ship:c', 'planet:lantern');link(data, 'ship:d', 'planet:lantern')
    # Product identity is a common exact context even when source copies differ.
    result = layout.derive(data, 'base:one')
    assert len({a['family_key'] for a in result['assignments'].values()}) == 1
    data['edges'] = []
    result = layout.derive(data, 'base:one')
    assert result['assignments']['ship:a']['family_key'] == result['assignments']['ship:d']['family_key']
    assert result['assignments']['ship:b']['family_key'] != result['assignments']['ship:a']['family_key']
    members = next(group['members'] for group in result['groups'] if 'ship:a' in group['members']); assert abs(members.index('ship:a')-members.index('ship:d')) == 1


def test_all_107_members_retain_full_group_keys_across_pages_filtering_and_input_order():
    data = fixture()
    for number in range(107):
        value = ship(data, f'ship:{number:03}', f'Vessel {number:03}', [f'/home/alice/clients/{"Orchard" if number % 2 else "Quartz"}/app-{number % 7}'])
        value['physical'] = dict(host='remote.example', path='/fleet/'+str(number))
    before = deepcopy(data)
    result = layout.derive(data, 'base:one')
    members = [identity for group in result['groups'] for identity in group['members']]
    assert len(members) == len(set(members)) == 107
    assert [len(members[offset:offset+80]) for offset in (0, 80)] == [80, 27]
    for shown in (members[:80], members[80:], members[::11]):
        # The view attaches assignments from the whole publication, not a
        # freshly classified page subset. Each group count remains global.
        assert {identity: result['assignments'][identity] for identity in shown} == {
            identity: layout.derive(data, 'base:one')['assignments'][identity] for identity in shown}
    random.Random(47).shuffle(data['entities']);random.Random(83).shuffle(data['edges'])
    assert layout.derive(data, 'base:one') == result
    assert sorted(data['entities'], key=lambda n:n['id']) == sorted(before['entities'], key=lambda n:n['id'])
    # Root publication, physical readiness and page order do not determine IDs.
    data['published'] = 999
    for n in data['entities']:
        n['readiness'] = dict(status='different recorded state')
    assert layout.derive(data, 'base:one') == result


def test_archives_only_when_actually_parented_to_selected_base_and_no_hidden_probes(monkeypatch):
    data = fixture()
    ship(data, 'ship:working', 'Voice', ['/voice'])
    local = ship(data, 'ship:local', 'Voice', ['/voice'], form='archive', related_ship_id='ship:working')
    local['parent_id'] = 'galaxy:owner'
    ship(data, 'ship:stored-here', 'Voice', ['/voice'], form='archive')
    def forbidden(*_, **__):
        raise AssertionError('Pure grouping attempted filesystem I/O')
    monkeypatch.setattr('builtins.open', forbidden)
    result = layout.derive(data, 'base:one')
    assert set(result['assignments']) == {'ship:working', 'ship:stored-here'}
    assert local['parent_id'] == 'galaxy:owner'
    assert 'position' not in json.dumps(result)


def test_wrong_relation_does_not_establish_product_context_and_parent_cycles_stop():
    data = fixture()
    ship(data, 'ship:none', 'Zorblax')
    link(data, 'ship:none', 'planet:lantern', kind='provider_implementation_location')
    assert layout.derive(data, 'base:one')['assignments']['ship:none']['label'] == 'Unassigned context'
    data['entities'][-1]['parent_id'] = 'base:one'
    data['entities'][4]['parent_id'] = 'planet:radar';data['entities'][5]['parent_id'] = 'planet:lantern'
    link(data, 'ship:none', 'planet:lantern')
    assert layout.derive(data, 'base:one')['assignments']['ship:none']['label'] == 'Unassigned context'
    with pytest.raises(ValueError, match='exact cached starbase'):
        layout.derive(data, 'Recorded base')
