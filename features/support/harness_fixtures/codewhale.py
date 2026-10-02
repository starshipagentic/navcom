"""navcom parsers for three DeepSeek-first harnesses: Codewhale, Reasonix, Deep Code.

The same file is copied into harness/codewhale, harness/reasonix and harness/deepcode.
"""
import base64
import importlib.util
import json
import os
import re
import struct
import sys
import tempfile
from pathlib import Path

spec = importlib.util.spec_from_file_location("nav", str(__import__("pathlib").Path(__file__).resolve().parents[3] / "navcom.py"))
nav = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nav)


def _load_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return None


def _jsonl(path):
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
            if isinstance(obj, dict):
                yield obj


def _tolerant(gen_fn):
    """Odd records end a transcript early instead of raising into the indexer."""
    def wrapper(key):
        try:
            yield from gen_fn(key)
        except Exception:
            return
    wrapper.__name__ = gen_fn.__name__
    return wrapper


def _safe_str(fn):
    def wrapper(key):
        try:
            return fn(key) or ""
        except Exception:
            return ""
    wrapper.__name__ = fn.__name__
    return wrapper


def _args(raw):
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except Exception:
            return raw
    return raw


# A text part that is one whole XML-ish element is host-injected context
# (<turn_meta>, <session_goal>, <workspace>, <session-context>, <system-reminder>, …).
_INJECTED_BLOCK_RE = re.compile(r"^\s*<([A-Za-z][\w-]*)\b[^>]*>.*</\1>\s*$|^\s*<[A-Za-z][\w-]*\b[^>]*/>\s*$", re.S)
_EDGE_BLOCK_RE = re.compile(r"\A\s*<([A-Za-z][\w-]*)\b[^>]*>\n.*?\n</\1>\s*|\s*<([A-Za-z][\w-]*)\b[^>]*>\n.*?\n</\2>\s*\Z", re.S)


def _strip_injected(text):
    """Drop whole injected XML blocks wrapped around typed text (leading or trailing)."""
    if not isinstance(text, str):
        return ""
    if _INJECTED_BLOCK_RE.match(text):
        return ""
    prev = None
    while prev != text:
        prev, text = text, _EDGE_BLOCK_RE.sub("", text, count=1)
    return text.strip()


# ─────────────────────────────────────────────────────────────────────────────
# Codewhale (formerly DeepSeek-TUI) ─ $CODEWHALE_HOME/sessions/<id>.json
#   legacy ~/.deepseek/sessions (migrated by move, or copied when the move fails)
# ─────────────────────────────────────────────────────────────────────────────

def codewhale_roots():
    explicit = nav._env_path("CODEWHALE_HOME")
    if explicit:
        return [explicit / "sessions"]  # an explicit home never falls back to ~/.deepseek
    return [Path.home() / ".codewhale" / "sessions", Path.home() / ".deepseek" / "sessions"]


def codewhale_list():
    seen, paths = set(), []
    for root in codewhale_roots():
        try:
            entries = sorted(root.glob("*.json")) if root.is_dir() else []
        except OSError:
            entries = []
        for path in entries:
            # session_boot_owners.json etc. are bookkeeping; checkpoints/ and
            # .work-graph-import-archive/ hold copies of the same sessions.
            if path.name in seen or path.name == "session_boot_owners.json":
                continue
            seen.add(path.name)
            paths.append(path)
    return nav._file_logs(paths, "codewhale")


def _codewhale_messages(session):
    """Every message the session ever held: the append-only journal (all branches,
    pre-compaction turns included) when present, else the flat messages list."""
    journal = session.get("journal") if isinstance(session.get("journal"), dict) else {}
    entries = journal.get("entries") if isinstance(journal.get("entries"), list) else []
    if entries:
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            kind = entry.get("kind")
            if kind == "message" and isinstance(entry.get("message"), dict):
                yield entry["message"]
            elif kind in ("user", "assistant") and isinstance(entry.get("text"), str):
                yield {"role": kind, "content": [{"type": "text", "text": entry["text"]}]}
            # compaction / branch_summary / system: generated context, not typed or said
        return
    messages = session.get("messages")
    for message in messages if isinstance(messages, list) else []:
        if isinstance(message, dict):
            yield message


