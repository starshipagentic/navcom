"""Hermes Agent (NousResearch) ─ $HERMES_HOME/state.db  (default ~/.hermes/state.db)

One SQLite DB holds every session (CLI, gateway: telegram/slack/discord/…, cron, subagents):
  sessions(id, source, cwd, git_repo_root, title, started_at, ended_at, …)
  messages(id, session_id, role user|assistant|tool, content, tool_calls JSON, tool_name,
           tool_call_id, timestamp, active, compacted, [display_kind, _compressed_summary] …)
List/dict content is stored as "\\x00json:" + json. Thinking lives in reasoning* columns (skipped).
Named profiles keep their own DB: <hermes root>/profiles/<name>/state.db.
"""
import importlib.util
import json
import os
import re
import sqlite3
from pathlib import Path

spec = importlib.util.spec_from_file_location("nav", str(__import__("pathlib").Path(__file__).resolve().parents[3] / "navcom.py"))
nav = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nav)


def _hermes_home():
    return nav._env_path("HERMES_HOME") or Path.home() / ".hermes"


def hermes_roots():
    dbs, seen = [], set()
    for home in (_hermes_home(), Path.home() / ".hermes"):
        profiles = home / "profiles"
        candidates = [home / "state.db"] + (sorted(profiles.glob("*/state.db")) if profiles.is_dir() else [])
        for db in candidates:
            if str(db) not in seen:
                seen.add(str(db))
                dbs.append(db)
    return dbs


def hermes_list():
    logs = []
    for db in hermes_roots():
        if not db.is_file():
            continue
        try:
            conn = nav._ro_connect(db)
            rows = conn.execute(
                "SELECT s.id, COALESCE(MAX(m.timestamp), s.ended_at, s.started_at), COUNT(m.id) "
                "FROM sessions s JOIN messages m ON m.session_id = s.id GROUP BY s.id").fetchall()
            conn.close()
        except sqlite3.Error:
            continue
        for sid, last, count in rows:
            logs.append((f"{db}#{sid}", float(last or 0), int(count or 0), "hermes"))
    return logs


def _split(key):
    db, _, sid = str(key).rpartition("#")
    return db, sid


def _decode(content):
    if isinstance(content, str) and content.startswith("\x00json:"):
        try:
            return nav._text_of(json.loads(content[len("\x00json:"):]))
        except Exception:
            return content
    return content if isinstance(content, str) else ""


_COMPACTION = ("[CONTEXT COMPACTION", "[CONTEXT SUMMARY]:")
_INJECTED = ("[System note:", "[System:", "[SYSTEM:", "[IMPORTANT:", "[Note:", "[Runtime note:") + _COMPACTION
_SKILL_PREFIX = "[IMPORTANT: The user has invoked the "


def _user_text(text):
    """What the human typed: strip Hermes' bracketed notes, memory fences and skill scaffolding."""
    text = (text or "").strip()
    if text.startswith(_COMPACTION):
        return ""
    if text.startswith(_SKILL_PREFIX):  # mirrors agent/skill_commands.extract_user_instruction_from_skill_message
        if " skill bundle," in text:
            i = text.find("\nUser instruction: ")
            text = text[i + 19:].split("\n\n[Loaded as part of the ")[0] if i >= 0 else ""
        else:
            marker = "The user has provided the following instruction alongside the skill invocation: "
            i = text.rfind(marker)
            text = text[i + len(marker):].split("\n\n[Runtime note:")[0] if i >= 0 else ""
    text = re.sub(r"<memory-context>.*?</memory-context>", "", text, flags=re.S).strip()
    while text.startswith(_INJECTED):
        end = text.find("]\n\n")
        text = "" if end < 0 else text[end + 3:].lstrip()
    for tail in ("\n\n[Note: Some earlier conversation turns", "\n\n[Runtime note:"):
        text = text.split(tail)[0]
    return text.strip()


def hermes_iter(key):
    db, sid = _split(key)
    try:
        conn = nav._ro_connect(db)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(messages)")}
        source = (conn.execute("SELECT source FROM sessions WHERE id = ?", (sid,)).fetchone() or [""])[0]
        extra = [c for c in ("display_kind", "_compressed_summary") if c in cols]
        where = " AND (active = 1 OR compacted = 1)" if {"active", "compacted"} <= cols else ""
        rows = conn.execute(
            "SELECT role, content, tool_calls, tool_name, tool_call_id"
            + "".join(f", {c}" for c in extra)
            + f" FROM messages WHERE session_id = ?{where} ORDER BY id", (sid,)).fetchall()
        conn.close()
    except sqlite3.Error:
        return
    calls = {}
    for row in rows:
        role, content, tool_calls, tool_name, call_id = row[:5]
        flags = dict(zip(extra, row[5:]))
        if flags.get("display_kind") == "hidden" or flags.get("_compressed_summary"):
            continue  # model-facing scaffolding / compaction summary
        text = _decode(content)
        if role == "user":
            text = "" if source == "subagent" else _user_text(text)
            if text:
                yield "user", text
        elif role == "assistant":
            if text.strip() and not text.lstrip().startswith(_COMPACTION):
                yield "assistant", text
            try:
                parsed = json.loads(tool_calls) if tool_calls else []
            except Exception:
                parsed = []
            for call in parsed if isinstance(parsed, list) else []:
                fn = (call or {}).get("function") or {}
                args = fn.get("arguments")
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except Exception:
                        pass
                label = nav._call_label(fn.get("name"), args)
                for cid in (call.get("id"), call.get("call_id")):
                    if cid:
                        calls[cid] = label
                cmd = nav._shell_cmd(fn.get("name"), args)
                if cmd:
                    yield "cmd", cmd
        elif role == "tool":
            turn = nav.tool_turn(calls.get(call_id) or tool_name or "tool", text)
            if turn:
                yield turn


