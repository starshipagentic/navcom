"""Aider (PyPI aider-chat) ─ <project>/.aider.chat.history.md, one navcom session per
"# aider chat started at <ts>" header, keyed "<history file>#<n>" (n = 1-based header ordinal).

Markdown written by aider/io.py (verified against aider 0.59 – 0.86.2):
  #### <line>␠␠          user input (every line of a multi-line message is prefixed; lines end "  ")
  > <line>␠␠             tool_output / tool_error / confirm_ask notes ("Running <cmd>", "Applied edit to x")
  <plain markdown>        assistant reply (ai_output: stripped content between blank lines)
Shell-command stdout is NOT written to the file (aider only prints it), so `tool` turns are aider's
own notes (edits applied, errors, "Added N lines of output to the chat").

No global index: files live in each git root / launch dir. Spotlight skips dotfiles, so discovery is a
bounded walk of ~ (cached for AIDER_RESCAN_SECONDS in navcom's index dir) plus $AIDER_CHAT_HISTORY_FILE.
"""
import importlib.util
import json
import os
import re
import time
from pathlib import Path

spec = importlib.util.spec_from_file_location("nav", str(__import__("pathlib").Path(__file__).resolve().parents[3] / "navcom.py"))
nav = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nav)

AIDER_HISTORY_NAME = ".aider.chat.history.md"
AIDER_SCAN_DEPTH = 5            # ~1s on a dev Mac; finds 141/144 histories (depth 6: 2.3s, 144)
AIDER_RESCAN_SECONDS = 3600
_AIDER_SKIP_DIRS = {"node_modules", "Library", "Applications", "Pictures", "Movies", "Music", "venv",
                    "__pycache__", "site-packages", "dist", "build", "target"}
_AIDER_HDR_RE = re.compile(rb"^# aider chat started at (\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)[ \t]*\r?$", re.M)
_AIDER_NOTE_SKIP_RE = re.compile(r"^(Tokens: .* sent|Cost: \$|.*\(Y\)es/\(N\)o.*:|Add the output to the chat\?)", re.I)
_AIDER_CHAT_CMD_RE = re.compile(r"^/(ask|code|architect|context)\s+(.+)$", re.S)
_AIDER_SHELL_RE = re.compile(r"^(?:/run|/test|!)\s*(.+)$", re.S)


def aider_roots():
    roots = [Path.home()]
    explicit = nav._env_path("AIDER_CHAT_HISTORY_FILE")
    if explicit:
        roots.insert(0, explicit)
    return roots


def _aider_walk(root, depth):
    found = []
    root = str(root)
    base = root.rstrip(os.sep).count(os.sep)
    for folder, dirs, files in os.walk(root):
        level = folder.count(os.sep) - base
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in _AIDER_SKIP_DIRS] if level < depth else []
        found.extend(os.path.join(folder, f) for f in files if f.endswith(AIDER_HISTORY_NAME))
    return found


def _aider_cache_path():
    return nav.default_index_path().parent / "navcom-aider-paths.json"


def _aider_history_files():
    """Every aider chat history under ~ (bounded walk, cached) plus $AIDER_CHAT_HISTORY_FILE."""
    home, cache_path, paths = str(Path.home()), _aider_cache_path(), None
    try:
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
        if cache.get("home") == home and time.time() - cache.get("scanned_at", 0) < AIDER_RESCAN_SECONDS:
            paths = cache.get("paths") or []
    except Exception:
        pass
    if paths is None:
        paths = sorted(_aider_walk(home, AIDER_SCAN_DEPTH))
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = cache_path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"home": home, "scanned_at": time.time(), "paths": paths}), encoding="utf-8")
            os.chmod(tmp, 0o600)
            tmp.replace(cache_path)
        except OSError:
            pass
    explicit = nav._env_path("AIDER_CHAT_HISTORY_FILE")
    if explicit and str(explicit) not in paths:
        paths = [str(explicit)] + list(paths)
    return [Path(p) for p in paths]


