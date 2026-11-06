"""Bare native slash commands remain searchable, with Claude-only reparsing."""
import json

import pytest


def event(text, role="user"):
    return dict(timestamp="2025-01-02T03:04:05Z", message=dict(role=role, content=text))


@pytest.mark.parametrize("text,expected", [
    ("<command-name>/solve2</command-name>", "/solve2"),
    ("<command-name>/review</command-name><command-args></command-args>", "/review"),
    ("<command-name> /plugin:review </command-name><command-args> \n </command-args>", "/plugin:review"),
    ("<command-name>/goal</command-name><command-args> ship it\nwith tests </command-args>", "/goal ship it\nwith tests"),
    ("<command-name>/review</command-name><command-args>", "/review"),
    ("<command-name> </command-name><command-args>orphan args</command-args>", None),
    ("<command-name></command-name>", None),
    ("<command-name>/unfinished", None),
    ("<command-args>no name</command-args>", None),
])
def test_native_command_name_and_optional_args(navcom, text, expected):
    assert navcom._rescue_slash_command(text) == expected


def test_cleaned_bare_command_keeps_native_date_and_assistant_quotes(navcom):
    quote = "The provider emits <command-name>/review</command-name><command-args></command-args>."
    text = "\n".join(json.dumps(row) for row in [
        event("<command-name>/review</command-name><command-args>  </command-args>"),
        event(quote, "assistant"),
        event("<command-name> </command-name><command-args>discard malformed name</command-args>"),
    ])
    turns = list(navcom.iter_clean_turns("fixture.jsonl", "claude", text))
    assert turns == [("user", "/review"), ("assistant", quote)]
    assert [turn.timestamp for turn in turns] == ["2025-01-02T03:04:05Z"] * 2


def test_codex_question_quoting_native_command_remains_exact_prose(navcom):
    text = "Why does <command-name>/review</command-name> disappear from my search?"
    raw = json.dumps(dict(type="response_item", timestamp="2025-01-02T03:04:05Z",
        payload=dict(type="message", role="user", content=[dict(type="input_text", text=text)])))
    turns = list(navcom.iter_clean_turns("fixture.jsonl", "codex", raw))
    assert turns == [("user", text)]
    assert turns[0].timestamp == "2025-01-02T03:04:05Z"


def test_unchanged_claude_upgrades_without_reparsing_current_codex(navcom, tmp_path, monkeypatch):
    monkeypatch.setattr(navcom, "INDEX_READ_ONLY", False)
    claude = tmp_path / "claude.jsonl"
    claude.write_text("\n".join(json.dumps(row) for row in [
        event("<command-name>/solve2</command-name><command-args></command-args>"),
        event("The operation finished.", "assistant"),
    ]) + "\n")
    codex = tmp_path / "codex.jsonl"
    codex.write_text(json.dumps(dict(type="response_item", timestamp="2025-01-02T03:04:05Z",
        payload=dict(type="message", role="user", content=[dict(type="input_text", text="codex stays intact")]))) + "\n")
    logs = [(str(path), path.stat().st_mtime, path.stat().st_size, provider)
            for path, provider in [(claude, "claude"), (codex, "codex")]]
    conn = navcom.open_index(tmp_path / "index.sqlite")

    def old_rescue(text):
        name = navcom._SLASH_COMMAND_RE.search(text)
        args = navcom._SLASH_ARGS_RE.search(text)
        if not name or not args or not args.group(1).strip():
            return None
        return name.group(1).strip() + " " + args.group(1).strip()

    with monkeypatch.context() as old:
        old.setattr(navcom, "PARSER_PROVIDER_VERSIONS", {})
        old.setattr(navcom, "_rescue_slash_command", old_rescue)
        navcom.index_logs(conn, logs, progress=False)
    assert dict(conn.execute("SELECT file,ver FROM file_parser")) == {str(claude): 4, str(codex): 4}
    assert conn.execute("SELECT count(*) FROM session_fts WHERE session_fts MATCH 'solve2'").fetchone()[0] == 0
    codex_before = conn.execute("SELECT rowid,text,ts FROM session_fts WHERE file=?", (str(codex),)).fetchall()
    original = navcom.index_log
    reparsed = []

    def observe(connection, log, **kwargs):
        reparsed.append((log[0], kwargs.get("force")))
        return original(connection, log, **kwargs)

    monkeypatch.setattr(navcom, "index_log", observe)
    navcom.index_logs(conn, logs, progress=False)
    assert reparsed == [(str(claude), True)]
    assert dict(conn.execute("SELECT file,ver FROM file_parser")) == {str(claude): 5, str(codex): 4}
    assert conn.execute("SELECT rowid,text,ts FROM session_fts WHERE file=?", (str(codex),)).fetchall() == codex_before
    hits, _, _ = navcom.search_hits(conn, "solve2", include_self=True)
    assert len(hits) == 1 and hits[0].role == "user" and hits[0].msg_index == 1
    assert hits[0].text == "/solve2" and hits[0].ts == "2025-01-02T03:04:05Z"
    reparsed.clear()
    navcom.index_logs(conn, logs, progress=False)
    assert reparsed == []
    conn.close()


