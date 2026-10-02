"""Cursor CLI (cursor-agent / `agent`) — two on-disk forms of the same chat.

1. Primary store (full fidelity, incl. tool outputs):
   $CURSOR_CONFIG_DIR | $XDG_CONFIG_HOME/cursor | ~/.cursor  /chats/<md5(cwd)>/<agentId>/store.db
   (and .../acp-sessions/<id>/store.db for `agent acp`).
   SQLite: meta(key,value) where key "0" = hex(JSON{agentId, latestRootBlobId, name, createdAt,
   mode, lastUsedModel, ...}); blobs(id TEXT hex sha256, data BLOB). The root blob is a protobuf
   ConversationStateStructure: field 1 root_prompt_messages_json (repeated 32-byte blob ids),
   field 9 previous_workspace_uris, field 13 summary_archives (blob ids of SummaryArchive protos,
   whose field 1 = summarized_messages blob ids). Each message blob is JSON of a Vercel AI SDK
   message {role: system|user|assistant|tool, content: str | [text|reasoning|redacted-reasoning|
   image|file|tool-call{toolCallId,toolName,args}|tool-result{toolCallId,toolName,result}]}.
   User text wraps the typed prompt in <user_query>, with injected <user_info>, <rules>,
   <system_reminder>, ... blocks around it.
2. Readable transcript (no tool outputs; thinking is merged into the assistant text block):
   $CURSOR_DATA_DIR | ~/.cursor  /projects/<slug(cwd)>/agent-transcripts/<id>/<id>.jsonl
   lines {"role":"user"|"assistant","message":{"content":[{"type":"text"},{"type":"tool_use",
   "name","input"}]}} plus {"type":"turn_ended"} / {"type":"metadata"}; subagents under
   <parent>/subagents/<id>.jsonl; legacy flat <id>.jsonl / <id>.txt ("user:" / "assistant:" blocks,
   "[Thinking]", "[Tool call] Name" + indented "key: value", "[Tool result] Name").

A session with a store.db is listed once, as "<store.db>#<agentId>"; transcripts are listed only
for ids without a store (e.g. written by the Cursor IDE, or a store that was removed).
"""
import hashlib
import importlib.util
import json
import os
import re
import sqlite3
from pathlib import Path

spec = importlib.util.spec_from_file_location("nav", str(__import__("pathlib").Path(__file__).resolve().parents[3] / "navcom.py"))
nav = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nav)

# Tags Cursor's own transcript writer strips from user text as injected context.
_CURSOR_INJECTED_TAGS = (
    "user_info", "project_layout", "rules", "always_applied_workspace_rules", "agent_requestable_workspace_rules",
    "user_rules", "agent_skills", "available_skills", "cloud_instructions", "cloud_task_instructions",
    "open_and_recently_viewed_files", "system_reminder", "system-reminder", "instructions_update",
    "mcp_instructions", "mcp_file_system", "mcp_file_system_servers", "git_status", "agent_transcripts",
    "cursor_rules_context", "attached_files", "system_notification", "task_notification", "agent_notification",
    "timestamp")
_CURSOR_TAG_RE = re.compile(r"<(%s)(?:\s[^>]*)?>[\s\S]*?</\1>" % "|".join(re.escape(t) for t in _CURSOR_INJECTED_TAGS),
                            re.I)
_CURSOR_QUERY_RE = re.compile(r"<user_query>([\s\S]*?)</user_query>")
_CURSOR_THINK_RE = re.compile(r"<(think|thinking)>[\s\S]*?</\1>", re.I)
_CURSOR_WS_RE = re.compile(r"Workspace Path:\s*(/[^\n<]+)")


def _cursor_config_dir():
    explicit = _env_path_nonblank("CURSOR_CONFIG_DIR")
    if explicit:
        return explicit
    xdg = _env_path_nonblank("XDG_CONFIG_HOME")
    return xdg / "cursor" if xdg else Path.home() / ".cursor"


def _cursor_data_dir():
    return _env_path_nonblank("CURSOR_DATA_DIR") or Path.home() / ".cursor"


def _env_path_nonblank(name):
    value = (os.environ.get(name) or "").strip()
    return Path(value).expanduser() if value else None


