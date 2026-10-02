"""Qwen Code (npm @qwen-code/qwen-code) transcripts for navcom.

$QWEN_RUNTIME_DIR | $QWEN_HOME | ~/.qwen
  projects/<cwd with [^a-zA-Z0-9] -> '-'>/chats/<sessionId>.jsonl            main sessions
  projects/<sanitized cwd>/subagents/<sessionId>/agent-<agentId>.jsonl       subagent sidechains

One JSON record per line: {uuid, parentUuid, sessionId, type: user|assistant|tool_result|system,
subtype?, provenance?, cwd, message: {role, parts[]}} with Gemini-style parts
(text / thought / functionCall{id,name,args} / functionResponse{id,name,response}).
/rewind leaves dead branches in the file; Qwen rebuilds a conversation by walking parentUuid back
from the last conversation record, so we index exactly that chain.
"""
import importlib.util
import json
import os
from pathlib import Path

spec = importlib.util.spec_from_file_location("nav", str(__import__("pathlib").Path(__file__).resolve().parents[3] / "navcom.py"))
nav = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nav)

_HOOK_CONTEXT_OPEN = "<qwen:user-prompt-submit-context>"
_REFERENCED_FILES = "\n--- Content from referenced files ---"
_NON_CONVERSATION = {"session_sources_snapshot", "session_artifact_event", "session_artifact_snapshot",
                     "managed_session_header_v1", "managed_session_event_v1", "managed_session_commit_v1"}


def qwen_roots():
    roots = []
    for root in (nav._env_path("QWEN_RUNTIME_DIR"), nav._env_path("QWEN_HOME"), Path.home() / ".qwen"):
        if root and root / "projects" not in roots:
            roots.append(root / "projects")
    return roots


def qwen_list():
    paths = []
    for root in qwen_roots():
        if root.is_dir():
            paths += list(root.glob("*/chats/*.jsonl")) + list(root.glob("*/subagents/*/agent-*.jsonl"))
    return nav._file_logs(sorted(set(paths)), "qwen")


