"""A background harvest must not make unchanged native retrieval cold again."""
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

import pytest

from test_sources_worker_cache import native
from test_relationships import example, cli as related_cli, harvest

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(not shutil.which('starforge'), reason='Optional native Starforge required')


def source_cli(cache, *args, ok=True):
    result = subprocess.run([sys.executable, str(ROOT / 'navcom.py'), 'sources',
        *map(str, args), '--cache', str(cache), '--json'], capture_output=True, text=True, timeout=30)
    assert (result.returncode == 0) is ok, result.stderr
    return json.loads(result.stdout) if ok else result


def test_public_native_query_reuses_unchanged_source_and_repins_after_unrelated_harvest(tmp_path):
    root, other, cache = tmp_path / 'quartz', tmp_path / 'violet', tmp_path / 'cache'
    root.mkdir(); other.mkdir()
    (root / 'worker.py').write_text('\n'.join(
        ['"""Marmot optical calibration workflow."""', 'def calibrate(value):']
        + [f'    step_{i} = value + {i}' for i in range(24)] + ['    return step_23', '']))
    (root / 'README.md').write_text('# Marmot calibration\nRetained source documentation.\n')
    (other / 'README.md').write_text('# Violet\nAn unrelated publication.\n')
    source_cli(cache, 'harvest', root, '--index', tmp_path / 'no-index')
    first = source_cli(cache, 'search', 'marmot', '--within', 'quartz')
    assert first['concept_hits'] and first['text_hits'] and not first['query_cache_hit']
    source_cli(cache, 'harvest', other, '--index', tmp_path / 'no-index')
    reused = source_cli(cache, 'search', 'marmot', '--within', 'quartz')
    assert reused['query_cache_hit'] and reused['harvest_invocations'] == 0
    assert reused['published'] != first['published']
    for kind in ('concept_hits', 'text_hits'):
        before, after = first[kind][0], reused[kind][0]
        assert before['source_ref']['snapshot'] == after['source_ref']['snapshot']
        assert after['source_ref']['published'] == reused['published']
        assert after['relative_path'] == before['relative_path']
        ref = after['source_ref']
        opened = source_cli(cache, 'read', ref['source_id'], ref['relative_path'],
            '--line', ref['line'], '--limit', 2, '--snapshot', ref['snapshot'], '--published', ref['published'])
        assert opened['snapshot'] == ref['snapshot'] and not opened['provenance']['current_file_read']
    (root / 'README.md').write_text('# Marmot calibration\nA newly harvested revision.\n')
    source_cli(cache, 'harvest', root, '--index', tmp_path / 'no-index')
    changed = source_cli(cache, 'search', 'marmot', '--within', 'quartz')
    assert not changed['query_cache_hit']
    assert changed['text_hits'][0]['source_ref']['snapshot'] != reused['text_hits'][0]['source_ref']['snapshot']
    ref = reused['text_hits'][0]['source_ref']
    rejected = source_cli(cache, 'read', ref['source_id'], ref['relative_path'],
        '--snapshot', ref['snapshot'], '--published', ref['published'], ok=False)
    assert 'snapshot changed' in rejected.stderr


def test_native_zero_partial_and_exact_scopes_reuse_but_missing_source_fails(tmp_path):
    result = native('''
import json
from pathlib import Path
import navcom_sources_worker as w
b=Path(sys.argv[2]);a=b/'alpha';z=b/'zulu';a.mkdir();z.mkdir();cache=b/'cache'
(a/'README.md').write_text('Marmot first\\nMarmot second\\n')
(a/'notes.md').write_text('Marmot private scope\\n')
(z/'README.md').write_text('Unrelated source\\n')
alpha=dict(id='alpha',root=str(a),label='Alpha',include=['.'])
zulu=dict(id='zulu',root=str(z),label='Zulu',include=['.'])
w.refresh([alpha],cache)
partial=dict(query='Marmot',within='alpha',mode='text',paths=['README.md'],limit=1)
zero=dict(query='AbsentTerm',within='alpha',mode='both',limit=2)
first=w.combined_search(partial,cache);assert first['potentially_truncated']
assert not w.combined_search(zero,cache)['text_hits']
w.refresh([zulu],cache,merge=True)
reused=w.combined_search(partial,cache);empty=w.combined_search(zero,cache)
assert reused['query_cache_hit'] and reused['potentially_truncated']
assert empty['query_cache_hit'] and not empty['text_hits'] and not empty['concept_hits']
assert not w.combined_search(dict(partial,paths=['notes.md']),cache)['query_cache_hit']
assert not w.combined_search(dict(partial,limit=2),cache)['query_cache_hit']
assert not w.combined_search(dict(partial,mode='both'),cache)['query_cache_hit']
state=w.read(cache/'current.json');source=next(s for s in state['sources']if s['id']=='alpha')
artifact=Path(source['artifact']);artifact.rename(artifact.with_name('offline-'+artifact.name))
for request in (zero,partial):
 try:w.combined_search(request,cache)
 except ValueError as error:assert 'artifact is unavailable' in str(error)
 else:raise AssertionError('unavailable immutable input returned a cached result')
w.refresh([zulu],cache)
try:w.combined_search(zero,cache)
except ValueError as error:assert 'exactly one source' in str(error)
else:raise AssertionError('removed source returned cached zero hits')
print(json.dumps(dict(zero_cached=True,partial_preserved=True,scope_isolated=True,missing_rejected=True)))
''', tmp_path)
    assert all(result.values())


def test_cached_original_publication_is_validated_before_repining(tmp_path):
    result = native('''
import json
from pathlib import Path
import navcom_sources_worker as w
b=Path(sys.argv[2]);a=b/'alpha';z=b/'zulu';a.mkdir();z.mkdir();cache=b/'cache'
(a/'README.md').write_text('Marmot retained source\\n');(z/'README.md').write_text('Other source\\n')
alpha=dict(id='alpha',root=str(a),label='Alpha',include=['.'])
zulu=dict(id='zulu',root=str(z),label='Zulu',include=['.'])
w.refresh([alpha],cache)
request=dict(query='Marmot',within='alpha',mode='text')
w.combined_search(request,cache)
memo=next((cache/'queries').glob('*.json'));bad=w.read(memo)
bad['text_hits'][0]['source_ref']['published']+=1;w.write(memo,bad)
w.refresh([zulu],cache,merge=True)
try:w.combined_search(request,cache)
except ValueError as error:assert 'reference does not match' in str(error)
else:raise AssertionError('a mismatched original publication was silently repinned')
print(json.dumps(dict(rejected=True)))
''', tmp_path)
    assert result['rejected']


def test_related_copied_read_commands_keep_snapshot_across_other_publications(example):
    found = related_cli(example)
    member = found['families'][0]['members'][0]
    commands = [member['read_command'], found['references'][0]['read_command']]
    commands += [file['read_command'] for file in member['representative_files']]
    other = example['root'].parent / 'unrelated'
    other.mkdir(); (other / 'README.md').write_text('# New independent source\n')
    harvest(example['sources'] + [dict(id='other',root=str(other),label='Other',include=['.'])], example['cache'])
    for command in commands:
        args = shlex.split(command)
        assert '--snapshot' in args and '--published' in args
        opened = subprocess.run([sys.executable, str(ROOT / 'navcom.py'), *args[1:], '--json'],
            capture_output=True, text=True, timeout=15)
        assert opened.returncode == 0, opened.stderr
        read = json.loads(opened.stdout)
        assert read['provenance']['publication_changed']
        assert not read['provenance']['current_file_read']
        assert read['snapshot'] == args[args.index('--snapshot') + 1]