@_tolerant
def codewhale_iter(key):
    session = _load_json(key)
    if not isinstance(session, dict):
        return
    calls = {}
    for message in _codewhale_messages(session):
        role = message.get("role")
        content = message.get("content")
        if isinstance(content, str):
            content = [{"type": "text", "text": content}]
        if not isinstance(content, list) or role == "system":
            continue
        texts = []
        for block in content:
            if not isinstance(block, dict):
                continue
            kind = block.get("type")
            if kind == "text" and isinstance(block.get("text"), str):
                text = block["text"]
                if role == "user":
                    text = _strip_injected(text)
                elif role == "assistant_interrupted":
                    text = text.replace(
                        "[The following assistant output was interrupted before completion and may be incomplete or wrong]\n", "")
                if text.strip():
                    texts.append(text)
            elif kind in ("tool_use", "server_tool_use"):
                if texts:
                    yield ("user" if role == "user" else "assistant"), "\n".join(texts)
                    texts = []
                args = _args(block.get("input"))
                calls[block.get("id")] = nav._call_label(block.get("name"), args)
                cmd = nav._shell_cmd(block.get("name"), args)
                if cmd:
                    yield "cmd", cmd
            elif kind in ("tool_result", "tool_search_tool_result", "code_execution_tool_result"):
                output = block.get("content")
                if (not isinstance(output, str) or not output.strip()) and block.get("content_blocks"):
                    output = block["content_blocks"]
                if block.get("is_error"):
                    output = "error\n" + (output if isinstance(output, str) else nav._text_of(output))
                turn = nav.tool_turn(calls.get(block.get("tool_use_id"), "tool"), output)
                if turn:
                    yield turn
            # thinking / image_url: skipped
        if texts:
            yield ("user" if role == "user" else "assistant"), "\n".join(texts)


def _codewhale_meta(key):
    session = _load_json(key)
    meta = session.get("metadata") if isinstance(session, dict) else None
    return meta if isinstance(meta, dict) else {}


@_safe_str
def codewhale_project(key):
    return str(_codewhale_meta(key).get("workspace") or "")


@_safe_str
def codewhale_title(key):
    return str(_codewhale_meta(key).get("title") or "")


def codewhale_fixture(home, cwd):
    sid = "0f0e0d0c-0b0a-4009-8807-060504030201"
    path = Path(home) / ".codewhale" / "sessions" / f"{sid}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    messages = [
        {"role": "user", "content": [
            {"type": "text", "text": "please check zebracorncodewhale"},
            {"type": "text", "text": f"<turn_meta>\nCurrent workspace: {cwd}\nzebracorninjected\n</turn_meta>"}]},
        {"role": "assistant", "content": [
            {"type": "thinking", "thinking": "zebracornthinking"},
            {"type": "tool_use", "id": "call_1", "name": "bash", "input": {"command": "echo hi-codewhale"}}]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "call_1", "content": "hi zebracorncodewhaletool"}]},
        {"role": "assistant", "content": [{"type": "text", "text": "done: zebracorncodewhale"}]},
    ]
    entries, parent = [], None
    for i, message in enumerate(messages):
        entry = {"id": f"e{i}", "kind": "message", "message": message,
                 "created_at": "2026-10-01T00:00:00Z", "spawn_depth": 0}
        if parent:
            entry["parent_id"] = parent
        entries.append(entry)
        parent = entry["id"]
    session = {
        "schema_version": 1,
        "metadata": {"id": sid, "title": "please check zebracorncodewhale",
                     "created_at": "2026-10-01T00:00:00Z", "updated_at": "2026-10-01T00:00:00Z",
                     "message_count": 4, "total_tokens": 0, "model": "deepseek-flash",
                     "model_provider": "deepseek", "workspace": cwd, "mode": "agent"},
        "messages": messages,
        "journal": {"entries": entries, "leaf_id": parent, "schema_version": 1, "spawn_depth": 0},
        "leaf_id": parent,
        "system_prompt": "## Codewhale\nzebracorninjected system prompt",
    }
    path.write_text(json.dumps(session, indent=2), encoding="utf-8")
    return str(path)


