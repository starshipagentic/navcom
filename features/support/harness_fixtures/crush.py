"""Crush (charmbracelet, npm @charmland/crush / brew charmbracelet/tap/crush) transcripts for navcom.

Per-project SQLite at <project>/.crush/crush.db (or --data-dir / options.data_directory). Every project
Crush has opened is listed in <global data>/projects.json {projects: [{path, data_dir, last_accessed}]},
global data = $CRUSH_GLOBAL_DATA | $XDG_DATA_HOME/crush | ~/.local/share/crush (%LOCALAPPDATA%\\crush).
  sessions(id, parent_session_id, title, message_count, updated_at, created_at, …)
     parent_session_id set for Agent-tool child sessions (id = tool call id) and for
     "title-<parent>" title-generation sessions (skipped)
  messages(id, session_id, role user|assistant|tool, parts JSON, created_at, is_summary_message, …)
     parts: [{type: text{text, hidden?} | reasoning{thinking} | tool_call{id,name,input(JSON str)}
             | tool_result{tool_call_id,name,content,is_error} | shell_command{command,output,exit_code}
             | image_url | binary | finish, data: {…}}]
Injected context (todo reminders, system prompt) is added at request time and never stored.
"""
import importlib.util
import json
import os
import sqlite3
from pathlib import Path

spec = importlib.util.spec_from_file_location("nav", str(__import__("pathlib").Path(__file__).resolve().parents[3] / "navcom.py"))
nav = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nav)


def _global_data():
    explicit = nav._env_path("CRUSH_GLOBAL_DATA")
    if explicit:
        return explicit
    if os.environ.get("XDG_DATA_HOME"):
        return nav._xdg_data_home() / "crush"
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "crush"
    return Path.home() / ".local" / "share" / "crush"


def _projects():
    try:
        data = json.loads((_global_data() / "projects.json").read_text(encoding="utf-8"))
        return [p for p in data.get("projects") or [] if isinstance(p, dict)]
    except Exception:
        return []


def crush_roots():
    dbs = [Path(p["data_dir"]).expanduser() / "crush.db" for p in _projects() if p.get("data_dir")]
    dbs.append(_global_data() / ".crush" / "crush.db")  # `crush server` meta-workspace
    out = []
    for db in dbs:
        if db not in out:
            out.append(db)
    return out


def crush_list():
    logs = []
    for db in crush_roots():
        if not db.is_file():
            continue
        try:
            conn = nav._ro_connect(db)
            rows = conn.execute(
                "SELECT s.id, MAX(s.updated_at, COALESCE(MAX(m.updated_at), 0)), COUNT(m.id),"
                " COALESCE(SUM(LENGTH(m.parts)), 0) FROM sessions s LEFT JOIN messages m ON m.session_id = s.id"
                " WHERE s.id NOT LIKE 'title-%' GROUP BY s.id").fetchall()
            conn.close()
        except sqlite3.Error:
            continue
        for sid, updated, count, size in rows:
            if count:
                logs.append((f"{db}#{sid}", float(updated or 0), int(size), "crush"))
    return logs


def _split(key):
    db, _, sid = str(key).partition("#")
    return db, sid


def _session(key):
    db, sid = _split(key)
    try:
        conn = nav._ro_connect(db)
        row = conn.execute("SELECT parent_session_id, title FROM sessions WHERE id = ?", (sid,)).fetchone()
        conn.close()
        return row or (None, "")
    except sqlite3.Error:
        return (None, "")


def crush_iter(key):
    db, sid = _split(key)
    try:
        conn = nav._ro_connect(db)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(messages)")}
        summary = "is_summary_message" if "is_summary_message" in cols else "0"  # older Crush schemas
        rows = conn.execute(f"SELECT role, parts, {summary} FROM messages WHERE session_id = ?"
                            " ORDER BY created_at, rowid", (sid,)).fetchall()
        is_child = bool(conn.execute("SELECT parent_session_id FROM sessions WHERE id = ?", (sid,)).fetchone()[0])
        conn.close()
    except (sqlite3.Error, TypeError):
        return
    calls = {}
    for role, raw, is_summary in rows:
        if is_summary:
            continue  # auto-compaction summary, not a reply
        try:
            parts = json.loads(raw or "[]")
        except Exception:
            continue
        text = []
        for part in parts if isinstance(parts, list) else []:
            kind, data = (part.get("type"), part.get("data") or {}) if isinstance(part, dict) else (None, {})
            if kind == "text" and isinstance(data.get("text"), str) and not data.get("hidden"):
                text.append(data["text"])
                continue
            if kind in ("tool_call", "tool_result", "shell_command"):
                yield from _flush(role, text, is_child)
                text = []
            if kind == "tool_call":
                args = data.get("input")
                try:
                    args = json.loads(args) if isinstance(args, str) and args.strip() else args
                except Exception:
                    pass
                calls[data.get("id")] = nav._call_label(data.get("name"), args)
                cmd = nav._shell_cmd(data.get("name"), args)
                if cmd:
                    yield "cmd", cmd
            elif kind == "tool_result":
                output = data.get("content") or ""
                if data.get("is_error"):
                    output = "error\n" + output
                turn = nav.tool_turn(calls.get(data.get("tool_call_id")) or data.get("name") or "tool", output)
                if turn:
                    yield turn
            elif kind == "shell_command" and data.get("command"):  # user's `!cmd` (bang mode)
                yield "cmd", data["command"]
                output = data.get("output") or ""
                if data.get("exit_code"):
                    output = f"exit {data['exit_code']}\n{output}"
                turn = nav.tool_turn(nav._call_label("bash", {"command": data["command"]}), output)
                if turn:
                    yield turn
        yield from _flush(role, text, is_child)