def cursor_roots():
    config = _cursor_config_dir()
    return [config / "chats", config / "acp-sessions", _cursor_data_dir() / "projects"]


def _cursor_stores():
    chats, acp, _ = cursor_roots()
    stores = []
    for pattern_root, pattern in ((chats, "*/*/store.db"), (acp, "*/store.db")):
        try:
            if pattern_root.is_dir():
                stores.extend(pattern_root.glob(pattern))
        except OSError:
            pass
    return stores


def _cursor_transcripts():
    """agent id -> transcript path (.jsonl preferred over .txt)."""
    root = cursor_roots()[2]
    found = {}
    try:
        project_dirs = [p for p in root.iterdir() if p.is_dir()] if root.is_dir() else []
    except OSError:
        project_dirs = []
    for project in project_dirs:
        base = project / "agent-transcripts"
        if not base.is_dir():
            continue
        for pattern in ("*.txt", "*.jsonl", "*/*.txt", "*/*.jsonl", "*/subagents/*.txt", "*/subagents/*.jsonl"):
            for path in base.glob(pattern):
                if path.suffix == ".jsonl" or path.stem not in found:
                    found[path.stem] = path
    return found


def cursor_list():
    logs, store_ids = [], set()
    for db in _cursor_stores():
        agent_id = db.parent.name
        store_ids.add(agent_id)
        size, mtime = 0, 0.0
        for part in (db, Path(str(db) + "-wal")):
            try:
                st = part.stat()
            except OSError:
                continue
            size += st.st_size
            mtime = max(mtime, st.st_mtime)
        if mtime:
            logs.append((f"{db}#{agent_id}", mtime, size, "cursor"))
    rest = [p for stem, p in _cursor_transcripts().items() if stem not in store_ids]
    return logs + nav._file_logs(sorted(rest), "cursor")


# ── store.db ────────────────────────────────────────────────────────────────

def _pb_fields(data):
    """Minimal protobuf reader: [(field_number, wire_type, value)]; raises on malformed input."""
    out, i, n = [], 0, len(data)

    def varint(pos):
        shift = result = 0
        while True:
            if pos >= n:
                raise ValueError("truncated varint")
            b = data[pos]
            pos += 1
            result |= (b & 0x7F) << shift
            if not b & 0x80:
                return result, pos
            shift += 7

    while i < n:
        key, i = varint(i)
        field, wire = key >> 3, key & 7
        if wire == 0:
            value, i = varint(i)
        elif wire == 1:
            value, i = data[i:i + 8], i + 8
        elif wire == 2:
            length, i = varint(i)
            value, i = data[i:i + length], i + length
        elif wire == 5:
            value, i = data[i:i + 4], i + 4
        else:
            raise ValueError(f"wire type {wire}")
        if i > n:
            raise ValueError("truncated field")
        out.append((field, wire, value))
    return out


def _cursor_meta(con):
    try:
        row = con.execute("SELECT value FROM meta WHERE key='0'").fetchone()
        raw = row[0] if row else ""
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", "replace")
        try:
            return json.loads(bytes.fromhex(raw.strip()).decode("utf-8", "replace"))
        except ValueError:
            return json.loads(raw)
    except Exception:
        return {}


def _cursor_blob(con, blob_id):
    if isinstance(blob_id, (bytes, bytearray)):
        blob_id = bytes(blob_id).hex()
    try:
        row = con.execute("SELECT data FROM blobs WHERE id=?", (blob_id,)).fetchone()
    except sqlite3.Error:
        return None
    return bytes(row[0]) if row and row[0] is not None else None


def _cursor_root(con):
    meta = _cursor_meta(con)
    root_id = meta.get("latestRootBlobId")
    if isinstance(root_id, dict) and isinstance(root_id.get("hex"), str):
        root_id = root_id["hex"]
    if isinstance(root_id, list):
        root_id = bytes(root_id).hex()
    data = _cursor_blob(con, root_id) if isinstance(root_id, str) and root_id else None
    try:
        return meta, (_pb_fields(data) if data else [])
    except ValueError:
        return meta, []