# ─────────────────────────────────────────────────────────────────────────────
# Reasonix ─ state root = $REASONIX_STATE_HOME | $REASONIX_HOME | ~/.reasonix
#   2.x (Studio, Go):      <state>/[projects/<slug>/]sessions/<stem>.jsonl  (+ <stem>.events.jsonl
#                          schema 1/3 replace|append records; may hold newer turns than the .jsonl)
#   1.x 1.38.2–1.38.7:     same names, but <stem>.events.jsonl is a schema 2 DAG log
#   1.x ≥1.38.8 (npm):     <state>/projects/<slug>/sessions-v4/<id>/events.frames
#                          (RX4F frames of zstd JSON records; big payloads in ../.content-v1)
# ─────────────────────────────────────────────────────────────────────────────

_REASONIX_SIDECARS = (".events.jsonl", ".conflicts.jsonl", ".guardian.jsonl", ".wire.jsonl",
                      ".adjudication.jsonl", ".execution.jsonl", ".turns.jsonl")


def reasonix_roots():
    state = nav._env_path("REASONIX_STATE_HOME", "REASONIX_HOME")
    if state:
        return [state]
    roots = [Path.home() / ".reasonix"]
    # pre-dotdir installs kept state in the OS config dir
    if sys.platform == "darwin":
        roots.append(Path.home() / "Library" / "Application Support" / "reasonix")
    else:
        xdg = os.environ.get("XDG_CONFIG_HOME")
        roots.append((Path(xdg).expanduser() if xdg else Path.home() / ".config") / "reasonix")
    return roots


def _reasonix_session_dirs(state):
    """<state>/sessions plus <state>/projects/<slug>/sessions; sessions-v4 sits beside each."""
    dirs = [state / "sessions"]
    try:
        dirs += [d / "sessions" for d in sorted((state / "projects").iterdir()) if d.is_dir()] \
            if (state / "projects").is_dir() else []
    except OSError:
        pass
    return dirs


def reasonix_list():
    logs = []
    for state in reasonix_roots():
        for sessions in _reasonix_session_dirs(state):
            for path in nav._rglob(sessions, "*.jsonl"):
                rel = path.relative_to(sessions).parts
                if any(p.startswith(".") or p.endswith(".ckpt") or p.endswith(".inbox") for p in rel[:-1]):
                    continue
                if path.name.endswith(_REASONIX_SIDECARS):
                    continue
                events = path.with_name(path.name[:-len(".jsonl")] + ".events.jsonl")
                try:
                    st = path.stat()
                    ev = events.stat() if events.exists() else None
                except OSError:
                    continue
                mtime = max(st.st_mtime, ev.st_mtime if ev else 0)
                logs.append((str(path), mtime, st.st_size + (ev.st_size if ev else 0), "reasonix"))
            v4 = sessions.parent / "sessions-v4"
            try:
                session_dirs = sorted(v4.iterdir()) if v4.is_dir() else []
            except OSError:
                session_dirs = []
            for sdir in session_dirs:
                frames = sdir / "events.frames"
                if sdir.name.startswith(".") or not (sdir / "manifest.json").is_file() or not frames.is_file():
                    continue
                imported = sessions / f"v4-{sdir.name}.jsonl"  # a 2.x import of this 1.x session
                try:
                    if imported.exists() and imported.stat().st_mtime >= frames.stat().st_mtime:
                        continue
                except OSError:
                    pass
                logs.extend(nav._file_logs([frames], "reasonix"))
    return logs


