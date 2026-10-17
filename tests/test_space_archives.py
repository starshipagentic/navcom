"""Physical ship copies stay reachable without becoming conceptual parents."""
import json
from pathlib import Path

import navcom_atlas_cli
import navcom_fleet
import navcom_navigation
import navcom_space as space
from test_space import API, database, package


def test_archive_links_preserve_locations_scopes_and_cached_navigation(tmp_path, monkeypatch, capsys):
    root = package(tmp_path / 'clients' / 'Orion' / 'orchard', name='Orchard')
    conn = database([(root, 'Growing amber')])
    base = dict(id='base:remote', kind='starbase', label='Remote store', parent_id=None)
    working = dict(id='ship:working', kind='ship', label='Orchard vessel', parent_id=base['id'],
                   physical=dict(host='remote.example', path='/fleet/orchard'), source_roots=[str(root)])
    archive = dict(id='ship:archive', kind='ship', label='Orchard stored copy', form='archive',
                   art_role='archive', parent_id=None, related_ship_id=working['id'], source_roots=[str(root)],
                   physical=dict(host='here', path=str(tmp_path / 'commission' / 'archive')),
                   integrity=dict(status='not checked', capture_evidence='seal-present-unverified'))
    calls = []
    def fleet(**kwargs):
        calls.append(kwargs)
        return dict(entities=[base, working, archive], coverage=dict(ships=2, archive_ships=1))
    monkeypatch.setattr(navcom_fleet, 'read_fleet', fleet)
    monkeypatch.setattr(space, '_star_inventory', lambda *_: ([], {}))
    cache = tmp_path / 'chart.json'
    data = space.refresh(API, conn, cache)
    assert calls == [dict(archive_cache=tmp_path / 'chart.json.fleet-archives.json')]
    nodes = {node['id']: node for node in data['entities']}
    saved = nodes[archive['id']]
    # A sprite name from an older fleet record never enters the chart; the view derives art from form.
    assert saved['form'] == 'archive' and 'art_role' not in saved
    assert saved['parent_id'] == space.GALAXY  # not physically inside a remote working ship
    assert saved['physical'] == archive['physical'] and saved['integrity'] == archive['integrity']
    assert nodes[working['id']]['physical'] == working['physical']
    assert saved['conversation_count'] == 0 and saved['conversation_collections'] == []
    assert nodes[space.GALAXY]['conversation_count'] == 1
    assert saved['ship_links'][0]['id'] == working['id']
    assert nodes[working['id']]['ship_links'][0]['id'] == saved['id']
    product = next(node for node in nodes.values() if node['kind'] == 'planet')
    assert {link['id'] for link in product['ship_links']} == {working['id'], saved['id']}
    assert any(edge['relation'] == 'archive_of' and edge['source'] == saved['id']
               and edge['target'] == working['id'] for edge in data['edges'])
    assert nodes[space.GALAXY]['stored_copies'][0]['id'] == saved['id']
    monkeypatch.setattr(navcom_fleet, 'read_fleet', lambda **_: (_ for _ in ()).throw(AssertionError('navigation inspected source')))
    overview = space.view(cache, action='explore')
    assert overview['stored_copy_count'] == 1
    assert saved['id'] not in {node['id'] for node in overview['nodes']}
    linked = navcom_navigation.view(API, conn, space_cache=cache, source_cache=tmp_path / 'sources', action='explore')
    assert linked['center']['commands']['stored_copies'][-4:] == ['--space-cache', str(cache), '--source-cache', str(tmp_path / 'sources')]
    assert {node['id'] for node in space.view(cache, kind='ships')['nodes']} == {saved['id'], working['id']}
    assert space.view(cache, action='search', query='stored copy')['nodes'][0]['id'] == saved['id']
    assert space.view(cache, action='explore', within=saved['id'])['center']['id'] == saved['id']
    shown = navcom_navigation.view(API, conn, space_cache=cache, source_cache=tmp_path / 'sources',
                                  action='show', within=saved['id'])
    command = shown['center']['commands']['carried_context']
    assert '--space-cache' in command and '--source-cache' not in command
    navcom_atlas_cli.render_space(shown)
    output = capsys.readouterr().out
    assert '[ship archive' in output and 'working copy: Orchard vessel' in output
    assert str(tmp_path / 'commission' / 'archive') in output
    conn.close()


def test_archive_command_accepts_generated_options(tmp_path):
    from navcom_atlas_cli import parser
    args = parser().parse_args(['context', 'ship:archive', '--space-cache', str(tmp_path / 'space'),
                               '--index', str(tmp_path / 'index')])
    assert args.command == 'context' and args.ref == 'ship:archive'