def _cursor_store_messages(key):
    db = key.split("#", 1)[0]
    try:
        con = nav._ro_connect(db)
    except sqlite3.Error:
        return {}, [], []
    try:
        meta, root = _cursor_root(con)
        ids = []
        for field, wire, value in root:
            if field == 13 and wire == 2:  # summary_archives → SummaryArchive.summarized_messages
                archive = _cursor_blob(con, value) if len(value) == 32 else value
                try:
                    ids.extend(v for f, w, v in _pb_fields(archive or b"") if f == 1 and w == 2)
                except ValueError:
                    pass
        ids.extend(v for f, w, v in root if f == 1 and w == 2)
        messages = []
        for blob_id in ids:
            data = _cursor_blob(con, blob_id) if len(blob_id) == 32 else blob_id
            try:
                msg = json.loads((data or b"").decode("utf-8", "replace"))
            except Exception:
                continue
            if isinstance(msg, dict):
                messages.append(msg)
        workspaces = []
        for f, w, v in root:
            if f == 9 and w == 2:
                try:
                    workspaces.append(v.decode("utf-8"))
                except UnicodeDecodeError:
                    pass
        return meta, messages, workspaces
    except sqlite3.Error:
        return {}, [], []
    finally:
        con.close()


def _cursor_user_text(text):
    queries = _CURSOR_QUERY_RE.findall(text or "")
    if queries:
        return "\n".join(q.strip() for q in queries if q.strip())
    return _CURSOR_TAG_RE.sub("", text or "").strip()


def _cursor_result_output(part):
    for field in ("result", "output", "content", "experimental_content"):
        value = part.get(field)
        if value is None:
            continue
        if isinstance(value, dict) and value.get("type") in ("text", "json", "error-text", "error-json", "content") \
                and "value" in value:
            value = value["value"]
        if isinstance(value, dict):
            texts = [str(value[k]) for k in ("stdout", "output", "stderr", "error", "text", "content")
                     if isinstance(value.get(k), (str, int, float)) and str(value[k]).strip()]
            if texts:
                return "\n".join(texts)
        return value
    return None


def _cursor_args(args):
    if isinstance(args, str):
        try:
            return json.loads(args)
        except Exception:
            return args
    return args


def _cursor_store_turns(messages):
    calls = {}
    for msg in messages:
        role, content = msg.get("role"), msg.get("content")
        if role == "system" or ((msg.get("providerOptions") or {}).get("cursor") or {}).get("isSummary"):
            continue
        parts = [{"type": "text", "text": content}] if isinstance(content, str) else content
        if not isinstance(parts, list):
            continue
        for part in parts:
            if not isinstance(part, dict):
                continue
            kind = part.get("type")
            if kind == "text" and role == "user":
                text = _cursor_user_text(part.get("text"))
                if text:
                    yield "user", text
            elif kind == "text" and role == "assistant":
                text = _CURSOR_THINK_RE.sub("", part.get("text") or "").strip()
                if text:
                    yield "assistant", text
            elif kind == "tool-call":
                args = _cursor_args(part.get("args", part.get("input")))
                calls[part.get("toolCallId")] = nav._call_label(part.get("toolName"), args)
                cmd = nav._shell_cmd(part.get("toolName"), args)
                if cmd:
                    yield "cmd", cmd
            elif kind == "tool-result":
                label = calls.get(part.get("toolCallId")) or part.get("toolName") or "tool"
                output = _cursor_result_output(part)
                if part.get("isError") and isinstance(output, str):
                    output = "error\n" + output
                turn = nav.tool_turn(label, output)
                if turn:
                    yield turn


# ── agent-transcripts ───────────────────────────────────────────────────────

def _cursor_jsonl_turns(path):
    try:
        handle = open(path, "r", encoding="utf-8", errors="replace")
    except OSError:
        return
    with handle:
        for line in handle:
            try:
                obj = json.loads(line)
            except Exception:
                continue
            role = obj.get("role") if isinstance(obj, dict) else None
            if role not in ("user", "assistant"):
                continue
            content = (obj.get("message") or {}).get("content")
            parts = [{"type": "text", "text": content}] if isinstance(content, str) else content
            for part in parts if isinstance(parts, list) else []:
                if not isinstance(part, dict):
                    continue
                if part.get("type") == "text":
                    text = part.get("text") or ""
                    text = _cursor_user_text(text) if role == "user" else _CURSOR_THINK_RE.sub("", text).strip()
                    if text:
                        yield role, text
                elif part.get("type") == "tool_use":
                    cmd = nav._shell_cmd(part.get("name"), _cursor_args(part.get("input")))
                    if cmd:
                        yield "cmd", cmd


