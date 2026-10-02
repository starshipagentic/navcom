"""Cline session parser for navcom. Two on-disk shapes:

1. Cline CLI 3.x / SDK (npm `cline`):
     $CLINE_SESSION_DATA_DIR or $CLINE_DATA_DIR/sessions or $CLINE_DIR/data/sessions (default ~/.cline/data/sessions)
       <id>/<id>.messages.json  {version, sessionId, agent, origin, system_prompt, messages:[Anthropic-style]}
       <id>/<id>.json           manifest {session_id, cwd, workspace_root, prompt, metadata.title, ...}
     db/sessions.db mirrors the manifests (index only; not needed to read transcripts).
2. Cline VS Code extension (and forks: Cursor, Windsurf, ...; also older ~/.cline/data/tasks):
     <app>/User/globalStorage/saoudrizwan.claude-dev/tasks/<ts>/ui_messages.json   (UI timeline: say/ask)
     .../tasks/<ts>/api_conversation_history.json  (model-facing; full of injected environment_details)
     .../state/taskHistory.json  [{id, task, cwdOnTaskInitialization?, ...}]
   We parse ui_messages.json: it separates typed text, replies, commands and outputs cleanly
   across both the XML-tool era (2024) and the native-tool era.
"""
import importlib.util
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location("nav", str(__import__("pathlib").Path(__file__).resolve().parents[3] / "navcom.py"))
nav = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nav)

CLINE_EXT_ID = "saoudrizwan.claude-dev"


def cline_data_dir():
    return nav._env_path("CLINE_DATA_DIR") or (nav._env_path("CLINE_DIR") or Path.home() / ".cline") / "data"


def cline_sessions_dir():
    return nav._env_path("CLINE_SESSION_DATA_DIR") or cline_data_dir() / "sessions"


def _editor_config_bases():
    if sys.platform == "darwin":
        return [Path.home() / "Library" / "Application Support"]
    if sys.platform.startswith("win"):
        return [Path(os.environ["APPDATA"])] if os.environ.get("APPDATA") else []
    return [Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config").expanduser()]


def _cline_task_dirs():
    dirs = [cline_data_dir() / "tasks"]
    for base in _editor_config_bases():
        try:
            dirs += sorted(base.glob(f"*/User/globalStorage/{CLINE_EXT_ID}/tasks"))
        except OSError:
            pass
    return dirs


def cline_roots():
    return [cline_sessions_dir()] + _cline_task_dirs()


def cline_list():
    paths = nav._rglob(cline_sessions_dir(), "*.messages.json")
    for tasks in _cline_task_dirs():
        try:
            if tasks.is_dir():
                paths += list(tasks.glob("*/ui_messages.json"))
        except OSError:
            pass
    return nav._file_logs(paths, "cline")


def _load_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return None


def cline_iter(key):
    if key.endswith("ui_messages.json"):
        yield from _cline_ui_iter(key)
    else:
        yield from _cline_sdk_iter(key)


# ── Cline CLI 3.x / SDK ──────────────────────────────────────────────────────

_WRAP_RE = re.compile(r"<user_(?:input|command)\b")
_FILE_RE = re.compile(r"<file_content\b[^>]*>.*?</file_content>", re.S)
_NOTICE_RE = re.compile(r"<mode_notice>.*?</mode_notice>", re.S)
_COMMAND_RE = re.compile(r'^\s*<user_command\b[^>]*\bslash="([^"]+)"[^>]*>(.*?)</user_command>\s*$', re.S | re.I)


def _cline_typed(text):
    """Cline's own normalizeUserInput: unwrap <user_input>, render <user_command slash> as /slash."""
    slash = _COMMAND_RE.match(text)
    text = _NOTICE_RE.sub("", _FILE_RE.sub("", text))
    for tag in ("user_input", "user_command"):
        text = re.sub(rf"<{tag}\b[^>]*>(.*?)</{tag}>", r"\1", text, flags=re.S)
        text = re.sub(rf"</?{tag}\b[^>]*>", "", text)
    text = text.strip()
    if slash:
        return f"/{slash.group(1)} {text}".strip()
    return text


def _cline_commands(name, args):
    """run_commands takes {commands:[str | {command, args}]} (or a bare string/list); others: navcom's rule."""
    if name != "run_commands":
        cmd = nav._shell_cmd(name, args)
        return [cmd] if cmd else []
    items = args.get("commands", args.get("command", args.get("cmd"))) if isinstance(args, dict) else args
    if not isinstance(items, list):
        items = [items]
    cmds = []
    for item in items:
        if isinstance(item, dict):
            argv = [a if not re.search(r'[\s"]', str(a)) else json.dumps(a) for a in item.get("args") or []]
            item = " ".join([str(item.get("command") or "")] + argv).strip()
        if isinstance(item, str) and item.strip():
            cmds.append(item.strip())
    return cmds


def _cline_label_args(args):
    """read_files {files:[{path}]} / fetch_web_content {requests:[{url}]} -> a dict _call_label understands."""
    if isinstance(args, dict):
        for field, key in (("files", "path"), ("requests", "url")):
            items = args.get(field)
            if isinstance(items, list):
                vals = [str(i.get(key) if isinstance(i, dict) else i) for i in items]
                return {key: ", ".join(v for v in vals if v and v != "None")}
    return args


def _cline_result(content):
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        content = [content]
    parts = []
    for item in content if isinstance(content, list) else []:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, dict) and ("result" in item or "error" in item):
            result = item.get("result")
            text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False) if result else ""
            if item.get("error") and str(item["error"]) not in text:
                text = f"error: {item['error']}\n{text}".strip()
            if len(content) > 1 and item.get("query"):
                text = f"$ {item['query']}\n{text}"
            parts.append(text)
        elif isinstance(item, dict) and item.get("type") == "text":
            parts.append(item.get("text") or "")
    return "\n".join(p for p in parts if p)