def _rx4f_records(frames_path):
    """Decode an RX4F log: 12-byte header (magic, compressed len, raw len; big-endian)
    then one zstd frame per JSON record. A torn tail is a write in progress."""
    try:
        data = Path(frames_path).read_bytes()
    except OSError:
        return []
    chunks, sizes, off = [], [], 0
    while off + 12 <= len(data) and data[off:off + 4] == b"RX4F":
        clen, rlen = struct.unpack(">II", data[off + 4:off + 12])
        if off + 12 + clen > len(data):
            break
        chunks.append(data[off + 12:off + 12 + clen])
        sizes.append(rlen)
        off += 12 + clen
    if not chunks:
        return []
    # zstd frames concatenate: decode them in one pass with navcom's reader, then split.
    with tempfile.NamedTemporaryFile(suffix=".zst", delete=False) as tmp:
        tmp.write(b"".join(chunks))
    try:
        raw = nav.read_zstd(tmp.name)
    finally:
        os.unlink(tmp.name)
    records, pos = [], 0
    for size in sizes:
        piece = raw[pos:pos + size]
        pos += size
        try:
            records.append(json.loads(piece))
        except Exception:
            break
    return records


def _reasonix_v4(frames_path):
    """-> (messages, title). Keeps every message the log ever committed (upserts in
    place; retracted and history-replaced messages are kept), in first-seen order."""
    sdir = Path(frames_path).parent
    manifest = _load_json(sdir / "manifest.json") or {}
    pool = (sdir if manifest.get("contentRoot") == ".content-v1" else sdir.parent) / ".content-v1"
    order, by_id, title, pending = [], {}, "", []

    def body_of(event):
        ref = event.get("payloadRef")
        try:
            if isinstance(ref, dict) and len(str(ref.get("digest", ""))) == 64:
                d = ref["digest"]
                return json.loads((pool / "objects" / d[:2] / d[2:4] / d).read_bytes())
            if event.get("payload"):
                return json.loads(base64.b64decode(event["payload"]))
        except Exception:
            pass
        return {}

    def add(message):
        if not isinstance(message, dict):
            return
        mid = message.get("id")
        if mid and mid in by_id:
            order[by_id[mid]] = message
        else:
            if mid:
                by_id[mid] = len(order)
            order.append(message)

    for rec in _rx4f_records(frames_path):
        kind = rec.get("recordType")
        if kind == "batch/begin":
            pending = []
        elif kind == "batch/event" and isinstance(rec.get("event"), dict):
            pending.append(rec["event"])
        elif kind == "batch/end":
            for event in pending:
                ek = event.get("kind")
                if ek in ("message/complete", "message/upsert"):
                    msg = body_of(event).get("message")
                    if ek == "message/complete" and isinstance(msg, dict) and msg.get("id") in by_id:
                        continue
                    add(msg)
                elif ek in ("history/replace", "legacy/import"):
                    for msg in body_of(event).get("messages") or []:
                        if not (isinstance(msg, dict) and msg.get("id") in by_id):
                            add(msg)
                elif ek == "session/title":
                    title = str(body_of(event).get("title") or "").strip() or title
            pending = []
    return order, title


def _reasonix_events_kind(events_path):
    for rec in _jsonl(events_path):
        return rec.get("schema_version")
    return None


def _reasonix_dag(events_path):
    """1.x schema 2 DAG log: every message node of every head, patches/redactions applied."""
    order, by_id = [], {}
    for rec in _jsonl(events_path):
        kind = rec.get("type")
        if kind == "message" and rec.get("id") and rec["id"] not in by_id:
            msgs = rec.get("msgs") or []
            if msgs and isinstance(msgs[0], dict):
                by_id[rec["id"]] = len(order)
                order.append(msgs[0])
        elif kind == "patch" and rec.get("target") in by_id:
            msgs = rec.get("msgs") or []
            if msgs and isinstance(msgs[0], dict):
                order[by_id[rec["target"]]] = msgs[0]
        elif kind == "redact" and isinstance(rec.get("targets"), dict):
            for target, msgs in rec["targets"].items():
                if target in by_id and msgs and isinstance(msgs[0], dict):
                    order[by_id[target]] = msgs[0]
    return order


