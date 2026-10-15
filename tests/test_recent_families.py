"""Recents is a persistent, searchable conversation tree, not a flat transcript list."""
import json
from pathlib import Path

import pytest


@pytest.fixture
def family(navcom, tmp_path):
    conn = navcom.open_index(tmp_path / 'index.sqlite')
    logs, keys = [], []
    ids = ['01a126c8-331b-7aa2-8783-d9ff30c38f32', '01a1320b-bf55-73f1-adb1-c82ca8f1ab69',
           '01a1320b-bf55-73f1-adb1-c82ca8f1ab70', '01a1320b-bf55-73f1-adb1-c82ca8f1ab71']
    for i, sid in enumerate(ids):
        key = tmp_path / f'rollout-2026-10-12T16-36-33-{sid}.jsonl'
        meta = dict(id=sid, cwd=str(tmp_path))
        if i in (1, 2): meta.update(parent_thread_id=ids[i - 1], agent_nickname=f'Agent {i}')
        records = [dict(type='session_meta', payload=meta)]
        for role, text in [('user', f'Work on project number {i}'),
                           ('assistant', 'Found zebracornneedle in code' if i == 2 else f'Finished part {i}')]:
            records.append(dict(type='response_item', payload=dict(type='message', role=role,
                           content=[dict(type='input_text' if role == 'user' else 'output_text', text=text)])))
        key.write_text('\n'.join(json.dumps(r) for r in records) + '\n')
        keys.append(str(key))
        logs.append((str(key), i + 1, key.stat().st_size, 'codex'))
    navcom.index_logs(conn, logs, progress=False)
    yield conn, keys, logs
    conn.close()


def test_whole_families_include_nested_children_and_old_parent(navcom, family):
    conn, keys, logs = family
    # Parent isn't in live discovery, but remains indexed.
    nodes, roots = navcom._recent_families(conn, logs[1:], {}, limit=2)
    assert set(roots) == {keys[0], keys[3]}
    assert nodes[keys[1]]['parent'] == keys[0]
    assert nodes[keys[2]]['parent'] == keys[1]
    collapsed = navcom._recent_tree(nodes, roots, {}, set(), set(nodes))
    assert all(depth == 0 for _, depth in collapsed)
    tree = navcom._recent_tree(nodes, roots, {}, {keys[0], keys[1]}, set(nodes))
    offset = tree.index((keys[0], 0))
    assert tree[offset:offset+3] == [(keys[0], 0), (keys[1], 1), (keys[2], 2)]


def test_recent_search_finds_transcript_and_reveals_ancestry(navcom, family):
    conn, keys, logs = family
    nodes, roots = navcom._recent_families(conn, logs, {})
    focus, matches = navcom._recent_matches(conn, nodes, {}, 'zebracornneedle')
    assert set(focus) == matches == {keys[2]}
    tree = navcom._recent_tree(nodes, roots, {}, set(), matches, 'zebracornneedle')
    assert tree == [(keys[0], 0), (keys[1], 1), (keys[2], 2)]
    for query in ('10.10.1.223', '"', 'a OR b', 'NOT', "don't", 'PR #76'):
        navcom._recent_matches(conn, nodes, {}, query)


def test_renames_notes_favorites_and_state_persist(navcom, family):
    conn, keys, logs = family
    annotations = {keys[2]: {'name': 'My favorite detective', 'note': 'Next: deploy the fix', 'favorite': True}}
    assert navcom._ui_write(conn, 'annotations', annotations)
    assert navcom._ui_read(conn, 'annotations') == annotations
    nodes, roots = navcom._recent_families(conn, logs, annotations, limit=1)
    assert keys[0] in roots  # Older starred family survives the Recents limit.
    for query in ('favorite detective', 'deploy the fix'):
        _, matches = navcom._recent_matches(conn, nodes, annotations, query)
        assert keys[2] in matches
    tree = navcom._recent_tree(nodes, roots, annotations, set(), set(nodes), favorites=True)
    assert tree == [(keys[0], 0), (keys[1], 1), (keys[2], 2)]
    state = dict(selected=keys[2], top=2, query='detective', expanded=[keys[0]], favorites=True)
    assert navcom._ui_write(conn, 'recents', state)
    path = conn.execute('PRAGMA database_list').fetchone()[2]
    other = navcom.open_index(Path(path))
    assert navcom._ui_read(other, 'recents') == state
    other.close()


