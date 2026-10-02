"""GitHub Copilot CLI (npm @github/copilot) session parser for navcom.

On disk ($COPILOT_HOME, default ~/.copilot):
  session-state/<uuid>/events.jsonl   one event per line {type, data, id, parentId, timestamp}
  session-state/<uuid>/workspace.yaml id, cwd, name, summary, user_named, created_at, updated_at
  session-state/<uuid>.jsonl          older flat layout (same events, no workspace.yaml)
  history-session-state/*.json        oldest layout {sessionId, chatMessages:[OpenAI-style messages]}
  session-store.db                    derived SQLite/FTS5 index (ignored)
"""
import importlib.util
import json
import re
import uuid
from pathlib import Path

spec = importlib.util.spec_from_file_location("nav", str(__import__("pathlib").Path(__file__).resolve().parents[3] / "navcom.py"))
nav = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nav)


def copilot_home():
    return nav._env_path("COPILOT_HOME") or Path.home() / ".copilot"


def copilot_roots():
    home = copilot_home()
    return [home / "session-state", home / "history-session-state"]


def copilot_list():
    state, legacy = copilot_roots()
    paths = []
    try:
        if state.is_dir():
            paths += list(state.glob("*/events.jsonl")) + list(state.glob("*.jsonl"))
        if legacy.is_dir():
            paths += list(legacy.glob("*.json"))
    except OSError:
        pass
    return nav._file_logs(paths, "copilot")


def _json_args(args):
    if isinstance(args, str):
        try:
            return json.loads(args)
        except Exception:
            return args
    return args


def _copilot_events(key):
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
                yield obj.get("type"), obj.get("data") if isinstance(obj.get("data"), dict) else {}


_SHELL_TAIL_RE = re.compile(r"\n?<shellId: [^>]*? exit code (-?\d+)>\s*$")


def _copilot_output(data, tool=""):
    result = data.get("result") if isinstance(data.get("result"), dict) else {}
    output = result.get("content") or ""
    detailed = result.get("detailedContent")
    # detailedContent carries full diffs for edit tools; for view it re-renders the file as a diff
    if isinstance(detailed, str) and detailed.strip() and (not output or tool not in ("view", "read", "glob", "grep")):
        output = detailed
    if not output and isinstance(result.get("contents"), list):
        output = nav._text_of(result["contents"])
    if isinstance(output, str):  # bash results end with "<shellId: 0 completed with exit code N>"
        tail = _SHELL_TAIL_RE.search(output)
        if tail:
            output = (f"exit {tail.group(1)}\n" if tail.group(1) != "0" else "") + output[:tail.start()]
    if data.get("success") is False:
        error = data.get("error") if isinstance(data.get("error"), dict) else {}
        output = "error\n" + "\n".join(t for t in (error.get("message"), output) if isinstance(t, str) and t)
    return output


def copilot_iter(key):
    if key.endswith(".json"):
        yield from _copilot_legacy_iter(key)
        return
    calls, names = {}, {}
    for kind, data in _copilot_events(key):
        if kind == "user.message":
            source = data.get("source")
            if (source and source != "user") or data.get("isAutopilotContinuation"):
                continue  # skill injections, inter-agent prompts, autopilot "continue" nudges
            text = data.get("content")  # 'transformedContent' adds <current_datetime> etc. — not typed
            if isinstance(text, str) and text.strip():
                yield "user", text
        elif kind == "assistant.message":
            text = data.get("content")  # reasoningText / encryptedContent are thinking — skipped
            if isinstance(text, str) and text.strip():
                yield "assistant", text
            for req in data.get("toolRequests") or []:
                if isinstance(req, dict):
                    calls[req.get("toolCallId")] = nav._call_label(req.get("name"), _json_args(req.get("arguments")))
        elif kind == "tool.execution_start":
            args = _json_args(data.get("arguments"))
            calls[data.get("toolCallId")] = nav._call_label(data.get("toolName"), args)
            names[data.get("toolCallId")] = data.get("toolName") or ""
            cmd = nav._shell_cmd(data.get("toolName"), args)  # bash / powershell; write_bash has no command
            if cmd:
                yield "cmd", cmd
        elif kind == "tool.execution_complete":
            turn = nav.tool_turn(calls.get(data.get("toolCallId"), "tool"),
                                 _copilot_output(data, names.get(data.get("toolCallId"), "")))
            if turn:
                yield turn
        # system.message (system prompt), system.notification, skill.invoked, session.*, hook.*,
        # assistant.reasoning, subagent.* and the rest are injected/bookkeeping: skipped.


_DATETIME_RE = re.compile(r"^\s*<current_datetime>.*?</current_datetime>\s*", re.S)


