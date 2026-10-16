"""Native, unfamiliar source fixtures; no production catalogs or model calls."""
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

import pytest

import navcom_relationships as relationships
from navcom_sources import runtime

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(not shutil.which('starforge'), reason='Optional native Starforge runtime required')


def harvest(sources, cache):
    result = subprocess.run([runtime(), '-I', '-B', '-c',
        'import json,sys;from pathlib import Path;sys.path.insert(0,sys.argv[1]);'
        'import navcom_sources_worker as w;print(json.dumps(w.refresh(json.loads(sys.argv[2]),Path(sys.argv[3]))))',
        str(ROOT), json.dumps(sources), str(cache)], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.fixture
def example(tmp_path):
    root = tmp_path / 'orchard'
    target = tmp_path / 'instrument-house'
    target.mkdir()
    (target / 'README.md').write_text('# Instrument house\nExpertise has its own independent home.\n')
    for folder in ['engines/v1', 'engines/v2', 'engines/v3', 'LABS/exp91', 'LABS/exp92']:
        path = root / folder
        path.mkdir(parents=True)
        (path / 'README.md').write_text('# ' + folder + '\nRetained research notes.\n')
        (path / 'calibration.py').write_text('"""Orchard optical calibration."""\n'
            'def calibrate(value):\n    """Observe a spectrum."""\n' +
            ''.join('    step' + str(i) + ' = value + ' + str(i) + '\n' for i in range(25)) +
            '    return value\n# UNIQUE_' + folder.replace('/', '_') + '\n')
    (root / 'README.md').write_text('# Orchard\nReference: [' + str(target / 'HANDOFF.md') + '](' +
                                  str(target / 'HANDOFF.md') + ')\n')
    sources = [dict(id=name, root=str(path), label=path.name, include=['.'])
               for name, path in [('orchard', root), ('instruments', target)]]
    cache = tmp_path / 'sources'
    harvest(sources, cache)
    nodes = [dict(id='galaxy:owner', kind='galaxy', label='Fixture', parent_id=None, locations=[], source_scopes=[]),
        dict(id='planet:orchard', kind='planet', label='Orchard', parent_id='galaxy:owner',
             locations=[dict(path=str(root))], source_scopes=[dict(source_id='orchard', paths=['.'])]),
        dict(id='moon:v2', kind='moon', label='Existing v2', parent_id='planet:orchard',
             locations=[dict(path=str(root / 'engines/v2'))], source_scopes=[dict(source_id='orchard', paths=['engines/v2'])]),
        dict(id='planet:instrument', kind='planet', label='Instrument house', parent_id='galaxy:owner',
             locations=[dict(path=str(target))], source_scopes=[dict(source_id='instruments', paths=['.'])])]
    for node in nodes:
        node.update(evidence=[], examples=[], conversation_count=0, conversation_collections=[],
                    source_ids=[scope['source_id'] for scope in node['source_scopes']],
                    status='suggested', position=dict(x=0, y=0), commands={})
    chart = tmp_path / 'space.json'
    chart.write_text(json.dumps(dict(schema_version=1, entities=nodes, edges=[], published=123, coverage={})))
    return dict(root=root, target=target, sources=sources, cache=cache, chart=chart)


def cli(example, *extra):
    result = subprocess.run([sys.executable, '-m', 'navcom_relationships', 'planet:orchard',
        '--space-cache', str(example['chart']), '--source-cache', str(example['cache']), '--json', *extra],
        cwd=ROOT, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_native_cli_version_family_references_and_cache(example):
    before = example['chart'].read_bytes()
    first = cli(example)
    assert not first['cached'] and first['harvest_invocations'] == 0
    assert len(first['families']) == 1
    family = first['families'][0]
    assert family['engine'] == 'starforge.lineage.LineageDetector.detect_repo_lineages'
    assert family['kind'] == 'version_family_suggestion'
    assert [member['path'] for member in family['members']] == ['engines/v1', 'engines/v2', 'engines/v3']
    assert family['members'][1]['destination_ids'] == ['moon:v2']
    assert all(' --path engines/v' in member['search_command'] for member in family['members'])
    for member in family['members']:
        files = member['representative_files']
        assert 1 <= len(files) <= 3 and files[0]['relative_path'].endswith('/README.md')
        assert files[1]['relative_path'].endswith('/calibration.py')
        assert all(file['source_ref']['relative_path'].startswith(member['path'] + '/') for file in files)
        assert all(file['source_ref']['snapshot'] == family['source_snapshot'] for file in files)
    assert 'not dated succession' in family['meaning']
    assert len(first['references']) == 1
    reference = first['references'][0]
    assert reference['kind'] == 'documented_path_reference' and reference['target_source_id'] == 'instruments'
    assert reference['path'] == 'README.md' and reference['line'] == 2
    assert reference['destination_ids'] == ['planet:instrument']
    assert example['chart'].read_bytes() == before
    second = cli(example)
    assert second['cached'] and second['fingerprint'] == first['fingerprint']


def test_scoped_query_never_widens_and_query_does_not_match_generated_commands(example):
    data = relationships.related(example['chart'], example['cache'], 'moon:v2', query='UNIQUE_engines_v2')
    assert not data['families'] and not data['references']
    hits = data['evidence'][0]['text_hits']
    assert hits and all(hit['relative_path'].startswith('engines/v2/') for hit in hits)
    miss = cli(example, '--query', 'absent-unrelated-query')
    assert miss['families'] == []


def test_plain_scoped_search_shows_both_native_paths(example, capsys):
    data = relationships.related(example['chart'], example['cache'], 'moon:v2', query='calibration')
    relationships.render(data)
    text = capsys.readouterr().out
    assert 'concept matches' in text and 'text matches' in text
    assert 'concept · engines/v2/calibration.py' in text and 'text · engines/v2/calibration.py:' in text
    assert 'No relationships found' not in text


def test_family_search_commands_preserve_exact_file_scope(example):
    chart = json.loads(example['chart'].read_text())
    paths = ['engines/v1/calibration.py', 'engines/v2/calibration.py']
    chart['entities'][1]['source_scopes'][0]['paths'] = paths
    example['chart'].write_text(json.dumps(chart))
    data = cli(example)
    family = data['families'][0]
    assert len(family['members']) == 2
    for member in family['members']:
        assert member['scope_paths'] == [member['path'] + '/calibration.py']
        args = shlex.split(member['search_command'])
        args[3] = 'calibration'
        result = subprocess.run([sys.executable, 'navcom.py', *args[1:], '--json'],
            cwd=ROOT, capture_output=True, text=True, timeout=20)
        assert result.returncode == 0, result.stderr
        evidence = json.loads(result.stdout)
        assert evidence['concept_hits'] and evidence['text_hits']
        assert all(hit['relative_path'] == member['scope_paths'][0]
                   for key in ['concept_hits', 'text_hits'] for hit in evidence[key])


def test_destination_enrichment_uses_pinned_native_source_roots(example, monkeypatch):
    original = relationships._run
    def publish_new_root(request, seconds):
        result = original(request, seconds)
        state_path = example['cache'] / 'current.json'
        state = json.loads(state_path.read_text())
        for source in state['sources']:
            if source['id'] == 'orchard':
                source['root'] = '/different/current/tree'
        state_path.write_text(json.dumps(state))
        return result
    monkeypatch.setattr(relationships, '_run', publish_new_root)
    data = relationships.related(example['chart'], example['cache'], 'planet:orchard')
    member = next(member for member in data['families'][0]['members'] if member['label'] == 'v2')
    assert member['destination_ids'] == ['moon:v2']
    assert data['source_roots']['orchard'] == str(example['root'])


def test_only_new_harvest_invalidates_relationship_cache(example):
    before = cli(example)
    shutil.rmtree(example['root'] / 'engines/v3')
    unchanged = cli(example)
    assert unchanged['cached'] and unchanged['fingerprint'] == before['fingerprint']
    harvest(example['sources'], example['cache'])
    after = cli(example)
    assert not after['cached'] and after['fingerprint'] != before['fingerprint']
    assert [member['path'] for member in after['families'][0]['members']] == ['engines/v1', 'engines/v2']


def test_invalid_scope_fails_without_global_fallback(example):
    data = json.loads(example['chart'].read_text())
    data['entities'][1]['source_scopes'][0]['paths'] = []
    example['chart'].write_text(json.dumps(data))
    with pytest.raises(ValueError, match='scope is missing or invalid'):
        relationships.related(example['chart'], example['cache'], 'planet:orchard')


def test_snapshot_link_cannot_read_other_tree(example, tmp_path):
    state = json.loads((example['cache'] / 'current.json').read_text())
    source = next(source for source in state['sources'] if source['id'] == 'orchard')
    snapshot = Path(source['artifact']) / 'source'
    snapshot.rename(snapshot.with_name('saved-source'))
    snapshot.symlink_to(example['root'], target_is_directory=True)
    with pytest.raises(ValueError, match='outside the configured source cache|linked path'):
        relationships.related(example['chart'], example['cache'], 'planet:orchard')


def test_known_root_reference_prefers_exact_target_over_ancestor(example):
    ancestor = example['target'].parent
    source = dict(id='container', root=str(ancestor), label='Container', include=['instrument-house/README.md'])
    # Cache containment policy intentionally rejects harvesting this ancestor;
    # retain its declared inventory identity in this isolated cache fixture only.
    state_path = example['cache'] / 'current.json'
    state = json.loads(state_path.read_text())
    state['sources'].append(source)
    state_path.write_text(json.dumps(state))
    data = cli(example)
    assert [ref['target_source_id'] for ref in data['references']] == ['instruments']


def test_unknown_child_path_never_links_to_broad_container(example):
    ancestor = example['target'].parent
    (example['root'] / 'README.md').write_text('# Orchard\nsource ' + str(ancestor / 'unharvested/.env') +
        '\nAPI_KEY=fixture-private-value cd ' + str(example['target']) + '\n')
    harvest(example['sources'], example['cache'])
    state_path = example['cache'] / 'current.json'
    state = json.loads(state_path.read_text())
    state['sources'].append(dict(id='container', root=str(ancestor), label='Container', include=['.'],
        discovery_coverage=dict(container_policy=dict(enabled=True))))
    state_path.write_text(json.dumps(state))
    data = cli(example)
    assert [ref['target_source_id'] for ref in data['references']] == ['instruments']
    assert data['references'][0]['line'] == 3
    assert data['references'][0]['excerpt'] == str(example['target'])
    assert 'fixture-private-value' not in json.dumps(data)
    assert data['coverage'][0]['reference_container_roots'] == 1


def test_source_pagination_is_explicit_and_does_not_drop_scopes(example, monkeypatch):
    chart = json.loads(example['chart'].read_text())
    chart['entities'][1]['source_scopes'] = [dict(source_id='source-' + str(i), paths=['.']) for i in range(11)]
    example['chart'].write_text(json.dumps(chart))
    seen = []
    def native(request, seconds):
        seen.append(request['scopes'])
        return dict(schema_version=1, families=[], references=[], evidence=[], coverage=[], published=123,
                    cached=False, harvest_invocations=0)
    monkeypatch.setattr(relationships, '_run', native)
    first = relationships.related(example['chart'], example['cache'], 'planet:orchard')
    second = relationships.related(example['chart'], example['cache'], 'planet:orchard', offset=first['next_offset'])
    assert first['source_total'] == 11 and first['next_offset'] == 8 and '--offset 8' in first['continue_command']
    assert second['next_offset'] is None
    assert len({scope['source_id'] for page in seen for scope in page}) == 11