def test_orphan_and_cycle_are_displayable_without_inventing_parent(navcom, family):
    conn, keys, logs = family
    path = Path(keys[0])
    records = path.read_text().splitlines()
    obj = json.loads(records[0]); obj['payload']['parent_thread_id'] = navcom.session_ref(keys[2])
    records[0] = json.dumps(obj); path.write_text('\n'.join(records) + '\n')
    nodes, roots = navcom._recent_families(conn, logs, {})
    assert len(navcom._recent_tree(nodes, roots, {}, set(nodes), set(nodes))) == 4
    path.unlink()
    conn.execute('DELETE FROM file_state WHERE file=?', (keys[0],))
    nodes, roots = navcom._recent_families(conn, logs[1:], {})
    assert keys[1] in roots and nodes[keys[1]]['parent'] is None


class Term:
    def __init__(self, keys, prompts=()):
        self.keys = iter(keys); self.prompts = iter(prompts); self.frames = []
    def size(self): return 110, 34
    def draw(self, rows): self.frames.append('\n'.join(rows))
    def key(self): return next(self.keys)
    def prompt(self, *args): return next(self.prompts)


def test_recents_search_edit_and_restore_journey(navcom, family, monkeypatch):
    conn, keys, logs = family
    monkeypatch.setattr(navcom, 'list_logs', lambda _: logs)
    term = Term(['/', 'down', 'down', 'e', 'd', 'f', 'x', 'v', 'q'],
                ['zebracornneedle', 'Detective', 'Ready for review'])
    navcom._menu_recent(term, conn)
    a = navcom._ui_read(conn, 'annotations')[keys[2]]
    assert a == dict(name='Detective', note='Ready for review', favorite=True)
    saved = navcom._ui_read(conn, 'recents')
    assert saved['selected'] == keys[2] and saved['favorites']
    term = Term(['q'])
    navcom._menu_recent(term, conn)
    frame = term.frames[-1]
    assert 'Detective' in frame and 'Ready for review' in frame and 'Open parent conversation' in frame
    assert navcom._ui_read(conn, 'recents')['selected'] == keys[2]


def test_search_open_passes_matching_turn(navcom, family, monkeypatch):
    conn, keys, logs = family
    monkeypatch.setattr(navcom, 'list_logs', lambda _: logs)
    opened = []
    monkeypatch.setattr(navcom, '_menu_view', lambda *args: opened.append(args))
    navcom._menu_recent(Term(['/', 'down', 'down', 'enter', 'q'], ['zebracornneedle']), conn)
    assert opened[0][2] == keys[2] and opened[0][4] is not None


@pytest.mark.parametrize('action', ['r', 't', 'n'])
def test_family_launch_actions_keep_selected_child_and_parent_plan(navcom, family, monkeypatch, action):
    conn, keys, logs = family
    monkeypatch.setattr(navcom, 'list_logs', lambda _: logs)
    actions = []
    monkeypatch.setattr(navcom, '_resume_action', lambda *args: actions.append(args) or 'preview')
    navcom._menu_recent(Term(['/', 'down', 'down', action, 'q'], ['zebracornneedle']), conn)
    assert actions[0][1]['key'] == keys[0]
    assert actions[0][4] == keys[2]  # Fresh context retains the selected child as well.
    assert actions[0][2] == action


def test_reading_position_and_name_survive_reopen(navcom, family, monkeypatch):
    conn, keys, _ = family
    navcom._ui_write(conn, 'annotations', {keys[0]: {'name': 'Recognizable title'}})
    monkeypatch.setattr(navcom, '_turn_rows', lambda *args, **kwargs: [navcom._line([(str(i), 'cream', None)], 110) for i in range(50)])
    term = Term(['down', 'down', 'q'])
    navcom._menu_view(term, conn, keys[0], 'codex')
    assert navcom._ui_read(conn, 'view:' + keys[0] + ':None')['scroll'] == 2
    term = Term(['q'])
    navcom._menu_view(term, conn, keys[0], 'codex')
    assert 'Recognizable title' in term.frames[-1]
    assert navcom._ui_read(conn, 'view:' + keys[0] + ':None')['scroll'] == 2


