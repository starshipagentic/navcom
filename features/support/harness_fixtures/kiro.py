"""Kiro CLI (AWS) parser for navcom.

Three storage generations, all handled:

  V2 (default engine in kiro-cli 2.27):
    $KIRO_HOME (default ~/.kiro)/sessions/cli/<uuid>.jsonl   + <uuid>.json sidecar
    lines: {"kind": Prompt|AssistantMessage|ToolResults|Compaction|ResetTo|CancelledPrompt|Clear,
            "data": {"content": [{"kind": text|toolUse|toolResult|image|thinking, "data": ...}]}}
    sidecar: {session_id, cwd, title|null, created_at, updated_at, session_created_reason, session_state}
  KAS ("V3" Kiro Agent Server, opt-in):
    $KIRO_HOME/sessions[/<workspace>]/sess_<uuid>/messages.jsonl + session.json
    lines: {"timestamp", "payload": {"type": user|assistant|tool_call|tool_result|..., ...}}
  V1 (legacy chat-cli / Amazon Q lineage): SQLite data.sqlite3 table conversations_v2
    macOS ~/Library/Application Support/kiro-cli/data.sqlite3, Linux $XDG_DATA_HOME/kiro-cli/data.sqlite3
    value JSON: {conversation_id, history: [{user{content{Prompt{prompt}|ToolUseResults{...}|CancelledToolUses{...}},
                 additional_context, env_context}, assistant{Response{content}|ToolUse{content, tool_uses}}}]}
"""
import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location("nav", str(__import__("pathlib").Path(__file__).resolve().parents[3] / "navcom.py"))
nav = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nav)

KIRO_SHELL_TOOLS = ("shell", "execute_bash", "execute_cmd", "executeBash", "bash")


def kiro_home():
    return nav._env_path("KIRO_HOME") or Path.home() / ".kiro"


def kiro_db_paths():
    if sys.platform == "darwin":
        base = [Path.home() / "Library" / "Application Support" / "kiro-cli"]
    else:
        base = []
    base.append(nav._xdg_data_home() / "kiro-cli")
    return [b / "data.sqlite3" for b in base]


def kiro_roots():
    return [kiro_home() / "sessions"] + kiro_db_paths()


def _kiro_db_logs(db):
    logs = []
    try:
        conn = nav._ro_connect(db)
        try:
            rows = conn.execute("SELECT conversation_id, MAX(updated_at), length(value) FROM conversations_v2 "
                                "GROUP BY conversation_id").fetchall()
        finally:
            conn.close()
    except sqlite3.Error:
        return logs
    for conv_id, updated, size in rows:
        logs.append((f"{db}#{conv_id}", nav._epoch_seconds(updated), int(size or 0), "kiro"))
    return logs


def kiro_list():
    root = kiro_home() / "sessions"
    files = [p for p in (list(root.glob("cli/*.jsonl")) + list(root.glob("*.jsonl"))) if p.is_file()]
    files += list(root.glob("sess_*/messages.jsonl")) + list(root.glob("*/sess_*/messages.jsonl"))
    logs = [log for log in nav._file_logs(files, "kiro") if log[2] > 0]  # failed first turns leave 0-byte logs
    for db in kiro_db_paths():
        if db.is_file():
            logs.extend(_kiro_db_logs(db))
    return logs


# ── helpers ──────────────────────────────────────────────────────────────────

