"""Amp (ampcode.com, npm @ampcode/cli, formerly @sourcegraph/amp) parser for navcom.

Local thread cache: $XDG_DATA_HOME/amp/threads/T-<uuid>.json (default ~/.local/share/amp, also on macOS;
the CLI honours XDG_DATA_HOME on darwin too). The server (ampcode.com) is the source of truth; the
local file is one JSON document per thread:
  {v, id, created(ms), title?, env{initial{trees[{displayName, uri:file://...}]}}, meta{traces},
   messages[{role: user|assistant|info, messageId, content[...], meta{sentAt}, usage, state}]}
  user content:      {type:text,text} | {type:tool_result, toolUseID, run{status, result|error}}
  assistant content: {type:text,text} | {type:thinking,thinking} | {type:tool_use, id, name, input}
  role "info" (ThreadInfoMessage) is injected by Amp, not typed.
"""
import importlib.util
import json
from pathlib import Path
from urllib.parse import unquote, urlparse

spec = importlib.util.spec_from_file_location("nav", str(__import__("pathlib").Path(__file__).resolve().parents[3] / "navcom.py"))
nav = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nav)

AMP_SHELL_TOOLS = ("Bash", "shell_command", "async_shell_command")


def amp_roots():
    return [nav._xdg_data_home() / "amp" / "threads"]


def amp_list():
    files = []
    for root in amp_roots():
        if root.is_dir():
            files.extend(p for p in root.glob("T-*.json") if p.is_file())
    return nav._file_logs(files, "amp")


def _amp_load(key):
    try:
        data = json.loads(Path(key).read_text(encoding="utf-8", errors="replace"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _amp_result_text(result):
    """Mirror of agentsview serializeAmpResult: Bash {output,exitCode}, Read {content}, Edit {diff}, lists."""
    if result is None:
        return ""
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        for key in ("output", "content", "diff"):
            if key in result:
                text = _amp_result_text(result[key])
                if text:
                    code = result.get("exitCode")
                    return (f"exit {code}\n" if key == "output" and code not in (None, 0) else "") + text
        if "success" in result:
            return "success" if result["success"] else "failed"
        if any(k in result for k in ("output", "content", "diff")):
            return ""
        return json.dumps(result, ensure_ascii=False)[:20000]
    if isinstance(result, list):
        if result and all(isinstance(i, str) for i in result):
            return "\n".join(result)
        if result and isinstance(result[0], dict) and result[0].get("type") == "image":
            return ""
        return json.dumps(result, ensure_ascii=False)[:20000] if result else ""
    return json.dumps(result)


def amp_iter(key):
    calls = {}
    for msg in _amp_load(key).get("messages") or []:
        if not isinstance(msg, dict) or msg.get("role") not in ("user", "assistant"):
            continue  # "info" messages are Amp-injected
        role, content = msg["role"], msg.get("content")
        if isinstance(content, str):
            content = [{"type": "text", "text": content}]
        texts = []
        for block in content if isinstance(content, list) else []:
            if not isinstance(block, dict):
                continue
            kind = block.get("type")
            if kind == "text" and isinstance(block.get("text"), str):
                texts.append(block["text"])
                continue
            if kind not in ("tool_use", "tool_result"):
                continue  # thinking, redacted_thinking, image
            if texts and "".join(texts).strip():
                yield role, "\n".join(texts)
            texts = []
            if kind == "tool_use":
                name, args = block.get("name"), block.get("input")
                calls[block.get("id")] = nav._call_label(name, args)
                cmd = None
                if name in AMP_SHELL_TOOLS and isinstance(args, dict):
                    cmd = args.get("cmd") or args.get("command")
                cmd = cmd.strip() if isinstance(cmd, str) else nav._shell_cmd(name, args)
                if cmd:
                    yield "cmd", cmd
            else:
                call_id = block.get("toolUseID") or block.get("tool_use_id")
                run = block.get("run") if isinstance(block.get("run"), dict) else {}
                if run:
                    status = run.get("status")
                    output = _amp_result_text(run.get("result"))
                    if status == "error" and not output:
                        output = (run.get("error") or {}).get("message") or "[unknown error]"
                    if status == "error" or (isinstance(run.get("result"), dict) and run["result"].get("success") is False):
                        output = "error\n" + output
                    elif status == "cancelled" and not output:
                        output = "[cancelled]"
                else:
                    output = block.get("content")
                turn = nav.tool_turn(calls.get(call_id, "tool"), output)
                if turn:
                    yield turn
        if texts and "".join(texts).strip():
            yield role, "\n".join(texts)


def amp_project(key):
    trees = ((_amp_load(key).get("env") or {}).get("initial") or {}).get("trees") or []
    for tree in trees:
        uri = tree.get("uri") if isinstance(tree, dict) else None
        if isinstance(uri, str) and uri.startswith("file://"):
            return unquote(urlparse(uri).path)
    return ""


def amp_title(key):
    title = _amp_load(key).get("title")
    return title.strip() if isinstance(title, str) else ""


def amp_fixture(home, cwd):
    tid = "T-019cc922-3fd6-706b-9950-e56ccf39e65a"
    root = Path(home) / ".local" / "share" / "amp" / "threads"
    root.mkdir(parents=True, exist_ok=True)
    thread = {
        "v": 7, "id": tid, "created": 1790911882030, "title": "zebracorn amp fixture",
        "agentMode": "smart", "nextMessageId": 6,
        "env": {"initial": {"trees": [{"displayName": Path(cwd).name, "uri": "file://" + cwd}],
                            "platform": {"os": "darwin", "client": "CLI", "clientVersion": "0.0.1790900127"}}},
        "meta": {"traces": [{"name": "inference", "startTime": "2026-10-02T03:31:23Z", "endTime": "2026-10-02T03:31:25Z"}]},
        "messages": [
            {"role": "info", "messageId": 0, "content": [{"type": "text", "text": "zebracorninjected AGENTS.md context"}]},
            {"role": "user", "messageId": 1, "content": [{"type": "text", "text": "check zebracornamp please"}],
             "userState": {}, "agentMode": "smart", "meta": {"sentAt": 1790911882030}},
            {"role": "assistant", "messageId": 2, "content": [
                {"type": "thinking", "thinking": "secret thoughts", "signature": "x", "provider": "anthropic"},
                {"type": "text", "text": "Running it."},
                {"type": "tool_use", "complete": True, "id": "toolu_01", "name": "Bash", "input": {"cmd": "echo hi-amp", "cwd": cwd}}],
             "state": {"type": "complete", "stopReason": "tool_use"},
             "usage": {"model": "claude-sonnet-4-5", "inputTokens": 10, "outputTokens": 5, "timestamp": "2026-10-02T03:31:24Z"}},
            {"role": "user", "messageId": 3, "content": [
                {"type": "tool_result", "toolUseID": "toolu_01",
                 "run": {"status": "done", "result": {"output": "hi-amp zebracornamptool\n", "exitCode": 0}}}]},
            {"role": "assistant", "messageId": 4, "content": [{"type": "text", "text": "Output was zebracornamp."}],
             "state": {"type": "complete", "stopReason": "end_turn"}},
        ],
    }
    path = root / f"{tid}.json"
    path.write_text(json.dumps(thread, indent=2), encoding="utf-8")
    return str(path)
