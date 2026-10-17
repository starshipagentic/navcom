"""Chart nodes carry the CLI's own commands, and every one of them runs as printed."""
import json
import sqlite3

import pytest

import navcom_atlas_cli
import navcom_history_cli
import navcom_navigation as navigation
import navcom_sources
import navcom_space as space


def node(identity, kind, parent, **extra):
    return dict(dict(id=identity, kind=kind, label=identity.split(':')[-1].title(), parent_id=parent,
                     status='suggested', evidence=[], locations=[], source_ids=[], source_scopes=[],
                     conversation_collections=[], examples=[], position=dict(x=0, y=0)), **extra)


@pytest.fixture
def chart(tmp_path):
    scope = [dict(source_id='src1', paths=['apps/web', 'apps/web/login.ts'])]
    nodes = [node('galaxy:owner', 'galaxy', None, stored_copies=[dict(id='fleet:ship:copy')]),
             node('system:coast', 'system', 'galaxy:owner'),
             node('planet:harbor', 'planet', 'system:coast', source_scopes=scope,
                  conversation_collections=['projects:abc']),
             node('moon:exp1', 'moon', 'planet:harbor'),
             node('district:login', 'district', 'planet:harbor', source_scopes=scope, suggested_query='login policy'),
             node('planet:labapp', 'district', 'moon:exp1', form='application'),
             node('star-candidate:tides', 'star', 'galaxy:owner'),
             node('fleet:starbase:dock', 'starbase', 'galaxy:owner', art_role='starbase'),
             node('fleet:ship:working', 'ship', 'fleet:starbase:dock', art_role='ship'),
             node('fleet:ship:copy', 'ship', 'galaxy:owner', form='archive', art_role='archive')]
    path = tmp_path / 'space.json'
    path.write_text(json.dumps(dict(schema_version=1, published=1, entities=nodes, edges=[], coverage={})))
    index = tmp_path / 'index.sqlite'
    sqlite3.connect(index).close()
    return path, tmp_path / 'sources', index


FILL = {'<query>': 'login', '<question>': 'What do you know?', '<commit>': 'abc123', '<YYYY-MM-DD>': '2026-01-01'}
PARSERS = {'atlas': navcom_atlas_cli.parser, 'history': navcom_history_cli.parser, 'sources': navcom_sources.parser}


def shown(chart, within):
    path, sources, index = chart
    with sqlite3.connect(index) as conn:
        return navigation.view(None, conn, space_cache=path, source_cache=sources, action='show', within=within)['center']


def test_every_node_command_parses_with_its_cli_and_pins_this_chart(chart):
    path, sources, index = chart
    for entity in json.loads(path.read_text())['entities']:
        commands = shown(chart, entity['id'])['commands']
        for name, value in commands.items():
            for argv in (value if not value or isinstance(value[0], list) else [value]):
                assert argv[0] == 'navcom', (name, argv)
                filled = [FILL.get(word, word) for word in argv]
                parsed = PARSERS[argv[1]]().parse_args(filled[2:])  # SystemExit on any unknown option
                if name != 'conversation_search' and argv[1] != 'sources':
                    assert str(parsed.space_cache) == str(path), (name, argv)
                if argv[1] == 'sources':
                    assert str(parsed.cache) == str(sources)
                elif getattr(parsed, 'index', None) is not None:
                    assert str(parsed.index) == str(index)


def test_commands_list_each_applicable_read_only_or_review_first_verb(chart):
    verbs = {identity: set(shown(chart, identity)['commands']) for identity in (
        'galaxy:owner', 'system:coast', 'planet:harbor', 'moon:exp1', 'district:login', 'planet:labapp',
        'star-candidate:tides', 'fleet:starbase:dock', 'fleet:ship:working', 'fleet:ship:copy')}
    everywhere = {'explore', 'show', 'search', 'navigate', 'source_search', 'conversation_search'}
    assert all(everywhere <= names for names in verbs.values())
    assert {'list', 'related', 'history_system', 'history_conversations', 'stored_copies', 'sources_list'} <= verbs['galaxy:owner']
    assert {'files', 'inspect', 'inspect_refresh', 'history_timeline', 'history_explore', 'related'} <= verbs['planet:harbor']
    assert 'inspect' not in verbs['district:login'] and 'inspect' in verbs['planet:labapp']
    assert {'ask', 'inspect_observe', 'history_timeline'} <= verbs['star-candidate:tides']
    assert {'carried_context', 'carried_search', 'handover', 'board_validate', 'inspect'} <= verbs['fleet:ship:working']
    assert 'board_validate' not in verbs['fleet:ship:copy'] and 'carried_context' in verbs['fleet:ship:copy']
    assert verbs['fleet:starbase:dock'] == everywhere | {'list'}
    # Writing or launching verbs are never offered; they follow from a printed review.
    for names in verbs.values():
        assert not {'board', 'launch', 'refresh', 'harvest', 'maintain'} & names


def test_existing_command_shapes_are_unchanged(chart):
    district = shown(chart, 'district:login')['commands']
    assert district['source_search'][0][:8] == ['navcom', 'sources', 'search', '<query>', '--within', 'src1',
                                                '--path', 'apps/web']
    assert district['conversation_search'] == [] and district['explore'][:4] == ['navcom', 'atlas', 'explore', 'district:login']
    assert shown(chart, 'fleet:ship:copy')['commands']['carried_context'][:4] == ['navcom', 'atlas', 'context', 'fleet:ship:copy']


def test_older_charts_never_return_view_sprite_names(chart):
    path, sources, index = chart
    for action in ('explore', 'show'):
        result = space.view(path, action=action)
        assert all('art_role' not in item for item in [result['center'], *result['nodes']])
    with sqlite3.connect(index) as conn:
        found = navigation.navigate(None, conn, space_cache=path, source_cache=sources, text='fly to working')
    assert found['nodes'] and all('art_role' not in item for item in found['nodes'])
    # Navigator results offer the same current, pinned commands as explore and show.
    assert all('--space-cache' in item['commands']['explore'] and 'inspect' in item['commands']
               for item in found['nodes'] if item['kind'] == 'ship')
    assert 'art_role' not in space.view(path, kind='ships')['nodes'][0]


def test_every_plural_kind_alias_still_lists_its_places(chart, navcom, capsys):
    path, sources, index = chart
    aliases = {'galaxies': 'galaxy', 'systems': 'system', 'solar-systems': 'system', 'planets': 'planet',
               'products': 'planet', 'moons': 'moon', 'experiments': 'moon', 'districts': 'district',
               'cities': 'district', 'stars': 'star', 'bases': 'starbase', 'starbases': 'starbase', 'ships': 'ship'}
    for alias, kind in aliases.items():  # The galaxy is the scope itself, so it lists no galaxies.
        assert {item['kind'] for item in space.view(path, kind=alias)['nodes']} == ({kind} - {'galaxy'}), alias
    # `districts` is a conversation grouping too; with --space it lists chart districts.
    assert navcom_atlas_cli.run(navcom, ['list', 'districts', '--space', '--space-cache', str(path),
                                         '--index', str(index), '--json']) == 0
    listed = json.loads(capsys.readouterr().out)['nodes']
    assert {item['id'] for item in listed} == {'district:login', 'planet:labapp'}