def _reasonix_replay(events_path):
    """2.x schema 1/3 log: replace resets, append extends. Messages a later replace
    dropped (rewinds, compaction) are kept, in first-seen order."""
    snapshots, cur, records = [], [], 0
    for rec in _jsonl(events_path):
        msgs = rec.get("messages") if isinstance(rec.get("messages"), list) else []
        msgs = [m for m in msgs if isinstance(m, dict)]
        if rec.get("type") == "replace":
            snapshots.append(cur)
            cur = msgs
        elif rec.get("type") == "append":
            idx = rec.get("message_index")
            cur = cur[:idx if isinstance(idx, int) else len(cur)] + msgs
        else:
            continue
        records += 1
    if not records:
        return None
    out, seen = [], set()
    for snap in snapshots + [cur]:
        counts = {}
        for msg in snap:
            sig = json.dumps(msg, sort_keys=True, ensure_ascii=False)
            counts[sig] = counts.get(sig, 0) + 1
            if (sig, counts[sig]) not in seen:
                seen.add((sig, counts[sig]))
                out.append(msg)
    return out


def _reasonix_messages(key):
    if key.endswith("events.frames"):
        return _reasonix_v4(key)[0]
    events = key[:-len(".jsonl")] + ".events.jsonl"
    if os.path.exists(events):
        schema = _reasonix_events_kind(events)
        msgs = _reasonix_dag(events) if schema == 2 else _reasonix_replay(events)
        if msgs:
            return msgs
    return list(_jsonl(key))


def _openai_calls(tool_calls):
    for call in tool_calls if isinstance(tool_calls, list) else []:
        if not isinstance(call, dict):
            continue
        fn = call.get("function") if isinstance(call.get("function"), dict) else call
        yield call.get("id"), fn.get("name") or call.get("resolved_name"), _args(fn.get("arguments"))


@_tolerant
def reasonix_iter(key):
    calls = {}
    for msg in _reasonix_messages(key):
        role = msg.get("role")
        if role == "user":
            if msg.get("host_authored") or msg.get("origin") == "host":
                continue  # session-context snapshots, steer notes: injected
            raw = msg.get("raw_content")
            text = raw if isinstance(raw, str) and raw.strip() else _strip_injected(nav._text_of(msg.get("content")))
            if text.strip():
                yield "user", text
        elif role == "assistant":
            text = nav._text_of(msg.get("content"))
            if text.strip():
                yield "assistant", text.strip()
            for cid, name, args in _openai_calls(msg.get("tool_calls")):
                calls[cid] = nav._call_label(name, args)
                cmd = nav._shell_cmd(name, args)
                if cmd:
                    yield "cmd", cmd
        elif role == "tool":
            output = msg.get("content")
            if isinstance(output, list):
                output = nav._text_of(output)
            label = calls.get(msg.get("tool_call_id")) or msg.get("name") or "tool"
            turn = nav.tool_turn(label, output)
            if turn:
                yield turn


_WORKSPACE_RE = re.compile(r'Current workspace: "([^"]+)"')


@_safe_str
def reasonix_project(key):
    for msg in _reasonix_messages(key)[:8]:
        if msg.get("role") in ("user", "system"):
            m = _WORKSPACE_RE.search(nav._text_of(msg.get("content")) or "")
            if m:
                return m.group(1)
    parts = Path(key).parts
    if "projects" in parts:
        i = len(parts) - 1 - parts[::-1].index("projects")
        if i + 1 < len(parts):
            return parts[i + 1]  # lossy slug (/ → -), same as navcom does for Claude
    return ""


@_safe_str
def reasonix_title(key):
    if key.endswith("events.frames"):
        title = _reasonix_v4(key)[1]
        if title:
            return title
        cache = _load_json(Path(key).parent.parent / ".query-cache" / Path(key).parent.name / "catalog-metadata.json")
        return str((cache or {}).get("title") or "").strip()
    meta = _load_json(key + ".meta") or {}
    return str(meta.get("title") or "").strip()  # 2.x keeps only a preview of the first prompt