def _cursor_txt_args(lines):
    args = {}
    for line in lines:
        key, sep, value = line.strip().partition(": ")
        if not sep:
            key, sep, value = line.strip().partition("=")
        if sep and key:
            args[key.strip()] = value.strip()
    return args


def _cursor_txt_turns(path):
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").split("\n")
    except OSError:
        return
    role, buf, i = None, [], 0

    def flush():
        text = "\n".join(buf).strip()
        if role == "user":
            text = _cursor_user_text(text)
        return (role, text) if role and text else None

    while i < len(lines):
        line = lines[i]
        bare = line.rstrip()
        if bare in ("user:", "assistant:"):
            turn = flush()
            if turn:
                yield turn
            role, buf, i = bare[:-1], [], i + 1
            continue
        marker = line.strip()
        if marker.startswith(("[Thinking]", "[Tool call] ", "[Tool result]")) and not line[:1].isspace():
            turn = flush()
            if turn:
                yield turn
            buf, i = [], i + 1
            body = []
            while i < len(lines) and (not lines[i].strip() or lines[i][:1] in (" ", "\t")):
                body.append(lines[i])
                i += 1
            if marker.startswith("[Tool call] "):
                cmd = nav._shell_cmd(marker[len("[Tool call] "):].strip(), _cursor_txt_args(body))
                if cmd:
                    yield "cmd", cmd
            elif marker.startswith("[Tool result]") and any(b.strip() for b in body):
                turn = nav.tool_turn(marker[len("[Tool result]"):].strip() or "tool", "\n".join(body))
                if turn:
                    yield turn
            continue
        buf.append(line)
        i += 1
    turn = flush()
    if turn:
        yield turn


def cursor_iter(key):
    if "#" in key:
        _, messages, _ = _cursor_store_messages(key)
        turns = list(_cursor_store_turns(messages))
        if turns:
            yield from turns
            return
        transcript = _cursor_transcripts().get(key.rsplit("#", 1)[1])
        if not transcript:
            return
        key = str(transcript)
    if key.endswith(".txt"):
        yield from _cursor_txt_turns(key)
    else:
        yield from _cursor_jsonl_turns(key)


def _cursor_slug_project(path):
    parts = Path(path).parts
    if "agent-transcripts" in parts:
        slug = parts[parts.index("agent-transcripts") - 1]
        decoded = nav.decode_encoded_dir("-" + slug)
        return decoded if decoded.startswith("/") and Path(decoded).is_dir() else ""
    return ""


def cursor_project(key):
    if "#" in key:
        _, messages, workspaces = _cursor_store_messages(key)
        for uri in workspaces:
            if uri.startswith("file://"):
                from urllib.parse import unquote
                return unquote(uri[len("file://"):])
            if uri.startswith("/"):
                return uri
        for msg in messages[:3]:
            text = msg.get("content") if isinstance(msg.get("content"), str) else nav._text_of(msg.get("content"))
            m = _CURSOR_WS_RE.search(text or "")
            if m:
                return m.group(1).strip()
        db = Path(key.split("#", 1)[0])
        if db.parent.parent.parent.name == "acp-sessions" or db.parent.parent.name == "acp-sessions":
            try:
                return json.loads((db.parent / "meta.json").read_text()).get("cwd") or ""
            except Exception:
                pass
        transcript = _cursor_transcripts().get(key.rsplit("#", 1)[1])
        if transcript:
            return _cursor_slug_project(transcript)
        # chats/<md5(cwd)>: confirm a candidate cwd from any transcript project folder
        digest = db.parent.parent.name
        for path in _cursor_transcripts().values():
            cand = _cursor_slug_project(path)
            if cand and hashlib.md5(cand.encode()).hexdigest() == digest:
                return cand
        return ""
    return _cursor_slug_project(key)


def cursor_title(key):
    if "#" not in key:
        return ""
    try:
        con = nav._ro_connect(key.split("#", 1)[0])
        try:
            name = _cursor_meta(con).get("name")
        finally:
            con.close()
    except sqlite3.Error:
        return ""
    return name if isinstance(name, str) else ""


