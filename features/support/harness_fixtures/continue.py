"""Continue (`cn` CLI, npm @continuedev/cli, and the Continue IDE extensions) session parser for navcom.

On disk ($CONTINUE_GLOBAL_DIR, default ~/.continue):
  sessions/<uuid>.json   {sessionId, title, workspaceDirectory, history:[ChatHistoryItem], usage?}
  sessions/sessions.json index [{sessionId, title, dateCreated, workspaceDirectory, messageCount?}]
ChatHistoryItem = {message:{role, content, toolCalls?, toolCallId?}, contextItems, editorState?,
                   toolCallStates?:[{toolCallId, toolCall, status, parsedArgs, output:[{content,name}]}],
                   toolCallState? (older IDE, singular), promptLogs?, conversationSummary?}
The IDE and the CLI share this file layout; the IDE stores content as parts, the CLI as a string.
"""
import importlib.util
import json
import uuid
from pathlib import Path
from urllib.parse import unquote, urlparse

spec = importlib.util.spec_from_file_location("nav", str(__import__("pathlib").Path(__file__).resolve().parents[3] / "navcom.py"))
nav = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nav)

DEFAULT_TITLES = ("", "Untitled Session", "New Session")


def continue_home():
    return nav._env_path("CONTINUE_GLOBAL_DIR") or Path.home() / ".continue"


def continue_roots():
    return [continue_home() / "sessions"]


def continue_list():
    root = continue_roots()[0]
    try:
        paths = [p for p in root.glob("*.json") if p.name != "sessions.json"] if root.is_dir() else []
    except OSError:
        paths = []
    return nav._file_logs(paths, "continue")


def _load(key):
    try:
        data = json.loads(Path(key).read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _args(call):
    fn = (call or {}).get("function") if isinstance(call, dict) else None
    fn = fn if isinstance(fn, dict) else {}
    args = fn.get("arguments")
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except Exception:
            pass
    return fn.get("name"), args


def _state_output(state):
    output = state.get("output")
    if isinstance(output, list):  # ContextItem[]: {content, name, description}
        return "\n".join(o.get("content") for o in output if isinstance(o, dict) and isinstance(o.get("content"), str))
    return output if isinstance(output, str) else ""


def continue_iter(key):
    calls, done, after_summary = {}, set(), False
    for item in _load(key).get("history") or []:
        if not isinstance(item, dict):
            continue
        msg = item.get("message") if isinstance(item.get("message"), dict) else {}
        role = msg.get("role")
        if item.get("conversationSummary") is not None:
            after_summary = True  # compaction summary (model-written context) — injected
            continue
        if role == "user":
            text = nav._text_of(msg.get("content") or "")
            if after_summary and text.strip() == "continue":
                continue  # cn auto-continues after compaction with a synthetic "continue"
            if text.strip():
                yield "user", text
        elif role == "assistant":
            text = nav._text_of(msg.get("content") or "")
            if text.strip():
                yield "assistant", text
            states = item.get("toolCallStates") or ([item["toolCallState"]] if isinstance(item.get("toolCallState"), dict) else [])
            by_id = {s.get("toolCallId"): s for s in states if isinstance(s, dict)}
            for call in msg.get("toolCalls") or [s.get("toolCall") for s in by_id.values()]:
                name, args = _args(call)
                cid = (call or {}).get("id") if isinstance(call, dict) else None
                state = by_id.get(cid) or {}
                if isinstance(state.get("parsedArgs"), dict):
                    args = state["parsedArgs"]
                label_args = args
                if isinstance(args, dict) and not args.get("path") and (args.get("filepath") or args.get("dirPath")):
                    label_args = {**args, "path": args.get("filepath") or args.get("dirPath")}  # Read/builtin_read_file
                calls[cid] = nav._call_label(name, label_args)
                cmd = nav._shell_cmd(name, args)  # cn "Bash"; IDE "builtin_run_terminal_command"
                if cmd:
                    yield "cmd", cmd
                if state:
                    turn = nav.tool_turn(calls[cid], _state_output(state))
                    done.add(cid)
                    if turn:
                        yield turn
        elif role == "tool":  # IDE agent mode also logs results as role=tool items
            if msg.get("toolCallId") not in done:
                turn = nav.tool_turn(calls.get(msg.get("toolCallId"), "tool"), msg.get("content"))
                if turn:
                    yield turn
        # role system (system prompt, slash-command output, compaction notices) and thinking: skipped
        after_summary = False


def continue_project(key):
    ws = _load(key).get("workspaceDirectory") or ""
    if isinstance(ws, str) and ws.startswith("file://"):
        ws = unquote(urlparse(ws).path)
    return ws if isinstance(ws, str) else ""


def continue_title(key):
    title = _load(key).get("title")
    return title if isinstance(title, str) and title not in DEFAULT_TITLES else ""


def continue_fixture(home, cwd):
    sid = str(uuid.uuid4())
    sdir = Path(home) / ".continue" / "sessions"
    sdir.mkdir(parents=True, exist_ok=True)
    args = json.dumps({"command": "echo hi-continue"})
    call = {"id": "call_1", "type": "function", "function": {"name": "Bash", "arguments": args}}
    history = [
        {"message": {"role": "system", "content": "You are an agent in the Continue CLI. zebracorninjected"}, "contextItems": []},
        {"message": {"role": "user", "content": "please check zebracorncontinue"},
         "contextItems": [{"name": "notes.md", "description": "file", "content": "attached zebracorninjected"}],
         "editorState": "please check zebracorncontinue"},
        {"message": {"role": "assistant", "content": "", "toolCalls": [call]}, "contextItems": [],
         "toolCallStates": [{"toolCallId": "call_1", "toolCall": call, "status": "done",
                             "parsedArgs": {"command": "echo hi-continue"},
                             "output": [{"content": "zebracorncontinuetool\n", "name": "Tool Result",
                                         "description": "Tool execution result"}]}]},
        {"message": {"role": "assistant", "content": "Done: zebracorncontinue"}, "contextItems": []},
        {"message": {"role": "assistant", "content": "summary zebracorninjected"}, "contextItems": [],
         "conversationSummary": "summary zebracorninjected"},
        {"message": {"role": "user", "content": "continue"}, "contextItems": []},
        {"message": {"role": "thinking", "content": "zebracorninjected thoughts"}, "contextItems": []},
    ]
    (sdir / f"{sid}.json").write_text(json.dumps(
        {"sessionId": sid, "title": "Untitled Session", "workspaceDirectory": cwd, "history": history}, indent=1))
    index = sdir / "sessions.json"
    try:
        entries = json.loads(index.read_text())
    except Exception:
        entries = []
    entries.append({"sessionId": sid, "title": "Untitled Session", "dateCreated": "1790911752258",
                    "workspaceDirectory": cwd, "messageCount": 2})
    index.write_text(json.dumps(entries, indent=2))
    return str(sdir / f"{sid}.json")