def _kiro_result_text(content):
    """Tool result content: str | [{"kind":"text"|"json","data"}] | [{"Text"}|{"Json"}] | dict."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(t for t in (_kiro_result_text(c) for c in content) if t)
    if isinstance(content, dict):
        if "kind" in content and "data" in content:
            return _kiro_result_text(content["data"])
        for key in ("Text", "text", "Json", "json"):
            if key in content:
                return _kiro_result_text(content[key])
        parts = [str(content[k]) for k in ("stdout", "stderr", "output", "content")
                 if isinstance(content.get(k), (str, int, float)) and str(content[k]).strip()]
        if parts:
            code = content.get("exit_status", content.get("exitCode"))
            prefix = f"exit {code}\n" if code not in (None, 0, "0") else ""
            return prefix + "\n".join(parts)
        return json.dumps(content, ensure_ascii=False)[:20000]
    return str(content)


def _kiro_call(calls, call_id, name, args):
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except Exception:
            pass
    calls[call_id] = nav._call_label(name, args)
    cmd = None
    if (name or "") in KIRO_SHELL_TOOLS and isinstance(args, dict):
        cmd = args.get("command") or args.get("cmd")
        cmd = cmd.strip() if isinstance(cmd, str) else None
    return cmd or nav._shell_cmd(name, args)


def _kiro_result_turn(calls, call_id, content, status=None):
    output = _kiro_result_text(content)
    if str(status or "").lower() in ("error", "failed"):
        output = "error\n" + output
    return nav.tool_turn(calls.get(call_id, "tool"), output)


def _kiro_blocks(data):
    content = (data or {}).get("content") if isinstance(data, dict) else None
    return content if isinstance(content, list) else []


# ── V2 JSONL ─────────────────────────────────────────────────────────────────

def _iter_kiro_v2(handle):
    calls = {}
    for line in handle:
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if not isinstance(obj, dict):
            continue
        kind, data = obj.get("kind"), obj.get("data") or {}
        if kind == "Prompt":
            text = "\n\n".join(b["data"].strip() for b in _kiro_blocks(data)
                               if isinstance(b, dict) and b.get("kind") == "text"
                               and isinstance(b.get("data"), str) and b["data"].strip())
            if text:
                yield "user", text
        elif kind == "AssistantMessage":
            texts = []
            for block in _kiro_blocks(data):
                if not isinstance(block, dict):
                    continue
                if block.get("kind") == "text" and isinstance(block.get("data"), str):
                    texts.append(block["data"])
                elif block.get("kind") == "toolUse" and isinstance(block.get("data"), dict):
                    if texts:
                        yield "assistant", "\n".join(texts)
                        texts = []
                    tu = block["data"]
                    cmd = _kiro_call(calls, tu.get("toolUseId"), tu.get("name"), tu.get("input"))
                    if cmd:
                        yield "cmd", cmd
            if "".join(texts).strip():
                yield "assistant", "\n".join(texts)
        elif kind == "ToolResults":
            for block in _kiro_blocks(data):
                if isinstance(block, dict) and block.get("kind") == "toolResult" and isinstance(block.get("data"), dict):
                    tr = block["data"]
                    turn = _kiro_result_turn(calls, tr.get("toolUseId"), tr.get("content"), tr.get("status"))
                    if turn:
                        yield turn
        # Compaction (generated summary), ResetTo, CancelledPrompt, Clear: not typed text


# ── KAS messages.jsonl ───────────────────────────────────────────────────────

def _iter_kiro_kas(handle):
    calls = {}
    for line in handle:
        try:
            payload = (json.loads(line) or {}).get("payload") or {}
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        typ = payload.get("type")
        content = payload.get("content")
        if typ in ("user", "assistant"):
            text = content if isinstance(content, str) else nav._text_of(content)
            if text and text.strip():
                yield typ, text.strip()
        elif typ == "tool_call":
            cmd = _kiro_call(calls, payload.get("toolCallId"), payload.get("toolName"), payload.get("args"))
            if cmd:
                yield "cmd", cmd
        elif typ == "tool_result":
            turn = _kiro_result_turn(calls, payload.get("toolCallId"), content, payload.get("status"))
            if turn:
                yield turn


# ── V1 SQLite ────────────────────────────────────────────────────────────────

def _kiro_db_row(key):
    db, _, conv_id = key.rpartition("#")
    try:
        conn = nav._ro_connect(db)
        try:
            return conn.execute("SELECT key, value FROM conversations_v2 WHERE conversation_id = ? "
                                "ORDER BY updated_at DESC LIMIT 1", (conv_id,)).fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return None


def _iter_kiro_db(key):
    row = _kiro_db_row(key)
    if not row:
        return
    try:
        conv = json.loads(row[1])
    except Exception:
        return
    calls = {}
    for entry in conv.get("history") or []:
        if not isinstance(entry, dict):
            continue
        user = entry.get("user") or {}
        content = user.get("content") or {}
        # user.additional_context / env_context are injected by the CLI: skipped
        if isinstance(content, dict):
            for variant in ("Prompt", "CancelledToolUses"):
                prompt = (content.get(variant) or {}).get("prompt") if isinstance(content.get(variant), dict) else None
                if isinstance(prompt, str) and prompt.strip():
                    yield "user", prompt.strip()
            for variant in ("ToolUseResults", "CancelledToolUses"):
                block = content.get(variant)
                for res in (block or {}).get("tool_use_results") or [] if isinstance(block, dict) else []:
                    if isinstance(res, dict):
                        turn = _kiro_result_turn(calls, res.get("tool_use_id"), res.get("content"), res.get("status"))
                        if turn:
                            yield turn
        assistant = entry.get("assistant") or {}
        for variant in ("Response", "ToolUse"):
            msg = assistant.get(variant)
            if not isinstance(msg, dict):
                continue
            if isinstance(msg.get("content"), str) and msg["content"].strip():
                yield "assistant", msg["content"]
            for tu in msg.get("tool_uses") or []:
                if isinstance(tu, dict):
                    cmd = _kiro_call(calls, tu.get("id"), tu.get("name"), tu.get("args"))
                    if cmd:
                        yield "cmd", cmd


def kiro_iter(key):
    if "#" in key and not key.endswith(".jsonl"):
        yield from _iter_kiro_db(key)
        return
    try:
        handle = open(key, "r", encoding="utf-8", errors="replace")
    except OSError:
        return
    with handle:
        if Path(key).name == "messages.jsonl":
            yield from _iter_kiro_kas(handle)
        else:
            yield from _iter_kiro_v2(handle)


def _kiro_sidecar(key):
    path = Path(key)
    side = path.parent / "session.json" if path.name == "messages.jsonl" else path.with_suffix(".json")
    try:
        data = json.loads(side.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def kiro_project(key):
    if "#" in key and not key.endswith(".jsonl"):
        row = _kiro_db_row(key)
        return row[0] if row and isinstance(row[0], str) else ""
    side = _kiro_sidecar(key)
    if isinstance(side.get("cwd"), str):
        return side["cwd"]
    paths = side.get("workspacePaths")
    return paths[0] if isinstance(paths, list) and paths and isinstance(paths[0], str) else ""


def kiro_title(key):
    if "#" in key and not key.endswith(".jsonl"):
        return ""
    title = _kiro_sidecar(key).get("title")
    return title.strip() if isinstance(title, str) else ""


# ── fixture ──────────────────────────────────────────────────────────────────

def kiro_fixture(home, cwd):
    sid = "3dffef0b-b33f-4a84-85ad-567e79973c9e"
    root = Path(home) / ".kiro" / "sessions" / "cli"
    root.mkdir(parents=True, exist_ok=True)
    now = "2026-10-02T03:31:23.533628Z"
    (root / f"{sid}.json").write_text(json.dumps({
        "session_id": sid, "cwd": cwd, "created_at": now, "updated_at": now,
        "title": "zebracorn fixture", "session_created_reason": "user",
        "session_state": {"version": "v1", "conversation_metadata": {"user_turn_metadatas": []},
                          "rts_model_state": {"conversation_id": sid, "model_info": None},
                          "permissions": {"trusted_tools": [], "denied_tools": [], "allowed_commands": []},
                          "agent_name": None, "goal": None}}), encoding="utf-8")
    lines = [
        {"version": "v1", "kind": "Prompt", "data": {"message_id": "m1", "content": [
            {"kind": "text", "data": "please check zebracornkiro"}]}},
        {"version": "v1", "kind": "AssistantMessage", "data": {"message_id": "m2", "content": [
            {"kind": "thinking", "data": {"text": "secret thoughts"}},
            {"kind": "text", "data": "Running it."},
            {"kind": "toolUse", "data": {"toolUseId": "tooluse_1", "name": "shell",
                                         "input": {"command": "echo hi-kiro", "summary": "say hi"}}}]}},
        {"version": "v1", "kind": "ToolResults", "data": {"content": [
            {"kind": "toolResult", "data": {"toolUseId": "tooluse_1", "status": "success", "content": [
                {"kind": "json", "data": {"exit_status": "0", "stdout": "hi-kiro zebracornkirotool\n", "stderr": ""}}]}}]}},
        {"version": "v1", "kind": "AssistantMessage", "data": {"message_id": "m3", "content": [
            {"kind": "text", "data": "Done: zebracornkiro"}]}},
        {"version": "v1", "kind": "Compaction", "data": {"summary": "zebracorninjected conversation summary",
                                                         "content": [{"kind": "text", "data": "zebracorninjected"}]}},
    ]
    path = root / f"{sid}.jsonl"
    path.write_text("".join(json.dumps(l) + "\n" for l in lines), encoding="utf-8")
    return str(path)