# ── fixture ─────────────────────────────────────────────────────────────────

def _pb_varint(value):
    out = bytearray()
    while True:
        b = value & 0x7F
        value >>= 7
        if value:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def _pb_bytes(field, payload):
    return _pb_varint((field << 3) | 2) + _pb_varint(len(payload)) + payload


def cursor_fixture(home, cwd):
    agent_id = "5c0ffee0-1111-4222-8333-944455556666"
    cfg = Path(home) / ".cursor"
    db_path = cfg / "chats" / hashlib.md5(os.path.abspath(cwd).encode()).hexdigest() / agent_id / "store.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    messages = [
        {"role": "system", "content": "You are Cursor's agent. zebracorninjected system prompt"},
        {"role": "user", "content": [{"type": "text", "text":
            f"<user_info>\nOS Version: darwin 25.2.0\nWorkspace Path: {cwd}\nzebracorninjected\n</user_info>\n"
            "<rules>\nzebracorninjected rule\n</rules>"}]},
        {"role": "user", "content": [{"type": "text", "text":
            "<timestamp>Thursday, Oct 1, 2026, 10:30 PM (UTC-4)</timestamp>\n"
            "<user_query>\nplease run it zebracorncursor\n</user_query>\n"
            "<system_reminder>zebracorninjected reminder</system_reminder>"}]},
        {"role": "assistant", "content": [
            {"type": "reasoning", "text": "secret zebracornthinking"},
            {"type": "text", "text": "Running it."},
            {"type": "tool-call", "toolCallId": "tool_1", "toolName": "Shell",
             "args": {"command": "echo hi-cursor", "description": "echo"}}]},
        {"role": "tool", "content": [{"type": "tool-result", "toolCallId": "tool_1", "toolName": "Shell",
                                      "result": "hi-cursor zebracorncursortool\n"}]},
        {"role": "assistant", "content": [{"type": "text", "text": "Done: zebracorncursor"}]},
    ]
    blobs, ids = {}, []
    for msg in messages:
        data = json.dumps(msg).encode()
        digest = hashlib.sha256(data).digest()
        blobs[digest.hex()] = data
        ids.append(digest)
    root = b"".join(_pb_bytes(1, d) for d in ids) + _pb_bytes(9, f"file://{cwd}".encode())
    root_id = hashlib.sha256(root).hexdigest()
    blobs[root_id] = root
    meta = {"agentId": agent_id, "latestRootBlobId": root_id, "name": "zebracorncursor fixture chat",
            "createdAt": 1790911641255, "mode": "default", "lastUsedModel": "auto"}
    con = sqlite3.connect(db_path)
    con.executescript("PRAGMA user_version = 1;"
                      "CREATE TABLE IF NOT EXISTS blobs (id TEXT PRIMARY KEY, data BLOB);"
                      "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);")
    con.executemany("INSERT OR REPLACE INTO blobs VALUES (?, ?)", list(blobs.items()))
    con.execute("INSERT OR REPLACE INTO meta VALUES ('0', ?)", (json.dumps(meta).encode().hex(),))
    con.commit()
    con.close()

    # The CLI also writes the readable transcript for the same chat (shadowed by the store in list()).
    slug = re.sub(r"-+", "-", re.sub(r"[^a-zA-Z0-9]", "-", cwd)).strip("-")
    tdir = cfg / "projects" / slug / "agent-transcripts" / agent_id
    tdir.mkdir(parents=True, exist_ok=True)
    lines = [
        {"role": "user", "message": {"content": [{"type": "text", "text":
            "<timestamp>Thursday, Oct 1, 2026, 10:30 PM (UTC-4)</timestamp>\n<user_query>\nplease run it zebracorncursor\n</user_query>"}]}},
        {"role": "assistant", "message": {"content": [
            {"type": "text", "text": "Running it."},
            {"type": "tool_use", "name": "Shell", "input": {"command": "echo hi-cursor", "description": "echo"}}]}},
        {"role": "assistant", "message": {"content": [{"type": "text", "text": "Done: zebracorncursor"}]}},
        {"type": "turn_ended", "status": "success"},
    ]
    (tdir / f"{agent_id}.jsonl").write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")
    return f"{db_path}#{agent_id}"
