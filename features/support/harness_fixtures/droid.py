"""Factory Droid CLI ─ $FACTORY_HOME_OVERRIDE|~ /.factory/sessions/<-cwd-slug>/<uuid>.jsonl

Line 1 is {"type":"session_start", id, title, cwd, owner, version:2, ...}; then
{"type":"message", id, parentId, timestamp, seq, message:{role, content[...]}} where content is
Anthropic-style blocks: text | thinking | redacted_thinking | image | document |
tool_use{id,name,input} | tool_result{tool_use_id,content,is_error}. Tool results ride in
role:"user" messages. Injected context: message ids starting "context-" (the per-session
<system-reminder> tool catalog / env block) or "__internal__system-reminder__", visibility
"llm_only" / hiddenFromUserViews, role "system", hook messages. Other line types
(agent_turn_outcome, todo_state, compaction_state, ...) carry no typed text.
The shell tool is "Execute" {command, summary, riskLevel}.
"""
import importlib.util
import json
import os
import re
from pathlib import Path

spec = importlib.util.spec_from_file_location("nav", str(__import__("pathlib").Path(__file__).resolve().parents[3] / "navcom.py"))
nav = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nav)

_DROID_INJECTED_IDS = ("context-", "__internal__system-reminder__")
_DROID_REMINDER_RE = re.compile(r"<(system-reminder|system-notification)>[\s\S]*?</\1>", re.I)


def droid_roots():
    home = nav._env_path("FACTORY_HOME_OVERRIDE") or Path.home()
    return [home / ".factory" / "sessions"]


def droid_list():
    paths = []
    for root in droid_roots():
        if root.is_dir():
            paths.extend(root.glob("*.jsonl"))       # flat / legacy layout
            paths.extend(root.glob("*/*.jsonl"))     # <cwd-slug>/<uuid>.jsonl
    return nav._file_logs(sorted(set(paths)), "droid")


def _droid_lines(key):
    try:
        handle = open(key, "r", encoding="utf-8", errors="replace")
    except OSError:
        return
    with handle:
        for line in handle:
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if isinstance(obj, dict):
                yield obj


def _droid_header(key):
    for obj in _droid_lines(key):
        return obj if obj.get("type") == "session_start" else {}
    return {}


def _droid_injected(obj, msg):
    if str(obj.get("id") or "").startswith(_DROID_INJECTED_IDS):
        return True
    if msg.get("role") == "system" or msg.get("hookEventName"):
        return True
    return msg.get("visibility") == "llm_only" or msg.get("hiddenFromUserViews") is True


def droid_iter(key):
    calls = {}
    for obj in _droid_lines(key):
        if obj.get("type") != "message":
            continue
        msg = obj.get("message") or {}
        role, content = msg.get("role"), msg.get("content")
        if isinstance(content, str):
            content = [{"type": "text", "text": content}]
        if not isinstance(content, list):
            continue
        injected = _droid_injected(obj, msg)
        for block in content:
            if not isinstance(block, dict):
                continue
            kind = block.get("type")
            if kind == "text" and not injected and role in ("user", "assistant"):
                text = block.get("text") or ""
                if role == "user":
                    text = _DROID_REMINDER_RE.sub("", text).strip()
                if text.strip():
                    yield role, text
            elif kind == "tool_use":
                args = block.get("input")
                calls[block.get("id")] = nav._call_label(block.get("name"), args)
                cmd = nav._shell_cmd(block.get("name"), args)
                if cmd is None and block.get("name") == "Execute" and isinstance(args, dict):
                    cmd = args.get("command")
                if cmd:
                    yield "cmd", cmd
            elif kind == "tool_result":
                output = block.get("content")
                if block.get("is_error") or block.get("isError"):
                    output = "error\n" + (nav._text_of(output) if isinstance(output, list) else str(output or ""))
                turn = nav.tool_turn(calls.get(block.get("tool_use_id") or block.get("toolUseId"), "tool"), output)
                if turn:
                    yield turn


def droid_project(key):
    cwd = _droid_header(key).get("cwd")
    return cwd if isinstance(cwd, str) else ""


def droid_title(key):
    title = _droid_header(key).get("title")
    return title if isinstance(title, str) else ""


def droid_fixture(home, cwd):
    sid = "0b5e1f0e-1111-4222-8333-944455556666"
    slug = cwd.replace("/", "-")
    path = Path(home) / ".factory" / "sessions" / slug / f"{sid}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    ts = "2026-10-02T03:27:35.671Z"
    lines = [
        {"type": "session_start", "id": sid, "title": "zebracorndroid fixture", "owner": "t", "version": 2,
         "cwd": cwd, "hostId": "84ca2682-0000-0000-0000-000000000000", "isSessionTitleManuallySet": False},
        {"type": "message", "id": "context-u1", "timestamp": ts, "message": {"role": "user", "content": [
            {"type": "text", "text": "<system-reminder>\nUnified tool catalog: zebracorninjected\n</system-reminder>"}]}},
        {"type": "message", "id": "u1", "parentId": "context-u1", "timestamp": ts, "seq": 1, "message": {
            "role": "user", "content": [{"type": "text", "text": "please run it zebracorndroid"}],
            "interactionMode": "auto"}},
        {"type": "message", "id": "a1", "parentId": "u1", "timestamp": ts, "seq": 2, "message": {
            "role": "assistant", "content": [
                {"type": "thinking", "thinking": "secret thoughts zebracornthinking", "signature": "x"},
                {"type": "text", "text": "Running it."},
                {"type": "tool_use", "id": "call_1", "name": "Execute",
                 "input": {"summary": "echo", "command": "echo hi-droid", "riskLevel": "low"}}],
            "modelId": "custom:ORDeepSeek-0"}},
        {"type": "message", "id": "r1", "parentId": "a1", "timestamp": ts, "seq": 3, "message": {
            "role": "user", "content": [{"type": "tool_result", "tool_use_id": "call_1", "is_error": False,
                                         "content": "hi-droid zebracorndroidtool\n\n\n[Process exited with code 0]"}]}},
        {"type": "message", "id": "a2", "parentId": "r1", "timestamp": ts, "seq": 4, "message": {
            "role": "assistant", "content": [{"type": "text", "text": "Done: zebracorndroid"}]}},
        {"type": "agent_turn_outcome", "turnId": "u1", "reason": "completed", "resultKind": "text"},
    ]
    path.write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")
    return str(path)
