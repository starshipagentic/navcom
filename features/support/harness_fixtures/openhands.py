"""OpenHands CLI (V1 / software-agent-sdk) ─ $OPENHANDS_CONVERSATIONS_DIR
(default $OPENHANDS_PERSISTENCE_DIR/conversations = ~/.openhands/conversations)

  <conv hex>/base_state.json                        agent config + workspace.working_dir
  <conv hex>/events/event-NNNNN-<uuid>.json         one JSON object per event, "kind" discriminator
  <conv hex>/subagents/<hex>/{base_state.json,events/}  task/delegate sub-conversations

Kinds: SystemPromptEvent (skip) · MessageEvent (source user|agent|environment; llm_message.content parts;
extended_content = injected agent context, skipped) · ActionEvent (tool_name, action{…}, thought = visible text,
reasoning_content skipped; FinishAction.message = final reply) · ObservationEvent (observation.content parts) ·
UserRejectObservation · AgentErrorEvent · Condensation*/ConversationStateUpdate/Pause/Token… (skip).
The key is the conversation directory.
"""
import importlib.util
import json
import os
import re
from pathlib import Path

spec = importlib.util.spec_from_file_location("nav", str(__import__("pathlib").Path(__file__).resolve().parents[3] / "navcom.py"))
nav = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nav)


def openhands_roots():
    explicit = nav._env_path("OPENHANDS_CONVERSATIONS_DIR")
    if explicit:
        return [explicit]
    return [(nav._env_path("OPENHANDS_PERSISTENCE_DIR") or Path.home() / ".openhands") / "conversations"]


def _event_files(conv):
    def idx(p):
        m = re.match(r"event-(\d+)-", p.name)
        return int(m.group(1)) if m else 0
    try:
        return sorted(Path(conv, "events").glob("event-*.json"), key=idx)
    except OSError:
        return []


def openhands_list():
    logs = []
    for root in openhands_roots():
        if not root.is_dir():
            continue
        for conv in list(root.glob("*")) + list(root.glob("*/subagents/*")):
            events = conv / "events"
            if not events.is_dir():
                continue
            files = _event_files(conv)
            if not files:
                continue
            try:
                mtime = max([events.stat().st_mtime] + [f.stat().st_mtime for f in files[-3:]])
            except OSError:
                continue
            logs.append((str(conv), mtime, len(files), "openhands"))
    return logs


# Messages the SDK itself sends with source="user" (response_dispatch nudge, critic refinement).
_NUDGES = ("Your last response did not include a function call or a message",
           "The task appears incomplete (iteration ")


def _parts_text(parts):
    return nav._text_of(parts if isinstance(parts, list) else [parts] if parts else [])


def _args(event):
    action = event.get("action")
    if isinstance(action, dict):
        return {k: v for k, v in action.items() if k != "kind"}
    raw = (event.get("tool_call") or {}).get("arguments")
    try:
        return json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        return raw


def openhands_iter(key):
    sub = "/subagents/" in str(key)
    calls = {}
    for path in _event_files(key):
        try:
            ev = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        kind = ev.get("kind")
        if kind == "MessageEvent":
            msg = ev.get("llm_message") or {}
            text = _parts_text(msg.get("content"))  # extended_content (skills/hook context) deliberately ignored
            if not text.strip():
                continue
            if ev.get("source") == "user" and msg.get("role") == "user":
                if not sub and not ev.get("sender") and not text.startswith(_NUDGES):
                    yield "user", text
            elif ev.get("source") == "agent" and msg.get("role") == "assistant":
                yield "assistant", text
        elif kind == "ActionEvent":
            thought = _parts_text(ev.get("thought"))
            if thought.strip():
                yield "assistant", thought
            name, args = ev.get("tool_name"), _args(ev)
            action = ev.get("action") or {}
            if action.get("kind") == "FinishAction" or name == "finish":
                if isinstance(args, dict) and str(args.get("message") or "").strip():
                    yield "assistant", str(args["message"])
                continue
            if name == "think":
                continue  # the think tool is reasoning
            label_args = args
            if isinstance(args, dict) and args.get("path") and not nav._is_shell_tool(name):
                label_args = {"path": f"{args.get('command', '')} {args['path']}".strip()}
            calls[ev.get("tool_call_id")] = nav._call_label(name, label_args)
            cmd = nav._shell_cmd(name, args)
            if cmd:
                yield "cmd", cmd
        elif kind in ("ObservationEvent", "UserRejectObservation", "AgentErrorEvent"):
            if ev.get("tool_name") in ("finish", "think"):
                continue
            obs = ev.get("observation") or {}
            if kind == "ObservationEvent":
                output = _parts_text(obs.get("content"))
                code = obs.get("exit_code")
                if obs.get("is_error") or code not in (None, 0, -1):
                    output = f"exit {code}\n{output}" if code not in (None, 0) else "error\n" + output
            elif kind == "UserRejectObservation":
                output = "rejected: " + str(ev.get("rejection_reason") or "")
            else:
                output = "error\n" + str(ev.get("error") or "")
            turn = nav.tool_turn(calls.get(ev.get("tool_call_id"), ev.get("tool_name") or "tool"), output)
            if turn:
                yield turn


