"""Product prose comes from scoped harvested documents, not an incidental package."""
import json

import pytest

import navcom_space as space
from test_space import API, database, git, isolated_fleet, package, source_cache


def by_path(data, path):
    return next(node for node in data['entities']
                if node['kind'] in {'planet', 'moon'} and
                any(location['path'] == str(path) for location in node['locations']))


def test_mixed_language_product_readme_outweighs_component_package_without_changing_scope(tmp_path):
    root = git(tmp_path / 'clients' / 'Cobalt' / 'TidalArchive')
    package(root, name='tidal-ui-theme', description='Browser widget and color library', workspaces=['apps/*'])
    app = package(root / 'apps' / 'portal', name='Observer portal',
                  description='Portal JavaScript bundle', scripts={'start': 'node main.js'})
    (root / 'index.php').write_text('<?php /* Main archival service */')
    (root / 'worker.rs').write_text('fn main() {}')
    (root / 'theme.js').write_text('export const color = "blue";')
    # This changed working README must never be read by chart formatting.
    (root / 'README.md').write_text('Current-only unpublished decoy description')
    sources = source_cache(tmp_path, [root], [])
    artifact = sources / 'artifacts' / '0'
    (artifact / 'catalog.json').write_text(json.dumps({'projects': {'tidal': {'summary': 'Syntax Status'}}}))
    conn = database([(root, 'Archive operations'), (app, 'Observer permissions')])
    cache = tmp_path / 'space.json'
    before = space.refresh(API, conn, cache, source_cache=sources)
    initial = by_path(before, root)
    assert initial['description'] == 'Browser widget and color library'

    snapshot = artifact / 'source'
    (snapshot / 'apps' / 'portal').mkdir(parents=True)
    root_text = '# Tidal Archive\nStores ocean observations, schedules sampling trips, and manages instrument records.\n'
    app_text = '# Observer portal\nPlan field visits and review measurements.\n'
    (snapshot / 'README.md').write_text(root_text)
    (snapshot / 'apps' / 'portal' / 'README.md').write_text(app_text)
    after = space.refresh(API, conn, cache, source_cache=sources)
    product, portal = by_path(after, root), by_path(after, app)
    assert 'Stores ocean observations' in product['description']
    assert 'Plan field visits' in portal['description']
    assert 'unpublished decoy' not in json.dumps(after)
    for node, original in ((product, initial), (portal, by_path(before, app))):
        for key in ('id', 'parent_id', 'position', 'source_ids', 'source_scopes', 'conversation_collections'):
            assert node[key] == original[key], key
    shown = space.view(cache, action='show', within=product['id'])['center']
    assert shown['contents']['description_source'] == dict(
        basis='harvested_readme', path=str(snapshot / 'README.md'))
    assert any(clue['text'] == 'Syntax Status' for clue in product['clues'])
    assert any(clue['basis'] == 'package_manifest' and clue['text'] == initial['description']
               for clue in product['clues'])
    conn.close()


@pytest.mark.parametrize('kind', ['planet', 'moon'])
@pytest.mark.parametrize('same_words', [False, True])
def test_authored_navcom_description_wins_even_for_experiments(tmp_path, kind, same_words):
    root = git(tmp_path / 'clients' / 'Cobalt' / 'Seagrass')
    authored = 'The owner-defined purpose of this undertaking.'
    package(root, name='ui-components', description=authored if same_words else 'Incidental component package')
    (root / '.navcom-space.json').write_text(json.dumps(dict(kind=kind, description=authored)))
    sources = source_cache(tmp_path, [root], [])
    snapshot = sources / 'artifacts' / '0' / 'source'
    snapshot.mkdir()
    (snapshot / 'README.md').write_text('# Seagrass\nRetained broader project description.\n')
    conn = database([(root, 'Saved context')])
    cache = tmp_path / 'space.json'
    data = space.refresh(API, conn, cache, source_cache=sources)
    node = by_path(data, root)
    assert node['description'] == authored
    assert node['kind'] == kind
    shown = space.view(cache, action='show', within=node['id'])['center']
    assert shown['contents']['description_source'] == dict(
        basis='owner_declaration', path=str(root / '.navcom-space.json'))
    assert any(clue['basis'] == 'harvested_readme' for clue in node['clues'])
    conn.close()


def test_nested_component_readme_does_not_relabel_its_containing_product(tmp_path):
    root = git(tmp_path / 'clients' / 'Cobalt' / 'Estuary')
    package(root, name='estuary', description='Current product metadata')
    component = root / 'internal' / 'theme'
    component.mkdir(parents=True)
    sources = source_cache(tmp_path, [root, component], [])
    root_snapshot = sources / 'artifacts' / '0' / 'source'
    root_snapshot.mkdir()
    (root_snapshot / 'README.md').write_text('# Estuary\nCoordinates the complete coastal observation service.\n')
    nested_snapshot = sources / 'artifacts' / '1' / 'source'
    nested_snapshot.mkdir()
    (nested_snapshot / 'README.md').write_text('# Theme\nA small color palette for controls.\n')
    conn = database([(root, 'Service context'), (component, 'Theme implementation')])
    cache = tmp_path / 'space.json'
    data = space.refresh(API, conn, cache, source_cache=sources)
    product = by_path(data, root)
    assert 'complete coastal observation service' in product['description']
    assert 'small color palette' not in product['description']
    assert any('small color palette' in clue['text'] for clue in product['clues'])
    assert set(product['source_ids']) == {'0', '1'}
    assert product['conversation_count'] == 2
    conn.close()