def _cline_sdk_iter(key):
    data = _load_json(key)
    messages = data.get("messages") if isinstance(data, dict) else data
    if not isinstance(messages, list):
        return
    blocks = lambda m: [{"type": "text", "text": m["content"]}] if isinstance(m.get("content"), str) else (
        m.get("content") if isinstance(m.get("content"), list) else [])
    # 3.x wraps typed input in <user_input>; once a session uses the wrapper, any bare user text is
    # runtime-injected (loop/mistake notices, file attachments). Imported/older sessions have no wrapper.
    wrapped = any(m.get("role") == "user" and any(b.get("type") == "text" and _WRAP_RE.search(b.get("text") or "")
                                                  for b in blocks(m) if isinstance(b, dict))
                  for m in messages if isinstance(m, dict))
    calls = {}
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        meta = msg.get("metadata") if isinstance(msg.get("metadata"), dict) else {}
        injected = bool(meta.get("kind")) or meta.get("displayRole") == "system"  # compaction summaries
        for block in blocks(msg):
            if not isinstance(block, dict):
                continue
            kind = block.get("type")
            if msg.get("role") == "user":
                if kind == "tool_result":
                    output = _cline_result(block.get("content"))
                    if block.get("is_error"):
                        output = "error\n" + output
                    turn = nav.tool_turn(calls.get(block.get("tool_use_id"), block.get("name") or "tool"), output)
                    if turn:
                        yield turn
                elif kind == "text" and not injected:
                    text = block.get("text") or ""
                    if wrapped and not _WRAP_RE.search(text):
                        continue
                    text = _cline_typed(text)
                    if text:
                        yield "user", text
            elif msg.get("role") == "assistant":
                if kind == "text" and (block.get("text") or "").strip():
                    yield "assistant", block["text"]
                elif kind == "tool_use":
                    args = block.get("input")
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except Exception:
                            pass
                    cmds = _cline_commands(block.get("name"), args)
                    calls[block.get("id")] = nav._call_label(
                        block.get("name"), {"command": " ; ".join(cmds)} if cmds else _cline_label_args(args))
                    for cmd in cmds:
                        yield "cmd", cmd
                # thinking / reasoning / redacted_thinking / image blocks: skipped


