#!/usr/bin/env python3
"""
navcom.py
==========
Super-fast search over past AI coding-agent sessions (Claude Code, Codex,
Gemini CLI, pi, omo, opencode, goose):
1) cleans each session into user / assistant / cmd turns
2) indexes the cleaned turns with SQLite FTS5 (incremental, shared index)
3) searches them — compact hits by default, windows with --context, --open to read
4) optionally summarizes those windows with whatever LLM CLI is around

This file embeds full copies of log_clean_quick + log_search_fts5 for function reuse.
"""
# Repo lives under github.com/starshipagentic/navcom.

import argparse
import collections
import io
import json
import shlex
import shutil
import subprocess
import os
import re
import sqlite3
import sys
import types
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

SUMMARY_MODEL_DEFAULT = "gemma3:4b"
DEFAULT_VERBOSITY = 1
GIT_LIMIT_DEFAULT = 3
GIT_ROLE_DEFAULT = "assistant"

LOG_CLEAN_QUICK_CODE = '#!/usr/bin/env python3\n"""\nlog_clean_quick.py\n=================\n\nPurpose\n-------\nClean and condense CLI logs (Codex/Claude/Gemini) into readable, line-broken\nuser + model turns, with optional command extraction.\n\nKey behaviors\n-------------\n- Drops provider-specific preamble noise (AGENTS.md, environment context, CLI caveats).\n- Preserves original line breaks inside messages.\n- Labels assistant output by provider name (codex/claude/gemini).\n- Emits `cmd:` lines from tool-call commands (default) and/or regex bash scraping.\n- Supports verbosity levels (10 = raw, 5 = structured summary via Ollama).\n- Automatically chunks large transcripts based on model context limits.\n- Writes chunk inputs/outputs to dump/ for inspection (verbosity 5).\n- Supports prompt overrides via --prompt-file.\n- Supports filtering to turns containing a query (--query).\n\nQuick usage\n-----------\npython3 log_clean_quick.py              # autodetect provider, last convo\npython3 log_clean_quick.py --all        # all providers, last convo each\npython3 log_clean_quick.py --codex      # codex only\npython3 log_clean_quick.py --no-cmds    # disable tool-call command extraction\npython3 log_clean_quick.py --include-bash\npython3 log_clean_quick.py --verbosity 5 --summary-model gemma3:4b\npython3 log_clean_quick.py --verbosity 5 --summary-mode reduce\npython3 log_clean_quick.py --verbosity 5 --dump-dir dump\npython3 log_clean_quick.py --verbosity 5 --prompt-file dump2/prompt2.txt\npython3 log_clean_quick.py --query diary --claude --recent 50\n"""\nimport argparse\nimport json\nimport os\nimport re\nimport sys\nimport subprocess\nimport signal\nfrom datetime import datetime, timezone\nfrom pathlib import Path\n\n\ntry:\n    signal.signal(signal.SIGPIPE, signal.SIG_DFL)\nexcept Exception:\n    pass\n\n\ndef safe_print(text):\n    try:\n        print(text)\n    except BrokenPipeError:\n        sys.exit(0)\n\n\ndef parse_ts(value):\n    if not value:\n        return None\n    if isinstance(value, (int, float)):\n        return datetime.fromtimestamp(value, tz=timezone.utc)\n    if isinstance(value, str):\n        text = value.strip()\n        if not text:\n            return None\n        try:\n            return datetime.fromisoformat(text.replace("Z", "+00:00"))\n        except Exception:\n            return None\n    return None\n\n\ndef latest_jsonl_timestamp(path):\n    try:\n        data = path.read_bytes()\n    except Exception:\n        return None\n    if not data:\n        return None\n    idx = data.rfind(b"\\n")\n    if idx == -1:\n        line = data\n    else:\n        line = data[idx + 1 :] or data[:idx]\n    try:\n        obj = json.loads(line.decode("utf-8", errors="replace"))\n    except Exception:\n        return None\n    return parse_ts(obj.get("timestamp"))\n\n\ndef latest_gemini_timestamp(path):\n    try:\n        obj = json.loads(path.read_text(encoding="utf-8", errors="replace"))\n    except Exception:\n        return None\n    ts = parse_ts(obj.get("lastUpdated"))\n    if ts:\n        return ts\n    messages = obj.get("messages") or []\n    for msg in reversed(messages):\n        if isinstance(msg, dict):\n            ts = parse_ts(msg.get("timestamp"))\n            if ts:\n                return ts\n    return None\n\n\ndef list_logs(root, pattern):\n    logs = []\n    if not root.exists():\n        return logs\n    for path in root.rglob(pattern):\n        try:\n            stat = path.stat()\n        except OSError:\n            continue\n        logs.append((path, stat.st_mtime))\n    logs.sort(key=lambda x: x[1])\n    return logs\n\n\ndef latest_files_for_provider(provider, recent):\n    home = Path.home()\n    if provider == "codex":\n        root = Path(os.environ.get("CODEX_HOME", home / ".codex")) / "sessions"\n        return [p for p, _ in list_logs(root, "*.jsonl")[-recent:]]\n    if provider == "claude":\n        root = Path(os.environ.get("CLAUDE_CONFIG_DIR", home / ".claude")) / "projects"\n        return [p for p, _ in list_logs(root, "*.jsonl")[-recent:]]\n    if provider == "gemini":\n        root = home / ".gemini" / "tmp"\n        return [p for p, _ in list_logs(root, "chats/*.json")[-recent:]]\n    return []\n\n\ndef detect_latest_provider():\n    providers = ["codex", "claude", "gemini"]\n    latest = {}\n    for provider in providers:\n        files = latest_files_for_provider(provider, 1)\n        if not files:\n            continue\n        path = files[-1]\n        if provider == "gemini":\n            ts = latest_gemini_timestamp(path)\n        else:\n            ts = latest_jsonl_timestamp(path)\n        if not ts:\n            try:\n                ts = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)\n            except Exception:\n                ts = None\n        latest[provider] = (ts, path)\n    best = None\n    for provider, (ts, path) in latest.items():\n        if not ts:\n            continue\n        if not best or ts > best[0]:\n            best = (ts, provider, path)\n    return best[1] if best else None\n\n\ndef clean_text(text):\n    lines = text.splitlines()\n    cleaned = [line.rstrip() for line in lines]\n    while cleaned and not cleaned[0].strip():\n        cleaned.pop(0)\n    while cleaned and not cleaned[-1].strip():\n        cleaned.pop()\n    return "\\n".join(cleaned)\n\n\ndef label_for_role(role, provider):\n    if role == "assistant":\n        return provider\n    if role == "user":\n        return "user"\n    if role == "cmd":\n        return "cmd"\n    return role\n\n\ndef is_preamble(role, text, provider):\n    if role != "user":\n        return False\n    stripped = text.strip()\n    if not stripped:\n        return False\n    codex_markers = [\n        "# AGENTS.md instructions",\n        "<INSTRUCTIONS>",\n        "<environment_context>",\n    ]\n    claude_markers = [\n        "Caveat: The messages below were generated by the user while running local commands.",\n        "<command-name>",\n        "<local-command-stdout>",\n    ]\n    markers = []\n    if provider == "codex":\n        markers = codex_markers\n    elif provider == "claude":\n        markers = claude_markers\n    else:\n        markers = codex_markers + claude_markers\n    for marker in markers:\n        if marker in stripped:\n            return True\n    return False\n\n\ndef extract_text_content(content, include_tools):\n    if isinstance(content, str):\n        return content\n    parts = []\n    if isinstance(content, list):\n        for item in content:\n            if not isinstance(item, dict):\n                continue\n            item_type = item.get("type")\n            if item_type == "text":\n                parts.append(item.get("text", ""))\n            elif item_type in ("input_text", "output_text"):\n                parts.append(item.get("text", ""))\n            elif item_type == "tool_use" and include_tools:\n                parts.append(item.get("name", "tool"))\n    return "\\n".join([p for p in parts if p]).strip()\n\n\ndef extract_cmd_from_input(input_obj):\n    if isinstance(input_obj, dict):\n        for key in ("command", "cmd", "script", "args"):\n            value = input_obj.get(key)\n            if isinstance(value, str) and value.strip():\n                return value.strip()\n    if isinstance(input_obj, str) and input_obj.strip():\n        return input_obj.strip()\n    return None\n\n\ndef extract_cmd_from_tool_result(text):\n    if not text:\n        return None\n    for line in text.splitlines():\n        stripped = line.strip()\n        if stripped.startswith(("$ ", "> ")):\n            return stripped[2:].strip()\n        if stripped.lower().startswith("command:"):\n            return stripped.split(":", 1)[1].strip()\n        if stripped.lower().startswith("cmd:"):\n            return stripped.split(":", 1)[1].strip()\n    return None\n\n\ndef format_cmd(text):\n    return re.sub(r"\\s+", " ", text.strip())\n\n\ndef should_capture_cmd(name, input_obj):\n    if isinstance(input_obj, dict) and any(key in input_obj for key in ("command", "cmd", "script")):\n        return True\n    if not name:\n        return False\n    lower = name.lower()\n    return any(token in lower for token in ("bash", "shell", "command", "cmd"))\n\n\ndef extract_bash_commands(text):\n    commands = []\n    fence_re = re.compile(r"```(?:bash|sh|zsh|shell)?\\n(.*?)```", re.DOTALL | re.IGNORECASE)\n    for match in fence_re.findall(text):\n        for line in match.splitlines():\n            stripped = line.strip()\n            if not stripped:\n                continue\n            if stripped.startswith(("$ ", "> ")):\n                stripped = stripped[2:].strip()\n            commands.append(stripped)\n    for line in text.splitlines():\n        stripped = line.strip()\n        if stripped.startswith(("$ ", "> ")):\n            commands.append(stripped[2:].strip())\n    deduped = []\n    seen = set()\n    for cmd in commands:\n        if not cmd or cmd in seen:\n            continue\n        seen.add(cmd)\n        deduped.append(cmd)\n    return deduped\n\n\nMODEL_CONTEXT_LIMITS = {\n    "gemma3:1b": 32768,\n    "gemma3:4b": 128000,\n    "gemma3:12b": 128000,\n    "gemma3:27b": 128000,\n    "granite4": 128000,\n    "granite4:8b": 128000,\n    "granite4:20b": 128000,\n}\nDEFAULT_CONTEXT_LIMIT = 32768\nCHARS_PER_TOKEN = 4\nSUMMARY_INPUT_FRACTION = 0.7\nSUMMARY_OUTPUT_TOKENS = 1024\nSUMMARY_MAX_PASSES = 4\nDUMP_DIR_DEFAULT = "dump"\nMODEL_VERBOSITY_DEFAULTS = {\n    "qwen3-vl:4b": 5,\n    "gemma3:4b": 4,\n}\n\n\ndef render_prompt_template(template, transcript, chunk_index=None, chunk_total=None):\n    text = template\n    if "{{transcript}}" not in text:\n        text = text.rstrip() + "\\n\\nTranscript:\\n{{transcript}}\\n"\n    text = text.replace("{{transcript}}", transcript)\n    text = text.replace("{{chunk_index}}", "" if chunk_index is None else str(chunk_index))\n    text = text.replace("{{chunk_total}}", "" if chunk_total is None else str(chunk_total))\n    return text\n\n\ndef build_summary_prompt(transcript, chunk_index=None, chunk_total=None, prompt_template=None):\n    if prompt_template:\n        return render_prompt_template(prompt_template, transcript, chunk_index, chunk_total)\n    chunk_note = ""\n    if chunk_index is not None and chunk_total:\n        chunk_note = f"(chunk {chunk_index} of {chunk_total})\\n"\n    return (\n        f"{transcript}\\n\\n"\n        "========\\n"\n        f"{chunk_note}"\n        "summarize the major categories of what i did in this conversation, "\n        "what decisions where made and why, and what code artifacts we created "\n        "or touched, and a list of common commands and their context:\\n"\n        "include .md, .yaml, and any code as artifacts\\n"\n    )\n\n\ndef build_meta_summary_prompt(summary_text):\n    return (\n        "You are consolidating multiple chunk summaries into one final handoff memo.\\n\\n"\n        "Input: summaries from earlier chunks.\\n\\n"\n        "Your job:\\n"\n        "1) Produce one consolidated summary (no duplicates).\\n"\n        "2) Keep the same sections as before (work, decisions, artifacts, commands, next steps, risks).\\n"\n        "3) Stay concise and factual.\\n\\n"\n        "Chunk summaries:\\n"\n        f"{summary_text}\\n"\n    )\n\n\ndef ensure_dump_dir(base_dir):\n    if not base_dir:\n        return None\n    base = Path(base_dir).expanduser()\n    base.mkdir(parents=True, exist_ok=True)\n    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")\n    run_dir = base / f"log_clean_quick-{timestamp}"\n    run_dir.mkdir(parents=True, exist_ok=True)\n    return run_dir\n\n\ndef write_dump_file(dump_dir, name, content):\n    if not dump_dir:\n        return\n    path = dump_dir / name\n    path.write_text(content, encoding="utf-8")\n\n\ndef write_manifest(dump_dir, data):\n    if not dump_dir:\n        return\n    manifest = dump_dir / "manifest.json"\n    manifest.write_text(json.dumps(data, indent=2), encoding="utf-8")\n\n\ndef estimate_tokens(text):\n    if not text:\n        return 0\n    return max(1, int(len(text) / CHARS_PER_TOKEN))\n\n\ndef model_context_limit(model):\n    if not model:\n        return DEFAULT_CONTEXT_LIMIT\n    for key, limit in MODEL_CONTEXT_LIMITS.items():\n        if model == key or model.startswith(key):\n            return limit\n    return DEFAULT_CONTEXT_LIMIT\n\n\ndef model_default_verbosity(model):\n    if not model:\n        return None\n    for key, value in MODEL_VERBOSITY_DEFAULTS.items():\n        if model == key or model.startswith(key):\n            return value\n    return None\n\n\ndef matches_query(text, query):\n    if not query:\n        return True\n    return query.lower() in text.lower()\n\n\ndef summary_char_budget(model, prompt_template=None):\n    base_prompt = build_summary_prompt("", prompt_template=prompt_template)\n    limit_tokens = model_context_limit(model)\n    base_tokens = estimate_tokens(base_prompt)\n    budget_tokens = int(limit_tokens * SUMMARY_INPUT_FRACTION) - base_tokens - SUMMARY_OUTPUT_TOKENS\n    if budget_tokens < 1024:\n        budget_tokens = 1024\n    return budget_tokens * CHARS_PER_TOKEN\n\n\ndef chunk_text_by_lines(text, max_chars):\n    if not text:\n        return []\n    lines = text.splitlines()\n    chunks = []\n    current = []\n    current_len = 0\n    for line in lines:\n        line_len = len(line) + 1\n        if line_len > max_chars:\n            if current:\n                chunks.append("\\n".join(current))\n                current = []\n                current_len = 0\n            start = 0\n            while start < len(line):\n                chunks.append(line[start : start + max_chars])\n                start += max_chars\n            continue\n        if current and current_len + line_len > max_chars:\n            chunks.append("\\n".join(current))\n            current = [line]\n            current_len = line_len\n        else:\n            current.append(line)\n            current_len += line_len\n    if current:\n        chunks.append("\\n".join(current))\n    return chunks\n\n\ndef summarize_chunks(chunks, model, dump_dir=None, prefix="chunk", prompt_template=None):\n    summaries = []\n    total = len(chunks)\n    for idx, chunk in enumerate(chunks, 1):\n        prompt = build_summary_prompt(\n            chunk,\n            chunk_index=idx,\n            chunk_total=total,\n            prompt_template=prompt_template,\n        )\n        summary, error = run_ollama(model, prompt)\n        if error:\n            return None, error\n        if dump_dir:\n            base = f"{prefix}-{idx:03d}"\n            write_dump_file(dump_dir, f"{base}.input.txt", chunk)\n            write_dump_file(dump_dir, f"{base}.summary.txt", summary.strip())\n        summaries.append(summary.strip())\n    return summaries, None\n\n\ndef reduce_summaries(text, model, max_chars, dump_dir=None, prompt_template=None):\n    reduced = text\n    for pass_idx in range(1, SUMMARY_MAX_PASSES + 1):\n        if len(reduced) <= max_chars:\n            break\n        if dump_dir:\n            write_dump_file(dump_dir, f"reduce-pass-{pass_idx}-input.txt", reduced)\n        chunks = chunk_text_by_lines(reduced, max_chars)\n        summaries, error = summarize_chunks(\n            chunks,\n            model,\n            dump_dir,\n            prefix=f"reduce{pass_idx}-chunk",\n            prompt_template=prompt_template,\n        )\n        if error:\n            return None, error\n        reduced = "\\n\\n".join(\n            f"Chunk {idx + 1}/{len(summaries)} summary:\\n{summary}"\n            for idx, summary in enumerate(summaries)\n        )\n        if dump_dir:\n            write_dump_file(dump_dir, f"reduce-pass-{pass_idx}-output.txt", reduced)\n    return reduced, None\n\n\ndef summarize_transcript(transcript, model, mode="chrono", dump_dir=None, prompt_template=None):\n    max_chars = summary_char_budget(model, prompt_template=prompt_template)\n    if len(transcript) <= max_chars and mode == "reduce":\n        prompt = build_summary_prompt(transcript, prompt_template=prompt_template)\n        summary, error = run_ollama(model, prompt)\n        if not error and dump_dir:\n            write_dump_file(dump_dir, "chunk-001.input.txt", transcript)\n            write_dump_file(dump_dir, "chunk-001.summary.txt", summary)\n            write_dump_file(dump_dir, "final-summary.txt", summary)\n        return summary, error\n\n    chunks = chunk_text_by_lines(transcript, max_chars)\n    summaries, error = summarize_chunks(chunks, model, dump_dir=dump_dir, prompt_template=prompt_template)\n    if error:\n        return None, error\n    combined = "\\n\\n".join(\n        f"Chunk {idx + 1}/{len(summaries)} summary:\\n{summary}"\n        for idx, summary in enumerate(summaries)\n    )\n    if dump_dir:\n        write_dump_file(dump_dir, "chunk-summaries.txt", combined)\n\n    if mode == "chrono":\n        if dump_dir:\n            write_dump_file(dump_dir, "final-summary.txt", combined)\n        return combined, None\n\n    combined, error = reduce_summaries(\n        combined,\n        model,\n        max_chars,\n        dump_dir=dump_dir,\n        prompt_template=prompt_template,\n    )\n    if error:\n        return None, error\n\n    final_prompt = build_meta_summary_prompt(combined)\n    summary, error = run_ollama(model, final_prompt)\n    if not error and dump_dir:\n        write_dump_file(dump_dir, "final-summary.txt", summary)\n    return summary, error\n\n\ndef run_ollama(model, prompt):\n    try:\n        result = subprocess.run(\n            ["ollama", "run", model],\n            input=prompt,\n            text=True,\n            capture_output=True,\n            check=False,\n        )\n    except FileNotFoundError:\n        return None, "ollama not found in PATH"\n    if result.returncode != 0:\n        return None, result.stderr.strip() or "ollama failed"\n    return result.stdout.strip(), None\n\n\ndef iter_codex(path, include_tools, include_cmds):\n    with path.open("r", encoding="utf-8", errors="replace") as handle:\n        for line in handle:\n            try:\n                obj = json.loads(line)\n            except Exception:\n                continue\n            msg_type = obj.get("type")\n            if msg_type == "response_item":\n                payload = obj.get("payload", {})\n                if payload.get("type") == "function_call" and include_cmds:\n                    name = payload.get("name")\n                    if name == "shell_command":\n                        try:\n                            args = json.loads(payload.get("arguments", "{}"))\n                        except Exception:\n                            args = {}\n                        cmd = args.get("command")\n                        if cmd:\n                            yield "cmd", cmd\n                    continue\n                if payload.get("type") != "message":\n                    continue\n                role = payload.get("role")\n                text = extract_text_content(payload.get("content", []), include_tools)\n                if text:\n                    yield role or "assistant", text\n            elif msg_type == "event_msg":\n                payload = obj.get("payload", {})\n                ptype = payload.get("type")\n                if ptype == "user_message":\n                    yield "user", payload.get("message", "")\n                elif ptype == "agent_message":\n                    yield "assistant", payload.get("message", "")\n\n\ndef iter_claude(path, include_tools, include_cmds):\n    with path.open("r", encoding="utf-8", errors="replace") as handle:\n        for line in handle:\n            try:\n                obj = json.loads(line)\n            except Exception:\n                continue\n            message = obj.get("message")\n            if isinstance(message, dict):\n                role = message.get("role")\n                content = message.get("content")\n                if include_cmds and isinstance(content, list):\n                    for item in content:\n                        if not isinstance(item, dict):\n                            continue\n                        if item.get("type") != "tool_use":\n                            continue\n                        name = item.get("name")\n                        input_obj = item.get("input")\n                        if not should_capture_cmd(name, input_obj):\n                            continue\n                        cmd = extract_cmd_from_input(input_obj)\n                        if cmd:\n                            yield "cmd", cmd\n                text = extract_text_content(content, include_tools)\n                if text and role in ("user", "assistant"):\n                    yield role, text\n                continue\n            role = obj.get("role")\n            if role in ("user", "assistant"):\n                content = obj.get("content")\n                text = extract_text_content(content, include_tools)\n                if text:\n                    yield role, text\n            if include_cmds and isinstance(message, dict):\n                content = message.get("content")\n                if isinstance(content, list):\n                    for item in content:\n                        if not isinstance(item, dict):\n                            continue\n                        if item.get("type") != "tool_result":\n                            continue\n                        cmd = extract_cmd_from_tool_result(item.get("content", ""))\n                        if cmd:\n                            yield "cmd", cmd\n\n\ndef iter_gemini(path, include_tools, include_cmds):\n    try:\n        obj = json.loads(path.read_text(encoding="utf-8", errors="replace"))\n    except Exception:\n        return\n    for msg in obj.get("messages", []):\n        if not isinstance(msg, dict):\n            continue\n        msg_type = msg.get("type")\n        if msg_type == "user":\n            role = "user"\n        elif msg_type in ("gemini", "assistant", "model"):\n            role = "assistant"\n        else:\n            continue\n        text = msg.get("content", "")\n        if text:\n            yield role, text\n        if include_cmds and isinstance(msg.get("toolCalls"), list):\n            for call in msg.get("toolCalls"):\n                name = call.get("name")\n                args_obj = call.get("args")\n                if not should_capture_cmd(name, args_obj):\n                    continue\n                cmd = extract_cmd_from_input(args_obj)\n                if not cmd:\n                    cmd = extract_cmd_from_input(call.get("result"))\n                if cmd:\n                    yield "cmd", cmd\n        if include_tools and isinstance(msg.get("toolCalls"), list):\n            for call in msg.get("toolCalls"):\n                result = call.get("resultDisplay")\n                if isinstance(result, str) and result.strip():\n                    yield "tool", result\n\n\ndef detect_provider_from_path(path):\n    path_str = str(path)\n    if path_str.endswith(".json"):\n        return "gemini"\n    if "/.claude/" in path_str:\n        return "claude"\n    if "/.codex/" in path_str:\n        return "codex"\n    return "codex"\n\n\ndef main():\n    parser = argparse.ArgumentParser(\n        description="Quickly clean CLI logs into compact user/assistant lines.",\n        formatter_class=argparse.RawTextHelpFormatter,\n    )\n    parser.add_argument("--codex", action="store_true", help="Use Codex logs.")\n    parser.add_argument("--claude", action="store_true", help="Use Claude logs.")\n    parser.add_argument("--gemini", action="store_true", help="Use Gemini logs.")\n    parser.add_argument("--all", action="store_true", help="Use all providers.")\n    parser.add_argument("--recent", type=int, default=1, help="Logs per provider (default: 1).")\n    parser.add_argument("--file", action="append", help="Log file path (repeatable).")\n    parser.add_argument("--include-tools", action="store_true", help="Include tool call summaries.")\n    parser.add_argument("--include-bash", action="store_true", help="Extract bash-style commands from text.")\n    parser.add_argument(\n        "--include-cmds",\n        action="store_true",\n        default=True,\n        help="Include shell commands from tool calls (default).",\n    )\n    parser.add_argument(\n        "--no-cmds",\n        action="store_false",\n        dest="include_cmds",\n        help="Disable tool-call command extraction.",\n    )\n    parser.add_argument("--no-header", action="store_true", help="Suppress file headers.")\n    parser.add_argument("--max-chars", type=int, default=0, help="Max chars per message.")\n    parser.add_argument("--query", help="Filter to turns containing this term (case-insensitive).")\n    parser.add_argument(\n        "--tour",\n        action="store_true",\n        help="Run a guided demo of cleaned output with colorized separators.",\n    )\n    parser.add_argument(\n        "--verbosity",\n        type=int,\n        default=None,\n        help="Verbosity level (1-10). Implemented: 10=raw, 5=summary. Default: model-based or 10.",\n    )\n    parser.add_argument(\n        "--summary-model",\n        default="gemma3:4b",\n        help="Ollama model name for summaries (used with verbosity 5).",\n    )\n    parser.add_argument(\n        "--prompt-file",\n        help="Path to a prompt template file (use {{transcript}} placeholder).",\n    )\n    parser.add_argument(\n        "--summary-mode",\n        choices=["chrono", "reduce"],\n        default="chrono",\n        help="Summary mode for verbosity 5 (chrono = per-chunk output, reduce = consolidated).",\n    )\n    parser.add_argument(\n        "--dump-dir",\n        default=DUMP_DIR_DEFAULT,\n        help="Base directory for dump output (verbosity 5).",\n    )\n    parser.add_argument(\n        "--no-dump",\n        action="store_true",\n        help="Disable dump output for verbosity 5.",\n    )\n    args = parser.parse_args()\n\n    if args.verbosity is None:\n        args.verbosity = model_default_verbosity(args.summary_model) or 10\n\n    if args.tour:\n        demo_sets = [\n            ("autodetect", []),\n            ("all providers", ["--all"]),\n            ("gemini only", ["--gemini"]),\n        ]\n        for idx, (label, flags) in enumerate(demo_sets, start=1):\n            safe_print("\\033[90m" + "=" * 72 + "\\033[0m")\n            safe_print("\\033[95m" + f"[{idx}/{len(demo_sets)}] {label}" + "\\033[0m")\n            safe_print("\\033[90m" + "=" * 72 + "\\033[0m")\n            cmd = [sys.executable, __file__] + flags\n            subprocess.run(cmd, check=False)\n        return 0\n\n    providers = []\n    if args.all:\n        providers = ["codex", "claude", "gemini"]\n    else:\n        if args.codex:\n            providers.append("codex")\n        if args.claude:\n            providers.append("claude")\n        if args.gemini:\n            providers.append("gemini")\n    if not providers:\n        detected = detect_latest_provider()\n        providers = [detected] if detected else ["codex"]\n\n    files = []\n    if args.file:\n        files.extend([Path(p).expanduser() for p in args.file])\n    else:\n        for provider in providers:\n            files.extend(latest_files_for_provider(provider, args.recent))\n\n    if not files:\n        safe_print("No log files found.")\n        return 1\n\n    output_lines = []\n    for path in files:\n        provider = detect_provider_from_path(path)\n        header = f"=== {provider} {path}\\n"\n        header_printed = False\n        def emit(line):\n            nonlocal header_printed\n            if not header_printed and not args.no_header:\n                if args.verbosity == 10:\n                    safe_print(header)\n                else:\n                    output_lines.append(header.rstrip())\n                header_printed = True\n            if args.verbosity == 10:\n                safe_print(f"{line}\\n")\n            else:\n                output_lines.append(line.rstrip())\n        if provider == "claude":\n            iterator = iter_claude(path, args.include_tools, args.include_cmds)\n        elif provider == "gemini":\n            iterator = iter_gemini(path, args.include_tools, args.include_cmds)\n        else:\n            iterator = iter_codex(path, args.include_tools, args.include_cmds)\n        last = None\n        for role, text in iterator:\n            raw = clean_text(text)\n            if not raw:\n                continue\n            if is_preamble(role, raw, provider):\n                continue\n            match_raw = raw\n            if args.max_chars and len(raw) > args.max_chars:\n                raw = raw[: args.max_chars] + "…"\n            if matches_query(match_raw, args.query):\n                key = (role, re.sub(r"\\s+", " ", raw.strip()))\n                if key == last:\n                    continue\n                last = key\n                label = label_for_role(role, provider)\n                if label == "cmd":\n                    line = f"cmd: {format_cmd(raw)}"\n                else:\n                    line = f"{label}:\\n{raw}\\n"\n                emit(line)\n            if args.include_bash and role in ("user", "assistant"):\n                for cmd in extract_bash_commands(raw):\n                    if not matches_query(cmd, args.query):\n                        continue\n                    line = f"cmd: {format_cmd(cmd)}"\n                    emit(line)\n        if header_printed:\n            if args.verbosity == 10:\n                safe_print("")\n            else:\n                output_lines.append("")\n\n    if args.verbosity == 10:\n        return 0\n\n    transcript = "\\n".join(output_lines).strip()\n    if args.verbosity == 5:\n        dump_dir = None\n        prompt_template = None\n        if args.prompt_file:\n            prompt_path = Path(args.prompt_file).expanduser()\n            if not prompt_path.exists():\n                safe_print(f"Prompt file not found: {prompt_path}")\n                return 1\n            prompt_template = prompt_path.read_text(encoding="utf-8")\n        if not args.no_dump:\n            dump_dir = ensure_dump_dir(args.dump_dir)\n            if dump_dir:\n                write_manifest(\n                    dump_dir,\n                    {\n                        "model": args.summary_model,\n                        "mode": args.summary_mode,\n                        "context_limit": model_context_limit(args.summary_model),\n                        "max_chunk_chars": summary_char_budget(args.summary_model, prompt_template=prompt_template),\n                        "providers": providers,\n                        "files": [str(path) for path in files],\n                        "prompt_file": str(prompt_path) if args.prompt_file else None,\n                    },\n                )\n        summary, error = summarize_transcript(\n            transcript,\n            args.summary_model,\n            mode=args.summary_mode,\n            dump_dir=dump_dir,\n            prompt_template=prompt_template,\n        )\n        if error:\n            safe_print(f"Summary error: {error}")\n            return 1\n        safe_print(summary)\n        return 0\n\n    safe_print("Only verbosity 10 (raw) and 5 (summary) are implemented.")\n    return 0\n\n\nif __name__ == "__main__":\n    sys.exit(main())\n'
LOG_CLEAN_QUICK_CODE = LOG_CLEAN_QUICK_CODE.replace(
    "--summary-model gemma3:4b",
    f"--summary-model {SUMMARY_MODEL_DEFAULT}",
)
LOG_CLEAN_QUICK_CODE = LOG_CLEAN_QUICK_CODE.replace(
    "default=\"gemma3:4b\"",
    f"default=\"{SUMMARY_MODEL_DEFAULT}\"",
)

LOG_SEARCH_FTS5_CODE = '#!/usr/bin/env python3\n"""\nlog_search_fts5.py\n==================\n\nSearch Codex CLI, Claude Code, and Gemini CLI session logs with SQLite FTS5 + commit sniffing.\n\nWhy this exists\n---------------\nYou asked for a tool that behaves like a tiny search engine for Codex sessions:\nfast keyword search, relevant snippets, and extra context (like related commits).\nThis script does that without embeddings. It uses tokenization + inverted index,\nthen (optionally) scans the surrounding conversation for commit mentions and\nresolves them against your local git repos.\n\nHigh-level flow\n---------------\n1) Read logs from Codex, Claude, and/or Gemini session folders.\n2) Index messages into a SQLite FTS5 table (incremental; no full rebuild needed).\n3) Run FTS queries (AND/OR/phrase matching) with BM25 ranking.\n4) If requested, sniff commit hashes near the search hits and show git details.\nWhat "indexing" means here\n--------------------------\nFTS5 builds an inverted index: term -> list of rows with that term.\nThis is not embedding/ML. It is fast and reliable for exact/near-exact terms.\nWe incrementally index new log lines by remembering the file offset and mtime.\n\nCommit sniffing (why it is useful)\n----------------------------------\nWhen a conversation reaches a "resolution point," it often mentions a commit.\nThis tool can scan forward/backward for those commit mentions and then call\ngit locally to show the commit message and files touched. That gives "clues"\nabout what changed without re-reading the whole thread.\n\nKey capabilities\n----------------\n- Full-text search with SQLite FTS5 (BM25 ranking)\n- Incremental indexing (fast for growing logs)\n- Role filtering (user vs assistant)\n- Prefix search by default (mountain -> mountain*) for forgiving matches\n  (applies inside quoted phrases too)\n- Deduped output by default (disable with --no-dedupe)\n- Adjustable snippet length (--snippet-tokens) or full text (--full)\n- Multi-provider log discovery (Codex, Claude, Gemini)\n- Catch-up mode: print the full last conversation(s)\n- Auto git on search and catch-up (unless disabled)\n- Commit sniffing modes:\n  - scan (default): scan the whole selected log(s)\n  - auto: if you search, find the nearest commit before+after the match\n  - direct: only the matched message\n  - forward: scan ahead from match\n  - backward: scan behind match\n  - between: from last commit before match to next commit after\n- Commit scope filters:\n  - conversation: prefer assistant "committed/pushed" messages (default)\n  - branch-only: only show commits on current branch (default)\n\nExamples\n--------\nIndex latest Codex log and search:\n  python3 /Users/t/dev/skills/log_search_fts5.py --codex "sessioncheck OR whoami"\n\nIndex the latest 3 conversations (time order) and search:\n  python3 /Users/t/dev/skills/log_search_fts5.py --recent 3 "sessioncheck OR whoami"\n\nPhrase-only smart defaults (last convo + git sniff):\n  python3 /Users/t/dev/skills/log_search_fts5.py sessioncheck whoami\n\nSearch and show commits (default full scan):\n  python3 /Users/t/dev/skills/log_search_fts5.py "sessioncheck OR whoami"\n\nScan all commits mentioned by the assistant across the entire log (defaults):\n  python3 /Users/t/dev/skills/log_search_fts5.py --latest\n\nCatch up on the full last conversation(s):\n  python3 /Users/t/dev/skills/log_search_fts5.py --claude\n  python3 /Users/t/dev/skills/log_search_fts5.py --all\n\nList logs:\n  python3 tools/log_search_fts5.py --list\n\nNotes\n-----\n- This script expects SQLite with FTS5 enabled (default on modern macOS/Linux).\n- If git is missing, commit sniffing is skipped.\n- Codex base dir: $CODEX_HOME (default: ~/.codex)\n- Claude base dir: $CLAUDE_CONFIG_DIR (default: ~/.claude)\n- Gemini base dir: ~/.gemini (no env override detected)\n"""\nimport argparse\nimport json\nimport os\nimport re\nimport sqlite3\nimport sys\nimport subprocess\nimport shutil\nimport signal\nfrom datetime import datetime\nfrom pathlib import Path\n\n\ntry:\n    signal.signal(signal.SIGPIPE, signal.SIG_DFL)\nexcept Exception:\n    pass\n\ndef safe_print(text):\n    try:\n        print(text)\n    except BrokenPipeError:\n        sys.exit(0)\n\n\ndef codex_sessions_root(codex_root=None):\n    codex_home = codex_root or os.environ.get("CODEX_HOME", os.path.expanduser("~/.codex"))\n    base = Path(codex_home).expanduser()\n    if (base / "sessions").is_dir():\n        return base / "sessions"\n    return base\n\n\ndef claude_projects_root(claude_root=None):\n    claude_home = claude_root or os.environ.get("CLAUDE_CONFIG_DIR", os.path.expanduser("~/.claude"))\n    base = Path(claude_home).expanduser()\n    if (base / "projects").is_dir():\n        return base / "projects"\n    return base\n\n\ndef gemini_tmp_root(gemini_root=None):\n    base = Path(gemini_root or os.path.expanduser("~/.gemini")).expanduser()\n    if (base / "tmp").is_dir():\n        return base / "tmp"\n    return base\n\n\ndef list_jsonl_logs(root, provider):\n    logs = []\n    if not root.exists():\n        return logs\n    for path in root.rglob("*.jsonl"):\n        try:\n            stat = path.stat()\n        except OSError:\n            continue\n        logs.append((path, stat.st_mtime, stat.st_size, provider))\n    logs.sort(key=lambda x: x[1])\n    return logs\n\n\ndef list_gemini_logs(root, provider):\n    logs = []\n    if not root.exists():\n        return logs\n    paths = list(root.rglob("chats/*.json"))\n    if not paths and root.name == "chats":\n        paths = list(root.rglob("*.json"))\n    for path in paths:\n        try:\n            stat = path.stat()\n        except OSError:\n            continue\n        logs.append((path, stat.st_mtime, stat.st_size, provider))\n    logs.sort(key=lambda x: x[1])\n    return logs\n\n\ndef provider_from_path(path, provider_by_path):\n    key = str(path)\n    if key in provider_by_path:\n        return provider_by_path[key]\n    path_str = str(path)\n    if "/.claude/" in path_str:\n        return "claude"\n    if "/.gemini/" in path_str:\n        return "gemini"\n    return "codex"\n\n\ndef select_recent_targets(logs, providers, count):\n    targets = []\n    for provider in providers:\n        provider_logs = [item for item in logs if item[3] == provider]\n        if not provider_logs:\n            continue\n        targets.extend([p for p, _, _, _ in provider_logs[-count:]])\n    return targets\n\n\ndef extract_text(content):\n    if isinstance(content, str):\n        return content.strip()\n    parts = []\n    if not isinstance(content, list):\n        return ""\n    for item in content:\n        if not isinstance(item, dict):\n            continue\n        t = item.get("type")\n        if t in ("input_text", "output_text", "text"):\n            parts.append(item.get("text", ""))\n            continue\n        if isinstance(item.get("text"), str):\n            parts.append(item.get("text", ""))\n    return "\\n".join([p for p in parts if p]).strip()\n\n\ndef parse_codex_line(line):\n    try:\n        obj = json.loads(line)\n    except Exception:\n        return []\n    ts = obj.get("timestamp", "")\n    msg_type = obj.get("type")\n    if msg_type == "response_item":\n        payload = obj.get("payload", {})\n        if payload.get("type") != "message":\n            return []\n        role = payload.get("role")\n        text = extract_text(payload.get("content", []))\n        if text:\n            return [(ts, role, text)]\n    elif msg_type == "event_msg":\n        payload = obj.get("payload", {})\n        ptype = payload.get("type")\n        if ptype in ("user_message", "agent_message"):\n            role = "user" if ptype == "user_message" else "assistant"\n            text = payload.get("message", "")\n            if text:\n                return [(ts, role, text)]\n    return []\n\n\ndef parse_claude_line(line):\n    try:\n        obj = json.loads(line)\n    except Exception:\n        return []\n    ts = obj.get("timestamp", "")\n    message = obj.get("message")\n    if isinstance(message, dict):\n        role = message.get("role") or obj.get("type")\n        text = extract_text(message.get("content"))\n        if not text and isinstance(message.get("content"), str):\n            text = message.get("content", "").strip()\n        if text and role:\n            return [(ts, role, text)]\n    role = obj.get("role")\n    if role in ("user", "assistant"):\n        content = obj.get("content")\n        text = extract_text(content)\n        if not text and isinstance(content, str):\n            text = content.strip()\n        if text:\n            return [(ts, role, text)]\n    return []\n\n\ndef extract_gemini_strings(obj):\n    parts = []\n    if isinstance(obj, dict):\n        for key, value in obj.items():\n            if key in ("output", "text", "content") and isinstance(value, str):\n                parts.append(value)\n            else:\n                parts.extend(extract_gemini_strings(value))\n    elif isinstance(obj, list):\n        for item in obj:\n            parts.extend(extract_gemini_strings(item))\n    return parts\n\n\ndef parse_gemini_messages(data):\n    messages = data.get("messages", [])\n    out = []\n    for msg in messages:\n        if not isinstance(msg, dict):\n            continue\n        msg_type = msg.get("type", "")\n        if msg_type in ("gemini", "assistant", "model"):\n            role = "assistant"\n        elif msg_type == "user":\n            role = "user"\n        else:\n            role = msg_type or ""\n        parts = []\n        content = msg.get("content")\n        if isinstance(content, str) and content.strip():\n            parts.append(content)\n        elif isinstance(content, list):\n            extracted = extract_text(content)\n            if extracted:\n                parts.append(extracted)\n        tool_calls = msg.get("toolCalls")\n        if isinstance(tool_calls, list):\n            for call in tool_calls:\n                if isinstance(call, dict) and isinstance(call.get("resultDisplay"), str):\n                    parts.append(call["resultDisplay"])\n                parts.extend(extract_gemini_strings(call.get("result")))\n        text = "\\n".join([p for p in parts if p]).strip()\n        if text:\n            out.append((msg.get("timestamp", ""), role, text))\n    return out\n\n\ndef ensure_db(conn):\n    cols = []\n    try:\n        cols = [row[1] for row in conn.execute("PRAGMA table_info(session_fts)")]\n    except sqlite3.OperationalError:\n        cols = []\n    if cols and "provider" not in cols:\n        conn.execute("DROP TABLE IF EXISTS session_fts")\n        conn.execute("DROP TABLE IF EXISTS file_state")\n        conn.commit()\n    conn.execute(\n        "CREATE VIRTUAL TABLE IF NOT EXISTS session_fts USING fts5(text, role, file, ts, msg_index UNINDEXED, provider UNINDEXED)"\n    )\n    conn.execute(\n        "CREATE TABLE IF NOT EXISTS file_state (file TEXT PRIMARY KEY, mtime REAL, size INTEGER, offset INTEGER, msg_index INTEGER)"\n    )\n    conn.commit()\n\n\ndef index_jsonl_file(conn, path, provider, parser):\n    stat = path.stat()\n    row = conn.execute(\n        "SELECT mtime, size, offset, msg_index FROM file_state WHERE file=?",\n        (str(path),),\n    ).fetchone()\n\n    if row and stat.st_size >= row[1] and stat.st_mtime >= row[0]:\n        offset = row[2]\n        msg_index = row[3]\n    else:\n        conn.execute("DELETE FROM session_fts WHERE file=?", (str(path),))\n        conn.execute("DELETE FROM file_state WHERE file=?", (str(path),))\n        offset = 0\n        msg_index = 0\n\n    with path.open("r", encoding="utf-8", errors="replace") as handle:\n        if offset:\n            handle.seek(offset)\n        for line in handle:\n            for ts, role, text in parser(line):\n                msg_index += 1\n                conn.execute(\n                    "INSERT INTO session_fts (text, role, file, ts, msg_index, provider) VALUES (?, ?, ?, ?, ?, ?)",\n                    (text, role or "", str(path), ts, msg_index, provider),\n                )\n        offset = handle.tell()\n\n    conn.execute(\n        "INSERT OR REPLACE INTO file_state (file, mtime, size, offset, msg_index) VALUES (?, ?, ?, ?, ?)",\n        (str(path), stat.st_mtime, stat.st_size, offset, msg_index),\n    )\n    conn.commit()\n\n\ndef index_json_file(conn, path, provider):\n    stat = path.stat()\n    row = conn.execute(\n        "SELECT mtime, size FROM file_state WHERE file=?",\n        (str(path),),\n    ).fetchone()\n    if row and stat.st_size == row[1] and stat.st_mtime == row[0]:\n        return\n    conn.execute("DELETE FROM session_fts WHERE file=?", (str(path),))\n    conn.execute("DELETE FROM file_state WHERE file=?", (str(path),))\n    msg_index = 0\n    try:\n        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))\n    except Exception:\n        data = {}\n    for ts, role, text in parse_gemini_messages(data if isinstance(data, dict) else {}):\n        msg_index += 1\n        conn.execute(\n            "INSERT INTO session_fts (text, role, file, ts, msg_index, provider) VALUES (?, ?, ?, ?, ?, ?)",\n            (text, role or "", str(path), ts, msg_index, provider),\n        )\n    conn.execute(\n        "INSERT OR REPLACE INTO file_state (file, mtime, size, offset, msg_index) VALUES (?, ?, ?, ?, ?)",\n        (str(path), stat.st_mtime, stat.st_size, stat.st_size, msg_index),\n    )\n    conn.commit()\n\n\ndef index_file(conn, path, provider):\n    if provider == "gemini":\n        return index_json_file(conn, path, provider)\n    parser = parse_codex_line if provider == "codex" else parse_claude_line\n    return index_jsonl_file(conn, path, provider, parser)\n\n\ndef search(conn, query, limit, role=None, snippet_tokens=250, providers=None, files=None):\n    params = [query]\n    where_parts = ["session_fts MATCH ?"]\n    if role:\n        where_parts.append("role=?")\n        params.append(role)\n    if providers:\n        where_parts.append(f"provider IN ({\',\'.join([\'?\'] * len(providers))})")\n        params.extend(providers)\n    if files:\n        where_parts.append(f"file IN ({\',\'.join([\'?\'] * len(files))})")\n        params.extend(files)\n    where = " AND ".join(where_parts)\n    params.append(limit)\n    sql = (\n        "SELECT ts, role, file, msg_index, provider, "\n        f"snippet(session_fts, 0, \'[\', \']\', \'…\', {int(snippet_tokens)}) AS snip, text "\n        "FROM session_fts "\n        f"WHERE {where} "\n        "ORDER BY bm25(session_fts) "\n        "LIMIT ?"\n    )\n    return conn.execute(sql, params).fetchall()\n\n\ndef tail_messages(conn, limit, role=None, providers=None, files=None):\n    params = []\n    where_parts = []\n    if role:\n        where_parts.append("role=?")\n        params.append(role)\n    if providers:\n        where_parts.append(f"provider IN ({\',\'.join([\'?\'] * len(providers))})")\n        params.extend(providers)\n    if files:\n        where_parts.append(f"file IN ({\',\'.join([\'?\'] * len(files))})")\n        params.extend(files)\n    where = " AND ".join(where_parts)\n    sql = (\n        "SELECT ts, role, file, msg_index, provider, text "\n        "FROM session_fts "\n    )\n    if where:\n        sql += f"WHERE {where} "\n    sql += "ORDER BY ts DESC, file DESC, msg_index DESC LIMIT ?"\n    params.append(limit)\n    rows = conn.execute(sql, params).fetchall()\n    rows.reverse()\n    return rows\n\n\ndef tail_messages_per_provider(conn, limit, providers, role=None, files=None):\n    rows = []\n    for provider in providers:\n        provider_rows = tail_messages(\n            conn,\n            limit,\n            role=role,\n            providers=[provider],\n            files=files,\n        )\n        rows.extend(provider_rows)\n    rows.sort(key=lambda r: (r[0], r[4], r[2], r[3]))\n    return rows\n\n\ndef dump_full_targets(conn, targets, role=None):\n    for target in targets:\n        params = [str(target)]\n        where = "file=?"\n        if role:\n            where += " AND role=?"\n            params.append(role)\n        rows = conn.execute(\n            "SELECT ts, role, file, msg_index, provider, text "\n            f"FROM session_fts WHERE {where} "\n            "ORDER BY msg_index",\n            params,\n        ).fetchall()\n        for ts, role_value, file, msg_index, provider, text in rows:\n            output_text = re.sub(r"\\s+", " ", text.strip())\n            safe_print(f"{ts} [{provider}:{role_value}] {output_text} ({file}#{msg_index})")\n\n\ndef apply_prefix_query(query):\n    if not query:\n        return query\n    parts = re.split(r\'(".*?")\', query)\n    out_parts = []\n    for part in parts:\n        if part.startswith(\'"\') and part.endswith(\'"\'):\n            inner = part[1:-1]\n            tokens = inner.split()\n            cooked = []\n            for token in tokens:\n                upper = token.upper()\n                if upper in ("AND", "OR", "NOT"):\n                    cooked.append(token)\n                    continue\n                if "*" in token or "(" in token or ")" in token:\n                    cooked.append(token)\n                    continue\n                cooked.append(f"{token}*")\n            out_parts.append(f"\\"{\' \'.join(cooked)}\\"")\n        else:\n            tokens = part.split()\n            cooked = []\n            for token in tokens:\n                upper = token.upper()\n                if upper in ("AND", "OR", "NOT"):\n                    cooked.append(token)\n                    continue\n                if "*" in token or "(" in token or ")" in token:\n                    cooked.append(token)\n                    continue\n                cooked.append(f"{token}*")\n            out_parts.append(" ".join(cooked))\n    return " ".join([p for p in out_parts if p]).strip()\n\n\ndef find_commit_hashes(text):\n    return list(dict.fromkeys(re.findall(r"\\b[0-9a-f]{7,40}\\b", text)))\n\n\ndef has_commit_context(text):\n    return bool(re.search(r"\\b(commit|pushed|merge|sha|hash)\\b", text, re.IGNORECASE))\n\n\ndef has_commit_action_context(text):\n    patterns = [\n        r"\\bcommitted\\b",\n        r"\\bpushed\\b",\n        r"\\bcommit:\\b",\n        r"\\bchanges committed\\b",\n        r"\\bcommitted\\s+\\+\\s+pushed\\b",\n        r"\\bcommit\\b.*\\b(pushed|push)\\b",\n    ]\n    return any(re.search(p, text, re.IGNORECASE) for p in patterns)\n\n\ndef find_commit_mentions(text, require_context=True, action_only=False):\n    if require_context and not has_commit_context(text):\n        return []\n    if action_only and not has_commit_action_context(text):\n        return []\n    return find_commit_hashes(text)\n\n\ndef scan_for_commit(\n    conn,\n    file_path,\n    start_idx,\n    end_idx,\n    direction="forward",\n    require_context=True,\n    role=None,\n    action_only=False,\n):\n    if end_idx < start_idx:\n        return None\n    params = [file_path, start_idx, end_idx]\n    where = "file=? AND msg_index BETWEEN ? AND ?"\n    if role:\n        where += " AND role=?"\n        params.append(role)\n    rows = conn.execute(\n        f"SELECT msg_index, text FROM session_fts WHERE {where} ORDER BY msg_index",\n        params,\n    ).fetchall()\n    if direction == "backward":\n        rows = reversed(rows)\n    for msg_index, text in rows:\n        hashes = find_commit_mentions(\n            text, require_context=require_context, action_only=action_only\n        )\n        if hashes:\n            return msg_index, hashes, text\n    return None\n\n\ndef scan_range(start_idx, end_idx, span, direction):\n    if span is None or span <= 0:\n        return start_idx, end_idx\n    if direction == "forward":\n        return start_idx, min(end_idx, start_idx + span)\n    if direction == "backward":\n        return max(1, end_idx - span), end_idx\n    return max(1, end_idx - span), min(end_idx, end_idx + span)\n\n\ndef max_msg_index(conn, file_path):\n    row = conn.execute(\n        "SELECT max(msg_index) FROM session_fts WHERE file=?",\n        (file_path,),\n    ).fetchone()\n    return row[0] or 0\n\n\ndef scan_commits(\n    conn,\n    file_path,\n    start_idx,\n    end_idx,\n    require_context=True,\n    role=None,\n    action_only=False,\n):\n    params = [file_path, start_idx, end_idx]\n    where = "file=? AND msg_index BETWEEN ? AND ?"\n    if role:\n        where += " AND role=?"\n        params.append(role)\n    rows = conn.execute(\n        f"SELECT msg_index, text FROM session_fts WHERE {where} ORDER BY msg_index",\n        params,\n    ).fetchall()\n    found = []\n    for msg_index, text in rows:\n        hashes = find_commit_mentions(\n            text, require_context=require_context, action_only=action_only\n        )\n        if hashes:\n            found.append((msg_index, hashes, text))\n    return found\n\n\ndef collect_git_roots(paths):\n    roots = []\n    seen = set()\n    for base in paths:\n        if not base or not base.exists():\n            continue\n        if (base / ".git").exists():\n            key = str(base.resolve())\n            if key not in seen:\n                roots.append(base)\n                seen.add(key)\n        for child in base.iterdir():\n            if not child.is_dir():\n                continue\n            if (child / ".git").exists():\n                key = str(child.resolve())\n                if key not in seen:\n                    roots.append(child)\n                    seen.add(key)\n    return roots\n\n\ndef git_commit_exists(repo, sha):\n    cmd = ["git", "-C", str(repo), "cat-file", "-e", f"{sha}^{{commit}}"]\n    return subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0\n\n\ndef git_commit_on_branch(repo, sha):\n    cmd = ["git", "-C", str(repo), "merge-base", "--is-ancestor", sha, "HEAD"]\n    return subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0\n\n\ndef git_show_summary(repo, sha):\n    cmd = ["git", "-C", str(repo), "show", "--stat", "--oneline", "--no-color", "-1", sha]\n    result = subprocess.run(cmd, capture_output=True, text=True)\n    if result.returncode != 0:\n        return None\n    return result.stdout.strip()\n\n\ndef main():\n    parser = argparse.ArgumentParser(\n        description=(\n            "Search Codex, Claude, and Gemini session logs with SQLite FTS5 and optional git commit sniffing. "\n            "Designed for fast, repeatable queries over JSONL/JSON logs."\n        ),\n        epilog=(\n            "Examples:\\n"\n            "  List logs:\\n"\n            "    python3 /Users/t/dev/skills/log_search_fts5.py --list\\n"\n            "\\n"\n            "  Search latest Codex log:\\n"\n            "    python3 /Users/t/dev/skills/log_search_fts5.py --codex \\"sessioncheck OR whoami\\"\\n"\n            "\\n"\n            "  Phrase-only (smart defaults: recent 5 + git sniff):\\n"\n            "    python3 /Users/t/dev/skills/log_search_fts5.py sessioncheck whoami\\n"\n            "\\n"\n            "  Prefix search is on by default (mountain -> mountain*). Disable with:\\n"\n            "    python3 /Users/t/dev/skills/log_search_fts5.py --no-prefix --query \\"mountain\\"\\n"\n            "\\n"\n            "  Prefix applies inside quoted phrases too:\\n"\n            "    python3 /Users/t/dev/skills/log_search_fts5.py --query \\"\\\\\\"mountain view\\\\\\"\\"\\n"\n            "\\n"\n            "  Full text output with a hard cap:\\n"\n            "    python3 /Users/t/dev/skills/log_search_fts5.py --latest --query \\"mountain\\" \\\\\\n"\n            "      --full --max-chars 1200\\n"\n            "\\n"\n            "  Order results by time (oldest first):\\n"\n            "    python3 /Users/t/dev/skills/log_search_fts5.py --latest --query \\"mountain\\" \\\\\\n"\n            "      --order time-asc\\n"\n            "\\n"\n            "  Search + git sniff (default full scan):\\n"\n            "    python3 /Users/t/dev/skills/log_search_fts5.py --codex \\"sessioncheck\\"\\n"\n            "\\n"\n            "  Scan all commit mentions across the whole log (defaults: conversation + branch-only):\\n"\n            "    python3 /Users/t/dev/skills/log_search_fts5.py --latest --git\\n"\n            "\\n"\n            "  Conversation-only commits on current branch (your session work):\\n"\n            "    python3 /Users/t/dev/skills/log_search_fts5.py --latest --git --git-mode scan \\\\\\n"\n            "      --git-scope conversation --git-span 0 --git-branch-only\\n"\n            "\\n"\n            "  Find commits near a topic (scan backward from match):\\n"\n            "    python3 /Users/t/dev/skills/log_search_fts5.py --latest --query \\"pm2\\" --git \\\\\\n"\n            "      --git-mode backward --git-span 200\\n"\n            "\\n"\n            "  Find commits near a topic (between commits):\\n"\n            "    python3 /Users/t/dev/skills/log_search_fts5.py --latest --query \\"sessioncheck\\" --git \\\\\\n"\n            "      --git-mode between --git-span 200\\n"\n            "\\n"\n            "  Search only assistant messages for a topic:\\n"\n            "    python3 /Users/t/dev/skills/log_search_fts5.py --latest --query \\"pm2\\" --role assistant\\n"\n            "\\n"\n            "  Search only user messages for a topic:\\n"\n            "    python3 /Users/t/dev/skills/log_search_fts5.py --latest --query \\"dynamodb\\" --role user\\n"\n            "\\n"\n            "  Index all logs then search:\\n"\n            "    python3 /Users/t/dev/skills/log_search_fts5.py --all-logs \\"setup-linux-ec2-dev\\"\\n"\n            "\\n"\n            "  Search the latest 3 conversations (time order):\\n"\n            "    python3 /Users/t/dev/skills/log_search_fts5.py --recent 3 \\"sessioncheck OR whoami\\"\\n"\n            "\\n"\n            "  Tail the last 25 messages from recent Claude logs:\\n"\n            "    python3 /Users/t/dev/skills/log_search_fts5.py --claude --recent 3 --tail 25\\n"\n            "\\n"\n            "  Search the latest 2 logs per provider:\\n"\n            "    python3 /Users/t/dev/skills/log_search_fts5.py --all --recent 2 \\"login\\"\\n"\n            "\\n"\n            "  Tail the last 5 messages per provider:\\n"\n            "    python3 /Users/t/dev/skills/log_search_fts5.py --all --tail 5 --tail-mode per-provider\\n"\n            "\\n"\n            "  Scan commit mentions across all providers (preset, same defaults):\\n"\n            "    python3 /Users/t/dev/skills/log_search_fts5.py --scan-commits\\n"\n            "\\n"\n            "  Scan all commit mentions in selected logs:\\n"\n            "    python3 /Users/t/dev/skills/log_search_fts5.py --commits\\n"\n            "\\n"\n            "  Catch up on full last conversation(s):\\n"\n            "    python3 /Users/t/dev/skills/log_search_fts5.py --catch-up\\n"\n            "    python3 /Users/t/dev/skills/log_search_fts5.py --catch-up --all\\n"\n            "\\n"\n            "  Search with git scanning disabled:\\n"\n            "    python3 /Users/t/dev/skills/log_search_fts5.py --query \\"pm2\\" --no-git\\n"\n            "\\n"\n            "  Search Claude logs:\\n"\n            "    python3 /Users/t/dev/skills/log_search_fts5.py --claude \\"setup.php\\"\\n"\n            "\\n"\n            "  Search Gemini logs:\\n"\n            "    python3 /Users/t/dev/skills/log_search_fts5.py --gemini \\"debug-session\\"\\n"\n            "\\n"\n            "  Search across all providers:\\n"\n            "    python3 /Users/t/dev/skills/log_search_fts5.py --all \\"login\\"\\n"\n            "\\n"\n            "  Use a custom index file (portable):\\n"\n            "    python3 /Users/t/dev/skills/log_search_fts5.py --latest --query \\"sessioncheck\\" \\\\\\n"\n            "      --index /tmp/session-index.sqlite\\n"\n            "\\n"\n            "  Limit git sniffing to a specific repo:\\n"\n            "    python3 /Users/t/dev/skills/log_search_fts5.py --latest --query \\"sessioncheck\\" --git \\\\\\n"\n            "      --git-root /Users/t/clients/thrivecart/mountain1/thrivecart\\n"\n            "\\n"\n            "  Scan commits only from user messages (team/dev mentions):\\n"\n            "    python3 /Users/t/dev/skills/log_search_fts5.py --latest --git --git-mode scan \\\\\\n"\n            "      --git-scope conversation --git-role user --git-span 0\\n"\n            "\\n"\n            "FTS tips:\\n"\n            "  - Use AND/OR: \\"foo AND bar\\"\\n"\n            "  - Use quotes for phrase: \\"npm run dev\\"\\n"\n        ),\n        formatter_class=argparse.RawTextHelpFormatter,\n    )\n    parser.add_argument(\n        "--provider",\n        action="append",\n        choices=["codex", "claude", "gemini", "all"],\n        help="Provider(s) to search (legacy; prefer --codex/--claude/--gemini/--all).",\n    )\n    parser.add_argument("--codex", action="store_true", help="Use Codex logs.")\n    parser.add_argument("--claude", action="store_true", help="Use Claude logs.")\n    parser.add_argument("--gemini", action="store_true", help="Use Gemini logs.")\n    parser.add_argument("--all", action="store_true", help="Use logs from all providers.")\n    parser.add_argument(\n        "--scan-commits",\n        action="store_true",\n        help="Preset: scan commit mentions across providers/logs (sets --all, --git, --git-mode scan, --git-span 0).",\n    )\n    parser.add_argument(\n        "--commits",\n        action="store_true",\n        help="Scan all commit mentions in selected logs (sets --git, --git-mode scan, --git-span 0).",\n    )\n    parser.add_argument(\n        "--no-git",\n        action="store_true",\n        help="Disable automatic git sniffing on searches.",\n    )\n    parser.add_argument(\n        "--catch-up",\n        "--catchup",\n        action="store_true",\n        help="Print the full last conversation(s) for the selected scope.",\n    )\n    parser.add_argument(\n        "--codex-root",\n        help="Override Codex base dir or sessions dir (default: $CODEX_HOME or ~/.codex).",\n    )\n    parser.add_argument(\n        "--claude-root",\n        help="Override Claude base dir or projects dir (default: $CLAUDE_CONFIG_DIR or ~/.claude).",\n    )\n    parser.add_argument(\n        "--gemini-root",\n        help="Override Gemini base dir or chats dir (default: ~/.gemini).",\n    )\n    parser.add_argument("--list", action="store_true", help="List available logs with index.")\n    parser.add_argument("--file", help="Log file path or index from --list.")\n    parser.add_argument("--latest", action="store_true", help="Use latest log file.")\n    parser.add_argument(\n        "--recent",\n        type=int,\n        help="Use the most recent N logs per provider (default: 1). Overrides --latest/--file.",\n    )\n    parser.add_argument(\n        "phrase",\n        nargs="*",\n        help="Phrase-only query (smart defaults when --query is omitted).",\n    )\n    parser.add_argument("--all-logs", action="store_true", help="Index all logs.")\n    parser.add_argument("--query", help="FTS query (e.g. sessioncheck AND whoami).")\n    parser.add_argument("--role", choices=["user", "assistant"], help="Filter by role.")\n    parser.add_argument(\n        "--order",\n        choices=["score", "time-asc", "time-desc"],\n        default="score",\n        help="Result ordering (default: score).",\n    )\n    parser.add_argument("--limit", type=int, default=20, help="Results limit.")\n    parser.add_argument(\n        "--tail",\n        type=int,\n        help="Print the last N messages (ignores --query).",\n    )\n    parser.add_argument(\n        "--tail-mode",\n        choices=["combined", "per-provider"],\n        help="Tail mode across providers (default: per-provider when multiple providers).",\n    )\n    parser.add_argument("--index", help="SQLite index path.")\n    parser.add_argument("--git", action="store_true", help="Try to resolve commit hashes found in results.")\n    parser.add_argument(\n        "--git-root",\n        action="append",\n        help="Git repo root to search (repeatable). Defaults to cwd and its immediate subdirs.",\n    )\n    parser.add_argument("--git-limit", type=int, default=3, help="Max commits to inspect.")\n    parser.add_argument(\n        "--git-mode",\n        choices=["scan", "auto", "direct", "forward", "backward", "between"],\n        default="scan",\n        help="Where to look for commits (default: scan = whole log).",\n    )\n    parser.add_argument(\n        "--git-scope",\n        choices=["all", "conversation"],\n        default="conversation",\n        help="Commit mention scope (default: conversation = assistant commit mentions).",\n    )\n    parser.add_argument(\n        "--git-role",\n        choices=["assistant", "user"],\n        help="Limit commit scanning to a specific role (default: assistant for conversation scope).",\n    )\n    parser.add_argument(\n        "--git-span",\n        type=int,\n        default=None,\n        help="Message window to scan forward/backward for commits (default: 200; 0 = full log).",\n    )\n    parser.add_argument(\n        "--git-start",\n        type=int,\n        default=1,\n        help="Starting message index for scan mode (1-based).",\n    )\n    parser.add_argument(\n        "--git-branch-only",\n        action="store_true",\n        default=True,\n        help="Only show commits that are on the current branch (HEAD) in a repo (default).",\n    )\n    parser.add_argument(\n        "--git-any-branch",\n        action="store_false",\n        dest="git_branch_only",\n        help="Allow commits from any branch.",\n    )\n    parser.add_argument(\n        "--no-prefix",\n        action="store_true",\n        help="Disable default prefix matching (mountain -> mountain*).",\n    )\n    parser.add_argument(\n        "--snippet-tokens",\n        type=int,\n        default=250,\n        help="Snippet token length for results (default: 250).",\n    )\n    parser.add_argument(\n        "--full",\n        action="store_true",\n        help="Show full text instead of snippet.",\n    )\n    parser.add_argument(\n        "--max-chars",\n        type=int,\n        default=0,\n        help="Max characters to display (0 = no limit).",\n    )\n    parser.add_argument(\n        "--no-dedupe",\n        action="store_true",\n        help="Disable deduplication of near-identical results.",\n    )\n\n    args = parser.parse_args()\n\n    if args.no_git:\n        args.git = False\n    else:\n        args.git = True\n\n    if args.scan_commits:\n        if not any([args.provider, args.codex, args.claude, args.gemini, args.all]):\n            args.all = True\n        if not any([args.all_logs, args.recent, args.file, args.latest]):\n            args.all_logs = True\n        args.git = True\n        args.git_mode = "scan"\n        args.git_span = 0\n\n    if args.commits:\n        args.git = True\n        args.git_mode = "scan"\n        args.git_span = 0\n\n    providers = []\n    if args.provider:\n        providers.extend([p for p in args.provider if p])\n    if args.codex:\n        providers.append("codex")\n    if args.claude:\n        providers.append("claude")\n    if args.gemini:\n        providers.append("gemini")\n    if args.all:\n        providers = ["codex", "claude", "gemini"]\n    providers = list(dict.fromkeys(providers))\n    if "all" in providers:\n        providers = ["codex", "claude", "gemini"]\n    if not providers:\n        providers = ["codex"]\n\n    logs = []\n    if "codex" in providers:\n        logs.extend(list_jsonl_logs(codex_sessions_root(args.codex_root), "codex"))\n    if "claude" in providers:\n        logs.extend(list_jsonl_logs(claude_projects_root(args.claude_root), "claude"))\n    if "gemini" in providers:\n        logs.extend(list_gemini_logs(gemini_tmp_root(args.gemini_root), "gemini"))\n    logs.sort(key=lambda x: x[1])\n    provider_by_path = {str(path): provider for path, _, _, provider in logs}\n    if args.list:\n        if not logs:\n            safe_print("No logs found.")\n            return 0\n        for idx, (path, mtime, size, provider) in enumerate(logs):\n            stamp = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")\n            safe_print(f"{idx:03d} {stamp} {size:9d} {provider:7} {path}")\n        return 0\n\n    if not logs:\n        safe_print("No logs found.")\n        return 1\n\n    default_index = os.path.join(os.environ.get("CODEX_HOME", os.path.expanduser("~/.codex")), "session-index.sqlite")\n    index_path = Path(args.index or default_index)\n\n    conn = sqlite3.connect(str(index_path))\n    ensure_db(conn)\n\n    targets = []\n    if not any([args.all_logs, args.recent, args.file, args.latest]):\n        args.recent = 1\n    if args.all_logs:\n        targets = [p for p, _, _, _ in logs]\n    elif args.recent:\n        if args.recent <= 0:\n            safe_print("--recent must be >= 1")\n            return 1\n        targets = select_recent_targets(logs, providers, args.recent)\n    elif args.file:\n        if args.file.isdigit():\n            idx = int(args.file)\n            if idx < 0 or idx >= len(logs):\n                safe_print(f"Index out of range: {idx}")\n                return 1\n            targets = [logs[idx][0]]\n        else:\n            targets = [Path(args.file).expanduser()]\n    else:\n        targets = [logs[-1][0]]\n\n    if not args.query and args.phrase:\n        args.query = " ".join(args.phrase).strip()\n\n    for target in targets:\n        if not target.exists():\n            safe_print(f"Log not found: {target}")\n            continue\n        index_file(conn, target, provider_from_path(target, provider_by_path))\n\n    git_roots = []\n    if args.git and shutil.which("git"):\n        if args.git_root:\n            git_roots = [Path(p).expanduser() for p in args.git_root]\n        else:\n            git_roots = collect_git_roots([Path.cwd(), Path.cwd().parent])\n    seen_commits = set()\n\n    def emit_git_for_hashes(hashes):\n        for sha in hashes:\n            if sha in seen_commits:\n                continue\n            if len(seen_commits) >= args.git_limit:\n                break\n            for repo in git_roots:\n                if git_commit_exists(repo, sha) and (\n                    not args.git_branch_only or git_commit_on_branch(repo, sha)\n                ):\n                    summary = git_show_summary(repo, sha)\n                    if summary:\n                        safe_print(f"  git: {repo} {sha}")\n                        for line in summary.splitlines():\n                            safe_print(f"  {line}")\n                    seen_commits.add(sha)\n                    break\n\n    def commit_scan_role():\n        if args.git_role:\n            return args.git_role\n        if args.git_scope == "conversation":\n            return "assistant"\n        return None\n\n    def scan_commits_for_targets():\n        for target in targets:\n            end_idx = max_msg_index(conn, str(target))\n            span = args.git_span\n            if span is None or span <= 0:\n                span = end_idx\n            scan_start = max(1, args.git_start)\n            scan_end = min(end_idx, scan_start + span)\n            commits = scan_commits(\n                conn,\n                str(target),\n                scan_start,\n                scan_end,\n                require_context=True,\n                role=commit_scan_role(),\n                action_only=(args.git_scope == "conversation"),\n            )\n            for _, hashes, _ in commits:\n                emit_git_for_hashes(hashes)\n\n    if not args.query and not args.tail:\n        args.catch_up = True\n\n    if args.catch_up:\n        dump_full_targets(conn, targets, role=args.role)\n        if args.git and git_roots:\n            scan_commits_for_targets()\n        conn.close()\n        return 0\n\n    file_filter = None\n    if len(targets) != len(logs):\n        file_filter = [str(p) for p in targets]\n\n    if args.tail:\n        tail_mode = args.tail_mode or ("per-provider" if len(providers) > 1 else "combined")\n        if tail_mode == "per-provider":\n            rows = tail_messages_per_provider(\n                conn,\n                args.tail,\n                providers=providers,\n                role=args.role,\n                files=file_filter,\n            )\n        else:\n            rows = tail_messages(\n                conn,\n                args.tail,\n                role=args.role,\n                providers=providers,\n                files=file_filter,\n            )\n        for ts, role, file, msg_index, provider, text in rows:\n            output_text = text if args.full else text\n            output_text = re.sub(r"\\s+", " ", output_text.strip())\n            if args.max_chars and len(output_text) > args.max_chars:\n                output_text = output_text[: args.max_chars] + "…"\n            safe_print(f"{ts} [{provider}:{role}] {output_text} ({file}#{msg_index})")\n        conn.close()\n        return 0\n\n    if args.git and args.git_mode in ("scan", "auto") and not args.query and git_roots:\n        scan_commits_for_targets()\n        return 0\n\n    if args.query:\n        query = args.query\n        if not args.no_prefix:\n            query = apply_prefix_query(query)\n        results = search(\n            conn,\n            query,\n            args.limit,\n            role=args.role,\n            snippet_tokens=args.snippet_tokens,\n            providers=providers,\n            files=file_filter,\n        )\n        if args.order != "score":\n            def parse_ts(ts):\n                try:\n                    return datetime.fromisoformat(ts.replace("Z", "+00:00"))\n                except Exception:\n                    return datetime.min\n            results.sort(\n                key=lambda r: parse_ts(r[0]),\n                reverse=(args.order == "time-desc"),\n            )\n        if not args.no_dedupe:\n            seen = set()\n            deduped = []\n            for ts, role, file, msg_index, provider, snip, text in results:\n                norm = re.sub(r"\\s+", " ", text.strip().lower())\n                key = (provider or "", role or "", norm)\n                if key in seen:\n                    continue\n                seen.add(key)\n                deduped.append((ts, role, file, msg_index, provider, snip, text))\n            results = deduped\n        for ts, role, file, msg_index, provider, snip, text in results:\n            output_text = text if args.full else snip\n            output_text = re.sub(r"\\s+", " ", output_text.strip())\n            if args.max_chars and len(output_text) > args.max_chars:\n                output_text = output_text[: args.max_chars] + "…"\n            safe_print(f"{ts} [{provider}:{role}] {output_text} ({file}#{msg_index})")\n            if not (args.git and git_roots):\n                continue\n\n            commit_result = None\n            if args.git_mode == "direct":\n                hashes = find_commit_hashes(text)\n                if hashes:\n                    commit_result = (msg_index, hashes, text)\n            elif args.git_mode == "forward":\n                span = args.git_span if args.git_span is not None else 200\n                start_idx, end_idx = scan_range(\n                    msg_index,\n                    max_msg_index(conn, file),\n                    span,\n                    "forward",\n                )\n                commit_result = scan_for_commit(\n                    conn,\n                    file,\n                    start_idx,\n                    end_idx,\n                    direction="forward",\n                    require_context=True,\n                    role=commit_scan_role(),\n                    action_only=(args.git_scope == "conversation"),\n                )\n            elif args.git_mode == "backward":\n                span = args.git_span if args.git_span is not None else 200\n                start_idx, end_idx = scan_range(\n                    msg_index,\n                    msg_index,\n                    span,\n                    "backward",\n                )\n                commit_result = scan_for_commit(\n                    conn,\n                    file,\n                    start_idx,\n                    end_idx,\n                    direction="backward",\n                    require_context=True,\n                    role=commit_scan_role(),\n                    action_only=(args.git_scope == "conversation"),\n                )\n            elif args.git_mode in ("between", "auto"):\n                max_idx = max_msg_index(conn, file)\n                span = args.git_span if args.git_span is not None else 200\n                back_start, back_end = scan_range(\n                    1,\n                    msg_index - 1,\n                    span if args.git_mode != "auto" else 0,\n                    "backward",\n                )\n                back = scan_for_commit(\n                    conn,\n                    file,\n                    back_start,\n                    back_end,\n                    direction="backward",\n                    require_context=True,\n                    role=commit_scan_role(),\n                    action_only=(args.git_scope == "conversation"),\n                )\n                start_idx = (back[0] + 1) if back else 1\n                forward_start, forward_end = scan_range(\n                    start_idx,\n                    max_idx,\n                    span if args.git_mode != "auto" else 0,\n                    "forward",\n                )\n                commit_result = scan_for_commit(\n                    conn,\n                    file,\n                    forward_start,\n                    forward_end,\n                    direction="forward",\n                    require_context=True,\n                    role=commit_scan_role(),\n                    action_only=(args.git_scope == "conversation"),\n                )\n\n            if not commit_result:\n                continue\n\n            _, hashes, _ = commit_result\n            emit_git_for_hashes(hashes)\n        if args.git and args.git_mode == "scan" and git_roots:\n            scan_commits_for_targets()\n    else:\n        safe_print(f"Indexed {len(targets)} file(s). SQLite index: {index_path}")\n\n    conn.close()\n    return 0\n\n\nif __name__ == "__main__":\n    sys.exit(main())\n'


def load_module(code, name):
    module = types.ModuleType(name)
    module.__file__ = f"<embedded:{name}>"
    exec(code, module.__dict__)
    return module


clean_mod = load_module(LOG_CLEAN_QUICK_CODE, "log_clean_quick")
fts_mod = load_module(LOG_SEARCH_FTS5_CODE, "log_search_fts5")

NAVCOM_VERSION = "0.8.0"
DEFAULT_LIMIT = 20  # hits per harness (and sessions listed by a bare `navcom`)

# Every harness navcom knows how to read. Order = display order in help/listings.
ALL_PROVIDERS = ["claude", "codex", "gemini", "pi", "omo", "opencode", "goose", "dsh", "grok", "kilo"]
PROVIDER_ALIASES = {
    "claude-code": "claude", "cc": "claude",
    "openai": "codex",
    "gemini-cli": "gemini",
    "pi-mono": "pi", "pi-dev": "pi",
    "omo-ai": "omo", "oh-my-openagent": "omo",
    "open-code": "opencode", "oc": "opencode",
    "block-goose": "goose",
    "deepseek": "dsh", "deepseek-harness": "dsh", "ds": "dsh",
    "grok-build": "grok", "xai": "grok", "grokbuild": "grok",
    "kilocode": "kilo", "kilo-code": "kilo",
}

# Harnesses added through register_harness(): id -> {list, iter, project, title, roots, match, …}.
# Each is a self-contained block of functions further down; the built-in ones above are wired
# by hand for historical reasons.
EXTRA_HARNESSES = {}


def register_harness(hid, *, list_fn, iter_fn, project_fn=None, title_fn=None, roots_fn=None,
                     match=None, aliases=(), color="0", archivable=False, label=None, retention_fn=None):
    """Plug a harness into listing, parsing, titles, projects, --where, flags and aliases."""
    EXTRA_HARNESSES[hid] = {
        "list": list_fn, "iter": iter_fn, "project": project_fn, "title": title_fn,
        "roots": roots_fn, "match": match, "archivable": archivable, "label": label or hid,
        "retention": retention_fn,
    }
    if hid not in ALL_PROVIDERS:
        ALL_PROVIDERS.append(hid)
    for alias in aliases:
        PROVIDER_ALIASES[alias] = hid
    _Style.PROVIDER_CODES[hid] = color


@dataclass
class Hit:
    ts: str
    role: str
    file: str
    msg_index: int
    provider: str
    snip: str
    text: str
    rank: float = 0.0


DEFAULT_SUMMARY_TEMPLATE = (
    "{{transcript}}\n\n"
    "========\n"
    "summarize the major categories of what i did in this conversation, "
    "what decisions where made and why, and what code artifacts we created "
    "or touched, and a list of common commands and their context:\n"
    "include .md, .yaml, and any code as artifacts\n"
    "Output Markdown (.md).\n"
)

VERBOSITY_WINDOW = {
    1: 0,
    2: 1,
    3: 2,
    4: 4,
    5: 6,
    6: 8,
    7: 12,
    8: 16,
    9: 24,
    10: 40,
}


# ─────────────────────────────────────────────────────────────────────────────
# Output styling — plain text unless stdout is a real terminal. LLM shell tools
# capture stdout through a pipe, and raw ANSI escapes are pure noise to them.
# ─────────────────────────────────────────────────────────────────────────────

class _Style:
    PROVIDER_CODES = {
        "claude": "95", "gemini": "94", "codex": "93", "pi": "92",
        "omo": "96", "opencode": "36", "goose": "33", "dsh": "34", "grok": "37", "kilo": "35",
    }

    def __init__(self):
        self.enabled = False

    def configure(self, mode="auto"):
        if mode == "always":
            self.enabled = True
        elif mode == "never":
            self.enabled = False
        elif os.environ.get("NO_COLOR"):
            self.enabled = False
        elif os.environ.get("FORCE_COLOR"):
            self.enabled = True
        else:
            try:
                self.enabled = sys.stdout.isatty()
            except Exception:
                self.enabled = False

    def _wrap(self, code, text):
        return f"\033[{code}m{text}\033[0m" if self.enabled else text

    def dim(self, text):
        return self._wrap("2", text)

    def warn(self, text):
        return self._wrap("93", text)

    def role(self, text):
        return self._wrap("96", text)

    def provider(self, name, text=None):
        return self._wrap(self.PROVIDER_CODES.get(name, "0"), name if text is None else text)

    def highlight(self, snippet):
        """Snippets arrive with «match» markers; color them on a TTY, keep the markers otherwise."""
        if not self.enabled:
            return snippet
        return snippet.replace("«", "\033[1;33m").replace("»", "\033[0m")


STYLE = _Style()


def safe_print(text=""):
    try:
        print(text)
    except BrokenPipeError:
        try:
            sys.stdout = open(os.devnull, "w")
        except Exception:
            pass
        raise SystemExit(0)


# ─────────────────────────────────────────────────────────────────────────────
# Where each harness keeps its sessions
# ─────────────────────────────────────────────────────────────────────────────

def _env_path(*names):
    for name in names:
        value = os.environ.get(name)
        if value:
            return Path(value).expanduser()
    return None


def _xdg_data_home():
    return Path(os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")).expanduser()


def pi_sessions_root():
    explicit = _env_path("PI_CODING_AGENT_SESSION_DIR")
    if explicit:
        return explicit
    return (_env_path("PI_CODING_AGENT_DIR") or Path.home() / ".pi" / "agent") / "sessions"


def omo_sessions_root():
    explicit = _env_path("OMO_CODING_AGENT_SESSION_DIR")
    if explicit:
        return explicit
    return (_env_path("OMO_CODING_AGENT_DIR") or Path.home() / ".omo" / "agent") / "sessions"


def opencode_data_root():
    return _env_path("OPENCODE_DATA_DIR") or _xdg_data_home() / "opencode"


def goose_session_roots():
    roots = []
    path_root = _env_path("GOOSE_PATH_ROOT")
    if path_root:
        roots.append(path_root / "data" / "sessions")
    roots.append(_xdg_data_home() / "goose" / "sessions")
    roots.append(Path.home() / "Library" / "Application Support" / "Block" / "goose" / "sessions")
    out, seen = [], set()
    for root in roots:
        key = str(root)
        if key not in seen:
            seen.add(key)
            out.append(root)
    return out


def provider_roots():
    """provider -> list of directories/databases navcom reads (for --where)."""
    return {
        "claude": [fts_mod.claude_projects_root()],
        "codex": [fts_mod.codex_sessions_root()],
        "gemini": gemini_tmp_roots(),
        "pi": [pi_sessions_root()],
        "omo": [omo_sessions_root()],
        "opencode": [opencode_data_root() / "opencode.db", opencode_data_root() / "storage" / "message"],
        "goose": [r / "sessions.db" for r in goose_session_roots()] + goose_session_roots(),
        "dsh": [dsh_sessions_root()],
        "grok": [grok_sessions_root()],
        "kilo": [kilo_db_path()],
        **{hid: list(h["roots"]() if h["roots"] else []) for hid, h in EXTRA_HARNESSES.items()},
    }


def default_index_path():
    explicit = _env_path("NAVCOM_INDEX")
    if explicit:
        return explicit
    codex_home = os.environ.get("CODEX_HOME", os.path.expanduser("~/.codex"))
    return Path(codex_home) / "navcom-index.sqlite"


# A log is (key, mtime, size, provider). For file-backed harnesses the key is the
# file path; for database-backed ones (opencode, goose) it is "<db>#<session id>".
_PROVIDER_BY_KEY = {}


def detect_provider_from_path(path):
    path_str = str(path)
    if path_str in _PROVIDER_BY_KEY:
        return _PROVIDER_BY_KEY[path_str]
    for hid, h in EXTRA_HARNESSES.items():
        if h["match"] and h["match"](path_str):
            return hid
    if "opencode" in path_str:
        return "opencode"
    if "/.dsh/" in path_str:
        return "dsh"
    if "/.grok/" in path_str:
        return "grok"
    if "kilo" in path_str and "#" in path_str:
        return "kilo"
    if "goose" in path_str:
        return "goose"
    if "/.claude/" in path_str:
        return "claude"
    if "/.omo/" in path_str:
        return "omo"
    if "/.pi/" in path_str:
        return "pi"
    if "/.gemini/" in path_str or path_str.endswith(".json"):
        return "gemini"
    return "codex"


def _file_logs(paths, provider):
    logs = []
    for path in paths:
        try:
            stat = path.stat()
        except OSError:
            continue
        logs.append((str(path), stat.st_mtime, stat.st_size, provider))
    return logs


def _rglob(root, pattern):
    """Path.rglob(pattern) semantics (pattern matched against the trailing path components),
    via os.walk — about 2.5x faster on big session trees, and every search lists them all."""
    import fnmatch
    try:
        if not root.is_dir():
            return []
    except OSError:
        return []
    parts = pattern.split("/")
    out = []
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            if not fnmatch.fnmatchcase(name, parts[-1]):
                continue
            if len(parts) > 1:
                tail = Path(dirpath).parts[-(len(parts) - 1):]
                if len(tail) != len(parts) - 1 or not all(
                        fnmatch.fnmatchcase(t, p) for t, p in zip(tail, parts[:-1])):
                    continue
            out.append(Path(dirpath) / name)
    return out


def _ro_connect(db_path):
    return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=10)


def _epoch_seconds(value):
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        value = float(value)
        return value / 1000.0 if value > 1e11 else value
    parsed = clean_mod.parse_ts(str(value).replace(" ", "T"))
    if parsed is None:
        return 0.0
    if parsed.tzinfo is None:
        from datetime import timezone
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def list_opencode_logs(db=None, provider="opencode"):
    """opencode's SQLite store (and Kilo's — same schema), plus opencode's legacy JSON storage."""
    logs = []
    base = opencode_data_root()
    db = db or base / "opencode.db"
    if db.exists():
        try:
            con = _ro_connect(db)
            rows = con.execute(
                "SELECT s.id, s.time_updated,"
                " (SELECT count(*) FROM part p WHERE p.session_id = s.id),"
                " (SELECT max(p.time_updated) FROM part p WHERE p.session_id = s.id)"
                " FROM session s"
            ).fetchall()
            con.close()
            for sid, updated, parts, part_updated in rows:
                if not parts:
                    continue
                mtime = max(_epoch_seconds(updated), _epoch_seconds(part_updated))
                logs.append((f"{db}#{sid}", mtime, int(parts), provider))
        except sqlite3.Error:
            pass
    if provider != "opencode":
        return logs
    # Pre-SQLite opencode kept one JSON file per message under storage/message/<session>/.
    legacy = base / "storage" / "message"
    if legacy.is_dir():
        for session_dir in legacy.iterdir():
            if not session_dir.is_dir():
                continue
            try:
                stat = session_dir.stat()
                count = sum(1 for _ in session_dir.glob("*.json"))
            except OSError:
                continue
            if count:
                logs.append((str(session_dir), stat.st_mtime, count, "opencode"))
    return logs


def list_goose_logs():
    logs = []
    for root in goose_session_roots():
        db = root / "sessions.db"
        if db.exists():
            try:
                con = _ro_connect(db)
                rows = con.execute(
                    "SELECT s.id, s.updated_at,"
                    " (SELECT count(*) FROM messages m WHERE m.session_id = s.id),"
                    " (SELECT max(m.created_timestamp) FROM messages m WHERE m.session_id = s.id)"
                    " FROM sessions s"
                ).fetchall()
                con.close()
                for sid, updated, count, last_created in rows:
                    if not count:
                        continue
                    mtime = max(_epoch_seconds(updated), _epoch_seconds(last_created))
                    logs.append((f"{db}#{sid}", mtime, int(count), "goose"))
            except sqlite3.Error:
                pass
        # Goose before the SQLite move wrote one .jsonl per session.
        logs.extend(_file_logs([p for p in _rglob(root, "*.jsonl")], "goose"))
    return logs


def list_logs(providers):
    logs = []
    if "codex" in providers:
        logs.extend(_file_logs(_rglob(fts_mod.codex_sessions_root(), "*.jsonl"), "codex"))
    if "claude" in providers:
        logs.extend(_file_logs(_rglob(fts_mod.claude_projects_root(), "*.jsonl"), "claude"))
    if "gemini" in providers:
        for root in gemini_tmp_roots():
            # ≤0.38: chats/session-*.json · ≥0.39: chats/session-*.jsonl (+ chats/<parent>/<sub>.jsonl)
            paths = _rglob(root, "chats/*.json") + [p for p in _rglob(root, "*.jsonl") if "chats" in p.parts]
            if not paths and root.name == "chats":
                paths = _rglob(root, "*.json")
            logs.extend(_file_logs(paths, "gemini"))
    if "pi" in providers:
        logs.extend(_file_logs(_rglob(pi_sessions_root(), "*.jsonl"), "pi"))
    if "omo" in providers:
        logs.extend(_file_logs(_rglob(omo_sessions_root(), "*.jsonl"), "omo"))
    if "opencode" in providers:
        logs.extend(list_opencode_logs())
    if "goose" in providers:
        logs.extend(list_goose_logs())
    if "dsh" in providers:
        logs.extend(list_dsh_logs())
    if "grok" in providers:
        logs.extend(list_grok_logs())
    if "kilo" in providers:
        logs.extend(list_opencode_logs(kilo_db_path(), "kilo"))
    for hid, h in EXTRA_HARNESSES.items():
        if hid in providers:
            try:
                logs.extend(h["list"]())
            except Exception as exc:  # one broken harness must never break search
                sys.stderr.write(f"[navcom] skipped {hid}: {type(exc).__name__}: {exc}\n")
    logs.sort(key=lambda x: x[1])
    for key, _, _, provider in logs:
        _PROVIDER_BY_KEY[key] = provider
    return logs


def log_for_path(path_str):
    """Build a log tuple for an explicit --file argument."""
    if "#" in path_str and not Path(path_str).exists():
        return (path_str, 0.0, 0, detect_provider_from_path(path_str))
    path = Path(path_str).expanduser()
    try:
        stat = path.stat()
    except OSError:
        return None
    provider = detect_provider_from_path(str(path))
    return (str(path), stat.st_mtime, stat.st_size, provider)


# ─────────────────────────────────────────────────────────────────────────────
# Turn extraction per harness → (role, text) with role in user/assistant/cmd
# ─────────────────────────────────────────────────────────────────────────────

class _LinesSource:
    """Duck-types the Path.open() the embedded iterators expect, over in-memory lines."""

    def __init__(self, text):
        self.text = text

    def open(self, *args, **kwargs):
        return io.StringIO(self.text)


def _text_of(content):
    if isinstance(content, str):
        return content
    parts = []
    if isinstance(content, list):
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get("type", "text") in ("text", "input_text", "output_text"):
                if isinstance(item.get("text"), str):
                    parts.append(item["text"])
    return "\n".join(p for p in parts if p)


SHELL_TOOL_NAMES = ("bash", "shell", "exec_command", "run_command", "command", "terminal")


def _is_shell_tool(name):
    lower = (name or "").lower()
    return any(tok in lower for tok in SHELL_TOOL_NAMES)


def iter_pi_lines(lines):
    """pi / omo session JSONL: {"type":"message","message":{role, content}} records."""
    calls = {}
    for line in lines:
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if not isinstance(obj, dict) or obj.get("type") != "message":
            continue
        msg = obj.get("message")
        if not isinstance(msg, dict):
            continue
        role = msg.get("role")
        content = msg.get("content")
        if role == "user":
            text = _text_of(content)
            if text:
                yield "user", text
        elif role == "toolResult":
            turn = tool_turn(calls.get(msg.get("toolCallId"), msg.get("toolName") or "tool"), content)
            if turn:
                yield turn
        elif role == "assistant":
            buf = []
            for item in content if isinstance(content, list) else [content]:
                if isinstance(item, str):
                    buf.append(item)
                    continue
                if not isinstance(item, dict):
                    continue
                if item.get("type") == "text" and isinstance(item.get("text"), str):
                    buf.append(item["text"])
                elif item.get("type") == "toolCall":
                    args = item.get("arguments") or {}
                    calls[item.get("id")] = _call_label(item.get("name"), args)
                    cmd = _shell_cmd(item.get("name"), args)
                    if cmd:
                        if buf:
                            yield "assistant", "\n".join(buf)
                            buf = []
                        yield "cmd", cmd
            if buf:
                yield "assistant", "\n".join(buf)
        elif role == "bashExecution":
            cmd = msg.get("command")
            if isinstance(cmd, str) and cmd.strip():
                yield "cmd", cmd
                turn = tool_turn(f"bash: {cmd}", msg.get("output"))
                if turn:
                    yield turn


def _goose_content_turns(role, content, calls=None):
    calls = {} if calls is None else calls
    buf = []
    for item in content if isinstance(content, list) else []:
        if not isinstance(item, dict):
            continue
        itype = item.get("type")
        if itype == "text" and isinstance(item.get("text"), str):
            buf.append(item["text"])
        elif itype == "toolRequest":
            call = item.get("toolCall") or {}
            value = call.get("value") if isinstance(call, dict) else None
            if isinstance(value, dict):
                args = value.get("arguments") or {}
                calls[item.get("id")] = _call_label(value.get("name"), args)
                cmd = _shell_cmd(value.get("name"), args)
                if cmd:
                    if buf:
                        yield role, "\n".join(buf)
                        buf = []
                    yield "cmd", cmd
        elif itype == "toolResponse":
            result = item.get("toolResult") or {}
            output = result.get("value") if isinstance(result, dict) else None
            if isinstance(result, dict) and result.get("status") == "error":
                output = result.get("error")
            turn = tool_turn(calls.get(item.get("id"), "tool"), output)
            if turn:
                if buf:
                    yield role, "\n".join(buf)
                    buf = []
                yield turn
    if buf:
        yield role, "\n".join(buf)


def iter_goose_lines(lines):
    """Legacy goose .jsonl: first line is session metadata, then one Message per line."""
    calls = {}
    for line in lines:
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if not isinstance(obj, dict) or obj.get("role") not in ("user", "assistant"):
            continue
        yield from _goose_content_turns(obj["role"], obj.get("content"), calls)


def iter_goose_db(key):
    db, sid = key.split("#", 1)
    try:
        con = _ro_connect(db)
        rows = con.execute(
            "SELECT role, content_json FROM messages WHERE session_id=? ORDER BY created_timestamp, id",
            (sid,),
        ).fetchall()
        con.close()
    except sqlite3.Error:
        return
    calls = {}
    for role, content_json in rows:
        if role not in ("user", "assistant"):
            continue
        try:
            content = json.loads(content_json)
        except Exception:
            continue
        yield from _goose_content_turns(role, content, calls)


def _opencode_parts_turns(role, parts):
    buf = []
    for part in parts:
        if not isinstance(part, dict):
            continue
        ptype = part.get("type")
        if ptype == "text" and isinstance(part.get("text"), str):
            if part.get("synthetic"):
                continue
            buf.append(part["text"])
        elif ptype == "tool":
            state = part.get("state") or {}
            args = state.get("input") if isinstance(state, dict) else None
            cmd = _shell_cmd(part.get("tool"), args)
            if buf and (cmd or state.get("output")):
                yield role, "\n".join(buf)
                buf = []
            if cmd:
                yield "cmd", cmd
            if isinstance(state, dict):
                turn = tool_turn(_call_label(part.get("tool"), args), state.get("output") or state.get("error"))
                if turn:
                    yield turn
    if buf:
        yield role, "\n".join(buf)


def iter_opencode_db(key):
    db, sid = key.split("#", 1)
    try:
        con = _ro_connect(db)
        messages = con.execute(
            "SELECT id, data FROM message WHERE session_id=? ORDER BY time_created, id", (sid,)
        ).fetchall()
        parts = con.execute(
            "SELECT message_id, data FROM part WHERE session_id=? ORDER BY time_created, id", (sid,)
        ).fetchall()
        con.close()
    except sqlite3.Error:
        return
    by_message = {}
    for mid, data in parts:
        try:
            by_message.setdefault(mid, []).append(json.loads(data))
        except Exception:
            continue
    for mid, data in messages:
        try:
            role = json.loads(data).get("role")
        except Exception:
            continue
        if role in ("user", "assistant"):
            yield from _opencode_parts_turns(role, by_message.get(mid, []))


def iter_opencode_legacy(key):
    session_dir = Path(key)
    part_root = session_dir.parent.parent / "part"
    messages = []
    for path in session_dir.glob("*.json"):
        try:
            obj = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        created = ((obj.get("time") or {}).get("created")) or 0
        messages.append((created, obj.get("id") or path.stem, obj.get("role")))
    messages.sort()
    for _, mid, role in messages:
        if role not in ("user", "assistant"):
            continue
        parts = []
        for ppath in sorted((part_root / mid).glob("*.json")):
            try:
                parts.append(json.loads(ppath.read_text(encoding="utf-8", errors="replace")))
            except Exception:
                continue
        yield from _opencode_parts_turns(role, parts)


def _read_complete_lines(path, offset):
    """Read whole lines appended after `offset`. Returns (text, new_offset).

    A half-written trailing line (the harness is mid-flush) is left for next time.
    """
    with open(path, "rb") as handle:
        if offset:
            handle.seek(offset)
        data = handle.read()
    cut = data.rfind(b"\n")
    if cut == -1:
        return "", offset
    return data[: cut + 1].decode("utf-8", errors="replace"), offset + cut + 1


JSONL_PROVIDERS = ("claude", "codex", "pi", "omo", "goose")
_IS_META_RE = re.compile(r'"isMeta"\s*:\s*true')

_SLASH_COMMAND_RE = re.compile(r"<command-name>\s*(.*?)\s*</command-name>", re.DOTALL)
_SLASH_ARGS_RE = re.compile(r"<command-args>\s*(.*?)\s*</command-args>", re.DOTALL)


def _rescue_slash_command(text):
    """Claude logs slash commands as <command-name>/goal</command-name><command-args>…</command-args>.

    The args are often the most important thing the user typed (a /goal, a /loop
    prompt), so keep them as "/goal …" instead of discarding the whole turn.
    """
    name = _SLASH_COMMAND_RE.search(text)
    args = _SLASH_ARGS_RE.search(text)
    if not name or not args or not args.group(1).strip():
        return None
    return f"{name.group(1).strip()} {args.group(1).strip()}"


def _raw_turns(key, provider, text_chunk=None):
    if provider in EXTRA_HARNESSES:
        return EXTRA_HARNESSES[provider]["iter"](key)
    if provider == "gemini":
        return iter_gemini_jsonl(key) if key.endswith(".jsonl") else iter_gemini_file(key)
    if provider == "dsh":
        return iter_dsh(key)
    if provider == "grok":
        return iter_grok_updates(key)
    if provider == "kilo":
        return iter_opencode_db(key)
    if provider == "opencode":
        return iter_opencode_db(key) if "#" in key else iter_opencode_legacy(key)
    if provider == "goose" and "#" in key:
        return iter_goose_db(key)
    if text_chunk is None:
        text_chunk, _ = _read_complete_lines(key, 0)
    if provider in ("pi", "omo"):
        return iter_pi_lines(text_chunk.splitlines())
    if provider == "goose":
        return iter_goose_lines(text_chunk.splitlines())
    if provider == "claude":
        return iter_claude_lines(text_chunk.splitlines())
    return iter_codex_lines(text_chunk.splitlines())


def iter_clean_turns(key, provider, text_chunk=None):
    last = None
    for role, text in _raw_turns(str(key), provider, text_chunk):
        if role not in ("user", "assistant", "cmd", "tool"):
            continue
        if isinstance(text, (list, dict)):
            # newer Gemini logs store content as a list of {"text": …} parts
            text = _text_of(text if isinstance(text, list) else [text]) or ""
        if not isinstance(text, str):
            text = str(text)
        raw = clean_mod.clean_text(text)
        if not raw:
            continue
        if role == "user" and "<command-name>" in raw:
            rescued = _rescue_slash_command(raw)
            if rescued:
                raw = rescued
        if clean_mod.is_preamble(role, raw, provider):
            continue
        raw = strip_ansi(_strip_conversation_artifacts(raw))
        if not raw:
            continue
        dedupe_key = (role, raw)
        if dedupe_key == last:
            continue
        last = dedupe_key
        yield role, raw


# ─────────────────────────────────────────────────────────────────────────────
# Tool outputs — what commands printed, files that were read, errors, test runs
# ─────────────────────────────────────────────────────────────────────────────
# Indexed as role "tool", capped (head + tail: errors live at the end), labelled with the
# call that produced them. Left out of normal searches; `--tool` searches only them.

TOOL_HEAD_CHARS = 3000
TOOL_TAIL_CHARS = 1000
_DATA_URI_RE = re.compile(r"data:[\w/+.-]+;base64,[A-Za-z0-9+/=\s]{200,}")
_BLOB_RE = re.compile(r"[A-Za-z0-9+/=]{600,}")
_NAVCOM_OUTPUT_MARKERS = ("→ read around a hit: navcom --open", "navcom: no session matches", "No hits. (query:",
                          "usage: navcom [words")
# a command that IS a navcom call (optionally after cd/env), not one that merely mentions navcom
_NAVCOM_LEADING_RE = re.compile(r"^\s*(?:cd\s+\S+\s*(?:&&|;)\s*)?(?:\w+=\S+\s+)*(?:\S*/)?navcom(?:\.py)?(?:\s|$)")


def cap_tool_output(text):
    text = _BLOB_RE.sub("[binary data]", _DATA_URI_RE.sub("[binary data]", strip_ansi(text or ""))).strip()
    if len(text) <= TOOL_HEAD_CHARS + TOOL_TAIL_CHARS + 200:
        return text
    omitted = len(text) - TOOL_HEAD_CHARS - TOOL_TAIL_CHARS
    return f"{text[:TOOL_HEAD_CHARS]}\n…[{omitted} chars omitted]…\n{text[-TOOL_TAIL_CHARS:]}"


def _is_navcom_output(label, text):
    command = label.split(": ", 1)[1] if label and ": " in label else ""
    if command and _NAVCOM_LEADING_RE.match(command):
        return True
    head = (text or "")[:400]
    return head.startswith("navcom: ") or any(m in (text or "") for m in _NAVCOM_OUTPUT_MARKERS)


def tool_turn(label, output):
    """('tool', '[label]\\n<capped output>') or None for empty / navcom's own output."""
    if isinstance(output, (list, dict)):
        output = _text_of(output if isinstance(output, list) else [output]) or (
            json.dumps(output, ensure_ascii=False)[:20000] if output else "")
    if not isinstance(output, str) or not output.strip():
        return None
    stripped = output.strip()
    if stripped.startswith("{") and '"output"' in stripped[:2000]:
        # Codex wraps command results: {"exit_code":2,"wall_time_seconds":…,"output":"…"}
        try:
            env = json.loads(stripped)
            if isinstance(env, dict) and isinstance(env.get("output"), str):
                code = env.get("exit_code", env.get("metadata", {}).get("exit_code") if isinstance(env.get("metadata"), dict) else None)
                output = (f"exit {code}\n" if code not in (None, 0) else "") + env["output"]
        except Exception:
            pass
    if _is_navcom_output(label, output):
        return None
    body = cap_tool_output(output)
    if not body:
        return None
    label = re.sub(r"\s+", " ", (label or "tool")).strip()[:200]
    return "tool", f"[{label}]\n{body}"


def _call_label(name, args):
    """Human label for a tool call: 'Bash: npm test', 'Read: src/app.ts', 'Grep: TODO'."""
    name = name or "tool"
    if isinstance(args, str):
        return f"{name}: {args[:160]}"
    if isinstance(args, dict):
        for key in ("command", "cmd", "file_path", "path", "pattern", "query", "url", "description", "prompt"):
            value = args.get(key)
            if isinstance(value, list):
                value = " ".join(str(v) for v in value)
            if isinstance(value, str) and value.strip():
                return f"{name}: {value.strip()[:160]}"
    return name


def _shell_cmd(name, args):
    """The shell command a tool call ran, if it is a shell-ish tool."""
    if not _is_shell_tool(name) or not isinstance(args, dict):
        return None
    for key in ("command", "cmd", "script"):
        value = args.get(key)
        if isinstance(value, list):
            value = " ".join(str(v) for v in value)
            if value.startswith(("bash -lc ", "bash -c ", "zsh -lc ", "sh -c ")):
                value = value.split(" ", 2)[2] if value.count(" ") >= 2 else value
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


# Codex's newer "exec" tool wraps calls in JS: await tools.exec_command({"cmd": "…"})
_CODEX_JS_CMD_RE = re.compile(r'exec_command\(\s*\{\s*"?cmd"?\s*:\s*("(?:[^"\\]|\\.)*"|`(?:[^`\\]|\\.)*`)')


def _codex_js_cmds(code):
    cmds = []
    for raw in _CODEX_JS_CMD_RE.findall(code or ""):
        if raw.startswith('"'):
            try:
                cmds.append(json.loads(raw))
                continue
            except Exception:
                pass
        cmds.append(raw[1:-1])
    return cmds


def iter_claude_lines(lines):
    """Claude Code JSONL: text turns, shell commands, and tool results (labelled by their call)."""
    calls = {}
    for line in lines:
        if _IS_META_RE.search(line):
            continue  # harness-injected (hook output, caveats), not the user speaking
        try:
            obj = json.loads(line)
        except Exception:
            continue
        msg = obj.get("message") if isinstance(obj, dict) else None
        if not isinstance(msg, dict):
            continue
        role, content = msg.get("role"), msg.get("content")
        if isinstance(content, list):
            for item in content:
                if not isinstance(item, dict):
                    continue
                if item.get("type") == "tool_use":
                    args = item.get("input") or {}
                    calls[item.get("id")] = _call_label(item.get("name"), args)
                    cmd = _shell_cmd(item.get("name"), args)
                    if cmd:
                        yield "cmd", cmd
            text = clean_mod.extract_text_content(content, False)
            if text and role in ("user", "assistant"):
                yield role, text
            for item in content:
                if isinstance(item, dict) and item.get("type") == "tool_result":
                    turn = tool_turn(calls.get(item.get("tool_use_id"), "tool"), item.get("content"))
                    if turn:
                        yield turn
        elif isinstance(content, str) and role in ("user", "assistant") and content.strip():
            yield role, content


def iter_codex_lines(lines):
    """Codex rollout JSONL: messages, commands (shell / exec_command / JS exec) and their outputs."""
    calls = {}
    for line in lines:
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if not isinstance(obj, dict):
            continue
        kind, payload = obj.get("type"), obj.get("payload") or {}
        ptype = payload.get("type") if isinstance(payload, dict) else None
        if kind == "response_item":
            if ptype == "message":
                text = _text_of(payload.get("content") or [])
                if text:
                    yield payload.get("role") or "assistant", text
            elif ptype in ("function_call", "custom_tool_call", "local_shell_call"):
                name = payload.get("name") or ("shell" if ptype == "local_shell_call" else "tool")
                raw = payload.get("arguments", payload.get("input", payload.get("action")))
                args = raw
                if isinstance(raw, str):
                    try:
                        args = json.loads(raw)
                    except Exception:
                        args = raw
                if isinstance(args, str):  # custom tools (exec JS, apply_patch) take free text
                    cmds = _codex_js_cmds(args)
                    label = f"{name}: {cmds[0]}" if cmds else f"{name}: {args.strip()[:160]}"
                else:
                    cmd = _shell_cmd(name, args)
                    cmds = [cmd] if cmd else []
                    label = _call_label(name, args)
                calls[payload.get("call_id")] = label
                for cmd in cmds:
                    yield "cmd", cmd
            elif ptype and ptype.endswith("_output"):
                output = payload.get("output")
                if isinstance(output, str):
                    try:
                        parsed = json.loads(output)
                        if isinstance(parsed, dict) and isinstance(parsed.get("output"), str):
                            output = parsed["output"]
                    except Exception:
                        pass
                turn = tool_turn(calls.get(payload.get("call_id"), ptype.replace("_output", "")), output)
                if turn:
                    yield turn
        elif kind == "event_msg":
            if ptype == "user_message":
                yield "user", payload.get("message", "")
            elif ptype == "agent_message":
                yield "assistant", payload.get("message", "")


def iter_gemini_file(path):
    try:
        obj = json.loads(Path(path).read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return
    for msg in obj.get("messages", []) if isinstance(obj, dict) else []:
        if not isinstance(msg, dict):
            continue
        mtype = msg.get("type")
        role = "user" if mtype == "user" else "assistant" if mtype in ("gemini", "assistant", "model") else None
        if role is None:
            continue
        content = msg.get("content")
        text = content if isinstance(content, str) else _text_of(content if isinstance(content, list) else [content])
        if text:
            yield role, text
        for call in msg.get("toolCalls") or []:
            if not isinstance(call, dict):
                continue
            cmd = _shell_cmd(call.get("name"), call.get("args"))
            if cmd:
                yield "cmd", cmd
            output = call.get("resultDisplay")
            if not isinstance(output, str) or not output.strip():
                output = "\n".join(fts_mod.extract_gemini_strings(call.get("result")))
            turn = tool_turn(_call_label(call.get("name"), call.get("args")), output)
            if turn:
                yield turn



# ─────────────────────────────────────────────────────────────────────────────
# Gemini CLI ≥ 0.39 (.jsonl), DeepSeek Harness (dsh), Grok Build, Kilo Code
# ─────────────────────────────────────────────────────────────────────────────

def gemini_tmp_roots():
    """Gemini keeps per-project chats under <home>/.gemini/tmp (GEMINI_CLI_HOME replaces <home>);
    under the macOS seatbelt sandbox it uses ~/.cache/.gemini/tmp."""
    roots = []
    explicit = _env_path("GEMINI_CLI_HOME")
    if explicit:
        roots.append(explicit / ".gemini" / "tmp")
    roots.append(fts_mod.gemini_tmp_root())
    roots.append(Path.home() / ".cache" / ".gemini" / "tmp")
    out, seen = [], set()
    for root in roots:
        if str(root) not in seen:
            seen.add(str(root))
            out.append(root)
    return out


def replay_gemini_jsonl(lines):
    """Rebuild a Gemini ≥0.39 session from its append-only record log.

    Records: metadata, message (a later line with the same id replaces it), {"$set": …}
    (legacy full `messages` checkpoint), {"$patch": …} (edit/remove/reorder) and
    {"$rewindTo": id} (drop that message and everything after it).
    """
    msgs, order, meta = {}, [], {}

    def apply(update):
        mid = update.get("id")
        if mid in msgs:
            target = msgs[mid]
            for field in ("content", "displayContent", "thoughts"):
                if field in update:
                    target[field] = update[field]
            for tc in update.get("toolCalls") or []:
                for existing in target.setdefault("toolCalls", []):
                    if existing.get("id") == tc.get("id"):
                        existing.update(tc)
                        break
                else:
                    target["toolCalls"].append(tc)

    for line in lines:
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if not isinstance(obj, dict):
            continue
        if "$set" in obj and isinstance(obj["$set"], dict):
            fields = dict(obj["$set"])
            if isinstance(fields.get("messages"), list):
                msgs = {m.get("id"): m for m in fields["messages"] if isinstance(m, dict)}
                order = [m.get("id") for m in fields.pop("messages") if isinstance(m, dict)]
            meta.update(fields)
        elif "$patch" in obj and isinstance(obj["$patch"], dict):
            patch = obj["$patch"]
            if patch.get("id"):
                apply(patch)
            for update in patch.get("updates") or []:
                if isinstance(update, dict):
                    apply(update)
            for rid in patch.get("removeIds") or []:
                msgs.pop(rid, None)
            if patch.get("orderIds"):
                order = [i for i in patch["orderIds"] if i in msgs] + [i for i in order if i not in patch["orderIds"]]
        elif "$rewindTo" in obj:
            target = obj["$rewindTo"]
            if target in order:
                for dropped in order[order.index(target):]:
                    msgs.pop(dropped, None)
                order = order[:order.index(target)]
        elif obj.get("id") and obj.get("type"):
            if obj["id"] not in msgs:
                order.append(obj["id"])
            msgs[obj["id"]] = obj
        elif obj.get("sessionId"):
            meta.update(obj)
    return [msgs[i] for i in order if i in msgs], meta


def _gemini_messages_turns(messages):
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        mtype = msg.get("type")
        role = "user" if mtype == "user" else "assistant" if mtype in ("gemini", "assistant", "model") else None
        if role is None:
            continue
        content = msg.get("content")
        text = content if isinstance(content, str) else _text_of(content if isinstance(content, list) else [content])
        if text:
            yield role, text
        for call in msg.get("toolCalls") or []:
            if not isinstance(call, dict):
                continue
            cmd = _shell_cmd(call.get("name"), call.get("args"))
            if cmd:
                yield "cmd", cmd
            output = call.get("resultDisplay")
            if not isinstance(output, str) or not output.strip():
                output = "\n".join(fts_mod.extract_gemini_strings(call.get("result")))
            turn = tool_turn(_call_label(call.get("name"), call.get("args")), output)
            if turn:
                yield turn


def iter_gemini_jsonl(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            messages, _ = replay_gemini_jsonl(handle)
    except OSError:
        return
    yield from _gemini_messages_turns(messages)


def _gemini_jsonl_meta(path):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            _, meta = replay_gemini_jsonl(handle)
        return meta
    except OSError:
        return {}


# DeepSeek Harness ─ $DSH_HOME/sessions/--<cwd>--/<session-…>/session.v<N>.jsonl.zstd

def dsh_sessions_root():
    return (_env_path("DSH_HOME") or Path.home() / ".dsh") / "sessions"


_ZSTD_WARNED = []


def read_zstd(path):
    """Decompress a (possibly multi-frame, possibly still-being-written) zstd file."""
    data = Path(path).read_bytes()
    try:
        from compression import zstd as pyzstd  # Python 3.14+
        out, buf = [], data
        while buf:
            dec = pyzstd.ZstdDecompressor()
            try:
                out.append(dec.decompress(buf))
            except Exception:
                break
            if not dec.eof:
                break  # last frame still being written
            buf = dec.unused_data
        return b"".join(out)
    except ImportError:
        pass
    try:
        import zstandard
        reader = zstandard.ZstdDecompressor().stream_reader(io.BytesIO(data), read_across_frames=True)
        chunks = []
        try:
            while True:
                chunk = reader.read(1 << 20)
                if not chunk:
                    break
                chunks.append(chunk)
        except Exception:
            pass
        return b"".join(chunks)
    except ImportError:
        pass
    exe = shutil.which("zstd")
    if exe:
        proc = subprocess.run([exe, "-dcq"], input=data, capture_output=True)
        return proc.stdout  # partial output is still good on a truncated last frame
    if not _ZSTD_WARNED:
        _ZSTD_WARNED.append(1)
        sys.stderr.write("[navcom] DeepSeek Harness sessions are zstd-compressed: install zstd "
                         "(brew install zstd / apt install zstd) to index them\n")
    return b""


def list_dsh_logs():
    root = dsh_sessions_root()
    logs = []
    if not root.is_dir():
        return logs
    for session_dir in root.glob("*/*"):
        if not session_dir.is_dir():
            continue
        candidates = list(session_dir.glob("session.v*.jsonl.zstd")) + list(session_dir.glob("session.jsonl"))
        if not candidates:
            continue

        def version(p):
            m = re.search(r"session\.v(\d+)\.jsonl", p.name)
            return int(m.group(1)) if m else 0
        logs.extend(_file_logs([max(candidates, key=version)], "dsh"))
    return logs


def _dsh_lines(key):
    raw = read_zstd(key) if key.endswith(".zstd") else Path(key).read_bytes()
    return raw.decode("utf-8", errors="replace").splitlines()


def iter_dsh(key):
    calls = {}
    for line in _dsh_lines(key):
        try:
            obj = json.loads(line)
        except Exception:
            continue
        kind, data = obj.get("type"), obj.get("data") or {}
        if kind == "user/message":
            if (data.get("source") or {}).get("kind", "user") != "user":
                continue  # runtime context, skill catalogs, reminders — injected, not typed
            text = _text_of(data.get("content") or [])
            if text:
                yield "user", text
        elif kind == "assistant/message":
            text = _text_of((data.get("message") or {}).get("content") or [])
            if text:
                yield "assistant", text
        elif kind == "tool/call":
            args = data.get("arguments")
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except Exception:
                    pass
            calls[data.get("callId")] = _call_label(data.get("name"), args)
            cmd = _shell_cmd(data.get("name"), args)
            if cmd:
                yield "cmd", cmd
        elif kind == "tool/result":
            msg = data.get("message") or {}
            output = msg.get("content")
            if msg.get("isError"):
                output = "error\n" + (_text_of(output) if isinstance(output, list) else str(output or ""))
            turn = tool_turn(calls.get(msg.get("toolCallId"), "tool"), output)
            if turn:
                yield turn


def _dsh_header(key):
    for line in _dsh_lines(key)[:1]:
        try:
            return json.loads(line)
        except Exception:
            return {}
    return {}


def _dsh_title(key):
    title = ""
    for line in _dsh_lines(key):
        if '"session/title"' in line:
            try:
                title = (json.loads(line).get("data") or {}).get("title") or title
            except Exception:
                pass
    return title


# Grok Build (xAI) ─ $GROK_HOME/sessions/<urlencoded cwd>/<uuidv7>/updates.jsonl

def grok_sessions_root():
    return (_env_path("GROK_HOME") or Path.home() / ".grok") / "sessions"


def list_grok_logs():
    root = grok_sessions_root()
    if not root.is_dir():
        return []
    return _file_logs([p for p in root.glob("*/*/updates.jsonl")], "grok")


def _acp_text(content):
    """ACP content: {"type":"text","text"} | [{"type":"content","content":{…}}, …] | diffs."""
    if isinstance(content, dict):
        if content.get("type") == "text":
            return content.get("text") or ""
        if content.get("type") == "content":
            return _acp_text(content.get("content"))
        if content.get("type") == "diff":
            return f"diff {content.get('path', '')}\n{content.get('newText', '')}"
        return ""
    if isinstance(content, list):
        return "\n".join(t for t in (_acp_text(c) for c in content) if t)
    return content if isinstance(content, str) else ""


def iter_grok_updates(key):
    calls, role, buf = {}, None, []
    try:
        handle = open(key, "r", encoding="utf-8", errors="replace")
    except OSError:
        return
    with handle:
        for line in handle:
            try:
                obj = json.loads(line)
            except Exception:
                continue
            update = (obj.get("params") or {}).get("update") or obj.get("update") or (
                obj if "sessionUpdate" in obj else None)
            if not isinstance(update, dict):
                continue
            tag = update.get("sessionUpdate")
            if tag in ("user_message_chunk", "agent_message_chunk"):
                speaker = "user" if tag == "user_message_chunk" else "assistant"
                content = update.get("content") or {}
                meta = update.get("_meta") or {}
                bash = (content.get("_meta") or {}).get("bash_command") if isinstance(content, dict) else None
                if meta.get("hostTurn") or bash:
                    if role and buf:
                        yield role, "".join(buf)
                    role, buf = None, []
                    if bash:
                        yield "cmd", bash
                    continue
                if role != speaker:
                    if role and buf:
                        yield role, "".join(buf)
                    role, buf = speaker, []
                buf.append(_acp_text(content))
                continue
            if role and buf and tag in ("tool_call", "tool_call_update"):
                yield role, "".join(buf)
                role, buf = None, []
            if tag == "tool_call":
                raw = update.get("rawInput") or {}
                cmd = raw.get("command") if isinstance(raw, dict) else None
                if isinstance(cmd, list):
                    cmd = " ".join(str(c) for c in cmd)
                calls[update.get("toolCallId")] = (f"{update.get('title') or update.get('kind') or 'tool'}"
                                                   + (f": {cmd}" if cmd and cmd not in str(update.get("title")) else ""))
                if cmd and (update.get("kind") == "execute" or "command" in raw):
                    yield "cmd", cmd
            elif tag == "tool_call_update" and update.get("status") in ("completed", "failed"):
                output = _acp_text(update.get("content"))
                if not output.strip():
                    raw = update.get("rawOutput")
                    if isinstance(raw, dict):
                        output = "\n".join(str(raw[k]) for k in ("output", "stdout", "stderr", "text", "result")
                                           if isinstance(raw.get(k), (str, int, float)) and str(raw[k]).strip())
                        if not output:
                            output = json.dumps(raw, ensure_ascii=False)[:20000]
                    elif isinstance(raw, str):
                        output = raw
                if update.get("status") == "failed":
                    output = "failed\n" + output
                turn = tool_turn(calls.get(update.get("toolCallId"), "tool"), output)
                if turn:
                    yield turn
    if role and buf:
        yield role, "".join(buf)


def _grok_summary(key):
    try:
        return json.loads((Path(key).parent / "summary.json").read_text(encoding="utf-8"))
    except Exception:
        return {}


def _grok_cwd(key):
    summary = _grok_summary(key)
    info = summary.get("info") if isinstance(summary.get("info"), dict) else {}
    for source in (info, summary):
        for field in ("cwd", "working_directory", "workingDirectory"):
            if isinstance(source.get(field), str):
                return source[field]
    group = Path(key).parent.parent
    cwd_file = group / ".cwd"
    if cwd_file.exists():
        try:
            return cwd_file.read_text(encoding="utf-8").strip()
        except OSError:
            pass
    from urllib.parse import unquote
    return unquote(group.name)


# Kilo Code CLI (an opencode fork; same SQLite schema)

def kilo_db_path():
    return _env_path("KILO_DB") or _xdg_data_home() / "kilo" / "kilo.db"


# Gemini CLI deletes chats older than 30 days by default (general.sessionRetention)

def gemini_settings_path():
    home = _env_path("GEMINI_CLI_HOME") or Path.home()
    return home / ".gemini" / "settings.json"


def gemini_retention_status():
    path = gemini_settings_path()
    if not path.parent.is_dir():
        return None, "Gemini CLI not installed"
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except Exception:
        return None, f"{path} is not plain JSON — not touched"
    retention = ((data.get("general") or {}) if isinstance(data, dict) else {}).get("sessionRetention")
    if retention is None:
        return 30, "default — Gemini CLI deletes chats after 30 days"
    if isinstance(retention, dict) and retention.get("enabled") is False:
        return 10 ** 6, "set in " + str(path)
    max_age = str((retention or {}).get("maxAge", "30d"))
    m = re.match(r"(\d+)\s*([dhwmy]?)", max_age)
    days = int(m.group(1)) * {"d": 1, "h": 1 / 24, "w": 7, "m": 30, "y": 365, "": 1}[m.group(2)] if m else 30
    return days, "set in " + str(path)


def ensure_json_setting(path, dotted, value):
    """Set a dotted key in a plain-JSON settings file when it is unset (backup, atomic, never JSONC)."""
    path = Path(path)
    if not path.parent.is_dir():
        return False
    try:
        raw = path.read_text(encoding="utf-8") if path.exists() else ""
        data = json.loads(raw) if raw.strip() else {}
    except Exception:
        return False
    if not isinstance(data, dict):
        return False
    node, keys = data, dotted.split(".")
    for k in keys[:-1]:
        if not isinstance(node.get(k, {}), dict):
            return False
        node = node.setdefault(k, {})
    if keys[-1] in node:
        return False  # the owner chose a value — respect it
    node[keys[-1]] = value
    try:
        if raw:
            backup = path.with_name(path.name + ".navcom-backup")
            if not backup.exists():
                backup.write_text(raw, encoding="utf-8")
        tmp = path.with_name(path.name + f".navcom-tmp-{os.getpid()}")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        if path.exists():
            os.chmod(tmp, path.stat().st_mode & 0o777)
        os.replace(tmp, path)
    except OSError:
        return False
    return True


def _yaml_value(value):
    return "true" if value is True else "false" if value is False else str(value)


def yaml_setting(path, dotted):
    """Read a two-level `section.key` from simple block YAML without a YAML library."""
    section, key = dotted.split(".", 1)
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    inside = False
    for line in lines:
        if re.match(rf"^{re.escape(section)}:\s*(#.*)?$", line):
            inside = True
            continue
        if inside and line and not line[0].isspace() and not line.lstrip().startswith("#"):
            inside = False
        m = re.match(rf"^\s+{re.escape(key)}:\s*([^#]*?)\s*(#.*)?$", line) if inside else None
        if m:
            return m.group(1)
    return None


def ensure_yaml_setting(path, dotted, value):
    """Add `section.key: value` to block YAML when unset — the only edit ever made: one line
    under an existing top-level `section:` (matching its indentation), or a new block at the end.
    Flow-style or otherwise unusual files are left alone."""
    path = Path(path)
    if not path.parent.is_dir() or yaml_setting(path, dotted) is not None:
        return False
    section, key = dotted.split(".", 1)
    try:
        raw = path.read_text(encoding="utf-8") if path.exists() else ""
    except OSError:
        return False
    lines = raw.splitlines()
    header = next((i for i, l in enumerate(lines) if re.match(rf"^{re.escape(section)}:\s*(#.*)?$", l)), None)
    if header is None:
        if re.search(rf"^{re.escape(section)}:", raw, re.M):
            return False  # e.g. `sessions: {…}` flow style — don't guess
        new = raw + ("" if raw.endswith("\n") or not raw else "\n") + f"{section}:\n  {key}: {_yaml_value(value)}  # set by navcom: keep history\n"
    else:
        child = next((l for l in lines[header + 1:] if l.strip() and not l.lstrip().startswith("#")), "")
        indent = (re.match(r"^(\s+)", child).group(1) if child[:1].isspace() else "  ")
        lines.insert(header + 1, f"{indent}{key}: {_yaml_value(value)}  # set by navcom: keep history")
        new = "\n".join(lines) + "\n"
    try:
        if raw:
            backup = path.with_name(path.name + ".navcom-backup")
            if not backup.exists():
                backup.write_text(raw, encoding="utf-8")
        tmp = path.with_name(path.name + f".navcom-tmp-{os.getpid()}")
        tmp.write_text(new, encoding="utf-8")
        if path.exists():
            os.chmod(tmp, path.stat().st_mode & 0o777)
        os.replace(tmp, path)
    except OSError:
        return False
    return True


def json_setting(path, dotted):
    try:
        node = json.loads(Path(path).read_text(encoding="utf-8"))
        for k in dotted.split("."):
            node = node[k]
        return node
    except Exception:
        return None


def ensure_registered_retention():
    """Harnesses that auto-delete history declare how to stop it (see <id>_retention())."""
    if os.environ.get("NAVCOM_NO_RETENTION_FIX"):
        return
    for hid, h in EXTRA_HARNESSES.items():
        if not h.get("retention"):
            continue
        try:
            spec = h["retention"]()
            target = str(spec.get("settings_path", "")) if spec else ""
            if target.endswith(".json"):
                ensure_json_setting(target, spec["key_path"], spec["never_delete_value"])
            elif target.endswith((".yaml", ".yml")) and spec["key_path"].count(".") == 1:
                ensure_yaml_setting(target, spec["key_path"], spec["never_delete_value"])
            elif spec and spec.get("apply"):
                spec["apply"]()  # non-JSON settings (YAML…) supply their own careful editor
        except Exception:
            pass


def ensure_gemini_retention():
    """Turn Gemini's automatic chat deletion off when nobody has configured it."""
    if os.environ.get("NAVCOM_NO_RETENTION_FIX"):
        return False
    path = gemini_settings_path()
    if not path.parent.is_dir():
        return False
    try:
        raw = path.read_text(encoding="utf-8") if path.exists() else ""
        data = json.loads(raw) if raw.strip() else {}
    except Exception:
        return False
    if not isinstance(data, dict):
        return False
    general = data.setdefault("general", {})
    if not isinstance(general, dict) or "sessionRetention" in general:
        return False
    general["sessionRetention"] = {"enabled": False}
    try:
        if raw:
            backup = path.with_name(path.name + ".navcom-backup")
            if not backup.exists():
                backup.write_text(raw, encoding="utf-8")
        tmp = path.with_name(path.name + f".navcom-tmp-{os.getpid()}")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        if path.exists():
            os.chmod(tmp, path.stat().st_mode & 0o777)
        os.replace(tmp, path)
    except OSError:
        return False
    return True



# ─────────────────────────────────────────────────────────────────────────────
# Session metadata: project (working dir) + a human title
# ─────────────────────────────────────────────────────────────────────────────

def _project_from_key(key, provider):
    """Best-effort working directory for a session without touching the index."""
    if provider in EXTRA_HARNESSES:
        fn = EXTRA_HARNESSES[provider]["project"]
        try:
            return (fn(key) if fn else "") or ""
        except Exception:
            return ""
    path = Path(key.split("#", 1)[0])
    if provider == "claude":
        # ~/.claude/projects/<-Users-t-dev-navcom>/<uuid>.jsonl (subagents nest deeper)
        parts = key.split("/.claude/projects/", 1)
        if len(parts) == 2:
            return parts[1].split("/", 1)[0]
        return path.parent.name
    if provider in ("pi", "omo"):
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                header = json.loads(handle.readline())
            if isinstance(header, dict) and header.get("cwd"):
                return header["cwd"]
        except Exception:
            pass
        root = pi_sessions_root() if provider == "pi" else omo_sessions_root()
        try:
            return path.relative_to(root).parts[0]
        except (ValueError, IndexError):
            return path.parent.name
    if provider == "gemini":
        if key.endswith(".jsonl"):
            dirs = _gemini_jsonl_meta(key).get("directories") or []
            if dirs and isinstance(dirs[0], str):
                return dirs[0]
            chats = next((p for p in path.parents if p.name == "chats"), path.parent)
            return _gemini_project(chats.parent)
        return _gemini_project(path.parent.parent)
    if provider == "dsh":
        return _dsh_header(key).get("cwd") or ""
    if provider == "grok":
        return _grok_cwd(key)
    if provider == "codex":
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                first = handle.readline()
            obj = json.loads(first)
            payload = obj.get("payload") or {}
            return payload.get("cwd") or ""
        except Exception:
            return ""
    if provider in ("opencode", "kilo"):
        if "#" in key:
            db, sid = key.split("#", 1)
            try:
                con = _ro_connect(db)
                row = con.execute("SELECT directory FROM session WHERE id=?", (sid,)).fetchone()
                con.close()
                return row[0] if row else ""
            except sqlite3.Error:
                return ""
        return _opencode_legacy_info(key).get("directory") or ""
    if provider == "goose":
        if "#" in key:
            db, sid = key.split("#", 1)
            try:
                con = _ro_connect(db)
                row = con.execute("SELECT working_dir FROM sessions WHERE id=?", (sid,)).fetchone()
                con.close()
                return row[0] if row else ""
            except sqlite3.Error:
                return ""
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                return (json.loads(handle.readline()) or {}).get("working_dir") or ""
        except Exception:
            return ""
    return ""


_DECODED_DIRS = {}


def decode_encoded_dir(name):
    """'-Users-t-clients-syra-syrab2bdev' → '/Users/t/clients/syra/syrab2bdev' if that path exists.

    Claude Code and pi flatten the working dir by turning '/' (and '.', '_') into '-',
    which is ambiguous; walk the real filesystem to recover the original.
    """
    if name in _DECODED_DIRS:
        return _DECODED_DIRS[name]
    tokens = [t for t in name.strip("-").split("-")]
    result = None
    if tokens and all(tokens):
        def walk(base, i, budget=[4000]):
            if i == len(tokens):
                return base
            for j in range(len(tokens), i, -1):
                budget[0] -= 1
                if budget[0] <= 0:
                    return None
                chunk = tokens[i:j]
                for joiner in ("-", ".", "_"):
                    for lead in ("", "."):
                        cand = base / (lead + joiner.join(chunk))
                        if cand.is_dir():
                            found = walk(cand, j)
                            if found:
                                return found
                    if len(chunk) == 1:
                        break
            return None
        found = walk(Path("/"), 0)
        result = str(found) if found else None
    _DECODED_DIRS[name] = result
    return result


_GEMINI_DIRS = None


def _gemini_dir_map():
    """Gemini names its per-project tmp dir after the project (projects.json) or sha256(path)."""
    global _GEMINI_DIRS
    if _GEMINI_DIRS is not None:
        return _GEMINI_DIRS
    import hashlib
    mapping, candidates = {}, set()
    gem = Path.home() / ".gemini"
    try:
        projects = json.loads((gem / "projects.json").read_text()).get("projects", {})
        for path_str, name in projects.items():
            mapping[name] = path_str
            candidates.add(path_str)
    except Exception:
        pass
    try:
        candidates.update(json.loads((gem / "trustedFolders.json").read_text()).keys())
    except Exception:
        pass
    # working dirs other harnesses recorded are good guesses too
    try:
        for child in fts_mod.claude_projects_root().iterdir():
            decoded = decode_encoded_dir(child.name) if child.name.startswith("-") else None
            if decoded:
                candidates.add(decoded)
    except OSError:
        pass
    candidates.update(_KNOWN_CWDS)
    for cand in candidates:
        for variant in (cand, cand.rstrip("/")):
            mapping.setdefault(hashlib.sha256(variant.encode()).hexdigest(), variant)
    _GEMINI_DIRS = mapping
    return mapping


_KNOWN_CWDS = set()


def _gemini_project(project_dir):
    marker = project_dir / ".project_root"
    try:
        if marker.is_file():
            return marker.read_text(encoding="utf-8").strip()
    except OSError:
        pass
    name = project_dir.name
    resolved = _gemini_dir_map().get(name)
    if resolved:
        return resolved
    return "" if re.fullmatch(r"[0-9a-f]{32,}", name) else name


def pretty_project(project):
    """Shorten a project label for display: /Users/t/dev/x → ~/dev/x, -Users-t-dev-x → ~/dev-x."""
    if not project:
        return ""
    if project.startswith("-"):
        project = decode_encoded_dir(project) or project
    home = str(Path.home())
    if project.startswith(home):
        return "~" + project[len(home):]
    encoded_home = home.replace("/", "-").replace(".", "-")
    stripped = project.strip("-")
    if ("-" + stripped).startswith(encoded_home):
        rest = ("-" + stripped)[len(encoded_home):].lstrip("-")
        return "~/" + rest if rest else "~"
    return project


def _norm_project(text):
    norm = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    # macOS: /var, /tmp and /etc are symlinks into /private — harnesses record either form
    return norm[len("private-"):] if norm.startswith("private-") else norm


def _opencode_legacy_info(key):
    """storage/session/<project>/<session>.json holds title + directory for legacy opencode."""
    session_dir = Path(key)
    for info in (session_dir.parent.parent / "session").glob(f"*/{session_dir.name}.json"):
        try:
            return json.loads(info.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
    return {}


_GENERIC_SESSION_FILES = re.compile(
    r"^(updates\.jsonl|session(\.v\d+)?\.jsonl(\.zstd)?|wire\.jsonl|events\.jsonl|events\.frames|messages\.jsonl"
    r"|transcript(_full)?\.jsonl|ui_messages\.json|api_conversation_history\.json|context(_\d+)?\.jsonl)$")
# folder names inside a session folder that say nothing about which session it is
_GENERIC_SESSION_DIRS = {"main", "agents", "logs", ".system_generated", "events", "sessions", "chats", "state"}


def session_ref(key):
    """Short, stable handle for a session: the file stem / db session id (or the session's
    folder, for harnesses that name every transcript file the same: dsh, Grok Build)."""
    if "#" in key and key.rsplit("#", 1)[1].isdigit():
        # file#N (one aider history file holds many sessions): name it by its project folder
        return f"{Path(key.rsplit('#', 1)[0]).parent.name}@{key.rsplit('#', 1)[1]}"
    tail = key.split("#", 1)[1] if "#" in key else Path(key).name
    if "#" not in key and _GENERIC_SESSION_FILES.match(tail):
        for parent in Path(key).parents:  # nearest ancestor folder that names the session
            if parent.name and parent.name not in _GENERIC_SESSION_DIRS and not parent.name.startswith("agent-"):
                tail = parent.name
                break
    tail = re.sub(r"\.messages$", "", re.sub(r"\.(jsonl|json)$", "", tail))
    for ext in (".jsonl", ".json"):
        if tail.endswith(ext):
            tail = tail[: -len(ext)]
    # codex: rollout-2026-01-02T03-04-05-<uuid> → keep the uuid, it's what's unique
    match = re.search(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$", tail)
    if match:
        return match.group(1)
    match = re.search(r"_([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$", tail)
    return match.group(1) if match else tail


_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-([0-9a-f])[0-9a-f]{3}-[0-9a-f]{4}-[0-9a-f]{12}$")


def short_ref(key):
    ref = session_ref(key)
    match = _UUID_RE.match(ref)
    if not match:
        return ref
    # UUIDv7 (pi, omo, codex) starts with a timestamp, so its head collides across
    # sessions started the same minute — use the random tail instead.
    return ref[-12:] if match.group(1) == "7" else ref[:8]


# ─────────────────────────────────────────────────────────────────────────────
# Index: FTS5 table (shared with the embedded log_search_fts5) + side tables
# ─────────────────────────────────────────────────────────────────────────────

INDEX_SCHEMA_VERSION = 3  # 3: repair Gemini turns stored as {'text': …} reprs
# Bump when turn extraction changes; older rows get re-read gradually (see index_logs).
PARSER_VERSION = 3  # 3: tool outputs, Codex exec_command / JS exec commands
UPGRADE_BUDGET_SECONDS = 1.0
UPGRADE_BYTES_PER_SECOND = 40_000_000
MAX_UPGRADE_REREAD_BYTES = 200_000_000


INDEX_READ_ONLY = False


def open_index(index_path):
    """Open (and migrate) the index; fall back to read-only if we can't write to it."""
    global INDEX_READ_ONLY
    try:
        conn = _open_index_rw(index_path)
        private_file(index_path)  # -wal/-shm appear only once the connection is open
        return conn
    except sqlite3.OperationalError as exc:
        if not index_path.exists():
            raise
        sys.stderr.write(f"[navcom] index is not writable ({exc}); searching it read-only\n")
    INDEX_READ_ONLY = True
    try:
        conn = sqlite3.connect(f"file:{index_path}?mode=ro", uri=True, timeout=10)
        existing = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
    except sqlite3.OperationalError:
        # WAL needs a writable -shm file; immutable=1 reads the file as a snapshot
        conn = sqlite3.connect(f"file:{index_path}?mode=ro&immutable=1", uri=True, timeout=10)
        existing = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
    # temp-schema stand-ins so every query path still works without writing
    if "turn_loc" not in existing:
        conn.execute("CREATE TEMP VIEW turn_loc AS SELECT file, msg_index, rowid AS rid FROM session_fts")
    if "file_meta" not in existing:
        conn.execute("CREATE TEMP TABLE file_meta (file TEXT PRIMARY KEY, provider TEXT, project TEXT, title TEXT)")
    if "file_parser" not in existing:
        conn.execute("CREATE TEMP TABLE file_parser (file TEXT PRIMARY KEY, ver INTEGER NOT NULL)")
    return conn


def _open_index_rw(index_path):
    index_path.parent.mkdir(parents=True, exist_ok=True)
    if not index_path.exists():
        index_path.touch(mode=0o600)
    private_file(index_path)
    # short busy timeout: a parallel navcom that is mid-index shouldn't stall us —
    # we'd rather search the slightly stale index (reads never block under WAL)
    conn = sqlite3.connect(str(index_path), timeout=3)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    except sqlite3.OperationalError:
        pass
    fts_mod.ensure_db(conn)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS turn_loc (file TEXT NOT NULL, msg_index INTEGER NOT NULL,"
        " rid INTEGER NOT NULL, PRIMARY KEY (file, msg_index)) WITHOUT ROWID"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS file_meta (file TEXT PRIMARY KEY, provider TEXT, project TEXT, title TEXT)"
    )
    conn.execute("CREATE TABLE IF NOT EXISTS file_parser (file TEXT PRIMARY KEY, ver INTEGER NOT NULL)")
    conn.execute("CREATE INDEX IF NOT EXISTS turn_loc_rid ON turn_loc(rid)")  # makes max(rid) O(log n)
    conn.commit()
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version < INDEX_SCHEMA_VERSION:
        conn.execute("BEGIN IMMEDIATE")
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version < 2:
            # turn_loc lets window/transcript lookups hit a B-tree instead of
            # full-scanning the FTS table (which cannot index its columns).
            conn.execute("DELETE FROM turn_loc")
            conn.execute(
                "INSERT OR REPLACE INTO turn_loc (file, msg_index, rid) SELECT file, msg_index, rowid FROM session_fts"
            )
            conn.execute("DELETE FROM session_fts WHERE rowid NOT IN (SELECT rid FROM turn_loc)")
        if version < 3:
            _repair_part_reprs(conn)
        if version < INDEX_SCHEMA_VERSION:
            conn.execute(f"PRAGMA user_version={INDEX_SCHEMA_VERSION}")
        conn.commit()
    # An older navcom (no turn_loc) may have appended rows since we last ran.
    newest_row = conn.execute("SELECT max(rowid) FROM session_fts").fetchone()[0] or 0
    newest_loc = conn.execute("SELECT max(rid) FROM turn_loc").fetchone()[0] or 0
    if newest_row > newest_loc:
        conn.execute(
            "INSERT OR REPLACE INTO turn_loc (file, msg_index, rid)"
            " SELECT file, msg_index, rowid FROM session_fts WHERE rowid > ?",
            (newest_loc,),
        )
        conn.commit()
    return conn


def _repair_part_reprs(conn):
    """Old navcom stored some Gemini turns as Python reprs of their parts ({'text': '…'}). The parser was
    fixed long ago, but turns from transcripts Gemini has since deleted can't be re-read — fix them in place."""
    import ast
    rows = conn.execute("SELECT rowid, text FROM session_fts WHERE text LIKE '{''text'': %' OR text LIKE '[{''text'': %'").fetchall()
    for rowid, text in rows:
        try:
            value = ast.literal_eval(text)
        except (ValueError, SyntaxError, MemoryError, RecursionError):
            match = re.match(r"^\[?\{'text': (['\"])(.*?)(?:\1\}\]?)?$", text, re.S)  # capped: no closing quote
            if not match:
                continue
            body = match.group(2).replace("\\n", "\n").replace("\\t", "\t").replace("\\'", "'").replace('\\"', '"')
            value = {"text": body.replace("\\\\", "\\")}
        parts = value if isinstance(value, list) else [value]
        if not parts or not all(isinstance(p, dict) and isinstance(p.get("text"), str) for p in parts):
            continue
        conn.execute("UPDATE session_fts SET text=? WHERE rowid=?", ("\n".join(p["text"] for p in parts), rowid))


def _delete_key(conn, key):
    rids = [row[0] for row in conn.execute("SELECT rid FROM turn_loc WHERE file=?", (key,))]
    for start in range(0, len(rids), 500):
        chunk = rids[start : start + 500]
        conn.execute(f"DELETE FROM session_fts WHERE rowid IN ({','.join('?' * len(chunk))})", chunk)
    conn.execute("DELETE FROM turn_loc WHERE file=?", (key,))


def index_log(conn, log, force=False):
    """(Re)index one session. Appended JSONL is indexed incrementally from the stored offset."""
    key, mtime, size, provider = log
    row = conn.execute("SELECT mtime, size, offset, msg_index FROM file_state WHERE file=?", (key,)).fetchone()
    if row and not force and row[0] == mtime and row[1] == size:
        return False
    is_file = provider in JSONL_PROVIDERS and "#" not in key
    incremental = (
        not force and is_file and row is not None
        and row[2] and row[1] and size > row[1] and row[2] <= size and mtime >= row[0]
    )
    if incremental:
        ver = conn.execute("SELECT ver FROM file_parser WHERE file=?", (key,)).fetchone()
        # else one full re-read to pick up parser improvements — unless it's huge (multi-GB
        # codex logs), where stalling this call matters more than the older parse
        incremental = bool(ver and ver[0] >= PARSER_VERSION) or size > MAX_UPGRADE_REREAD_BYTES
    if incremental:
        offset, msg_index = row[2], row[3] or 0
    else:
        _delete_key(conn, key)
        offset, msg_index = 0, 0
    try:
        text_chunk = None
        if is_file:
            text_chunk, offset = _read_complete_lines(key, offset)
        else:
            offset = size
        for role, text in iter_clean_turns(key, provider, text_chunk):
            msg_index += 1
            cur = conn.execute(
                "INSERT INTO session_fts (text, role, file, ts, msg_index, provider) VALUES (?, ?, ?, ?, ?, ?)",
                (text, role or "", key, "", msg_index, provider),
            )
            conn.execute(
                "INSERT OR REPLACE INTO turn_loc (file, msg_index, rid) VALUES (?, ?, ?)",
                (key, msg_index, cur.lastrowid),
            )
    except OSError as exc:
        sys.stderr.write(f"[navcom] skipped unreadable log {key}: {exc}\n")
        return False
    conn.execute(
        "INSERT OR REPLACE INTO file_state (file, mtime, size, offset, msg_index) VALUES (?, ?, ?, ?, ?)",
        (key, mtime, size, offset, msg_index),
    )
    if not incremental:
        conn.execute("DELETE FROM file_meta WHERE file=?", (key,))
        conn.execute("INSERT OR REPLACE INTO file_parser (file, ver) VALUES (?, ?)", (key, PARSER_VERSION))
    return True


def index_logs(conn, logs, force=False, progress=True, upgrade=True):
    """Bring the index up to date; if it's locked or read-only, keep going with what's there."""
    global INDEX_READ_ONLY
    if INDEX_READ_ONLY:
        return 0
    try:
        return _index_logs(conn, logs, force, progress, upgrade)
    except sqlite3.OperationalError as exc:
        if _is_query_error(exc):
            raise
        try:
            conn.rollback()
        except sqlite3.Error:
            pass
        sys.stderr.write(f"[navcom] index not refreshed ({exc}); results may miss the newest turns\n")
        INDEX_READ_ONLY = True  # don't wait on the lock again for cache writes this run
        return 0


def _index_logs(conn, logs, force=False, progress=True, upgrade=True):
    # one query for every file's (mtime, size) instead of one per log: unchanged logs skip instantly
    known = {} if force else {f: (m, z) for f, m, z in conn.execute("SELECT file, mtime, size FROM file_state")}
    logs = [log for log in logs if known.get(log[0]) != (log[1], log[2])]
    changed = 0
    total = len(logs)
    announced = False
    for i, log in enumerate(logs, 1):
        if index_log(conn, log, force=force):
            changed += 1
            if changed % 200 == 0:
                conn.commit()
                if progress and not announced:
                    sys.stderr.write("[navcom] indexing new/changed sessions (first run takes a while)…\n")
                    announced = True
                if progress:
                    sys.stderr.write(f"[navcom]   {i}/{total}\n")
    conn.commit()
    if upgrade and not force:
        upgrade_stale_parses(conn, logs)
    return changed


def upgrade_stale_parses(conn, logs, budget=UPGRADE_BUDGET_SECONDS):
    """Re-read sessions indexed by an older parser, newest first, within a small time budget.

    Keeps every call fast after an upgrade while the index converges in the background
    of normal use. `navcom --reindex` does it all at once.
    """
    current = {row[0] for row in conn.execute("SELECT file FROM file_parser WHERE ver >= ?", (PARSER_VERSION,))}
    stale = [log for log in logs if log[0] not in current]
    if not stale:
        return 0
    import time
    deadline = None if budget is None else time.monotonic() + budget
    done = 0
    for log in reversed(stale):
        if deadline is not None:
            left = deadline - time.monotonic()
            if left <= 0:
                break
            if "#" not in log[0] and log[2] > left * UPGRADE_BYTES_PER_SECOND:
                continue  # too big for this call's budget; it upgrades on its next change or --reindex
        index_log(conn, log, force=True)
        done += 1
    conn.commit()
    return done


def session_meta(conn, key, provider=None):
    """(project, title) for a session, cached in file_meta."""
    row = conn.execute("SELECT project, title FROM file_meta WHERE file=?", (key,)).fetchone()
    if row and row[1] is not None:
        return row[0] or "", row[1] or ""
    provider = provider or detect_provider_from_path(key)
    project = row[0] if row and row[0] is not None else _project_from_key(key, provider)
    title = _native_title(key, provider)
    if not title:
        firsts = conn.execute(
            "SELECT f.text FROM turn_loc l JOIN session_fts f ON f.rowid = l.rid"
            " WHERE l.file=? AND f.role='user' ORDER BY l.msg_index LIMIT 5",
            (key,),
        ).fetchall()
        texts = [re.sub(r"\s+", " ", strip_ansi(t[0])).strip() for t in firsts]
        # skip throwaway openers ("hi", "hello", "continue") when something meatier follows
        meaty = [t for t in texts if len(t) >= 20]
        title = (meaty or texts or [""])[0][:160]
    if not INDEX_READ_ONLY or conn.execute(
            "SELECT 1 FROM sqlite_temp_master WHERE name='file_meta'").fetchone():
        try:
            conn.execute(
                "INSERT OR REPLACE INTO file_meta (file, provider, project, title) VALUES (?, ?, ?, ?)",
                (key, provider, project, title),
            )
        except sqlite3.OperationalError:
            pass  # index busy elsewhere; metadata is a cache, skip
    return project, title


def _native_title(key, provider):
    if provider in EXTRA_HARNESSES:
        fn = EXTRA_HARNESSES[provider]["title"]
        try:
            return ((fn(key) if fn else "") or "").strip()[:160]
        except Exception:
            return ""
    """Titles some harnesses store themselves (opencode, goose)."""
    if provider == "opencode" and "#" not in key:
        return (_opencode_legacy_info(key).get("title") or "").strip()[:160]
    if provider == "dsh":
        return _dsh_title(key)[:160]
    if provider == "grok":
        summary = _grok_summary(key)
        # a manual /rename lands in title; otherwise Grok writes generated_title (seen on 1.0.46)
        return (summary.get("title") or summary.get("generated_title") or summary.get("session_summary") or "").strip()[:160]
    if provider in ("pi", "omo") and "#" not in key:
        # pi/omo record a session name (/name, auto-title) as {"type":"session_info","name":…}
        name = ""
        try:
            with open(key, "r", encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    if '"session_info"' in line:
                        try:
                            name = json.loads(line).get("name") or name
                        except Exception:
                            pass
        except OSError:
            return ""
        return name.strip()[:160]
    if "#" not in key or provider not in ("opencode", "goose", "kilo"):
        return ""
    db, sid = key.split("#", 1)
    try:
        con = _ro_connect(db)
        if provider in ("opencode", "kilo"):
            row = con.execute("SELECT title FROM session WHERE id=?", (sid,)).fetchone()
        else:
            row = con.execute("SELECT name, description FROM sessions WHERE id=?", (sid,)).fetchone()
            row = (row[0] or row[1],) if row else None
        con.close()
    except sqlite3.Error:
        return ""
    title = (row[0] or "") if row else ""
    return "" if title.lower().startswith("new session") else title.strip()[:160]


def session_date(conn, key, fallback_mtime=None):
    row = conn.execute("SELECT mtime FROM file_state WHERE file=?", (key,)).fetchone()
    mtime = row[0] if row else fallback_mtime
    if not mtime:
        return "????-??-??"
    return datetime.fromtimestamp(mtime).strftime("%Y-%m-%d")


# ─────────────────────────────────────────────────────────────────────────────
# Query cooking — turn whatever an LLM (or human) typed into a VALID FTS5 query
# ─────────────────────────────────────────────────────────────────────────────

_FTS_SAFE_BAREWORD = re.compile(r"^\w+$", re.UNICODE)
_SMART_QUOTES = str.maketrans({"“": '"', "”": '"', "„": '"', "«": '"', "»": '"', "‘": "'", "’": "'", "`": "'"})
_OR_WORDS = {"OR", "or", "|", "||"}
_AND_WORDS = {"AND", "and", "&", "&&", "+"}


def _cook_term(token):
    """One whitespace-free chunk of user text → FTS5 term (or '' if nothing to match)."""
    word = token.strip("*")
    if not word or not any(ch.isalnum() for ch in word):
        return ""
    if _FTS_SAFE_BAREWORD.match(word):
        return f"{word}*"
    # Anything with punctuation becomes a literal FTS5 string; the tokenizer then
    # splits it the same way the indexed text was split (don't → don t, v0.1 → v0 1).
    escaped = word.replace('"', '""')
    return f'"{escaped}"*'


def _cook_phrase(inner):
    words = [w for w in re.split(r"\s+", inner.strip()) if w]
    if not words or not any(ch.isalnum() for ch in inner):
        return ""
    escaped = " ".join(words).replace('"', '""')
    return f'"{escaped}"*'


def _split_query(query):
    """Split into ("phrase", text) / ("word", text) / ("op", AND|OR|NOT) / ("paren", ( or )) items."""
    query = (query or "").translate(_SMART_QUOTES)
    items = []
    pos = 0
    for match in re.finditer(r'"([^"]*)"', query):
        items.extend(_split_words(query[pos : match.start()]))
        items.append(("phrase", match.group(1)))
        pos = match.end()
    items.extend(_split_words(query[pos:]))
    return items


def _split_words(chunk):
    items = []
    # a stray (unbalanced) double quote is just punctuation
    for raw in chunk.replace('"', " ").split():
        if raw in _OR_WORDS:
            items.append(("op", "OR"))
            continue
        if raw in ("AND", "&", "&&"):
            items.append(("op", "AND"))
            continue
        if raw == "NOT":
            items.append(("op", "NOT"))
            continue
        if raw in ("and", "+"):
            continue  # implicit AND already
        # peel grouping parens off the edges: "(auth" / "login)" but not "main()"
        lead = ""
        while raw.startswith("(") and not raw.startswith("()"):
            lead += "("
            raw = raw[1:]
        trail = ""
        while raw.endswith(")") and not raw.endswith("()"):
            trail += ")"
            raw = raw[:-1]
        for _ in lead:
            items.append(("paren", "("))
        if raw:
            items.append(("word", raw))
        for _ in trail:
            items.append(("paren", ")"))
    return items


def _assemble(items, force_or=False):
    """Validate operator/paren placement so FTS5 never sees a syntax error."""
    # drop parens unless they balance
    depth, ok = 0, True
    for kind, val in items:
        if kind == "paren":
            depth += 1 if val == "(" else -1
            if depth < 0:
                ok = False
                break
    if not ok or depth != 0:
        items = [it for it in items if it[0] != "paren"]
    out = []  # list of (kind, text) where kind in term/op/(/)
    for kind, val in items:
        if kind == "word":
            term = _cook_term(val)
            if term:
                out.append(("term", term))
        elif kind == "phrase":
            term = _cook_phrase(val)
            if term:
                out.append(("term", term))
        elif kind == "op":
            out.append(("op", "OR" if force_or else val))
        else:
            out.append((val, val))
    # remove empty groups "( )" and operators that don't sit between two operands
    cleaned = []
    for kind, val in out:
        if kind == "op":
            if not cleaned or cleaned[-1][0] in ("op", "("):
                continue
        if kind == ")":
            while cleaned and cleaned[-1][0] == "op":
                cleaned.pop()
            if cleaned and cleaned[-1][0] == "(":
                cleaned.pop()
                continue
        if kind in ("term", "(") and cleaned and cleaned[-1][0] in ("term", ")"):
            # adjacent operands: FTS5 allows implicit AND between plain terms but
            # rejects it next to a parenthesis, so always spell the operator out
            if force_or:
                cleaned.append(("op", "OR"))
            elif kind == "(" or cleaned[-1][0] == ")":
                cleaned.append(("op", "AND"))
        cleaned.append((kind, val))
    while cleaned and cleaned[-1][0] in ("op", "("):
        cleaned.pop()
    # a NOT directly after "(" or at the start has no left operand; FTS5 rejects it
    text = " ".join(val for _, val in cleaned)
    return text.strip()


def _comma_groups(query):
    """Split "a b, c; d" into ["a b", "c", "d"] — separators must end a word, quotes are respected."""
    query = (query or "").translate(_SMART_QUOTES)
    groups, buf, in_quote = [], [], False
    for i, ch in enumerate(query):
        if ch == '"':
            in_quote = not in_quote
        nxt = query[i + 1] if i + 1 < len(query) else " "
        if ch in ",;" and not in_quote and nxt.isspace():
            groups.append("".join(buf))
            buf = []
            continue
        buf.append(ch)
    groups.append("".join(buf))
    return [g for g in groups if any(c.isalnum() for c in g)]


def fts_prefix_query(query):
    """Cook a raw query into a valid FTS5 MATCH expression.

    Words are ANDed and prefix-matched; comma/semicolon-separated groups are
    alternatives ("drizzle, prisma, sequelize" → any of them, best matches first).
    """
    groups = _comma_groups(query)
    if len(groups) > 1:
        parts = [_assemble(_split_query(g)) for g in groups]
        parts = [f"({p})" if " " in p else p for p in parts if p]
        return " OR ".join(parts)
    return _assemble(_split_query(query))


def fts_any_query(query):
    """Same terms, joined with OR — the fallback when no single turn has them all."""
    items = [it for it in _split_query(query) if it[0] in ("word", "phrase")]
    return _assemble(items, force_or=True)


def fts_literal_query(query):
    """Last-resort query: every word a quoted literal, no operators at all."""
    words = re.findall(r"\w+", (query or "").translate(_SMART_QUOTES), re.UNICODE)
    return " ".join(f'"{w}"*' for w in words)


def fts_raw_query(query):
    """--no-prefix: the user's own FTS5 syntax, but still immune to syntax errors."""
    return query


def term_count(query):
    return sum(1 for kind, _ in _split_query(query) if kind in ("word", "phrase"))


def has_operators(query):
    if len(_comma_groups(query)) > 1:
        return True
    return any(kind in ("op", "paren") for kind, _ in _split_query(query))


# ─────────────────────────────────────────────────────────────────────────────
# Search
# ─────────────────────────────────────────────────────────────────────────────

# navcom finding its own earlier invocations is noise ("cmd: navcom --query foo").
_NAVCOM_CMD_RE = re.compile(r"(^|[;&|(]\s*|\s)(\S*/)?navcom(\.py)?(\s|$)")

SNIPPET_MAX_TOKENS = 64  # FTS5 hard limit


def _key_filter_clause(conn, keys):
    if keys is None:
        return "", []
    if len(keys) <= 400:
        return f" AND file IN ({','.join('?' * len(keys))})", list(keys)
    conn.execute("CREATE TEMP TABLE IF NOT EXISTS _navcom_keys (file TEXT PRIMARY KEY)")
    conn.execute("DELETE FROM _navcom_keys")
    conn.executemany("INSERT OR IGNORE INTO _navcom_keys (file) VALUES (?)", [(k,) for k in keys])
    return " AND file IN (SELECT file FROM _navcom_keys)", []


def run_match(conn, match, limit, providers=None, keys=None, snippet_tokens=32, role=None, include_tools=False):
    tokens = max(1, min(int(snippet_tokens), SNIPPET_MAX_TOKENS))
    where = "session_fts MATCH ?"
    # Only the turn text — otherwise words in project paths (file column) inflate hits.
    params = [f"text : ({match})"]
    if providers and set(providers) != set(ALL_PROVIDERS):
        where += f" AND provider IN ({','.join('?' * len(providers))})"
        params.extend(providers)
    if role:
        where += " AND role=?"
        params.append(role)
    elif not include_tools:
        where += " AND role != 'tool'"  # tool outputs only with --tool / --everything
    clause, key_params = _key_filter_clause(conn, keys)
    where += clause
    params.extend(key_params)
    params.append(limit)
    sql = (
        "SELECT ts, role, file, msg_index, provider, "
        f"snippet(session_fts, 0, '«', '»', '…', {tokens}), text, rank "
        f"FROM session_fts WHERE {where} ORDER BY rank LIMIT ?"
    )
    return [Hit(*row) for row in conn.execute(sql, params).fetchall()]


def _is_query_error(exc):
    msg = str(exc).lower()
    return "locked" not in msg and "readonly" not in msg and "disk" not in msg


_WORD_RE = re.compile(r"\w+", re.UNICODE)


def _query_terms(match):
    """Lower-cased search words from a cooked FTS5 expression (operators and syntax dropped)."""
    words = re.findall(r"\w+", match.lower(), re.UNICODE)
    return [w for w in words if w not in ("and", "or", "not", "near", "text")]


def make_snippet(text, terms, tokens=32):
    """FTS-style snippet: the `tokens`-word window with the most prefix matches, matches «marked»."""
    if not text:
        return ""
    words = list(_WORD_RE.finditer(text))
    if not words:
        return text[:200]
    term_tuple = tuple(terms)
    hits = [i for i, m in enumerate(words) if m.group(0).lower().startswith(term_tuple)] if term_tuple else []
    if not hits:
        start = 0
    else:
        start, best_count, j = max(0, hits[0] - tokens // 4), 0, 0
        for i, h in enumerate(hits):  # two pointers: windows starting a little before each hit
            s0 = max(0, h - tokens // 4)
            while j < len(hits) and hits[j] < s0 + tokens:
                j += 1
            if j - i > best_count:
                start, best_count = s0, j - i
    start = max(0, min(start, len(words) - tokens))  # fill the window instead of running short
    end = min(len(words), start + tokens)
    hit_set = set(hits)
    out, pos = [], (0 if start == 0 else words[start].start())
    for i in range(start, end):
        m = words[i]
        out.append(text[pos:m.start()])
        out.append(f"«{m.group(0)}»" if i in hit_set else m.group(0))
        pos = m.end()
    if end == len(words):
        out.append(text[pos:])
    snippet = "".join(out).strip()
    return ("…" if start > 0 else "") + snippet + ("…" if end < len(words) else "")


def _search_once(conn, match, providers, keys, per_harness, snippet_tokens, role, include_self, exclude_keys,
                 include_tools=False):
    """Top `per_harness` hits for EVERY harness (a busy harness can't crowd the others out).

    Two passes instead of one MATCH per harness (30 harnesses × a full match = seconds):
    (1) stream (rowid, provider, rank) for all matches once, keeping the best few per harness
    in a heap; (2) fetch snippets for just those rows."""
    fetch = per_harness * 2 + 8
    tokens = max(1, min(int(snippet_tokens), SNIPPET_MAX_TOKENS))
    match_expr = f"text : ({match})"
    where = "session_fts MATCH ?"
    params = [match_expr]
    if providers and set(providers) != set(ALL_PROVIDERS):
        where += f" AND provider IN ({','.join('?' * len(providers))})"
        params.extend(providers)
    if role:
        where += " AND role=?"
        params.append(role)
    elif not include_tools:
        where += " AND role != 'tool'"
    clause, key_params = _key_filter_clause(conn, keys)
    where += clause
    params.extend(key_params)
    # one streaming pass over every match; a tiny heap per harness keeps its best `fetch` rows
    import heapq
    best = {}
    for rid, prov, rnk in conn.execute(f"SELECT rowid, provider, rank FROM session_fts WHERE {where}", params):
        heap = best.setdefault(prov, [])
        if len(heap) < fetch:
            heapq.heappush(heap, (-rnk, rid))
        elif -rnk > heap[0][0]:
            heapq.heapreplace(heap, (-rnk, rid))
    rank_of = {rid: -neg for heap in best.values() for neg, rid in heap}
    ids = list(rank_of)
    terms = _query_terms(match)
    rows = []
    for start in range(0, len(ids), 500):
        chunk = ids[start:start + 500]
        # plain rowid lookups (no MATCH, no FTS snippet(): both re-scan every match → seconds)
        for rid, ts, role, file, msg_index, prov, text in conn.execute(
            "SELECT rowid, ts, role, file, msg_index, provider, text FROM session_fts "
            f"WHERE rowid IN ({','.join('?' * len(chunk))})", chunk,
        ):
            rows.append((ts, role, file, msg_index, prov, make_snippet(text, terms, tokens), text, rank_of[rid]))
    by_provider = {}
    for row in sorted(rows, key=lambda r: r[7]):
        by_provider.setdefault(row[4], []).append(Hit(*row))
    merged, excluded = [], 0
    for raw in by_provider.values():
        kept, skipped = _filter_hits(raw, per_harness, include_self, exclude_keys)
        merged.extend(kept)
        excluded += skipped
    merged.sort(key=lambda h: h.rank)
    return merged, excluded


def search_hits(conn, query, providers=None, keys=None, limit=20, snippet_tokens=32,
                no_prefix=False, role=None, any_terms=False, include_self=False, exclude_keys=None,
                include_tools=False):
    """Returns (hits, cooked_query, note). `limit` is per harness. Never raises on query syntax.

    Fallback chain — each step only if the previous one found nothing:
      raw (--no-prefix) → cooked → all-literal   (any form FTS5 rejects is skipped)
      "exact phrase"    → its words, all → its words, any
      several words     → any of them (BM25 ranks rare words first)
    """
    providers = list(providers or ALL_PROVIDERS)

    def attempt(match):
        try:
            return _search_once(conn, match, providers, keys, limit, snippet_tokens, role,
                                include_self, exclude_keys, include_tools)
        except sqlite3.OperationalError as exc:
            if not _is_query_error(exc):
                raise
            return None

    forms = []
    if no_prefix:
        forms.append(fts_raw_query(query))
    forms.append(fts_any_query(query) if any_terms else fts_prefix_query(query))
    forms.append(fts_literal_query(query))
    hits, excluded, cooked, note = [], 0, "", ""
    for form in forms:
        if not form:
            continue
        result = attempt(form)
        if result is not None:
            (hits, excluded), cooked = result, form
            break

    plain = query.translate(_SMART_QUOTES)
    if not hits and not any_terms and '"' in plain and not has_operators(query):
        loose = plain.replace('"', " ")
        steps = [(fts_prefix_query(loose), "no exact phrase match — showing turns with all of its words")]
        if term_count(loose) > 1:
            steps.append((fts_any_query(loose), "no exact phrase match — showing turns with ANY of its words (best first)"))
        for form, why in steps:
            result = attempt(form) if form else None
            if result and result[0]:
                (hits, excluded), cooked, note = result, form, why
                break

    if not hits and not any_terms and term_count(query) > 1 and not has_operators(query):
        form = fts_any_query(query)
        result = attempt(form) if form else None
        if result and result[0]:
            (hits, excluded), cooked = result, form
            note = "no single turn contains ALL of those words — showing turns with ANY of them (rare words rank first)"

    if excluded:
        extra = f"skipped {excluded} hit{'s' if excluded != 1 else ''} from this session (--include-self to show)"
        note = f"{note}; {extra}" if note else extra
    return hits, cooked, note


def _filter_hits(hits, limit, include_self, exclude_keys):
    """Drop navcom's own past invocations, the calling session and duplicate turns."""
    filtered, seen = [], set()
    excluded = 0
    for hit in hits:
        if not include_self and hit.role == "cmd" and _NAVCOM_CMD_RE.search(hit.text or ""):
            continue
        if exclude_keys and hit.file in exclude_keys:
            excluded += 1
            continue
        sig = (hit.role, re.sub(r"\s+", " ", (hit.text or "")[:400]))
        if sig in seen:
            continue
        seen.add(sig)
        filtered.append(hit)
        if len(filtered) >= limit:
            break
    return filtered, excluded


def window_ranges_for_hits(hits, window):
    ranges = {}
    for hit in hits:
        start = max(1, hit.msg_index - window)
        end = hit.msg_index + window
        ranges.setdefault(hit.file, []).append((start, end))
    merged = {}
    for file, spans in ranges.items():
        spans.sort()
        out = []
        for start, end in spans:
            if not out or start > out[-1][1] + 1:
                out.append([start, end])
            else:
                out[-1][1] = max(out[-1][1], end)
        merged[file] = [(a, b) for a, b in out]
    return merged


def fetch_window_rows(conn, file_path, ranges):
    rows = []
    for start, end in ranges:
        rows.extend(
            conn.execute(
                "SELECT l.msg_index, f.role, f.text FROM turn_loc l JOIN session_fts f ON f.rowid = l.rid"
                " WHERE l.file=? AND l.msg_index BETWEEN ? AND ? ORDER BY l.msg_index",
                (file_path, start, end),
            ).fetchall()
        )
    return rows


def max_msg_index(conn, file_path):
    row = conn.execute("SELECT max(msg_index) FROM turn_loc WHERE file=?", (file_path,)).fetchone()
    return row[0] or 0


_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07|\[[0-9;]{1,8}m(?=\S)")


def strip_ansi(text):
    """Drop terminal escape codes (and their orphaned "[2m" remains) from logged text."""
    return _ANSI_RE.sub("", text) if text else text


def format_turn(role, text, provider=None, msg_index=None):
    text = strip_ansi(text)
    label = clean_mod.label_for_role(role, provider or "") or "assistant"
    prefix = f"#{msg_index} " if msg_index is not None else ""
    if label == "cmd":
        return f"{STYLE.dim(prefix)}{STYLE.role('cmd:')} {clean_mod.format_cmd(text)}"
    return f"{STYLE.dim(prefix)}{STYLE.role(label + ':')}\n{text}\n"


def ensure_markdown_prompt(prompt_template):
    if not prompt_template:
        return DEFAULT_SUMMARY_TEMPLATE
    lowered = prompt_template.lower()
    if "markdown" in lowered or ".md" in lowered:
        return prompt_template
    return prompt_template.rstrip() + "\n\nOutput Markdown (.md).\n"


def build_prompt_from_text(prompt_text):
    return (
        "{{transcript}}\n\n"
        "========\n"
        f"{prompt_text.strip()}\n\n"
        "Output Markdown (.md).\n"
    )


def convert_dump_txt_to_md(dump_dir):
    if not dump_dir:
        return
    for path in dump_dir.glob("*.txt"):
        target = path.with_suffix(".md")
        try:
            path.replace(target)
        except OSError:
            continue
    final_summary = dump_dir / "final-summary.md"
    if final_summary.exists():
        final_summary.replace(dump_dir / "final.md")


def build_transcript_from_rows(rows, provider=None):
    parts = []
    for _, role, text in rows:
        label = clean_mod.label_for_role(role, provider or "") or "assistant"
        if label == "cmd":
            parts.append(f"cmd: {clean_mod.format_cmd(text)}")
        else:
            parts.append(f"{label}:\n{text}\n")
    return "\n".join(parts).strip()


def _scan_commits(conn, file_path):
    rows = conn.execute(
        "SELECT l.msg_index, f.text FROM turn_loc l JOIN session_fts f ON f.rowid = l.rid"
        " WHERE l.file=? AND f.role=? ORDER BY l.msg_index",
        (file_path, GIT_ROLE_DEFAULT),
    ).fetchall()
    found = []
    for msg_index, text in rows:
        hashes = fts_mod.find_commit_mentions(text, require_context=True, action_only=True)
        if hashes:
            found.append((msg_index, hashes, text))
    return found


def collect_git_summaries(conn, targets, limit=GIT_LIMIT_DEFAULT):
    if not shutil.which("git"):
        return []
    git_roots = fts_mod.collect_git_roots([Path.cwd(), Path.cwd().parent])
    if not git_roots:
        return []
    seen = set()
    summaries = []
    for target in targets:
        for _, hashes, _ in _scan_commits(conn, str(target)):
            for sha in hashes:
                if sha in seen:
                    continue
                for repo in git_roots:
                    if not fts_mod.git_commit_exists(repo, sha):
                        continue
                    if not fts_mod.git_commit_on_branch(repo, sha):
                        continue
                    summary = fts_mod.git_show_summary(repo, sha)
                    if summary:
                        summaries.append((repo, sha, summary))
                    seen.add(sha)
                    break
                if len(seen) >= limit:
                    return summaries
    return summaries


def format_git_section(git_summaries):
    if not git_summaries:
        return ""
    lines = ["git:"]
    for repo, sha, summary in git_summaries:
        lines.append(f"{repo} {sha}")
        lines.append(summary)
    return "\n".join(lines).strip()


CLAUDE_FAST = ["--tools", "", "--no-chrome", "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}', "--no-session-persistence"]

CLI_CONFIG = [
    # Pass 1: subscription (env key stripped)
    {"name": "claude-sonnet", "cmd": ["claude", "-p", "--model", "sonnet"] + CLAUDE_FAST, "key_var": "ANTHROPIC_API_KEY", "label": "claude/sonnet (subscription)"},
    {"name": "claude-default", "cmd": ["claude", "-p"] + CLAUDE_FAST, "key_var": "ANTHROPIC_API_KEY", "label": "claude (subscription)"},
    {"name": "gemini-flash", "cmd": ["gemini", "-m", "gemini-2.5-flash"], "key_var": "GOOGLE_API_KEY", "label": "gemini/2.5-flash (subscription)", "prompt_flag": "-p"},
    {"name": "codex", "cmd": ["codex", "exec"], "key_var": "OPENAI_API_KEY", "label": "codex (subscription)"},
]

# Cache file for engines that are known broken (expired auth, missing subscription, etc.)
# Auto-expires after 1 hour so we retry periodically
SKIP_CACHE_PATH = Path(os.environ.get("CODEX_HOME", os.path.expanduser("~/.codex"))) / "navcom-skip-cache"
SKIP_CACHE_TTL = 3600  # 1 hour


def _load_skip_cache():
    try:
        if SKIP_CACHE_PATH.exists():
            data = json.loads(SKIP_CACHE_PATH.read_text())
            now = datetime.now().timestamp()
            # Prune expired entries
            return {k: v for k, v in data.items() if now - v < SKIP_CACHE_TTL}
    except Exception:
        pass
    return {}


def _save_skip_cache(cache):
    try:
        SKIP_CACHE_PATH.write_text(json.dumps(cache))
    except Exception:
        pass


def _mark_engine_broken(name):
    cache = _load_skip_cache()
    cache[name] = datetime.now().timestamp()
    _save_skip_cache(cache)


def _is_engine_skipped(name):
    cache = _load_skip_cache()
    return name in cache


def _strip_conversation_artifacts(text):
    """Remove CLI conversation artifacts that confuse summarizers.
    Targets specific known patterns from Claude Code, Gemini CLI, and hook systems."""
    # Hook injections, system reminders, task notifications, function blocks, teammate messages
    artifact_tags = r"(?:[\w-]*(?:hook|reminder|caveat|notification|function[\w_]*|teammate-message)[\w-]*)"
    text = re.sub(rf"<{artifact_tags}[^>]*>.*?</{artifact_tags}>", "", text, flags=re.DOTALL)
    # Insight blocks (sonnet formatting artifact)
    text = re.sub(r"`★ Insight[^`]*`\n.*?`─+`", "", text, flags=re.DOTALL)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _gemini_strip_mcp():
    """Temporarily remove MCP servers from gemini settings. Returns backup path or None."""
    settings = Path.home() / ".gemini" / "settings.json"
    backup = Path.home() / ".gemini" / "settings.json.navcom-bak"
    if not settings.exists():
        return None
    try:
        data = json.loads(settings.read_text())
        if "mcpServers" not in data:
            return None
        # Backup original
        backup.write_text(settings.read_text())
        # Write stripped version
        data.pop("mcpServers")
        settings.write_text(json.dumps(data, indent=2))
        return str(backup)
    except Exception:
        return None


def _gemini_restore_mcp(backup_path):
    """Restore gemini settings from backup. Always called, even on exceptions."""
    if not backup_path:
        return
    backup = Path(backup_path)
    settings = Path.home() / ".gemini" / "settings.json"
    try:
        if backup.exists():
            settings.write_text(backup.read_text())
            backup.unlink()
    except Exception:
        pass


SUMMARY_TOTAL_TIMEOUT = float(os.environ.get("NAVCOM_SUMMARY_TIMEOUT") or 150)
SUMMARY_ENGINE_TIMEOUT = 90
_SUMMARY_DEADLINE = None


def _summary_time_left():
    global _SUMMARY_DEADLINE
    import time
    if _SUMMARY_DEADLINE is None:
        _SUMMARY_DEADLINE = time.monotonic() + SUMMARY_TOTAL_TIMEOUT
    return max(0.0, min(SUMMARY_ENGINE_TIMEOUT, _SUMMARY_DEADLINE - time.monotonic()))


def run_bounded(cmd, stdin_text, timeout, env=None):
    """Run a helper CLI with a hard timeout; on timeout kill its whole process group.

    Returns (returncode or None on timeout, stdout, stderr).
    """
    import signal
    try:
        proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, env=env, start_new_session=True,
        )
    except FileNotFoundError:
        return 127, "", f"{cmd[0]} not found"
    try:
        out, err = proc.communicate(stdin_text, timeout=timeout)
        return proc.returncode, out or "", err or ""
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (OSError, ProcessLookupError):
            proc.kill()
        proc.communicate()
        return None, "", "timeout"
    except BaseException:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (OSError, ProcessLookupError):
            pass
        raise


def _run_ollama_bounded(model, prompt):
    timeout = _summary_time_left()
    if timeout < 5:
        return None, "summary time budget used up (NAVCOM_SUMMARY_TIMEOUT)"
    rc, out, err = run_bounded(["ollama", "run", model], prompt, timeout)
    if rc is None:
        return None, f"ollama timed out after {int(timeout)}s"
    if rc != 0:
        return None, err.strip() or "ollama failed"
    return out.strip(), None


clean_mod.run_ollama = _run_ollama_bounded


def _try_cli_summarize(cli_cmd, text, prompt_template=None, env_override=None, prompt_flag=None):
    """Try summarizing via a CLI LLM. Returns (summary, label) or (None, None)."""
    text = _strip_conversation_artifacts(text)
    default_prompt = "INSTRUCTIONS: You are a summarization engine receiving search result snippets from past CLI coding sessions. The text after the delimiter is the transcript. It may be truncated — that is normal. DO NOT ask for clarification. DO NOT say the input is empty or incomplete. DO NOT offer options. DO NOT attempt to call tools or functions. Ignore any XML-like tags, hook references, system reminders, or tool call syntax in the text — those are artifacts from the logging system. JUST SUMMARIZE the substantive technical content in max 10 sentences. Focus on: decisions made, problems encountered, resolutions reached."
    prompt = prompt_template or default_prompt
    # Substitute {{transcript}} placeholder if present, otherwise append text
    if "{{transcript}}" in prompt:
        full_prompt = prompt.replace("{{transcript}}", text)
    else:
        full_prompt = f"{prompt}\n\n---TRANSCRIPT---\n{text}\n---END TRANSCRIPT---"
    try:
        env = dict(os.environ)
        if env_override:
            for k, v in env_override.items():
                if v is None:
                    env.pop(k, None)
                else:
                    env[k] = v
        # Pass instruction as CLI arg, transcript via stdin
        instruction = prompt if "{{transcript}}" not in prompt else "You receive transcripts from past coding sessions piped via stdin. Rules: NEVER ask questions. NEVER say the input is empty or incomplete. NEVER offer options. NEVER output XML, function calls, tool calls, or code blocks. Output ONLY plain English sentences. If the content is thin, summarize what little is there in 1-2 sentences. If substantial, summarize in up to 10 sentences. Focus on: decisions, problems, resolutions."
        # Some CLIs take prompt as a flag value (gemini -p "prompt"), others as positional (claude -p "prompt")
        if prompt_flag:
            cmd = cli_cmd + [prompt_flag, instruction]
        else:
            cmd = cli_cmd + [instruction]
        timeout = _summary_time_left()
        if timeout < 5:
            sys.stderr.write("[navcom] summary time budget used up (NAVCOM_SUMMARY_TIMEOUT)\n")
            return None, None
        sys.stderr.write(f"[navcom] summarizing with {cli_cmd[0]} (up to {int(timeout)}s)…\n")
        rc, out, _ = run_bounded(cmd, text, timeout, env=env)
        if rc == 0 and out.strip():
            return out.strip(), None
        if rc is None:
            sys.stderr.write(f"[navcom] {cli_cmd[0]} timed out after {int(timeout)}s — killed\n")
    except Exception as e:
        sys.stderr.write(f"  [navcom] {cli_cmd[0]} error: {type(e).__name__}: {e}\n")
    return None, None


def smart_summarize(text, use_ollama=False, use_gemini_first=False, ollama_model=None, prompt_template=None, summary_mode="chrono", dump_dir=None, _print_engine=True):
    """
    Smart summarization with transparent fallback chain:
    1. All CLIs with key STRIPPED (subscription/free tier)
    2. All CLIs with key PRESENT (API key / paid)
    3. Ollama (local)
    4. Raw output (no summarization)

    If --ollama is set, skip straight to ollama.
    Always prints which engine was used.
    """
    if not use_ollama:
        # Reorder if gemini requested first
        configs = list(CLI_CONFIG)
        if use_gemini_first:
            configs.sort(key=lambda c: 0 if "gemini" in c["name"] else 1)

        # Pass 1: try all CLIs with API key REMOVED (subscription auth)
        for cfg in configs:
            cli_bin = cfg["cmd"][0]
            if not shutil.which(cli_bin):
                continue
            if _is_engine_skipped(cfg["name"]):
                continue
            # Gemini hack: strip MCP servers to avoid 30s startup tax
            gemini_backup = None
            if cli_bin == "gemini":
                gemini_backup = _gemini_strip_mcp()
            try:
                summary, _ = _try_cli_summarize(
                    cfg["cmd"], text, prompt_template,
                    env_override={cfg["key_var"]: None},
                    prompt_flag=cfg.get("prompt_flag"),
                )
            finally:
                if gemini_backup:
                    _gemini_restore_mcp(gemini_backup)
            if summary:
                if _print_engine:
                    print(STYLE.dim(f"[NavCom summary via {cfg['label']}]"))
                return summary, None
            else:
                _mark_engine_broken(cfg["name"])

        # Pass 2: try all CLIs with API key PRESENT (paid)
        for cfg in configs:
            cli_bin = cfg["cmd"][0]
            if not shutil.which(cli_bin):
                continue
            api_name = cfg["name"] + "-apikey"
            if _is_engine_skipped(api_name):
                continue
            if not os.environ.get(cfg["key_var"]):
                continue
            gemini_backup = None
            if cli_bin == "gemini":
                gemini_backup = _gemini_strip_mcp()
            try:
                summary, _ = _try_cli_summarize(
                    cfg["cmd"], text, prompt_template,
                    prompt_flag=cfg.get("prompt_flag"),
                )
            finally:
                if gemini_backup:
                    _gemini_restore_mcp(gemini_backup)
            if summary:
                if _print_engine:
                    print(STYLE.dim(f"[NavCom summary via {cfg['label'].replace('subscription', 'api-key')}]"))
                return summary, None
            else:
                _mark_engine_broken(api_name)

    # Pass 3: Ollama (or forced via --ollama)
    if shutil.which("ollama"):
        model = ollama_model or SUMMARY_MODEL_DEFAULT
        if _print_engine:
            print(STYLE.dim(f"[NavCom summary via ollama/{model}]"))
        return clean_mod.summarize_transcript(
            text, model, mode=summary_mode,
            dump_dir=dump_dir, prompt_template=prompt_template,
        )

    # All failed
    print(STYLE.warn("[NavCom: no summarization engine available — showing raw output]"))
    return None, "no engine available"


def summarize_text(text, model, prompt_template=None, summary_mode="chrono", dump_dir=None, use_ollama=False, use_gemini_first=False, _print_engine=True):
    if use_ollama:
        if _print_engine:
            print(STYLE.dim(f"[NavCom summary via ollama/{model}]"))
        return clean_mod.summarize_transcript(
            text, model, mode=summary_mode,
            dump_dir=dump_dir, prompt_template=prompt_template,
        )
    return smart_summarize(
        text, use_ollama=False, use_gemini_first=use_gemini_first, ollama_model=model,
        prompt_template=prompt_template, summary_mode=summary_mode, dump_dir=dump_dir,
        _print_engine=_print_engine,
    )



# ─────────────────────────────────────────────────────────────────────────────
# Agent skill card — installed silently so every harness knows navcom exists
# ─────────────────────────────────────────────────────────────────────────────

SKILL_NAME = "navcom-session-recall"
SKILL_MARKER = "<!-- managed by navcom: updated automatically on upgrade; edit freely and it will be left alone -->"
SKILL_MD = """---
name: navcom-session-recall
description: Search every past AI coding session on this machine (Claude Code, Codex, Gemini CLI, Copilot CLI, Cline, Continue, Qwen Code, Kimi Code, Crush, pi, omo, opencode, goose, Kilo, DeepSeek dsh/Codewhale/Reasonix/Deep Code, Grok Build) with the local `navcom` CLI. Use when the user says "use navcom", asks to find an old conversation or thread, asks what was done/decided/tried before on a topic, wants to recover context after a compaction, or needs evidence from past sessions (commands run, errors seen, decisions) before continuing work.
---
""" + SKILL_MARKER + """

# NavCom session recall

`navcom` is a sub-second full-text search (SQLite FTS5 + BM25) over every coding-agent transcript
on this machine. Output is plain text grouped by session: date, harness, project dir, a **ref**, and
the matching turns (`#533 user: …«match»…`).

## The recipe

```bash
navcom topic words here          # 1. find  (no flag, no quotes needed)
navcom --open <ref>:<turn>       # 2. read the turns around one hit, full text
```

Step 1 prints a ready-to-run `--open` line. Do not grep the raw JSONL. `--open` is faster and
still works for sessions the harness has since deleted.

## Queries: type them as-is

- Punctuation is safe: `10.10.1.223`, `don't`, `PR #76`, `cerbos-wave-2`, `main()`, `file.py`,
  `user@x.com`. **Never strip punctuation by hand.**
- All words must appear in one turn, prefix-matched (`auth` matches `authentication`). If no turn
  has them all, navcom shows turns with ANY of them (rare words rank first) and prints a `note:`.
- `a OR b`, `a | b`, or a comma list `cognito, cerbos, fhir` means any of them. `NOT x` excludes.
- `"exact phrase"` falls back to loose words when the phrase isn't found.
- Lowercase `and` is ignored and lowercase `or` means OR.
- Awkward shell quoting? `navcom - <<'EOF'` … `EOF` reads the query from stdin.
- 2–4 distinctive words (ids, error strings, service or file names) beat long sentences.

## Narrow or widen

```bash
navcom deploy -n 50              # hits PER HARNESS (default 20). Every harness gets its own share
navcom deploy --claude           # also --codex --gemini --pi --omo --opencode --goose, or -p claude,pi
navcom deploy --here             # sessions started in this directory (or below)
navcom deploy --project syra     # working dir contains "syra"
navcom deploy --days 7           # or --since 2026-09-01 / --since 12h / --until …
navcom deploy --user             # only what the user typed;  --cmd = shell commands that were run
navcom "TypeError: x" --tool     # search TOOL OUTPUTS (command output, files read, errors, tests)
navcom deploy --newest           # newest sessions first
navcom goal --this-session       # only THIS conversation (recall after compaction)
navcom --sessions                # the 20 most recent sessions, with titles
```

- The conversation you run navcom from is skipped automatically (`--include-self` keeps it).
- `--this` = the harness you're running in. For the current directory use `--here`.

## Read more

```bash
navcom --open 7ec78a59:533       # 3 turns either side of #533 (--window-turns N for more)
navcom --open 7ec78a59:520-560   # a range of turns
navcom --open 7ec78a59 --user    # every user turn in that session
navcom deploy --context          # expand every hit in place
navcom deploy --json             # structured: sessions[] with ref, date, project, hits[]
navcom --resume 7ec78a59 --print # user wants to reopen it themselves? hand them this cd + resume command
navcom --restore 7ec78a59        # transcript deleted by its harness? put it back, then resume it
```

## Good to know

- Parallel runs are fine. Read-only sandboxes work (they search without refreshing the index).
- `--solo` / `--summary` hand the hits to another LLM CLI, so they're slow (≤150s). Usually
  better to read the hits and summarize them yourself.
- `navcom --help` is the full manual. `navcom --where` shows which harness logs exist.
- Humans: `navcom --menu` is a full-screen retro dashboard (retention, history, search). Agents should use
  the plain commands above.
- `navcom --skill` prints this card; `navcom --skill install` (re)installs it for every harness here.

## Evidence pattern

Report what navcom found (session ref, date, harness, project, turn numbers and quoted snippets)
separately from what you verified live now, and flag anything memory-derived as possibly stale.
"""


def _home_dir(env, default):
    return _env_path(env) or Path.home() / default


# Where each harness discovers USER-LEVEL Agent Skills (verified per harness: live runs, shipped
# bundles, source). Each entry: (skills dir, harness homes whose presence means "install here",
# who it serves). Shared dirs come first; per-harness dirs only where a harness reads neither
# ~/.claude/skills nor ~/.agents/skills. Deliberately NOT written (they'd only add duplicates —
# Codex 0.159 lists both ~/.codex/skills and ~/.agents/skills copies, Gemini warns on conflicts,
# Factory treats a second personal copy as invalid, OpenHands warns): ~/.codex/skills, ~/.factory/skills,
# ~/.openhands/skills, ~/.cline/skills, ~/.codewhale/skills, ~/.reasonix/skills, ~/.deepcode/skills,
# ~/.vibe/skills, ~/.augment/skills, ~/.cursor/skills. Aider has no global mechanism (only the
# user's own ~/.aider.conf.yml), so it is skipped.
def skill_target_table():
    home = Path.home()
    claude = _home_dir("CLAUDE_CONFIG_DIR", ".claude")
    codex = _home_dir("CODEX_HOME", ".codex")
    hermes = _home_dir("HERMES_HOME", ".hermes")
    table = [
        (claude / "skills", [claude], "Claude Code (opencode, Kilo, goose, Grok, Crush, Amp, Augment, Cursor also read it)"),
        (home / ".agents" / "skills",
         [home / ".agents", codex, home / ".gemini", home / ".pi", home / ".omo", opencode_data_root(),
          home / ".config" / "opencode", home / ".config" / "goose", home / ".dsh", home / ".grok",
          kilo_db_path().parent, home / ".config" / "kilo", home / ".kilocode", _home_dir("QWEN_HOME", ".qwen"),
          _home_dir("KIMI_CODE_HOME", ".kimi-code"), _home_dir("COPILOT_HOME", ".copilot"), home / ".config" / "crush",
          home / ".cline", home / ".codewhale", home / ".reasonix", home / ".deepcode", home / ".openhands",
          home / ".vibe", home / ".factory", home / ".cursor", home / ".config" / "amp", home / ".augment"],
         "Agent Skills standard: Codex, Gemini CLI, Copilot CLI, pi, omo, opencode, Kilo, goose, Qwen, Kimi, Crush, "
         "DeepSeek dsh, Grok Build, Cline, Codewhale, Reasonix, Deep Code, OpenHands, Mistral Vibe, Factory, "
         "Cursor, Amp, Augment, grok-dev"),
        (_home_dir("CONTINUE_GLOBAL_DIR", ".continue") / "skills", [_home_dir("CONTINUE_GLOBAL_DIR", ".continue")],
         "Continue (cn + IDE)"),
        (hermes / "skills", [hermes], "Hermes Agent"),
        (_home_dir("KIRO_HOME", ".kiro") / "skills", [_home_dir("KIRO_HOME", ".kiro")], "Kiro CLI"),
        (home / ".gemini" / "config" / "skills", [home / ".gemini" / "antigravity-cli", home / ".gemini" / "config"],
         "Antigravity CLI"),
    ]
    profiles = hermes / "profiles"
    if profiles.is_dir():  # every Hermes profile has its own skills dir
        for prof in sorted(p for p in profiles.iterdir() if p.is_dir()):
            table.append((prof / "skills", [prof], f"Hermes profile {prof.name}"))
    return table


def retired_skill_targets():
    """Folders older navcom versions wrote that now only create duplicates."""
    return [_home_dir("CODEX_HOME", ".codex") / "skills"]


def skill_targets():
    """Skill folders of the harnesses that are actually installed here (deduped, order kept)."""
    out = []
    for target, homes, _who in skill_target_table():
        if any(h.is_dir() for h in homes) and target not in out:
            out.append(target)
    return out


def _skill_state_path():
    return default_index_path().parent / "navcom-skills.json"


def install_skills(force=False, report=False):
    """Write/refresh the skill card in every harness's skill folder.

    Missing → written. Ours and unchanged since we wrote it → updated to this version.
    Edited by someone (hash differs) or not ours → left alone, unless force.
    """
    import hashlib
    digest = lambda text: hashlib.sha256(text.encode("utf-8")).hexdigest()
    want = digest(SKILL_MD)
    state_path = _skill_state_path()
    try:
        state = json.loads(state_path.read_text())
    except Exception:
        state = {}
    changed, done = False, []
    for root in retired_skill_targets():
        path = root / SKILL_NAME / "SKILL.md"
        try:
            current = path.read_text(encoding="utf-8") if path.exists() else None
        except OSError:
            current = None
        if current is None or SKILL_MARKER not in current:
            continue  # not ours (or already gone): leave it
        try:
            live = {(t / SKILL_NAME / "SKILL.md").resolve() for t in skill_targets()}
            if path.resolve() in live:
                continue  # symlinked onto a live target: deleting would remove the real card
        except OSError:
            continue
        if state.get(str(path)) not in (None, digest(current)) and not force:
            done.append((path, "left alone (edited by someone)"))
            continue
        try:
            path.unlink()
            path.parent.rmdir() if not any(path.parent.iterdir()) else None
            state.pop(str(path), None)
            changed = True
            done.append((path, "removed (duplicate: also read from ~/.agents/skills)"))
        except OSError:
            pass
    for root in skill_targets():
        path = root / SKILL_NAME / "SKILL.md"
        key = str(path)
        try:
            current = path.read_text(encoding="utf-8") if path.exists() else None
        except OSError:
            continue
        if current is not None and digest(current) == want:
            if state.get(key) != want:
                state[key], changed = want, True
            done.append((path, "up to date"))
            continue
        ours = current is None or (SKILL_MARKER in current and state.get(key) in (None, digest(current)))
        if not ours and not force:
            done.append((path, "left alone (edited by someone)"))
            continue
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(SKILL_MD, encoding="utf-8")
        except OSError as exc:
            done.append((path, f"not writable: {exc}"))
            continue
        state[key], changed = want, True
        done.append((path, "installed" if current is None else "updated"))
    if not changed:
        private_file(state_path)
    if changed:
        try:
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(json.dumps(state, indent=1))
            private_file(state_path)
        except OSError:
            pass
    if report:
        if not done:
            safe_print("navcom: no agent harness found to install the skill into")
        who = {str(t / SKILL_NAME / "SKILL.md"): w for t, _h, w in skill_target_table()}
        for path, what in done:
            safe_print(f"  {what:32s} {path}")
            if str(path) in who:
                safe_print(f"  {'':32s}   read by {who[str(path)]}")
        if done:
            safe_print(f"  {'':32s} Aider has no global skills folder: add the card with read: in ~/.aider.conf.yml")
    return done


SKILL_SUMMARY = ("Search every past AI coding session (Claude Code, Codex, Gemini, Copilot, Cline, Qwen, Kimi, DeepSeek, Grok, …) "
                 "with navcom: find, then --open")


def skill_tar_bytes():
    """The skill as a deterministic ustar stream: exactly one top-level <id>/ dir (Skillflag spec §9)."""
    import tarfile
    buf = io.BytesIO()
    data = SKILL_MD.encode("utf-8")
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.USTAR_FORMAT) as tar:
        for name, payload in ((f"{SKILL_NAME}/", None), (f"{SKILL_NAME}/SKILL.md", data)):
            info = tarfile.TarInfo(name.rstrip("/"))
            info.mtime, info.uid, info.gid, info.uname, info.gname = 0, 0, 0, "root", "root"
            if payload is None:
                info.type, info.mode = tarfile.DIRTYPE, 0o755
                tar.addfile(info)
            else:
                info.size, info.mode = len(payload), 0o644
                tar.addfile(info, io.BytesIO(payload))
    return buf.getvalue()


def cmd_skill(action, ids, as_json=False):
    """navcom --skill [show|list|export|install] [id]  — Skillflag-compatible (github.com/osolmaz/skillflag).

    Bare `navcom --skill` prints the stock SKILL.md. Unlike the Skillflag draft, `install`
    really installs (into every harness present) — full-service by design.
    """
    import hashlib
    action = (action or "show").lower()
    skill_id = ids[0] if ids else SKILL_NAME
    if action not in ("show", "list", "export", "install"):
        sys.stderr.write(f"navcom: --skill takes show (default), list, export or install — not {action!r}\n")
        return 2
    if action != "list" and skill_id != SKILL_NAME:
        sys.stderr.write(f"navcom: no skill {skill_id!r}; navcom ships one: {SKILL_NAME}\n")
        return 1
    if action == "show":
        sys.stdout.write(SKILL_MD)
    elif action == "list":
        if as_json:
            tar = skill_tar_bytes()
            safe_print(json.dumps({"skillflag_version": "0.1", "skills": [{
                "id": SKILL_NAME, "summary": SKILL_SUMMARY, "version": NAVCOM_VERSION, "files": 1,
                "digest": "sha256:" + hashlib.sha256(tar).hexdigest()}]}))
        else:
            safe_print(f"{SKILL_NAME}\t{SKILL_SUMMARY}")
    elif action == "export":
        sys.stdout.buffer.write(skill_tar_bytes())
        sys.stdout.flush()
    else:
        install_skills(force=True, report=True)
    return 0


def auto_install_skills():
    """Silent, cheap (a few stats + small reads), never fails the command."""
    if os.environ.get("NAVCOM_NO_SKILLS"):
        return
    try:
        install_skills()
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# Keep Claude Code from deleting your history
# ─────────────────────────────────────────────────────────────────────────────
# Claude Code deletes transcripts older than `cleanupPeriodDays` (default 30) on startup —
# hard-coded since the very first release, v0.2.9 (2025-02-24, launch day); a setting since
# v0.2.118 (2025-05-18). navcom sets
# it to 100 years when nobody has chosen a value. An explicit value is the owner's choice and
# is left alone. Never 0: Claude rejects it, and older versions read 0 as "save nothing".

CLAUDE_RETENTION_DAYS = 36500


def claude_settings_path():
    return (_env_path("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "settings.json"


def claude_retention_status():
    """(days or None, how) — what Claude Code will do with old transcripts."""
    path = claude_settings_path()
    if not path.parent.is_dir():
        return None, "Claude Code not installed"
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except Exception:
        return None, f"{path} is not plain JSON — not touched"
    if not isinstance(data, dict):
        return None, f"{path} is not a JSON object — not touched"
    days = data.get("cleanupPeriodDays")
    if days is None:
        return 30, "default — Claude deletes transcripts after 30 days"
    return days, "set in " + str(path)


def ensure_claude_retention():
    """Set cleanupPeriodDays=36500 when unset. Atomic write, one backup, never touches odd files."""
    if os.environ.get("NAVCOM_NO_RETENTION_FIX"):
        return False
    path = claude_settings_path()
    if not path.parent.is_dir():
        return False
    try:
        raw = path.read_text(encoding="utf-8") if path.exists() else ""
        data = json.loads(raw) if raw.strip() else {}
    except Exception:
        return False  # JSONC / broken file: never risk corrupting Claude's settings
    if not isinstance(data, dict) or "cleanupPeriodDays" in data:
        return False
    data["cleanupPeriodDays"] = CLAUDE_RETENTION_DAYS
    try:
        if raw:
            backup = path.with_name(path.name + ".navcom-backup")
            if not backup.exists():
                backup.write_text(raw, encoding="utf-8")
        tmp = path.with_name(path.name + f".navcom-tmp-{os.getpid()}")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        if path.exists():
            os.chmod(tmp, path.stat().st_mode & 0o777)
        os.replace(tmp, path)
    except OSError:
        return False
    return True


def private_file(path):
    """navcom's index holds the text of transcripts Claude keeps owner-only (0600); match that."""
    for candidate in (Path(str(path)), Path(f"{path}-wal"), Path(f"{path}-shm")):
        try:
            if candidate.exists() and candidate.stat().st_mode & 0o077:
                os.chmod(candidate, 0o600)
        except OSError:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# Raw archive — a complete compressed copy of every transcript, restorable
# ─────────────────────────────────────────────────────────────────────────────
# ~/.navcom/archive/<harness>/<path>.jsonl.gz. Appended JSONL is archived incrementally as
# extra gzip members (gzip readers concatenate them), so a growing session is never re-read
# whole. Default harness: claude (the one that deletes). NAVCOM_ARCHIVE=all|off|claude,pi,…

ARCHIVE_BUDGET_SECONDS = 1.0
ARCHIVABLE = ("claude", "codex", "gemini", "pi", "omo", "goose", "dsh", "grok")
ARCHIVE_DEFAULT = "claude,gemini"  # the harnesses that delete their own history


def archive_root():
    return _env_path("NAVCOM_ARCHIVE_DIR") or Path.home() / ".navcom" / "archive"


def archive_providers():
    raw = (os.environ.get("NAVCOM_ARCHIVE") or ARCHIVE_DEFAULT).strip().lower()
    if raw in ("off", "0", "no", "none", "false"):
        return []
    archivable = list(ARCHIVABLE) + [hid for hid, h in EXTRA_HARNESSES.items() if h["archivable"]]
    if raw == "all":
        return archivable
    return [p for p in re.split(r"[,\s]+", raw) if p in archivable]


def _provider_root(provider):
    return {
        "claude": fts_mod.claude_projects_root(), "codex": fts_mod.codex_sessions_root(),
        "gemini": fts_mod.gemini_tmp_root(), "pi": pi_sessions_root(), "omo": omo_sessions_root(),
        "dsh": dsh_sessions_root(), "grok": grok_sessions_root(),
        **{hid: (h["roots"]() or [None])[0] for hid, h in EXTRA_HARNESSES.items() if h["roots"]},
    }.get(provider)


def archive_path_for(key, provider):
    path = Path(key)
    root = _provider_root(provider)
    try:
        rel = path.relative_to(root) if root else Path(path.name)
    except ValueError:
        rel = Path(path.name)
    return archive_root() / provider / (str(rel) + ".gz")


def _ensure_private_dir(path):
    """mkdir -p, and make every directory from the archive root down owner-only."""
    root = archive_root()
    path.mkdir(parents=True, exist_ok=True)
    dirs = [path] + [p for p in path.parents if p == root or root in p.parents]
    if root == Path.home() / ".navcom" / "archive":
        dirs.append(root.parent)
    for d in dirs:
        try:
            os.chmod(d, 0o700)
        except OSError:
            pass


def _ensure_archive_table(conn):
    conn.execute(
        "CREATE TABLE IF NOT EXISTS archive_state (file TEXT PRIMARY KEY, provider TEXT, bytes INTEGER,"
        " head TEXT, mtime REAL, path TEXT)"
    )


def archive_log(conn, log, state=None):
    """Bring one transcript's archive copy up to date. Returns bytes compressed."""
    import gzip
    import hashlib
    key, mtime, size, provider = log
    if "#" in key or not Path(key).is_file():
        return 0
    if state and state[0] == size:
        return 0
    with open(key, "rb") as handle:
        # fingerprint only bytes already archived, so a pure append keeps the same fingerprint
        prefix = min(4096, state[0]) if state else min(4096, size)
        head = hashlib.sha256(handle.read(prefix)).hexdigest()
        target = archive_path_for(key, provider)
        _ensure_private_dir(target.parent)
        appending = bool(state and size > state[0] and state[1] == head and target.exists())
        if not appending:
            handle.seek(0)
            head = hashlib.sha256(handle.read(min(4096, size))).hexdigest()
        if appending:
            handle.seek(state[0])
            chunk = handle.read(size - state[0])
            with open(target, "ab") as out:
                out.write(gzip.compress(chunk, 6))
            written = len(chunk)
        else:
            handle.seek(0)
            tmp = target.with_name(target.name + f".tmp-{os.getpid()}")
            with gzip.open(tmp, "wb", compresslevel=6) as out:
                shutil.copyfileobj(handle, out, 1 << 20)
            os.replace(tmp, target)
            written = size
    if appending and state[0] < 4096:
        with open(key, "rb") as handle:
            head = hashlib.sha256(handle.read(min(4096, size))).hexdigest()
    os.chmod(target, 0o600)
    conn.execute(
        "INSERT OR REPLACE INTO archive_state (file, provider, bytes, head, mtime, path) VALUES (?, ?, ?, ?, ?, ?)",
        (key, provider, size, head, mtime, str(target)),
    )
    return written


def archive_logs(conn, logs, budget=ARCHIVE_BUDGET_SECONDS):
    """Archive new/grown transcripts — oldest first (closest to a harness's deletion sweep)."""
    import time
    wanted = set(archive_providers())
    if not wanted or INDEX_READ_ONLY:
        return 0, 0
    _ensure_archive_table(conn)
    states = {row[0]: (row[1], row[2]) for row in conn.execute("SELECT file, bytes, head FROM archive_state")}
    deadline = None if budget is None else time.monotonic() + budget
    files = total = 0
    for log in sorted((l for l in logs if l[3] in wanted and "#" not in l[0]), key=lambda l: l[1]):
        state = states.get(log[0])
        if state and state[0] == log[2]:
            continue
        if deadline is not None and time.monotonic() > deadline:
            break
        try:
            written = archive_log(conn, log, state)
        except OSError as exc:
            sys.stderr.write(f"[navcom] archive skipped {log[0]}: {exc}\n")
            continue
        if written:
            files += 1
            total += written
            conn.commit()
    return files, total


def _gunzip_to(src, dest):
    import gzip
    tmp = dest.with_name(dest.name + f".navcom-restore-{os.getpid()}")
    with gzip.open(src, "rb") as inp, open(tmp, "wb") as out:
        shutil.copyfileobj(inp, out, 1 << 20)
    os.chmod(tmp, 0o600)
    os.replace(tmp, dest)


def cmd_restore(conn, ref, providers):
    """Put archived transcripts back where their harness looks, so they can be resumed."""
    _ensure_archive_table(conn)
    if ref.strip().lower() in ("all", "missing"):
        rows = conn.execute("SELECT file, provider, bytes, mtime, path FROM archive_state").fetchall()
        rows = [r for r in rows if not Path(r[0]).exists()]
        if not rows:
            safe_print("navcom: every archived transcript is still on disk — nothing to restore.")
            return 0
    else:
        key, _ = resolve_ref(conn, ref, providers)
        row = conn.execute("SELECT file, provider, bytes, mtime, path FROM archive_state WHERE file=?",
                           (key,)).fetchone() if key else None
        if not row:  # archived but never indexed: match the ref against the archive itself
            want = ref.strip()
            for cand in conn.execute("SELECT file, provider, bytes, mtime, path FROM archive_state ORDER BY mtime DESC"):
                sref = session_ref(cand[0])
                if sref.startswith(want) or sref.endswith(want) or Path(cand[0]).name == want:
                    row = cand
                    break
        if not row:
            safe_print(f"navcom: {ref!r} is not in the raw archive (it only covers sessions navcom saw after "
                       f"archiving started). Its text may still be readable: navcom --open {ref}")
            return 1
        rows = [row]
    restored = 0
    for file, provider, size, mtime, src in rows:
        dest = Path(file)
        if dest.exists() and dest.stat().st_size >= size:
            safe_print(f"still on disk  {dest}")
            continue
        if not Path(src).exists():
            safe_print(f"archive copy missing  {src}")
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        _gunzip_to(Path(src), dest)
        if mtime:
            os.utime(dest, (mtime, mtime))
        restored += 1
        hint = ""
        if provider == "claude":
            project = _project_from_key(file, "claude")
            cwd = decode_encoded_dir(project) if project.startswith("-") else project
            hint = f"   →  cd {cwd or '<project dir>'} && claude --resume {session_ref(file)}"
        safe_print(f"restored  {dest}{hint}")
    days, _ = claude_retention_status()
    if restored and days is not None and days < 3650:
        safe_print(STYLE.warn(f"note: Claude Code deletes transcripts after {days} days here — "
                              "restored ones may be swept again. Remove that setting or raise it."))
    return 0


def archive_summary(conn):
    try:
        _ensure_archive_table(conn)
        rows = conn.execute("SELECT count(*), coalesce(sum(bytes), 0) FROM archive_state").fetchone()
    except sqlite3.Error:
        return ""
    gone = sum(1 for (f,) in conn.execute("SELECT file FROM archive_state") if not Path(f).exists())
    size = 0
    root = archive_root()
    if root.exists():
        size = sum(p.stat().st_size for p in root.rglob("*.gz"))
    which = ",".join(archive_providers()) or "off"
    return (f"{rows[0]} transcripts ({rows[1] / 1e6:.0f} MB raw → {size / 1e6:.0f} MB gz; {gone} restorable "
            f"after deletion) [{which}]  {root}")


# ─────────────────────────────────────────────────────────────────────────────
# Daily maintenance job — so nothing depends on someone remembering to run navcom
# ─────────────────────────────────────────────────────────────────────────────

DAILY_LABEL = "io.navcom.maintain"


def _navcom_executable():
    exe = shutil.which("navcom")
    return str(Path(exe).resolve()) if exe else None


def _daily_paths():
    home = Path.home()
    return {
        "darwin": home / "Library" / "LaunchAgents" / f"{DAILY_LABEL}.plist",
        "service": (_env_path("XDG_CONFIG_HOME") or home / ".config") / "systemd" / "user" / "navcom-maintain.service",
        "timer": (_env_path("XDG_CONFIG_HOME") or home / ".config") / "systemd" / "user" / "navcom-maintain.timer",
        "log": home / ".navcom" / "maintain.log",
        "off": home / ".navcom" / "daily-off",
    }


def _daily_env():
    keep = ("CODEX_HOME", "CLAUDE_CONFIG_DIR", "NAVCOM_INDEX", "NAVCOM_ARCHIVE", "NAVCOM_ARCHIVE_DIR",
            "XDG_DATA_HOME", "PI_CODING_AGENT_DIR", "OMO_CODING_AGENT_DIR", "GOOSE_PATH_ROOT")
    env = {k: os.environ[k] for k in keep if os.environ.get(k)}
    env["PATH"] = os.pathsep.join(dict.fromkeys(
        [str(Path(_navcom_executable() or sys.executable).parent), "/opt/homebrew/bin", "/usr/local/bin",
         "/usr/bin", "/bin"]))
    return env


def _launchd_plist(exe, log):
    import plistlib
    return plistlib.dumps({
        "Label": DAILY_LABEL,
        "ProgramArguments": [exe, "--maintain"],
        "StartCalendarInterval": {"Hour": 12, "Minute": 17},  # missed runs fire on wake
        "StandardOutPath": str(log), "StandardErrorPath": str(log),
        "EnvironmentVariables": _daily_env(),
        "LowPriorityIO": True, "Nice": 10, "ProcessType": "Background",
    })


def _run_quiet(cmd):
    if os.environ.get("NAVCOM_DRY_SCHEDULER"):
        return 0
    try:
        return subprocess.run(cmd, capture_output=True, timeout=20).returncode
    except Exception:
        return 1


def install_daily_job(force=False):
    """Install (or refresh) the daily `navcom --maintain` job. Returns a status string."""
    exe = _navcom_executable()
    if not exe:
        return "navcom isn't on PATH (pipx install navcom) — no daily job"
    paths = _daily_paths()
    if force and paths["off"].exists():
        paths["off"].unlink()
    paths["log"].parent.mkdir(parents=True, exist_ok=True)
    os.chmod(paths["log"].parent, 0o700)
    if sys.platform == "darwin":
        content = _launchd_plist(exe, paths["log"])
        plist = paths["darwin"]
        if plist.exists() and plist.read_bytes() == content and not force:
            return f"daily job installed  {plist}"
        plist.parent.mkdir(parents=True, exist_ok=True)
        plist.write_bytes(content)
        domain = f"gui/{os.getuid()}"
        _run_quiet(["launchctl", "bootout", f"{domain}/{DAILY_LABEL}"])
        _run_quiet(["launchctl", "bootstrap", domain, str(plist)])
        return f"daily job installed  {plist}"
    if sys.platform.startswith("linux") and (shutil.which("systemctl") or os.environ.get("NAVCOM_DRY_SCHEDULER")):
        service = (f"[Unit]\nDescription=navcom daily maintenance\n\n[Service]\nType=oneshot\n"
                   f"ExecStart={exe} --maintain\nNice=10\n"
                   + "".join(f'Environment="{k}={v}"\n' for k, v in _daily_env().items()))
        timer = ("[Unit]\nDescription=navcom daily maintenance\n\n[Timer]\nOnCalendar=daily\n"
                 "Persistent=true\nRandomizedDelaySec=900\n\n[Install]\nWantedBy=timers.target\n")
        unchanged = (paths["service"].exists() and paths["service"].read_text() == service
                     and paths["timer"].exists() and paths["timer"].read_text() == timer)
        if unchanged and not force:
            return f"daily job installed  {paths['timer']}"
        paths["service"].parent.mkdir(parents=True, exist_ok=True)
        paths["service"].write_text(service)
        paths["timer"].write_text(timer)
        _run_quiet(["systemctl", "--user", "daemon-reload"])
        _run_quiet(["systemctl", "--user", "enable", "--now", "navcom-maintain.timer"])
        return f"daily job installed  {paths['timer']}"
    return f"no daily job on {sys.platform} (run `navcom --maintain` from your scheduler)"


def remove_daily_job():
    paths = _daily_paths()
    removed = []
    paths["off"].parent.mkdir(parents=True, exist_ok=True)
    paths["off"].write_text("navcom --daily off; `navcom --daily on` re-enables\n")
    if paths["darwin"].exists():
        _run_quiet(["launchctl", "bootout", f"gui/{os.getuid()}/{DAILY_LABEL}"])
        paths["darwin"].unlink()
        removed.append(str(paths["darwin"]))
    for k in ("timer", "service"):
        if paths[k].exists():
            if k == "timer":
                _run_quiet(["systemctl", "--user", "disable", "--now", "navcom-maintain.timer"])
            paths[k].unlink()
            removed.append(str(paths[k]))
    return removed


def daily_job_status():
    paths = _daily_paths()
    for k in ("darwin", "timer"):
        if paths[k].exists():
            log = paths["log"]
            last = (datetime.fromtimestamp(log.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
                    if log.exists() else "not yet")
            return f"daily `navcom --maintain` scheduled ({paths[k]}); last run: {last}"
    return "no daily job (navcom --daily on)"


def auto_install_daily_job():
    if os.environ.get("NAVCOM_NO_DAILY") or _daily_paths()["off"].exists():
        return
    try:
        install_daily_job()
    except Exception:
        pass


def cmd_maintain(conn, force=False):
    """Everything, with no time budgets: the daily job's entry point."""
    import time
    start = time.monotonic()
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logs = list_logs(ALL_PROVIDERS)
    changed = _index_logs(conn, logs, force=force, progress=force, upgrade=False)
    upgraded = upgrade_stale_parses(conn, logs, budget=None)
    files, raw = archive_logs(conn, logs, budget=None)
    safe_print(f"{stamp} navcom {NAVCOM_VERSION} maintain: {len(logs)} sessions seen, {changed} indexed, "
               f"{upgraded} re-parsed, {files} archived ({raw / 1e6:.1f} MB) in {time.monotonic() - start:.0f}s")
    return 0


# >>> registered harnesses (generated by harness/integrate.py — edit the parsers, not this block)
from pathlib import Path  # noqa: E402 (harness parsers)
from urllib.parse import unquote, urlparse  # noqa: E402 (harness parsers)
import base64  # noqa: E402 (harness parsers)
import hashlib  # noqa: E402 (harness parsers)
import html  # noqa: E402 (harness parsers)
import json  # noqa: E402 (harness parsers)
import os  # noqa: E402 (harness parsers)
import re  # noqa: E402 (harness parsers)
import sqlite3  # noqa: E402 (harness parsers)
import struct  # noqa: E402 (harness parsers)
import sys  # noqa: E402 (harness parsers)
import tempfile  # noqa: E402 (harness parsers)
import time  # noqa: E402 (harness parsers)
import uuid  # noqa: E402 (harness parsers)


# ── Qwen Code (qwen) ─────────────────────────────────────────────────────────
# Qwen Code (npm @qwen-code/qwen-code) transcripts for navcom.
#
# $QWEN_RUNTIME_DIR | $QWEN_HOME | ~/.qwen
#   projects/<cwd with [^a-zA-Z0-9] -> '-'>/chats/<sessionId>.jsonl            main sessions
#   projects/<sanitized cwd>/subagents/<sessionId>/agent-<agentId>.jsonl       subagent sidechains
#
# One JSON record per line: {uuid, parentUuid, sessionId, type: user|assistant|tool_result|system,
# subtype?, provenance?, cwd, message: {role, parts[]}} with Gemini-style parts
# (text / thought / functionCall{id,name,args} / functionResponse{id,name,response}).
# /rewind leaves dead branches in the file; Qwen rebuilds a conversation by walking parentUuid back
# from the last conversation record, so we index exactly that chain.

_qwen_HOOK_CONTEXT_OPEN = "<qwen:user-prompt-submit-context>"
_qwen_REFERENCED_FILES = "\n--- Content from referenced files ---"
_qwen_NON_CONVERSATION = {"session_sources_snapshot", "session_artifact_event", "session_artifact_snapshot",
                     "managed_session_header_v1", "managed_session_event_v1", "managed_session_commit_v1"}


def qwen_roots():
    roots = []
    for root in (_env_path("QWEN_RUNTIME_DIR"), _env_path("QWEN_HOME"), Path.home() / ".qwen"):
        if root and root / "projects" not in roots:
            roots.append(root / "projects")
    return roots


def qwen_list():
    paths = []
    for root in qwen_roots():
        if root.is_dir():
            paths += list(root.glob("*/chats/*.jsonl")) + list(root.glob("*/subagents/*/agent-*.jsonl"))
    return _file_logs(sorted(set(paths)), "qwen")


def _qwen_records(key):
    out = []
    try:
        with open(key, "r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                if isinstance(obj, dict) and obj.get("uuid"):
                    out.append(obj)
    except OSError:
        pass
    return out


def _qwen_live_chain(records):
    """Records on the surviving branch, oldest first (fragments sharing a uuid are merged)."""
    by_uuid = {}
    for rec in records:
        first = by_uuid.get(rec["uuid"])
        if first is None:
            by_uuid[rec["uuid"]] = dict(rec)
        elif isinstance(rec.get("message"), dict):
            msg = dict(first.get("message") or {"role": rec["message"].get("role")})
            msg["parts"] = list(msg.get("parts") or []) + list(rec["message"].get("parts") or [])
            first["message"] = msg
    leaf = next((r["uuid"] for r in reversed(records)
                 if not (r.get("type") == "system" and r.get("subtype") in _qwen_NON_CONVERSATION)), None)
    chain, seen = [], set()
    while leaf and leaf not in seen and leaf in by_uuid:
        seen.add(leaf)
        chain.append(by_uuid[leaf])
        leaf = by_uuid[leaf].get("parentUuid")
    return chain[::-1]


def _qwen_user_text(rec):
    payload = rec.get("systemPayload") if isinstance(rec.get("systemPayload"), dict) else {}
    if isinstance(payload.get("displayText"), str) and payload["displayText"].strip():
        return payload["displayText"]
    texts = [p["text"] for p in (rec.get("message") or {}).get("parts") or []
             if isinstance(p, dict) and isinstance(p.get("text"), str) and not p.get("thought")]
    texts = [t for t in texts if not t.strip().startswith(_qwen_HOOK_CONTEXT_OPEN)]
    return "\n".join(texts).split(_qwen_REFERENCED_FILES, 1)[0]


def qwen_iter(key):
    calls = {}
    for rec in _qwen_live_chain(_qwen_records(key)):
        kind, parts = rec.get("type"), (rec.get("message") or {}).get("parts") or []
        if kind == "user":
            typed = rec.get("provenance", "real_user") == "real_user" and rec.get("subtype") in (None, "mid_turn_user_message")
            if typed and not rec.get("isSidechain"):  # sidechain prompts are written by the parent agent
                text = _qwen_user_text(rec)
                if text.strip():
                    yield "user", text
        elif kind == "assistant":
            text = []
            for part in parts:
                if not isinstance(part, dict) or part.get("thought"):
                    continue
                if isinstance(part.get("text"), str):
                    text.append(part["text"])
                call = part.get("functionCall")
                if isinstance(call, dict):
                    if text and "".join(text).strip():
                        yield "assistant", "".join(text)
                    text = []
                    args = call.get("args")
                    calls[call.get("id")] = _call_label(call.get("name"), args)
                    cmd = _shell_cmd(call.get("name"), args)
                    if cmd:
                        yield "cmd", cmd
            if "".join(text).strip():
                yield "assistant", "".join(text)
        elif kind == "tool_result":
            for part in parts:
                resp = part.get("functionResponse") if isinstance(part, dict) else None
                if not isinstance(resp, dict):
                    continue
                body = resp.get("response")
                if isinstance(body, dict):
                    output = body.get("output") if body.get("output") is not None else body.get("error")
                    if output is None:
                        output = body
                    elif body.get("error") and body.get("output") is not None:
                        output = f"error\n{body['error']}\n{output}"
                else:
                    output = body
                label = calls.get(resp.get("id")) or resp.get("name") or "tool"
                turn = tool_turn(label, output)
                if turn:
                    yield turn


def qwen_project(key):
    for rec in _qwen_records(key)[:50]:
        if isinstance(rec.get("cwd"), str) and rec["cwd"]:
            return rec["cwd"]
    return ""


def qwen_title(key):
    title = ""
    for rec in _qwen_records(key):
        if rec.get("type") == "system" and rec.get("subtype") == "custom_title":
            title = ((rec.get("systemPayload") or {}).get("customTitle") or title)
    if not title and "/subagents/" in str(key):
        try:
            title = json.loads(Path(str(key)[:-len(".jsonl")] + ".meta.json").read_text()).get("description") or ""
        except Exception:
            pass
    return title


def qwen_retention():
    home = _env_path("QWEN_HOME") or Path.home() / ".qwen"
    return {
        "settings_path": str(home / "settings.json"),
        "key_path": "general.cleanupPeriodDays",
        "never_delete_value": 36500,
        "default_days": 30,
        "note": "Qwen Code's daily housekeeping deletes subagent transcripts (projects/*/subagents/<session>/), "
                "/rewind file-history backups and debug logs older than general.cleanupPeriodDays (default 30). "
                "Main chats/*.jsonl are never auto-deleted. There is no 'off' value (0 means ~1 hour), "
                "so set a very large number of days.",
    }


def _qwen_sanitize(cwd):
    return "".join(c if c.isalnum() and c.isascii() else "-" for c in cwd)


# ── Kimi Code (kimi) ─────────────────────────────────────────────────────────
# Kimi Code (npm @moonshot-ai/kimi-code, v2 engine) transcripts for navcom, plus legacy Kimi CLI.
#
# $KIMI_CODE_HOME | ~/.kimi-code
#   sessions/wd_<slug>_<sha256[:12]>/session_<uuid>/state.json             {cwd, title, agents{…}}
#   sessions/wd_…/session_<uuid>/agents/main/wire.jsonl                     main agent
#   sessions/wd_…/session_<uuid>/agents/agent-<n>/wire.jsonl                subagents (Agent tool)
# wire.jsonl is an append-only event log. The model context is rebuilt from:
#   context.append_message      {message: {role, content[], toolCalls[], toolCallId?, origin{kind}}}
#                               origin.kind "user" = typed; "injection"/"system_trigger"/… = not typed;
#                               "shell_command" = a `!cmd` the user ran (phase input|output)
#   context.append_loop_event   {event: content.part{part{type:text|think}} | tool.call{toolCallId,name,args}
#                                | tool.result{toolCallId, result{output, isError}}}
# `agent.message.appended` events duplicate the same content for live UIs and are ignored.
#
# Legacy Kimi CLI ($KIMI_SHARE_DIR | ~/.kimi): sessions/<md5(workdir)>/<uuid>/context*.jsonl (or a flat
# sessions/<md5>/<uuid>.jsonl): OpenAI-style rows {role: user|assistant|tool|_system_prompt|_checkpoint|_usage,
# content, tool_calls[{id, function{name, arguments}}], tool_call_id}; workdirs in kimi.json work_dirs[].path.

def _kimi_kimi_home():
    return _env_path("KIMI_CODE_HOME") or Path.home() / ".kimi-code"


def _kimi_legacy_home():
    return _env_path("KIMI_SHARE_DIR") or Path.home() / ".kimi"


def kimi_roots():
    return [_kimi_kimi_home() / "sessions", _kimi_legacy_home() / "sessions"]


def kimi_list():
    current, legacy = kimi_roots()
    paths = list(current.glob("*/*/agents/*/wire.jsonl")) if current.is_dir() else []
    if legacy.is_dir():
        paths += [p for p in legacy.glob("*/*/context*.jsonl") if re.fullmatch(r"context(_\d+)?\.jsonl", p.name)]
        paths += [p for p in legacy.glob("*/*.jsonl") if re.fullmatch(r"[0-9a-f]{32}", p.parent.name)]
    return _file_logs(sorted(set(paths)), "kimi")


def _kimi_lines(key):
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


def _kimi_parts_text(content, kinds=("text",)):
    if isinstance(content, str):
        return content
    out = []
    for part in content or []:
        if isinstance(part, dict) and part.get("type", "text") in kinds and isinstance(part.get("text"), str):
            out.append(part["text"])
    return "\n".join(t for t in out if t)


def _kimi_args(raw):
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except Exception:
            return raw
    return raw


def _kimi_message_turns(msg, calls, legacy=False):
    """Turns for one whole message (v2 context.append_message, or a legacy context.jsonl row)."""
    role = msg.get("role")
    origin = (msg.get("origin") or {}).get("kind") if isinstance(msg.get("origin"), dict) else None
    if role == "user":
        text = _kimi_parts_text(msg.get("content"))
        if origin == "shell_command":
            m = re.search(r"<bash-input>\n?(.*?)\n?</bash-input>", text, re.S)
            if m:
                cmd = html.unescape(m.group(1)).strip()
                calls["!shell"] = _call_label("Bash", {"command": cmd})
                yield "cmd", cmd
            elif "<bash-stdout>" in text:
                out = "\n".join(html.unescape(x) for x in re.findall(r"<bash-std(?:out|err)>(.*?)</bash-std(?:out|err)>", text, re.S))
                turn = tool_turn(calls.get("!shell", "Bash"), out)
                if turn:
                    yield turn
        elif origin == "user" or (legacy and origin is None and not text.lstrip().startswith("<system")):
            if text.strip():
                yield "user", text
    elif role == "assistant":
        text = _kimi_parts_text(msg.get("content"))
        if text.strip():
            yield "assistant", text
        for call in msg.get("toolCalls") or msg.get("tool_calls") or []:
            fn = call.get("function") if isinstance(call.get("function"), dict) else call
            args = _kimi_args(fn.get("arguments"))
            calls[call.get("id")] = _call_label(fn.get("name"), args)
            cmd = _shell_cmd(fn.get("name"), args)
            if cmd:
                yield "cmd", cmd
    elif role == "tool":
        output = _kimi_parts_text(msg.get("content"))
        if legacy:
            output = re.sub(r"</?system>", "", output)
        turn = tool_turn(calls.get(msg.get("toolCallId") or msg.get("tool_call_id"), "tool"), output)
        if turn:
            yield turn


def kimi_iter(key):
    calls, text, legacy = {}, [], not str(key).endswith("wire.jsonl")
    for obj in _kimi_lines(key):
        if legacy:
            yield from _kimi_message_turns(obj, calls, legacy=True)
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
            yield from _kimi_message_turns(obj.get("message") or {}, calls)
        elif event.get("type") == "tool.call":
            args = event.get("args")
            calls[event.get("toolCallId")] = _call_label(event.get("name"), args)
            cmd = _shell_cmd(event.get("name"), args)
            if cmd:
                yield "cmd", cmd
        elif event.get("type") == "tool.result":
            result = event.get("result") or {}
            output = result.get("output")
            output = _kimi_parts_text(output) if isinstance(output, list) else output
            if result.get("isError"):
                output = "error\n" + str(output or "")
            turn = tool_turn(calls.get(event.get("toolCallId"), "tool"), output)
            if turn:
                yield turn
    if text and "\n".join(text).strip():
        yield "assistant", "\n".join(text)


def _kimi_session_dir(key):
    path = Path(key)
    return path.parents[2] if path.name == "wire.jsonl" else (path.parent if path.name.startswith("context") else None)


def _kimi_state(key):
    sdir = _kimi_session_dir(key)
    try:
        return json.loads((sdir / "state.json").read_text(encoding="utf-8")) if sdir else {}
    except Exception:
        return {}


def kimi_project(key):
    path = Path(key)
    if path.name == "wire.jsonl":
        state = _kimi_state(key)
        if isinstance(state.get("cwd"), str):
            return state["cwd"]
        for obj in _kimi_lines(_kimi_kimi_home() / "session_index.jsonl"):
            if obj.get("sessionDir") == str(path.parents[2]) and obj.get("workDir"):
                return obj["workDir"]
        return ""
    bucket = path.parent.parent.name if path.name.startswith("context") else path.parent.name
    try:
        work_dirs = json.loads((_kimi_legacy_home() / "kimi.json").read_text(encoding="utf-8")).get("work_dirs") or []
    except Exception:
        work_dirs = []
    for wd in work_dirs:
        if isinstance(wd, dict) and hashlib.md5(str(wd.get("path", "")).encode()).hexdigest() == bucket:
            return wd["path"]
    return ""


def kimi_title(key):
    state = _kimi_state(key)
    title = state.get("title") or state.get("customTitle") or state.get("custom_title") or ""
    if not title and not str(key).endswith("wire.jsonl") and _kimi_session_dir(key):
        try:
            title = json.loads((_kimi_session_dir(key) / "metadata.json").read_text(encoding="utf-8")).get("title") or ""
        except Exception:
            pass
    return title if isinstance(title, str) else ""


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


# ── Crush (crush) ────────────────────────────────────────────────────────────
# Crush (charmbracelet, npm @charmland/crush / brew charmbracelet/tap/crush) transcripts for navcom.
#
# Per-project SQLite at <project>/.crush/crush.db (or --data-dir / options.data_directory). Every project
# Crush has opened is listed in <global data>/projects.json {projects: [{path, data_dir, last_accessed}]},
# global data = $CRUSH_GLOBAL_DATA | $XDG_DATA_HOME/crush | ~/.local/share/crush (%LOCALAPPDATA%\crush).
#   sessions(id, parent_session_id, title, message_count, updated_at, created_at, …)
#      parent_session_id set for Agent-tool child sessions (id = tool call id) and for
#      "title-<parent>" title-generation sessions (skipped)
#   messages(id, session_id, role user|assistant|tool, parts JSON, created_at, is_summary_message, …)
#      parts: [{type: text{text, hidden?} | reasoning{thinking} | tool_call{id,name,input(JSON str)}
#              | tool_result{tool_call_id,name,content,is_error} | shell_command{command,output,exit_code}
#              | image_url | binary | finish, data: {…}}]
# Injected context (todo reminders, system prompt) is added at request time and never stored.

def _crush_global_data():
    explicit = _env_path("CRUSH_GLOBAL_DATA")
    if explicit:
        return explicit
    if os.environ.get("XDG_DATA_HOME"):
        return _xdg_data_home() / "crush"
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "crush"
    return Path.home() / ".local" / "share" / "crush"


def _crush_projects():
    try:
        data = json.loads((_crush_global_data() / "projects.json").read_text(encoding="utf-8"))
        return [p for p in data.get("projects") or [] if isinstance(p, dict)]
    except Exception:
        return []


def crush_roots():
    dbs = [Path(p["data_dir"]).expanduser() / "crush.db" for p in _crush_projects() if p.get("data_dir")]
    dbs.append(_crush_global_data() / ".crush" / "crush.db")  # `crush server` meta-workspace
    out = []
    for db in dbs:
        if db not in out:
            out.append(db)
    return out


def crush_list():
    logs = []
    for db in crush_roots():
        if not db.is_file():
            continue
        try:
            conn = _ro_connect(db)
            rows = conn.execute(
                "SELECT s.id, MAX(s.updated_at, COALESCE(MAX(m.updated_at), 0)), COUNT(m.id),"
                " COALESCE(SUM(LENGTH(m.parts)), 0) FROM sessions s LEFT JOIN messages m ON m.session_id = s.id"
                " WHERE s.id NOT LIKE 'title-%' GROUP BY s.id").fetchall()
            conn.close()
        except sqlite3.Error:
            continue
        for sid, updated, count, size in rows:
            if count:
                logs.append((f"{db}#{sid}", float(updated or 0), int(size), "crush"))
    return logs


def _crush_split(key):
    db, _, sid = str(key).partition("#")
    return db, sid


def _crush_session(key):
    db, sid = _crush_split(key)
    try:
        conn = _ro_connect(db)
        row = conn.execute("SELECT parent_session_id, title FROM sessions WHERE id = ?", (sid,)).fetchone()
        conn.close()
        return row or (None, "")
    except sqlite3.Error:
        return (None, "")


def crush_iter(key):
    db, sid = _crush_split(key)
    try:
        conn = _ro_connect(db)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(messages)")}
        summary = "is_summary_message" if "is_summary_message" in cols else "0"  # older Crush schemas
        rows = conn.execute(f"SELECT role, parts, {summary} FROM messages WHERE session_id = ?"
                            " ORDER BY created_at, rowid", (sid,)).fetchall()
        is_child = bool(conn.execute("SELECT parent_session_id FROM sessions WHERE id = ?", (sid,)).fetchone()[0])
        conn.close()
    except (sqlite3.Error, TypeError):
        return
    calls = {}
    for role, raw, is_summary in rows:
        if is_summary:
            continue  # auto-compaction summary, not a reply
        try:
            parts = json.loads(raw or "[]")
        except Exception:
            continue
        text = []
        for part in parts if isinstance(parts, list) else []:
            kind, data = (part.get("type"), part.get("data") or {}) if isinstance(part, dict) else (None, {})
            if kind == "text" and isinstance(data.get("text"), str) and not data.get("hidden"):
                text.append(data["text"])
                continue
            if kind in ("tool_call", "tool_result", "shell_command"):
                yield from _crush_flush(role, text, is_child)
                text = []
            if kind == "tool_call":
                args = data.get("input")
                try:
                    args = json.loads(args) if isinstance(args, str) and args.strip() else args
                except Exception:
                    pass
                calls[data.get("id")] = _call_label(data.get("name"), args)
                cmd = _shell_cmd(data.get("name"), args)
                if cmd:
                    yield "cmd", cmd
            elif kind == "tool_result":
                output = data.get("content") or ""
                if data.get("is_error"):
                    output = "error\n" + output
                turn = tool_turn(calls.get(data.get("tool_call_id")) or data.get("name") or "tool", output)
                if turn:
                    yield turn
            elif kind == "shell_command" and data.get("command"):  # user's `!cmd` (bang mode)
                yield "cmd", data["command"]
                output = data.get("output") or ""
                if data.get("exit_code"):
                    output = f"exit {data['exit_code']}\n{output}"
                turn = tool_turn(_call_label("bash", {"command": data["command"]}), output)
                if turn:
                    yield turn
        yield from _crush_flush(role, text, is_child)


def _crush_flush(role, text, is_child):
    body = "\n".join(t for t in text if t)
    if body.strip():
        if role == "assistant":
            yield "assistant", body
        elif role == "user" and not is_child:  # child (Agent tool) sessions are prompted by the parent agent
            yield "user", body


def crush_project(key):
    db = Path(_crush_split(key)[0])
    for proj in _crush_projects():
        if proj.get("data_dir") and Path(proj["data_dir"]).expanduser() / "crush.db" == db:
            return proj.get("path") or ""
    return str(db.parent.parent) if db.parent.name == ".crush" else ""


def crush_title(key):
    return _crush_session(key)[1] or ""


# ── GitHub Copilot CLI (copilot) ─────────────────────────────────────────────
# GitHub Copilot CLI (npm @github/copilot) session parser for navcom.
#
# On disk ($COPILOT_HOME, default ~/.copilot):
#   session-state/<uuid>/events.jsonl   one event per line {type, data, id, parentId, timestamp}
#   session-state/<uuid>/workspace.yaml id, cwd, name, summary, user_named, created_at, updated_at
#   session-state/<uuid>.jsonl          older flat layout (same events, no workspace.yaml)
#   history-session-state/*.json        oldest layout {sessionId, chatMessages:[OpenAI-style messages]}
#   session-store.db                    derived SQLite/FTS5 index (ignored)

def copilot_home():
    return _env_path("COPILOT_HOME") or Path.home() / ".copilot"


def copilot_roots():
    home = copilot_home()
    return [home / "session-state", home / "history-session-state"]


def copilot_list():
    state, legacy = copilot_roots()
    paths = []
    try:
        if state.is_dir():
            paths += list(state.glob("*/events.jsonl")) + list(state.glob("*.jsonl"))
        if legacy.is_dir():
            paths += list(legacy.glob("*.json"))
    except OSError:
        pass
    return _file_logs(paths, "copilot")


def _copilot_json_args(args):
    if isinstance(args, str):
        try:
            return json.loads(args)
        except Exception:
            return args
    return args


def _copilot_copilot_events(key):
    try:
        handle = open(key, "r", encoding="utf-8", errors="replace")
    except OSError:
        return
    with handle:
        for line in handle:
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if isinstance(obj, dict):
                yield obj.get("type"), obj.get("data") if isinstance(obj.get("data"), dict) else {}


_copilot_SHELL_TAIL_RE = re.compile(r"\n?<shellId: [^>]*? exit code (-?\d+)>\s*$")


def _copilot_copilot_output(data, tool=""):
    result = data.get("result") if isinstance(data.get("result"), dict) else {}
    output = result.get("content") or ""
    detailed = result.get("detailedContent")
    # detailedContent carries full diffs for edit tools; for view it re-renders the file as a diff
    if isinstance(detailed, str) and detailed.strip() and (not output or tool not in ("view", "read", "glob", "grep")):
        output = detailed
    if not output and isinstance(result.get("contents"), list):
        output = _text_of(result["contents"])
    if isinstance(output, str):  # bash results end with "<shellId: 0 completed with exit code N>"
        tail = _copilot_SHELL_TAIL_RE.search(output)
        if tail:
            output = (f"exit {tail.group(1)}\n" if tail.group(1) != "0" else "") + output[:tail.start()]
    if data.get("success") is False:
        error = data.get("error") if isinstance(data.get("error"), dict) else {}
        output = "error\n" + "\n".join(t for t in (error.get("message"), output) if isinstance(t, str) and t)
    return output


def copilot_iter(key):
    if key.endswith(".json"):
        yield from _copilot_copilot_legacy_iter(key)
        return
    calls, names = {}, {}
    for kind, data in _copilot_copilot_events(key):
        if kind == "user.message":
            source = data.get("source")
            if (source and source != "user") or data.get("isAutopilotContinuation"):
                continue  # skill injections, inter-agent prompts, autopilot "continue" nudges
            text = data.get("content")  # 'transformedContent' adds <current_datetime> etc. — not typed
            if isinstance(text, str) and text.strip():
                yield "user", text
        elif kind == "assistant.message":
            text = data.get("content")  # reasoningText / encryptedContent are thinking — skipped
            if isinstance(text, str) and text.strip():
                yield "assistant", text
            for req in data.get("toolRequests") or []:
                if isinstance(req, dict):
                    calls[req.get("toolCallId")] = _call_label(req.get("name"), _copilot_json_args(req.get("arguments")))
        elif kind == "tool.execution_start":
            args = _copilot_json_args(data.get("arguments"))
            calls[data.get("toolCallId")] = _call_label(data.get("toolName"), args)
            names[data.get("toolCallId")] = data.get("toolName") or ""
            cmd = _shell_cmd(data.get("toolName"), args)  # bash / powershell; write_bash has no command
            if cmd:
                yield "cmd", cmd
        elif kind == "tool.execution_complete":
            turn = tool_turn(calls.get(data.get("toolCallId"), "tool"),
                                 _copilot_copilot_output(data, names.get(data.get("toolCallId"), "")))
            if turn:
                yield turn
        # system.message (system prompt), system.notification, skill.invoked, session.*, hook.*,
        # assistant.reasoning, subagent.* and the rest are injected/bookkeeping: skipped.


_copilot_DATETIME_RE = re.compile(r"^\s*<current_datetime>.*?</current_datetime>\s*", re.S)


def _copilot_copilot_legacy_iter(key):
    """history-session-state/*.json (Copilot CLI 0.0.x): OpenAI-style chatMessages. Unverified on disk."""
    try:
        data = json.loads(Path(key).read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return
    calls = {}
    for msg in (data.get("chatMessages") if isinstance(data, dict) else None) or []:
        if not isinstance(msg, dict):
            continue
        role, text = msg.get("role"), _text_of(msg.get("content") or "")
        if role == "user":
            text = _copilot_DATETIME_RE.sub("", text)
            if text.strip() and not text.lstrip().startswith("<reminder>"):
                yield "user", text
        elif role == "assistant":
            if text.strip():
                yield "assistant", text
            for call in msg.get("tool_calls") or []:
                fn = (call or {}).get("function") or {}
                args = _copilot_json_args(fn.get("arguments"))
                calls[call.get("id")] = _call_label(fn.get("name"), args)
                cmd = _shell_cmd(fn.get("name"), args)
                if cmd:
                    yield "cmd", cmd
        elif role == "tool":
            turn = tool_turn(calls.get(msg.get("tool_call_id"), "tool"), msg.get("content"))
            if turn:
                yield turn


def _copilot_copilot_workspace(key):
    """workspace.yaml is flat `key: value` YAML; parse the scalars we need without a YAML lib."""
    out = {}
    try:
        lines = (Path(key).parent / "workspace.yaml").read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return out
    for line in lines:
        m = re.match(r"^([A-Za-z_]+):\s?(.*)$", line)
        if not m:
            continue
        value = m.group(2).strip()
        if len(value) >= 2 and value[0] == value[-1] == "'":
            value = value[1:-1].replace("''", "'")
        elif len(value) >= 2 and value[0] == value[-1] == '"':
            try:
                value = json.loads(value)
            except Exception:
                value = value[1:-1]
        out[m.group(1)] = value
    return out


def copilot_project(key):
    if key.endswith("events.jsonl"):
        cwd = _copilot_copilot_workspace(key).get("cwd")
        if cwd:
            return cwd
    for kind, data in _copilot_copilot_events(key) if key.endswith(".jsonl") else []:
        if kind in ("session.start", "session.resume"):
            ctx = data.get("context") if isinstance(data.get("context"), dict) else {}
            if isinstance(ctx.get("cwd"), str):
                return ctx["cwd"]
    return ""


def copilot_title(key):
    if not key.endswith(".jsonl"):
        return ""
    title = ""
    for kind, data in _copilot_copilot_events(key):
        if kind == "session.title_changed" and isinstance(data.get("title"), str):
            title = data["title"]
    if title:
        return title
    ws = _copilot_copilot_workspace(key) if key.endswith("events.jsonl") else {}
    if ws.get("user_named") == "true" and ws.get("name"):
        return ws["name"]
    return ws.get("summary") or ws.get("name") or ""


# ── Cline (cline) ────────────────────────────────────────────────────────────
# Cline session parser for navcom. Two on-disk shapes:
#
# 1. Cline CLI 3.x / SDK (npm `cline`):
#      $CLINE_SESSION_DATA_DIR or $CLINE_DATA_DIR/sessions or $CLINE_DIR/data/sessions (default ~/.cline/data/sessions)
#        <id>/<id>.messages.json  {version, sessionId, agent, origin, system_prompt, messages:[Anthropic-style]}
#        <id>/<id>.json           manifest {session_id, cwd, workspace_root, prompt, metadata.title, ...}
#      db/sessions.db mirrors the manifests (index only; not needed to read transcripts).
# 2. Cline VS Code extension (and forks: Cursor, Windsurf, ...; also older ~/.cline/data/tasks):
#      <app>/User/globalStorage/saoudrizwan.claude-dev/tasks/<ts>/ui_messages.json   (UI timeline: say/ask)
#      .../tasks/<ts>/api_conversation_history.json  (model-facing; full of injected environment_details)
#      .../state/taskHistory.json  [{id, task, cwdOnTaskInitialization?, ...}]
#    We parse ui_messages.json: it separates typed text, replies, commands and outputs cleanly
#    across both the XML-tool era (2024) and the native-tool era.

_cline_CLINE_EXT_ID = "saoudrizwan.claude-dev"


def cline_data_dir():
    return _env_path("CLINE_DATA_DIR") or (_env_path("CLINE_DIR") or Path.home() / ".cline") / "data"


def cline_sessions_dir():
    return _env_path("CLINE_SESSION_DATA_DIR") or cline_data_dir() / "sessions"


def _cline_editor_config_bases():
    if sys.platform == "darwin":
        return [Path.home() / "Library" / "Application Support"]
    if sys.platform.startswith("win"):
        return [Path(os.environ["APPDATA"])] if os.environ.get("APPDATA") else []
    return [Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config").expanduser()]


def _cline_cline_task_dirs():
    dirs = [cline_data_dir() / "tasks"]
    for base in _cline_editor_config_bases():
        try:
            dirs += sorted(base.glob(f"*/User/globalStorage/{_cline_CLINE_EXT_ID}/tasks"))
        except OSError:
            pass
    return dirs


def cline_roots():
    return [cline_sessions_dir()] + _cline_cline_task_dirs()


def cline_list():
    paths = _rglob(cline_sessions_dir(), "*.messages.json")
    for tasks in _cline_cline_task_dirs():
        try:
            if tasks.is_dir():
                paths += list(tasks.glob("*/ui_messages.json"))
        except OSError:
            pass
    return _file_logs(paths, "cline")


def _cline_load_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return None


def cline_iter(key):
    if key.endswith("ui_messages.json"):
        yield from _cline_cline_ui_iter(key)
    else:
        yield from _cline_cline_sdk_iter(key)


# ── Cline CLI 3.x / SDK ──────────────────────────────────────────────────────

_cline_WRAP_RE = re.compile(r"<user_(?:input|command)\b")
_cline_FILE_RE = re.compile(r"<file_content\b[^>]*>.*?</file_content>", re.S)
_cline_NOTICE_RE = re.compile(r"<mode_notice>.*?</mode_notice>", re.S)
_cline_COMMAND_RE = re.compile(r'^\s*<user_command\b[^>]*\bslash="([^"]+)"[^>]*>(.*?)</user_command>\s*$', re.S | re.I)


def _cline_cline_typed(text):
    """Cline's own normalizeUserInput: unwrap <user_input>, render <user_command slash> as /slash."""
    slash = _cline_COMMAND_RE.match(text)
    text = _cline_NOTICE_RE.sub("", _cline_FILE_RE.sub("", text))
    for tag in ("user_input", "user_command"):
        text = re.sub(rf"<{tag}\b[^>]*>(.*?)</{tag}>", r"\1", text, flags=re.S)
        text = re.sub(rf"</?{tag}\b[^>]*>", "", text)
    text = text.strip()
    if slash:
        return f"/{slash.group(1)} {text}".strip()
    return text


def _cline_cline_commands(name, args):
    """run_commands takes {commands:[str | {command, args}]} (or a bare string/list); others: navcom's rule."""
    if name != "run_commands":
        cmd = _shell_cmd(name, args)
        return [cmd] if cmd else []
    items = args.get("commands", args.get("command", args.get("cmd"))) if isinstance(args, dict) else args
    if not isinstance(items, list):
        items = [items]
    cmds = []
    for item in items:
        if isinstance(item, dict):
            argv = [a if not re.search(r'[\s"]', str(a)) else json.dumps(a) for a in item.get("args") or []]
            item = " ".join([str(item.get("command") or "")] + argv).strip()
        if isinstance(item, str) and item.strip():
            cmds.append(item.strip())
    return cmds


def _cline_cline_label_args(args):
    """read_files {files:[{path}]} / fetch_web_content {requests:[{url}]} -> a dict _call_label understands."""
    if isinstance(args, dict):
        for field, key in (("files", "path"), ("requests", "url")):
            items = args.get(field)
            if isinstance(items, list):
                vals = [str(i.get(key) if isinstance(i, dict) else i) for i in items]
                return {key: ", ".join(v for v in vals if v and v != "None")}
    return args


def _cline_cline_result(content):
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        content = [content]
    parts = []
    for item in content if isinstance(content, list) else []:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, dict) and ("result" in item or "error" in item):
            result = item.get("result")
            text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False) if result else ""
            if item.get("error") and str(item["error"]) not in text:
                text = f"error: {item['error']}\n{text}".strip()
            if len(content) > 1 and item.get("query"):
                text = f"$ {item['query']}\n{text}"
            parts.append(text)
        elif isinstance(item, dict) and item.get("type") == "text":
            parts.append(item.get("text") or "")
    return "\n".join(p for p in parts if p)


def _cline_cline_sdk_iter(key):
    data = _cline_load_json(key)
    messages = data.get("messages") if isinstance(data, dict) else data
    if not isinstance(messages, list):
        return
    blocks = lambda m: [{"type": "text", "text": m["content"]}] if isinstance(m.get("content"), str) else (
        m.get("content") if isinstance(m.get("content"), list) else [])
    # 3.x wraps typed input in <user_input>; once a session uses the wrapper, any bare user text is
    # runtime-injected (loop/mistake notices, file attachments). Imported/older sessions have no wrapper.
    wrapped = any(m.get("role") == "user" and any(b.get("type") == "text" and _cline_WRAP_RE.search(b.get("text") or "")
                                                  for b in blocks(m) if isinstance(b, dict))
                  for m in messages if isinstance(m, dict))
    calls = {}
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        meta = msg.get("metadata") if isinstance(msg.get("metadata"), dict) else {}
        injected = bool(meta.get("kind")) or meta.get("displayRole") == "system"  # compaction summaries
        for block in blocks(msg):
            if not isinstance(block, dict):
                continue
            kind = block.get("type")
            if msg.get("role") == "user":
                if kind == "tool_result":
                    output = _cline_cline_result(block.get("content"))
                    if block.get("is_error"):
                        output = "error\n" + output
                    turn = tool_turn(calls.get(block.get("tool_use_id"), block.get("name") or "tool"), output)
                    if turn:
                        yield turn
                elif kind == "text" and not injected:
                    text = block.get("text") or ""
                    if wrapped and not _cline_WRAP_RE.search(text):
                        continue
                    text = _cline_cline_typed(text)
                    if text:
                        yield "user", text
            elif msg.get("role") == "assistant":
                if kind == "text" and (block.get("text") or "").strip():
                    yield "assistant", block["text"]
                elif kind == "tool_use":
                    args = block.get("input")
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except Exception:
                            pass
                    cmds = _cline_cline_commands(block.get("name"), args)
                    calls[block.get("id")] = _call_label(
                        block.get("name"), {"command": " ; ".join(cmds)} if cmds else _cline_cline_label_args(args))
                    for cmd in cmds:
                        yield "cmd", cmd
                # thinking / reasoning / redacted_thinking / image blocks: skipped


# ── VS Code extension tasks (ui_messages.json) ────────────────────────────────

def _cline_cline_ui_iter(key):
    messages = _cline_load_json(key)
    if not isinstance(messages, list):
        return
    seen_request = got_task = False
    cmd_label, cmd_out, mcp_label = None, [], None

    def flush():
        return tool_turn(cmd_label, "\n".join(cmd_out)) if cmd_label and cmd_out else None

    for msg in messages:
        if not isinstance(msg, dict):
            continue  # note: newer builds leave partial=True on finished text, so `partial` is not a skip signal
        kind, text = msg.get("say") or msg.get("ask"), msg.get("text") or ""
        if kind != "command_output" and cmd_label:
            turn = flush()
            if turn:
                yield turn
            cmd_label, cmd_out = None, []
        if kind == "api_req_started":  # the full model request incl. environment_details — injected
            seen_request = True
        elif kind == "task" or (kind == "text" and msg.get("type") == "say" and not seen_request and not got_task):
            got_task = True
            if text.strip():
                yield "user", text
        elif kind == "user_feedback":
            if text.strip():
                yield "user", text
        elif kind in ("text", "completion_result") and msg.get("type") == "say":
            text = re.sub(r"\s*HAS_CHANGES\s*$", "", text)
            if text.strip():
                yield "assistant", text
        elif kind in ("followup", "plan_mode_respond", "completion_result") and msg.get("type") == "ask":
            obj = _cline_maybe_json(text)
            if isinstance(obj, dict):
                text = obj.get("question") or obj.get("response") or ""
            if isinstance(text, str) and text.strip():
                yield "assistant", text
        elif kind == "command":
            cmd = re.sub(r"\s*REQ_APP\s*$", "", text).strip()
            if cmd:
                yield "cmd", cmd
                cmd_label, cmd_out = _call_label("execute_command", {"command": cmd}), []
        elif kind == "command_output":
            if cmd_label:
                cmd_out.append(text)
            else:
                turn = tool_turn("command output", text)
                if turn:
                    yield turn
        elif kind == "tool":
            obj = _cline_maybe_json(text)
            if isinstance(obj, dict):
                output = obj.get("content") or obj.get("diff") or ""
                turn = tool_turn(_call_label(obj.get("tool"), obj), output if isinstance(output, str) else "")
                if turn:
                    yield turn
        elif kind == "use_mcp_server":
            obj = _cline_maybe_json(text) or {}
            mcp_label = _call_label(f"{obj.get('serverName', 'mcp')}.{obj.get('toolName') or obj.get('uri') or ''}",
                                        _cline_maybe_json(obj.get("arguments")) if obj.get("arguments") else None)
        elif kind == "mcp_server_response":
            turn = tool_turn(mcp_label or "mcp", text)
            if turn:
                yield turn
        # reasoning, api_req_*, error, checkpoint_created, resume_task, browser_action*, ... skipped
    turn = flush()
    if turn:
        yield turn


def _cline_maybe_json(text):
    if not isinstance(text, str) or not text.lstrip().startswith(("{", "[")):
        return text if isinstance(text, dict) else None
    try:
        return json.loads(text)
    except Exception:
        return None


def _cline_cline_task_meta(key):
    task_id = Path(key).parent.name
    history = _cline_load_json(Path(key).parent.parent.parent / "state" / "taskHistory.json")
    for item in history if isinstance(history, list) else []:
        if isinstance(item, dict) and str(item.get("id")) == task_id:
            return item
    return {}


def _cline_cline_manifest(key):
    sid = Path(key).name[: -len(".messages.json")]
    manifest = _cline_load_json(Path(key).parent / f"{sid}.json")
    if isinstance(manifest, dict):
        return manifest
    db = cline_data_dir() / "db" / "sessions.db"
    try:
        con = _ro_connect(db)
        try:
            row = con.execute("SELECT cwd, prompt, metadata_json FROM sessions WHERE session_id = ?", (sid,)).fetchone()
        finally:
            con.close()
    except sqlite3.Error:
        row = None
    if not row:
        return {}
    meta = _cline_maybe_json(row[2]) or {}
    return {"cwd": row[0], "prompt": row[1], "metadata": meta if isinstance(meta, dict) else {}}


_cline_CWD_RE = re.compile(r"# Current Working Directory \((/[^)\n]+)\) Files")


def cline_project(key):
    if key.endswith("ui_messages.json"):
        cwd = _cline_cline_task_meta(key).get("cwdOnTaskInitialization")
        if cwd:
            return cwd
        try:
            with open(Path(key).parent / "api_conversation_history.json", "r", encoding="utf-8", errors="replace") as fh:
                m = _cline_CWD_RE.search(fh.read(2_000_000))
            return m.group(1) if m else ""
        except OSError:
            return ""
    manifest = _cline_cline_manifest(key)
    return manifest.get("cwd") or manifest.get("workspace_root") or ""


def cline_title(key):
    if key.endswith("ui_messages.json"):
        task = _cline_cline_task_meta(key).get("task") or ""
        return task.strip().splitlines()[0][:200] if task.strip() else ""
    meta = _cline_cline_manifest(key).get("metadata") or {}
    return meta.get("title") or "" if isinstance(meta, dict) else ""


def cline_legacy_fixture(home, cwd):
    """A VS Code extension task (ui_messages.json + api history + taskHistory), as on this Mac."""
    base = Path(home) / "Library" / "Application Support" / "Code" / "User" / "globalStorage" / _cline_CLINE_EXT_ID
    if not sys.platform == "darwin":
        base = Path(home) / ".config" / "Code" / "User" / "globalStorage" / _cline_CLINE_EXT_ID
    tid = "1728640760969"
    tdir = base / "tasks" / tid
    tdir.mkdir(parents=True, exist_ok=True)
    ui = [
        {"ts": 1, "type": "say", "say": "text", "text": "please check zebracornclineext", "images": []},
        {"ts": 2, "type": "say", "say": "api_req_started",
         "text": json.dumps({"request": "<task>x</task>\n<environment_details>zebracorninjected</environment_details>"})},
        {"ts": 3, "type": "say", "say": "reasoning", "text": "zebracorninjected thinking"},
        {"ts": 4, "type": "say", "say": "text", "text": "Running it for zebracornclineext.", "partial": False},
        {"ts": 5, "type": "ask", "ask": "command", "text": "echo hi-clineext", "partial": False},
        {"ts": 6, "type": "ask", "ask": "command_output", "text": "zebracornclineexttool"},
        {"ts": 7, "type": "ask", "ask": "command_output", "text": "second line"},
        {"ts": 8, "type": "say", "say": "api_req_started", "text": json.dumps({"request": "[execute_command] zebracorninjected"})},
        {"ts": 9, "type": "say", "say": "tool", "text": json.dumps({"tool": "readFile", "path": "calc.py", "content": "def add zebracornclineextfile"})},
        {"ts": 10, "type": "say", "say": "completion_result", "text": "All done zebracornclineext"},
        {"ts": 11, "type": "ask", "ask": "completion_result", "text": ""},
        {"ts": 12, "type": "say", "say": "user_feedback", "text": "thanks zebracornclineext", "images": []},
    ]
    (tdir / "ui_messages.json").write_text(json.dumps(ui))
    (tdir / "api_conversation_history.json").write_text(json.dumps([{"role": "user", "content": [
        {"type": "text", "text": "<task>\nplease check zebracornclineext\n</task>"},
        {"type": "text", "text": f"<environment_details>\n# Current Working Directory ({cwd}) Files\nzebracorninjected\n</environment_details>"}]}]))
    (base / "state").mkdir(parents=True, exist_ok=True)
    (base / "state" / "taskHistory.json").write_text(json.dumps([{"id": tid, "ts": 1, "task": "please check zebracornclineext"}]))
    return str(tdir / "ui_messages.json")


# ── Continue (continue) ──────────────────────────────────────────────────────
# Continue (`cn` CLI, npm @continuedev/cli, and the Continue IDE extensions) session parser for navcom.
#
# On disk ($CONTINUE_GLOBAL_DIR, default ~/.continue):
#   sessions/<uuid>.json   {sessionId, title, workspaceDirectory, history:[ChatHistoryItem], usage?}
#   sessions/sessions.json index [{sessionId, title, dateCreated, workspaceDirectory, messageCount?}]
# ChatHistoryItem = {message:{role, content, toolCalls?, toolCallId?}, contextItems, editorState?,
#                    toolCallStates?:[{toolCallId, toolCall, status, parsedArgs, output:[{content,name}]}],
#                    toolCallState? (older IDE, singular), promptLogs?, conversationSummary?}
# The IDE and the CLI share this file layout; the IDE stores content as parts, the CLI as a string.

_continue_DEFAULT_TITLES = ("", "Untitled Session", "New Session")


def continue_home():
    return _env_path("CONTINUE_GLOBAL_DIR") or Path.home() / ".continue"


def continue_roots():
    return [continue_home() / "sessions"]


def continue_list():
    root = continue_roots()[0]
    try:
        paths = [p for p in root.glob("*.json") if p.name != "sessions.json"] if root.is_dir() else []
    except OSError:
        paths = []
    return _file_logs(paths, "continue")


def _continue_load(key):
    try:
        data = json.loads(Path(key).read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _continue_args(call):
    fn = (call or {}).get("function") if isinstance(call, dict) else None
    fn = fn if isinstance(fn, dict) else {}
    args = fn.get("arguments")
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except Exception:
            pass
    return fn.get("name"), args


def _continue_state_output(state):
    output = state.get("output")
    if isinstance(output, list):  # ContextItem[]: {content, name, description}
        return "\n".join(o.get("content") for o in output if isinstance(o, dict) and isinstance(o.get("content"), str))
    return output if isinstance(output, str) else ""


def continue_iter(key):
    calls, done, after_summary = {}, set(), False
    for item in _continue_load(key).get("history") or []:
        if not isinstance(item, dict):
            continue
        msg = item.get("message") if isinstance(item.get("message"), dict) else {}
        role = msg.get("role")
        if item.get("conversationSummary") is not None:
            after_summary = True  # compaction summary (model-written context) — injected
            continue
        if role == "user":
            text = _text_of(msg.get("content") or "")
            if after_summary and text.strip() == "continue":
                continue  # cn auto-continues after compaction with a synthetic "continue"
            if text.strip():
                yield "user", text
        elif role == "assistant":
            text = _text_of(msg.get("content") or "")
            if text.strip():
                yield "assistant", text
            states = item.get("toolCallStates") or ([item["toolCallState"]] if isinstance(item.get("toolCallState"), dict) else [])
            by_id = {s.get("toolCallId"): s for s in states if isinstance(s, dict)}
            for call in msg.get("toolCalls") or [s.get("toolCall") for s in by_id.values()]:
                name, args = _continue_args(call)
                cid = (call or {}).get("id") if isinstance(call, dict) else None
                state = by_id.get(cid) or {}
                if isinstance(state.get("parsedArgs"), dict):
                    args = state["parsedArgs"]
                label_args = args
                if isinstance(args, dict) and not args.get("path") and (args.get("filepath") or args.get("dirPath")):
                    label_args = {**args, "path": args.get("filepath") or args.get("dirPath")}  # Read/builtin_read_file
                calls[cid] = _call_label(name, label_args)
                cmd = _shell_cmd(name, args)  # cn "Bash"; IDE "builtin_run_terminal_command"
                if cmd:
                    yield "cmd", cmd
                if state:
                    turn = tool_turn(calls[cid], _continue_state_output(state))
                    done.add(cid)
                    if turn:
                        yield turn
        elif role == "tool":  # IDE agent mode also logs results as role=tool items
            if msg.get("toolCallId") not in done:
                turn = tool_turn(calls.get(msg.get("toolCallId"), "tool"), msg.get("content"))
                if turn:
                    yield turn
        # role system (system prompt, slash-command output, compaction notices) and thinking: skipped
        after_summary = False


def continue_project(key):
    ws = _continue_load(key).get("workspaceDirectory") or ""
    if isinstance(ws, str) and ws.startswith("file://"):
        ws = unquote(urlparse(ws).path)
    return ws if isinstance(ws, str) else ""


def continue_title(key):
    title = _continue_load(key).get("title")
    return title if isinstance(title, str) and title not in _continue_DEFAULT_TITLES else ""


# ── Codewhale (codewhale) ────────────────────────────────────────────────────
# navcom parsers for three DeepSeek-first harnesses: Codewhale, Reasonix, Deep Code.
#
# The same file is copied into harness/codewhale, harness/reasonix and harness/deepcode.

def _codewhale_load_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return None


def _codewhale_jsonl(path):
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


def _codewhale_tolerant(gen_fn):
    """Odd records end a transcript early instead of raising into the indexer."""
    def wrapper(key):
        try:
            yield from gen_fn(key)
        except Exception:
            return
    wrapper.__name__ = gen_fn.__name__
    return wrapper


def _codewhale_safe_str(fn):
    def wrapper(key):
        try:
            return fn(key) or ""
        except Exception:
            return ""
    wrapper.__name__ = fn.__name__
    return wrapper


def _codewhale_args(raw):
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except Exception:
            return raw
    return raw


# A text part that is one whole XML-ish element is host-injected context
# (<turn_meta>, <session_goal>, <workspace>, <session-context>, <system-reminder>, …).
_codewhale_INJECTED_BLOCK_RE = re.compile(r"^\s*<([A-Za-z][\w-]*)\b[^>]*>.*</\1>\s*$|^\s*<[A-Za-z][\w-]*\b[^>]*/>\s*$", re.S)
_codewhale_EDGE_BLOCK_RE = re.compile(r"\A\s*<([A-Za-z][\w-]*)\b[^>]*>\n.*?\n</\1>\s*|\s*<([A-Za-z][\w-]*)\b[^>]*>\n.*?\n</\2>\s*\Z", re.S)


def _codewhale_strip_injected(text):
    """Drop whole injected XML blocks wrapped around typed text (leading or trailing)."""
    if not isinstance(text, str):
        return ""
    if _codewhale_INJECTED_BLOCK_RE.match(text):
        return ""
    prev = None
    while prev != text:
        prev, text = text, _codewhale_EDGE_BLOCK_RE.sub("", text, count=1)
    return text.strip()


# ─────────────────────────────────────────────────────────────────────────────
# Codewhale (formerly DeepSeek-TUI) ─ $CODEWHALE_HOME/sessions/<id>.json
#   legacy ~/.deepseek/sessions (migrated by move, or copied when the move fails)
# ─────────────────────────────────────────────────────────────────────────────

def codewhale_roots():
    explicit = _env_path("CODEWHALE_HOME")
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
    return _file_logs(paths, "codewhale")


def _codewhale_codewhale_messages(session):
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


@_codewhale_tolerant
def codewhale_iter(key):
    session = _codewhale_load_json(key)
    if not isinstance(session, dict):
        return
    calls = {}
    for message in _codewhale_codewhale_messages(session):
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
                    text = _codewhale_strip_injected(text)
                elif role == "assistant_interrupted":
                    text = text.replace(
                        "[The following assistant output was interrupted before completion and may be incomplete or wrong]\n", "")
                if text.strip():
                    texts.append(text)
            elif kind in ("tool_use", "server_tool_use"):
                if texts:
                    yield ("user" if role == "user" else "assistant"), "\n".join(texts)
                    texts = []
                args = _codewhale_args(block.get("input"))
                calls[block.get("id")] = _call_label(block.get("name"), args)
                cmd = _shell_cmd(block.get("name"), args)
                if cmd:
                    yield "cmd", cmd
            elif kind in ("tool_result", "tool_search_tool_result", "code_execution_tool_result"):
                output = block.get("content")
                if (not isinstance(output, str) or not output.strip()) and block.get("content_blocks"):
                    output = block["content_blocks"]
                if block.get("is_error"):
                    output = "error\n" + (output if isinstance(output, str) else _text_of(output))
                turn = tool_turn(calls.get(block.get("tool_use_id"), "tool"), output)
                if turn:
                    yield turn
            # thinking / image_url: skipped
        if texts:
            yield ("user" if role == "user" else "assistant"), "\n".join(texts)


def _codewhale_codewhale_meta(key):
    session = _codewhale_load_json(key)
    meta = session.get("metadata") if isinstance(session, dict) else None
    return meta if isinstance(meta, dict) else {}


@_codewhale_safe_str
def codewhale_project(key):
    return str(_codewhale_codewhale_meta(key).get("workspace") or "")


@_codewhale_safe_str
def codewhale_title(key):
    return str(_codewhale_codewhale_meta(key).get("title") or "")


# ─────────────────────────────────────────────────────────────────────────────
# Reasonix ─ state root = $REASONIX_STATE_HOME | $REASONIX_HOME | ~/.reasonix
#   2.x (Studio, Go):      <state>/[projects/<slug>/]sessions/<stem>.jsonl  (+ <stem>.events.jsonl
#                          schema 1/3 replace|append records; may hold newer turns than the .jsonl)
#   1.x 1.38.2–1.38.7:     same names, but <stem>.events.jsonl is a schema 2 DAG log
#   1.x ≥1.38.8 (npm):     <state>/projects/<slug>/sessions-v4/<id>/events.frames
#                          (RX4F frames of zstd JSON records; big payloads in ../.content-v1)
# ─────────────────────────────────────────────────────────────────────────────

_codewhale_REASONIX_SIDECARS = (".events.jsonl", ".conflicts.jsonl", ".guardian.jsonl", ".wire.jsonl",
                      ".adjudication.jsonl", ".execution.jsonl", ".turns.jsonl")


def reasonix_roots():
    state = _env_path("REASONIX_STATE_HOME", "REASONIX_HOME")
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


def _codewhale_reasonix_session_dirs(state):
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
        for sessions in _codewhale_reasonix_session_dirs(state):
            for path in _rglob(sessions, "*.jsonl"):
                rel = path.relative_to(sessions).parts
                if any(p.startswith(".") or p.endswith(".ckpt") or p.endswith(".inbox") for p in rel[:-1]):
                    continue
                if path.name.endswith(_codewhale_REASONIX_SIDECARS):
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
                logs.extend(_file_logs([frames], "reasonix"))
    return logs


def _codewhale_rx4f_records(frames_path):
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
        raw = read_zstd(tmp.name)
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


def _codewhale_reasonix_v4(frames_path):
    """-> (messages, title). Keeps every message the log ever committed (upserts in
    place; retracted and history-replaced messages are kept), in first-seen order."""
    sdir = Path(frames_path).parent
    manifest = _codewhale_load_json(sdir / "manifest.json") or {}
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

    for rec in _codewhale_rx4f_records(frames_path):
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


def _codewhale_reasonix_events_kind(events_path):
    for rec in _codewhale_jsonl(events_path):
        return rec.get("schema_version")
    return None


def _codewhale_reasonix_dag(events_path):
    """1.x schema 2 DAG log: every message node of every head, patches/redactions applied."""
    order, by_id = [], {}
    for rec in _codewhale_jsonl(events_path):
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


def _codewhale_reasonix_replay(events_path):
    """2.x schema 1/3 log: replace resets, append extends. Messages a later replace
    dropped (rewinds, compaction) are kept, in first-seen order."""
    snapshots, cur, records = [], [], 0
    for rec in _codewhale_jsonl(events_path):
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


def _codewhale_reasonix_messages(key):
    if key.endswith("events.frames"):
        return _codewhale_reasonix_v4(key)[0]
    events = key[:-len(".jsonl")] + ".events.jsonl"
    if os.path.exists(events):
        schema = _codewhale_reasonix_events_kind(events)
        msgs = _codewhale_reasonix_dag(events) if schema == 2 else _codewhale_reasonix_replay(events)
        if msgs:
            return msgs
    return list(_codewhale_jsonl(key))


def _codewhale_openai_calls(tool_calls):
    for call in tool_calls if isinstance(tool_calls, list) else []:
        if not isinstance(call, dict):
            continue
        fn = call.get("function") if isinstance(call.get("function"), dict) else call
        yield call.get("id"), fn.get("name") or call.get("resolved_name"), _codewhale_args(fn.get("arguments"))


@_codewhale_tolerant
def reasonix_iter(key):
    calls = {}
    for msg in _codewhale_reasonix_messages(key):
        role = msg.get("role")
        if role == "user":
            if msg.get("host_authored") or msg.get("origin") == "host":
                continue  # session-context snapshots, steer notes: injected
            raw = msg.get("raw_content")
            text = raw if isinstance(raw, str) and raw.strip() else _codewhale_strip_injected(_text_of(msg.get("content")))
            if text.strip():
                yield "user", text
        elif role == "assistant":
            text = _text_of(msg.get("content"))
            if text.strip():
                yield "assistant", text.strip()
            for cid, name, args in _codewhale_openai_calls(msg.get("tool_calls")):
                calls[cid] = _call_label(name, args)
                cmd = _shell_cmd(name, args)
                if cmd:
                    yield "cmd", cmd
        elif role == "tool":
            output = msg.get("content")
            if isinstance(output, list):
                output = _text_of(output)
            label = calls.get(msg.get("tool_call_id")) or msg.get("name") or "tool"
            turn = tool_turn(label, output)
            if turn:
                yield turn


_codewhale_WORKSPACE_RE = re.compile(r'Current workspace: "([^"]+)"')


@_codewhale_safe_str
def reasonix_project(key):
    for msg in _codewhale_reasonix_messages(key)[:8]:
        if msg.get("role") in ("user", "system"):
            m = _codewhale_WORKSPACE_RE.search(_text_of(msg.get("content")) or "")
            if m:
                return m.group(1)
    parts = Path(key).parts
    if "projects" in parts:
        i = len(parts) - 1 - parts[::-1].index("projects")
        if i + 1 < len(parts):
            return parts[i + 1]  # lossy slug (/ → -), same as navcom does for Claude
    return ""


@_codewhale_safe_str
def reasonix_title(key):
    if key.endswith("events.frames"):
        title = _codewhale_reasonix_v4(key)[1]
        if title:
            return title
        cache = _codewhale_load_json(Path(key).parent.parent / ".query-cache" / Path(key).parent.name / "catalog-metadata.json")
        return str((cache or {}).get("title") or "").strip()
    meta = _codewhale_load_json(key + ".meta") or {}
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
    return _file_logs(paths, "deepcode")


def _codewhale_deepcode_tool_output(content):
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


@_codewhale_tolerant
def deepcode_iter(key):
    calls = {}
    for msg in _codewhale_jsonl(key):
        role = msg.get("role")
        params = msg.get("messageParams") if isinstance(msg.get("messageParams"), dict) else {}
        meta = msg.get("meta") if isinstance(msg.get("meta"), dict) else {}
        if role == "user":
            prompt = meta.get("userPrompt") if isinstance(meta.get("userPrompt"), dict) else {}
            text = prompt.get("text") if isinstance(prompt.get("text"), str) else _text_of(msg.get("content"))
            if text and text.strip():
                yield "user", text
        elif role == "assistant":
            text = _text_of(msg.get("content"))
            if text.strip():
                yield "assistant", text.strip()
            for cid, name, args in _codewhale_openai_calls(params.get("tool_calls")):
                calls[cid] = _call_label(name, args)
                cmd = _shell_cmd(name, args)
                if cmd:
                    yield "cmd", cmd
        elif role == "tool":
            label = calls.get(params.get("tool_call_id"))
            if not label and isinstance(meta.get("function"), dict):
                fn = meta["function"]
                label = _call_label(fn.get("name"), _codewhale_args(fn.get("arguments")))
            turn = tool_turn(label or "tool", _codewhale_deepcode_tool_output(msg.get("content")))
            if turn:
                yield turn
        # system: prompt, environment, skill bodies, compaction summaries (meta.isSummary)


def _codewhale_deepcode_index_entry(key):
    index = _codewhale_load_json(Path(key).parent / "sessions-index.json") or {}
    sid = Path(key).stem
    for entry in index.get("entries") or []:
        if isinstance(entry, dict) and entry.get("id") == sid:
            return index, entry
    return index, {}


_codewhale_ROOT_PATH_RE = re.compile(r'"root path":\s*"((?:[^"\\]|\\.)*)"')


@_codewhale_safe_str
def deepcode_project(key):
    index, _ = _codewhale_deepcode_index_entry(key)
    if isinstance(index.get("originalPath"), str) and index["originalPath"]:
        return index["originalPath"]
    for msg in _codewhale_jsonl(key):
        if msg.get("role") == "system":
            m = _codewhale_ROOT_PATH_RE.search(_text_of(msg.get("content")) or "")
            if m:
                try:
                    return json.loads(f'"{m.group(1)}"')
                except Exception:
                    return m.group(1)
        elif msg.get("role") == "user":
            break
    return Path(key).parent.name


@_codewhale_safe_str
def deepcode_title(key):
    _, entry = _codewhale_deepcode_index_entry(key)
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


# ── Hermes Agent (hermes) ────────────────────────────────────────────────────
# Hermes Agent (NousResearch) ─ $HERMES_HOME/state.db  (default ~/.hermes/state.db)
#
# One SQLite DB holds every session (CLI, gateway: telegram/slack/discord/…, cron, subagents):
#   sessions(id, source, cwd, git_repo_root, title, started_at, ended_at, …)
#   messages(id, session_id, role user|assistant|tool, content, tool_calls JSON, tool_name,
#            tool_call_id, timestamp, active, compacted, [display_kind, _compressed_summary] …)
# List/dict content is stored as "\x00json:" + json. Thinking lives in reasoning* columns (skipped).
# Named profiles keep their own DB: <hermes root>/profiles/<name>/state.db.

def _hermes_hermes_home():
    return _env_path("HERMES_HOME") or Path.home() / ".hermes"


def hermes_roots():
    dbs, seen = [], set()
    for home in (_hermes_hermes_home(), Path.home() / ".hermes"):
        profiles = home / "profiles"
        candidates = [home / "state.db"] + (sorted(profiles.glob("*/state.db")) if profiles.is_dir() else [])
        for db in candidates:
            if str(db) not in seen:
                seen.add(str(db))
                dbs.append(db)
    return dbs


def hermes_list():
    logs = []
    for db in hermes_roots():
        if not db.is_file():
            continue
        try:
            conn = _ro_connect(db)
            rows = conn.execute(
                "SELECT s.id, COALESCE(MAX(m.timestamp), s.ended_at, s.started_at), COUNT(m.id) "
                "FROM sessions s JOIN messages m ON m.session_id = s.id GROUP BY s.id").fetchall()
            conn.close()
        except sqlite3.Error:
            continue
        for sid, last, count in rows:
            logs.append((f"{db}#{sid}", float(last or 0), int(count or 0), "hermes"))
    return logs


def _hermes_split(key):
    db, _, sid = str(key).rpartition("#")
    return db, sid


def _hermes_decode(content):
    if isinstance(content, str) and content.startswith("\x00json:"):
        try:
            return _text_of(json.loads(content[len("\x00json:"):]))
        except Exception:
            return content
    return content if isinstance(content, str) else ""


_hermes_COMPACTION = ("[CONTEXT COMPACTION", "[CONTEXT SUMMARY]:")
_hermes_INJECTED = ("[System note:", "[System:", "[SYSTEM:", "[IMPORTANT:", "[Note:", "[Runtime note:") + _hermes_COMPACTION
_hermes_SKILL_PREFIX = "[IMPORTANT: The user has invoked the "


def _hermes_user_text(text):
    """What the human typed: strip Hermes' bracketed notes, memory fences and skill scaffolding."""
    text = (text or "").strip()
    if text.startswith(_hermes_COMPACTION):
        return ""
    if text.startswith(_hermes_SKILL_PREFIX):  # mirrors agent/skill_commands.extract_user_instruction_from_skill_message
        if " skill bundle," in text:
            i = text.find("\nUser instruction: ")
            text = text[i + 19:].split("\n\n[Loaded as part of the ")[0] if i >= 0 else ""
        else:
            marker = "The user has provided the following instruction alongside the skill invocation: "
            i = text.rfind(marker)
            text = text[i + len(marker):].split("\n\n[Runtime note:")[0] if i >= 0 else ""
    text = re.sub(r"<memory-context>.*?</memory-context>", "", text, flags=re.S).strip()
    while text.startswith(_hermes_INJECTED):
        end = text.find("]\n\n")
        text = "" if end < 0 else text[end + 3:].lstrip()
    for tail in ("\n\n[Note: Some earlier conversation turns", "\n\n[Runtime note:"):
        text = text.split(tail)[0]
    return text.strip()


def hermes_iter(key):
    db, sid = _hermes_split(key)
    try:
        conn = _ro_connect(db)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(messages)")}
        source = (conn.execute("SELECT source FROM sessions WHERE id = ?", (sid,)).fetchone() or [""])[0]
        extra = [c for c in ("display_kind", "_compressed_summary") if c in cols]
        where = " AND (active = 1 OR compacted = 1)" if {"active", "compacted"} <= cols else ""
        rows = conn.execute(
            "SELECT role, content, tool_calls, tool_name, tool_call_id"
            + "".join(f", {c}" for c in extra)
            + f" FROM messages WHERE session_id = ?{where} ORDER BY id", (sid,)).fetchall()
        conn.close()
    except sqlite3.Error:
        return
    calls = {}
    for row in rows:
        role, content, tool_calls, tool_name, call_id = row[:5]
        flags = dict(zip(extra, row[5:]))
        if flags.get("display_kind") == "hidden" or flags.get("_compressed_summary"):
            continue  # model-facing scaffolding / compaction summary
        text = _hermes_decode(content)
        if role == "user":
            text = "" if source == "subagent" else _hermes_user_text(text)
            if text:
                yield "user", text
        elif role == "assistant":
            if text.strip() and not text.lstrip().startswith(_hermes_COMPACTION):
                yield "assistant", text
            try:
                parsed = json.loads(tool_calls) if tool_calls else []
            except Exception:
                parsed = []
            for call in parsed if isinstance(parsed, list) else []:
                fn = (call or {}).get("function") or {}
                args = fn.get("arguments")
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except Exception:
                        pass
                label = _call_label(fn.get("name"), args)
                for cid in (call.get("id"), call.get("call_id")):
                    if cid:
                        calls[cid] = label
                cmd = _shell_cmd(fn.get("name"), args)
                if cmd:
                    yield "cmd", cmd
        elif role == "tool":
            turn = tool_turn(calls.get(call_id) or tool_name or "tool", text)
            if turn:
                yield turn


def _hermes_session_row(key, column):
    db, sid = _hermes_split(key)
    try:
        conn = _ro_connect(db)
        row = conn.execute(f"SELECT {column}, source FROM sessions WHERE id = ?", (sid,)).fetchone()
        conn.close()
        return row
    except sqlite3.Error:
        return None


def hermes_project(key):
    row = _hermes_session_row(key, "COALESCE(NULLIF(cwd, ''), git_repo_root, '')")
    return (row[0] or "") if row else ""


def hermes_title(key):
    row = _hermes_session_row(key, "title")
    if not row or not row[0]:
        return ""
    title, source = row
    return title if source in (None, "", "cli") else f"[{source}] {title}"


def _hermes_sessions_yaml_block(path):
    """Line-based read of the top-level `sessions:` mapping in config.yaml (stdlib has no YAML)."""
    out, inside = {}, False
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    for line in lines:
        if re.match(r"^sessions:\s*(#.*)?$", line):
            inside = True
            continue
        if inside:
            if line and not line[0].isspace() and not line.lstrip().startswith("#"):
                break
            m = re.match(r"^\s+(auto_prune|retention_days):\s*([^#\s]+)", line)
            if m:
                out[m.group(1)] = m.group(2).strip("'\"")
    return out


def hermes_retention():
    path = _hermes_hermes_home() / "config.yaml"
    block = _hermes_sessions_yaml_block(path)
    try:
        days = int(block.get("retention_days", 90))
    except ValueError:
        days = 90
    current = block.get("auto_prune")
    return {
        "settings_path": str(path),
        "key_path": "sessions.auto_prune",
        "never_delete_value": False,
        "default_days": days,
        "note": ("YAML, not JSON (stdlib cannot round-trip it). Since release v2026.9.7 Hermes defaults "
                 "sessions.auto_prune: true (hermes_cli/config_defaults.py) and deletes ENDED sessions inactive "
                 "for sessions.retention_days (90) from state.db at CLI/gateway/cron startup, at most once per "
                 "sessions.min_interval_hours (24); v2026.8.31 and older (this Mac: v0.17.0 / 2026.6.19) "
                 "defaulted it to false. Safe fix: `hermes config set sessions.auto_prune false`, or append a "
                 "top-level 'sessions:' block with 'auto_prune: false' when the file has none. Each profile "
                 "(<root>/profiles/<name>/config.yaml) has its own setting. "
                 f"Currently: auto_prune={current if current is not None else 'unset (version default)'}."),
    }


# ── OpenHands (openhands) ────────────────────────────────────────────────────
# OpenHands CLI (V1 / software-agent-sdk) ─ $OPENHANDS_CONVERSATIONS_DIR
# (default $OPENHANDS_PERSISTENCE_DIR/conversations = ~/.openhands/conversations)
#
#   <conv hex>/base_state.json                        agent config + workspace.working_dir
#   <conv hex>/events/event-NNNNN-<uuid>.json         one JSON object per event, "kind" discriminator
#   <conv hex>/subagents/<hex>/{base_state.json,events/}  task/delegate sub-conversations
#
# Kinds: SystemPromptEvent (skip) · MessageEvent (source user|agent|environment; llm_message.content parts;
# extended_content = injected agent context, skipped) · ActionEvent (tool_name, action{…}, thought = visible text,
# reasoning_content skipped; FinishAction.message = final reply) · ObservationEvent (observation.content parts) ·
# UserRejectObservation · AgentErrorEvent · Condensation*/ConversationStateUpdate/Pause/Token… (skip).
# The key is the conversation directory.

def openhands_roots():
    explicit = _env_path("OPENHANDS_CONVERSATIONS_DIR")
    if explicit:
        return [explicit]
    return [(_env_path("OPENHANDS_PERSISTENCE_DIR") or Path.home() / ".openhands") / "conversations"]


def _openhands_event_files(conv):
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
            files = _openhands_event_files(conv)
            if not files:
                continue
            try:
                mtime = max([events.stat().st_mtime] + [f.stat().st_mtime for f in files[-3:]])
            except OSError:
                continue
            logs.append((str(conv), mtime, len(files), "openhands"))
    return logs


# Messages the SDK itself sends with source="user" (response_dispatch nudge, critic refinement).
_openhands_NUDGES = ("Your last response did not include a function call or a message",
           "The task appears incomplete (iteration ")


def _openhands_parts_text(parts):
    return _text_of(parts if isinstance(parts, list) else [parts] if parts else [])


def _openhands_args(event):
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
    for path in _openhands_event_files(key):
        try:
            ev = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        kind = ev.get("kind")
        if kind == "MessageEvent":
            msg = ev.get("llm_message") or {}
            text = _openhands_parts_text(msg.get("content"))  # extended_content (skills/hook context) deliberately ignored
            if not text.strip():
                continue
            if ev.get("source") == "user" and msg.get("role") == "user":
                if not sub and not ev.get("sender") and not text.startswith(_openhands_NUDGES):
                    yield "user", text
            elif ev.get("source") == "agent" and msg.get("role") == "assistant":
                yield "assistant", text
        elif kind == "ActionEvent":
            thought = _openhands_parts_text(ev.get("thought"))
            if thought.strip():
                yield "assistant", thought
            name, args = ev.get("tool_name"), _openhands_args(ev)
            action = ev.get("action") or {}
            if action.get("kind") == "FinishAction" or name == "finish":
                if isinstance(args, dict) and str(args.get("message") or "").strip():
                    yield "assistant", str(args["message"])
                continue
            if name == "think":
                continue  # the think tool is reasoning
            label_args = args
            if isinstance(args, dict) and args.get("path") and not _is_shell_tool(name):
                label_args = {"path": f"{args.get('command', '')} {args['path']}".strip()}
            calls[ev.get("tool_call_id")] = _call_label(name, label_args)
            cmd = _shell_cmd(name, args)
            if cmd:
                yield "cmd", cmd
        elif kind in ("ObservationEvent", "UserRejectObservation", "AgentErrorEvent"):
            if ev.get("tool_name") in ("finish", "think"):
                continue
            obs = ev.get("observation") or {}
            if kind == "ObservationEvent":
                output = _openhands_parts_text(obs.get("content"))
                code = obs.get("exit_code")
                if obs.get("is_error") or code not in (None, 0, -1):
                    output = f"exit {code}\n{output}" if code not in (None, 0) else "error\n" + output
            elif kind == "UserRejectObservation":
                output = "rejected: " + str(ev.get("rejection_reason") or "")
            else:
                output = "error\n" + str(ev.get("error") or "")
            turn = tool_turn(calls.get(ev.get("tool_call_id"), ev.get("tool_name") or "tool"), output)
            if turn:
                yield turn


def _openhands_base_state(key):
    try:
        with open(Path(key) / "base_state.json", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def openhands_project(key):
    ws = _openhands_base_state(key).get("workspace") or {}
    if isinstance(ws.get("working_dir"), str):
        return ws["working_dir"]
    for path in _openhands_event_files(key):  # fall back to the first terminal observation's cwd
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
    tags = _openhands_base_state(key).get("tags") or {}
    return str(tags.get("title") or "") if isinstance(tags, dict) else ""


# ── Mistral Vibe (vibe) ──────────────────────────────────────────────────────
# Mistral Vibe ─ <session_logging.save_dir>/<prefix>_<YYYYmmdd_HHMMSS UTC>_<id8>/{meta.json,messages.jsonl}
# (default save_dir = $VIBE_HOME/logs/session = ~/.vibe/logs/session; prefix "session")
#
# messages.jsonl: one LLMMessage per line (system prompt is NOT written; it lives in meta.json):
#   {"role": "user"|"assistant"|"tool", "content": str, "injected": bool, "input_text"?, "reasoning_content"?,
#    "tool_calls"?: [{"id","function":{"name","arguments": json-str}}], "name"?, "tool_call_id"?,
#    "tool_result"?, "manual_shell"?: {"command","cwd","stdout","stderr","output_text","exit_code",…},
#    "context_boundary"?: "compaction"}
# meta.json: session_id, title, environment.working_directory, origin_directory, config, system_prompt, stats…

def _vibe_vibe_home():
    return _env_path("VIBE_HOME") or Path.home() / ".vibe"


def vibe_roots():
    roots = []
    try:
        import tomllib
        cfg = tomllib.loads((_vibe_vibe_home() / "config.toml").read_text(encoding="utf-8"))
        save_dir = (cfg.get("session_logging") or {}).get("save_dir")
        if isinstance(save_dir, str) and save_dir.strip():
            roots.append(Path(save_dir).expanduser())
    except Exception:
        pass
    default = _vibe_vibe_home() / "logs" / "session"
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
    return _file_logs(paths, "vibe")


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
                turn = tool_turn(f"!: {shell['command']}", (f"exit {code}\n" if code not in (None, 0) else "") + (output or ""))
                if turn:
                    yield turn
                continue
            if role == "user":
                if msg.get("injected") or msg.get("context_boundary"):
                    continue  # retries, hook output, compaction summaries, skill/file expansions
                text = msg.get("input_text") or _text_of(msg.get("content") or "")
                if text.strip():
                    yield "user", text
            elif role == "assistant":
                text = _text_of(msg.get("content") or "")
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
                    calls[call.get("id")] = _call_label(fn.get("name"), args)
                    cmd = _shell_cmd(fn.get("name"), args)
                    if cmd:
                        yield "cmd", cmd
            elif role == "tool":
                output = _text_of(msg.get("content") or "")
                result = (msg.get("tool_result") or {}).get("output") if isinstance(msg.get("tool_result"), dict) else None
                if isinstance(result, dict) and ("stdout" in result or "stderr" in result):
                    code = result.get("returncode", result.get("exit_code"))
                    output = (f"exit {code}\n" if code not in (None, 0) else "") + "\n".join(
                        str(result[k]) for k in ("stdout", "stderr") if result.get(k))
                elif not output.strip() and result:
                    output = result
                turn = tool_turn(calls.get(msg.get("tool_call_id"), msg.get("name") or "tool"), output)
                if turn:
                    yield turn


def _vibe_meta(key):
    try:
        with open(Path(key).parent / "meta.json", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def vibe_project(key):
    meta = _vibe_meta(key)
    env = meta.get("environment") if isinstance(meta.get("environment"), dict) else {}
    for value in (env.get("working_directory"), meta.get("origin_directory")):
        if isinstance(value, str) and value:
            return value
    return ""


def vibe_title(key):
    title = _vibe_meta(key).get("title")
    return title if isinstance(title, str) else ""


# ── Aider (aider) ────────────────────────────────────────────────────────────
# Aider (PyPI aider-chat) ─ <project>/.aider.chat.history.md, one navcom session per
# "# aider chat started at <ts>" header, keyed "<history file>#<n>" (n = 1-based header ordinal).
#
# Markdown written by aider/io.py (verified against aider 0.59 – 0.86.2):
#   #### <line>␠␠          user input (every line of a multi-line message is prefixed; lines end "  ")
#   > <line>␠␠             tool_output / tool_error / confirm_ask notes ("Running <cmd>", "Applied edit to x")
#   <plain markdown>        assistant reply (ai_output: stripped content between blank lines)
# Shell-command stdout is NOT written to the file (aider only prints it), so `tool` turns are aider's
# own notes (edits applied, errors, "Added N lines of output to the chat").
#
# No global index: files live in each git root / launch dir. Spotlight skips dotfiles, so discovery is a
# bounded walk of ~ (cached for AIDER_RESCAN_SECONDS in navcom's index dir) plus $AIDER_CHAT_HISTORY_FILE.

_aider_AIDER_HISTORY_NAME = ".aider.chat.history.md"
_aider_AIDER_SCAN_DEPTH = 5            # ~1s on a dev Mac; finds 141/144 histories (depth 6: 2.3s, 144)
_aider_AIDER_RESCAN_SECONDS = 3600
_aider_AIDER_SKIP_DIRS = {"node_modules", "Library", "Applications", "Pictures", "Movies", "Music", "venv",
                    "__pycache__", "site-packages", "dist", "build", "target"}
_aider_AIDER_HDR_RE = re.compile(rb"^# aider chat started at (\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)[ \t]*\r?$", re.M)
_aider_AIDER_NOTE_SKIP_RE = re.compile(r"^(Tokens: .* sent|Cost: \$|.*\(Y\)es/\(N\)o.*:|Add the output to the chat\?)", re.I)
_aider_AIDER_CHAT_CMD_RE = re.compile(r"^/(ask|code|architect|context)\s+(.+)$", re.S)
_aider_AIDER_SHELL_RE = re.compile(r"^(?:/run|/test|!)\s*(.+)$", re.S)


def aider_roots():
    roots = [Path.home()]
    explicit = _env_path("AIDER_CHAT_HISTORY_FILE")
    if explicit:
        roots.insert(0, explicit)
    return roots


def _aider_aider_walk(root, depth):
    found = []
    root = str(root)
    base = root.rstrip(os.sep).count(os.sep)
    for folder, dirs, files in os.walk(root):
        level = folder.count(os.sep) - base
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in _aider_AIDER_SKIP_DIRS] if level < depth else []
        found.extend(os.path.join(folder, f) for f in files if f.endswith(_aider_AIDER_HISTORY_NAME))
    return found


def _aider_aider_cache_path():
    return default_index_path().parent / "navcom-aider-paths.json"


def _aider_aider_history_files():
    """Every aider chat history under ~ (bounded walk, cached) plus $AIDER_CHAT_HISTORY_FILE."""
    home, cache_path, paths = str(Path.home()), _aider_aider_cache_path(), None
    try:
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
        if cache.get("home") == home and time.time() - cache.get("scanned_at", 0) < _aider_AIDER_RESCAN_SECONDS:
            paths = cache.get("paths") or []
    except Exception:
        pass
    if paths is None:
        paths = sorted(_aider_aider_walk(home, _aider_AIDER_SCAN_DEPTH))
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = cache_path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"home": home, "scanned_at": time.time(), "paths": paths}), encoding="utf-8")
            os.chmod(tmp, 0o600)
            tmp.replace(cache_path)
        except OSError:
            pass
    explicit = _env_path("AIDER_CHAT_HISTORY_FILE")
    if explicit and str(explicit) not in paths:
        paths = [str(explicit)] + list(paths)
    return [Path(p) for p in paths]


def _aider_aider_sections(data):
    """[(n, start, end, header_ts_or_None)] — n=0 is text before the first header (old/odd files)."""
    heads = list(_aider_AIDER_HDR_RE.finditer(data))
    sections = []
    first = heads[0].start() if heads else len(data)
    if data[:first].strip():
        sections.append((0, 0, first, None))
    for i, m in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(data)
        sections.append((i + 1, m.start(), end, m.group(1).decode()))
    return sections


def _aider_aider_epoch(ts):
    try:
        return time.mktime(time.strptime(ts, "%Y-%m-%d %H:%M:%S"))  # aider writes local time
    except Exception:
        return 0.0


def aider_list():
    """One navcom session per `# aider chat started at` header. The per-file split is cached by
    (mtime, size), so a search re-reads only history files that changed since the last run."""
    cache_path = _aider_aider_cache_path().with_name("navcom-aider-sections.json")
    try:
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception:
        cache = {}
    logs, fresh, dirty = [], {}, False
    for path in _aider_aider_history_files():
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
            sections, rows = _aider_aider_sections(data), []
            for i, (n, start, end, _ts) in enumerate(sections):
                if b"\n#### " not in data[start:end]:
                    continue  # aider started and quit without a prompt
                nxt = sections[i + 1][3] if i + 1 < len(sections) else None
                mtime = (_aider_aider_epoch(nxt) or stat.st_mtime) if nxt else stat.st_mtime
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


def _aider_aider_split_key(key):
    path, _, n = str(key).rpartition("#")
    if not path or not n.isdigit():
        return str(key), None
    return path, int(n)


def _aider_aider_section_text(key):
    path, n = _aider_aider_split_key(key)
    try:
        data = Path(path).read_bytes()
    except OSError:
        return ""
    for num, start, end, _ts in _aider_aider_sections(data):
        if n is None or num == n:
            return data[start:end].decode("utf-8", errors="replace")
    return ""


def _aider_aider_blocks(text):
    """('hdr'|'user'|'note'|'text', [lines]) groups in file order."""
    blocks = []
    for line in text.splitlines():
        if _aider_AIDER_HDR_RE.match(line.encode("utf-8", "replace")):
            kind, body = "hdr", line
        elif line.startswith("#### ") and line.endswith("  ") or line.rstrip() == "####":
            kind, body = "user", line[5:].rstrip()
        elif (line.startswith("> ") or line.rstrip() == ">") and line.endswith("  ") or line == ">  ":
            kind, body = "note", line[2:].rstrip()
        elif line.endswith("  ") and _aider_AIDER_NOTE_SKIP_RE.match(line.strip()):
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
    for kind, lines in _aider_aider_blocks(_aider_aider_section_text(key)):
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
            m = _aider_AIDER_CHAT_CMD_RE.match(body)
            if m:
                echo = m.group(2).strip()
            m = _aider_AIDER_SHELL_RE.match(body)
            if m and m.group(1).strip():
                cmd = m.group(1).strip()
                yield "cmd", cmd
                cmd_label = _call_label("Bash", {"command": cmd})
        elif kind == "text":
            if seen_user:
                last_reply = body
                yield "assistant", body
        elif kind == "note":
            if not seen_user:
                continue  # launch banner: argv, version, model, repo-map
            notes = []

            def flush():
                turn = tool_turn(cmd_label or "aider", "\n".join(notes))
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
                    cmd_label = _call_label("Bash", {"command": cmd})
                elif line.startswith(("Run shell command", "Run shell commands")):
                    # the commands echoed just before this prompt are a proposal from the reply, not output
                    proposed = {ln.strip() for ln in last_reply.splitlines()}
                    while notes and notes[-1] in proposed:
                        notes.pop()
                elif line and not _aider_AIDER_NOTE_SKIP_RE.match(line):
                    notes.append(line)
            # the command echoed before "Run shell command?" is a proposal, not output
            if notes:
                turn = flush()
                if turn:
                    yield turn


def aider_project(key):
    path, _ = _aider_aider_split_key(key)
    return str(Path(path).parent)


def aider_title(key):
    return ""  # aider stores no titles


# ── Antigravity CLI (agy) ────────────────────────────────────────────────────
# Antigravity CLI (`agy`, Google, closed-source Go; verified on agy 1.2.14)
# ─ ~/.gemini/antigravity-cli/brain/<conversation id>/.system_generated/logs/transcript_full.jsonl
#
# The primary store is SQLite-per-conversation (conversations/<id>.db, protobuf step blobs); agy also
# writes a readable JSONL "trajectory log" per conversation (documented in its own built-in skill):
#   transcript.jsonl       compact; long fields cut, listed in "truncated_fields"; tool_call args re-encoded
#   transcript_full.jsonl  untruncated  ← we index this one
#   chunks/transcript_full/NNNNNNNN.jsonl  the same steps in chunks (merged by step_index as a safety net)
# One JSON object per step: {step_index, source: USER_EXPLICIT|USER_IMPLICIT|MODEL|SYSTEM,
# type: USER_INPUT|PLANNER_RESPONSE|GENERIC|RUN_COMMAND|VIEW_FILE|ERROR_MESSAGE|..., status: DONE|ERROR,
# created_at, content, thinking, tool_calls[{name, args}], media, truncated_fields}.
# Tool results are the steps that follow a PLANNER_RESPONSE, in call order (no call id is logged).
# Title/workspace live in <app data dir>/conversation_summaries.db (table conversation_summaries).
# The Antigravity IDE (app data dir "antigravity") uses the same layout; older IDE builds only kept
# encrypted .pb conversations, which are not readable.

_agy_AGY_APP_DIRS = ("antigravity-cli", "antigravity")
_agy_AGY_SKIP_TYPES = {"SYSTEM_MESSAGE", "EPHEMERAL_MESSAGE", "CONVERSATION_HISTORY", "CHECKPOINT", "KNOWLEDGE_ARTIFACTS",
                   "KI_INSERTION", "DIRECTORY_RULES", "MEMORY", "RETRIEVE_MEMORY", "SUGGESTED_RESPONSES",
                   "BRAIN_UPDATE", "PLAN_INPUT", "TASK_BOUNDARY", "DUMMY", "UNSPECIFIED", "FINISH"}
_agy_AGY_REQUEST_RE = re.compile(r"<USER_REQUEST>\s*(.*?)\s*</USER_REQUEST>", re.S)
_agy_AGY_TAG_BLOCK_RE = re.compile(r"<([A-Z][A-Z0-9_]+)>.*?</\1>", re.S)
_agy_AGY_SHELL_TOOLS = ("run_command", "shell_exec", "send_command_input")


def agy_gemini_dir():
    return Path.home() / ".gemini"  # agy has a --gemini_dir flag but no env override


def agy_roots():
    return [agy_gemini_dir() / app / "brain" for app in _agy_AGY_APP_DIRS]


def _agy_agy_logs_dir(key):
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


def _agy_agy_steps(key):
    """Steps by step_index: chunks first, then the full log, then the compact log only for gaps."""
    logs_dir = _agy_agy_logs_dir(key)
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


def _agy_agy_user_text(content):
    if not isinstance(content, str):
        return ""
    found = _agy_AGY_REQUEST_RE.findall(content)
    if found:
        return "\n".join(t for t in found if t.strip()).strip()
    return _agy_AGY_TAG_BLOCK_RE.sub("", content).strip()  # ADDITIONAL_METADATA, USER_SETTINGS_CHANGE, ...


def _agy_agy_args(args):
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


def _agy_agy_shell(name, args):
    if (name or "").lower() not in _agy_AGY_SHELL_TOOLS:
        return None
    for field in ("CommandLine", "commandLine", "command", "Command", "cmd", "Input"):
        value = args.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _agy_agy_label(name, args):
    cmd = _agy_agy_shell(name, args)
    if cmd:
        return f"{name}: {cmd[:160]}"
    for field in ("AbsolutePath", "TargetFile", "File", "Path", "SearchPath", "Query", "Url", "DirectoryPath"):
        value = args.get(field)
        if isinstance(value, str) and value.strip():
            return f"{name}: {value.strip()[:160]}"
    return _call_label(name, args)


def agy_iter(key):
    pending, last_error = [], None
    for step in _agy_agy_steps(key):
        kind, source = step.get("type") or "", step.get("source") or ""
        content = step.get("content")
        if kind == "USER_INPUT":
            if source == "USER_EXPLICIT":
                text = _agy_agy_user_text(content)
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
                args = _agy_agy_args(call.get("args") or call.get("arguments"))
                pending.append(_agy_agy_label(call.get("name"), args))
                cmd = _agy_agy_shell(call.get("name"), args)
                if cmd:
                    yield "cmd", cmd
            continue
        if kind in _agy_AGY_SKIP_TYPES or source == "USER_IMPLICIT":
            continue
        is_error = step.get("status") == "ERROR" or kind == "ERROR_MESSAGE"
        if pending:
            label = pending.pop(0)
        elif is_error:
            label = "error"
        else:
            continue  # system-sourced chatter with no originating call
        output = content if isinstance(content, str) else _text_of(content) if content else ""
        error = step.get("error") if isinstance(step.get("error"), str) else ""
        if is_error or error:
            # retried API failures arrive as "API error (attempt N): ..." — keep one per streak
            norm = re.sub(r"\(attempt \d+\)", "", error)
            if label == "error" and norm == last_error:
                continue
            last_error = norm if label == "error" else None
            output = "\n".join(t for t in ("error", error, output) if t)
        turn = tool_turn(label, output)
        if turn:
            yield turn


def _agy_agy_summary(key):
    logs_dir = _agy_agy_logs_dir(key)
    conv_id = logs_dir.parent.parent.name
    app_dir = logs_dir.parent.parent.parent.parent
    db = app_dir / "conversation_summaries.db"
    if db.is_file():
        try:
            conn = _ro_connect(db)
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
        uris = json.loads(_agy_agy_summary(key).get("uris") or "[]")
    except Exception:
        uris = []
    for uri in uris if isinstance(uris, list) else []:
        if isinstance(uri, str) and uri.startswith("file://"):
            return unquote(urlparse(uri).path)
    for step in _agy_agy_steps(key):  # fallback: the Cwd of the first command
        for call in step.get("tool_calls") or [] if isinstance(step.get("tool_calls"), list) else []:
            cwd = _agy_agy_args((call or {}).get("args")).get("Cwd")
            if isinstance(cwd, str) and cwd.startswith("/"):
                return cwd
    return ""


def agy_title(key):
    return (_agy_agy_summary(key).get("title") or "").strip()


# ── Factory Droid (droid) ────────────────────────────────────────────────────
# Factory Droid CLI ─ $FACTORY_HOME_OVERRIDE|~ /.factory/sessions/<-cwd-slug>/<uuid>.jsonl
#
# Line 1 is {"type":"session_start", id, title, cwd, owner, version:2, ...}; then
# {"type":"message", id, parentId, timestamp, seq, message:{role, content[...]}} where content is
# Anthropic-style blocks: text | thinking | redacted_thinking | image | document |
# tool_use{id,name,input} | tool_result{tool_use_id,content,is_error}. Tool results ride in
# role:"user" messages. Injected context: message ids starting "context-" (the per-session
# <system-reminder> tool catalog / env block) or "__internal__system-reminder__", visibility
# "llm_only" / hiddenFromUserViews, role "system", hook messages. Other line types
# (agent_turn_outcome, todo_state, compaction_state, ...) carry no typed text.
# The shell tool is "Execute" {command, summary, riskLevel}.

_droid_DROID_INJECTED_IDS = ("context-", "__internal__system-reminder__")
_droid_DROID_REMINDER_RE = re.compile(r"<(system-reminder|system-notification)>[\s\S]*?</\1>", re.I)


def droid_roots():
    home = _env_path("FACTORY_HOME_OVERRIDE") or Path.home()
    return [home / ".factory" / "sessions"]


def droid_list():
    paths = []
    for root in droid_roots():
        if root.is_dir():
            paths.extend(root.glob("*.jsonl"))       # flat / legacy layout
            paths.extend(root.glob("*/*.jsonl"))     # <cwd-slug>/<uuid>.jsonl
    return _file_logs(sorted(set(paths)), "droid")


def _droid_droid_lines(key):
    try:
        handle = open(key, "r", encoding="utf-8", errors="replace")
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


def _droid_droid_header(key):
    for obj in _droid_droid_lines(key):
        return obj if obj.get("type") == "session_start" else {}
    return {}


def _droid_droid_injected(obj, msg):
    if str(obj.get("id") or "").startswith(_droid_DROID_INJECTED_IDS):
        return True
    if msg.get("role") == "system" or msg.get("hookEventName"):
        return True
    return msg.get("visibility") == "llm_only" or msg.get("hiddenFromUserViews") is True


def droid_iter(key):
    calls = {}
    for obj in _droid_droid_lines(key):
        if obj.get("type") != "message":
            continue
        msg = obj.get("message") or {}
        role, content = msg.get("role"), msg.get("content")
        if isinstance(content, str):
            content = [{"type": "text", "text": content}]
        if not isinstance(content, list):
            continue
        injected = _droid_droid_injected(obj, msg)
        for block in content:
            if not isinstance(block, dict):
                continue
            kind = block.get("type")
            if kind == "text" and not injected and role in ("user", "assistant"):
                text = block.get("text") or ""
                if role == "user":
                    text = _droid_DROID_REMINDER_RE.sub("", text).strip()
                if text.strip():
                    yield role, text
            elif kind == "tool_use":
                args = block.get("input")
                calls[block.get("id")] = _call_label(block.get("name"), args)
                cmd = _shell_cmd(block.get("name"), args)
                if cmd is None and block.get("name") == "Execute" and isinstance(args, dict):
                    cmd = args.get("command")
                if cmd:
                    yield "cmd", cmd
            elif kind == "tool_result":
                output = block.get("content")
                if block.get("is_error") or block.get("isError"):
                    output = "error\n" + (_text_of(output) if isinstance(output, list) else str(output or ""))
                turn = tool_turn(calls.get(block.get("tool_use_id") or block.get("toolUseId"), "tool"), output)
                if turn:
                    yield turn


def droid_project(key):
    cwd = _droid_droid_header(key).get("cwd")
    return cwd if isinstance(cwd, str) else ""


def droid_title(key):
    title = _droid_droid_header(key).get("title")
    return title if isinstance(title, str) else ""


# ── Cursor CLI (cursor) ──────────────────────────────────────────────────────
# Cursor CLI (cursor-agent / `agent`) — two on-disk forms of the same chat.
#
# 1. Primary store (full fidelity, incl. tool outputs):
#    $CURSOR_CONFIG_DIR | $XDG_CONFIG_HOME/cursor | ~/.cursor  /chats/<md5(cwd)>/<agentId>/store.db
#    (and .../acp-sessions/<id>/store.db for `agent acp`).
#    SQLite: meta(key,value) where key "0" = hex(JSON{agentId, latestRootBlobId, name, createdAt,
#    mode, lastUsedModel, ...}); blobs(id TEXT hex sha256, data BLOB). The root blob is a protobuf
#    ConversationStateStructure: field 1 root_prompt_messages_json (repeated 32-byte blob ids),
#    field 9 previous_workspace_uris, field 13 summary_archives (blob ids of SummaryArchive protos,
#    whose field 1 = summarized_messages blob ids). Each message blob is JSON of a Vercel AI SDK
#    message {role: system|user|assistant|tool, content: str | [text|reasoning|redacted-reasoning|
#    image|file|tool-call{toolCallId,toolName,args}|tool-result{toolCallId,toolName,result}]}.
#    User text wraps the typed prompt in <user_query>, with injected <user_info>, <rules>,
#    <system_reminder>, ... blocks around it.
# 2. Readable transcript (no tool outputs; thinking is merged into the assistant text block):
#    $CURSOR_DATA_DIR | ~/.cursor  /projects/<slug(cwd)>/agent-transcripts/<id>/<id>.jsonl
#    lines {"role":"user"|"assistant","message":{"content":[{"type":"text"},{"type":"tool_use",
#    "name","input"}]}} plus {"type":"turn_ended"} / {"type":"metadata"}; subagents under
#    <parent>/subagents/<id>.jsonl; legacy flat <id>.jsonl / <id>.txt ("user:" / "assistant:" blocks,
#    "[Thinking]", "[Tool call] Name" + indented "key: value", "[Tool result] Name").
#
# A session with a store.db is listed once, as "<store.db>#<agentId>"; transcripts are listed only
# for ids without a store (e.g. written by the Cursor IDE, or a store that was removed).

# Tags Cursor's own transcript writer strips from user text as injected context.
_cursor_CURSOR_INJECTED_TAGS = (
    "user_info", "project_layout", "rules", "always_applied_workspace_rules", "agent_requestable_workspace_rules",
    "user_rules", "agent_skills", "available_skills", "cloud_instructions", "cloud_task_instructions",
    "open_and_recently_viewed_files", "system_reminder", "system-reminder", "instructions_update",
    "mcp_instructions", "mcp_file_system", "mcp_file_system_servers", "git_status", "agent_transcripts",
    "cursor_rules_context", "attached_files", "system_notification", "task_notification", "agent_notification",
    "timestamp")
_cursor_CURSOR_TAG_RE = re.compile(r"<(%s)(?:\s[^>]*)?>[\s\S]*?</\1>" % "|".join(re.escape(t) for t in _cursor_CURSOR_INJECTED_TAGS),
                            re.I)
_cursor_CURSOR_QUERY_RE = re.compile(r"<user_query>([\s\S]*?)</user_query>")
_cursor_CURSOR_THINK_RE = re.compile(r"<(think|thinking)>[\s\S]*?</\1>", re.I)
_cursor_CURSOR_WS_RE = re.compile(r"Workspace Path:\s*(/[^\n<]+)")


def _cursor_cursor_config_dir():
    explicit = _cursor_env_path_nonblank("CURSOR_CONFIG_DIR")
    if explicit:
        return explicit
    xdg = _cursor_env_path_nonblank("XDG_CONFIG_HOME")
    return xdg / "cursor" if xdg else Path.home() / ".cursor"


def _cursor_cursor_data_dir():
    return _cursor_env_path_nonblank("CURSOR_DATA_DIR") or Path.home() / ".cursor"


def _cursor_env_path_nonblank(name):
    value = (os.environ.get(name) or "").strip()
    return Path(value).expanduser() if value else None


def cursor_roots():
    config = _cursor_cursor_config_dir()
    return [config / "chats", config / "acp-sessions", _cursor_cursor_data_dir() / "projects"]


def _cursor_cursor_stores():
    chats, acp, _ = cursor_roots()
    stores = []
    for pattern_root, pattern in ((chats, "*/*/store.db"), (acp, "*/store.db")):
        try:
            if pattern_root.is_dir():
                stores.extend(pattern_root.glob(pattern))
        except OSError:
            pass
    return stores


def _cursor_cursor_transcripts():
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
    for db in _cursor_cursor_stores():
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
    rest = [p for stem, p in _cursor_cursor_transcripts().items() if stem not in store_ids]
    return logs + _file_logs(sorted(rest), "cursor")


# ── store.db ────────────────────────────────────────────────────────────────

def _cursor_pb_fields(data):
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


def _cursor_cursor_meta(con):
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


def _cursor_cursor_blob(con, blob_id):
    if isinstance(blob_id, (bytes, bytearray)):
        blob_id = bytes(blob_id).hex()
    try:
        row = con.execute("SELECT data FROM blobs WHERE id=?", (blob_id,)).fetchone()
    except sqlite3.Error:
        return None
    return bytes(row[0]) if row and row[0] is not None else None


def _cursor_cursor_root(con):
    meta = _cursor_cursor_meta(con)
    root_id = meta.get("latestRootBlobId")
    if isinstance(root_id, dict) and isinstance(root_id.get("hex"), str):
        root_id = root_id["hex"]
    if isinstance(root_id, list):
        root_id = bytes(root_id).hex()
    data = _cursor_cursor_blob(con, root_id) if isinstance(root_id, str) and root_id else None
    try:
        return meta, (_cursor_pb_fields(data) if data else [])
    except ValueError:
        return meta, []


def _cursor_cursor_store_messages(key):
    db = key.split("#", 1)[0]
    try:
        con = _ro_connect(db)
    except sqlite3.Error:
        return {}, [], []
    try:
        meta, root = _cursor_cursor_root(con)
        ids = []
        for field, wire, value in root:
            if field == 13 and wire == 2:  # summary_archives → SummaryArchive.summarized_messages
                archive = _cursor_cursor_blob(con, value) if len(value) == 32 else value
                try:
                    ids.extend(v for f, w, v in _cursor_pb_fields(archive or b"") if f == 1 and w == 2)
                except ValueError:
                    pass
        ids.extend(v for f, w, v in root if f == 1 and w == 2)
        messages = []
        for blob_id in ids:
            data = _cursor_cursor_blob(con, blob_id) if len(blob_id) == 32 else blob_id
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


def _cursor_cursor_user_text(text):
    queries = _cursor_CURSOR_QUERY_RE.findall(text or "")
    if queries:
        return "\n".join(q.strip() for q in queries if q.strip())
    return _cursor_CURSOR_TAG_RE.sub("", text or "").strip()


def _cursor_cursor_result_output(part):
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


def _cursor_cursor_args(args):
    if isinstance(args, str):
        try:
            return json.loads(args)
        except Exception:
            return args
    return args


def _cursor_cursor_store_turns(messages):
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
                text = _cursor_cursor_user_text(part.get("text"))
                if text:
                    yield "user", text
            elif kind == "text" and role == "assistant":
                text = _cursor_CURSOR_THINK_RE.sub("", part.get("text") or "").strip()
                if text:
                    yield "assistant", text
            elif kind == "tool-call":
                args = _cursor_cursor_args(part.get("args", part.get("input")))
                calls[part.get("toolCallId")] = _call_label(part.get("toolName"), args)
                cmd = _shell_cmd(part.get("toolName"), args)
                if cmd:
                    yield "cmd", cmd
            elif kind == "tool-result":
                label = calls.get(part.get("toolCallId")) or part.get("toolName") or "tool"
                output = _cursor_cursor_result_output(part)
                if part.get("isError") and isinstance(output, str):
                    output = "error\n" + output
                turn = tool_turn(label, output)
                if turn:
                    yield turn


# ── agent-transcripts ───────────────────────────────────────────────────────

def _cursor_cursor_jsonl_turns(path):
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
                    text = _cursor_cursor_user_text(text) if role == "user" else _cursor_CURSOR_THINK_RE.sub("", text).strip()
                    if text:
                        yield role, text
                elif part.get("type") == "tool_use":
                    cmd = _shell_cmd(part.get("name"), _cursor_cursor_args(part.get("input")))
                    if cmd:
                        yield "cmd", cmd


def _cursor_cursor_txt_args(lines):
    args = {}
    for line in lines:
        key, sep, value = line.strip().partition(": ")
        if not sep:
            key, sep, value = line.strip().partition("=")
        if sep and key:
            args[key.strip()] = value.strip()
    return args


def _cursor_cursor_txt_turns(path):
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").split("\n")
    except OSError:
        return
    role, buf, i = None, [], 0

    def flush():
        text = "\n".join(buf).strip()
        if role == "user":
            text = _cursor_cursor_user_text(text)
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
                cmd = _shell_cmd(marker[len("[Tool call] "):].strip(), _cursor_cursor_txt_args(body))
                if cmd:
                    yield "cmd", cmd
            elif marker.startswith("[Tool result]") and any(b.strip() for b in body):
                turn = tool_turn(marker[len("[Tool result]"):].strip() or "tool", "\n".join(body))
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
        _, messages, _ = _cursor_cursor_store_messages(key)
        turns = list(_cursor_cursor_store_turns(messages))
        if turns:
            yield from turns
            return
        transcript = _cursor_cursor_transcripts().get(key.rsplit("#", 1)[1])
        if not transcript:
            return
        key = str(transcript)
    if key.endswith(".txt"):
        yield from _cursor_cursor_txt_turns(key)
    else:
        yield from _cursor_cursor_jsonl_turns(key)


def _cursor_cursor_slug_project(path):
    parts = Path(path).parts
    if "agent-transcripts" in parts:
        slug = parts[parts.index("agent-transcripts") - 1]
        decoded = decode_encoded_dir("-" + slug)
        return decoded if decoded.startswith("/") and Path(decoded).is_dir() else ""
    return ""


def cursor_project(key):
    if "#" in key:
        _, messages, workspaces = _cursor_cursor_store_messages(key)
        for uri in workspaces:
            if uri.startswith("file://"):
                from urllib.parse import unquote
                return unquote(uri[len("file://"):])
            if uri.startswith("/"):
                return uri
        for msg in messages[:3]:
            text = msg.get("content") if isinstance(msg.get("content"), str) else _text_of(msg.get("content"))
            m = _cursor_CURSOR_WS_RE.search(text or "")
            if m:
                return m.group(1).strip()
        db = Path(key.split("#", 1)[0])
        if db.parent.parent.parent.name == "acp-sessions" or db.parent.parent.name == "acp-sessions":
            try:
                return json.loads((db.parent / "meta.json").read_text()).get("cwd") or ""
            except Exception:
                pass
        transcript = _cursor_cursor_transcripts().get(key.rsplit("#", 1)[1])
        if transcript:
            return _cursor_cursor_slug_project(transcript)
        # chats/<md5(cwd)>: confirm a candidate cwd from any transcript project folder
        digest = db.parent.parent.name
        for path in _cursor_cursor_transcripts().values():
            cand = _cursor_cursor_slug_project(path)
            if cand and hashlib.md5(cand.encode()).hexdigest() == digest:
                return cand
        return ""
    return _cursor_cursor_slug_project(key)


def cursor_title(key):
    if "#" not in key:
        return ""
    try:
        con = _ro_connect(key.split("#", 1)[0])
        try:
            name = _cursor_cursor_meta(con).get("name")
        finally:
            con.close()
    except sqlite3.Error:
        return ""
    return name if isinstance(name, str) else ""


# ── fixture ─────────────────────────────────────────────────────────────────

def _cursor_pb_varint(value):
    out = bytearray()
    while True:
        b = value & 0x7F
        value >>= 7
        if value:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def _cursor_pb_bytes(field, payload):
    return _cursor_pb_varint((field << 3) | 2) + _cursor_pb_varint(len(payload)) + payload


# ── Kiro CLI (kiro) ──────────────────────────────────────────────────────────
# Kiro CLI (AWS) parser for navcom.
#
# Three storage generations, all handled:
#
#   V2 (default engine in kiro-cli 2.27):
#     $KIRO_HOME (default ~/.kiro)/sessions/cli/<uuid>.jsonl   + <uuid>.json sidecar
#     lines: {"kind": Prompt|AssistantMessage|ToolResults|Compaction|ResetTo|CancelledPrompt|Clear,
#             "data": {"content": [{"kind": text|toolUse|toolResult|image|thinking, "data": ...}]}}
#     sidecar: {session_id, cwd, title|null, created_at, updated_at, session_created_reason, session_state}
#   KAS ("V3" Kiro Agent Server, opt-in):
#     $KIRO_HOME/sessions[/<workspace>]/sess_<uuid>/messages.jsonl + session.json
#     lines: {"timestamp", "payload": {"type": user|assistant|tool_call|tool_result|..., ...}}
#   V1 (legacy chat-cli / Amazon Q lineage): SQLite data.sqlite3 table conversations_v2
#     macOS ~/Library/Application Support/kiro-cli/data.sqlite3, Linux $XDG_DATA_HOME/kiro-cli/data.sqlite3
#     value JSON: {conversation_id, history: [{user{content{Prompt{prompt}|ToolUseResults{...}|CancelledToolUses{...}},
#                  additional_context, env_context}, assistant{Response{content}|ToolUse{content, tool_uses}}}]}

_kiro_KIRO_SHELL_TOOLS = ("shell", "execute_bash", "execute_cmd", "executeBash", "bash")


def kiro_home():
    return _env_path("KIRO_HOME") or Path.home() / ".kiro"


def kiro_db_paths():
    if sys.platform == "darwin":
        base = [Path.home() / "Library" / "Application Support" / "kiro-cli"]
    else:
        base = []
    base.append(_xdg_data_home() / "kiro-cli")
    return [b / "data.sqlite3" for b in base]


def kiro_roots():
    return [kiro_home() / "sessions"] + kiro_db_paths()


def _kiro_kiro_db_logs(db):
    logs = []
    try:
        conn = _ro_connect(db)
        try:
            rows = conn.execute("SELECT conversation_id, MAX(updated_at), length(value) FROM conversations_v2 "
                                "GROUP BY conversation_id").fetchall()
        finally:
            conn.close()
    except sqlite3.Error:
        return logs
    for conv_id, updated, size in rows:
        logs.append((f"{db}#{conv_id}", _epoch_seconds(updated), int(size or 0), "kiro"))
    return logs


def kiro_list():
    root = kiro_home() / "sessions"
    files = [p for p in (list(root.glob("cli/*.jsonl")) + list(root.glob("*.jsonl"))) if p.is_file()]
    files += list(root.glob("sess_*/messages.jsonl")) + list(root.glob("*/sess_*/messages.jsonl"))
    logs = [log for log in _file_logs(files, "kiro") if log[2] > 0]  # failed first turns leave 0-byte logs
    for db in kiro_db_paths():
        if db.is_file():
            logs.extend(_kiro_kiro_db_logs(db))
    return logs


# ── helpers ──────────────────────────────────────────────────────────────────

def _kiro_kiro_result_text(content):
    """Tool result content: str | [{"kind":"text"|"json","data"}] | [{"Text"}|{"Json"}] | dict."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(t for t in (_kiro_kiro_result_text(c) for c in content) if t)
    if isinstance(content, dict):
        if "kind" in content and "data" in content:
            return _kiro_kiro_result_text(content["data"])
        for key in ("Text", "text", "Json", "json"):
            if key in content:
                return _kiro_kiro_result_text(content[key])
        parts = [str(content[k]) for k in ("stdout", "stderr", "output", "content")
                 if isinstance(content.get(k), (str, int, float)) and str(content[k]).strip()]
        if parts:
            code = content.get("exit_status", content.get("exitCode"))
            prefix = f"exit {code}\n" if code not in (None, 0, "0") else ""
            return prefix + "\n".join(parts)
        return json.dumps(content, ensure_ascii=False)[:20000]
    return str(content)


def _kiro_kiro_call(calls, call_id, name, args):
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except Exception:
            pass
    calls[call_id] = _call_label(name, args)
    cmd = None
    if (name or "") in _kiro_KIRO_SHELL_TOOLS and isinstance(args, dict):
        cmd = args.get("command") or args.get("cmd")
        cmd = cmd.strip() if isinstance(cmd, str) else None
    return cmd or _shell_cmd(name, args)


def _kiro_kiro_result_turn(calls, call_id, content, status=None):
    output = _kiro_kiro_result_text(content)
    if str(status or "").lower() in ("error", "failed"):
        output = "error\n" + output
    return tool_turn(calls.get(call_id, "tool"), output)


def _kiro_kiro_blocks(data):
    content = (data or {}).get("content") if isinstance(data, dict) else None
    return content if isinstance(content, list) else []


# ── V2 JSONL ─────────────────────────────────────────────────────────────────

def _kiro_iter_kiro_v2(handle):
    calls = {}
    for line in handle:
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if not isinstance(obj, dict):
            continue
        kind, data = obj.get("kind"), obj.get("data") or {}
        if kind == "Prompt":
            text = "\n\n".join(b["data"].strip() for b in _kiro_kiro_blocks(data)
                               if isinstance(b, dict) and b.get("kind") == "text"
                               and isinstance(b.get("data"), str) and b["data"].strip())
            if text:
                yield "user", text
        elif kind == "AssistantMessage":
            texts = []
            for block in _kiro_kiro_blocks(data):
                if not isinstance(block, dict):
                    continue
                if block.get("kind") == "text" and isinstance(block.get("data"), str):
                    texts.append(block["data"])
                elif block.get("kind") == "toolUse" and isinstance(block.get("data"), dict):
                    if texts:
                        yield "assistant", "\n".join(texts)
                        texts = []
                    tu = block["data"]
                    cmd = _kiro_kiro_call(calls, tu.get("toolUseId"), tu.get("name"), tu.get("input"))
                    if cmd:
                        yield "cmd", cmd
            if "".join(texts).strip():
                yield "assistant", "\n".join(texts)
        elif kind == "ToolResults":
            for block in _kiro_kiro_blocks(data):
                if isinstance(block, dict) and block.get("kind") == "toolResult" and isinstance(block.get("data"), dict):
                    tr = block["data"]
                    turn = _kiro_kiro_result_turn(calls, tr.get("toolUseId"), tr.get("content"), tr.get("status"))
                    if turn:
                        yield turn
        # Compaction (generated summary), ResetTo, CancelledPrompt, Clear: not typed text


# ── KAS messages.jsonl ───────────────────────────────────────────────────────

def _kiro_iter_kiro_kas(handle):
    calls = {}
    for line in handle:
        try:
            payload = (json.loads(line) or {}).get("payload") or {}
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        typ = payload.get("type")
        content = payload.get("content")
        if typ in ("user", "assistant"):
            text = content if isinstance(content, str) else _text_of(content)
            if text and text.strip():
                yield typ, text.strip()
        elif typ == "tool_call":
            cmd = _kiro_kiro_call(calls, payload.get("toolCallId"), payload.get("toolName"), payload.get("args"))
            if cmd:
                yield "cmd", cmd
        elif typ == "tool_result":
            turn = _kiro_kiro_result_turn(calls, payload.get("toolCallId"), content, payload.get("status"))
            if turn:
                yield turn


# ── V1 SQLite ────────────────────────────────────────────────────────────────

def _kiro_kiro_db_row(key):
    db, _, conv_id = key.rpartition("#")
    try:
        conn = _ro_connect(db)
        try:
            return conn.execute("SELECT key, value FROM conversations_v2 WHERE conversation_id = ? "
                                "ORDER BY updated_at DESC LIMIT 1", (conv_id,)).fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return None


def _kiro_iter_kiro_db(key):
    row = _kiro_kiro_db_row(key)
    if not row:
        return
    try:
        conv = json.loads(row[1])
    except Exception:
        return
    calls = {}
    for entry in conv.get("history") or []:
        if not isinstance(entry, dict):
            continue
        user = entry.get("user") or {}
        content = user.get("content") or {}
        # user.additional_context / env_context are injected by the CLI: skipped
        if isinstance(content, dict):
            for variant in ("Prompt", "CancelledToolUses"):
                prompt = (content.get(variant) or {}).get("prompt") if isinstance(content.get(variant), dict) else None
                if isinstance(prompt, str) and prompt.strip():
                    yield "user", prompt.strip()
            for variant in ("ToolUseResults", "CancelledToolUses"):
                block = content.get(variant)
                for res in (block or {}).get("tool_use_results") or [] if isinstance(block, dict) else []:
                    if isinstance(res, dict):
                        turn = _kiro_kiro_result_turn(calls, res.get("tool_use_id"), res.get("content"), res.get("status"))
                        if turn:
                            yield turn
        assistant = entry.get("assistant") or {}
        for variant in ("Response", "ToolUse"):
            msg = assistant.get(variant)
            if not isinstance(msg, dict):
                continue
            if isinstance(msg.get("content"), str) and msg["content"].strip():
                yield "assistant", msg["content"]
            for tu in msg.get("tool_uses") or []:
                if isinstance(tu, dict):
                    cmd = _kiro_kiro_call(calls, tu.get("id"), tu.get("name"), tu.get("args"))
                    if cmd:
                        yield "cmd", cmd


def kiro_iter(key):
    if "#" in key and not key.endswith(".jsonl"):
        yield from _kiro_iter_kiro_db(key)
        return
    try:
        handle = open(key, "r", encoding="utf-8", errors="replace")
    except OSError:
        return
    with handle:
        if Path(key).name == "messages.jsonl":
            yield from _kiro_iter_kiro_kas(handle)
        else:
            yield from _kiro_iter_kiro_v2(handle)


def _kiro_kiro_sidecar(key):
    path = Path(key)
    side = path.parent / "session.json" if path.name == "messages.jsonl" else path.with_suffix(".json")
    try:
        data = json.loads(side.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def kiro_project(key):
    if "#" in key and not key.endswith(".jsonl"):
        row = _kiro_kiro_db_row(key)
        return row[0] if row and isinstance(row[0], str) else ""
    side = _kiro_kiro_sidecar(key)
    if isinstance(side.get("cwd"), str):
        return side["cwd"]
    paths = side.get("workspacePaths")
    return paths[0] if isinstance(paths, list) and paths and isinstance(paths[0], str) else ""


def kiro_title(key):
    if "#" in key and not key.endswith(".jsonl"):
        return ""
    title = _kiro_kiro_sidecar(key).get("title")
    return title.strip() if isinstance(title, str) else ""


# ── fixture ──────────────────────────────────────────────────────────────────


# ── Amp (amp) ────────────────────────────────────────────────────────────────
# Amp (ampcode.com, npm @ampcode/cli, formerly @sourcegraph/amp) parser for navcom.
#
# Local thread cache: $XDG_DATA_HOME/amp/threads/T-<uuid>.json (default ~/.local/share/amp, also on macOS;
# the CLI honours XDG_DATA_HOME on darwin too). The server (ampcode.com) is the source of truth; the
# local file is one JSON document per thread:
#   {v, id, created(ms), title?, env{initial{trees[{displayName, uri:file://...}]}}, meta{traces},
#    messages[{role: user|assistant|info, messageId, content[...], meta{sentAt}, usage, state}]}
#   user content:      {type:text,text} | {type:tool_result, toolUseID, run{status, result|error}}
#   assistant content: {type:text,text} | {type:thinking,thinking} | {type:tool_use, id, name, input}
#   role "info" (ThreadInfoMessage) is injected by Amp, not typed.

_amp_AMP_SHELL_TOOLS = ("Bash", "shell_command", "async_shell_command")


def amp_roots():
    return [_xdg_data_home() / "amp" / "threads"]


def amp_list():
    files = []
    for root in amp_roots():
        if root.is_dir():
            files.extend(p for p in root.glob("T-*.json") if p.is_file())
    return _file_logs(files, "amp")


def _amp_amp_load(key):
    try:
        data = json.loads(Path(key).read_text(encoding="utf-8", errors="replace"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _amp_amp_result_text(result):
    """Mirror of agentsview serializeAmpResult: Bash {output,exitCode}, Read {content}, Edit {diff}, lists."""
    if result is None:
        return ""
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        for key in ("output", "content", "diff"):
            if key in result:
                text = _amp_amp_result_text(result[key])
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
    for msg in _amp_amp_load(key).get("messages") or []:
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
                calls[block.get("id")] = _call_label(name, args)
                cmd = None
                if name in _amp_AMP_SHELL_TOOLS and isinstance(args, dict):
                    cmd = args.get("cmd") or args.get("command")
                cmd = cmd.strip() if isinstance(cmd, str) else _shell_cmd(name, args)
                if cmd:
                    yield "cmd", cmd
            else:
                call_id = block.get("toolUseID") or block.get("tool_use_id")
                run = block.get("run") if isinstance(block.get("run"), dict) else {}
                if run:
                    status = run.get("status")
                    output = _amp_amp_result_text(run.get("result"))
                    if status == "error" and not output:
                        output = (run.get("error") or {}).get("message") or "[unknown error]"
                    if status == "error" or (isinstance(run.get("result"), dict) and run["result"].get("success") is False):
                        output = "error\n" + output
                    elif status == "cancelled" and not output:
                        output = "[cancelled]"
                else:
                    output = block.get("content")
                turn = tool_turn(calls.get(call_id, "tool"), output)
                if turn:
                    yield turn
        if texts and "".join(texts).strip():
            yield role, "\n".join(texts)


def amp_project(key):
    trees = ((_amp_amp_load(key).get("env") or {}).get("initial") or {}).get("trees") or []
    for tree in trees:
        uri = tree.get("uri") if isinstance(tree, dict) else None
        if isinstance(uri, str) and uri.startswith("file://"):
            return unquote(urlparse(uri).path)
    return ""


def amp_title(key):
    title = _amp_amp_load(key).get("title")
    return title.strip() if isinstance(title, str) else ""


# ── Augment Auggie (auggie) ──────────────────────────────────────────────────
# Augment Code CLI `auggie` (npm @augmentcode/auggie) — one JSON file per session.
#
# Store: <augmentCacheDir>/sessions/<conversationId>.json, augmentCacheDir = ~/.augment (only override is the
# --augment-cache-dir flag; no env var). Siblings `<id>-backup<N>.json` (pre-rewind backups) and
# `<id>.json.<ms>.tmp` (atomic-write temp) are not sessions.
#
# File (SessionManager.saveSession in augment.mjs 0.36.0):
#   {sessionId, created, modified, title?, customTitle?, workspaceId?, parentConversationId?,
#    agentState{userGuidelines, workspaceGuidelines, modelId, userEmail, agentPersonaId},
#    chatHistory: [{exchange{request_message, response_text, request_id, request_nodes[], response_nodes[]},
#                   completed, sequenceId, finishedAt, isHistorySummary, source}]}
#   request_nodes  type 0 text_node{content} | 1 tool_result_node{tool_use_id, content, is_error, content_nodes}
#                  | 2 image | 4 ide_state_node{workspace_folders[{repository_root, folder_root}], current_terminal}
#                  | 10 history_summary_node (compaction)
#   response_nodes type 0 {content} text | 5 tool_use{tool_use_id, tool_name, input_json} | 8 thinking | ...
#   Shell tool: tool_name "launch-process", input {command, wait, max_wait_seconds, cwd}.
#
# Mapping: request_message -> user (exchanges that are history summaries are injected, skipped);
# tool_result_node -> tool (results for the previous exchange's tool_use); response_text -> assistant;
# tool_use launch-process -> cmd. agentState guidelines = injected rules, never indexed.

_auggie_AUGGIE_NOT_SESSION = re.compile(r"-backup\d+\.json$")
_auggie_AUGGIE_SHELL_TOOLS = ("launch-process",)


def auggie_roots():
    return [Path.home() / ".augment" / "sessions"]


def auggie_list():
    paths = []
    for root in auggie_roots():
        try:
            paths += [p for p in root.glob("*.json") if not _auggie_AUGGIE_NOT_SESSION.search(p.name)]
        except OSError:
            pass
    return [(k, m, s, "auggie") for k, m, s, _ in _file_logs(paths, "auggie")]


def _auggie_auggie_load(key):
    try:
        data = json.loads(Path(key).read_text(encoding="utf-8", errors="replace"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _auggie_auggie_args(raw):
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except Exception:
            return raw
    return raw


def _auggie_auggie_result_text(node):
    content = node.get("content")
    if not (isinstance(content, str) and content.strip()):
        content = "\n".join(n.get("text_content") or "" for n in node.get("content_nodes") or []
                            if isinstance(n, dict) and n.get("text_content"))
    if node.get("is_error"):
        content = "error\n" + (content or "")
    return content


def _auggie_is_summary(entry, exchange):
    if entry.get("isHistorySummary"):
        return True
    return any(isinstance(n, dict) and (n.get("type") == 10 or n.get("history_summary_node"))
               for n in exchange.get("request_nodes") or [])


def auggie_iter(key):
    calls = {}
    for entry in _auggie_auggie_load(key).get("chatHistory") or []:
        if not isinstance(entry, dict):
            continue
        ex = entry.get("exchange") or {}
        summary = _auggie_is_summary(entry, ex)
        user = ex.get("request_message")
        if isinstance(user, str) and user.strip() and not summary:
            yield "user", user
        for node in ex.get("request_nodes") or []:
            result = node.get("tool_result_node") if isinstance(node, dict) else None
            if isinstance(result, dict):
                turn = tool_turn(calls.get(result.get("tool_use_id"), "tool"), _auggie_auggie_result_text(result))
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
            name, args = use.get("tool_name"), _auggie_auggie_args(use.get("input_json"))
            calls[use.get("tool_use_id")] = _call_label(name, args)
            cmd = _shell_cmd(name, args)
            if not cmd and name in _auggie_AUGGIE_SHELL_TOOLS and isinstance(args, dict):
                cmd = (args.get("command") or "").strip() or None
            if cmd:
                yield "cmd", cmd


def auggie_project(key):
    """Same rule as auggie's own j1t(): first ide_state_node workspace folder, else the terminal cwd."""
    terminal = ""
    for entry in _auggie_auggie_load(key).get("chatHistory") or []:
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
    data = _auggie_auggie_load(key)
    return data.get("customTitle") or data.get("title") or ""


# ── grok-dev (community Grok CLI) (grokdev) ──────────────────────────────────
# grok-dev (community superagent-ai/grok-cli, npm `grok-dev`) — SQLite store ~/.grok/grok.db.
#
# Shares ~/.grok with xAI's official Grok Build CLI (~/.grok/sessions/*/updates.jsonl), but this is a
# different file. Path is hard-coded: os.homedir()/.grok/grok.db (dist/storage/db.js) — no env override.
#
# Schema (dist/storage/migrations.js, user_version 3):
#   workspaces(id, scope_key, canonical_path, git_root, display_name, last_seen_at)
#   sessions(id, workspace_id, title, recap_text, recap_model, recap_updated_at, model, mode,
#            cwd_at_start, cwd_last, status, created_at, updated_at)
#   messages(session_id, seq, role, message_json, created_at)   -- message_json = Vercel AI SDK ModelMessage
#   tool_calls / tool_results / usage_events / compactions        -- denormalised copies; not needed
#
# message_json roles:
#   user      {"content": str | [{type:"text",text} | {type:"image",...}]}        -> user
#   assistant {"content": str | [{type:"text"} | {type:"reasoning"} | {type:"tool-call",toolCallId,toolName,input}]}
#   tool      {"content": [{type:"tool-result",toolCallId,toolName,output:{type:"json"|"text"|"error-text",value}}]}
#   system    background-task notifications + compaction summaries                 -> skipped (injected)

def grokdev_db_path():
    return Path.home() / ".grok" / "grok.db"


def grokdev_roots():
    return [grokdev_db_path()]


def grokdev_list():
    db = grokdev_db_path()
    if not db.is_file():
        return []
    try:
        conn = _ro_connect(db)
        rows = conn.execute("""
            SELECT s.id, s.updated_at, COUNT(m.seq), MAX(m.created_at)
            FROM sessions s LEFT JOIN messages m ON m.session_id = s.id
            GROUP BY s.id HAVING COUNT(m.seq) > 0""").fetchall()
        conn.close()
    except Exception:
        return []
    return [(f"{db}#{sid}", max(_epoch_seconds(updated), _epoch_seconds(last)), int(count), "grokdev")
            for sid, updated, count, last in rows]


def _grokdev_split_key(key):
    db, _, sid = str(key).rpartition("#")
    return db, sid


def _grokdev_grokdev_output(output):
    """ToolResultOutput -> text: {type:json, value:{success, output, error}} | {type:text|error-text, value}."""
    if not isinstance(output, dict):
        return output
    kind, value = output.get("type"), output.get("value")
    if kind == "json" and isinstance(value, dict):
        if "success" in value or "output" in value or "error" in value:
            text = value.get("output")
            if not isinstance(text, str):
                text = json.dumps(text, ensure_ascii=False) if text not in (None, "") else ""
            if value.get("error"):
                text = f"error\n{value['error']}\n{text}".rstrip()
            return text
        return json.dumps(value, ensure_ascii=False)[:20000]
    if kind == "error-text":
        return f"error\n{value}"
    if kind in ("text", "content"):
        return value if isinstance(value, str) else _text_of(value)
    return value if isinstance(value, (str, list)) else json.dumps(output, ensure_ascii=False)[:20000]


def grokdev_iter(key):
    db, sid = _grokdev_split_key(key)
    try:
        conn = _ro_connect(db)
        rows = conn.execute("SELECT role, message_json FROM messages WHERE session_id = ? ORDER BY seq",
                            (sid,)).fetchall()
        conn.close()
    except Exception:
        return
    calls = {}
    for role, raw in rows:
        try:
            msg = json.loads(raw)
        except Exception:
            continue
        content = msg.get("content")
        if role == "user":
            text = _text_of(content)
            if text and text.strip():
                yield "user", text
        elif role == "assistant":
            if isinstance(content, str):
                if content.strip():
                    yield "assistant", content
                continue
            for part in content or []:
                if not isinstance(part, dict):
                    continue
                kind = part.get("type")
                if kind == "text" and (part.get("text") or "").strip():
                    yield "assistant", part["text"]
                elif kind == "tool-call":
                    args = part.get("input")
                    if isinstance(args, str):
                        try:
                            args = json.loads(args) if args.strip() else {}
                        except Exception:
                            pass
                    calls[part.get("toolCallId")] = _call_label(part.get("toolName"), args)
                    cmd = _shell_cmd(part.get("toolName"), args)
                    if cmd:
                        yield "cmd", cmd
        elif role == "tool":
            for part in content or []:
                if isinstance(part, dict) and part.get("type") == "tool-result":
                    label = calls.get(part.get("toolCallId")) or part.get("toolName") or "tool"
                    turn = tool_turn(label, _grokdev_grokdev_output(part.get("output")))
                    if turn:
                        yield turn
        # role == "system": background notifications / compaction summaries — injected, skipped


def _grokdev_grokdev_session(key):
    db, sid = _grokdev_split_key(key)
    try:
        conn = _ro_connect(db)
        row = conn.execute("""SELECT s.title, s.cwd_at_start, s.cwd_last, w.canonical_path
                              FROM sessions s LEFT JOIN workspaces w ON w.id = s.workspace_id
                              WHERE s.id = ?""", (sid,)).fetchone()
        conn.close()
        return row or (None, None, None, None)
    except Exception:
        return (None, None, None, None)


def grokdev_project(key):
    title, start, last, workspace = _grokdev_grokdev_session(key)
    return start or last or workspace or ""


def grokdev_title(key):
    return _grokdev_grokdev_session(key)[0] or ""


_grokdev_SCHEMA = """
CREATE TABLE IF NOT EXISTS workspaces (id TEXT PRIMARY KEY, scope_key TEXT NOT NULL UNIQUE,
  canonical_path TEXT NOT NULL, git_root TEXT, display_name TEXT NOT NULL, last_seen_at TEXT NOT NULL) STRICT;
CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY,
  workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE, title TEXT, recap_text TEXT,
  recap_model TEXT, recap_updated_at TEXT, model TEXT NOT NULL, mode TEXT NOT NULL, cwd_at_start TEXT NOT NULL,
  cwd_last TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL) STRICT;
CREATE TABLE IF NOT EXISTS messages (session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  seq INTEGER NOT NULL, role TEXT NOT NULL, message_json TEXT NOT NULL, created_at TEXT NOT NULL,
  PRIMARY KEY (session_id, seq)) STRICT;
CREATE TABLE IF NOT EXISTS tool_calls (id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE, message_seq INTEGER NOT NULL,
  tool_call_id TEXT NOT NULL, tool_name TEXT NOT NULL, args_json TEXT NOT NULL, status TEXT NOT NULL,
  started_at TEXT NOT NULL, completed_at TEXT, UNIQUE(session_id, tool_call_id)) STRICT;
CREATE TABLE IF NOT EXISTS tool_results (id INTEGER PRIMARY KEY AUTOINCREMENT,
  tool_call_row_id INTEGER NOT NULL REFERENCES tool_calls(id) ON DELETE CASCADE, output_kind TEXT NOT NULL,
  output_json TEXT NOT NULL, success INTEGER NOT NULL, created_at TEXT NOT NULL) STRICT;
CREATE TABLE IF NOT EXISTS compactions (id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE, first_kept_seq INTEGER NOT NULL,
  summary TEXT NOT NULL, tokens_before INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL) STRICT;
"""


register_harness('qwen', list_fn=qwen_list, iter_fn=qwen_iter, project_fn=qwen_project,
                 title_fn=qwen_title, roots_fn=qwen_roots, match=lambda p: '/.qwen/' in p,
                 aliases=['qwen-code', 'qwencode', 'alibaba'], color='93', archivable=True, label='Qwen Code',
                 retention_fn=qwen_retention)
register_harness('kimi', list_fn=kimi_list, iter_fn=kimi_iter, project_fn=kimi_project,
                 title_fn=kimi_title, roots_fn=kimi_roots, match=lambda p: '/.kimi-code/' in p or '/.kimi/sessions/' in p,
                 aliases=['kimi-code', 'kimicode', 'moonshot'], color='95', archivable=True, label='Kimi Code')
register_harness('crush', list_fn=crush_list, iter_fn=crush_iter, project_fn=crush_project,
                 title_fn=crush_title, roots_fn=crush_roots, match=lambda p: '/.crush/crush.db#' in p or '/crush/crush.db#' in p,
                 aliases=['charm', 'charmbracelet'], color='35', archivable=False, label='Crush')
register_harness('copilot', list_fn=copilot_list, iter_fn=copilot_iter, project_fn=copilot_project,
                 title_fn=copilot_title, roots_fn=copilot_roots, match=lambda p: '/.copilot/' in p,
                 aliases=['github-copilot', 'gh-copilot', 'copilot-cli'], color='37', archivable=True, label='GitHub Copilot CLI')
register_harness('cline', list_fn=cline_list, iter_fn=cline_iter, project_fn=cline_project,
                 title_fn=cline_title, roots_fn=cline_roots, match=lambda p: '/.cline/' in p or 'saoudrizwan.claude-dev' in p,
                 aliases=['cline-cli'], color='36', archivable=True, label='Cline')
register_harness('continue', list_fn=continue_list, iter_fn=continue_iter, project_fn=continue_project,
                 title_fn=continue_title, roots_fn=continue_roots, match=lambda p: '/.continue/sessions/' in p,
                 aliases=['cn', 'continue-cli'], color='34', archivable=True, label='Continue')
register_harness('codewhale', list_fn=codewhale_list, iter_fn=codewhale_iter, project_fn=codewhale_project,
                 title_fn=codewhale_title, roots_fn=codewhale_roots, match=lambda p: '/.codewhale/' in p or '/.deepseek/sessions/' in p,
                 aliases=['deepseek-tui', 'whale'], color='94', archivable=True, label='Codewhale')
register_harness('reasonix', list_fn=reasonix_list, iter_fn=reasonix_iter, project_fn=reasonix_project,
                 title_fn=reasonix_title, roots_fn=reasonix_roots, match=lambda p: '/.reasonix/' in p,
                 aliases=['deepseek-reasonix'], color='96', archivable=True, label='DeepSeek Reasonix')
register_harness('deepcode', list_fn=deepcode_list, iter_fn=deepcode_iter, project_fn=deepcode_project,
                 title_fn=deepcode_title, roots_fn=deepcode_roots, match=lambda p: '/.deepcode/' in p,
                 aliases=['deep-code', 'deepcode-cli'], color='92', archivable=True, label='Deep Code')
register_harness('hermes', list_fn=hermes_list, iter_fn=hermes_iter, project_fn=hermes_project,
                 title_fn=hermes_title, roots_fn=hermes_roots, match=lambda p: '/.hermes/' in p,
                 aliases=['nous', 'hermes-agent'], color='33', archivable=False, label='Hermes Agent',
                 retention_fn=hermes_retention)
register_harness('openhands', list_fn=openhands_list, iter_fn=openhands_iter, project_fn=openhands_project,
                 title_fn=openhands_title, roots_fn=openhands_roots, match=lambda p: '/.openhands/' in p,
                 aliases=['open-hands', 'all-hands'], color='32', archivable=False, label='OpenHands')
register_harness('vibe', list_fn=vibe_list, iter_fn=vibe_iter, project_fn=vibe_project,
                 title_fn=vibe_title, roots_fn=vibe_roots, match=lambda p: '/.vibe/' in p,
                 aliases=['mistral', 'mistral-vibe'], color='91', archivable=True, label='Mistral Vibe')
register_harness('aider', list_fn=aider_list, iter_fn=aider_iter, project_fn=aider_project,
                 title_fn=aider_title, roots_fn=aider_roots, match=lambda p: '.aider.chat.history.md' in p,
                 aliases=['aider-chat'], color='92', archivable=True, label='Aider')
register_harness('agy', list_fn=agy_list, iter_fn=agy_iter, project_fn=agy_project,
                 title_fn=agy_title, roots_fn=agy_roots, match=lambda p: '/antigravity' in p,
                 aliases=['antigravity', 'google-antigravity'], color='94', archivable=True, label='Antigravity CLI')
register_harness('droid', list_fn=droid_list, iter_fn=droid_iter, project_fn=droid_project,
                 title_fn=droid_title, roots_fn=droid_roots, match=lambda p: '/.factory/' in p,
                 aliases=['factory', 'factory-droid'], color='33', archivable=True, label='Factory Droid')
register_harness('cursor', list_fn=cursor_list, iter_fn=cursor_iter, project_fn=cursor_project,
                 title_fn=cursor_title, roots_fn=cursor_roots, match=lambda p: '/.cursor/' in p,
                 aliases=['cursor-agent', 'cursor-cli'], color='97', archivable=True, label='Cursor CLI')
register_harness('kiro', list_fn=kiro_list, iter_fn=kiro_iter, project_fn=kiro_project,
                 title_fn=kiro_title, roots_fn=kiro_roots, match=lambda p: '/.kiro/' in p or 'kiro-cli/data.sqlite3#' in p,
                 aliases=['kiro-cli', 'amazon-q', 'q-cli'], color='33', archivable=True, label='Kiro CLI')
register_harness('amp', list_fn=amp_list, iter_fn=amp_iter, project_fn=amp_project,
                 title_fn=amp_title, roots_fn=amp_roots, match=lambda p: '/amp/threads/' in p,
                 aliases=['sourcegraph-amp', 'ampcode'], color='35', archivable=True, label='Amp')
register_harness('auggie', list_fn=auggie_list, iter_fn=auggie_iter, project_fn=auggie_project,
                 title_fn=auggie_title, roots_fn=auggie_roots, match=lambda p: '/.augment/' in p,
                 aliases=['augment', 'augment-code'], color='36', archivable=True, label='Augment Auggie')
register_harness('grokdev', list_fn=grokdev_list, iter_fn=grokdev_iter, project_fn=grokdev_project,
                 title_fn=grokdev_title, roots_fn=grokdev_roots, match=lambda p: '/.grok/grok.db#' in p,
                 aliases=['grok-cli', 'grok-dev', 'superagent-grok'], color='37', archivable=False, label='grok-dev (community Grok CLI)')
# <<< registered harnesses

# ─────────────────────────────────────────────────────────────────────────────
# navcom --menu — CAPCOM-style retro TUI (Atari raster bands, vertical gradients only)
# ─────────────────────────────────────────────────────────────────────────────
# Style guide: ~/dev/EXP31-pi-dev-tools/docs/retro-raster-tui-style.md. Horizontal is solid,
# vertical is the gradient; half-block ▀ doubles the vertical resolution; GTIA palette; block-glyph
# wordmark (font-independent). Stdlib only: termios/tty/select key loop, alternate screen.

MENU_P = dict(black="000000", blue_deep="000071", blue_dark="13007d", blue_mid="351c9d",
              cyan="6cc4e2", sky="8ee6ff", gold_dk="816f00", gold="c7b43d", amber="ead760",
              yellow="fffa84", orange="ca8e3d", orange_dk="975b0a", orange_hot="fdc170",
              red_deep="420404", cream="e6d6b0", ink="1a0f00", green="6aab36", red="c2402a",
              grey="555555", grey_lt="9aa0a6")
MENU_SPARK = "▁▂▃▄▅▆▇█"
MENU_SLOGAN = "YOUR CONVERSATIONS · YOUR MACHINE · YOUR DATA"
MENU_TAGLINE = "every coding agent's history — searchable in a blink, archived, kept for 100 years"

_GLYPHS = {  # 5x7 masks, '#' = on
    "N": ["#   #", "##  #", "# # #", "#  ##", "#   #", "#   #", "#   #"],
    "A": [" ### ", "#   #", "#   #", "#####", "#   #", "#   #", "#   #"],
    "V": ["#   #", "#   #", "#   #", "#   #", "#   #", " # # ", "  #  "],
    "C": ["#####", "#    ", "#    ", "#    ", "#    ", "#    ", "#####"],
    "O": [" ### ", "#   #", "#   #", "#   #", "#   #", "#   #", " ### "],
    "M": ["#   #", "## ##", "# # #", "# # #", "#   #", "#   #", "#   #"],
}


def _mrgb(c):
    h = MENU_P.get(c, c)
    return f"{int(h[0:2], 16)};{int(h[2:4], 16)};{int(h[4:6], 16)}"


def _msgr(fg=None, bg=None):
    return (f"\033[38;2;{_mrgb(fg)}m" if fg else "") + (f"\033[48;2;{_mrgb(bg)}m" if bg else "")


def _interp(a, b, t, d):
    a, b = MENU_P.get(a, a), MENU_P.get(b, b)
    return "".join(f"{(int(a[i:i + 2], 16) * (d - t) + int(b[i:i + 2], 16) * t) // d:02x}" for i in (0, 2, 4))


def _line(spans, width, dfg="cream", dbg="black"):
    """Render [(text, fg, bg)] clipped/padded to exactly `width` cells."""
    out, vis = [], 0
    for text, fg, bg in spans:
        if vis >= width:
            break
        text = str(text)[:width - vis]
        out.append(_msgr(fg or dfg, bg or dbg) + text + "\033[0m")
        vis += len(text)
    if vis < width:
        out.append(_msgr(dfg, dbg) + " " * (width - vis) + "\033[0m")
    return "".join(out)


def _stripe(width, top, bot):
    return _line([("▀" * width, top, bot)], width)


def _band(width, text, fg, bg):
    pad = max(0, (width - len(text)) // 2)
    return _line([(" " * pad + text, fg, bg)], width, dbg=bg)


def _meter(frac, width):
    frac = max(0.0, min(1.0, frac))
    n = int(round(frac * width))
    return "█" * n + "░" * (width - n)


def _spark(xs):
    """sqrt-scaled so one huge day doesn't flatten the other 29."""
    xs = [max(0, x) ** 0.5 for x in (list(xs) or [0])]
    hi = max(xs)
    if hi <= 0:
        return MENU_SPARK[0] * len(xs)
    return "".join(MENU_SPARK[min(7, int(x / hi * 7 + 0.001))] if x else " " for x in xs)


def _box(title, body, width, height, bfg="blue_mid", tfg="gold"):
    inner = width - 2
    rows = [_line([("╭─ ", bfg, None), (title, tfg, None), (" " + "─" * max(0, inner - len(title) - 3), bfg, None),
                   ("╮", bfg, None)], width)]
    for i in range(height - 2):
        spans = body[i] if i < len(body) else []
        rows.append(_line([("│ ", bfg, None)] + list(spans), width - 1) + _line([("│", bfg, None)], 1))
    rows.append(_line([("╰" + "─" * inner + "╯", bfg, None)], width))
    return rows


def _wordmark(width, word="NAVCOM", top="orange_hot", bot="orange_dk", on="▀▀"):
    off, gap = "  ", "  "
    vis = len(word) * (5 * len(on) + len(gap))
    if vis > width:  # narrow terminal: single-cell pixels
        on, off, gap = on[:1], " ", " "
        vis = len(word) * (5 * len(on) + len(gap))
    rows = []
    for r in range(7):
        line = ""
        for ch in word:
            line += "".join(on if c == "#" else off for c in _GLYPHS[ch][r]) + gap
        pad = max(0, (width - vis) // 2)
        rows.append(_line([(" " * pad + line, _interp(top, bot, r, 6), "black")], width))
    return rows


def _wrap(text, width):
    out = []
    for para in str(text).splitlines() or [""]:
        line = ""
        for word in para.split(" "):
            while len(word) > width:
                if line:
                    out.append(line)
                    line = ""
                out.append(word[:width])
                word = word[width:]
            if len(line) + len(word) + (1 if line else 0) > width:
                out.append(line)
                line = word
            else:
                line = f"{line} {word}" if line else word
        out.append(line)
    return out


def splash_frame(width):
    rows = [_stripe(width, "black", "blue_deep"), _stripe(width, "blue_deep", "blue_dark"),
            _stripe(width, "blue_dark", "blue_mid"), _line([], width)]
    rows += _wordmark(width)
    rows += [_line([], width), _stripe(width, "orange_hot", "orange"),
             _band(width, MENU_SLOGAN, "ink", "orange"),
             _stripe(width, "orange", "orange_dk"),
             _band(width, MENU_TAGLINE, "cream", "orange_dk"),
             _stripe(width, "orange_dk", "red_deep"), _stripe(width, "red_deep", "black"),
             _band(width, f"navcom {NAVCOM_VERSION} · press any key", "grey_lt", "black")]
    return rows


# ── dashboard data ───────────────────────────────────────────────────────────

def dashboard_stats(conn):
    """Everything the dashboard shows, computed from the index + disk in well under a second."""
    import time
    now = time.time()
    logs = list_logs(ALL_PROVIDERS)
    on_disk = {l[0] for l in logs}
    per_harness = collections.Counter(l[3] for l in logs)
    rows = conn.execute("SELECT file, mtime FROM file_state").fetchall()
    rescued = sum(1 for f, _ in rows if f not in on_disk)
    oldest = min((m for _, m in rows if m), default=now)
    days = [0] * 30
    for _, m in rows:
        age = int((now - (m or 0)) // 86400)
        if 0 <= age < 30:
            days[29 - age] += 1
    turns = conn.execute("SELECT count(*) FROM turn_loc").fetchone()[0]
    try:
        tool_rows = conn.execute("SELECT count(*) FROM session_fts WHERE role='tool'").fetchone()[0]
    except sqlite3.Error:
        tool_rows = 0
    claude_logs = [l for l in logs if l[3] == "claude"]
    claude_old_kept = sum(1 for l in claude_logs if now - l[1] > 30 * 86400)
    retention = []
    for name, status in (("Claude Code", claude_retention_status), ("Gemini CLI", gemini_retention_status)):
        d, how = status()
        if d is not None:
            retention.append((name, 30, d, how))
    for hid, h in EXTRA_HARNESSES.items():
        if not h.get("retention"):
            continue
        try:
            spec = h["retention"]()
        except Exception:
            continue
        if not spec or not Path(spec["settings_path"]).parent.is_dir():
            continue
        reader = yaml_setting if str(spec["settings_path"]).endswith((".yaml", ".yml")) else json_setting
        cur = reader(spec["settings_path"], spec["key_path"])
        kept = cur is not None and str(cur).lower() in (str(spec["never_delete_value"]).lower(), "false", "36500")
        retention.append((h["label"], spec.get("default_days", 30), 36500 if kept else spec.get("default_days", 30),
                          f"{spec['key_path']} = {cur}"))
    archive_files = archive_bytes = 0
    root = archive_root()
    if root.exists():
        for p in root.rglob("*.gz"):
            archive_files += 1
            archive_bytes += p.stat().st_size
    return {
        "sessions": len(rows), "on_disk": len(on_disk), "rescued": rescued, "turns": turns, "tools": tool_rows,
        "oldest": oldest, "days": days, "per_harness": per_harness, "retention": retention,
        "claude_old_kept": claude_old_kept, "archive_files": archive_files, "archive_bytes": archive_bytes,
        "daily": daily_job_status(), "index_bytes": default_index_path().stat().st_size
        if default_index_path().exists() else 0,
    }


MENU_ACTIONS = [
    ("search", "SEARCH", "Find any conversation, command or error across every harness.",
     "navcom <words>"),
    ("recent", "RECENT SESSIONS", "Your latest sessions, with titles — open one to read it.",
     "navcom --sessions"),
    ("open", "OPEN BY REF", "Read a session by the ref printed in search results (e.g. 7ec78a59:533).",
     "navcom --open <ref>[:turn]"),
    ("harness", "HARNESSES", "Every coding agent navcom reads, how many sessions each has, where they live.",
     "navcom --where"),
    ("learn", "LEARN NAVCOM", "The two-step recipe and the query rules, with copy-paste examples.",
     "navcom --help"),
    ("skill", "SKILL CARD", "Teach every agent on this machine to use navcom (already automatic).",
     "navcom --skill install"),
    ("maintain", "RUN UPKEEP NOW", "Index everything, archive raw transcripts, re-parse old rows.",
     "navcom --maintain"),
    ("quit", "QUIT", "Back to your shell.", ""),
]


def dashboard_frame(stats, sel, width, height):
    import time
    W = width
    rows = [_stripe(W, "orange_hot", "orange"),
            _line([("  NAVCOM", "yellow", None), (" · mission control for your agent history   ", "cream", None),
                   (MENU_SLOGAN.lower(), "orange_hot", None), ("   " + time.strftime("%H:%M:%S"), "grey_lt", None)], W),
            _stripe(W, "orange", "orange_dk")]
    lw = rw = min(36, max(22, (W - 6) // 3))
    cw = max(24, W - lw - rw - 2)
    th = 13
    s = stats
    oldest = datetime.fromtimestamp(s["oldest"]).strftime("%Y-%m-%d")
    hist = [
        [("sessions   ", "grey_lt", None), (f"{s['sessions']:,}", "yellow", None)],
        [("turns      ", "grey_lt", None), (f"{s['turns']:,}", "cream", None)],
        [("tool output", "grey_lt", None), (f" {s['tools']:,}", "cream", None)],
        [("history    ", "grey_lt", None), (f"since {oldest}", "cyan", None)],
        [("rescued    ", "grey_lt", None), (f"{s['rescued']:,}", "green", None), (" deleted by", "grey_lt", None)],
        [("           ", None, None), ("their harness,", "grey_lt", None)],
        [("           ", None, None), ("still yours", "green", None)],
        [("archive    ", "grey_lt", None),
         (f"{s['archive_files']:,} raw · {s['archive_bytes'] / 1e6:.0f} MB", "cream", None)],
        [("index      ", "grey_lt", None), (f"{s['index_bytes'] / 1e9:.2f} GB", "cream", None)],
    ]
    bw = max(8, cw - 33)
    sliver = "█" + "░" * (bw - 1)  # 30 days against 36,500: one cell is already generous
    ret = [[("Claude's default  ", "grey_lt", None), (sliver, "red", None), ("  30 days", "red", None)],
           [("navcom keeps     ", "grey_lt", None), (_meter(1.0, bw), "green", None), ("  100 years", "green", None)],
           [("─" * (cw - 4), "blue_mid", None)]]
    for name, default, now_days, _how in s["retention"][:6]:
        ok = now_days >= 3650
        ret.append([("● " if ok else "○ ", "green" if ok else "red", None), (f"{name[:14]:<15}", "cream", None),
                    (f"wipes at {default}d → ", "grey_lt", None),
                    ("kept 100y" if ok else f"DELETES {now_days:g}d", "green" if ok else "red", None)])
    if s["claude_old_kept"]:
        ret.append([("  saved so far: ", "grey_lt", None), (f"{s['claude_old_kept']} Claude chats", "green", None),
                    (" > 30d old", "grey_lt", None)])
    top = s["per_harness"].most_common(5)
    hi = max([n for _, n in top] or [1])
    act = [[("30 days ", "grey_lt", None), (_spark(s["days"]), "cyan", None)],
           [("─" * (rw - 4), "blue_mid", None)]]
    for name, n in top:
        act.append([(f"{name:<9}", "cream", None), (_meter(n / hi, rw - 18), "amber", None), (f" {n:>5}", "grey_lt", None)])
    act += [[("─" * (rw - 4), "blue_mid", None)],
            [("● " if "scheduled" in s["daily"] else "○ ", "green" if "scheduled" in s["daily"] else "red", None),
             ("daily upkeep " + ("on" if "scheduled" in s["daily"] else "off"), "cream", None)],
            [(f"{len([1 for v in s['per_harness'].values() if v])} harnesses active", "grey_lt", None)]]
    a, b, c = _box("HISTORY", hist, lw, th), _box("RETENTION ▸ keeping your data", ret, cw, th, tfg="orange_hot"), \
        _box("ACTIVITY", act, rw, th)
    rows += [a[i] + " " + b[i] + " " + c[i] for i in range(th)]
    acts = []
    for i, (_aid, label, why, cli) in enumerate(MENU_ACTIONS):
        on = i == sel
        acts.append([("▶ " if on else "  ", "orange_hot" if on else "blue_mid", None),
                     (f" {label:<16}", "ink" if on else "cream", "amber" if on else None),
                     (f"  {why}", "cream" if on else "grey_lt", None)])
    rows += _box("ACTIONS   (↑↓ select · enter go)", acts, W, len(MENU_ACTIONS) + 2)
    cli = MENU_ACTIONS[sel][3]
    rows.append(_line([("  CLI ▸ ", "orange_hot", None), (cli or "—", "yellow", None),
                       ("   learn the command: everything here is one line in a script or an agent", "grey_lt", None)], W))
    rows.append(_line([("  ↑↓", "orange_hot", None), (" move  ", "grey_lt", None), ("enter", "orange_hot", None),
                       (" go  ", "grey_lt", None), ("/", "orange_hot", None), (" search  ", "grey_lt", None),
                       ("r", "orange_hot", None), (" refresh  ", "grey_lt", None), ("q", "orange_hot", None),
                       (" quit", "grey_lt", None)], W))
    rows += [_stripe(W, "orange_dk", "red_deep"), _stripe(W, "red_deep", "black")]
    return rows[:height]


def _screen(title, body_rows, width, height, footer, cli="", resume=None):
    """Generic full-screen page: title band, body, [RESUME line], CLI line, key hints."""
    rows = [_stripe(width, "black", "blue_deep"), _band(width, title, "yellow", "blue_dark"),
            _stripe(width, "blue_dark", "black")]
    room = height - len(rows) - 4 - (resume is not None)
    rows += body_rows[:room] + [_line([], width)] * max(0, room - len(body_rows))
    if resume is not None:
        spans = resume if isinstance(resume, list) else [resume]
        rows.append(_line([("  RESUME ▸ ", "orange_hot", None)] + spans, width))
    rows.append(_line([("  CLI ▸ ", "orange_hot", None), (cli or "—", "yellow", None)], width))
    rows.append(_line([("  " + footer, "grey_lt", None)], width))
    rows += [_stripe(width, "orange_dk", "red_deep"), _stripe(width, "red_deep", "black")]
    return rows


ROLE_COLORS = {"user": "amber", "cmd": "orange_hot", "tool": "grey_lt"}


def _turn_rows(role, text, provider, msg_index, width, marked=False):
    label = clean_mod.label_for_role(role, provider or "") or "assistant"
    color = ROLE_COLORS.get(role, "cyan")
    rows = [_line([("▶ " if marked else "  ", "orange_hot", None), (f"#{msg_index} ", "grey", None),
                   (label + ":", color, None)], width)]
    for chunk in _wrap(strip_ansi(text), width - 6)[:400]:
        rows.append(_line([("    " + chunk, "cream" if role != "tool" else "grey_lt", None)], width))
    return rows


# ── the interactive app ──────────────────────────────────────────────────────

class _Term:
    """Alternate screen + cbreak keys; restores the terminal no matter what."""

    def __enter__(self):
        import termios
        import tty
        self.fd = sys.stdin.fileno()
        self.old = termios.tcgetattr(self.fd)
        tty.setcbreak(self.fd)
        sys.stdout.write("\033[?1049h\033[?25l\033[2J")
        sys.stdout.flush()
        return self

    def __exit__(self, *exc):
        import termios
        termios.tcsetattr(self.fd, termios.TCSADRAIN, self.old)
        sys.stdout.write("\033[?25h\033[?1049l")
        sys.stdout.flush()

    def key(self, timeout=None):
        import select
        if not select.select([sys.stdin], [], [], timeout)[0]:
            return None
        ch = os.read(self.fd, 1)
        if ch == b"\x1b":
            if select.select([sys.stdin], [], [], 0.03)[0]:
                seq = os.read(self.fd, 2)
                return {b"[A": "up", b"[B": "down", b"[C": "right", b"[D": "left",
                        b"[5": "pgup", b"[6": "pgdn", b"[H": "home", b"[F": "end"}.get(seq, "esc")
            return "esc"
        if ch in (b"\r", b"\n"):
            return "enter"
        if ch == b"\x7f":
            return "backspace"
        try:
            return ch.decode("utf-8")
        except UnicodeDecodeError:
            return None

    @staticmethod
    def size():
        sz = shutil.get_terminal_size((110, 34))
        return max(60, sz.columns), max(24, sz.lines)

    @staticmethod
    def draw(rows):
        sys.stdout.write("\033[H" + "\n".join(rows) + "\033[J")
        sys.stdout.flush()

    def prompt(self, label, hint=""):
        """One-line input drawn as a band at the bottom; esc cancels."""
        text = ""
        while True:
            w, h = self.size()
            sys.stdout.write(f"\033[{h - 1};1H" + _line([(f"  {label} ▸ ", "ink", "amber"), (text + "█", "yellow", "blue_dark")], w,
                                                     dbg="blue_dark")
                             + f"\033[{h};1H" + _line([("  " + hint, "grey_lt", None)], w))
            sys.stdout.flush()
            k = self.key()
            if k == "enter":
                return text.strip()
            if k == "esc":
                return None
            if k == "backspace":
                text = text[:-1]
            elif k and len(k) == 1 and k.isprintable():
                text += k


class _ResumeNow(Exception):
    """Leave the TUI and hand this terminal to the harness (raised out of the key loop)."""

    def __init__(self, plan):
        super().__init__(plan["line"])
        self.plan = plan


RESUME_KEYS = "r resume here · t new tab · c copy"


def _resume_span(plan, flash=""):
    """The RESUME line's text span for a session (or why it can't be reopened)."""
    if flash:
        return (flash, "green" if flash.startswith("✓") else "amber", None)
    if not plan:
        return ("this harness can't reopen past sessions — read it here instead", "grey_lt", None)
    if plan["gone"] and not plan["archived"]:
        return (f"{plan['provider']} deleted this transcript before navcom archived it — read-only", "grey_lt", None)
    keys = [("   ", None, None), (" r ", "ink", "amber"), (" here ", "amber", None), (" t ", "ink", "amber"),
            (" tab ", "amber", None), (" c ", "ink", "amber"), (" copy", "amber", None)]
    if plan["gone"]:
        return [(f"navcom --resume {short_ref(plan['key'])}   (restores {plan['provider']}'s deleted file first)", "cream", None)] + keys
    return [(plan["line"], "cream", None)] + keys


def _resume_action(conn, plan, k):
    """Handle r / t / c on a session. Returns a one-line status; 'r' leaves the TUI via _ResumeNow."""
    if not plan:
        return "· this harness can't reopen past sessions"
    if k == "c":
        if plan["gone"] and not plan["archived"]:
            text = f"navcom --open {short_ref(plan['key'])}"  # can't be reopened; reading it is what's left
        else:
            text = plan["line"] if not plan["gone"] else f"navcom --resume {short_ref(plan['key'])}"
        return "✓ copied: " + text if copy_to_clipboard(text) else "· no clipboard here — " + text
    if plan["gone"]:
        ok, message = ensure_resumable(conn, plan)
        conn.commit()
        if not ok:
            return "· " + message
        plan = dict(plan, gone=False)
    if k == "t":
        ok, message = resume_in_new_tab(plan)
        return ("✓ " if ok else "· ") + message
    exe = plan["argv"][0]
    if not (shutil.which(exe) or os.path.exists(exe)):
        return f"· {exe} isn't installed here"
    if plan["cwd"] and not os.path.isdir(plan["cwd"]):
        return f"· its folder {plan['cwd']} no longer exists"
    raise _ResumeNow(plan)


def _menu_search(term, conn, query):
    import shlex
    try:
        words = shlex.split(query)
    except ValueError:
        words = query.split()
    providers, rest, tool = list(ALL_PROVIDERS), [], False
    for w in words:  # tiny subset of CLI flags, so typing them here teaches the CLI too
        if w.startswith("--") and w[2:] in ALL_PROVIDERS:
            providers = [w[2:]] if providers == ALL_PROVIDERS else providers + [w[2:]]
        elif w in ("--tool", "--tools"):
            tool = True
        else:
            rest.append(w)
    q = " ".join(rest)
    hits, cooked, note = search_hits(conn, q, providers=providers, limit=12,
                                     role="tool" if tool else None, include_tools=tool)
    groups = _group_hits(conn, hits)
    items = []  # (kind, payload)
    for g in groups:
        project, title = session_meta(conn, g["key"], g["provider"])
        items.append(("head", (g, project, title)))
        for h in g["hits"]:
            items.append(("hit", (g, h)))
    sel = next((i for i, it in enumerate(items) if it[0] == "hit"), 0)
    top, plans, flash = 0, {}, ""
    while True:
        w, hgt = term.size()
        body = [_line([("  query ", "grey_lt", None), (cooked or "(nothing searchable)", "cyan", None),
                       (f"   {len(hits)} hits in {len(groups)} sessions", "grey_lt", None)], w)]
        if note:
            body.append(_line([("  note: " + note, "amber", None)], w))
        view = hgt - 10 - len(body)
        if sel < top:
            top = sel
        if sel >= top + view:
            top = sel - view + 1
        for i, (kind, payload) in enumerate(items[top:top + view], start=top):
            if kind == "head":
                g, project, title = payload
                body.append(_line([("  ", None, None), (session_date(conn, g["key"]), "grey_lt", None),
                                   (f"  {g['provider']:<9}", "cyan", None), (pretty_project(project)[:28] + "  ", "cream", None),
                                   (title[:max(0, w - 60)], "gold", None)], w))
            else:
                g, h = payload
                on = i == sel
                snip = _trim_snippet(h.snip or h.text, w - 24).replace("«", "").replace("»", "")
                body.append(_line([("  ▶ " if on else "    ", "orange_hot", None),
                                   (f"#{h.msg_index:<6}", "grey", "amber" if on else None),
                                   (f"{h.role}: ", ROLE_COLORS.get(h.role, "cyan"), "amber" if on else None),
                                   (snip, "ink" if on else "cream", "amber" if on else None)], w))
        if not items:
            body.append(_line([("  No hits — try fewer words, or a OR b.", "amber", None)], w))
        cur = items[sel][1] if items and items[sel][0] == "hit" else None
        cli = f"navcom {query}" + (f"   →   navcom --open {display_ref(conn, cur[0]['key'], cur[0]['provider'])}:{cur[1].msg_index}"
                                    if cur else "")
        if cur and cur[0]["key"] not in plans:
            plans[cur[0]["key"]] = resume_plan(conn, cur[0]["key"], cur[0]["provider"])
        plan = plans.get(cur[0]["key"]) if cur else None
        term.draw(_screen(f"SEARCH ▸ {query}", body, w, hgt,
                          f"↑↓ move · enter read · {RESUME_KEYS} · / new search · esc back", cli,
                          resume=_resume_span(plan, flash) if cur else None))
        flash = ""
        k = term.key()
        if k in ("r", "t", "c") and cur:
            flash = _resume_action(conn, plan, k)
            continue
        if k in ("esc", "q", "left"):
            return
        if k == "/":
            return "again"
        if k in ("up", "k"):
            sel = next((i for i in range(sel - 1, -1, -1) if items[i][0] == "hit"), sel)
        elif k in ("down", "j"):
            sel = next((i for i in range(sel + 1, len(items)) if items[i][0] == "hit"), sel)
        elif k == "enter" and cur:
            _menu_view(term, conn, cur[0]["key"], cur[0]["provider"], cur[1].msg_index)


def _menu_view(term, conn, key, provider, focus=None):
    last = max_msg_index(conn, key)
    lo = max(1, (focus or 1) - 60)
    hi = (focus or 1) + 120 if focus else 300
    turns = fetch_window_rows(conn, key, [(lo, hi)])
    project, title = session_meta(conn, key, provider)
    ref = display_ref(conn, key, provider)
    plan = resume_plan(conn, key, provider)
    scroll, flash = None, ""
    while True:
        w, hgt = term.size()
        rows, anchor = [], 0
        for msg_index, role, text in turns:
            if msg_index == focus:
                anchor = len(rows)
            rows += _turn_rows(role, text, provider, msg_index, w, marked=msg_index == focus)
        if scroll is None:
            scroll = max(0, anchor - 3)
        view = hgt - 10
        scroll = max(0, min(scroll, max(0, len(rows) - view)))
        head = [_line([("  ", None, None), (session_date(conn, key), "grey_lt", None), (f"  {provider}", "cyan", None),
                       (f"  {pretty_project(project)}", "cream", None), (f"  turns {lo}-{min(hi, last)} of {last}", "grey_lt", None)], w),
                _line([("  " + (title or "")[:w - 4], "gold", None)], w)]
        cli = f"navcom --open {ref}:{focus}" if focus else f"navcom --open {ref}"
        term.draw(_screen(f"SESSION ▸ {ref}", head + rows[scroll:scroll + view - 2], w, hgt,
                          f"↑↓ scroll · pgup/pgdn page · {RESUME_KEYS} · esc back", cli, resume=_resume_span(plan, flash)))
        flash = ""
        k = term.key()
        if k in ("r", "t", "c"):
            flash = _resume_action(conn, plan, k)
            continue
        if k in ("esc", "q", "left"):
            return
        if k in ("up", "k"):
            scroll -= 1
        elif k in ("down", "j"):
            scroll += 1
        elif k == "pgup":
            scroll -= view - 4
        elif k in ("pgdn", " "):
            scroll += view - 4
        elif k == "home":
            scroll = 0
        elif k == "end":
            scroll = len(rows)


def _menu_list(term, conn, title, entries, cli, on_enter=None, resumable=False):
    """entries: [(spans, payload)]; resumable: payloads are (key, provider) and r/t/c reopen them."""
    sel, top, plans, flash = 0, 0, {}, ""
    while True:
        w, hgt = term.size()
        view = hgt - 9 - resumable
        sel = max(0, min(sel, len(entries) - 1))
        if sel < top:
            top = sel
        if sel >= top + view:
            top = sel - view + 1
        body = []
        for i, (spans, _payload) in enumerate(entries[top:top + view], start=top):
            on = i == sel and on_enter is not None
            body.append(_line([("  ▶ " if on else "    ", "orange_hot", None)]
                              + [(t, "ink" if on else fg, "amber" if on else bg) for t, fg, bg in spans], w))
        payload = entries[sel][1] if entries else None
        plan = None
        if resumable and payload:
            if payload[0] not in plans:
                plans[payload[0]] = resume_plan(conn, payload[0], payload[1])
            plan = plans[payload[0]]
        term.draw(_screen(title, body, w, hgt, ("↑↓ move · enter open · " if on_enter else "↑↓ scroll · ")
                          + (RESUME_KEYS + " · " if resumable else "") + "esc back", cli,
                          resume=_resume_span(plan, flash) if resumable else None))
        flash = ""
        k = term.key()
        if resumable and payload and k in ("r", "t", "c"):
            flash = _resume_action(conn, plan, k)
            continue
        if k in ("esc", "q", "left"):
            return
        if k in ("up", "k"):
            sel -= 1
        elif k in ("down", "j"):
            sel += 1
        elif k == "pgdn":
            sel += view
        elif k == "pgup":
            sel -= view
        elif k == "enter" and on_enter and entries:
            on_enter(entries[sel][1])


LEARN_PAGES = [
    ("THE RECIPE", "navcom <words>            find — hits grouped by session, each with a ref and #turn\n"
                   "navcom --open <ref>:<n>   read the turns around one hit, full text\n\n"
                   "That's the whole loop. Agents (Claude Code, Codex, Gemini, Copilot, …) already know it from\n"
                   "the skill card navcom installed for them."),
    ("GET BACK IN", "On any search hit or open session:   r  resume here   ·   t  new tab   ·   c  copy the command\n"
                    "The RESUME line shows exactly what runs: cd <its folder> && <harness> resume <id>.\n"
                    "From the shell: navcom --resume <ref>  (--tab for a new tab, --print to just print it).\n"
                    "A transcript its harness deleted is restored from navcom's archive first."),
    ("QUERIES", "Type anything — punctuation is safe: 10.10.1.223  don't  PR #76  main()  cerbos-wave-2\n"
                "words      all must be in one turn, prefix-matched (auth → authentication)\n"
                "a OR b     either one · a, b, c = any of them · NOT x excludes · \"exact phrase\"\n"
                "No turn has every word? navcom shows turns with ANY of them, rare words first."),
    ("NARROW", "--claude --codex --cline …   only those harnesses (30 supported)\n"
               "--here / --project syra       by working directory\n"
               "--days 7 / --since 2026-09-01 by date\n"
               "--user / --cmd / --tool       what you typed / commands run / tool output"),
    ("YOUR DATA", "Claude Code deletes transcripts after 30 days by default (since its first release).\n"
                  "navcom sets cleanupPeriodDays to 36500, turns Gemini's 30-day wipe off, keeps Qwen and\n"
                  "Hermes from pruning — only where you haven't chosen otherwise — archives every raw\n"
                  "transcript, and keeps searching sessions even after their harness deletes them.\n"
                  "Nothing leaves this machine."),
    ("AUTOMATIC", "A daily upkeep job (launchd / systemd) indexes and archives while you sleep.\n"
                  "Every agent harness gets the navcom skill card, so your agents use navcom on their own.\n"
                  "navcom --where   shows every harness, retention setting, the archive and the daily job."),
]


def run_menu(conn):
    try:
        return _run_menu(conn)
    except _ResumeNow as now:  # the terminal is restored by now; hand it to the harness
        conn.commit()
        conn.close()
        return resume_here(now.plan)


def _run_menu(conn):
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        safe_print("navcom --menu is the interactive terminal UI — run it in a terminal. "
                   "For scripts and agents: navcom --help")
        return 0
    import time
    with _Term() as term:
        w, h = term.size()
        term.draw(splash_frame(w) + [_line([], w)] * max(0, h - 20))
        stats = dashboard_stats(conn)
        term.key(timeout=2.2)
        sel = 0
        while True:
            w, h = term.size()
            term.draw(dashboard_frame(stats, sel, w, h))
            k = term.key(timeout=1.0)  # 1s tick keeps the clock live
            if k is None:
                continue
            if k in ("q", "esc"):
                return 0
            if k in ("up", "k"):
                sel = (sel - 1) % len(MENU_ACTIONS)
            elif k in ("down", "j"):
                sel = (sel + 1) % len(MENU_ACTIONS)
            elif k == "r":
                stats = dashboard_stats(conn)
            elif k in ("enter", "/"):
                action = "search" if k == "/" else MENU_ACTIONS[sel][0]
                if action == "quit":
                    return 0
                if action == "search":
                    while True:
                        q = term.prompt("SEARCH", "type words · add --claude/--codex/… or --tool · enter go · esc back")
                        if not q or _menu_search(term, conn, q) != "again":
                            break
                elif action == "recent":
                    logs = list_logs(ALL_PROVIDERS)[-80:]
                    index_logs(conn, logs, progress=False)
                    entries = []
                    for key, mtime, _size, prov in reversed(logs):
                        project, title = session_meta(conn, key, prov)
                        stamp = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M") if mtime else "?"
                        entries.append(([(stamp + "  ", "grey_lt", None), (f"{prov:<9}", "cyan", None),
                                         (f"{pretty_project(project)[:26]:<28}", "cream", None),
                                         (title[:80], "gold", None)], (key, prov)))
                    _menu_list(term, conn, "RECENT SESSIONS", entries, "navcom --sessions",
                               on_enter=lambda kp: _menu_view(term, conn, kp[0], kp[1]), resumable=True)
                elif action == "open":
                    ref = term.prompt("REF", "a ref from search results, e.g. 7ec78a59 or 7ec78a59:533 · esc back")
                    if ref:
                        m = re.match(r"^(.*?)[:#](\d+)$", ref)
                        base, focus = (m.group(1), int(m.group(2))) if m else (ref, None)
                        key, _ = resolve_ref(conn, base)
                        if key:
                            _menu_view(term, conn, key, _key_provider(conn, key), focus)
                elif action == "harness":
                    roots = provider_roots()
                    counts = collections.Counter(l[3] for l in list_logs(ALL_PROVIDERS))
                    entries = []
                    for hid in ALL_PROVIDERS:
                        n = counts.get(hid, 0)
                        where = next((str(r) for r in roots.get(hid, []) if Path(r).exists()), "")
                        label = EXTRA_HARNESSES.get(hid, {}).get("label", hid)
                        entries.append(([("● " if n else "○ ", "green" if n else "grey", None),
                                         (f"{label[:24]:<26}", "cream", None), (f"{n:>6} ", "yellow", None),
                                         (f" --{hid:<11}", "orange_hot", None), (pretty_project(where)[:60], "grey_lt", None)], None))
                    _menu_list(term, conn, f"HARNESSES ▸ {sum(1 for v in counts.values() if v)} active of {len(ALL_PROVIDERS)}",
                               entries, "navcom --where")
                elif action == "learn":
                    entries = []
                    for head, text in LEARN_PAGES:
                        entries.append(([("■ " + head, "orange_hot", None)], None))
                        for line in text.splitlines():
                            entries.append(([("  " + line, "cream", None)], None))
                        entries.append(([("", None, None)], None))
                    _menu_list(term, conn, "LEARN NAVCOM", entries, "navcom --help")
                elif action == "skill":
                    import contextlib
                    buf = io.StringIO()
                    with contextlib.redirect_stdout(buf):
                        install_skills(force=False, report=True)
                    entries = [([("  " + line, "cream", None)], None) for line in buf.getvalue().splitlines()]
                    entries += [([("", None, None)], None),
                                ([("  Every agent harness reads this card, so your agents reach for navcom themselves.", "grey_lt", None)], None)]
                    _menu_list(term, conn, "SKILL CARD", entries, "navcom --skill   ·   navcom --skill install")
                elif action == "maintain":
                    term.draw(_screen("UPKEEP ▸ running…", [_line([("  indexing every harness and archiving raw transcripts…", "cyan", None)], w)],
                                      w, h, "please wait", "navcom --maintain"))
                    import contextlib
                    buf = io.StringIO()
                    t0 = time.time()
                    with contextlib.redirect_stdout(buf):
                        cmd_maintain(conn)
                    stats = dashboard_stats(conn)
                    entries = [([("  " + line, "green", None)], None) for line in buf.getvalue().splitlines()]
                    entries.append(([(f"  done in {time.time() - t0:.1f}s", "grey_lt", None)], None))
                    _menu_list(term, conn, "UPKEEP ▸ done", entries, "navcom --maintain")

# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

HELP_TEXT = """\
navcom — instant full-text search over every AI coding session on this machine:
{HARNESSES}.
SQLite FTS5 + BM25, ~0.2s.  `navcom --where` shows which ones are on this machine.

THE RECIPE (agents: this is all you need)
  1. navcom <words>                 find: hits grouped by session → date, harness, project, ref, #turn
  2. navcom --open <ref>:<turn>     read the turns around one hit, full text
  3. navcom --resume <ref>          (humans) get back into it: cd to its folder + reopen it in its harness
  Don't grep raw session logs, don't strip punctuation, don't bother with --compact (it's the default).
  navcom --skill                    print navcom's SKILL.md skill card (already auto-installed for
                                    every harness here: Claude, Codex, Gemini, Copilot, pi, omo, opencode,
                                    goose, Qwen, Kimi, Continue, Hermes, Kiro, … — navcom --skill install)

QUERIES — type anything; navcom never errors on query syntax
  navcom cognito token refresh      all words in one turn, each prefix-matched (auth → authentication)
  navcom "exact phrase"             phrase; if it isn't found, retried as loose words
  navcom cognito OR cerbos          either one (also: or, |)
  navcom cognito, cerbos, fhir      a comma/semicolon list = any of them
  navcom deploy NOT staging         exclude (uppercase NOT)
  navcom 10.10.1.223 "don't" PR #76 main() v0.1.3 cerbos-wave-2    ← punctuation is fine
  navcom - <<'EOF'                  query from stdin when shell quoting gets awkward
  it's the "weird"; one
  EOF
  • If no turn has ALL the words, you get turns with ANY of them (rare words rank first) + a note.
  • Lowercase "and" is ignored, lowercase "or" means OR, "not" stays a normal word.
  • 2–4 distinctive words (ids, error text, file/service names) beat long sentences.

NARROW / WIDEN
  navcom deploy -n 50               hits PER HARNESS (default 20); every harness gets its own share
  navcom deploy --claude --pi       only these harnesses (--codex --gemini --omo --opencode --goose
                                    --dsh --grok --kilo, or -p claude,deepseek)
  navcom deploy --here              sessions started in this directory (or below it)
  navcom deploy --project syra      sessions whose working directory contains "syra"
  navcom deploy --days 7            active in the last 7 days (--since 2026-09-01, --since 12h, --until …)
  navcom deploy --user              only what the user typed  (--cmd: shell commands the agent ran;
                                    --role assistant: replies)
  navcom "TypeError: cannot read" --tool    search TOOL OUTPUTS: what commands printed, files read,
                                    errors, test results (left out of normal searches)
  navcom cognito --everything       conversation turns and tool outputs together
  navcom deploy --latest            only the newest session (--recent 3: newest 3 per harness;
                                    --file <ref|uuid|path>: one session)
  navcom goal --this-session        only the conversation you are in (recall after context compaction)
  navcom deploy --this              only the harness you are running in (NOT the directory — use --here)

READ
  navcom --open 7ec78a59:533        3 turns either side of #533, full text (--window-turns 8 for more)
  navcom --open 7ec78a59:520-560    a range of turns
  navcom --open 7ec78a59            the whole session, turns trimmed to 400 chars (--max-chars 0: full)
  navcom --open 7ec78a59 --user     just the user's turns
  navcom deploy --context           expand every hit in place with its neighbouring turns
  navcom --sessions                 your 20 most recent sessions, with titles
  navcom --menu                     the retro full-screen UI: live dashboard, search, read, learn

GET BACK INTO A CONVERSATION (every search ends with the copy-paste command for the top session)
  navcom --resume 7ec78a59          cd to the session's folder and reopen it in its own harness, right
                                    here (claude --resume, codex resume, opencode --session, pi --session…)
  navcom --resume 7ec78a59 --tab    … in a new tab: cmux, tmux, iTerm2, WezTerm, kitty, Terminal.app
  navcom --resume 7ec78a59 --print  just print `cd <folder> && <harness> resume <id>` (pipes/agents get this)
  navcom --restore 7ec78a59         put a deleted transcript back from navcom's archive, so
                                    `claude --resume` works again   (--restore all: every one)

OUTPUT
  default    plain text grouped by session, matches marked «like this»; colour only on a terminal
  --json     {"query","note","sessions":[{"ref","key","provider","date","project","title","resume",
              "hits":[{"msg_index","role","snippet"}]}]}
  --newest   sessions newest-first instead of best-match-first
  --max-chars N    snippet/turn length (0 = everything)

SUMMARIES (slow: they call another LLM CLI — usually better to read the hits yourself)
  navcom deploy --solo              one summary of all hits  (--summary: one per session)
  --llmgemini / --ollama pick the engine; hard limit 150s (NAVCOM_SUMMARY_TIMEOUT)

YOUR HISTORY STAYS YOURS (all automatic, silent)
  • Claude Code deletes transcripts after 30 days by default; navcom sets cleanupPeriodDays=36500
    when unset (an explicit value is respected).
  • Every Claude transcript is also kept whole, compressed, in ~/.navcom/archive (NAVCOM_ARCHIVE=all
    for every harness, =off to stop).  navcom --restore <ref> brings one back.
  • A daily `navcom --maintain` job keeps index + archive current even when nobody runs navcom
    (navcom --daily status | off | on).
  • The index keeps sessions (and tool outputs) even after a harness deletes them.

GOOD TO KNOW
  • The session you run navcom from is skipped (it would match itself); --include-self keeps it.
  • Parallel runs are fine; read-only sandboxes work (they search without refreshing the index).
  • Index: $NAVCOM_INDEX or $CODEX_HOME/navcom-index.sqlite. navcom --where shows what's found.
  • Exit codes: 0 ok (including "No hits."), 1 session/ref/file not found, 2 bad flag or value.
"""


class NavcomArgumentParser(argparse.ArgumentParser):
    """argparse, but unknown flags get a helpful hint instead of a bare usage dump."""

    def error(self, message):
        hint = ""
        match = re.search(r"unrecognized arguments?: (.+)", message)
        if match:
            import difflib
            known = [opt for action in self._actions for opt in action.option_strings]
            suggestions = []
            for bad in match.group(1).split():
                if bad.startswith("-"):
                    close = difflib.get_close_matches(bad.split("=")[0], known, n=2, cutoff=0.6)
                    if close:
                        suggestions.append(f"{bad} → did you mean {' or '.join(close)}?")
            if suggestions:
                hint = "\n  " + "\n  ".join(suggestions)
        text = (f"navcom: {message}{hint}\n"
                "Try: navcom <words>   ·   navcom --help   (search terms need no flag and no quotes)\n")
        sys.stderr.write(text)
        try:
            # agents often run `navcom … 2>/dev/null` and then read an empty result as
            # "nothing found" — when stdout is captured, say it there too
            if not sys.stdout.isatty() and not sys.stderr.isatty():
                sys.stdout.write(text)
        except Exception:
            pass
        raise SystemExit(2)


def harness_names_wrapped(width=96):
    names = ["Claude Code", "Codex", "Gemini CLI", "pi", "omo", "opencode", "goose", "DeepSeek dsh",
             "Grok Build", "Kilo"] + [h["label"] for h in EXTRA_HARNESSES.values()]
    lines, line = [], ""
    for name in names:
        piece = (", " if line else "") + name
        if len(line) + len(piece) > width:
            lines.append(line + ",")
            line = name
        else:
            line += piece
    return "\n".join(lines + [line])


def build_parser():
    parser = NavcomArgumentParser(
        prog="navcom",
        usage="navcom [words ...] [options]      (full manual below; examples in every section)",
        description=HELP_TEXT.replace("{HARNESSES}", harness_names_wrapped()),
        formatter_class=argparse.RawTextHelpFormatter,
        allow_abbrev=True,
    )
    parser.add_argument("phrase", nargs="*", metavar="words",
                        help="What to search for — no flag or quotes needed.  navcom cognito token refresh\n"
                             "Use - to read the query from stdin.")
    parser.add_argument("-q", "--query", "--search", "--q", dest="query", action="append", metavar="WORDS",
                        help="Same as bare words (repeatable; combined with any bare words).")

    g = parser.add_argument_group("harnesses (default: all of them)")
    for name in ALL_PROVIDERS:
        g.add_argument(f"--{name}", action="store_true", help=f"Only {name} sessions (combine several: --claude --pi).")
    g.add_argument("-p", "--provider", "--providers", "--harness", "--source", "--agent", action="append",
                   metavar="NAMES", help="Harnesses by name, comma-separated.  -p claude,pi  (aliases: omo-ai, pi-dev, cc…)")
    g.add_argument("--all", action="store_true", help="All harnesses (the default; accepted for compatibility).")
    g.add_argument("--this", action="store_true",
                   help="Only the harness you are running inside. NOT the directory — that's --here.")

    s = parser.add_argument_group("scope")
    s.add_argument("--here", action="store_true", help="Only sessions started in the current directory (or below it).")
    s.add_argument("--project", "--repo", "--dir", "--cwd", dest="project", metavar="TEXT",
                   help="Only sessions whose working directory contains TEXT.  --project syra")
    s.add_argument("--days", "--last-days", type=float, metavar="N", help="Only sessions active in the last N days.  --days 7")
    s.add_argument("--since", "--after", metavar="WHEN", help="Active since WHEN: 2026-09-01, 12h, 3d, 2w, today, yesterday.")
    s.add_argument("--until", "--before", metavar="WHEN", help="Last active before WHEN (same formats as --since).")
    s.add_argument("--role", choices=["user", "assistant", "cmd", "tool"], help="Only this kind of turn.")
    s.add_argument("--tool", "--tools", "--outputs", "--output", dest="role", action="store_const", const="tool",
                   help="Search only tool outputs: what commands printed, files read, errors, test results.\n"
                        'navcom "TypeError: cannot read" --tool')
    s.add_argument("--everything", "--all-turns", action="store_true",
                   help="Search conversation turns AND tool outputs together.")
    s.add_argument("--user", dest="role", action="store_const", const="user", help="Only what the user typed (= --role user).")
    s.add_argument("--cmd", "--cmds", "--commands", dest="role", action="store_const", const="cmd",
                   help="Only shell commands the agent ran (= --role cmd).")
    s.add_argument("--latest", "--last", action="store_true", help="Only the single newest session.")
    s.add_argument("--recent", type=int, default=0, metavar="N", help="Only the N newest sessions of each harness.")
    s.add_argument("--file", "--session", metavar="REF",
                   help="One session: a ref from the results, a uuid, a file name, a path, or a --list number.")
    s.add_argument("--this-session", "--current", "--current-session", "--me", dest="this_session", action="store_true",
                   help="Only the conversation you are in (recall after context compaction).")
    s.add_argument("--include-self", action="store_true",
                   help="Keep hits from the session navcom runs inside, and past navcom commands (skipped by default).")
    s.add_argument("--all-logs", action="store_true", help=argparse.SUPPRESS)

    o = parser.add_argument_group("output")
    o.add_argument("-n", "--limit", "--max", "--top", "--max-results", "--head", type=int, default=None, metavar="N",
                   help=f"Hits per harness (default {DEFAULT_LIMIT}; 0 = no limit). Every harness gets its own N.\n"
                        "With no query / --list: how many sessions to list.")
    o.add_argument("--open", "--show", "--read", "--view", dest="open_ref", metavar="REF[:N]",
                   help="Read a session by the ref printed in results.  --open 7ec78a59:533  (3 turns either side)\n"
                        "--open 7ec78a59:520-560 (range)   --open 7ec78a59 (whole session)")
    o.add_argument("--resume", "--reopen", dest="resume_ref", metavar="REF",
                   help="Get back into that conversation yourself: cd to its folder and reopen it in its harness\n"
                        "(claude --resume, codex resume, …), right here in this terminal.\n"
                        "--resume REF --tab   in a new tab instead (cmux, tmux, iTerm2, WezTerm, kitty, Terminal)\n"
                        "--resume REF --print just print the command (also what pipes and agents get)")
    o.add_argument("--tab", "--new-tab", action="store_true", help=argparse.SUPPRESS)
    o.add_argument("--print", "--print-only", dest="print_only", action="store_true", help=argparse.SUPPRESS)
    o.add_argument("--context", "--full", "--expand", "--verbose", action="store_true",
                   help="Expand every hit in place with its neighbouring turns.")
    o.add_argument("--window-turns", "--window", "--turns", "--around", type=int, metavar="N",
                   help="Turns shown either side of a hit (implies --context; default 1, with --open 3).")
    o.add_argument("--max-chars", "--chars", "--width", type=int, default=None, metavar="N",
                   help="Trim each snippet/turn to N chars (0 = everything). Defaults: 220 hits, 200 context,\n"
                        "3000 --open REF:N, 400 --open REF.")
    o.add_argument("--json", action="store_true",
                   help='JSON: {"query","note","sessions":[{"ref","key","provider","date","project","title","resume","hits":[…]}]}')
    o.add_argument("--newest", "--recent-first", "--sort-date", action="store_true",
                   help="Order sessions newest-first instead of best-match-first.")
    o.add_argument("--compact", "--brief", "--short", action="store_true",
                   help="Accepted for compatibility — compact is already the default.")
    o.add_argument("--any", "--or", action="store_true", help="Match ANY of the words instead of all of them.")
    o.add_argument("--no-prefix", "--exact", action="store_true",
                   help="Whole words only (no auth → authentication), and FTS5 syntax is passed through raw.")
    o.add_argument("--snippet-tokens", type=int, default=32, metavar="N", help="Snippet length in words (max 64).")
    o.add_argument("--color", choices=["auto", "always", "never"], default="auto",
                   help="Colour (default auto: only on a terminal, never into a pipe).")
    o.add_argument("--no-color", dest="color", action="store_const", const="never", help=argparse.SUPPRESS)
    o.add_argument("--verbosity", type=int, default=None, help=argparse.SUPPRESS)
    o.add_argument("--sessions", "--recent-sessions", action="store_true",
                   help="Your most recent sessions, with titles (-n for how many; harness/date/project filters apply).")
    o.add_argument("--list", "--ls", action="store_true",
                   help="List session files with --file numbers (newest 50; -n 0 for all; honours --recent/harnesses).")
    o.add_argument("--menu", "--tui", "--ui", action="store_true",
                   help="The retro full-screen UI: live dashboard (retention, history, activity), search, read,\n"
                        "learn the commands. Humans only — agents should use the plain commands.")

    m = parser.add_argument_group("summaries (slow: they call another LLM CLI)")
    m.add_argument("--solo", action="store_true", help="One consolidated summary of all hits.  navcom deploy --solo")
    m.add_argument("--summary", "--summarize", action="store_true", help="One summary per matching session.")
    m.add_argument("--prompt", metavar="TEXT", help='Your own summary instruction (implies --summary).  --prompt "list every table"')
    m.add_argument("--prompt-file", metavar="PATH", help="Prompt template file with a {{transcript}} placeholder.")
    m.add_argument("--llmgemini", action="store_true", help="Summarize with Gemini first.")
    m.add_argument("--ollama", action="store_true", help="Summarize with local Ollama.")
    m.add_argument("--summary-model", default=SUMMARY_MODEL_DEFAULT, metavar="MODEL", help="Ollama model (default gemma3:4b).")
    m.add_argument("--summary-mode", default="chrono", choices=["chrono", "reduce"], help=argparse.SUPPRESS)
    m.add_argument("--dump-dir", metavar="DIR", help="Also write summary inputs/outputs to DIR.")

    x = parser.add_argument_group("index & setup")
    x.add_argument("--where", "--doctor", "--status", action="store_true",
                   help="Where each harness keeps its sessions, and index stats.")
    x.add_argument("--reindex", action="store_true", help="Re-read the selected sessions from scratch.")
    x.add_argument("--index", metavar="PATH", help="Index file (default $NAVCOM_INDEX or $CODEX_HOME/navcom-index.sqlite).")
    x.add_argument("--skill", "--skills", nargs="?", const="show", metavar="ACTION",
                   help="navcom's agent skill card (SKILL.md).  navcom --skill            print it\n"
                        "navcom --skill install   (re)install it for every harness here, and show where\n"
                        "navcom --skill list | export   Skillflag-compatible listing / tar export")
    x.add_argument("--install-skills", action="store_true", help=argparse.SUPPRESS)
    x.add_argument("--restore", metavar="REF",
                   help="Put an archived transcript back on disk so its harness can resume it (or 'all' = every\n"
                        "archived transcript that was deleted).  navcom --restore 7ec78a59")
    x.add_argument("--maintain", action="store_true",
                   help="Full catch-up with no time limits: index everything, re-parse old rows, archive.\n"
                        "The daily background job runs this.")
    x.add_argument("--daily", choices=["on", "off", "status"],
                   help="The daily `navcom --maintain` job (installed automatically; off removes it).")
    x.add_argument("-V", "-v", "--version", action="version", version=f"navcom {NAVCOM_VERSION}")
    return parser


def _parse_when(value):
    """YYYY-MM-DD[ HH:MM] or relative 90m / 12h / 3d / 2w / 1mo → epoch seconds."""
    text = (value or "").strip().lower()
    rel = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(m|min|mins|minutes?|h|hr|hrs|hours?|d|days?|w|wk|weeks?|mo|months?)", text)
    now = datetime.now().timestamp()
    if rel:
        n = float(rel.group(1))
        unit = rel.group(2)
        if unit.startswith("mo"):
            seconds = n * 30 * 86400
        elif unit.startswith("m"):
            seconds = n * 60
        elif unit.startswith("h"):
            seconds = n * 3600
        elif unit.startswith("w"):
            seconds = n * 7 * 86400
        else:
            seconds = n * 86400
        return now - seconds
    if text in ("today",):
        return datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    if text in ("yesterday",):
        return datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp() - 86400
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y/%m/%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(value.strip(), fmt).timestamp()
        except ValueError:
            continue
    raise ValueError(f"can't read date {value!r} — use YYYY-MM-DD or 12h / 3d / 2w")


def _detect_current_provider(logs):
    env = os.environ
    if env.get("CLAUDECODE") or env.get("CLAUDE_CODE_ENTRYPOINT"):
        return "claude"
    if env.get("GEMINI_CLI"):
        return "gemini"
    if env.get("OPENCODE") or env.get("OPENCODE_BIN_PATH"):
        return "opencode"
    if env.get("GOOSE_TERMINAL") or env.get("GOOSE_SESSION_ID"):
        return "goose"
    if any(k.startswith("CODEX_") for k in env) and not env.get("CODEX_HOME_ONLY"):
        if env.get("CODEX_SANDBOX") or env.get("CODEX_THREAD_ID") or env.get("CODEX_MANAGED_BY_NPM"):
            return "codex"
    if any(k.startswith("OMO_") for k in env):
        return "omo"
    if any(k.startswith("PI_CODING_AGENT") for k in env):
        return "pi"
    return logs[-1][3] if logs else None


SESSION_ID_ENV = ("CLAUDE_CODE_SESSION_ID", "CODEX_THREAD_ID", "CODEX_SESSION_ID", "GOOSE_SESSION_ID",
                  "OPENCODE_SESSION_ID", "PI_SESSION_ID", "OMO_SESSION_ID", "GEMINI_SESSION_ID")


def env_session_log(logs):
    """The log of the conversation navcom runs inside — only when the harness says so."""
    for var in SESSION_ID_ENV:
        sid = os.environ.get(var)
        if not sid:
            continue
        for log in reversed(logs):
            if session_ref(log[0]) == sid or log[0].endswith("#" + sid):
                return log
    return None


def current_session_log(logs):
    """The log of the conversation navcom is being run from, if the harness tells us."""
    for var in SESSION_ID_ENV:
        sid = os.environ.get(var)
        if not sid:
            continue
        for log in reversed(logs):
            ref = session_ref(log[0])
            if ref == sid or log[0].endswith("#" + sid) or sid in Path(log[0].split("#")[0]).name:
                return log
    detected = _detect_current_provider(logs)
    same = [log for log in logs if log[3] == detected]
    return same[-1] if same else (logs[-1] if logs else None)


def resolve_providers(args, logs_for_detect=None):
    chosen = [name for name in ALL_PROVIDERS if getattr(args, name, False)]
    for spec in args.provider or []:
        for raw in re.split(r"[,\s]+", spec):
            name = PROVIDER_ALIASES.get(raw.strip().lower(), raw.strip().lower())
            if not name:
                continue
            if name not in ALL_PROVIDERS:
                raise ValueError(f"unknown harness {raw!r} — known: {', '.join(ALL_PROVIDERS)}")
            if name not in chosen:
                chosen.append(name)
    if args.this:
        detected = _detect_current_provider(logs_for_detect if logs_for_detect is not None else list_logs(ALL_PROVIDERS))
        if detected and detected not in chosen:
            chosen.append(detected)
    return chosen or list(ALL_PROVIDERS)


def _gather_query(args):
    parts = []
    for q in args.query or []:
        parts.append(q)
    parts.extend(args.phrase or [])
    if any(p.strip() == "-" for p in parts):
        parts = [p for p in parts if p.strip() != "-"]
        try:
            parts.append(sys.stdin.read())
        except Exception:
            pass
    query = " ".join(p for p in parts if p is not None).strip()
    # "navcom search foo" / "navcom find foo" — the verb isn't part of the query
    first, _, rest = query.partition(" ")
    if first.lower() in ("search", "find", "query", "grep", "lookup") and rest.strip():
        query = rest.strip()
    return query or None


def _key_provider(conn, key):
    return _PROVIDER_BY_KEY.get(key) or detect_provider_from_path(key)


def filter_keys(conn, keys, providers, args):
    """Apply provider/date/project filters over index keys. Returns list or None (= no filter)."""
    since = until = None
    if args.days is not None:
        since = datetime.now().timestamp() - args.days * 86400
    if args.since:
        since = _parse_when(args.since)
    if args.until:
        until = _parse_when(args.until)
    want_project = args.project or args.here
    if keys is None and since is None and until is None and not want_project:
        return None
    if keys is None:
        rows = conn.execute("SELECT file, mtime FROM file_state").fetchall()
    else:
        wanted = set(keys)
        rows = [r for r in conn.execute("SELECT file, mtime FROM file_state").fetchall() if r[0] in wanted]
    out = []
    here_set = set()
    if args.here:
        real = os.path.realpath(os.getcwd())
        pwd = os.environ.get("PWD")
        for cand in (pwd if pwd and os.path.realpath(pwd) == real else None, os.getcwd(), real):
            if cand:
                here_set.add(_norm_project(cand))
    needle = _norm_project(args.project) if args.project else None
    project_cache = {}
    if want_project:
        project_cache = {f: p for f, p in conn.execute("SELECT file, project FROM file_meta")}
        _KNOWN_CWDS.update(p for p in project_cache.values() if p and p.startswith("/"))
    new_meta = []
    for key, mtime in rows:
        if _key_provider(conn, key) not in providers:
            continue
        if since is not None and (mtime or 0) < since:
            continue
        if until is not None and (mtime or 0) >= until:
            continue
        if want_project:
            project = project_cache.get(key)
            if project is None:
                project = _project_from_key(key, _key_provider(conn, key))
                new_meta.append((key, _key_provider(conn, key), project))
            norm = _norm_project(project)
            if here_set and not any(norm == h or norm.startswith(h + "-") for h in here_set):
                continue
            if needle is not None and needle not in norm:
                continue
        out.append(key)
    if new_meta and not INDEX_READ_ONLY:
        try:
            conn.executemany(
                "INSERT OR IGNORE INTO file_meta (file, provider, project, title) VALUES (?, ?, ?, NULL)", new_meta
            )
            conn.commit()
        except sqlite3.OperationalError:
            pass
    return out


def _trim_snippet(snippet, max_chars):
    text = re.sub(r"\s+", " ", strip_ansi(snippet or "")).strip()
    if not max_chars or len(text) <= max_chars:
        return text
    mark = text.find("«")
    if mark == -1 or mark < max_chars * 0.6:
        return text[:max_chars].rstrip() + "…"
    start = max(0, mark - max_chars // 3)
    return "…" + text[start : start + max_chars].strip() + "…"


def _group_hits(conn, hits, newest=False):
    groups = {}
    for rank, hit in enumerate(hits):
        g = groups.setdefault(hit.file, {"key": hit.file, "best": rank, "hits": [], "provider": hit.provider})
        g["hits"].append(hit)
    ordered = list(groups.values())
    for g in ordered:
        row = conn.execute("SELECT mtime FROM file_state WHERE file=?", (g["key"],)).fetchone()
        g["mtime"] = row[0] if row else 0
        g["hits"].sort(key=lambda h: h.msg_index)
    if newest:
        ordered.sort(key=lambda g: -g["mtime"])
    else:
        ordered.sort(key=lambda g: g["best"])
    return ordered


def _session_header(conn, i, g):
    project, title = session_meta(conn, g["key"], g["provider"])
    date = session_date(conn, g["key"])
    prov = g["provider"] or detect_provider_from_path(g["key"])
    count = len(g["hits"])
    proj = pretty_project(project) or "-"
    hits_label = f"{count} hit" + ("s" if count != 1 else "")
    return f"[{i}] {date}  {STYLE.provider(prov, f'{prov:8s}')} {proj}  ref {display_ref(conn, g['key'], prov)}  ({hits_label})"


def print_compact(conn, groups, max_chars, total_hits, cooked, note):
    sessions = len(groups)
    safe_print(f"navcom: {total_hits} hit{'s' if total_hits != 1 else ''} in {sessions} session{'s' if sessions != 1 else ''} · query: {cooked}")
    if note:
        safe_print(STYLE.warn(f"note: {note}"))
    for i, g in enumerate(groups, 1):
        safe_print(_session_header(conn, i, g))
        for hit in g["hits"]:
            snippet = hit.snip if hit.snip else hit.text
            snippet = _trim_snippet(snippet, max_chars)
            safe_print(f"    {STYLE.dim('#' + str(hit.msg_index))} {STYLE.role(hit.role + ':')} {STYLE.highlight(snippet)}")
    if groups:
        first = groups[0]
        safe_print(STYLE.dim(
            f"→ read around a hit: navcom --open {display_ref(conn, first['key'], first['provider'])}:{first['hits'][0].msg_index}"
            "   · expand all: add --context"
        ))
        hint = resume_hint(conn, groups)
        if hint:
            safe_print(STYLE.dim(hint))


def resume_hint(conn, groups):
    """Footer line: the copy-paste command that reopens the best still-resumable session."""
    for g in groups[:5]:
        try:
            plan = resume_plan(conn, g["key"], g["provider"])
        except Exception:
            plan = None
        if plan and (not plan["gone"] or plan["archived"]):
            ref = display_ref(conn, g["key"], g["provider"])
            line = plan["line"] if not plan["gone"] else f"navcom --resume {ref}"
            return f"→ get back into [{groups.index(g) + 1}] yourself: {line}   · any session: navcom --resume <ref> (--tab: new tab)"
    return ""


def print_json(conn, groups, cooked, note):
    out = {"query": cooked, "note": note or None, "sessions": []}
    for g in groups:
        project, title = session_meta(conn, g["key"], g["provider"])
        out["sessions"].append({
            "ref": display_ref(conn, g["key"], g["provider"]),
            "key": g["key"],
            "provider": g["provider"],
            "date": session_date(conn, g["key"]),
            "project": project,
            "title": title,
            "resume": _resume_json(conn, g["key"], g["provider"]),
            "hits": [
                {"msg_index": h.msg_index, "role": h.role, "snippet": re.sub(r"\s+", " ", h.snip or "").strip()}
                for h in g["hits"]
            ],
        })
    safe_print(json.dumps(out, indent=2, ensure_ascii=False))


def _resume_json(conn, key, provider):
    plan = resume_plan(conn, key, provider)
    if not plan or (plan["gone"] and not plan["archived"]):
        return None
    return plan["line"] if not plan["gone"] else f"navcom --resume {short_ref(key)}"


def print_context(conn, groups, window, max_chars):
    for i, g in enumerate(groups, 1):
        prov = g["provider"] or detect_provider_from_path(g["key"])
        spans = window_ranges_for_hits(g["hits"], window)[g["key"]]
        safe_print(_session_header(conn, i, g))
        safe_print(STYLE.dim(f"    {g['key']}"))
        hit_ids = {h.msg_index for h in g["hits"]}
        for msg_index, role, text in fetch_window_rows(conn, g["key"], spans):
            if max_chars and len(text) > max_chars:
                text = text[:max_chars] + "…"
            marker = "▶ " if msg_index in hit_ids else ""
            safe_print(marker + format_turn(role, text, prov, msg_index))
        safe_print("")


_REF_CACHE = {}


def _ref_like(ref):
    """SQL LIKE pattern that finds the index keys a ref could name."""
    clean = ref.replace("%", "").replace("_", "\\_")
    if "@" in clean and clean.rsplit("@", 1)[1].isdigit():
        folder, n = clean.rsplit("@", 1)
        return f"%/{folder}/%#{n}"
    return f"%{clean}%"


def display_ref(conn, key, provider=None):
    """The ref to print for a session: its short ref, prefixed with the harness when that
    short ref also names another indexed session (omo imports pi sessions under the same id)."""
    ref = short_ref(key)
    if ref not in _REF_CACHE:
        others = {f for (f,) in conn.execute("SELECT file FROM file_state WHERE file LIKE ? ESCAPE '\\'",
                                             (_ref_like(ref),)) if short_ref(f) == ref}
        _REF_CACHE[ref] = len(others | {key}) > 1
    if _REF_CACHE[ref]:
        return f"{provider or detect_provider_from_path(key)}:{ref}"
    return ref


def resolve_ref(conn, ref, providers=None):
    """REF → index key. Accepts a full key/path, a file stem, a uuid prefix, an opencode/goose id,
    or HARNESS:REF to pick one of several sessions sharing an id."""
    ref = ref.strip()
    strict = False
    prefix, _, rest = ref.partition(":")
    if rest and prefix.lower() in ALL_PROVIDERS:
        providers, ref, strict = [prefix.lower()], rest, True
    if conn.execute("SELECT 1 FROM file_state WHERE file=?", (ref,)).fetchone():
        return ref, []
    rows = conn.execute(
        "SELECT file, mtime FROM file_state WHERE file LIKE ? ESCAPE '\\' ORDER BY mtime DESC", (_ref_like(ref),)
    ).fetchall()
    exact = [r for r in rows if session_ref(r[0]) == ref or short_ref(r[0]) == ref]
    matches = exact or [
        r for r in rows
        if session_ref(r[0]).startswith(ref) or session_ref(r[0]).endswith(ref)
        or Path(r[0].split("#")[-1]).stem.startswith(ref)
    ]
    if not matches:
        matches = rows
    if providers:
        scoped = [r for r in matches if _key_provider(conn, r[0]) in providers]
        matches = scoped if (scoped or strict) else matches
    if not matches:
        return None, []
    return matches[0][0], [m[0] for m in matches[1:]]


# ─────────────────────────────────────────────────────────────────────────────
# Resume: get back into a past conversation yourself (cd to its folder, reopen it)
# ─────────────────────────────────────────────────────────────────────────────

_UUID_ANY = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def _json_field(path, *names, limit=65536):
    """First of `names` found in a JSON / JSONL file's head (no full parse of big files)."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            head = handle.read(limit)
    except OSError:
        return ""
    for name in names:
        match = re.search(rf'"{re.escape(name)}"\s*:\s*"([^"]+)"', head)
        if match:
            return match.group(1)
    return ""


def _grok_build_bin():
    # /opt/homebrew/bin/grok is often the community grok-cli; Grok Build installs to ~/.grok/bin
    home_bin = Path.home() / ".grok" / "bin" / "grok"
    return str(home_bin) if home_bin.exists() else "grok"


def _resume_claude(key, ref):
    match = re.search(r"/([0-9a-f-]{36})/subagents/", key)  # a subagent sidechain → its parent session
    return ["claude", "--resume", match.group(1) if match else ref]


def _resume_gemini(key, ref):
    sid = _json_field(key, "sessionId") or ref
    return ["gemini", "--resume", sid]


def _resume_vibe(key, ref):
    return ["vibe", "--resume", ref.rsplit("_", 1)[-1]]  # vibe matches the short id in session_<date>_<time>_<id>


def _resume_kimi(key, ref):
    folder = next((part for part in Path(key).parts if part.startswith("session_")), f"session_{ref}")
    return ["kimi", "-S", folder]  # Kimi wants the session_<uuid> folder name, not the bare uuid


def _resume_kiro(key, ref):
    if "#" in key:  # v1 SQLite: conversations are keyed by folder, so "resume" = the latest one there
        return None
    return ["kiro-cli", "--v3", "--resume-id", ref] if ref.startswith("sess_") else ["kiro-cli", "chat", "--resume-id", ref]


def _resume_goose(key, ref):
    if key.endswith(".jsonl"):  # pre-SQLite goose named sessions by file
        return ["goose", "session", "--resume", "--name", ref]
    return ["goose", "session", "--resume", "--session-id", ref]


def _resume_cline(key, ref):
    if "saoudrizwan.claude-dev" in key or "/tasks/" in key:
        return None  # a VS Code extension task: the Cline CLI can't open those
    return ["cline", "--id", ref]


def _resume_codewhale(key, ref):
    return ["deepseek", "resume", ref] if "/.deepseek/" in key else ["codewhale", "--resume", ref]


def _resume_amp(key, ref):
    return ["amp", "threads", "continue", ref if ref.startswith("T-") else f"T-{ref}"]


# provider → argv builder (key, ref) → argv (None: can't).  navcom cds into the session's folder first:
# most harnesses file sessions per folder, and the rest at least run their tools there.
RESUME_COMMANDS = {
    "claude": _resume_claude,
    "codex": lambda key, ref: ["codex", "resume", ref],
    "gemini": _resume_gemini,
    "opencode": lambda key, ref: ["opencode", "--session", ref],
    "kilo": lambda key, ref: ["kilo", "--session", ref],
    "pi": lambda key, ref: ["pi", "--session", ref],
    "omo": lambda key, ref: ["omo", "--session", ref],
    "goose": _resume_goose,
    "dsh": lambda key, ref: ["dsh", "tui", "--resume", f"session-{ref}"],
    "grok": lambda key, ref: [_grok_build_bin(), "--resume", ref],
    "qwen": lambda key, ref: ["qwen", "--resume", ref],
    "kimi": _resume_kimi,
    "crush": lambda key, ref: ["crush", "--session", ref],
    "copilot": lambda key, ref: ["copilot", "--resume", ref],
    "cline": _resume_cline,
    "codewhale": _resume_codewhale,
    "reasonix": lambda key, ref: ["reasonix", "--resume", ref],
    "deepcode": lambda key, ref: ["deepcode", "-r", ref],
    "hermes": lambda key, ref: ["hermes", "--resume", ref],
    "openhands": lambda key, ref: ["openhands", "--resume", ref],
    "vibe": _resume_vibe,
    "agy": lambda key, ref: ["agy", "--conversation", ref],
    "droid": lambda key, ref: ["droid", "--resume", ref],
    "cursor": lambda key, ref: ["cursor-agent", "--resume", ref],
    "kiro": _resume_kiro,
    "amp": _resume_amp,
    "auggie": lambda key, ref: ["auggie", "--resume", ref],
    "grokdev": lambda key, ref: ["grok", "--session", ref],
}
# harnesses with no resume-by-id: the closest thing, and what it really does
RESUME_FALLBACKS = {
    "continue": lambda key, ref: (["cn", "--fork", ref], "Continue can't reopen a session by id — this starts a "
                                                          "new session with a copy of its history (cn --fork)"),
    "aider": lambda key, ref: (["aider", "--restore-chat-history"], "Aider has no per-session resume — this reloads "
                                                                    "the folder's whole chat history"),
    "kiro": lambda key, ref: (["kiro-cli", "chat", "--resume"], "this older Kiro conversation is stored per folder — "
                                                                "this reopens the latest one there"),
}


def resume_plan(conn, key, provider=None):
    """How to get back into a session: {cwd, argv, line, exact, note}. None if the harness can't."""
    provider = provider or _key_provider(conn, key)
    project, _title = session_meta(conn, key, provider)
    if project.startswith("-"):
        project = decode_encoded_dir(project) or project
    cwd = project if project and project.startswith("/") else ""
    if provider == "claude" or not cwd:
        # the transcript's own record of where it ran beats a folder name decoded from '-Users-t-x'
        recorded = _json_field(key, "cwd") if "#" not in key and os.path.isfile(key) else ""
        if recorded.startswith("/"):
            cwd = recorded
    ref = session_ref(key)
    note = ""
    argv, exact = (RESUME_COMMANDS[provider](key, ref) if provider in RESUME_COMMANDS else None), True
    if not argv and provider in RESUME_FALLBACKS:
        argv, note = RESUME_FALLBACKS[provider](key, ref)
        exact = False
    if not argv:
        return None
    shown = [_shell_path(argv[0]) if argv[0].startswith("/") else argv[0]] + argv[1:]
    line = " ".join([shown[0], shlex.join(shown[1:])]) if len(shown) > 1 else shown[0]
    if cwd:
        line = f"cd {_shell_path(cwd)} && {line}"
    store = key.split("#", 1)[0]
    gone = not os.path.exists(store)
    archived = False
    if gone:
        try:
            _ensure_archive_table(conn)
            row = conn.execute("SELECT path FROM archive_state WHERE file=?", (key,)).fetchone()
            archived = bool(row and Path(row[0]).exists())
        except sqlite3.Error:
            pass
    return {"cwd": cwd, "argv": argv, "line": line, "exact": exact, "note": note, "provider": provider,
            "key": key, "gone": gone, "archived": archived}


def ensure_resumable(conn, plan):
    """A session its harness already deleted: put navcom's archived copy back first. → (ok, message)."""
    if not plan["gone"]:
        return True, ""
    if plan["archived"]:
        import contextlib
        with contextlib.redirect_stdout(io.StringIO()):
            cmd_restore(conn, plan["key"], None)
        if os.path.exists(plan["key"].split("#", 1)[0]):
            return True, f"{plan['provider']} had deleted this session — restored it from navcom's archive"
    return False, (f"{plan['provider']} deleted this session's transcript and navcom's archive doesn't have it, "
                   f"so {plan['provider']} can't reopen it. navcom still has the text: navcom --open {short_ref(plan['key'])}")


def _shell_path(path):
    """~/dev/x when that is safe to type unquoted, else a quoted absolute path."""
    home = str(Path.home())
    if path == home or path.startswith(home + "/"):
        rest = path[len(home):]
        if re.fullmatch(r"[\w./@+-]*", rest):
            return "~" + rest
    return shlex.quote(path)


def resume_here(plan):
    """Replace navcom with the harness, in the session's folder, in this terminal."""
    exe = plan["argv"][0]
    if not (shutil.which(exe) or os.path.exists(exe)):
        sys.stderr.write(f"navcom: {exe} isn't installed here. The command is:\n  {plan['line']}\n")
        return 1
    if plan["cwd"]:
        if not os.path.isdir(plan["cwd"]):
            sys.stderr.write(f"navcom: the session's folder {plan['cwd']} no longer exists. The command is:\n  {plan['line']}\n")
            return 1
        os.chdir(plan["cwd"])
    sys.stderr.write(f"navcom ▸ {plan['line']}\n")
    sys.stderr.flush()
    try:
        os.execvp(exe, plan["argv"])
    except OSError as exc:
        sys.stderr.write(f"navcom: could not start {exe}: {exc}\n")
        return 1


def _tab_title(plan):
    return f"{plan['provider']} · {Path(plan['cwd']).name or '~'}" if plan["cwd"] else plan["provider"]


def resume_in_new_tab(plan):
    """Open the resume command in a new tab of the terminal you're in. → (ok, message)."""
    import subprocess
    cwd = plan["cwd"] if plan["cwd"] and os.path.isdir(plan["cwd"]) else str(Path.home())
    shell = os.environ.get("SHELL") or "/bin/sh"
    keep_open = [shell, "-lic", f"{shlex.join(plan['argv'])}; exec {shlex.quote(shell)} -l"]
    title = _tab_title(plan)

    def run(cmd, env=None):
        try:
            done = subprocess.run(cmd, capture_output=True, text=True, timeout=15, env=env)
            return done.returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False

    term = os.environ.get("TERM_PROGRAM", "")
    cmux = os.environ.get("CMUX_BUNDLED_CLI_PATH") or shutil.which("cmux")
    if cmux and (os.environ.get("CMUX_WORKSPACE_ID") or os.environ.get("CMUX_SOCKET_PATH")):
        env = dict(os.environ, CMUX_QUIET="1")
        if run([cmux, "new-workspace", "--name", title, "--cwd", cwd, "--command", shlex.join(plan["argv"])], env):
            return True, "opened in a new cmux workspace"
    if os.environ.get("TMUX") and shutil.which("tmux"):
        if run(["tmux", "new-window", "-c", cwd, "-n", title, shlex.join(keep_open)]):
            return True, "opened in a new tmux window"
    if os.environ.get("WEZTERM_PANE") and shutil.which("wezterm"):
        if run(["wezterm", "cli", "spawn", "--cwd", cwd, "--"] + keep_open):
            return True, "opened in a new WezTerm tab"
    if os.environ.get("KITTY_WINDOW_ID") and shutil.which("kitty"):
        if run(["kitty", "@", "launch", "--type=tab", "--cwd", cwd, "--tab-title", title] + keep_open):
            return True, "opened in a new kitty tab"
    line = f"cd {shlex.quote(cwd)} && {shlex.join(plan['argv'])}"
    if sys.platform == "darwin" and term == "iTerm.app":
        script = ('tell application "iTerm2" to tell current window\n'
                  '  set t to (create tab with default profile)\n'
                  f'  tell current session of t to write text {_applescript_str(line)}\nend tell')
        if run(["osascript", "-e", script]):
            return True, "opened in a new iTerm2 tab"
    if sys.platform == "darwin" and term == "Apple_Terminal":
        if run(["osascript", "-e", f'tell application "Terminal" to do script {_applescript_str(line)}',
                "-e", 'tell application "Terminal" to activate']):
            return True, "opened in a new Terminal window"
    if sys.platform == "darwin" and term == "ghostty":
        if run(["open", "-na", "Ghostty.app", "--args", f"--working-directory={cwd}", "-e"] + keep_open):
            return True, "opened in a new Ghostty window"
    if sys.platform.startswith("linux") and shutil.which("gnome-terminal") and \
            (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        if run(["gnome-terminal", "--tab", f"--working-directory={cwd}", "--"] + keep_open):
            return True, "opened in a new terminal tab"
    copied = copy_to_clipboard(plan["line"])
    return False, ("can't open a tab in this terminal — " + ("command copied, paste it in a new tab" if copied
                                                             else f"run: {plan['line']}"))


def _applescript_str(text):
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def copy_to_clipboard(text):
    """System clipboard (pbcopy / wl-copy / xclip / xsel / clip), else OSC 52 via the terminal."""
    import subprocess
    for cmd in (["pbcopy"], ["wl-copy"], ["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"], ["clip.exe"]):
        if shutil.which(cmd[0]):
            try:
                subprocess.run(cmd, input=text, text=True, timeout=5, check=True,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return True
            except (OSError, subprocess.SubprocessError):
                continue
    if sys.stdout.isatty():
        import base64
        sys.stdout.write("\033]52;c;" + base64.b64encode(text.encode()).decode() + "\a")
        sys.stdout.flush()
        return True
    return False


def cmd_resume(conn, args, providers):
    ref = args.resume_ref.strip()
    if not Path(ref).exists():
        ref = re.sub(r"[:#]\d+(-\d+)?$", "", ref)  # a hit ref (abc123:73) names its session
    key, _others = resolve_ref(conn, ref, providers)
    if not key:
        safe_print(f"navcom: no session matches ref {ref!r}. Refs are printed in search results (e.g. 'ref 395e14b4').")
        return 1
    plan = resume_plan(conn, key)
    if not plan:
        prov = _key_provider(conn, key)
        safe_print(f"navcom: {prov} has no way to reopen a past session from the command line. "
                   f"Read it instead: navcom --open {display_ref(conn, key, prov)}")
        return 1
    if plan["gone"] and not plan["archived"]:
        _ok, message = ensure_resumable(conn, plan)
        safe_print(f"navcom: {message}")
        return 1
    if plan["note"]:
        sys.stderr.write(f"navcom: {plan['note']}\n")
    interactive = sys.stdin.isatty() and sys.stdout.isatty()
    if (args.print_only or not interactive) and not args.tab:
        if plan["gone"]:
            sys.stderr.write(f"navcom: {plan['provider']} deleted this session — `navcom --resume {short_ref(key)}` "
                             "restores it from the archive first (or: navcom --restore REF)\n")
        safe_print(plan["line"])  # scripts, agents, `| pbcopy`: just the command
        return 0
    if plan["gone"]:
        ok, message = ensure_resumable(conn, plan)
        conn.commit()
        sys.stderr.write(f"navcom: {message}\n")
        if not ok:
            return 1
    if args.tab:
        ok, message = resume_in_new_tab(plan)
        safe_print(f"{'✓' if ok else '·'} {message}\n  {plan['line']}")
        return 0 if ok else 1
    conn.close()
    return resume_here(plan)


def cmd_open(conn, args, providers):
    ref = args.open_ref
    lo = hi = None
    match = re.match(r"^(.*?)[:#](\d+)(?:-(\d+))?$", ref)
    if match and not Path(ref).exists():
        ref, lo = match.group(1), int(match.group(2))
        hi = int(match.group(3)) if match.group(3) else None
    key, others = resolve_ref(conn, ref, providers)
    if not key:
        safe_print(f"navcom: no session matches ref {ref!r}. Refs are printed in search results (e.g. 'ref 395e14b4').")
        return 1
    prov = _key_provider(conn, key)
    last = max_msg_index(conn, key)
    if lo is None:
        span = (1, last)
        default_chars = 400
    elif hi is not None:
        span = (min(lo, hi), max(lo, hi))
        default_chars = 3000
    else:
        w = args.window_turns if args.window_turns is not None else 3
        span = (max(1, lo - w), lo + w)
        default_chars = 3000
    max_chars = args.max_chars if args.max_chars is not None else default_chars
    project, title = session_meta(conn, key, prov)
    safe_print(f"{session_date(conn, key)}  {STYLE.provider(prov)}  {pretty_project(project) or '-'}  ref {display_ref(conn, key, prov)}  turns {span[0]}-{min(span[1], last)} of {last}")
    safe_print(STYLE.dim(key))
    plan = resume_plan(conn, key, prov)
    if plan and not plan["gone"]:
        safe_print(STYLE.dim(f"resume: {plan['line']}"))
    elif plan and plan["archived"]:
        safe_print(STYLE.dim(f"resume: navcom --resume {display_ref(conn, key, prov)}   ({prov} deleted it; navcom restores it from its archive)"))
    elif plan:
        safe_print(STYLE.dim(f"resume: not possible — {prov} deleted this transcript before navcom archived it (the text below is navcom's copy)"))
    if others:
        safe_print(STYLE.warn(f"note: {len(others)} other session(s) also match {ref!r}; showing the most recent"))
    safe_print("")
    rows = fetch_window_rows(conn, key, [span])
    if args.role:
        rows = [r for r in rows if r[1] == args.role]
    for msg_index, role, text in rows:
        if max_chars and len(text) > max_chars:
            text = text[:max_chars] + f"… [+{len(text) - max_chars} chars; --max-chars 0 for all]"
        marker = "▶ " if lo is not None and hi is None and msg_index == lo else ""
        safe_print(marker + format_turn(role, text, prov, msg_index))
    if lo is not None and hi is None and span[1] < last:
        safe_print(STYLE.dim(f"→ more: navcom --open {display_ref(conn, key, prov)}:{span[1] + 1}-{min(last, span[1] + 10)}"))
    return 0


def cmd_recent_sessions(conn, logs, limit, keys=None):
    if keys is not None:
        wanted = set(keys)
        pool = [l for l in logs if l[0] in wanted]
    else:
        pool = logs
    shown = pool[-limit:] if limit else pool
    index_logs(conn, shown)
    safe_print(f"navcom: {len(shown)} most recent session{'s' if len(shown) != 1 else ''} of {len(pool)} · search: navcom <words> · read: navcom --open <ref> · reopen: navcom --resume <ref>")
    for key, mtime, size, prov in reversed(shown):
        project, title = session_meta(conn, key, prov)
        stamp = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M") if mtime else "????-??-?? ??:??"
        title = (title[:90] + "…") if len(title) > 90 else title
        safe_print(f"{stamp}  {STYLE.provider(prov, f'{prov:8s}')} {pretty_project(project) or '-':28s} {display_ref(conn, key, prov):10s} {title}")
    conn.commit()
    return 0


def cmd_where(conn, providers):
    safe_print(f"navcom {NAVCOM_VERSION}")
    roots = provider_roots()
    logs = list_logs(providers)
    counts = {}
    for _, _, _, prov in logs:
        counts[prov] = counts.get(prov, 0) + 1
    for prov in providers:
        found = [str(r) for r in roots.get(prov, []) if Path(r).exists()]
        where = ", ".join(found) if found else f"not found ({', '.join(str(r) for r in roots.get(prov, []))})"
        safe_print(f"  {STYLE.provider(prov, f'{prov:8s}')} {counts.get(prov, 0):6d} sessions  {where}")
    stats = conn.execute("SELECT count(*) FROM file_state").fetchone()[0]
    turns = conn.execute("SELECT count(*) FROM turn_loc").fetchone()[0]
    on_disk = {l[0] for l in logs}
    archived = sum(1 for (f,) in conn.execute("SELECT file FROM file_state") if f not in on_disk)
    safe_print(f"  index    {stats} sessions, {turns} turns ({archived} no longer on disk but still searchable)")
    safe_print(f"           {default_index_path()}")
    summary = archive_summary(conn)
    if summary:
        safe_print(f"  archive  {summary}")
    safe_print(f"  daily    {daily_job_status()}")
    for name, status in (("claude", claude_retention_status), ("gemini", gemini_retention_status)):
        days, how = status()
        if days is not None:
            verdict = "keeps history ~forever" if days >= 3650 else f"DELETES transcripts after {days:g} days"
            safe_print(f"  {name:8s} retention: {verdict} ({how})")
    for hid, h in EXTRA_HARNESSES.items():
        if not h.get("retention") or hid not in providers:
            continue
        try:
            spec = h["retention"]()
        except Exception:
            continue
        if not spec or not Path(spec["settings_path"]).parent.is_dir():
            continue
        reader = yaml_setting if str(spec["settings_path"]).endswith((".yaml", ".yml")) else json_setting
        current = reader(spec["settings_path"], spec["key_path"])
        if current is None:
            safe_print(f"  {hid:8s} retention: DELETES after {spec.get('default_days', '?')} days by default "
                       f"({spec['key_path']} unset in {spec['settings_path']})")
        else:
            safe_print(f"  {hid:8s} retention: {spec['key_path']} = {current} ({spec['settings_path']})")
    return 0


def run(argv=None):
    parser = build_parser()
    if not (sys.argv[1:] if argv is None else argv):
        parser.print_help()  # bare `navcom`: the manual (LLMs and humans both start here)
        return 0
    args = parser.parse_intermixed_args(argv)
    STYLE.configure(args.color)

    if args.prompt:
        args.summary = True
    if args.solo:
        args.summary = True
        args.summary_mode = "reduce"
    if args.window_turns is not None or args.verbosity is not None:
        args.context = True

    if args.skill or args.install_skills:
        return cmd_skill("install" if args.install_skills else args.skill, args.phrase or [], args.json)

    query = _gather_query(args)

    try:
        all_logs_for_detect = list_logs(ALL_PROVIDERS) if args.this else None
        providers = resolve_providers(args, all_logs_for_detect)
    except ValueError as exc:
        sys.stderr.write(f"navcom: {exc}\n")
        return 2

    index_path = Path(args.index).expanduser() if args.index else default_index_path()
    try:
        conn = open_index(index_path)
    except sqlite3.Error as exc:
        sys.stderr.write(f"navcom: can't open index {index_path}: {exc}\n")
        return 1

    auto_install_skills()
    for fix in (ensure_claude_retention, ensure_gemini_retention, ensure_registered_retention):
        try:
            fix()
        except Exception:
            pass
    if args.daily == "off":
        removed = remove_daily_job()
        safe_print("removed  " + ", ".join(removed) if removed else "no daily job was installed")
        safe_print("daily job stays off until `navcom --daily on`")
        return 0
    auto_install_daily_job()
    if args.daily:
        if args.daily == "on":
            safe_print(install_daily_job(force=True))
        safe_print(daily_job_status())
        return 0
    if args.maintain:
        return cmd_maintain(conn, force=args.reindex)
    if args.restore:
        return cmd_restore(conn, args.restore, providers)

    if args.menu:
        return run_menu(conn)
    if args.where:
        return cmd_where(conn, providers)

    logs = list_logs(providers)

    if args.list:
        if not logs:
            safe_print("No logs found.")
            return 0
        indexed = list(enumerate(logs))
        if args.recent:
            keep = set()
            for prov in providers:
                keep.update([i for i, l in indexed if l[3] == prov][-args.recent:])
            indexed = [(i, l) for i, l in indexed if i in keep]
        limit = 50 if args.limit is None else args.limit
        if limit and len(indexed) > limit:
            safe_print(STYLE.dim(f"(showing last {limit} of {len(indexed)}; --limit 0 for all)"))
            indexed = indexed[-limit:]
        for idx, (key, mtime, size, prov) in indexed:
            stamp = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S") if mtime else "????-??-?? ??:??:??"
            safe_print(f"{idx:03d} {stamp} {size:9d} {prov:8s} {key}")
        return 0

    # Which sessions are in play?
    explicit_scope = bool(args.file or args.latest or args.recent or args.this_session)
    if args.this_session:
        current = current_session_log(logs if logs else list_logs(ALL_PROVIDERS))
        if current is None:
            safe_print("navcom: can't tell which session this is.")
            return 1
        targets = [current]
    elif args.file:
        if args.file.isdigit() and not Path(args.file).exists():
            idx = int(args.file)
            if idx < 0 or idx >= len(logs):
                safe_print(f"Index out of range: {idx} (see navcom --list)")
                return 1
            targets = [logs[idx]]
        else:
            log = log_for_path(args.file)
            if log is None:
                # a bare file name / uuid / ref: look for it among the sessions on disk
                want = args.file.strip()
                stem = Path(want).stem if want.endswith((".jsonl", ".json")) else want
                on_disk = [l for l in logs if Path(l[0].split("#")[-1]).name == want
                           or session_ref(l[0]) == stem or session_ref(l[0]).startswith(stem)
                           or short_ref(l[0]) == stem or l[0].endswith("#" + want)]
                log = on_disk[-1] if on_disk else None
            if log is None:
                key, _ = resolve_ref(conn, args.file, providers)
                log = next((l for l in logs if l[0] == key), None) if key else None
                if log is None and key:
                    log = (key, 0.0, 0, _key_provider(conn, key))
            if log is None:
                safe_print(f"Log not found: {args.file}")
                return 1
            targets = [log]
    elif args.latest:
        targets = logs[-1:] if logs else []
    elif args.recent:
        targets = []
        for prov in providers:
            targets.extend([l for l in logs if l[3] == prov][-args.recent:])
    else:
        targets = logs

    if args.resume_ref:
        index_logs(conn, logs)
        conn.commit()
        return cmd_resume(conn, args, providers)

    if args.open_ref:
        index_logs(conn, logs)
        result = cmd_open(conn, args, providers)
        conn.commit()
        conn.close()
        return result

    if args.sessions or (not query and not explicit_scope and not args.summary):
        try:
            keys = filter_keys(conn, None, providers, args)
        except ValueError as exc:
            sys.stderr.write(f"navcom: {exc}\n")
            return 2
        limit = DEFAULT_LIMIT if args.limit is None else args.limit
        return cmd_recent_sessions(conn, logs, limit, keys)

    if not targets and not query:
        safe_print("No logs found.")
        return 1

    index_logs(conn, targets, force=args.reindex)
    try:
        archive_logs(conn, logs if explicit_scope else targets)
    except Exception as exc:
        sys.stderr.write(f"[navcom] archive step skipped: {exc}\n")

    prompt_template = None
    if args.prompt:
        prompt_template = build_prompt_from_text(args.prompt)
    elif args.prompt_file:
        prompt_path = Path(args.prompt_file).expanduser()
        if not prompt_path.exists():
            safe_print(f"Prompt file not found: {prompt_path}")
            return 1
        prompt_template = prompt_path.read_text(encoding="utf-8")
    if args.summary:
        prompt_template = ensure_markdown_prompt(prompt_template)

    if not query:
        return dump_transcripts(conn, args, targets, providers, prompt_template)

    try:
        keys = filter_keys(conn, [t[0] for t in targets] if explicit_scope else None, providers, args)
    except ValueError as exc:
        sys.stderr.write(f"navcom: {exc}\n")
        return 2

    limit = DEFAULT_LIMIT if args.limit is None else args.limit
    exclude = None
    if not args.include_self and not explicit_scope:
        me = env_session_log(logs)
        if me:
            exclude = {me[0]}
            # Claude keeps a session's subagent transcripts in <session-id>/subagents/
            sid_dir = "/" + session_ref(me[0]) + "/"
            exclude.update(l[0] for l in logs if sid_dir in l[0])
    hits, cooked, note = search_hits(
        conn, query, providers=providers, keys=keys,
        limit=limit or 100000, snippet_tokens=args.snippet_tokens,
        no_prefix=args.no_prefix, role=args.role, any_terms=args.any,
        include_self=args.include_self, exclude_keys=exclude, include_tools=args.everything,
    )
    if not hits:
        scope = ", ".join(providers) if set(providers) != set(ALL_PROVIDERS) else "all harnesses"
        extra = []
        if keys is not None:
            extra.append(f"{len(keys)} sessions after filters")
        if args.role:
            extra.append(f"role={args.role}")
        safe_print(f"No hits. (query: {cooked or '(nothing searchable)'} · {scope}{' · ' + ', '.join(extra) if extra else ''})")
        safe_print(STYLE.dim("tip: fewer or shorter words; words are prefix-matched and ALL must be in one turn — or use a OR b"))
        conn.close()
        return 0

    groups = _group_hits(conn, hits, newest=args.newest)

    if args.json:
        print_json(conn, groups, cooked, note)
        conn.commit()
        conn.close()
        return 0

    if not args.context and not args.summary:
        max_chars = 220 if args.max_chars is None else args.max_chars
        print_compact(conn, groups, max_chars, len(hits), cooked, note)
        full = [p for p in providers if sum(1 for h in hits if h.provider == p) >= limit] if limit else []
        if full:
            safe_print(STYLE.dim(f"(top {limit} per harness shown; {', '.join(full)} had more — -n {limit * 3} for more, or narrow with --here / --days 7 / more words)"))
        conn.commit()
        conn.close()
        return 0

    if args.window_turns is not None:
        window = args.window_turns
    elif args.verbosity is not None:
        window = VERBOSITY_WINDOW.get(args.verbosity, 6)
    else:
        window = VERBOSITY_WINDOW.get(DEFAULT_VERBOSITY, 1) or 1

    if not args.summary:
        max_chars = 200 if args.max_chars is None else args.max_chars
        safe_print(f"navcom: {len(hits)} hits in {len(groups)} sessions · query: {cooked}")
        if note:
            safe_print(STYLE.warn(f"note: {note}"))
        print_context(conn, groups, window, max_chars)
        conn.commit()
        conn.close()
        return 0

    return summarize_hits(conn, args, groups, hits, window, prompt_template, providers, targets, query)


def summarize_hits(conn, args, groups, hits, window, prompt_template, providers, targets, query):
    dump_dir = None
    if args.dump_dir:
        dump_dir = clean_mod.ensure_dump_dir(args.dump_dir)
        if dump_dir:
            clean_mod.write_manifest(dump_dir, {
                "query": query, "providers": providers, "window": window,
                "summary_model": args.summary_model, "summary_mode": args.summary_mode,
                "prompt_file": str(args.prompt_file) if args.prompt_file else None,
            })
            clean_mod.write_dump_file(dump_dir, "hits.md", json.dumps([hit.__dict__ for hit in hits], indent=2))

    summary_engine_printed = False
    reduce_chunks = []
    for g in groups:
        file_path = g["key"]
        provider = g["provider"] or detect_provider_from_path(file_path)
        spans = window_ranges_for_hits(g["hits"], window)[file_path]
        rows = fetch_window_rows(conn, file_path, spans)
        transcript = build_transcript_from_rows(rows, provider)
        project, _ = session_meta(conn, file_path, provider)
        file_date = session_date(conn, file_path)
        short = short_ref(file_path)
        dated_transcript = f"[Session: {file_date} | {provider} | {short} | {pretty_project(project)}]\n{transcript}"
        if args.summary_mode == "reduce":
            reduce_chunks.append(dated_transcript)
            continue
        summary, error = summarize_text(
            dated_transcript, args.summary_model, prompt_template=prompt_template,
            summary_mode=args.summary_mode, dump_dir=dump_dir,
            use_ollama=args.ollama, use_gemini_first=args.llmgemini,
            _print_engine=not summary_engine_printed,
        )
        summary_engine_printed = True
        if error:
            safe_print(f"Summary error: {error}")
        else:
            safe_print("")
            safe_print(STYLE.dim(f"{provider}  {file_date}  ref {short}  {pretty_project(project)}"))
            safe_print(summary)
            if dump_dir:
                clean_mod.write_dump_file(dump_dir, "window.md", transcript)
                clean_mod.write_dump_file(dump_dir, "summary.md", summary)
                clean_mod.write_dump_file(dump_dir, "final.md", summary)
                convert_dump_txt_to_md(dump_dir)

    if args.summary_mode == "reduce" and reduce_chunks:
        combined = "\n\n---\n\n".join(reduce_chunks)
        summary, error = summarize_text(
            combined, args.summary_model, prompt_template=prompt_template,
            summary_mode="chrono", dump_dir=dump_dir,
            use_ollama=args.ollama, use_gemini_first=args.llmgemini, _print_engine=True,
        )
        if error:
            safe_print(f"Summary error: {error}")
        else:
            safe_print(summary)
    conn.commit()
    conn.close()
    return 0


def dump_transcripts(conn, args, targets, providers, prompt_template):
    """No query + explicit sessions (--latest/--recent/--file): print or summarize them whole."""
    dump_dir = None
    if args.summary and args.dump_dir:
        dump_dir = clean_mod.ensure_dump_dir(args.dump_dir)
        if dump_dir:
            clean_mod.write_manifest(dump_dir, {
                "query": None, "providers": providers, "files": [t[0] for t in targets],
                "summary_model": args.summary_model, "summary_mode": args.summary_mode,
            })
    max_chars = 200 if args.max_chars is None else args.max_chars
    git_section_all = ""
    if not args.summary:
        git_section_all = format_git_section(collect_git_summaries(conn, [t[0] for t in targets]))
    for key, _, _, provider in targets:
        last = max_msg_index(conn, key)
        rows = fetch_window_rows(conn, key, [(1, last)])
        if args.role:
            rows = [r for r in rows if r[1] == args.role]
        if not args.summary:
            project, _ = session_meta(conn, key, provider)
            safe_print(f"=== {session_date(conn, key)}  {provider}  {pretty_project(project) or '-'}  ref {display_ref(conn, key, provider)}")
            safe_print(STYLE.dim(key))
            for msg_index, role, text in rows:
                if max_chars and len(text) > max_chars:
                    text = text[:max_chars] + "…"
                safe_print(format_turn(role, text, provider, msg_index))
            continue
        full_rows = rows
        transcript = build_transcript_from_rows(full_rows, provider)
        git_section = format_git_section(collect_git_summaries(conn, [key]))
        if git_section:
            transcript = f"{transcript}\n\n{git_section}"
        summary, error = summarize_text(
            transcript, args.summary_model, prompt_template=prompt_template,
            summary_mode=args.summary_mode, dump_dir=dump_dir,
            use_ollama=args.ollama, use_gemini_first=args.llmgemini,
        )
        if error:
            safe_print(f"Summary error: {error}")
        else:
            safe_print(summary)
            if dump_dir:
                clean_mod.write_dump_file(dump_dir, "window.md", transcript)
                clean_mod.write_dump_file(dump_dir, "summary.md", summary)
                clean_mod.write_dump_file(dump_dir, "final.md", summary)
                convert_dump_txt_to_md(dump_dir)
    if git_section_all:
        safe_print("")
        safe_print(git_section_all)
    conn.commit()
    conn.close()
    return 0


def main(argv=None):
    try:
        return run(argv)
    except KeyboardInterrupt:
        return 130
    except BrokenPipeError:
        return 0
    except sqlite3.OperationalError as exc:
        sys.stderr.write(f"navcom: index error: {exc}\n")
        if "locked" in str(exc):
            sys.stderr.write("navcom: another navcom is indexing right now — retry in a few seconds.\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
