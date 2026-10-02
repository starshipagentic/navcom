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


def test_resume_span_explains_sessions_that_cannot_reopen(navcom, tmp_path):
    assert "read-only" in navcom._resume_span(plan_for(tmp_path, gone=True))[0]
    assert "navcom --resume" in navcom._resume_span(plan_for(tmp_path, gone=True, archived=True))[0][0]
    assert "can't reopen" in navcom._resume_span(None)[0]


def test_copy_key_copies_the_command(navcom, tmp_path, monkeypatch):
    copied = []
    monkeypatch.setattr(navcom, "copy_to_clipboard", lambda text: copied.append(text) or True)
    msg = navcom._resume_action(None, plan_for(tmp_path), "c")
    assert msg.startswith("✓ copied") and copied == [plan_for(tmp_path)["line"]]
    navcom._resume_action(None, plan_for(tmp_path, gone=True), "c")
    assert copied[-1].startswith("navcom --open ")  # unrecoverable: reading it is what's left


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

