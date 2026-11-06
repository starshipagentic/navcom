"""Literal recorded Git repository links, never product or generation inference."""
import json
import shlex
import subprocess
import sys

import pytest

import navcom_relationships as relationships
from test_relationships import ROOT, example, harvest, cli


def repository(example, origin='forge.example/optics/instruments'):
    chart = json.loads(example['chart'].read_text())
    node = next(n for n in chart['entities'] if n['id'] == 'planet:instrument')
    node['evidence'] = [dict(type='repository_identity', basis='Git origin', origin=origin,
                             path=str(example['target']))]
    example['chart'].write_text(json.dumps(chart))
    return chart


def test_native_cli_repository_urls_paths_mismatches_and_pinned_reader(example):
    chart = repository(example)
    lines = [
        '# Orchard',
        '[Commit](https://FORGE.EXAMPLE/optics/instruments/commit/abc123)',
        '<https://forge.example/optics/instruments.git>',
        'git@forge.example:optics/instruments.git',
        '[Code](https://forge.example/optics/instruments/blob/main/src/calibrate.py#L3)',
        'https://forge.example/optics/instruments.',
        'https://forge.example/optics/instruments-extra',
        'https://different.example/optics/instruments',
        'https://forge.example.evil/optics/instruments',
        'https://elsewhere.example/forge.example/optics/instruments',
        'https://forge.example/optics/instruments/../elsewhere',
        'https://user:DO_NOT_EXPOSE@forge.example/optics/instruments?token=HIDDEN#fragment',
        'ssh://git@forge.example:2222/optics/instruments.git',
        'https://user:DO_NOT_EXPOSE@forge.example:8443/optics/instruments/commit/abc123?token=HIDDEN#fragment',
        'https://forge.example:8443/optics/instruments-extra',
        'ssh://git@different.example:2222/optics/instruments.git',
    ]
    (example['root']/'README.md').write_text('\n'.join(lines)+'\n')
    harvest(example['sources'], example['cache'])
    chart_bytes = example['chart'].read_bytes()
    first = cli(example)
    refs = first['references']
    assert [r['line'] for r in refs] == [2, 3, 4, 5, 6, 12, 13, 14]
    assert all(r['kind'] == 'documented_repository_reference' for r in refs)
    assert all(r['target_origin'] == 'forge.example/optics/instruments' for r in refs)
    assert all(r['destination_ids'] == ['planet:instrument'] for r in refs)
    assert all(r['target_source_id'] == 'instruments' for r in refs)
    assert all('no shared product identity' in r['meaning'] for r in refs)
    assert all(r['source_ref']['relative_path'] == 'README.md' for r in refs)
    assert 'DO_NOT_EXPOSE' not in json.dumps(first) and 'HIDDEN' not in json.dumps(first)
    assert not first['cached'] and first['harvest_invocations'] == 0
    second = cli(example)
    assert second['cached'] and second['fingerprint'] == first['fingerprint']
    assert second['references'] == first['references']
    assert example['chart'].read_bytes() == chart_bytes
    args = shlex.split(refs[0]['read_command'])
    read = subprocess.run([sys.executable, str(ROOT/'navcom.py'), *args[1:], '--json'],
                          capture_output=True, text=True, timeout=20)
    assert read.returncode == 0, read.stderr
    assert '/commit/abc123' in read.stdout
    # The reader remains exact even when the live source file subsequently moves.
    (example['root']/'README.md').unlink()
    assert cli(example)['cached']


def test_native_reference_scope_target_change_and_nested_identity(example):
    chart = repository(example)
    nested = dict(chart['entities'][-1], id='planet:nested', label='Separate nested repository',
                  locations=[dict(path=str(example['target']/'nested'))],
                  evidence=[dict(type='repository_identity', basis='Git origin',
                      origin='forge.example/optics/instruments/nested', path=str(example['target']/'nested'))])
    chart['entities'].append(nested)
    example['chart'].write_text(json.dumps(chart))
    (example['root']/'README.md').write_text('https://forge.example/optics/instruments/nested/tree/main/notes.md\n')
    (example['root']/'engines/v2/README.md').write_text('Exact scoped note; no repository link.\n')
    harvest(example['sources'], example['cache'])
    first = cli(example)
    assert len(first['references']) == 1
    assert first['references'][0]['destination_ids'] == ['planet:nested']
    assert first['references'][0]['target_source_id'] is None
    scoped = relationships.related(example['chart'], example['cache'], 'moon:v2')
    assert not scoped['references']
    # Origin identity belongs to this chart publication and affects memo identity.
    chart['entities'][-1]['evidence'][0]['origin'] = 'forge.example/elsewhere/nested'
    example['chart'].write_text(json.dumps(chart))
    changed = cli(example)
    assert not changed['cached'] and changed['fingerprint'] != first['fingerprint']


def test_only_recorded_remote_identity_supplies_targets():
    rows = [dict(id='planet:x',kind='planet',evidence=[
        dict(type='package_manifest', origin='forge.example/a/b', path='/work/x'),
        dict(type='repository_identity', origin='file:/private/local', path='/work/x'),
        dict(type='repository_identity', origin='forge.example/a/b', path='/work/x')])]
    assert relationships._repository_targets(dict(entities=rows)) == [
        dict(origin='forge.example/a/b', root='/work/x', destination_id='planet:x')]