def _copilot_legacy_iter(key):
    """history-session-state/*.json (Copilot CLI 0.0.x): OpenAI-style chatMessages. Unverified on disk."""
    try:
        data = json.loads(Path(key).read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return
    calls = {}
    for msg in (data.get("chatMessages") if isinstance(data, dict) else None) or []:
        if not isinstance(msg, dict):
            continue
        role, text = msg.get("role"), nav._text_of(msg.get("content") or "")
        if role == "user":
            text = _DATETIME_RE.sub("", text)
            if text.strip() and not text.lstrip().startswith("<reminder>"):
                yield "user", text
        elif role == "assistant":
            if text.strip():
                yield "assistant", text
            for call in msg.get("tool_calls") or []:
                fn = (call or {}).get("function") or {}
                args = _json_args(fn.get("arguments"))
                calls[call.get("id")] = nav._call_label(fn.get("name"), args)
                cmd = nav._shell_cmd(fn.get("name"), args)
                if cmd:
                    yield "cmd", cmd
        elif role == "tool":
            turn = nav.tool_turn(calls.get(msg.get("tool_call_id"), "tool"), msg.get("content"))
            if turn:
                yield turn


def _copilot_workspace(key):
    """workspace.yaml is flat `key: value` YAML; parse the scalars we need without a YAML lib."""
    out = {}
    try:
        lines = (Path(key).parent / "workspace.yaml").read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return out
    for line in lines:
        m = re.match(r"^([A-Za-z_]+):\s?(.*)$", line)
        if not m:
            continue
        value = m.group(2).strip()
        if len(value) >= 2 and value[0] == value[-1] == "'":
            value = value[1:-1].replace("''", "'")
        elif len(value) >= 2 and value[0] == value[-1] == '"':
            try:
                value = json.loads(value)
            except Exception:
                value = value[1:-1]
        out[m.group(1)] = value
    return out


def copilot_project(key):
    if key.endswith("events.jsonl"):
        cwd = _copilot_workspace(key).get("cwd")
        if cwd:
            return cwd
    for kind, data in _copilot_events(key) if key.endswith(".jsonl") else []:
        if kind in ("session.start", "session.resume"):
            ctx = data.get("context") if isinstance(data.get("context"), dict) else {}
            if isinstance(ctx.get("cwd"), str):
                return ctx["cwd"]
    return ""


def copilot_title(key):
    if not key.endswith(".jsonl"):
        return ""
    title = ""
    for kind, data in _copilot_events(key):
        if kind == "session.title_changed" and isinstance(data.get("title"), str):
            title = data["title"]
    if title:
        return title
    ws = _copilot_workspace(key) if key.endswith("events.jsonl") else {}
    if ws.get("user_named") == "true" and ws.get("name"):
        return ws["name"]
    return ws.get("summary") or ws.get("name") or ""


def copilot_fixture(home, cwd):
    sid = str(uuid.uuid4())
    sdir = Path(home) / ".copilot" / "session-state" / sid
    sdir.mkdir(parents=True, exist_ok=True)
    ts = "2026-10-02T03:25:21.434Z"
    (sdir / "workspace.yaml").write_text(
        f"id: {sid}\ncwd: {cwd}\nclient_name: github/cli\nname: 'fixture zebracorncopilot'\n"
        f"user_named: false\nsummary_count: 0\nfork_count: 0\ncreated_at: {ts}\nupdated_at: {ts}\n")
    events = [
        ("session.start", {"sessionId": sid, "version": 1, "producer": "copilot-agent", "copilotVersion": "1.0.91",
                           "startTime": ts, "selectedModel": "fixture-model", "context": {"cwd": cwd}}),
        ("user.message", {"content": "please check zebracorncopilot",
                          "transformedContent": "<current_datetime>2026-10-01</current_datetime>\n\nzebracorninjected",
                          "messageId": "m1", "interactionId": "i1", "turnId": "0"}),
        ("system.message", {"role": "system", "content": "You are the GitHub Copilot CLI. zebracorninjected"}),
        ("user.message", {"content": "skill body zebracorninjected", "source": "skill-pdf", "messageId": "m2"}),
        ("assistant.turn_start", {"turnId": "0", "interactionId": "i1"}),
        ("assistant.message", {"messageId": "a1", "content": "Running it for zebracorncopilot.",
                               "reasoningText": "thinking zebracorninjected",
                               "toolRequests": [{"toolCallId": "call_1", "name": "bash", "type": "function",
                                                 "arguments": {"command": "echo hi-copilot", "description": "say hi"}}]}),
        ("tool.execution_start", {"toolCallId": "call_1", "toolName": "bash",
                                  "arguments": {"command": "echo hi-copilot", "description": "say hi"}}),
        ("tool.execution_complete", {"toolCallId": "call_1", "success": True,
                                     "result": {"content": "zebracorncopilottool\n<shellId: 0 completed with exit code 0>"}}),
        ("assistant.turn_end", {"turnId": "0"}),
        ("session.shutdown", {"shutdownType": "routine"}),
    ]
    with open(sdir / "events.jsonl", "w", encoding="utf-8") as fh:
        parent = None
        for i, (kind, data) in enumerate(events):
            eid = str(uuid.uuid4())
            fh.write(json.dumps({"type": kind, "data": data, "id": eid, "timestamp": ts, "parentId": parent}) + "\n")
            parent = eid
    return str(sdir / "events.jsonl")
