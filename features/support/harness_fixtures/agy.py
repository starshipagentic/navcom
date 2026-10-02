"""Antigravity CLI (`agy`, Google, closed-source Go; verified on agy 1.2.14)
─ ~/.gemini/antigravity-cli/brain/<conversation id>/.system_generated/logs/transcript_full.jsonl

The primary store is SQLite-per-conversation (conversations/<id>.db, protobuf step blobs); agy also
writes a readable JSONL "trajectory log" per conversation (documented in its own built-in skill):
  transcript.jsonl       compact; long fields cut, listed in "truncated_fields"; tool_call args re-encoded
  transcript_full.jsonl  untruncated  ← we index this one
  chunks/transcript_full/NNNNNNNN.jsonl  the same steps in chunks (merged by step_index as a safety net)
One JSON object per step: {step_index, source: USER_EXPLICIT|USER_IMPLICIT|MODEL|SYSTEM,
type: USER_INPUT|PLANNER_RESPONSE|GENERIC|RUN_COMMAND|VIEW_FILE|ERROR_MESSAGE|..., status: DONE|ERROR,
created_at, content, thinking, tool_calls[{name, args}], media, truncated_fields}.
Tool results are the steps that follow a PLANNER_RESPONSE, in call order (no call id is logged).
Title/workspace live in <app data dir>/conversation_summaries.db (table conversation_summaries).
The Antigravity IDE (app data dir "antigravity") uses the same layout; older IDE builds only kept
encrypted .pb conversations, which are not readable.
"""
import importlib.util
import json
import re
from pathlib import Path

spec = importlib.util.spec_from_file_location("nav", str(__import__("pathlib").Path(__file__).resolve().parents[3] / "navcom.py"))
nav = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nav)

_AGY_APP_DIRS = ("antigravity-cli", "antigravity")
_AGY_SKIP_TYPES = {"SYSTEM_MESSAGE", "EPHEMERAL_MESSAGE", "CONVERSATION_HISTORY", "CHECKPOINT", "KNOWLEDGE_ARTIFACTS",
                   "KI_INSERTION", "DIRECTORY_RULES", "MEMORY", "RETRIEVE_MEMORY", "SUGGESTED_RESPONSES",
                   "BRAIN_UPDATE", "PLAN_INPUT", "TASK_BOUNDARY", "DUMMY", "UNSPECIFIED", "FINISH"}
_AGY_REQUEST_RE = re.compile(r"<USER_REQUEST>\s*(.*?)\s*</USER_REQUEST>", re.S)
_AGY_TAG_BLOCK_RE = re.compile(r"<([A-Z][A-Z0-9_]+)>.*?</\1>", re.S)
_AGY_SHELL_TOOLS = ("run_command", "shell_exec", "send_command_input")


def agy_gemini_dir():
    return Path.home() / ".gemini"  # agy has a --gemini_dir flag but no env override


def agy_roots():
    return [agy_gemini_dir() / app / "brain" for app in _AGY_APP_DIRS]


def _agy_logs_dir(key):
    return Path(key).parent


def agy_list():
    logs = []
    for root in agy_roots():
        if not root.is_dir():
            continue
        for conv in root.iterdir():
            logs_dir = conv / ".system_generated" / "logs"
            files = [p for p in (logs_dir / "transcript_full.jsonl", logs_dir / "transcript.jsonl") if p.is_file()]
            files += sorted((logs_dir / "chunks" / "transcript_full").glob("*.jsonl")) if logs_dir.is_dir() else []
            if not files:
                continue
            try:
                stats = [p.stat() for p in files]
            except OSError:
                continue
            if not any(s.st_size for s in stats):
                continue
            logs.append((str(logs_dir / "transcript_full.jsonl"), max(s.st_mtime for s in stats),
                         sum(s.st_size for s in stats), "agy"))
    return logs


def _agy_steps(key):
    """Steps by step_index: chunks first, then the full log, then the compact log only for gaps."""
    logs_dir = _agy_logs_dir(key)
    sources = sorted((logs_dir / "chunks" / "transcript_full").glob("*.jsonl")) + [logs_dir / "transcript_full.jsonl"]
    steps = {}
    for path, overwrite in [(p, True) for p in sources] + [(logs_dir / "transcript.jsonl", False)]:
        try:
            handle = open(path, "r", encoding="utf-8", errors="replace")
        except OSError:
            continue
        with handle:
            for line in handle:
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                if isinstance(obj, dict) and isinstance(obj.get("step_index"), int):
                    if overwrite or obj["step_index"] not in steps:
                        steps[obj["step_index"]] = obj
    return [steps[i] for i in sorted(steps)]


