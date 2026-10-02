"""grok-dev (community superagent-ai/grok-cli, npm `grok-dev`) — SQLite store ~/.grok/grok.db.

Shares ~/.grok with xAI's official Grok Build CLI (~/.grok/sessions/*/updates.jsonl), but this is a
different file. Path is hard-coded: os.homedir()/.grok/grok.db (dist/storage/db.js) — no env override.

Schema (dist/storage/migrations.js, user_version 3):
  workspaces(id, scope_key, canonical_path, git_root, display_name, last_seen_at)
  sessions(id, workspace_id, title, recap_text, recap_model, recap_updated_at, model, mode,
           cwd_at_start, cwd_last, status, created_at, updated_at)
  messages(session_id, seq, role, message_json, created_at)   -- message_json = Vercel AI SDK ModelMessage
  tool_calls / tool_results / usage_events / compactions        -- denormalised copies; not needed

message_json roles:
  user      {"content": str | [{type:"text",text} | {type:"image",...}]}        -> user
  assistant {"content": str | [{type:"text"} | {type:"reasoning"} | {type:"tool-call",toolCallId,toolName,input}]}
  tool      {"content": [{type:"tool-result",toolCallId,toolName,output:{type:"json"|"text"|"error-text",value}}]}
  system    background-task notifications + compaction summaries                 -> skipped (injected)
"""
import importlib.util
import json
from pathlib import Path

spec = importlib.util.spec_from_file_location("nav", str(__import__("pathlib").Path(__file__).resolve().parents[3] / "navcom.py"))
nav = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nav)


def grokdev_db_path():
    return Path.home() / ".grok" / "grok.db"


def grokdev_roots():
    return [grokdev_db_path()]


def grokdev_list():
    db = grokdev_db_path()
    if not db.is_file():
        return []
    try:
        conn = nav._ro_connect(db)
        rows = conn.execute("""
            SELECT s.id, s.updated_at, COUNT(m.seq), MAX(m.created_at)
            FROM sessions s LEFT JOIN messages m ON m.session_id = s.id
            GROUP BY s.id HAVING COUNT(m.seq) > 0""").fetchall()
        conn.close()
    except Exception:
        return []
    return [(f"{db}#{sid}", max(nav._epoch_seconds(updated), nav._epoch_seconds(last)), int(count), "grokdev")
            for sid, updated, count, last in rows]


def _split_key(key):
    db, _, sid = str(key).rpartition("#")
    return db, sid


def _grokdev_output(output):
    """ToolResultOutput -> text: {type:json, value:{success, output, error}} | {type:text|error-text, value}."""
    if not isinstance(output, dict):
        return output
    kind, value = output.get("type"), output.get("value")
    if kind == "json" and isinstance(value, dict):
        if "success" in value or "output" in value or "error" in value:
            text = value.get("output")
            if not isinstance(text, str):
                text = json.dumps(text, ensure_ascii=False) if text not in (None, "") else ""
            if value.get("error"):
                text = f"error\n{value['error']}\n{text}".rstrip()
            return text
        return json.dumps(value, ensure_ascii=False)[:20000]
    if kind == "error-text":
        return f"error\n{value}"
    if kind in ("text", "content"):
        return value if isinstance(value, str) else nav._text_of(value)
    return value if isinstance(value, (str, list)) else json.dumps(output, ensure_ascii=False)[:20000]


def grokdev_iter(key):
    db, sid = _split_key(key)
    try:
        conn = nav._ro_connect(db)
        rows = conn.execute("SELECT role, message_json FROM messages WHERE session_id = ? ORDER BY seq",
                            (sid,)).fetchall()
        conn.close()
    except Exception:
        return
    calls = {}
    for role, raw in rows:
        try:
            msg = json.loads(raw)
        except Exception:
            continue
        content = msg.get("content")
        if role == "user":
            text = nav._text_of(content)
            if text and text.strip():
                yield "user", text
        elif role == "assistant":
            if isinstance(content, str):
                if content.strip():
                    yield "assistant", content
                continue
            for part in content or []:
                if not isinstance(part, dict):
                    continue
                kind = part.get("type")
                if kind == "text" and (part.get("text") or "").strip():
                    yield "assistant", part["text"]
                elif kind == "tool-call":
                    args = part.get("input")
                    if isinstance(args, str):
                        try:
                            args = json.loads(args) if args.strip() else {}
                        except Exception:
                            pass
                    calls[part.get("toolCallId")] = nav._call_label(part.get("toolName"), args)
                    cmd = nav._shell_cmd(part.get("toolName"), args)
                    if cmd:
                        yield "cmd", cmd
        elif role == "tool":
            for part in content or []:
                if isinstance(part, dict) and part.get("type") == "tool-result":
                    label = calls.get(part.get("toolCallId")) or part.get("toolName") or "tool"
                    turn = nav.tool_turn(label, _grokdev_output(part.get("output")))
                    if turn:
                        yield turn
        # role == "system": background notifications / compaction summaries — injected, skipped