def _records(key):
    out = []
    try:
        with open(key, "r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                if isinstance(obj, dict) and obj.get("uuid"):
                    out.append(obj)
    except OSError:
        pass
    return out


def _live_chain(records):
    """Records on the surviving branch, oldest first (fragments sharing a uuid are merged)."""
    by_uuid = {}
    for rec in records:
        first = by_uuid.get(rec["uuid"])
        if first is None:
            by_uuid[rec["uuid"]] = dict(rec)
        elif isinstance(rec.get("message"), dict):
            msg = dict(first.get("message") or {"role": rec["message"].get("role")})
            msg["parts"] = list(msg.get("parts") or []) + list(rec["message"].get("parts") or [])
            first["message"] = msg
    leaf = next((r["uuid"] for r in reversed(records)
                 if not (r.get("type") == "system" and r.get("subtype") in _NON_CONVERSATION)), None)
    chain, seen = [], set()
    while leaf and leaf not in seen and leaf in by_uuid:
        seen.add(leaf)
        chain.append(by_uuid[leaf])
        leaf = by_uuid[leaf].get("parentUuid")
    return chain[::-1]


def _user_text(rec):
    payload = rec.get("systemPayload") if isinstance(rec.get("systemPayload"), dict) else {}
    if isinstance(payload.get("displayText"), str) and payload["displayText"].strip():
        return payload["displayText"]
    texts = [p["text"] for p in (rec.get("message") or {}).get("parts") or []
             if isinstance(p, dict) and isinstance(p.get("text"), str) and not p.get("thought")]
    texts = [t for t in texts if not t.strip().startswith(_HOOK_CONTEXT_OPEN)]
    return "\n".join(texts).split(_REFERENCED_FILES, 1)[0]


def qwen_iter(key):
    calls = {}
    for rec in _live_chain(_records(key)):
        kind, parts = rec.get("type"), (rec.get("message") or {}).get("parts") or []
        if kind == "user":
            typed = rec.get("provenance", "real_user") == "real_user" and rec.get("subtype") in (None, "mid_turn_user_message")
            if typed and not rec.get("isSidechain"):  # sidechain prompts are written by the parent agent
                text = _user_text(rec)
                if text.strip():
                    yield "user", text
        elif kind == "assistant":
            text = []
            for part in parts:
                if not isinstance(part, dict) or part.get("thought"):
                    continue
                if isinstance(part.get("text"), str):
                    text.append(part["text"])
                call = part.get("functionCall")
                if isinstance(call, dict):
                    if text and "".join(text).strip():
                        yield "assistant", "".join(text)
                    text = []
                    args = call.get("args")
                    calls[call.get("id")] = nav._call_label(call.get("name"), args)
                    cmd = nav._shell_cmd(call.get("name"), args)
                    if cmd:
                        yield "cmd", cmd
            if "".join(text).strip():
                yield "assistant", "".join(text)
        elif kind == "tool_result":
            for part in parts:
                resp = part.get("functionResponse") if isinstance(part, dict) else None
                if not isinstance(resp, dict):
                    continue
                body = resp.get("response")
                if isinstance(body, dict):
                    output = body.get("output") if body.get("output") is not None else body.get("error")
                    if output is None:
                        output = body
                    elif body.get("error") and body.get("output") is not None:
                        output = f"error\n{body['error']}\n{output}"
                else:
                    output = body
                label = calls.get(resp.get("id")) or resp.get("name") or "tool"
                turn = nav.tool_turn(label, output)
                if turn:
                    yield turn


def qwen_project(key):
    for rec in _records(key)[:50]:
        if isinstance(rec.get("cwd"), str) and rec["cwd"]:
            return rec["cwd"]
    return ""


def qwen_title(key):
    title = ""
    for rec in _records(key):
        if rec.get("type") == "system" and rec.get("subtype") == "custom_title":
            title = ((rec.get("systemPayload") or {}).get("customTitle") or title)
    if not title and "/subagents/" in str(key):
        try:
            title = json.loads(Path(str(key)[:-len(".jsonl")] + ".meta.json").read_text()).get("description") or ""
        except Exception:
            pass
    return title


def qwen_retention():
    home = nav._env_path("QWEN_HOME") or Path.home() / ".qwen"
    return {
        "settings_path": str(home / "settings.json"),
        "key_path": "general.cleanupPeriodDays",
        "never_delete_value": 36500,
        "default_days": 30,
        "note": "Qwen Code's daily housekeeping deletes subagent transcripts (projects/*/subagents/<session>/), "
                "/rewind file-history backups and debug logs older than general.cleanupPeriodDays (default 30). "
                "Main chats/*.jsonl are never auto-deleted. There is no 'off' value (0 means ~1 hour), "
                "so set a very large number of days.",
    }


def _sanitize(cwd):
    return "".join(c if c.isalnum() and c.isascii() else "-" for c in cwd)


def qwen_fixture(home, cwd):
    sid = "0f0e0d0c-0000-4000-8000-00000000qwen"
    path = Path(home) / ".qwen" / "projects" / _sanitize(cwd) / "chats" / f"{sid}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    base = {"sessionId": sid, "timestamp": "2026-10-01T00:00:00.000Z", "cwd": cwd, "version": "0.24.7"}
    rows = [
        {"uuid": "u1", "parentUuid": None, "type": "user", "provenance": "real_user",
         "message": {"role": "user", "parts": [{"text": "please check zebracornqwen"},
                                               {"text": _HOOK_CONTEXT_OPEN + "\nzebracorninjected hook\n</qwen:user-prompt-submit-context>"}]}},
        {"uuid": "s1", "parentUuid": "u1", "type": "system", "subtype": "ui_telemetry", "provenance": "system",
         "systemPayload": {"uiEvent": {"response_text": "zebracorninjected telemetry"}}},
        {"uuid": "n1", "parentUuid": "s1", "type": "user", "subtype": "notification", "provenance": "system",
         "message": {"role": "user", "parts": [{"text": "<system-reminder>zebracorninjected</system-reminder>"}]}},
        {"uuid": "a1", "parentUuid": "n1", "type": "assistant", "provenance": "assistant_output", "model": "m",
         "message": {"role": "model", "parts": [{"text": "zebracorninjected thinking", "thought": True},
                                                {"text": "Running it."},
                                                {"functionCall": {"id": "c1", "name": "run_shell_command",
                                                                  "args": {"command": "echo hi-qwen"}}}]}},
        {"uuid": "t1", "parentUuid": "a1", "type": "tool_result", "provenance": "tool_result",
         "message": {"role": "user", "parts": [{"functionResponse": {"id": "c1", "name": "run_shell_command",
                                                                     "response": {"output": "Command: echo hi-qwen\nOutput: zebracornqwentool\nExit Code: 0"}}}]}},
        # a rewound turn: written, then abandoned by /rewind (its parent chain is dropped)
        {"uuid": "d1", "parentUuid": "t1", "type": "assistant", "provenance": "assistant_output",
         "message": {"role": "model", "parts": [{"text": "zebracorndeadbranch"}]}},
        {"uuid": "r1", "parentUuid": "t1", "type": "system", "subtype": "rewind", "systemPayload": {}},
        {"uuid": "a2", "parentUuid": "r1", "type": "assistant", "provenance": "assistant_output", "model": "m",
         "message": {"role": "model", "parts": [{"text": "Done: zebracornqwen"}]}},
        {"uuid": "ti", "parentUuid": "a2", "type": "system", "subtype": "custom_title",
         "systemPayload": {"customTitle": "Fixture qwen session", "titleSource": "auto"}},
    ]
    with open(path, "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps({**base, **row}) + "\n")
    return str(path)