def _agy_user_text(content):
    if not isinstance(content, str):
        return ""
    found = _AGY_REQUEST_RE.findall(content)
    if found:
        return "\n".join(t for t in found if t.strip()).strip()
    return _AGY_TAG_BLOCK_RE.sub("", content).strip()  # ADDITIONAL_METADATA, USER_SETTINGS_CHANGE, ...


def _agy_args(args):
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except Exception:
            return {"command": args}
    if not isinstance(args, dict):
        return {}
    out = {}
    for k, v in args.items():  # the compact log re-encodes every value as a JSON string
        if isinstance(v, str) and v[:1] in ('"', "{", "[") and v[-1:] in ('"', "}", "]"):
            try:
                v = json.loads(v)
            except Exception:
                pass
        out[k] = v
    return out


def _agy_shell(name, args):
    if (name or "").lower() not in _AGY_SHELL_TOOLS:
        return None
    for field in ("CommandLine", "commandLine", "command", "Command", "cmd", "Input"):
        value = args.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _agy_label(name, args):
    cmd = _agy_shell(name, args)
    if cmd:
        return f"{name}: {cmd[:160]}"
    for field in ("AbsolutePath", "TargetFile", "File", "Path", "SearchPath", "Query", "Url", "DirectoryPath"):
        value = args.get(field)
        if isinstance(value, str) and value.strip():
            return f"{name}: {value.strip()[:160]}"
    return nav._call_label(name, args)


def agy_iter(key):
    pending, last_error = [], None
    for step in _agy_steps(key):
        kind, source = step.get("type") or "", step.get("source") or ""
        content = step.get("content")
        if kind == "USER_INPUT":
            if source == "USER_EXPLICIT":
                text = _agy_user_text(content)
                if text:
                    yield "user", text
            continue
        if kind == "PLANNER_RESPONSE":
            if isinstance(content, str) and content.strip():
                yield "assistant", content.strip()  # "thinking" is never read
            calls = step.get("tool_calls")
            if isinstance(calls, str):
                try:
                    calls = json.loads(calls)
                except Exception:
                    calls = []
            for call in calls if isinstance(calls, list) else []:
                if not isinstance(call, dict):
                    continue
                args = _agy_args(call.get("args") or call.get("arguments"))
                pending.append(_agy_label(call.get("name"), args))
                cmd = _agy_shell(call.get("name"), args)
                if cmd:
                    yield "cmd", cmd
            continue
        if kind in _AGY_SKIP_TYPES or source == "USER_IMPLICIT":
            continue
        is_error = step.get("status") == "ERROR" or kind == "ERROR_MESSAGE"
        if pending:
            label = pending.pop(0)
        elif is_error:
            label = "error"
        else:
            continue  # system-sourced chatter with no originating call
        output = content if isinstance(content, str) else nav._text_of(content) if content else ""
        error = step.get("error") if isinstance(step.get("error"), str) else ""
        if is_error or error:
            # retried API failures arrive as "API error (attempt N): ..." — keep one per streak
            norm = re.sub(r"\(attempt \d+\)", "", error)
            if label == "error" and norm == last_error:
                continue
            last_error = norm if label == "error" else None
            output = "\n".join(t for t in ("error", error, output) if t)
        turn = nav.tool_turn(label, output)
        if turn:
            yield turn


def _agy_summary(key):
    logs_dir = _agy_logs_dir(key)
    conv_id = logs_dir.parent.parent.name
    app_dir = logs_dir.parent.parent.parent.parent
    db = app_dir / "conversation_summaries.db"
    if db.is_file():
        try:
            conn = nav._ro_connect(db)
            try:
                row = conn.execute("SELECT title, preview, workspace_uris FROM conversation_summaries "
                                   "WHERE conversation_id = ?", (conv_id,)).fetchone()
            finally:
                conn.close()
            if row:
                return {"title": row[0] or row[1] or "", "uris": row[2] or "[]"}
        except Exception:
            pass
    try:  # fallback: <app dir>/cache/conversation_metadata.json
        meta = json.loads((app_dir / "cache" / "conversation_metadata.json").read_text(encoding="utf-8"))
        summary = ((meta.get("conversations") or {}).get(conv_id) or {}).get("summary") or {}
        return {"title": summary.get("Title") or summary.get("Preview") or "",
                "uris": json.dumps(summary.get("WorkspaceURIs") or [])}
    except Exception:
        return {}