def test_appended_old_claude_reparses_earlier_bare_command(navcom, tmp_path, monkeypatch):
    monkeypatch.setattr(navcom, "INDEX_READ_ONLY", False)
    path = tmp_path / "claude.jsonl"
    path.write_text(json.dumps(event("<command-name>/review</command-name>")) + "\n")
    old_time = path.stat().st_mtime
    conn = navcom.open_index(tmp_path / "index.sqlite")
    with monkeypatch.context() as old:
        old.setattr(navcom, "PARSER_PROVIDER_VERSIONS", {})
        old.setattr(navcom, "_rescue_slash_command", lambda text: None)
        navcom.index_log(conn, (str(path), old_time, path.stat().st_size, "claude"))
    conn.commit()
    with path.open("a") as stream:
        stream.write(json.dumps(event("Follow-up", "assistant")) + "\n")
    navcom.index_log(conn, (str(path), old_time + 1, path.stat().st_size, "claude"))
    assert conn.execute("SELECT role,text FROM session_fts ORDER BY msg_index").fetchall() == [
        ("user", "/review"), ("assistant", "Follow-up")]
    assert conn.execute("SELECT ver FROM file_parser").fetchone()[0] == 5
    conn.close()


@pytest.mark.parametrize("query", ["solve2", "/solve2", "solve"])
def test_repeated_command_search_preserves_distinct_sessions(navcom, tmp_path, monkeypatch, query):
    monkeypatch.setattr(navcom, "INDEX_READ_ONLY", False)
    first, second = tmp_path / "first.jsonl", tmp_path / "second.jsonl"
    command = "<command-name>/solve2</command-name>"
    first.write_text("\n".join(json.dumps(row) for row in [
        event(command), event("First attempt finished.", "assistant"), event(command),
    ]) + "\n")
    second.write_text(json.dumps(event(command)) + "\n")
    conn = navcom.open_index(tmp_path / "index.sqlite")
    try:
        logs = [(str(path), path.stat().st_mtime, path.stat().st_size, "claude")
                for path in (first, second)]
        navcom.index_logs(conn, logs, progress=False)
        assert conn.execute("SELECT count(*) FROM session_fts WHERE session_fts MATCH 'solve2'").fetchone()[0] == 3

        hits, _, _ = navcom.search_hits(conn, query, providers=["claude"], include_self=True, limit=20)
        assert len(hits) == 2
        assert {hit.file for hit in hits} == {str(first), str(second)}
        assert all(hit.role == "user" and hit.text == "/solve2" for hit in hits)

        # Repeated identical turns in one session still make only one search hit.
        local, _, _ = navcom.search_hits(conn, query, keys=[str(first)], include_self=True, limit=20)
        assert len(local) == 1 and local[0].file == str(first)
        assert conn.execute("SELECT count(*) FROM session_fts WHERE session_fts MATCH 'solve2'").fetchone()[0] == 3
    finally:
        conn.close()