def _flush(role, text, is_child):
    body = "\n".join(t for t in text if t)
    if body.strip():
        if role == "assistant":
            yield "assistant", body
        elif role == "user" and not is_child:  # child (Agent tool) sessions are prompted by the parent agent
            yield "user", body


def crush_project(key):
    db = Path(_split(key)[0])
    for proj in _projects():
        if proj.get("data_dir") and Path(proj["data_dir"]).expanduser() / "crush.db" == db:
            return proj.get("path") or ""
    return str(db.parent.parent) if db.parent.name == ".crush" else ""


def crush_title(key):
    return _session(key)[1] or ""


def crush_fixture(home, cwd):
    home = Path(home)
    data_dir = home / "proj" / ".crush"
    data_dir.mkdir(parents=True, exist_ok=True)
    gdata = home / ".local" / "share" / "crush"
    gdata.mkdir(parents=True, exist_ok=True)
    (gdata / "projects.json").write_text(json.dumps({"projects": [
        {"path": cwd, "data_dir": str(data_dir), "last_accessed": "2026-10-01T00:00:00Z"}]}))
    db = data_dir / "crush.db"
    conn = sqlite3.connect(db)
    conn.executescript("""
    CREATE TABLE sessions (id TEXT PRIMARY KEY, parent_session_id TEXT, title TEXT NOT NULL,
      message_count INTEGER NOT NULL DEFAULT 0, prompt_tokens INTEGER NOT NULL DEFAULT 0,
      completion_tokens INTEGER NOT NULL DEFAULT 0, cost REAL NOT NULL DEFAULT 0.0,
      updated_at INTEGER NOT NULL, created_at INTEGER NOT NULL, summary_message_id TEXT, todos TEXT, channel TEXT);
    CREATE TABLE messages (id TEXT PRIMARY KEY, session_id TEXT NOT NULL, role TEXT NOT NULL,
      parts TEXT NOT NULL default '[]', model TEXT, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL,
      finished_at INTEGER, provider TEXT, is_summary_message INTEGER DEFAULT 0 NOT NULL,
      FOREIGN KEY (session_id) REFERENCES sessions (id) ON DELETE CASCADE);
    """)
    sid, t = "5e55a0de-0000-4000-8000-000000crush1", 1790000000
    p = lambda kind, **data: {"type": kind, "data": data}
    msgs = [
        ("user", [p("text", text="please check zebracorncrush"), p("finish", reason="stop", time=0)], 0),
        ("user", [p("text", text="zebracorninjected continue", hidden=True)], 0),
        ("assistant", [p("reasoning", thinking="zebracorninjected thoughts"), p("text", text="Running it."),
                       p("tool_call", id="call_1", name="bash", input=json.dumps({"command": "echo hi-crush", "description": "d"}),
                         provider_executed=False, finished=True), p("finish", reason="tool_use", time=t)], 0),
        ("tool", [p("tool_result", tool_call_id="call_1", name="bash", content="zebracorncrushtool\n\n<cwd>/x</cwd>",
                    data="", mime_type="", metadata="{}", is_error=False)], 0),
        ("assistant", [p("text", text="Done: zebracorncrush"), p("finish", reason="end_turn", time=t)], 0),
        ("assistant", [p("text", text="zebracorninjected summary of the conversation")], 1),
    ]
    conn.execute("INSERT INTO sessions (id, title, message_count, updated_at, created_at) VALUES (?,?,?,?,?)",
                 (sid, "Fixture crush session", len(msgs), t, t))
    conn.execute("INSERT INTO sessions (id, parent_session_id, title, message_count, updated_at, created_at)"
                 " VALUES (?,?,?,?,?,?)", (f"title-{sid}", sid, "Generate a title", 1, t, t))
    conn.execute("INSERT INTO messages (id, session_id, role, parts, created_at, updated_at) VALUES (?,?,?,?,?,?)",
                 ("tm", f"title-{sid}", "user", json.dumps([p("text", text="zebracorninjected title prompt")]), t, t))
    for i, (role, parts, summary) in enumerate(msgs):
        conn.execute("INSERT INTO messages (id, session_id, role, parts, created_at, updated_at, is_summary_message)"
                     " VALUES (?,?,?,?,?,?,?)", (f"m{i}", sid, role, json.dumps(parts), t, t, summary))
    conn.commit()
    conn.close()
    return f"{db}#{sid}"
