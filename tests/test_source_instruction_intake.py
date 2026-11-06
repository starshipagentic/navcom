"""Authored agent instructions survive native intake without opening settings."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest

import navcom_source_discovery as discovery
from navcom_source_policy import instruction_document, permitted_path


def put(root, name, content='InstructionContextMarker: review the supplied evidence.\n'):
    target = root / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    return target


@pytest.fixture
def instructions(tmp_path):
    root = tmp_path / 'quartz-toolbox'
    root.mkdir()
    subprocess.run(['git', 'init', '-q', str(root)], check=True)
    accepted = {
        '.claude/commands/triage.md', '.claude/commands/team/review.md',
        '.claude/agents/reviewer.md', '.claude/skills/receipt/SKILL.md',
        '.claude/skills/receipt/references/format.md', '.agents/skills/audit/SKILL.md',
        '.codex/prompts/inspect.md', '.codex/skills/report/SKILL.md',
        'commands/repair.md', 'project-quartz-commands/diagnose.md',
        'project-quartz-agents/reviewer.md', 'bundled-skills/receipt/SKILL.md',
        'CLAUDE.md', 'AGENTS.md',
    }
    rejected = {
        '.claude/settings.json', '.claude/settings.local.json', '.claude/notes.md',
        '.claude/commands/.env', '.claude/commands/secrets/README.md',
        '.claude/agents/credentials/token.md', '.claude/commands/generated/report.md',
        '.claude/skills/receipt/scripts/run.py', '.claude/commands/run.sh',
        '.codex/config.toml', '.agents/settings.md', '.other/commands/triage.md',
        'project-quartz-commands/.private/README.md', 'arbitrary-notes.md',
        '.claude/commands/ignored.md',
    }
    for name in accepted:
        put(root, name)
    for name in rejected:
        put(root, name, 'PRIVATE_INPUT_SENTINEL\n')
    (root / '.gitignore').write_text('.claude/commands/ignored.md\n.claude/commands/tracked.md\n')
    put(root, '.claude/commands/tracked.md')
    subprocess.run(['git', '-C', str(root), 'add', '-f', '.claude/commands/tracked.md'], check=True)
    accepted.add('.claude/commands/tracked.md')
    outside = put(tmp_path, 'outside.md', 'SYMLINK_SENTINEL\n')
    (root / '.claude/commands/link.md').symlink_to(outside)
    rejected.add('.claude/commands/link.md')
    return root, accepted, rejected


def test_known_instruction_locations_use_existing_git_scope_and_guards(instructions):
    root, accepted, rejected = instructions
    selected, coverage = discovery._metadata(root)
    assert set(selected) == accepted
    assert not set(selected) & rejected
    assert coverage['metadata_files'] == len(accepted) and coverage['code_files'] == 0
    reasons = {item['path']: item['reason'] for item in coverage['excluded']}
    assert reasons['.claude/commands/ignored.md'] == 'Git ignored automatic input'
    assert reasons['.claude/commands/link.md'] == 'symlink'
    assert reasons['.claude/settings.json'] == 'hidden, secret or generated path'
    assert discovery._metadata(root) == (selected, coverage)


def test_instruction_metadata_keeps_size_count_and_depth_limits(tmp_path, monkeypatch):
    root = tmp_path / 'source'
    put(root, '.claude/commands/oversize.md', 'x' * 1025)
    put(root, '.claude/commands/kept.md')
    put(root, '.claude/commands/another.md')
    put(root, '.claude/commands/a/b/c/d/e/deep.md')
    monkeypatch.setattr(discovery, 'MAX_METADATA_FILES', 1)
    selected, coverage = discovery._metadata(root, max_file_bytes=1024)
    assert len(selected) == 1
    reasons = {item['path']: item['reason'] for item in coverage['excluded']}
    assert reasons['.claude/commands/oversize.md'] == 'metadata file size limit'
    assert any('depth budget' in reason for reason in reasons.values())
    assert 'metadata file/byte budget exceeded' in coverage['limits']


@pytest.mark.parametrize('path', ['.private/commands/a.md', '.claude/settings.md',
    '.claude/commands/.local/a.md', '.claude/skills/a/scripts/run.py',
    '.claude/commands/secrets/a.md', '.agents/commands/a.md', '../commands/a.md'])
def test_no_arbitrary_hidden_or_private_path_exception(path):
    assert not permitted_path(path)


def test_visible_exported_instructions_are_not_an_arbitrary_markdown_allowlist():
    assert instruction_document('backup-project-commands/inspect.md')
    assert instruction_document('agents/reviewer.md')
    assert not instruction_document('backup-project-config/settings.md')
    assert not instruction_document('commands/settings.json')


@pytest.mark.skipif(not shutil.which('starforge'), reason='Installed native Starforge required')
def test_native_harvest_search_read_cache_and_policy_fingerprint(instructions, tmp_path):
    from test_sources_worker_cache import native
    root, accepted, _ = instructions
    selected, _ = discovery._metadata(root)
    result = native(r'''
import json
from pathlib import Path
import navcom_sources_worker as worker
from navcom_source_reader import read_source
root=Path(sys.argv[3]); selected=json.loads(sys.argv[4]); cache=Path(sys.argv[2])/'cache'
source=dict(id='quartz-instructions',root=str(root),label='Quartz instructions',include=selected)
payload,_,_=worker.source_bytes(source)
assert set(payload)==set(selected)
assert not any(b'PRIVATE_INPUT_SENTINEL' in value or b'SYMLINK_SENTINEL' in value for value in payload.values())
first=worker.refresh([source],cache)
found=worker.combined_search(dict(query='InstructionContextMarker',within=source['id'],mode='both',limit=100),cache)
paths={hit['relative_path'] for hit in found['text_hits']}
assert paths==set(selected), (paths,selected)
hit=next(hit for hit in found['text_hits'] if hit['relative_path']=='.claude/commands/triage.md')
ref=hit['source_ref']
opened=read_source(ref['source_id'],ref['relative_path'],cache_path=cache,snapshot=ref['snapshot'],published=ref['published'])
assert 'InstructionContextMarker' in ''.join(line['text'] for line in opened['lines'])
assert worker.refresh([source],cache)['analyzed_sources']==0
assert worker.combined_search(dict(query='InstructionContextMarker',within=source['id'],mode='both',limit=100),cache)['query_cache_hit']
# Explicit source selections cannot bypass the hidden/private instruction policy.
unsafe=dict(source,include=['.claude/commands/triage.md','.claude/settings.json','.claude/commands/secrets/README.md'])
assert set(worker.source_bytes(unsafe)[0])=={'.claude/commands/triage.md'}
linked=root/'.claude/commands/local-link'; linked.symlink_to(root/'commands',target_is_directory=True)
try: worker.source_bytes(dict(source,include=['.claude/commands/local-link/repair.md']))
except ValueError: pass
else: raise AssertionError('Explicit symlink ancestor was accepted')
harvest,query=worker.extractor_signature(),worker.query_signature()
policy=Path(sys.argv[2])/'policy-copy.py'; policy.write_bytes(Path(worker.navcom_source_policy.__file__).read_bytes())
worker.navcom_source_policy.__file__=str(policy)
assert worker.extractor_signature()==harvest
policy.write_text(policy.read_text()+'\nPOLICY_VERSION = 2\n')
assert worker.extractor_signature()!=harvest and worker.query_signature()==query
print(json.dumps(dict(harvested=first['analyzed_sources'],text_hits=len(paths),read_path=ref['relative_path'])))
''', tmp_path, str(root), json.dumps(selected))
    assert result == dict(harvested=1, text_hits=len(accepted), read_path='.claude/commands/triage.md')
