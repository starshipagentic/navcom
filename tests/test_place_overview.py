"""Place cards explain their actual contents without inventing classifications."""
from navcom_place_overview import previews
from test_space import API, database, git, package, isolated_fleet


def place(identity, kind, parent, label=None, **fields):
    return dict(id=identity, kind=kind, parent_id=parent, label=label or identity, **fields)


def test_only_direct_children_count_and_lab_apps_are_not_product_planets():
    entities = [place('system', 'system', None), place('product', 'planet', 'system'),
                place('trial', 'moon', 'product'),
                place('editor', 'district', 'trial', form='application'),
                place('auth', 'district', 'product', evidence=[dict(type='starforge_token_group', paths=['a.py', 'b.py', 'a.py'])]),
                place('foreign', 'planet', 'other')]
    result = previews(entities, ['system', 'product', 'trial'])
    assert result['system']['total'] == 1
    assert result['system']['groups'][0]['category'] == 'products'
    assert result['product']['total'] == 2
    assert result['product']['groups'][0]['places'][0]['files'] == 2
    assert result['trial']['groups'][0]['category'] == 'applications'
    assert result['trial']['groups'][0]['places'][0]['id'] == 'editor'


def test_previews_are_bounded_stable_and_do_not_mutate_catalog():
    entities = [place(str(i), 'moon', 'planet', label=f'Experiment {i:02}') for i in reversed(range(11))]
    original = [node.copy() for node in entities]
    result = previews(entities, ['planet'])['planet']['groups'][0]
    assert result['count'] == 11 and result['more'] is True
    assert [node['id'] for node in result['places']] == ['0', '1', '2', '3']
    assert previews(list(reversed(entities)), ['planet'])['planet']['groups'][0] == result
    assert entities == original


def test_readme_provenance_requires_an_exact_saved_clue():
    entities = [place('p', 'planet', None, description='Recorded prose', clues=[
        dict(text='Recorded prose', basis='harvested_readme', path='/snapshot/README.md')]),
        place('q', 'planet', None, description='Owner description', clues=[
            dict(text='Different prose', basis='harvested_readme', path='/snapshot/README.md')])]
    result = previews(entities, ['p', 'q'])
    assert result['p']['description_source']['basis'] == 'harvested_readme'
    assert 'description_source' not in result['q']
    assert result['p']['total'] == 0


def test_public_cli_exposes_the_same_contents_without_rewriting_the_chart(tmp_path):
    import json
    from pathlib import Path
    import subprocess
    import sys
    import navcom_space
    root = git(tmp_path / 'clients' / 'Orchard' / 'suite')
    package(root, name='Orchard suite', workspaces=['apps/*'])
    package(root / 'apps' / 'scheduler', name='Scheduler', scripts={'dev': 'vite'})
    conn = database([(root, 'Suite planning')])
    cache = tmp_path / 'space.json'
    chart = navcom_space.refresh(API, conn, cache)
    conn.close()
    system = next(node for node in chart['entities'] if node['kind'] == 'system' and node['label'] == 'Orchard')
    before = cache.read_bytes()
    command = [sys.executable, str(Path(__file__).resolve().parents[1] / 'navcom.py'),
               'atlas', 'show', system['id'], '--space-cache', str(cache),
               '--index', str(tmp_path / 'absent.sqlite')]
    result = subprocess.run(command + ['--json'], capture_output=True, text=True, check=True)
    data = json.loads(result.stdout)
    preview = data['center']['contents']
    assert preview['basis'] == 'published_direct_children'
    assert {item['label'] for item in preview['groups'][0]['places']} == {'suite', 'Scheduler'}
    text = subprocess.run(command, capture_output=True, text=True, check=True).stdout
    assert 'Products: 2' in text and 'Scheduler' in text
    assert cache.read_bytes() == before


def test_human_navigation_does_not_dump_unbounded_diagnostics(capsys):
    import navcom_atlas_cli
    data = dict(nodes=[place('editor', 'district', 'trial', form='application',
                            evidence=[dict(type='native_application', path='/repo/lab/package.json',
                                           entry_points=[{'file': 'private-detail'}] * 1000)])],
                coverage=dict(indexed_conversations=6641, indexed_projects=331,
                              harvested_sources=145, unavailable_roots=['/missing/' + str(i) for i in range(1000)],
                              unknown_projects=82, stars=dict(complete=False, batches=[{}] * 1000)))
    navcom_atlas_cli.render_space(data)
    output = capsys.readouterr().out
    assert '[lab application' in output and '/repo/lab/package.json' in output
    assert '6,641 conversations' in output and '1000 unavailable locations' in output
    assert '82 projects with unknown identity' in output and 'expert discovery is partial' in output
    assert '--json' in output and len(output) < 1000
    assert 'private-detail' not in output and '/missing/999' not in output
    assert len(data['coverage']['unavailable_roots']) == 1000


def test_human_coverage_preserves_native_fleet_gaps():
    from navcom_atlas_cli import _coverage_lines
    for fleet, expected in (({'status': 'partial', 'available': True}, 'partial'),
                            ({'status': 'unavailable', 'available': False}, 'unavailable')):
        assert 'fleet discovery is '+expected in '\n'.join(_coverage_lines({'fleet': fleet}))
