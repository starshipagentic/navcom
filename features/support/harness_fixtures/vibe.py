"""Mistral Vibe ─ <session_logging.save_dir>/<prefix>_<YYYYmmdd_HHMMSS UTC>_<id8>/{meta.json,messages.jsonl}
(default save_dir = $VIBE_HOME/logs/session = ~/.vibe/logs/session; prefix "session")

messages.jsonl: one LLMMessage per line (system prompt is NOT written; it lives in meta.json):
  {"role": "user"|"assistant"|"tool", "content": str, "injected": bool, "input_text"?, "reasoning_content"?,
   "tool_calls"?: [{"id","function":{"name","arguments": json-str}}], "name"?, "tool_call_id"?,
   "tool_result"?, "manual_shell"?: {"command","cwd","stdout","stderr","output_text","exit_code",…},
   "context_boundary"?: "compaction"}
meta.json: session_id, title, environment.working_directory, origin_directory, config, system_prompt, stats…
"""
import importlib.util
import json
import os
from pathlib import Path

spec = importlib.util.spec_from_file_location("nav", str(__import__("pathlib").Path(__file__).resolve().parents[3] / "navcom.py"))
nav = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nav)


def _vibe_home():
    return nav._env_path("VIBE_HOME") or Path.home() / ".vibe"


def vibe_roots():
    roots = []
    try:
        import tomllib
        cfg = tomllib.loads((_vibe_home() / "config.toml").read_text(encoding="utf-8"))
        save_dir = (cfg.get("session_logging") or {}).get("save_dir")
        if isinstance(save_dir, str) and save_dir.strip():
            roots.append(Path(save_dir).expanduser())
    except Exception:
        pass
    default = _vibe_home() / "logs" / "session"
    if default not in roots:
        roots.append(default)
    return roots


def vibe_list():
    paths = []
    for root in vibe_roots():
        try:
            if root.is_dir():
                paths.extend(p for p in root.glob("*/messages.jsonl") if (p.parent / "meta.json").exists())
        except OSError:
            continue
    return nav._file_logs(paths, "vibe")


def vibe_iter(key):
    calls = {}
    try:
        handle = open(key, "r", encoding="utf-8", errors="replace")
    except OSError:
        return
    with handle:
        for line in handle:
            try:
                msg = json.loads(line)
            except Exception:
                continue
            if not isinstance(msg, dict):
                continue
            role = msg.get("role")
            shell = msg.get("manual_shell")
            if isinstance(shell, dict) and shell.get("command"):
                # user typed `!<command>` in the TUI: the message text is Vibe's context wrapper
                yield "cmd", shell["command"]
                output = shell.get("output_text") or "\n".join(
                    s for s in (shell.get("stdout"), shell.get("stderr")) if s)
                code = shell.get("exit_code")
                turn = nav.tool_turn(f"!: {shell['command']}", (f"exit {code}\n" if code not in (None, 0) else "") + (output or ""))
                if turn:
                    yield turn
                continue
            if role == "user":
                if msg.get("injected") or msg.get("context_boundary"):
                    continue  # retries, hook output, compaction summaries, skill/file expansions
                text = msg.get("input_text") or nav._text_of(msg.get("content") or "")
                if text.strip():
                    yield "user", text
            elif role == "assistant":
                text = nav._text_of(msg.get("content") or "")
                if text.strip() and not msg.get("injected") and not msg.get("context_boundary"):
                    yield "assistant", text
                for call in msg.get("tool_calls") or []:
                    fn = (call or {}).get("function") or {}
                    args = fn.get("arguments")
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except Exception:
                            pass
                    calls[call.get("id")] = nav._call_label(fn.get("name"), args)
                    cmd = nav._shell_cmd(fn.get("name"), args)
                    if cmd:
                        yield "cmd", cmd
            elif role == "tool":
                output = nav._text_of(msg.get("content") or "")
                result = (msg.get("tool_result") or {}).get("output") if isinstance(msg.get("tool_result"), dict) else None
                if isinstance(result, dict) and ("stdout" in result or "stderr" in result):
                    code = result.get("returncode", result.get("exit_code"))
                    output = (f"exit {code}\n" if code not in (None, 0) else "") + "\n".join(
                        str(result[k]) for k in ("stdout", "stderr") if result.get(k))
                elif not output.strip() and result:
                    output = result
                turn = nav.tool_turn(calls.get(msg.get("tool_call_id"), msg.get("name") or "tool"), output)
                if turn:
                    yield turn


def _meta(key):
    try:
        with open(Path(key).parent / "meta.json", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def vibe_project(key):
    meta = _meta(key)
    env = meta.get("environment") if isinstance(meta.get("environment"), dict) else {}
    for value in (env.get("working_directory"), meta.get("origin_directory")):
        if isinstance(value, str) and value:
            return value
    return ""


def vibe_title(key):
    title = _meta(key).get("title")
    return title if isinstance(title, str) else ""


def vibe_fixture(home, cwd):
    sdir = Path(home) / ".vibe" / "logs" / "session" / "session_20261001_120000_0123abcd"
    sdir.mkdir(parents=True, exist_ok=True)
    (sdir / "meta.json").write_text(json.dumps({
        "session_id": "0123abcd-0000-4000-8000-000000000000", "parent_session_id": None,
        "start_time": "2026-10-01T12:00:00+00:00", "end_time": "2026-10-01T12:01:00+00:00",
        "environment": {"working_directory": cwd}, "origin_directory": cwd, "title": "Fixture zebracornvibe",
        "title_source": "manual", "total_messages": 6,
        "system_prompt": {"role": "system", "content": "You are Vibe zebracorninjected"}}, indent=2), encoding="utf-8")
    lines = [
        {"role": "user", "content": "please run it zebracornvibe", "injected": False, "message_id": "m1"},
        {"role": "user", "content": "<skill>zebracorninjected</skill>", "injected": True, "message_id": "m2"},
        {"role": "assistant", "content": "", "injected": False, "reasoning_content": "thinking zebracorninjected",
         "tool_calls": [{"id": "call_1", "index": 0, "type": "function",
                         "function": {"name": "bash", "arguments": json.dumps({"command": "echo hi-vibe"})}}],
         "message_id": "m3"},
        {"role": "tool", "content": "command: echo hi-vibe\nexit_code: 0\nstdout: hi-vibe zebracornvibetool\n",
         "injected": False, "name": "bash", "tool_call_id": "call_1",
         "tool_result": {"output": {"command": "echo hi-vibe", "exit_code": 0, "stdout": "hi-vibe zebracornvibetool\n"},
                         "duration": 0.01, "cancelled": False}},
        {"role": "assistant", "content": "done zebracornvibe", "injected": False, "message_id": "m4"},
    ]
    (sdir / "messages.jsonl").write_text("".join(json.dumps(l) + "\n" for l in lines), encoding="utf-8")
    return str(sdir / "messages.jsonl")
