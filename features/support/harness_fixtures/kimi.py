"""Kimi Code (npm @moonshot-ai/kimi-code, v2 engine) transcripts for navcom, plus legacy Kimi CLI.

$KIMI_CODE_HOME | ~/.kimi-code
  sessions/wd_<slug>_<sha256[:12]>/session_<uuid>/state.json             {cwd, title, agents{…}}
  sessions/wd_…/session_<uuid>/agents/main/wire.jsonl                     main agent
  sessions/wd_…/session_<uuid>/agents/agent-<n>/wire.jsonl                subagents (Agent tool)
wire.jsonl is an append-only event log. The model context is rebuilt from:
  context.append_message      {message: {role, content[], toolCalls[], toolCallId?, origin{kind}}}
                              origin.kind "user" = typed; "injection"/"system_trigger"/… = not typed;
                              "shell_command" = a `!cmd` the user ran (phase input|output)
  context.append_loop_event   {event: content.part{part{type:text|think}} | tool.call{toolCallId,name,args}
                               | tool.result{toolCallId, result{output, isError}}}
`agent.message.appended` events duplicate the same content for live UIs and are ignored.

Legacy Kimi CLI ($KIMI_SHARE_DIR | ~/.kimi): sessions/<md5(workdir)>/<uuid>/context*.jsonl (or a flat
sessions/<md5>/<uuid>.jsonl): OpenAI-style rows {role: user|assistant|tool|_system_prompt|_checkpoint|_usage,
content, tool_calls[{id, function{name, arguments}}], tool_call_id}; workdirs in kimi.json work_dirs[].path.
"""
import hashlib
import html
import importlib.util
import json
import re
from pathlib import Path

spec = importlib.util.spec_from_file_location("nav", str(__import__("pathlib").Path(__file__).resolve().parents[3] / "navcom.py"))
nav = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nav)


def _kimi_home():
    return nav._env_path("KIMI_CODE_HOME") or Path.home() / ".kimi-code"


def _legacy_home():
    return nav._env_path("KIMI_SHARE_DIR") or Path.home() / ".kimi"


def kimi_roots():
    return [_kimi_home() / "sessions", _legacy_home() / "sessions"]


def kimi_list():
    current, legacy = kimi_roots()
    paths = list(current.glob("*/*/agents/*/wire.jsonl")) if current.is_dir() else []
    if legacy.is_dir():
        paths += [p for p in legacy.glob("*/*/context*.jsonl") if re.fullmatch(r"context(_\d+)?\.jsonl", p.name)]
        paths += [p for p in legacy.glob("*/*.jsonl") if re.fullmatch(r"[0-9a-f]{32}", p.parent.name)]
    return nav._file_logs(sorted(set(paths)), "kimi")