def agy_project(key):
    from urllib.parse import unquote, urlparse
    try:
        uris = json.loads(_agy_summary(key).get("uris") or "[]")
    except Exception:
        uris = []
    for uri in uris if isinstance(uris, list) else []:
        if isinstance(uri, str) and uri.startswith("file://"):
            return unquote(urlparse(uri).path)
    for step in _agy_steps(key):  # fallback: the Cwd of the first command
        for call in step.get("tool_calls") or [] if isinstance(step.get("tool_calls"), list) else []:
            cwd = _agy_args((call or {}).get("args")).get("Cwd")
            if isinstance(cwd, str) and cwd.startswith("/"):
                return cwd
    return ""


def agy_title(key):
    return (_agy_summary(key).get("title") or "").strip()


def agy_fixture(home, cwd):
    import sqlite3
    conv_id = "0f1e2d3c-4b5a-4968-8777-a6b5c4d3e2f1"
    app = Path(home) / ".gemini" / "antigravity-cli"
    logs = app / "brain" / conv_id / ".system_generated" / "logs"
    (logs / "chunks" / "transcript_full").mkdir(parents=True, exist_ok=True)
    steps = [
        {"step_index": 0, "source": "USER_EXPLICIT", "type": "USER_INPUT", "status": "DONE",
         "created_at": "2026-10-02T03:46:27Z",
         "content": "<USER_REQUEST>\nplease check zebracornagy\n</USER_REQUEST>\n<ADDITIONAL_METADATA>\n"
                    "The current local time is: 2026-10-01T22:46:27-05:00. zebracorninjected\n</ADDITIONAL_METADATA>"},
        {"step_index": 1, "source": "SYSTEM", "type": "EPHEMERAL_MESSAGE", "status": "DONE",
         "created_at": "2026-10-02T03:46:27Z", "content": "zebracorninjected reminder"},
        {"step_index": 2, "source": "MODEL", "type": "PLANNER_RESPONSE", "status": "DONE",
         "created_at": "2026-10-02T03:46:27Z", "thinking": "zebracorninjected thought",
         "tool_calls": [{"name": "run_command", "args": {"CommandLine": "echo hi-agy", "Cwd": cwd,
                                                         "WaitMsBeforeAsync": 2000}}]},
        {"step_index": 3, "source": "MODEL", "type": "GENERIC", "status": "DONE", "created_at": "2026-10-02T03:46:29Z",
         "content": "Created At: 2026-10-01T22:46:29-05:00\n\nThe command exited with code 0.\nOutput:\n"
                    "hi-agy zebracornagytool\r\n"},
        {"step_index": 4, "source": "MODEL", "type": "PLANNER_RESPONSE", "status": "DONE",
         "created_at": "2026-10-02T03:46:29Z", "content": "Done: zebracornagy"},
    ]
    body = "".join(json.dumps(s) + "\n" for s in steps)
    (logs / "transcript_full.jsonl").write_text(body, encoding="utf-8")
    (logs / "chunks" / "transcript_full" / "00000000.jsonl").write_text(body, encoding="utf-8")
    (logs / "transcript.jsonl").write_text(body, encoding="utf-8")
    conn = sqlite3.connect(app / "conversation_summaries.db")
    conn.execute("CREATE TABLE IF NOT EXISTS conversation_summaries (conversation_id text, title text NOT NULL DEFAULT '', "
                 "preview text NOT NULL DEFAULT '', step_count integer NOT NULL DEFAULT 0, last_modified_time datetime "
                 "NOT NULL, workspace_uris text NOT NULL, app_data_dir text NOT NULL DEFAULT '', PRIMARY KEY (conversation_id))")
    conn.execute("INSERT OR REPLACE INTO conversation_summaries VALUES (?,?,?,?,?,?,?)",
                 (conv_id, "zebracorn fixture", "zebracorn fixture", len(steps), "2026-10-02 03:46:30+00:00",
                  json.dumps(["file://" + cwd]), "antigravity-cli"))
    conn.commit()
    conn.close()
    return str(logs / "transcript_full.jsonl")