def _aider_sections(data):
    """[(n, start, end, header_ts_or_None)] — n=0 is text before the first header (old/odd files)."""
    heads = list(_AIDER_HDR_RE.finditer(data))
    sections = []
    first = heads[0].start() if heads else len(data)
    if data[:first].strip():
        sections.append((0, 0, first, None))
    for i, m in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(data)
        sections.append((i + 1, m.start(), end, m.group(1).decode()))
    return sections


def _aider_epoch(ts):
    try:
        return time.mktime(time.strptime(ts, "%Y-%m-%d %H:%M:%S"))  # aider writes local time
    except Exception:
        return 0.0


def aider_list():
    """One navcom session per `# aider chat started at` header. The per-file split is cached by
    (mtime, size), so a search re-reads only history files that changed since the last run."""
    cache_path = _aider_cache_path().with_name("navcom-aider-sections.json")
    try:
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception:
        cache = {}
    logs, fresh, dirty = [], {}, False
    for path in _aider_history_files():
        try:
            stat = path.stat()
        except OSError:
            continue
        entry = cache.get(str(path))
        if not entry or entry.get("mtime") != stat.st_mtime or entry.get("size") != stat.st_size:
            try:
                data = path.read_bytes()
            except OSError:
                continue
            sections, rows = _aider_sections(data), []
            for i, (n, start, end, _ts) in enumerate(sections):
                if b"\n#### " not in data[start:end]:
                    continue  # aider started and quit without a prompt
                nxt = sections[i + 1][3] if i + 1 < len(sections) else None
                mtime = (_aider_epoch(nxt) or stat.st_mtime) if nxt else stat.st_mtime
                rows.append([f"{path}#{n}", mtime, end - start])
            entry, dirty = {"mtime": stat.st_mtime, "size": stat.st_size, "rows": rows}, True
        fresh[str(path)] = entry
        logs.extend((key, mtime, size, "aider") for key, mtime, size in entry["rows"])
    if dirty or set(fresh) != set(cache):
        try:
            tmp = cache_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(fresh), encoding="utf-8")
            os.chmod(tmp, 0o600)
            tmp.replace(cache_path)
        except OSError:
            pass
    return logs


def _aider_split_key(key):
    path, _, n = str(key).rpartition("#")
    if not path or not n.isdigit():
        return str(key), None
    return path, int(n)


def _aider_section_text(key):
    path, n = _aider_split_key(key)
    try:
        data = Path(path).read_bytes()
    except OSError:
        return ""
    for num, start, end, _ts in _aider_sections(data):
        if n is None or num == n:
            return data[start:end].decode("utf-8", errors="replace")
    return ""


def _aider_blocks(text):
    """('hdr'|'user'|'note'|'text', [lines]) groups in file order."""
    blocks = []
    for line in text.splitlines():
        if _AIDER_HDR_RE.match(line.encode("utf-8", "replace")):
            kind, body = "hdr", line
        elif line.startswith("#### ") and line.endswith("  ") or line.rstrip() == "####":
            kind, body = "user", line[5:].rstrip()
        elif (line.startswith("> ") or line.rstrip() == ">") and line.endswith("  ") or line == ">  ":
            kind, body = "note", line[2:].rstrip()
        elif line.endswith("  ") and _AIDER_NOTE_SKIP_RE.match(line.strip()):
            # old aider wrapped confirm prompts: "> Add the output to the chat?\n(Y)es/(n)o/...: n  "
            kind, body = "note", line[2:].rstrip()
        else:
            kind, body = "text", line
        if blocks and blocks[-1][0] == kind:
            blocks[-1][1].append(body)
        else:
            blocks.append((kind, [body]))
    return blocks