def reasonix_fixture(home, cwd):
    slug = cwd.replace("/", "-")
    sessions = Path(home) / ".reasonix" / "projects" / slug / "sessions"
    sessions.mkdir(parents=True, exist_ok=True)
    stem = sessions / "20261001-000000.000000000-deepseek-flash"
    system = {"role": "system", "content": "You are Reasonix, a coding agent. zebracorninjected"}
    user = {"role": "user",
            "content": f'<workspace>\nCurrent workspace: "{cwd}".\nzebracorninjected\n</workspace>\n\n'
                       "run it zebracornreasonix\n\n<execution-policy preset=\"balanced\" version=\"3\">\nverify=targeted\n</execution-policy>",
            "raw_content": "run it zebracornreasonix", "createdAt": 1790000000000}
    call = {"role": "assistant", "content": " ", "reasoning_content": "zebracornthinking",
            "tool_calls": [{"id": "call_1", "name": "bash", "arguments": json.dumps({"command": "echo hi-reasonix"})}]}
    result = {"role": "tool", "content": "hi zebracornreasonixtool\n", "tool_call_id": "call_1", "name": "bash"}
    steer = {"role": "user", "content": f'<workspace>\nCurrent workspace: "{cwd}"\n</workspace>\nzebracorninjected steer',
             "host_authored": True}
    reply = {"role": "assistant", "content": "done zebracornreasonix"}
    # checkpoint .jsonl lags the event log: the newest turns exist only in the sidecar
    with open(f"{stem}.jsonl", "w", encoding="utf-8") as fh:
        for m in (system, user):
            fh.write(json.dumps(m) + "\n")
    with open(f"{stem}.events.jsonl", "w", encoding="utf-8") as fh:
        fh.write(json.dumps({"schema_version": 1, "type": "replace", "revision": 1, "messages": [system, user],
                             "created_at": "2026-10-01T00:00:00Z"}) + "\n")
        fh.write(json.dumps({"schema_version": 1, "type": "append", "revision": 2, "base_revision": 1,
                             "message_index": 2, "messages": [call, result, steer, reply],
                             "created_at": "2026-10-01T00:00:01Z"}) + "\n")
    Path(f"{stem}.jsonl.meta").write_text(json.dumps({"id": stem.name, "model": "deepseek/deepseek-flash",
                                                       "revision": 2, "schema_version": 2, "turns": 1,
                                                       "preview": "run it zebracornreasonix"}), encoding="utf-8")
    return f"{stem}.jsonl"


def reasonix_v4_fixture(home, cwd):
    """A 1.x sessions-v4 store (RX4F frames), built with the zstd CLI."""
    import hashlib
    import subprocess
    sid = "0123456789abcdef0123456789abcdef"
    sdir = Path(home) / ".reasonix" / "projects" / cwd.replace("/", "-") / "sessions-v4" / sid
    sdir.mkdir(parents=True, exist_ok=True)
    (sdir / "manifest.json").write_text(json.dumps({
        "schemaVersion": 4, "codec": "reasonix.session.linear/v4", "storageRevision": 3,
        "contentRoot": "../.content-v1", "sessionId": sid, "createdAt": "2026-10-01T00:00:00Z",
        "writerGeneration": 1, "kind": "headless-run"}), encoding="utf-8")
    big = json.dumps({"message": {"role": "tool", "id": "m5", "content": "hi zebracornreasonixv4tool\n",
                                  "tool_call_id": "c1", "name": "bash"}}).encode()
    digest = hashlib.sha256(big).hexdigest()
    obj = sdir.parent / ".content-v1" / "objects" / digest[:2] / digest[2:4] / digest
    obj.parent.mkdir(parents=True, exist_ok=True)
    obj.write_bytes(big)
    events = [
        ("message/complete", {"message": {"role": "user", "id": "m1", "origin": "host",
                                          "content": f'<session-context version="1">\n## Workspace\n\nCurrent workspace: "{cwd}"\nzebracorninjected\n</session-context>'}}),
        ("message/complete", {"message": {"role": "user", "id": "m2", "origin": "user",
                                          "content": "v4 zebracornreasonixv4", "raw_content": "v4 zebracornreasonixv4"}}),
        ("message/complete", {"message": {"role": "assistant", "id": "m3", "reasoning_content": "zebracornthinking",
                                          "tool_calls": [{"id": "c1", "name": "bash",
                                                          "arguments": json.dumps({"command": "echo hi-reasonixv4"})}]}}),
        ("message/complete", None),  # payload in the content pool
        ("message/complete", {"message": {"role": "assistant", "id": "m6", "content": "done zebracornreasonixv4"}}),
        ("session/title", {"title": "v4 zebracorn title"}),
    ]
    out = bytearray()

    def frame(rec):
        raw = json.dumps(rec).encode()
        comp = subprocess.run(["zstd", "-q", "-c"], input=raw, capture_output=True).stdout
        out.extend(b"RX4F" + struct.pack(">II", len(comp), len(raw)) + comp)

    head = {"schemaVersion": 4, "codec": "reasonix.session.linear/v4"}
    for seq, (kind, body) in enumerate(events, start=1):
        frame({**head, "recordType": "batch/begin", "commitId": f"c{seq}", "firstSeq": seq, "eventCount": 1})
        ev = {"id": f"e{seq}", "seq": seq, "kind": kind}
        if body is None:
            ev["payloadRef"] = {"digest": digest, "bytes": len(big)}
        else:
            ev["payload"] = base64.b64encode(json.dumps(body).encode()).decode()
        frame({**head, "recordType": "batch/event", "event": ev})
        frame({**head, "recordType": "batch/end", "commitId": f"c{seq}", "firstSeq": seq, "eventCount": 1, "sha256": ""})
    (sdir / "events.frames").write_bytes(bytes(out))
    return str(sdir / "events.frames")