# ── VS Code extension tasks (ui_messages.json) ────────────────────────────────

def _cline_ui_iter(key):
    messages = _load_json(key)
    if not isinstance(messages, list):
        return
    seen_request = got_task = False
    cmd_label, cmd_out, mcp_label = None, [], None

    def flush():
        return nav.tool_turn(cmd_label, "\n".join(cmd_out)) if cmd_label and cmd_out else None

    for msg in messages:
        if not isinstance(msg, dict):
            continue  # note: newer builds leave partial=True on finished text, so `partial` is not a skip signal
        kind, text = msg.get("say") or msg.get("ask"), msg.get("text") or ""
        if kind != "command_output" and cmd_label:
            turn = flush()
            if turn:
                yield turn
            cmd_label, cmd_out = None, []
        if kind == "api_req_started":  # the full model request incl. environment_details — injected
            seen_request = True
        elif kind == "task" or (kind == "text" and msg.get("type") == "say" and not seen_request and not got_task):
            got_task = True
            if text.strip():
                yield "user", text
        elif kind == "user_feedback":
            if text.strip():
                yield "user", text
        elif kind in ("text", "completion_result") and msg.get("type") == "say":
            text = re.sub(r"\s*HAS_CHANGES\s*$", "", text)
            if text.strip():
                yield "assistant", text
        elif kind in ("followup", "plan_mode_respond", "completion_result") and msg.get("type") == "ask":
            obj = _maybe_json(text)
            if isinstance(obj, dict):
                text = obj.get("question") or obj.get("response") or ""
            if isinstance(text, str) and text.strip():
                yield "assistant", text
        elif kind == "command":
            cmd = re.sub(r"\s*REQ_APP\s*$", "", text).strip()
            if cmd:
                yield "cmd", cmd
                cmd_label, cmd_out = nav._call_label("execute_command", {"command": cmd}), []
        elif kind == "command_output":
            if cmd_label:
                cmd_out.append(text)
            else:
                turn = nav.tool_turn("command output", text)
                if turn:
                    yield turn
        elif kind == "tool":
            obj = _maybe_json(text)
            if isinstance(obj, dict):
                output = obj.get("content") or obj.get("diff") or ""
                turn = nav.tool_turn(nav._call_label(obj.get("tool"), obj), output if isinstance(output, str) else "")
                if turn:
                    yield turn
        elif kind == "use_mcp_server":
            obj = _maybe_json(text) or {}
            mcp_label = nav._call_label(f"{obj.get('serverName', 'mcp')}.{obj.get('toolName') or obj.get('uri') or ''}",
                                        _maybe_json(obj.get("arguments")) if obj.get("arguments") else None)
        elif kind == "mcp_server_response":
            turn = nav.tool_turn(mcp_label or "mcp", text)
            if turn:
                yield turn
        # reasoning, api_req_*, error, checkpoint_created, resume_task, browser_action*, ... skipped
    turn = flush()
    if turn:
        yield turn


def _maybe_json(text):
    if not isinstance(text, str) or not text.lstrip().startswith(("{", "[")):
        return text if isinstance(text, dict) else None
    try:
        return json.loads(text)
    except Exception:
        return None


def _cline_task_meta(key):
    task_id = Path(key).parent.name
    history = _load_json(Path(key).parent.parent.parent / "state" / "taskHistory.json")
    for item in history if isinstance(history, list) else []:
        if isinstance(item, dict) and str(item.get("id")) == task_id:
            return item
    return {}