def _lines(key):
    try:
        with open(key, "r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                if isinstance(obj, dict):
                    yield obj
    except OSError:
        return


def _parts_text(content, kinds=("text",)):
    if isinstance(content, str):
        return content
    out = []
    for part in content or []:
        if isinstance(part, dict) and part.get("type", "text") in kinds and isinstance(part.get("text"), str):
            out.append(part["text"])
    return "\n".join(t for t in out if t)


def _args(raw):
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except Exception:
            return raw
    return raw


def _message_turns(msg, calls, legacy=False):
    """Turns for one whole message (v2 context.append_message, or a legacy context.jsonl row)."""
    role = msg.get("role")
    origin = (msg.get("origin") or {}).get("kind") if isinstance(msg.get("origin"), dict) else None
    if role == "user":
        text = _parts_text(msg.get("content"))
        if origin == "shell_command":
            m = re.search(r"<bash-input>\n?(.*?)\n?</bash-input>", text, re.S)
            if m:
                cmd = html.unescape(m.group(1)).strip()
                calls["!shell"] = nav._call_label("Bash", {"command": cmd})
                yield "cmd", cmd
            elif "<bash-stdout>" in text:
                out = "\n".join(html.unescape(x) for x in re.findall(r"<bash-std(?:out|err)>(.*?)</bash-std(?:out|err)>", text, re.S))
                turn = nav.tool_turn(calls.get("!shell", "Bash"), out)
                if turn:
                    yield turn
        elif origin == "user" or (legacy and origin is None and not text.lstrip().startswith("<system")):
            if text.strip():
                yield "user", text
    elif role == "assistant":
        text = _parts_text(msg.get("content"))
        if text.strip():
            yield "assistant", text
        for call in msg.get("toolCalls") or msg.get("tool_calls") or []:
            fn = call.get("function") if isinstance(call.get("function"), dict) else call
            args = _args(fn.get("arguments"))
            calls[call.get("id")] = nav._call_label(fn.get("name"), args)
            cmd = nav._shell_cmd(fn.get("name"), args)
            if cmd:
                yield "cmd", cmd
    elif role == "tool":
        output = _parts_text(msg.get("content"))
        if legacy:
            output = re.sub(r"</?system>", "", output)
        turn = nav.tool_turn(calls.get(msg.get("toolCallId") or msg.get("tool_call_id"), "tool"), output)
        if turn:
            yield turn


def kimi_iter(key):
    calls, text, legacy = {}, [], not str(key).endswith("wire.jsonl")
    for obj in _lines(key):
        if legacy:
            yield from _message_turns(obj, calls, legacy=True)
            continue
        kind = obj.get("type")
        event = obj.get("event") if isinstance(obj.get("event"), dict) else {}
        if kind == "context.append_loop_event" and event.get("type") == "content.part":
            part = event.get("part") or {}
            if part.get("type") == "text" and isinstance(part.get("text"), str):
                text.append(part["text"])
            continue
        if kind not in ("context.append_message", "context.append_loop_event"):
            continue
        if text and "\n".join(text).strip():
            yield "assistant", "\n".join(text)
        text = []
        if kind == "context.append_message":
            yield from _message_turns(obj.get("message") or {}, calls)
        elif event.get("type") == "tool.call":
            args = event.get("args")
            calls[event.get("toolCallId")] = nav._call_label(event.get("name"), args)
            cmd = nav._shell_cmd(event.get("name"), args)
            if cmd:
                yield "cmd", cmd
        elif event.get("type") == "tool.result":
            result = event.get("result") or {}
            output = result.get("output")
            output = _parts_text(output) if isinstance(output, list) else output
            if result.get("isError"):
                output = "error\n" + str(output or "")
            turn = nav.tool_turn(calls.get(event.get("toolCallId"), "tool"), output)
            if turn:
                yield turn
    if text and "\n".join(text).strip():
        yield "assistant", "\n".join(text)


def _session_dir(key):
    path = Path(key)
    return path.parents[2] if path.name == "wire.jsonl" else (path.parent if path.name.startswith("context") else None)


def _state(key):
    sdir = _session_dir(key)
    try:
        return json.loads((sdir / "state.json").read_text(encoding="utf-8")) if sdir else {}
    except Exception:
        return {}


def kimi_project(key):
    path = Path(key)
    if path.name == "wire.jsonl":
        state = _state(key)
        if isinstance(state.get("cwd"), str):
            return state["cwd"]
        for obj in _lines(_kimi_home() / "session_index.jsonl"):
            if obj.get("sessionDir") == str(path.parents[2]) and obj.get("workDir"):
                return obj["workDir"]
        return ""
    bucket = path.parent.parent.name if path.name.startswith("context") else path.parent.name
    try:
        work_dirs = json.loads((_legacy_home() / "kimi.json").read_text(encoding="utf-8")).get("work_dirs") or []
    except Exception:
        work_dirs = []
    for wd in work_dirs:
        if isinstance(wd, dict) and hashlib.md5(str(wd.get("path", "")).encode()).hexdigest() == bucket:
            return wd["path"]
    return ""


def kimi_title(key):
    state = _state(key)
    title = state.get("title") or state.get("customTitle") or state.get("custom_title") or ""
    if not title and not str(key).endswith("wire.jsonl") and _session_dir(key):
        try:
            title = json.loads((_session_dir(key) / "metadata.json").read_text(encoding="utf-8")).get("title") or ""
        except Exception:
            pass
    return title if isinstance(title, str) else ""


def kimi_fixture(home, cwd):
    norm = cwd.replace("\\", "/").rstrip("/")
    digest = hashlib.sha256(norm.encode()).hexdigest()[:12]
    slug = re.sub(r"[^a-z0-9._-]+", "-", norm.split("/")[-1].lower()).strip("-")[:40].strip("-")
    slug = slug if slug not in ("", ".", "..") else "workspace"
    sid = "session_00000000-0000-4000-8000-0000000kimi01"
    sdir = Path(home) / ".kimi-code" / "sessions" / f"wd_{slug}_{digest}" / sid
    wire = sdir / "agents" / "main" / "wire.jsonl"
    wire.parent.mkdir(parents=True, exist_ok=True)
    (sdir / "state.json").write_text(json.dumps({
        "id": sid, "version": 2, "cwd": cwd, "title": "Fixture kimi session", "titleKind": "generated",
        "createdAt": 1790000000000, "updatedAt": 1790000001000, "archived": False,
        "agents": {"main": {"homedir": str(wire.parent), "type": "main"}}, "isCustomTitle": False}))
    t = 1790000000000
    msg = lambda m: {"type": "context.append_message", "agentId": "main", "message": m, "time": t}
    loop = lambda e: {"type": "context.append_loop_event", "agentId": "main", "event": e, "time": t}
    user = {"role": "user", "content": [{"type": "text", "text": "please check zebracornkimi"}],
            "toolCalls": [], "origin": {"kind": "user"}}
    rows = [
        {"type": "metadata", "protocol_version": "1.5", "created_at": t},
        {"type": "profile.bind", "agentId": "main", "systemPrompt": "zebracorninjected system prompt"},
        {"type": "turn.prompt", "agentId": "main", "input": user["content"], "origin": {"kind": "user"}},
        msg(user),
        {"message": {"message": user, "meta": {"origin": {"kind": "user"}}}, "type": "agent.message.appended", "kind": "event"},
        msg({"role": "user", "content": [{"type": "text", "text": "<system-reminder>\nzebracorninjected\n</system-reminder>"}],
             "toolCalls": [], "origin": {"kind": "injection", "variant": "date_change"}}),
        loop({"type": "step.begin", "uuid": "s1", "turnId": "0", "step": 1}),
        loop({"type": "content.part", "uuid": "p0", "stepUuid": "s1", "part": {"type": "think", "think": "zebracorninjected thoughts"}}),
        loop({"type": "content.part", "uuid": "p1", "stepUuid": "s1", "part": {"type": "text", "text": "Running it."}}),
        loop({"type": "tool.call", "uuid": "c1", "stepUuid": "s1", "toolCallId": "functions.Bash:0", "name": "Bash",
              "args": {"command": "echo hi-kimi"}}),
        loop({"type": "tool.result", "parentUuid": "c1", "toolCallId": "functions.Bash:0",
              "result": {"output": "zebracornkimitool\n", "durationMs": 3}}),
        loop({"type": "step.end", "uuid": "s1", "finishReason": "tool_use"}),
        loop({"type": "step.begin", "uuid": "s2", "turnId": "0", "step": 2}),
        loop({"type": "content.part", "uuid": "p2", "stepUuid": "s2", "part": {"type": "text", "text": "Done: zebracornkimi"}}),
        loop({"type": "step.end", "uuid": "s2", "finishReason": "end_turn"}),
        {"message": {"message": {"role": "assistant", "content": [{"type": "text", "text": "Done: zebracornkimi"}], "toolCalls": []}},
         "type": "agent.message.appended", "kind": "event"},
        {"type": "turn.ended", "agentId": "main", "turnId": 0, "reason": "completed"},
    ]
    with open(wire, "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")
    with open(Path(home) / ".kimi-code" / "session_index.jsonl", "a", encoding="utf-8") as handle:
        handle.write(json.dumps({"sessionId": sid, "sessionDir": str(sdir), "workDir": cwd}) + "\n")
    return str(wire)


def kimi_legacy_fixture(home, cwd):
    """Legacy Kimi CLI layout (~/.kimi), used only by verify.py."""
    bucket = hashlib.md5(cwd.encode()).hexdigest()
    sdir = Path(home) / ".kimi" / "sessions" / bucket / "11111111-2222-4333-8444-555555555555"
    sdir.mkdir(parents=True, exist_ok=True)
    (Path(home) / ".kimi" / "kimi.json").write_text(json.dumps({"work_dirs": [{"path": cwd, "kaos": "local"}]}))
    (sdir / "state.json").write_text(json.dumps({"custom_title": "Legacy kimi session"}))
    rows = [
        {"role": "_system_prompt", "content": "zebracorninjected system"},
        {"role": "_checkpoint", "id": 0},
        {"role": "user", "content": "please check zebracornkimi"},
        {"role": "user", "content": [{"type": "text", "text": "<system>zebracorninjected</system>"}]},
        {"role": "assistant", "content": [{"type": "think", "think": "zebracorninjected"}, {"type": "text", "text": "Running it."}],
         "tool_calls": [{"type": "function", "id": "Shell:0", "function": {"name": "Shell", "arguments": "{\"command\": \"echo hi-kimi\"}"}}]},
        {"role": "tool", "tool_call_id": "Shell:0", "content": [{"type": "text", "text": "<system>Command executed successfully.</system>"},
                                                                {"type": "text", "text": "zebracornkimitool"}]},
        {"role": "assistant", "content": "Done: zebracornkimi"},
        {"role": "_usage", "token_count": 123},
    ]
    with open(sdir / "context.jsonl", "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")
    return str(sdir / "context.jsonl")