# ─────────────────────────────────────────────────────────────────────────────
# Deep Code (lessweb/deepcode-cli, npm @vegamo/deepcode-cli)
#   ~/.deepcode/projects/<cwd with / → ->/<sessionId>.jsonl  (+ sessions-index.json)
#   os.homedir() only; no env override.
# ─────────────────────────────────────────────────────────────────────────────

def deepcode_roots():
    return [Path.home() / ".deepcode" / "projects"]


def deepcode_list():
    paths = []
    for root in deepcode_roots():
        try:
            paths += sorted(root.glob("*/*.jsonl")) if root.is_dir() else []
        except OSError:
            pass
    return nav._file_logs(paths, "deepcode")


def _deepcode_tool_output(content):
    """Tool results are a JSON envelope {"ok","name","output"|"error","metadata":{exitCode…}}."""
    if not isinstance(content, str):
        return content
    try:
        env = json.loads(content)
    except Exception:
        return content
    if not isinstance(env, dict) or not ({"output", "error", "ok"} & set(env)):
        return content
    body = env.get("output")
    if not isinstance(body, str):
        body = json.dumps(body, ensure_ascii=False) if body not in (None, "") else ""
    meta = env.get("metadata") if isinstance(env.get("metadata"), dict) else {}
    code = meta.get("exitCode")
    head = []
    if env.get("ok") is False:
        head.append("error" + (f": {env['error']}" if isinstance(env.get("error"), str) else ""))
    if code not in (None, 0):
        head.append(f"exit {code}")
    return "\n".join(head + [body]).strip()


@_tolerant
def deepcode_iter(key):
    calls = {}
    for msg in _jsonl(key):
        role = msg.get("role")
        params = msg.get("messageParams") if isinstance(msg.get("messageParams"), dict) else {}
        meta = msg.get("meta") if isinstance(msg.get("meta"), dict) else {}
        if role == "user":
            prompt = meta.get("userPrompt") if isinstance(meta.get("userPrompt"), dict) else {}
            text = prompt.get("text") if isinstance(prompt.get("text"), str) else nav._text_of(msg.get("content"))
            if text and text.strip():
                yield "user", text
        elif role == "assistant":
            text = nav._text_of(msg.get("content"))
            if text.strip():
                yield "assistant", text.strip()
            for cid, name, args in _openai_calls(params.get("tool_calls")):
                calls[cid] = nav._call_label(name, args)
                cmd = nav._shell_cmd(name, args)
                if cmd:
                    yield "cmd", cmd
        elif role == "tool":
            label = calls.get(params.get("tool_call_id"))
            if not label and isinstance(meta.get("function"), dict):
                fn = meta["function"]
                label = nav._call_label(fn.get("name"), _args(fn.get("arguments")))
            turn = nav.tool_turn(label or "tool", _deepcode_tool_output(msg.get("content")))
            if turn:
                yield turn
        # system: prompt, environment, skill bodies, compaction summaries (meta.isSummary)


