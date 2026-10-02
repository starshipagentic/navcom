"""Augment Code CLI `auggie` (npm @augmentcode/auggie) — one JSON file per session.

Store: <augmentCacheDir>/sessions/<conversationId>.json, augmentCacheDir = ~/.augment (only override is the
--augment-cache-dir flag; no env var). Siblings `<id>-backup<N>.json` (pre-rewind backups) and
`<id>.json.<ms>.tmp` (atomic-write temp) are not sessions.

File (SessionManager.saveSession in augment.mjs 0.36.0):
  {sessionId, created, modified, title?, customTitle?, workspaceId?, parentConversationId?,
   agentState{userGuidelines, workspaceGuidelines, modelId, userEmail, agentPersonaId},
   chatHistory: [{exchange{request_message, response_text, request_id, request_nodes[], response_nodes[]},
                  completed, sequenceId, finishedAt, isHistorySummary, source}]}
  request_nodes  type 0 text_node{content} | 1 tool_result_node{tool_use_id, content, is_error, content_nodes}
                 | 2 image | 4 ide_state_node{workspace_folders[{repository_root, folder_root}], current_terminal}
                 | 10 history_summary_node (compaction)
  response_nodes type 0 {content} text | 5 tool_use{tool_use_id, tool_name, input_json} | 8 thinking | ...
  Shell tool: tool_name "launch-process", input {command, wait, max_wait_seconds, cwd}.

Mapping: request_message -> user (exchanges that are history summaries are injected, skipped);
tool_result_node -> tool (results for the previous exchange's tool_use); response_text -> assistant;
tool_use launch-process -> cmd. agentState guidelines = injected rules, never indexed.
"""
import importlib.util
import json
import re
from pathlib import Path

spec = importlib.util.spec_from_file_location("nav", str(__import__("pathlib").Path(__file__).resolve().parents[3] / "navcom.py"))
nav = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nav)

_AUGGIE_NOT_SESSION = re.compile(r"-backup\d+\.json$")
AUGGIE_SHELL_TOOLS = ("launch-process",)


def auggie_roots():
    return [Path.home() / ".augment" / "sessions"]


def auggie_list():
    paths = []
    for root in auggie_roots():
        try:
            paths += [p for p in root.glob("*.json") if not _AUGGIE_NOT_SESSION.search(p.name)]
        except OSError:
            pass
    return [(k, m, s, "auggie") for k, m, s, _ in nav._file_logs(paths, "auggie")]