def _cline_manifest(key):
    sid = Path(key).name[: -len(".messages.json")]
    manifest = _load_json(Path(key).parent / f"{sid}.json")
    if isinstance(manifest, dict):
        return manifest
    db = cline_data_dir() / "db" / "sessions.db"
    try:
        con = nav._ro_connect(db)
        try:
            row = con.execute("SELECT cwd, prompt, metadata_json FROM sessions WHERE session_id = ?", (sid,)).fetchone()
        finally:
            con.close()
    except sqlite3.Error:
        row = None
    if not row:
        return {}
    meta = _maybe_json(row[2]) or {}
    return {"cwd": row[0], "prompt": row[1], "metadata": meta if isinstance(meta, dict) else {}}


_CWD_RE = re.compile(r"# Current Working Directory \((/[^)\n]+)\) Files")


def cline_project(key):
    if key.endswith("ui_messages.json"):
        cwd = _cline_task_meta(key).get("cwdOnTaskInitialization")
        if cwd:
            return cwd
        try:
            with open(Path(key).parent / "api_conversation_history.json", "r", encoding="utf-8", errors="replace") as fh:
                m = _CWD_RE.search(fh.read(2_000_000))
            return m.group(1) if m else ""
        except OSError:
            return ""
    manifest = _cline_manifest(key)
    return manifest.get("cwd") or manifest.get("workspace_root") or ""


def cline_title(key):
    if key.endswith("ui_messages.json"):
        task = _cline_task_meta(key).get("task") or ""
        return task.strip().splitlines()[0][:200] if task.strip() else ""
    meta = _cline_manifest(key).get("metadata") or {}
    return meta.get("title") or "" if isinstance(meta, dict) else ""


def cline_fixture(home, cwd):
    """A Cline CLI 3.x session: messages.json + manifest + sessions.db row (as written by cline 3.0.67)."""
    sid = "1790000000000_fixtr"
    sdir = Path(home) / ".cline" / "data" / "sessions" / sid
    sdir.mkdir(parents=True, exist_ok=True)
    messages_path = sdir / f"{sid}.messages.json"
    messages = [
        {"id": "u1", "role": "user", "ts": 1790000000100, "content": [
            {"type": "text", "text": '<user_input mode="act">please check zebracorncline</user_input>'},
            {"type": "text", "text": '<file_content path="notes.md"> attached zebracorninjected </file_content>'}]},
        {"id": "a1", "role": "assistant", "ts": 1790000000200, "content": [
            {"type": "thinking", "thinking": "zebracorninjected thoughts"},
            {"type": "text", "text": "Running it for zebracorncline."},
            {"type": "tool_use", "id": "call_1", "name": "run_commands", "input": {"commands": ["echo hi-cline"]}}]},
        {"id": "r1", "role": "user", "ts": 1790000000300, "content": [
            {"type": "tool_result", "tool_use_id": "call_1", "name": "run_commands",
             "content": [{"query": "echo hi-cline", "result": "zebracornclinetool\n", "success": True}]}]},
        {"id": "n1", "role": "user", "content": [
            {"type": "text", "text": "You seem to be repeating yourself zebracorninjected"}]},
        {"id": "s1", "role": "user", "content": [{"type": "text", "text": "Context summary:  zebracorninjected"}],
         "metadata": {"kind": "compaction_summary", "displayRole": "system"}},
        {"id": "a2", "role": "assistant", "content": [{"type": "text", "text": "Done: zebracorncline"}]},
    ]
    messages_path.write_text(json.dumps({
        "version": 1, "updated_at": "2026-10-02T03:27:02.059Z", "agent": "lead", "sessionId": sid,
        "origin": {"source": "cli", "mode": "user", "sessionId": sid, "version": "3.0.67"},
        "messages": messages, "system_prompt": "You are Cline. zebracorninjected"}, indent=2))
    manifest = {"version": 1, "session_id": sid, "source": "cli", "pid": 1, "started_at": "2026-10-02T03:26:48.960Z",
                "status": "completed", "interactive": False, "provider": "openrouter", "model": "fixture",
                "cwd": cwd, "workspace_root": cwd, "prompt": "please check zebracorncline",
                "metadata": {"title": "fixture zebracorncline"}, "messages_path": str(messages_path)}
    (sdir / f"{sid}.json").write_text(json.dumps(manifest, indent=2))
    db_dir = Path(home) / ".cline" / "data" / "db"
    db_dir.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_dir / "sessions.db")
    con.execute("CREATE TABLE IF NOT EXISTS sessions (session_id TEXT PRIMARY KEY, source TEXT NOT NULL, pid INTEGER NOT NULL,"
                " started_at TEXT NOT NULL, status TEXT NOT NULL, interactive INTEGER NOT NULL, provider TEXT NOT NULL,"
                " model TEXT NOT NULL, cwd TEXT NOT NULL, workspace_root TEXT NOT NULL, prompt TEXT, metadata_json TEXT,"
                " messages_path TEXT, updated_at TEXT NOT NULL)")
    con.execute("INSERT OR REPLACE INTO sessions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (sid, "cli", 1, manifest["started_at"], "completed", 0, "openrouter", "fixture", cwd, cwd,
                 manifest["prompt"], json.dumps(manifest["metadata"]), str(messages_path), manifest["started_at"]))
    con.commit()
    con.close()
    return str(messages_path)