def _deepcode_index_entry(key):
    index = _load_json(Path(key).parent / "sessions-index.json") or {}
    sid = Path(key).stem
    for entry in index.get("entries") or []:
        if isinstance(entry, dict) and entry.get("id") == sid:
            return index, entry
    return index, {}


_ROOT_PATH_RE = re.compile(r'"root path":\s*"((?:[^"\\]|\\.)*)"')


@_safe_str
def deepcode_project(key):
    index, _ = _deepcode_index_entry(key)
    if isinstance(index.get("originalPath"), str) and index["originalPath"]:
        return index["originalPath"]
    for msg in _jsonl(key):
        if msg.get("role") == "system":
            m = _ROOT_PATH_RE.search(nav._text_of(msg.get("content")) or "")
            if m:
                try:
                    return json.loads(f'"{m.group(1)}"')
                except Exception:
                    return m.group(1)
        elif msg.get("role") == "user":
            break
    return Path(key).parent.name


@_safe_str
def deepcode_title(key):
    _, entry = _deepcode_index_entry(key)
    return str(entry.get("summary") or "").strip()


def deepcode_fixture(home, cwd):
    sid = "6f1c2d3e-4a5b-4c6d-8e7f-001122334455"
    pdir = Path(home) / ".deepcode" / "projects" / cwd.replace("/", "-")
    pdir.mkdir(parents=True, exist_ok=True)
    base = {"sessionId": sid, "contentParams": None, "compacted": False,
            "createTime": "2026-10-01T00:00:00.000Z", "updateTime": "2026-10-01T00:00:00.000Z"}
    args = json.dumps({"command": "echo hi-deepcode", "description": "say hi", "sideEffects": ["read-in-cwd"]})
    rows = [
        {**base, "id": "s1", "role": "system", "content": "You are a helpful software engineer assistant.",
         "messageParams": None, "visible": False},
        {**base, "id": "s2", "role": "system",
         "content": f'# Local Workspace Environment\n```json\n{{"root path": "{cwd}"}}\n```\nzebracorninjected',
         "messageParams": None, "visible": False},
        {**base, "id": "u1", "role": "user", "content": "hello zebracorndeepcode", "messageParams": None,
         "visible": True, "meta": {"userPrompt": {"text": "hello zebracorndeepcode"}}},
        {**base, "id": "a1", "role": "assistant", "content": " ", "visible": False,
         "messageParams": {"tool_calls": [{"id": "call_1", "type": "function",
                                           "function": {"name": "bash", "arguments": args}}],
                           "reasoning_content": "zebracornthinking"},
         "meta": {"asThinking": True}},
        {**base, "id": "t1", "role": "tool", "visible": True, "messageParams": {"tool_call_id": "call_1"},
         "content": json.dumps({"ok": True, "name": "bash", "output": "hi zebracorndeepcodetool\n",
                                "metadata": {"exitCode": 0, "cwd": cwd}}, indent=2),
         "meta": {"function": {"name": "bash", "arguments": args}}},
        {**base, "id": "s3", "role": "system", "content": "There are earlier parts of the conversation. zebracorninjected",
         "messageParams": None, "visible": False, "meta": {"isSummary": True}},
        {**base, "id": "a2", "role": "assistant", "content": "all done zebracorndeepcode", "visible": True,
         "messageParams": {"reasoning_content": "zebracornthinking"}},
    ]
    path = pdir / f"{sid}.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    (pdir / "sessions-index.json").write_text(json.dumps({
        "version": 1, "originalPath": cwd,
        "entries": [{"id": sid, "summary": "hello zebracorndeepcode", "assistantReply": "all done",
                     "status": "completed", "createTime": base["createTime"], "updateTime": base["updateTime"]}]},
        indent=2), encoding="utf-8")
    return str(path)