def _auggie_load(key):
    try:
        data = json.loads(Path(key).read_text(encoding="utf-8", errors="replace"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _auggie_args(raw):
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except Exception:
            return raw
    return raw


def _auggie_result_text(node):
    content = node.get("content")
    if not (isinstance(content, str) and content.strip()):
        content = "\n".join(n.get("text_content") or "" for n in node.get("content_nodes") or []
                            if isinstance(n, dict) and n.get("text_content"))
    if node.get("is_error"):
        content = "error\n" + (content or "")
    return content


def _is_summary(entry, exchange):
    if entry.get("isHistorySummary"):
        return True
    return any(isinstance(n, dict) and (n.get("type") == 10 or n.get("history_summary_node"))
               for n in exchange.get("request_nodes") or [])


def auggie_iter(key):
    calls = {}
    for entry in _auggie_load(key).get("chatHistory") or []:
        if not isinstance(entry, dict):
            continue
        ex = entry.get("exchange") or {}
        summary = _is_summary(entry, ex)
        user = ex.get("request_message")
        if isinstance(user, str) and user.strip() and not summary:
            yield "user", user
        for node in ex.get("request_nodes") or []:
            result = node.get("tool_result_node") if isinstance(node, dict) else None
            if isinstance(result, dict):
                turn = nav.tool_turn(calls.get(result.get("tool_use_id"), "tool"), _auggie_result_text(result))
                if turn:
                    yield turn
        if summary:
            continue
        nodes = [n for n in ex.get("response_nodes") or [] if isinstance(n, dict)]
        text = ex.get("response_text")
        if not (isinstance(text, str) and text.strip()):
            text = "".join(n.get("content") or "" for n in nodes if n.get("type") == 0 and isinstance(n.get("content"), str))
        if text and text.strip():
            yield "assistant", text
        for node in nodes:
            use = node.get("tool_use")
            if not isinstance(use, dict):
                continue
            name, args = use.get("tool_name"), _auggie_args(use.get("input_json"))
            calls[use.get("tool_use_id")] = nav._call_label(name, args)
            cmd = nav._shell_cmd(name, args)
            if not cmd and name in AUGGIE_SHELL_TOOLS and isinstance(args, dict):
                cmd = (args.get("command") or "").strip() or None
            if cmd:
                yield "cmd", cmd


def auggie_project(key):
    """Same rule as auggie's own j1t(): first ide_state_node workspace folder, else the terminal cwd."""
    terminal = ""
    for entry in _auggie_load(key).get("chatHistory") or []:
        for node in ((entry or {}).get("exchange") or {}).get("request_nodes") or []:
            state = node.get("ide_state_node") if isinstance(node, dict) else None
            if not isinstance(state, dict):
                continue
            for folder in state.get("workspace_folders") or []:
                root = (folder or {}).get("repository_root") or (folder or {}).get("folder_root")
                if root:
                    return root
            terminal = terminal or ((state.get("current_terminal") or {}).get("current_working_directory") or "")
    return terminal


def auggie_title(key):
    data = _auggie_load(key)
    return data.get("customTitle") or data.get("title") or ""


def auggie_fixture(home, cwd):
    sid = "3f2b8c1e-5d4a-4e7b-9a10-6c2d8e4f1a22"
    path = Path(home) / ".augment" / "sessions" / f"{sid}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    ide = {"id": 1, "type": 4, "ide_state_node": {
        "workspace_folders": [{"repository_root": cwd, "folder_root": cwd}], "workspace_folders_unchanged": False,
        "current_terminal": {"terminal_id": 0, "current_working_directory": cwd}}}
    tool_id = "toolu_vrtx_01AbCdEf"

    def entry(seq, exchange, **extra):
        return {"exchange": exchange, "completed": True, "sequenceId": seq, "finishedAt": "2026-10-02T03:30:00.000Z",
                "changedFiles": [], "changedFilesSkipped": [], "changedFilesSkippedCount": 0,
                "isHistorySummary": False, "historySummaryVersion": 0, "source": "local", **extra}

    data = {
        "sessionId": sid, "created": "2026-10-02T03:29:00.000Z", "modified": "2026-10-02T03:30:00.000Z",
        "chatHistory": [
            entry(1, {"request_message": "please say zebracornauggie and run echo", "request_id": "r1",
                      "request_nodes": [{"id": 0, "type": 0, "text_node": {"content": "please say zebracornauggie and run echo"}}, ide],
                      "response_text": "Running it.",
                      "response_nodes": [{"id": 0, "type": 0, "content": "Running it."},
                                         {"id": 1, "type": 8, "content": "", "thinking": {"content": "zebracornthinking"}},
                                         {"id": 2, "type": 5, "content": "", "tool_use": {
                                             "tool_use_id": tool_id, "tool_name": "launch-process",
                                             "input_json": json.dumps({"command": "echo hi-auggie", "wait": True,
                                                                       "max_wait_seconds": 30, "cwd": cwd})}}]}),
            entry(2, {"request_message": "", "request_id": "r2",
                      "request_nodes": [{"id": 1, "type": 1, "tool_result_node": {
                          "tool_use_id": tool_id, "is_error": False,
                          "content": "Here are the results from executing the command.\n<return-code>\n0\n</return-code>\n"
                                     "<stdout>\nhi-auggie zebracornauggietool\n</stdout>"}}],
                      "response_text": "Output shown: zebracornauggie",
                      "response_nodes": [{"id": 0, "type": 0, "content": "Output shown: zebracornauggie"}]}),
            entry(3, {"request_message": "<summary>zebracorninjected compaction summary</summary>", "request_id": "r3",
                      "request_nodes": [{"id": 0, "type": 10, "history_summary_node": {"summary_text": "zebracorninjected"}}],
                      "response_text": "", "response_nodes": []}, isHistorySummary=True),
        ],
        "agentState": {"userGuidelines": "zebracorninjected user rules", "workspaceGuidelines": "",
                       "modelId": "claude-sonnet-4-6", "userEmail": "", "agentPersonaId": None},
        "workspaceId": "ws-fixture", "title": "zebracorn fixture", "terminalId": "t1",
    }
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    (path.parent / f"{sid}-backup1.json").write_text(json.dumps(data), encoding="utf-8")  # must not be listed
    return str(path)