def _session_row(key, column):
    db, sid = _split(key)
    try:
        conn = nav._ro_connect(db)
        row = conn.execute(f"SELECT {column}, source FROM sessions WHERE id = ?", (sid,)).fetchone()
        conn.close()
        return row
    except sqlite3.Error:
        return None


def hermes_project(key):
    row = _session_row(key, "COALESCE(NULLIF(cwd, ''), git_repo_root, '')")
    return (row[0] or "") if row else ""


def hermes_title(key):
    row = _session_row(key, "title")
    if not row or not row[0]:
        return ""
    title, source = row
    return title if source in (None, "", "cli") else f"[{source}] {title}"


def _sessions_yaml_block(path):
    """Line-based read of the top-level `sessions:` mapping in config.yaml (stdlib has no YAML)."""
    out, inside = {}, False
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    for line in lines:
        if re.match(r"^sessions:\s*(#.*)?$", line):
            inside = True
            continue
        if inside:
            if line and not line[0].isspace() and not line.lstrip().startswith("#"):
                break
            m = re.match(r"^\s+(auto_prune|retention_days):\s*([^#\s]+)", line)
            if m:
                out[m.group(1)] = m.group(2).strip("'\"")
    return out


def hermes_retention():
    path = _hermes_home() / "config.yaml"
    block = _sessions_yaml_block(path)
    try:
        days = int(block.get("retention_days", 90))
    except ValueError:
        days = 90
    current = block.get("auto_prune")
    return {
        "settings_path": str(path),
        "key_path": "sessions.auto_prune",
        "never_delete_value": False,
        "default_days": days,
        "note": ("YAML, not JSON (stdlib cannot round-trip it). Since release v2026.9.7 Hermes defaults "
                 "sessions.auto_prune: true (hermes_cli/config_defaults.py) and deletes ENDED sessions inactive "
                 "for sessions.retention_days (90) from state.db at CLI/gateway/cron startup, at most once per "
                 "sessions.min_interval_hours (24); v2026.8.31 and older (this Mac: v0.17.0 / 2026.6.19) "
                 "defaulted it to false. Safe fix: `hermes config set sessions.auto_prune false`, or append a "
                 "top-level 'sessions:' block with 'auto_prune: false' when the file has none. Each profile "
                 "(<root>/profiles/<name>/config.yaml) has its own setting. "
                 f"Currently: auto_prune={current if current is not None else 'unset (version default)'}."),
    }


def hermes_fixture(home, cwd):
    home = Path(home)
    hh = home / ".hermes"
    hh.mkdir(parents=True, exist_ok=True)
    db = hh / "state.db"
    conn = sqlite3.connect(db)
    conn.executescript("""
CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, source TEXT NOT NULL, user_id TEXT, model TEXT,
  system_prompt TEXT, parent_session_id TEXT, started_at REAL NOT NULL, ended_at REAL, message_count INTEGER DEFAULT 0,
  cwd TEXT, git_branch TEXT, git_repo_root TEXT, title TEXT, archived INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL REFERENCES sessions(id),
  role TEXT NOT NULL, content TEXT, tool_call_id TEXT, tool_calls TEXT, tool_name TEXT, timestamp REAL NOT NULL,
  token_count INTEGER, finish_reason TEXT, reasoning TEXT, reasoning_content TEXT, observed INTEGER DEFAULT 0,
  active INTEGER NOT NULL DEFAULT 1, compacted INTEGER NOT NULL DEFAULT 0);
""")
    sid = "20261001_120000_abc123"
    t = 1790900000.0
    conn.execute("INSERT INTO sessions (id, source, model, system_prompt, started_at, ended_at, message_count, cwd, title) "
                 "VALUES (?, 'cli', 'deepseek/deepseek-chat-v3.1', 'You are Hermes Agent zebracorninjected', ?, ?, 5, ?, ?)",
                 (sid, t, t + 60, cwd, "Fixture zebracornhermes session"))
    call = [{"id": "call_1", "call_id": "call_1", "type": "function",
             "function": {"name": "terminal", "arguments": json.dumps({"command": "echo hi-hermes"})}}]
    rows = [
        ("user", "[System note: The user's previous session expired due to inactivity. zebracorninjected]", None, None, None),
        ("user", "please run it zebracornhermes", None, None, None),
        ("assistant", "", json.dumps(call), None, None),
        ("tool", json.dumps({"output": "hi-hermes zebracornhermestool", "exit_code": 0, "error": None}), None, "terminal", "call_1"),
        ("assistant", "\x00json:" + json.dumps([{"type": "text", "text": "done zebracornhermes"}]), None, None, None),
    ]
    for i, (role, content, tcalls, tname, tcid) in enumerate(rows):
        conn.execute("INSERT INTO messages (session_id, role, content, tool_calls, tool_name, tool_call_id, timestamp, reasoning) "
                     "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                     (sid, role, content, tcalls, tname, tcid, t + i, "thinking zebracorninjected" if role == "assistant" else None))
    conn.commit()
    conn.close()
    return f"{db}#{sid}"