def test_busy_work_animates_and_cleans_up_after_error(navcom):
    import time, threading
    term = Term([])
    with pytest.raises(ValueError):
        with navcom._menu_busy(term, 'Working'):
            time.sleep(.32)
            raise ValueError('expected')
    assert len(term.frames) >= 2
    assert not any(t.name == 'navcom-ui-progress' for t in threading.enumerate())


def test_favorite_survives_disappearance_from_live_discovery(navcom, family):
    conn, keys, logs = family
    annotations = {keys[0]: {'favorite': True}}
    nodes, roots = navcom._recent_families(conn, [logs[3]], annotations, limit=1)
    assert keys[0] in nodes and keys[0] in roots


def test_parent_match_keeps_nonmatching_children_and_h_really_collapses(navcom, family):
    conn, keys, logs = family
    nodes, roots = navcom._recent_families(conn, logs, {})
    matches = {keys[0]}
    opened = navcom._recent_tree(nodes, roots, {}, set(), matches, 'parent-only-query')
    assert opened == [(keys[0], 0), (keys[1], 1)]
    closed = navcom._recent_tree(nodes, roots, {}, set(), matches, 'parent-only-query', collapsed={keys[0]})
    assert closed == [(keys[0], 0)]
    reopened = navcom._recent_tree(nodes, roots, {}, {keys[0], keys[1]}, matches, 'parent-only-query')
    assert reopened == [(keys[0], 0), (keys[1], 1), (keys[2], 2)]


def test_search_h_toggle_frames_and_persistence(navcom, family, monkeypatch):
    conn, keys, logs = family
    monkeypatch.setattr(navcom, 'list_logs', lambda _: logs)
    term = Term(['/', 'h', 'h', 'h', 'esc'], ['zebracornneedle'])
    navcom._menu_recent(term, conn)
    frames = [f for f in term.frames if 'RECENT CONVERSATIONS' in f]
    assert '↳ CHILD' in frames[1]
    assert '↳ CHILD' not in frames[2]
    assert '↳ CHILD' in frames[3]
    assert '↳ CHILD' not in frames[4]
    term = Term(['esc'])
    navcom._menu_recent(term, conn)
    assert '↳ CHILD' not in term.frames[-1]


def test_global_search_labels_and_hides_children_then_escapes(navcom, family):
    conn, keys, _ = family
    term = Term(['h', 'h', 'esc'])
    navcom._menu_search(term, conn, 'zebracornneedle')
    frames = [f for f in term.frames if 'SEARCH ▸' in f]
    assert '↳ CHILD' in frames[0]
    assert '↳ CHILD' not in frames[1]
    assert '↳ CHILD' in frames[2]


@pytest.mark.parametrize('route', ['recent', 'search'])
def test_escape_from_search_and_repeated_escape_keeps_dashboard_open(navcom, family, monkeypatch, route):
    conn, keys, logs = family
    monkeypatch.setattr(navcom, 'list_logs', lambda _: logs)
    # Use the actual menu navigation; only startup and the terminal surface are replaced.
    monkeypatch.setattr(navcom.sys.stdin, 'isatty', lambda: True)
    monkeypatch.setattr(navcom.sys.stdout, 'isatty', lambda: True)
    monkeypatch.setattr(navcom, '_load_menu_dashboard', lambda *args, **kwargs: (conn, {}))
    monkeypatch.setattr(navcom, 'dashboard_frame', lambda *args: ['DASHBOARD'])
    keys_in = ['down', 'enter', '/', 'esc', 'esc', 'q'] if route == 'recent' else ['/', 'esc', 'esc', 'q']
    class MenuTerm(Term):
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def key(self, timeout=None): return next(self.keys)
    term = MenuTerm(keys_in, ['zebracornneedle'])
    monkeypatch.setattr(navcom, '_Term', lambda: term)
    navcom._run_menu(conn)
    assert term.frames[-1] == 'DASHBOARD'
    assert list(term.keys) == []  # q, not the extra Escape, ended the app.