def _grokdev_session(key):
    db, sid = _split_key(key)
    try:
        conn = nav._ro_connect(db)
        row = conn.execute("""SELECT s.title, s.cwd_at_start, s.cwd_last, w.canonical_path
                              FROM sessions s LEFT JOIN workspaces w ON w.id = s.workspace_id
                              WHERE s.id = ?""", (sid,)).fetchone()
        conn.close()
        return row or (None, None, None, None)
    except Exception:
        return (None, None, None, None)


def grokdev_project(key):
    title, start, last, workspace = _grokdev_session(key)
    return start or last or workspace or ""


def grokdev_title(key):
    return _grokdev_session(key)[0] or ""


_SCHEMA = """
CREATE TABLE IF NOT EXISTS workspaces (id TEXT PRIMARY KEY, scope_key TEXT NOT NULL UNIQUE,
  canonical_path TEXT NOT NULL, git_root TEXT, display_name TEXT NOT NULL, last_seen_at TEXT NOT NULL) STRICT;
CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE, title TEXT, recap_text TEXT,
  recap_model TEXT, recap_updated_at TEXT, model TEXT NOT NULL, mode TEXT NOT NULL, cwd_at_start TEXT NOT NULL,
  cwd_last TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL) STRICT;
CREATE TABLE IF NOT EXISTS messages (session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  seq INTEGER NOT NULL, role TEXT NOT NULL, message_json TEXT NOT NULL, created_at TEXT NOT NULL,
  PRIMARY KEY (session_id, seq)) STRICT;
CREATE TABLE IF NOT EXISTS tool_calls (id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE, message_seq INTEGER NOT NULL,
  tool_call_id TEXT NOT NULL, tool_name TEXT NOT NULL, args_json TEXT NOT NULL, status TEXT NOT NULL,
  started_at TEXT NOT NULL, completed_at TEXT, UNIQUE(session_id, tool_call_id)) STRICT;
CREATE TABLE IF NOT EXISTS tool_results (id INTEGER PRIMARY KEY AUTOINCREMENT,
  tool_call_row_id INTEGER NOT NULL REFERENCES tool_calls(id) ON DELETE CASCADE, output_kind TEXT NOT NULL,
  output_json TEXT NOT NULL, success INTEGER NOT NULL, created_at TEXT NOT NULL) STRICT;
CREATE TABLE IF NOT EXISTS compactions (id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE, first_kept_seq INTEGER NOT NULL,
  summary TEXT NOT NULL, tokens_before INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL) STRICT;
"""


def grokdev_fixture(home, cwd):
    import sqlite3
    db = Path(home) / ".grok" / "grok.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db)
    conn.executescript(_SCHEMA)
    conn.execute("PRAGMA user_version = 3")
    ts = "2026-10-02T03:29:41.039Z"
    sid = "9c50d8f22635"
    conn.execute("INSERT INTO workspaces VALUES (?,?,?,?,?,?)", ("56c2445959b489d7", cwd, cwd, None, Path(cwd).name, ts))
    conn.execute("INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                 (sid, "56c2445959b489d7", "zebracorn fixture", None, None, None, "openai/gpt-oss-120b", "agent",
                  cwd, cwd, "active", ts, ts))
    call_id = "fc_548bf827-6223-4e6f-b59d-90c97de3db36"
    messages = [
        ("system", {"role": "system", "content": "Background task finished: zebracorninjected notification"}),
        ("user", {"role": "user", "content": "please say zebracorngrokdev and run echo"}),
        ("assistant", {"role": "assistant", "content": [
            {"type": "reasoning", "text": "thinking about zebracornthinking"},
            {"type": "tool-call", "toolCallId": call_id, "toolName": "bash",
             "input": {"command": "echo hi-grokdev", "timeout": 30000, "background": False}}]}),
        ("tool", {"role": "tool", "content": [{"type": "tool-result", "toolCallId": call_id, "toolName": "bash",
                                                "output": {"type": "json", "value": {"success": True,
                                                                                    "output": "hi-grokdev zebracorngrokdevtool"}}}]}),
        ("assistant", {"role": "assistant", "content": [{"type": "text", "text": "done: zebracorngrokdev"}]}),
    ]
    for seq, (role, msg) in enumerate(messages, 1):
        conn.execute("INSERT INTO messages VALUES (?,?,?,?,?)", (sid, seq, role, json.dumps(msg), ts))
    conn.commit()
    conn.close()
    return f"{db}#{sid}"
