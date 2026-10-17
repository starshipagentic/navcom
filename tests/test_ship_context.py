"""Native carried-context recovery is distinct from host search or captain resume."""
import hashlib
import json
import os
from pathlib import Path

import pytest

import navcom_atlas_cli
import navcom_ship_context as context


TOOL = Path.home() / '.codex/skills/ship-commission/scripts/navcom.py'


@pytest.fixture
def ship(tmp_path):
    root = tmp_path / 'Orchard ship'
    catalog = root / '.starship/navcom/index.json'
    catalog.parent.mkdir(parents=True)
    store = root / '.starship/secrets/navcom'
    store.mkdir(parents=True)
    records = []
    for number, messages in enumerate([
        [(3, 'user', 'Why did Orchard choose amber storage?'),
         (7, 'assistant', 'Amber storage preserves the original evidence and recovery trail.'),
         (12, 'user', 'What remains for the next captain?')],
        [(2, 'assistant', 'Next: verify orchard login after restore.')],
    ]):
        identity = f'session-{number}'
        record = dict(id=identity, provider='fixture', messages=[dict(index=i, role=r, text=t) for i,r,t in messages])
        path = store / f'fixture-{identity}.json'
        raw = json.dumps(record).encode(); path.write_bytes(raw)
        records.append(dict(id=identity,provider='fixture',file=str(path.relative_to(root)),
                            sha256=hashlib.sha256(raw).hexdigest(),title='Orchard design',project='/original/orchard',messages=len(messages)))
    catalog.write_text(json.dumps(dict(version=1, sessions=records)))
    (root / '.starship/HANDOVER.md').write_text('# Orchard\nRecover amber storage decisions, then verify login.\n')
    # A project copy is not used, even when the ship contains one.
    (root / '.starship/navcom.py').write_text("raise RuntimeError('PROJECT CODE MUST NOT RUN')\n")
    entity = dict(id='fleet:ship:orchard',kind='ship',label='Orchard',parent_id='galaxy:owner',
                  physical=dict(host='localhost',path=str(root)),position={},locations=[],evidence=[],examples=[])
    return entity, root, catalog


def require_native():
    if not TOOL.is_file():
        pytest.skip('Installed ship-commission native reader required')


def test_metadata_inventory_does_not_read_private_dialogue(ship, monkeypatch):
    entity, root, catalog = ship
    read = context._read
    def guarded(root, relative, maximum):
        assert str(relative) == str(context.CATALOG)
        return read(root, relative, maximum)
    monkeypatch.setattr(context, '_read', guarded)
    first = context.inspect_context(entity, limit=1)
    assert first['state']=='available' and first['total_sessions']==2
    assert first['sessions'][0]['id']=='session-0' and first['next_offset']==1
    assert not first['coverage']['dialogue_read'] and not first['coverage']['complete']
    second = context.inspect_context(entity, offset=1, limit=1)
    assert second['sessions'][0]['id']=='session-1' and second['coverage']['complete']


def test_installed_native_search_page_open_and_literal_query(ship):
    require_native()
    entity, root, catalog = ship
    before={str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()}
    first=context.read_context(entity, query='amber', limit=1, max_chars=20)
    assert first['state']=='available' and first['returned']==1 and first['next_offset']==1
    hit=first['messages'][0]
    assert hit['id']=='session-0' and hit['index']==3 and hit['text_truncated']
    assert hit['title']=='Orchard design' and hit['project']=='/original/orchard'
    second=context.read_context(entity, query='amber', offset=first['next_offset'],limit=1)
    assert second['messages'][0]['index']==7 and second['next_offset'] is None
    opened=context.read_context(entity, action='open', ref=hit['id'], turn=hit['index'])
    assert opened['messages'][0]['text']=='Why did Orchard choose amber storage?'
    assert context.read_context(entity, action='open',ref='session-0',turn=4)['messages']==[]
    assert context.read_context(entity, query='--help')['messages']==[]
    assert opened['provenance']['tool']['path']==str(TOOL.resolve())
    assert all(r['catalog_hash_verified'] for r in opened['provenance']['records'])
    assert before=={str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()}
    assert not list(root.rglob('__pycache__'))


def test_handover_pages_are_exact_and_separate_from_dialogue(ship):
    entity, root, _ = ship
    first=context.read_context(entity, action='handover', max_chars=12)
    second=context.read_context(entity, action='handover', offset=first['next_offset'],max_chars=100)
    assert first['context_kind']=='handover' and first['text_truncated']
    assert first['text']+second['text']==(root/'.starship/HANDOVER.md').read_text()
    assert second['coverage']['complete'] and first['messages']==[]


