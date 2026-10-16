"""Physical copies remain separate from conceptual product identity."""
import json
import os
from pathlib import Path
import subprocess
import sys

import navcom
import navcom_place_inspection as observer
from navcom_web import WebApp


def git(path, *args):
    result = subprocess.run(['git', '-C', str(path), *args], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def repository(tmp_path):
    root = tmp_path / 'product'; root.mkdir()
    git(root, 'init', '-b', 'main')
    git(root, 'config', 'user.name', 'NavCom fixture')
    git(root, 'config', 'user.email', 'fixture@example.invalid')
    (root / 'README.md').write_text('Independent product fixture\n')
    git(root, 'add', '.'); git(root, 'commit', '-m', 'Initial product')
    return root


def place(*paths):
    return dict(id='planet:fixture', kind='planet', label='Fixture product',
                locations=[dict(path=str(p)) for p in paths], evidence=[], examples=[],
                source_ids=[], source_scopes=[], conversation_collections=[])


def test_native_worktrees_and_independent_copies_with_explicit_refresh(tmp_path, monkeypatch):
    root = repository(tmp_path); linked = tmp_path / 'linked'; copied = tmp_path / 'copied'
    git(root, 'worktree', 'add', '-b', 'experiment', str(linked))
    git(root, 'clone', str(root), str(copied))
    entity = place(root, linked, copied); cache = tmp_path / 'cache'
    first = observer.inspect_place(entity, cache)
    assert not first['cached'] and first['coverage']['observed'] == 3
    assert {r['kind'] for r in first['relationships']} == {'linked_worktrees', 'independent_repositories'}
    assert [p['git']['branch'] for p in first['locations']] == ['main', 'experiment', 'main']
    original = first['locations'][0]['git']['commit']
    (root / 'README.md').write_text('Product advanced\n'); git(root, 'commit', '-am', 'Advance')
    real = observer._git
    monkeypatch.setattr(observer, '_git', lambda *a: (_ for _ in ()).throw(AssertionError('Cached read ran Git')))
    cached = observer.inspect_place(entity, cache)
    assert cached['cached'] and cached['locations'][0]['git']['commit'] == original
    monkeypatch.setattr(observer, '_git', real)
    fresh = observer.inspect_place(entity, cache, refresh=True)
    assert fresh['locations'][0]['git']['commit'] != original
    assert fresh['locations'][1]['git']['commit'] == original
    assert all(not r['same_commit'] for r in fresh['relationships'] if r['left'] == str(root))


def test_wrong_git_environment_does_not_redirect_observation(tmp_path, monkeypatch):
    root = repository(tmp_path); elsewhere = tmp_path / 'elsewhere'; elsewhere.mkdir()
    git(elsewhere, 'init', '-b', 'wrong')
    monkeypatch.setenv('GIT_DIR', str(elsewhere / '.git'))
    monkeypatch.setenv('GIT_WORK_TREE', str(elsewhere))
    result = observer.inspect_place(place(root), tmp_path / 'cache')
    assert result['locations'][0]['git']['branch'] == 'main'
    assert result['locations'][0]['git']['root'] == str(root.resolve())


def test_missing_remote_and_nested_paths_are_not_confused(tmp_path):
    root = repository(tmp_path); nested = root / 'apps' / 'client'; nested.mkdir(parents=True)
    entity = place(root, nested, tmp_path / 'missing')
    entity['locations'].append(dict(path=str(root), host='unreachable-fixture-host'))
    result = observer.inspect_place(entity, tmp_path / 'cache')
    assert result['locations'][2]['availability'] == 'missing'
    assert result['locations'][3]['availability'] == 'unobserved'
    assert result['locations'][3]['git'] is None
    assert result['relationships'][0]['kind'] == 'same_checkout'
    assert result['locations'][1]['path'] == str(nested)


def test_location_identity_change_invalidates_cache_and_bounds_are_visible(tmp_path, monkeypatch):
    root = repository(tmp_path); cache = tmp_path / 'cache'
    observer.inspect_place(place(root), cache)
    changed = observer.inspect_place(place(root, tmp_path / 'missing'), cache)
    assert not changed['cached'] and changed['coverage']['observed'] == 2
    monkeypatch.setattr(observer, 'MAX_LOCATIONS', 1)
    bounded = observer.inspect_place(place(root, tmp_path / 'missing'), cache, refresh=True)
    assert bounded['coverage'] == dict(recorded=2, observed=1, omitted=1)
    assert bounded['gaps']


def test_cli_and_web_use_same_physical_dossier_without_opening_index(tmp_path, monkeypatch):
    root = repository(tmp_path); entity = place(root); entity['parent_id'] = 'galaxy:owner'
    galaxy = dict(place(), id='galaxy:owner', kind='galaxy', label='Your galaxy', parent_id=None)
    cache = tmp_path / 'space.json'
    cache.write_text(json.dumps(dict(schema_version=1, published=1, entities=[galaxy, entity], edges=[], coverage={})))
    monkeypatch.setenv('NAVCOM_SPACE_CACHE', str(cache))
    index = tmp_path / 'absent-index'
    argv = [sys.executable, str(Path(navcom.__file__)), 'atlas', 'inspect', entity['id'],
            '--space-cache', str(cache), '--index', str(index), '--json']
    cli = subprocess.run(argv, capture_output=True, text=True, env=dict(os.environ, NAVCOM_NO_SKILLS='1'))
    assert cli.returncode == 0, cli.stderr
    direct = json.loads(cli.stdout)
    web = WebApp(navcom, index).get(None, '/api/space/inspect', {'within': [entity['id']]})
    assert web['inspection'] == dict(direct['inspection'], cached=True)
    assert web['inspection']['locations'][0]['git']['branch'] == 'main'
    assert not index.exists()


def test_unborn_and_detached_are_explicit(tmp_path):
    root = repository(tmp_path)
    git(root, 'checkout', '--detach')
    detached = observer.inspect_place(place(root), tmp_path / 'cache')
    assert detached['locations'][0]['git']['head_state'] == 'detached'
    empty = tmp_path / 'empty'; empty.mkdir(); git(empty, 'init', '-b', 'beginning')
    unborn = observer.inspect_place(place(empty), tmp_path / 'cache')
    assert unborn['locations'][0]['git']['head_state'] == 'unborn'
    assert unborn['locations'][0]['git']['commit'] is None
