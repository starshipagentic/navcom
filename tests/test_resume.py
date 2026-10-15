"""Resume: the TUI's RESUME line, the r/t/c keys, the new-tab launchers, and the index repair."""
import re
import stat

import pytest

ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def plan_for(tmp_path, gone=False, archived=False):
    return {"cwd": str(tmp_path), "argv": ["codex", "resume", "019f49ce-2b07-79d2-ae8d-991aabb1fef1"],
            "line": f"cd {tmp_path} && codex resume 019f49ce-2b07-79d2-ae8d-991aabb1fef1", "exact": True, "note": "",
            "provider": "codex", "key": str(tmp_path / "rollout-x-019f49ce-2b07-79d2-ae8d-991aabb1fef1.jsonl"),
            "gone": gone, "archived": archived}


def test_resume_line_keeps_screens_exact_width(navcom, tmp_path):
    for width in (80, 140):
        rows = navcom._screen("T", [], width, 30, "keys", "navcom x",
                              resume=navcom._resume_span(plan_for(tmp_path)))
        assert len(rows) == 30 and all(len(ANSI.sub("", r)) == width for r in rows)
        assert any("RESUME ▸ cd " in ANSI.sub("", r) for r in rows)


def test_resume_span_offers_a_fresh_agent_when_it_cannot_reopen(navcom, tmp_path):
    assert "fresh agent" in navcom._resume_span(plan_for(tmp_path, gone=True))[0][0]
    assert "navcom --resume" in navcom._resume_span(plan_for(tmp_path, gone=True, archived=True))[0][0]
    assert "can't reopen it" in navcom._resume_span(None)[0][0]


def test_copy_key_copies_the_command(navcom, tmp_path, monkeypatch):
    copied = []
    monkeypatch.setattr(navcom, "copy_to_clipboard", lambda text: copied.append(text) or True)
    msg = navcom._resume_action(None, plan_for(tmp_path), "c")
    assert msg.startswith("✓ copied") and copied == [plan_for(tmp_path)["line"]]


def test_resume_key_leaves_the_tui(navcom, tmp_path, monkeypatch):
    monkeypatch.setattr(navcom.shutil, "which", lambda exe: "/usr/bin/" + exe)
    with pytest.raises(navcom._ResumeNow) as caught:
        navcom._resume_action(None, plan_for(tmp_path), "r")
    assert caught.value.plan["argv"][0] == "codex"


def _recorder(tmp_path, name):
    log = tmp_path / f"{name}.args"
    exe = tmp_path / "bin" / name
    exe.parent.mkdir(exist_ok=True)
    exe.write_text(f'#!/bin/sh\nfor a in "$@"; do printf "%s\\n" "$a"; done > {log}\n')
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    return exe, log


@pytest.mark.parametrize("terminal", ["cmux", "tmux", "wezterm", "kitty"])
def test_new_tab_uses_the_terminal_you_are_in(navcom, tmp_path, monkeypatch, terminal):
    for var in ("CMUX_WORKSPACE_ID", "CMUX_SOCKET_PATH", "CMUX_BUNDLED_CLI_PATH", "TMUX", "WEZTERM_PANE",
                "KITTY_WINDOW_ID", "TERM_PROGRAM"):
        monkeypatch.delenv(var, raising=False)
    exe, log = _recorder(tmp_path, terminal)
    monkeypatch.setenv("PATH", f"{exe.parent}:/usr/bin:/bin")
    monkeypatch.setenv({"cmux": "CMUX_WORKSPACE_ID", "tmux": "TMUX", "wezterm": "WEZTERM_PANE",
                        "kitty": "KITTY_WINDOW_ID"}[terminal], "1")
    ok, message = navcom.resume_in_new_tab(plan_for(tmp_path))
    assert ok, message
    args = log.read_text().splitlines()
    assert str(tmp_path) in args  # opened in the session's folder
    assert any("codex resume 019f49ce" in a for a in args)