@pytest.mark.parametrize('case',['fifo','linked-parent'])
def test_context_leaf_or_directory_cannot_block_or_redirect_read(ship,case):
    entity,root,catalog=ship
    if case=='fifo':
        handover=root/'.starship/HANDOVER.md';handover.unlink();os.mkfifo(handover)
        result=context.read_context(entity,action='handover')
    else:
        directory=catalog.parent;other=directory.with_name('moved-catalog');directory.rename(other);directory.symlink_to(other,target_is_directory=True)
        result=context.inspect_context(entity)
    assert result['state']=='unavailable' and not result['coverage']['complete']


@pytest.mark.parametrize('host',['remote.invalid',None,''])
def test_remote_ship_never_reads_local_path_or_loads_reader(ship,monkeypatch,host):
    entity, _, _=ship; entity['physical']['host']=host
    monkeypatch.setattr(context,'_read',lambda *_:pytest.fail('Remote namespace read locally'))
    monkeypatch.setattr(context,'_tool',lambda *_:pytest.fail('Remote reader loaded'))
    for action in ('inspect','search','handover'):
        data=context.inspect_context(entity) if action=='inspect' else context.read_context(entity, action=action,query='amber')
        assert data['state']=='unavailable' and not data['coverage']['complete']


@pytest.mark.parametrize('case',['outside','credential','linked','hash','identity'])
def test_only_exact_catalog_bound_dialogue_is_eligible(ship,monkeypatch,case):
    entity, root, catalog=ship
    data=json.loads(catalog.read_text()); record=data['sessions'][0]; path=root/record['file']
    if case=='outside':record['file']='../../other.json'
    elif case=='credential':record['file']='.starship/secrets/credentials.json'
    elif case=='linked':
        target=root/'unrelated.json';path.rename(target);path.symlink_to(target)
    elif case=='hash':path.write_text('{}')
    else:
        content=json.loads(path.read_text());content['id']='wrong';raw=json.dumps(content).encode();path.write_bytes(raw)
        record['sha256']=hashlib.sha256(raw).hexdigest()
    catalog.write_text(json.dumps(data))
    monkeypatch.setattr(context,'_tool',lambda *_:pytest.fail('Invalid cargo loaded native reader'))
    result=context.read_context(entity,query='amber')
    assert result['state']=='unavailable' and result['messages']==[] and not result['coverage']['complete']


def test_read_budget_is_explicit_and_exact_open_can_narrow_session_scope(ship,monkeypatch):
    require_native()
    entity, root, catalog=ship
    # Each record fits, but the combined search exceeds the fixed byte budget.
    entries=json.loads(catalog.read_text())['sessions']
    maximum=max((root/r['file']).stat().st_size for r in entries)
    monkeypatch.setattr(context,'TOTAL_BYTES',maximum)
    result=context.read_context(entity,query='amber')
    assert result['state']=='unavailable' and 'bound' in result['reason']
    assert context.read_context(entity, action='open',ref='session-0')['state']=='available'


def test_native_reader_uses_one_pinned_generation_if_live_cargo_changes(ship,monkeypatch):
    require_native()
    entity, root, catalog=ship
    original=context.subprocess.run
    def changed(argv,**kwargs):
        record=json.loads(catalog.read_text())['sessions'][0]
        (root/record['file']).write_text('changed after snapshot')
        result=original(argv,**kwargs)
        assert str(root) not in argv and not Path(argv[argv.index('--ship')+1]).samefile(root)
        return result
    monkeypatch.setattr(context.subprocess,'run',changed)
    result=context.read_context(entity,query='amber')
    assert result['state']=='available' and len(result['messages'])==2
    assert 'unchanged' in result['provenance']['isolation']


def test_open_can_pin_the_catalog_from_prior_search(ship):
    require_native()
    entity,root,catalog=ship
    found=context.read_context(entity,query='amber')
    expected=found['provenance']['catalog_sha256']
    assert context.read_context(entity,action='open',ref='session-0',turn=3,expected_catalog=expected)['state']=='available'
    data=json.loads(catalog.read_text());data['activated_at']='new-generation';catalog.write_text(json.dumps(data))
    result=context.read_context(entity,action='open',ref='session-0',turn=3,expected_catalog=expected)
    assert result['state']=='unavailable' and 'catalog changed' in result['reason']


def test_human_render_exposes_original_turn_and_continuation(ship,capsys):
    require_native()
    result=context.read_context(ship[0],query='amber',limit=1)
    navcom_atlas_cli.render_context(result)
    output=capsys.readouterr().out
    assert 'session-0 · turn 3' in output and '--offset 1' in output
    assert 'not current host history' in output and 'amber storage' in output


@pytest.mark.parametrize('kwargs',[dict(query=''),dict(query='x'*501),dict(query='x',offset=-1),
    dict(query='x',limit=51),dict(query='x',max_chars=8001),dict(action='open',ref=''),dict(query='x',turn=1)])
def test_bad_request_bounds_reject_before_access(ship,monkeypatch,kwargs):
    monkeypatch.setattr(context,'_selection',lambda *_:pytest.fail('Bad request accessed ship'))
    with pytest.raises(ValueError):context.read_context(ship[0],**kwargs)