def _base_state(key):
    try:
        with open(Path(key) / "base_state.json", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def openhands_project(key):
    ws = _base_state(key).get("workspace") or {}
    if isinstance(ws.get("working_dir"), str):
        return ws["working_dir"]
    for path in _event_files(key):  # fall back to the first terminal observation's cwd
        try:
            ev = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        wd = ((ev.get("observation") or {}).get("metadata") or {}).get("working_dir")
        if isinstance(wd, str) and wd:
            return wd
    return ""


def openhands_title(key):
    # The CLI stores no title; it shows the first user prompt (conversations/store/local.py).
    tags = _base_state(key).get("tags") or {}
    return str(tags.get("title") or "") if isinstance(tags, dict) else ""


def openhands_fixture(home, cwd):
    conv = Path(home) / ".openhands" / "conversations" / "0123456789abcdef0123456789abcdef"
    events = conv / "events"
    events.mkdir(parents=True, exist_ok=True)
    (conv / "base_state.json").write_text(json.dumps({
        "id": "01234567-89ab-cdef-0123-456789abcdef", "workspace": {"working_dir": cwd, "kind": "LocalWorkspace"},
        "persistence_dir": str(conv), "execution_status": "finished", "tags": {}}), encoding="utf-8")
    ts = "2026-10-01T12:00:0{}.000000"

    def text(t):
        return [{"cache_prompt": False, "type": "text", "text": t}]
    evs = [
        {"source": "agent", "system_prompt": {"type": "text", "text": "You are OpenHands agent zebracorninjected"},
         "tools": [], "kind": "SystemPromptEvent"},
        {"source": "user", "llm_message": {"role": "user", "content": text("run it zebracornopenhands"), "thinking_blocks": []},
         "activated_skills": [], "extended_content": text("<EXTRA_INFO>skill context zebracorninjected</EXTRA_INFO>"),
         "kind": "MessageEvent"},
        {"source": "agent", "thought": [], "reasoning_content": "thinking zebracorninjected", "thinking_blocks": [],
         "action": {"command": "echo hi-openhands", "is_input": False, "reset": False, "kind": "TerminalAction"},
         "tool_name": "terminal", "tool_call_id": "call_1",
         "tool_call": {"id": "call_1", "name": "terminal", "arguments": json.dumps({"command": "echo hi-openhands"})},
         "security_risk": "LOW", "kind": "ActionEvent"},
        {"source": "environment", "tool_name": "terminal", "tool_call_id": "call_1",
         "observation": {"content": text("hi-openhands zebracornopenhandstool"), "is_error": False,
                         "command": "echo hi-openhands", "exit_code": 0,
                         "metadata": {"exit_code": 0, "working_dir": cwd}, "kind": "TerminalObservation"},
         "kind": "ObservationEvent"},
        {"source": "user", "llm_message": {"role": "user", "content": text(
            "Your last response did not include a function call or a message. Please use a tool to proceed "
            "with the task. zebracorninjected")}, "kind": "MessageEvent"},
        {"source": "agent", "llm_message": {"role": "assistant", "content": text("done zebracornopenhands"),
                                            "reasoning_content": "zebracorninjected"}, "kind": "MessageEvent"},
    ]
    for i, ev in enumerate(evs):
        eid = f"00000000-0000-4000-8000-00000000000{i}"
        (events / f"event-{i:05d}-{eid}.json").write_text(
            json.dumps({"id": eid, "timestamp": ts.format(i), **ev}), encoding="utf-8")
    return str(conv)