def test_new_tab_falls_back_to_copying(navcom, tmp_path, monkeypatch):
    for var in ("CMUX_WORKSPACE_ID", "CMUX_SOCKET_PATH", "CMUX_BUNDLED_CLI_PATH", "TMUX", "WEZTERM_PANE",
                "KITTY_WINDOW_ID"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("TERM_PROGRAM", "some-terminal")
    monkeypatch.setattr(navcom, "copy_to_clipboard", lambda text: True)
    ok, message = navcom.resume_in_new_tab(plan_for(tmp_path))
    assert not ok and "copied" in message


def test_index_repair_unwraps_gemini_part_reprs(navcom, tmp_path):
    conn = navcom.open_index(tmp_path / "idx.sqlite")
    rows = ["{'text': 'Drizzle ORM migration\\nsecond line'}", "[{'text': 'a'}, {'text': 'b'}]",
            "{'text': 'capped repr with no closing quote", "{'text': 1}  not a parts repr"]
    for i, text in enumerate(rows):
        conn.execute("INSERT INTO session_fts (file, provider, role, msg_index, text) VALUES (?,?,?,?,?)",
                     ("k", "gemini", "user", i, text))
    navcom._repair_part_reprs(conn)
    got = [t for (t,) in conn.execute("SELECT text FROM session_fts ORDER BY rowid")]
    assert got[:3] == ["Drizzle ORM migration\nsecond line", "a\nb", "capped repr with no closing quote"]
    assert got[3] == rows[3]



@pytest.fixture
def indexed(navcom, tmp_path, monkeypatch):
    import fake_home
    from pathlib import Path
    home = tmp_path / "home"
    fake_home.build(home)
    for k, v in fake_home.env_for(home).items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    conn = navcom.open_index(tmp_path / "idx.sqlite")
    navcom.index_logs(conn, navcom.list_logs(navcom.ALL_PROVIDERS), progress=False)
    return conn


def _codex_key(conn):
    return next(f for (f,) in conn.execute("SELECT file FROM file_state") if "rollout-" in f)


def test_recap_is_a_compact_context_pack(navcom, indexed):
    key = _codex_key(indexed)
    text = navcom.session_recap(indexed, key)
    for section in ("navcom --recap · codex", "reopen it: cd ", "## What the user asked", "## Where it stopped",
                    "## Commands run", "## Dig deeper", "navcom --open "):
        assert section in text, section
    assert len(navcom.session_recap(indexed, key, budget=2000)) < 6000


def test_revive_starts_a_fresh_agent_primed_with_the_recap(navcom, indexed, tmp_path, monkeypatch):
    key = _codex_key(indexed)
    plan = navcom.revive_plan(indexed, key, "claude", "codex", focus=4)
    assert plan["argv"][0] == "claude" and plan["line"].startswith("cd ")
    prompt = plan["argv"][1]
    assert "navcom --recap " in prompt and ":4`" in prompt and "'" not in prompt
    for harness in navcom.FRESH_START:  # every primed start puts the prompt on its command line
        assert navcom.revive_plan(indexed, key, harness, "codex", focus=4)["argv"][-1] == prompt


def test_copy_on_a_dead_session_copies_the_revive_line(navcom, indexed, monkeypatch):
    copied = []
    monkeypatch.setattr(navcom, "copy_to_clipboard", lambda text: copied.append(text) or True)
    monkeypatch.setattr(navcom, "fresh_harnesses", lambda original=None: ["claude"])
    key = _codex_key(indexed)
    navcom._resume_action(indexed, None, "c", key=key, provider="codex")
    assert "claude " in copied[-1] and "navcom --recap" in copied[-1]


def test_every_harness_can_be_revived(navcom, indexed):
    key = _codex_key(indexed)
    assert set(navcom.REVIVE_AGENTS) >= set(navcom.ALL_PROVIDERS) - {"opencode-legacy", "goose-legacy", "gemini-jsonl"}
    for harness in navcom.REVIVE_AGENTS:
        plan = navcom.revive_plan(indexed, key, harness, "codex")
        text = navcom.revive_text(plan)
        assert "navcom --recap " in text, harness
        assert bool(plan["paste"]) == (harness not in navcom.FRESH_START), harness


def test_paste_agents_get_the_prompt_on_the_clipboard_when_started(navcom, indexed, monkeypatch, capsys):
    copied = []
    monkeypatch.setattr(navcom, "copy_to_clipboard", lambda text: copied.append(text) or True)
    monkeypatch.setattr(navcom.shutil, "which", lambda exe: "/usr/bin/" + exe)
    monkeypatch.setattr(navcom.os, "execvp", lambda exe, argv: None)
    monkeypatch.setattr(navcom.os, "chdir", lambda path: None)
    plan = navcom.revive_plan(indexed, _codex_key(indexed), "kimi", "codex")
    navcom.resume_here(plan)
    assert copied == [plan["paste"]] and "paste it once it starts" in capsys.readouterr().err

@pytest.fixture
def agent_family(navcom, tmp_path):
    import json
    conn = navcom.open_index(tmp_path / 'family.sqlite')
    keys = []
    ids = ['01a126c8-331b-7aa2-8783-d9ff30c38f32',
           '01a1320b-bf55-73f1-adb1-c82ca8f1ab69',
           '01a1320b-bf55-73f1-adb1-c82ca8f1ab70']
    for i, sid in enumerate(ids):
        path = tmp_path / 'sessions' / f'rollout-2026-10-12T16-36-33-{sid}.jsonl'
        path.parent.mkdir(exist_ok=True)
        meta = {'id': sid, 'session_id': ids[0], 'cwd': str(tmp_path if i == 0 else path.parent)}
        if i:
            meta.update(source={'subagent': {'thread_spawn': {'parent_thread_id': ids[i-1]}}},
                        agent_nickname='Galileo')
        path.write_text(json.dumps({'type': 'session_meta', 'payload': meta}) + '\n' +
                        json.dumps({'type': 'response_item', 'payload': {'type': 'message', 'role': 'user',
                                   'content': [{'type': 'input_text', 'text': f'conversation {i}'}]}}) + '\n')
        keys.append(str(path))
    logs = [(key, i + 1, __import__('os').path.getsize(key), 'codex') for i, key in enumerate(keys)]
    navcom.index_logs(conn, logs, progress=False)
    return conn, keys, ids, logs


def test_nested_child_resumes_root_with_root_cwd(navcom, agent_family, tmp_path):
    conn, keys, ids, _ = agent_family
    for key in keys:
        plan = navcom.resume_plan(conn, key, 'codex')
        assert plan['argv'] == ['codex', 'resume', ids[0]]
        assert plan['cwd'] == str(tmp_path)
        assert plan['key'] == keys[0]
        assert bool(plan['note']) == (key != keys[0])


def test_child_r_and_t_use_same_parent(navcom, agent_family, monkeypatch):
    conn, keys, ids, _ = agent_family
    plan = navcom.resume_plan(conn, keys[-1], 'codex')
    monkeypatch.setattr(navcom.shutil, 'which', lambda exe: '/usr/bin/' + exe)
    with pytest.raises(navcom._ResumeNow) as caught:
        navcom._resume_action(conn, plan, 'r')
    launched = []
    monkeypatch.setattr(navcom, 'resume_in_new_tab', lambda p: (launched.append(p) or True, 'opened'))
    navcom._resume_action(conn, plan, 't')
    assert launched == [caught.value.plan]
    assert launched[0]['argv'][-1] == ids[0]


def test_fresh_harness_loads_parent_and_selected_child(navcom, agent_family, tmp_path):
    conn, keys, ids, _ = agent_family
    for harness in navcom.REVIVE_AGENTS:
        plan = navcom.revive_plan(conn, keys[-1], harness, 'codex', focus=4)
        prompt = plan['paste'] or plan['argv'][-1]
        assert f'navcom --recap {navcom.short_ref(keys[0])}' in prompt
        assert f'navcom --recap {navcom.short_ref(keys[-1])}' in prompt
        assert f'navcom --open {navcom.short_ref(keys[-1])}:4' in prompt
        assert plan['cwd'] == str(tmp_path)


def test_missing_parent_never_launches_child(navcom, agent_family):
    conn, keys, _, _ = agent_family
    from pathlib import Path
    Path(keys[0]).unlink()
    conn.execute('DELETE FROM file_state WHERE file=?', (keys[0],))
    plan = navcom.resume_plan(conn, keys[1], 'codex')
    assert plan['blocked'] and not plan['argv']
    assert not navcom.ensure_resumable(conn, plan)[0]
    assert 'parent' in navcom._resume_span(plan)[0][0]
    assert 'navcom --recap' in navcom.revive_plan(conn, keys[1], 'codex', 'codex')['argv'][-1]


def test_cycle_never_launches_child(navcom, agent_family):
    import json
    from pathlib import Path
    conn, keys, ids, _ = agent_family
    path = Path(keys[0])
    lines = path.read_text().splitlines()
    meta = json.loads(lines[0])
    meta['payload']['parent_thread_id'] = ids[-1]
    path.write_text(json.dumps(meta) + '\n' + '\n'.join(lines[1:]) + '\n')
    plan = navcom.resume_plan(conn, keys[-1], 'codex')
    assert plan['blocked'] and 'cyclic' in plan['note']


def test_recents_filters_before_limit_and_labels_children(navcom, agent_family):
    conn, keys, _, logs = agent_family
    parents, combined = navcom._recent_entries(conn, logs, limit=2)
    assert [payload[0] for _, payload in parents] == [keys[0]]
    assert any('Galileo' in str(spans) and 'parent' in str(spans) for spans, _ in combined)


def test_recents_h_toggle_and_launch(navcom, agent_family, monkeypatch):
    conn, keys, ids, logs = agent_family
    parents, combined = navcom._recent_entries(conn, logs)
    class Term:
        inputs = iter(['h', 'up', 'r'])
        frames = []
        def size(self): return 140, 30
        def draw(self, frame): self.frames.append('\n'.join(frame))
        def key(self): return next(self.inputs)
    term = Term()
    monkeypatch.setattr(navcom.shutil, 'which', lambda exe: '/usr/bin/' + exe)
    with pytest.raises(navcom._ResumeNow) as caught:
        navcom._menu_list(term, conn, 'RECENT', parents, '', on_enter=lambda item: None,
                          resumable=True, alternate_entries=combined)
    assert 'parents only' in term.frames[0] and 'parents + children' in term.frames[1]
    assert caught.value.plan['argv'][-1] == ids[0]

@pytest.mark.parametrize('launch_key', ['enter', 't'])
def test_n_picker_launches_fresh_harness_with_family_context(navcom, agent_family, monkeypatch, launch_key):
    conn, keys, _, _ = agent_family
    monkeypatch.setattr(navcom, 'fresh_harnesses', lambda provider: ['claude'])
    monkeypatch.setattr(navcom.shutil, 'which', lambda exe: '/usr/bin/' + exe)
    launched = []
    monkeypatch.setattr(navcom, 'resume_in_new_tab', lambda plan: (launched.append(plan) or True, 'opened'))
    class Term:
        def size(self): return 140, 30
        def draw(self, frame): pass
        def key(self): return launch_key
    plan = navcom.resume_plan(conn, keys[-1], 'codex')
    if launch_key == 'enter':
        with pytest.raises(navcom._ResumeNow) as caught:
            navcom._resume_action(conn, plan, 'n', Term(), keys[-1], 'codex')
        launched.append(caught.value.plan)
    else:
        navcom._resume_action(conn, plan, 'n', Term(), keys[-1], 'codex')
    assert launched[0]['argv'][0] == 'claude'
    prompt = launched[0]['argv'][-1]
    for key in (keys[0], keys[-1]):
        assert f'navcom --recap {navcom.short_ref(key)}' in prompt


def test_archived_child_keeps_parent_routing(navcom, agent_family, tmp_path):
    from pathlib import Path
    conn, keys, ids, _ = agent_family
    navcom._ensure_archive_table(conn)
    # Preserve ancestry even when only the archived child transcript remains.
    path = Path(keys[-1])
    saved = tmp_path / 'saved-child.jsonl'
    saved.write_bytes(path.read_bytes())
    columns = {row[1] for row in conn.execute('PRAGMA table_info(archive_state)')}
    assert {'file', 'path'} <= columns
    conn.execute('INSERT INTO archive_state (file, path) VALUES (?, ?)', (keys[-1], str(saved)))
    path.unlink()
    assert navcom.resume_plan(conn, keys[-1], 'codex')['argv'][-1] == ids[0]


def test_children_are_marked_at_start_of_tui_and_printed_rows(navcom, agent_family, capsys):
    conn, keys, _, logs = agent_family
    parents, combined = navcom._recent_entries(conn, logs)
    assert parents[0][0][0][0] == '● '
    for spans, (key, _) in combined:
        text = ''.join(span[0] for span in spans)
        assert text.startswith('    ↳ CHILD  ' if key != keys[0] else '● ')
    navcom.cmd_recent_sessions(conn, logs, limit=80)
    rows = ANSI.sub('', capsys.readouterr().out).splitlines()[1:]
    assert rows[0].startswith('    ↳ CHILD  ')
    assert rows[1].startswith('    ↳ CHILD  ')
    assert rows[2].startswith('● ')