def aider_iter(key):
    seen_user, last_reply, echo, cmd_label = False, "", None, None
    for kind, lines in _aider_blocks(_aider_section_text(key)):
        body = "\n".join(lines).strip()
        if kind == "hdr" or not body:
            continue
        if kind == "user":
            seen_user = True
            if body == "<blank>":
                continue
            if echo is not None and body == echo:
                echo = None
                continue  # /ask X is re-logged as "#### X"
            echo = None
            if "# Announcement lines from when this session of aider was launched:" in body:
                continue  # /help builds a docs-stuffed prompt and logs it as user input
            if last_reply and " ".join(body.split()) == " ".join(last_reply.split()):
                continue  # architect mode hands its plan to the editor coder as a "user" message
            yield "user", body
            cmd_label = None
            m = _AIDER_CHAT_CMD_RE.match(body)
            if m:
                echo = m.group(2).strip()
            m = _AIDER_SHELL_RE.match(body)
            if m and m.group(1).strip():
                cmd = m.group(1).strip()
                yield "cmd", cmd
                cmd_label = nav._call_label("Bash", {"command": cmd})
        elif kind == "text":
            if seen_user:
                last_reply = body
                yield "assistant", body
        elif kind == "note":
            if not seen_user:
                continue  # launch banner: argv, version, model, repo-map
            notes = []

            def flush():
                turn = nav.tool_turn(cmd_label or "aider", "\n".join(notes))
                notes.clear()
                return turn
            for line in lines:
                line = line.strip()
                if line.startswith("Running ") and len(line) > 8:
                    if notes:
                        turn = flush()
                        if turn:
                            yield turn
                    cmd = line[8:].strip()
                    yield "cmd", cmd
                    cmd_label = nav._call_label("Bash", {"command": cmd})
                elif line.startswith(("Run shell command", "Run shell commands")):
                    # the commands echoed just before this prompt are a proposal from the reply, not output
                    proposed = {ln.strip() for ln in last_reply.splitlines()}
                    while notes and notes[-1] in proposed:
                        notes.pop()
                elif line and not _AIDER_NOTE_SKIP_RE.match(line):
                    notes.append(line)
            # the command echoed before "Run shell command?" is a proposal, not output
            if notes:
                turn = flush()
                if turn:
                    yield turn


def aider_project(key):
    path, _ = _aider_split_key(key)
    return str(Path(path).parent)


def aider_title(key):
    return ""  # aider stores no titles


def aider_fixture(home, cwd):
    home = Path(home)
    project = Path(cwd)
    try:
        project.relative_to(home)
    except ValueError:
        project = home / "dev" / (project.name or "proj")
    project.mkdir(parents=True, exist_ok=True)
    hist = project / AIDER_HISTORY_NAME
    hist.write_text(
        "\n# aider chat started at 2026-09-30 10:00:00\n\n"
        "> /usr/local/bin/aider --model openrouter/deepseek/deepseek-chat-v3.1  \n"
        "> Aider v0.86.2  \n> Model: openrouter/deepseek/deepseek-chat-v3.1 with diff edit format  \n"
        "> Git repo: none  \n\n"
        "#### quit  \n\n"
        "\n# aider chat started at 2026-10-01 09:00:00\n\n"
        "> Aider v0.86.2  \n> zebracorninjected banner note  \n\n"
        "#### /help how do I run tests  \n\n"
        "#### # Question: how do I zebracorninjected  \n"
        "#### # Announcement lines from when this session of aider was launched:  \n"
        "#### Aider v0.86.2  \n\n"
        "Use /run.\n\n"
        "#### please check zebracornaider  \n"
        "#### second line  \n\n"
        "Sure, zebracornaider reply.\n\n"
        "```bash\necho hi-aider\n```\n\n"
        "> Tokens: 2.4k sent, 34 received. Cost: $0.00064 message, $0.00064 session.  \n"
        "> echo hi-aider  \n"
        "> Run shell command? (Y)es/(N)o/(D)on't ask again [Yes]: y  \n"
        "> Running echo hi-aider  \n"
        "> zebracornaidertool: command printed an error  \n"
        "> Add command output to the chat? (Y)es/(N)o/(D)on't ask again [Yes]: y  \n"
        "> Added 1 line of output to the chat.  \n",
        encoding="utf-8")
    return f"{hist}#2"