def cline_legacy_fixture(home, cwd):
    """A VS Code extension task (ui_messages.json + api history + taskHistory), as on this Mac."""
    base = Path(home) / "Library" / "Application Support" / "Code" / "User" / "globalStorage" / CLINE_EXT_ID
    if not sys.platform == "darwin":
        base = Path(home) / ".config" / "Code" / "User" / "globalStorage" / CLINE_EXT_ID
    tid = "1728640760969"
    tdir = base / "tasks" / tid
    tdir.mkdir(parents=True, exist_ok=True)
    ui = [
        {"ts": 1, "type": "say", "say": "text", "text": "please check zebracornclineext", "images": []},
        {"ts": 2, "type": "say", "say": "api_req_started",
         "text": json.dumps({"request": "<task>x</task>\n<environment_details>zebracorninjected</environment_details>"})},
        {"ts": 3, "type": "say", "say": "reasoning", "text": "zebracorninjected thinking"},
        {"ts": 4, "type": "say", "say": "text", "text": "Running it for zebracornclineext.", "partial": False},
        {"ts": 5, "type": "ask", "ask": "command", "text": "echo hi-clineext", "partial": False},
        {"ts": 6, "type": "ask", "ask": "command_output", "text": "zebracornclineexttool"},
        {"ts": 7, "type": "ask", "ask": "command_output", "text": "second line"},
        {"ts": 8, "type": "say", "say": "api_req_started", "text": json.dumps({"request": "[execute_command] zebracorninjected"})},
        {"ts": 9, "type": "say", "say": "tool", "text": json.dumps({"tool": "readFile", "path": "calc.py", "content": "def add zebracornclineextfile"})},
        {"ts": 10, "type": "say", "say": "completion_result", "text": "All done zebracornclineext"},
        {"ts": 11, "type": "ask", "ask": "completion_result", "text": ""},
        {"ts": 12, "type": "say", "say": "user_feedback", "text": "thanks zebracornclineext", "images": []},
    ]
    (tdir / "ui_messages.json").write_text(json.dumps(ui))
    (tdir / "api_conversation_history.json").write_text(json.dumps([{"role": "user", "content": [
        {"type": "text", "text": "<task>\nplease check zebracornclineext\n</task>"},
        {"type": "text", "text": f"<environment_details>\n# Current Working Directory ({cwd}) Files\nzebracorninjected\n</environment_details>"}]}]))
    (base / "state").mkdir(parents=True, exist_ok=True)
    (base / "state" / "taskHistory.json").write_text(json.dumps([{"id": tid, "ts": 1, "task": "please check zebracornclineext"}]))
    return str(tdir / "ui_messages.json")
