#!/usr/bin/env python3
"""
navcom.py
==========
Synthesize log_clean_quick + log_search_fts5 into one tool that:
1) cleans turns using log_clean_quick logic
2) indexes the cleaned turns with FTS5
3) searches clean text and returns windows around hits
4) optionally summarizes those windows

This file embeds full copies of both scripts for reference and function reuse.
"""

import argparse
import json
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


@dataclass
class Hit:
    ts: str
    role: str
    file: str
    msg_index: int
    provider: str
    snip: str
    text: str


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


def default_index_path():
    codex_home = os.environ.get("CODEX_HOME", os.path.expanduser("~/.codex"))
    return Path(codex_home) / "navcom-index.sqlite"


def detect_provider_from_path(path):
    path_str = str(path)
    if path_str.endswith(".json"):
        return "gemini"
    if "/.claude/" in path_str:
        return "claude"
    if "/.codex/" in path_str:
        return "codex"
    return "codex"


def list_logs(providers, codex_root=None, claude_root=None, gemini_root=None):
    logs = []
    if "codex" in providers:
        logs.extend(fts_mod.list_jsonl_logs(fts_mod.codex_sessions_root(codex_root), "codex"))
    if "claude" in providers:
        logs.extend(fts_mod.list_jsonl_logs(fts_mod.claude_projects_root(claude_root), "claude"))
    if "gemini" in providers:
        logs.extend(fts_mod.list_gemini_logs(fts_mod.gemini_tmp_root(gemini_root), "gemini"))
    logs.sort(key=lambda x: x[1])
    return logs


def select_targets(logs, providers, recent=0, all_logs=False, file=None, latest=False):
    if all_logs or recent == 0:
        return [p for p, _, _, _ in logs]
    if file:
        if file.isdigit():
            idx = int(file)
            if idx < 0 or idx >= len(logs):
                raise ValueError(f"Index out of range: {idx}")
            return [logs[idx][0]]
        return [Path(file).expanduser()]
    if latest:
        return [logs[-1][0]]
    return fts_mod.select_recent_targets(logs, providers, recent)


def iter_clean_turns(path, provider, include_tools=False, include_cmds=True):
    if provider == "claude":
        iterator = clean_mod.iter_claude(path, include_tools, include_cmds)
    elif provider == "gemini":
        iterator = clean_mod.iter_gemini(path, include_tools, include_cmds)
    else:
        iterator = clean_mod.iter_codex(path, include_tools, include_cmds)
    for role, text in iterator:
        if isinstance(text, list):
            text = "\n".join(str(t) for t in text)
        if not isinstance(text, str):
            text = str(text)
        raw = clean_mod.clean_text(text)
        if not raw:
            continue
        if clean_mod.is_preamble(role, raw, provider):
            continue
        raw = _strip_conversation_artifacts(raw)
        if not raw:
            continue
        yield role, raw


def needs_reindex(conn, path, stat):
    row = conn.execute("SELECT mtime, size FROM file_state WHERE file=?", (str(path),)).fetchone()
    if not row:
        return True
    return not (row[0] == stat.st_mtime and row[1] == stat.st_size)


def index_clean_file(conn, path, provider):
    stat = path.stat()
    if not needs_reindex(conn, path, stat):
        return
    conn.execute("DELETE FROM session_fts WHERE file=?", (str(path),))
    msg_index = 0
    for role, text in iter_clean_turns(path, provider, include_tools=False, include_cmds=True):
        msg_index += 1
        conn.execute(
            "INSERT INTO session_fts (text, role, file, ts, msg_index, provider) VALUES (?, ?, ?, ?, ?, ?)",
            (text, role or "", str(path), "", msg_index, provider),
        )
    conn.execute(
        "INSERT OR REPLACE INTO file_state (file, mtime, size, offset, msg_index) VALUES (?, ?, ?, ?, ?)",
        (str(path), stat.st_mtime, stat.st_size, stat.st_size, msg_index),
    )


def index_targets(conn, targets):
    for target in targets:
        if not target.exists():
            print(f"Log not found: {target}")
            continue
        provider = detect_provider_from_path(target)
        index_clean_file(conn, target, provider)


def search_hits(conn, query, providers=None, files=None, limit=20, snippet_tokens=250, no_prefix=False):
    cooked = query
    if not no_prefix:
        cooked = fts_mod.apply_prefix_query(cooked)
    if providers:
        hits = []
        for provider in providers:
            results = fts_mod.search(
                conn,
                cooked,
                limit,
                providers=[provider],
                files=files,
                snippet_tokens=snippet_tokens,
            )
            hits.extend(Hit(*row) for row in results)
        return hits
    results = fts_mod.search(conn, cooked, limit, providers=None, files=files, snippet_tokens=snippet_tokens)
    return [Hit(*row) for row in results]


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
                "SELECT msg_index, role, text FROM session_fts WHERE file=? AND msg_index BETWEEN ? AND ? ORDER BY msg_index",
                (file_path, start, end),
            ).fetchall()
        )
    return rows


def format_turn(role, text, provider=None):
    label = clean_mod.label_for_role(role, provider or "")
    if not label and role == "assistant":
        label = "assistant"
    if label == "cmd":
        return f"cmd: {clean_mod.format_cmd(text)}"
    return f"{label}:\n{text}\n"


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
        parts.append(format_turn(role, text, provider))
    return "\n".join(parts).strip()


def collect_git_summaries(conn, targets, limit=GIT_LIMIT_DEFAULT):
    if not fts_mod.shutil.which("git"):
        return []
    git_roots = fts_mod.collect_git_roots([Path.cwd(), Path.cwd().parent])
    if not git_roots:
        return []
    seen = set()
    summaries = []
    for target in targets:
        end_idx = fts_mod.max_msg_index(conn, str(target))
        commits = fts_mod.scan_commits(
            conn,
            str(target),
            1,
            end_idx,
            require_context=True,
            role=GIT_ROLE_DEFAULT,
            action_only=True,
        )
        for _, hashes, _ in commits:
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
        result = subprocess.run(
            cmd,
            input=text,
            capture_output=True, text=True, timeout=120, env=env,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip(), None
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
                    print(f"\033[2m[NavCom summary via {cfg['label']}]\033[0m")
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
                    print(f"\033[2m[NavCom summary via {cfg['label'].replace('subscription', 'api-key')}]\033[0m")
                return summary, None
            else:
                _mark_engine_broken(api_name)

    # Pass 3: Ollama (or forced via --ollama)
    if shutil.which("ollama"):
        model = ollama_model or SUMMARY_MODEL_DEFAULT
        if _print_engine:
            print(f"\033[2m[NavCom summary via ollama/{model}]\033[0m")
        return clean_mod.summarize_transcript(
            text, model, mode=summary_mode,
            dump_dir=dump_dir, prompt_template=prompt_template,
        )

    # All failed
    print("\033[93m[NavCom: no summarization engine available — showing raw output]\033[0m")
    return None, "no engine available"


def summarize_text(text, model, prompt_template=None, summary_mode="chrono", dump_dir=None, use_ollama=False, use_gemini_first=False, _print_engine=True):
    if use_ollama:
        if _print_engine:
            print(f"\033[2m[NavCom summary via ollama/{model}]\033[0m")
        return clean_mod.summarize_transcript(
            text, model, mode=summary_mode,
            dump_dir=dump_dir, prompt_template=prompt_template,
        )
    return smart_summarize(
        text, use_ollama=False, use_gemini_first=use_gemini_first, ollama_model=model,
        prompt_template=prompt_template, summary_mode=summary_mode, dump_dir=dump_dir,
        _print_engine=_print_engine,
    )


def main():
    parser = argparse.ArgumentParser(
        description=(
            "NavCom — search and recall context from past CLI coding sessions.\n"
            "Indexes Claude, Gemini, and Codex conversation logs. Searches with FTS5.\n"
            "Optionally summarizes results via Claude, Gemini, Ollama, or any available LLM.\n"
            "\n"
            "═══════════════════════════════════════════════════════════════════\n"
            " QUICK START\n"
            "═══════════════════════════════════════════════════════════════════\n"
            "\n"
            "  navcom --query \"drizzle\"                  Search everything, show context\n"
            "  navcom --query \"drizzle\" --compact         Just hits + snippets, one line each\n"
            "  navcom --query \"drizzle\" --solo             One fast summary across all hits\n"
            "  navcom --query \"drizzle\" --summary         Per-chunk summaries (more detail)\n"
            "\n"
            "  TIP: --solo is the fastest way to catch up on a topic. Raw output\n"
            "  (no --solo/--summary) is great when piping to your current LLM:\n"
            "    navcom --query \"auth\" --compact | claude -p \"summarize this\"\n"
            "    navcom --query \"auth\" --compact | gemini -p \"summarize this\"\n"
            "\n"
            "═══════════════════════════════════════════════════════════════════\n"
            " FILTER BY PROVIDER (default: all)\n"
            "═══════════════════════════════════════════════════════════════════\n"
            "\n"
            "  navcom --query \"auth\" --claude              Only Claude sessions\n"
            "  navcom --query \"auth\" --gemini              Only Gemini sessions\n"
            "  navcom --query \"auth\" --claude --gemini     Both, no Codex\n"
            "  navcom --query \"auth\"                       All providers (default)\n"
            "  navcom --query \"auth\" --this                Auto-detect current provider\n"
            "\n"
            "═══════════════════════════════════════════════════════════════════\n"
            " SUMMARIZATION — who does the thinking?\n"
            "═══════════════════════════════════════════════════════════════════\n"
            "\n"
            "  --solo                     One fast consolidated summary (recommended)\n"
            "  --solo --llmgemini         Use Gemini instead of Claude (cleaner, no hooks)\n"
            "  --solo --ollama            Use local Ollama (offline, no cloud)\n"
            "  --summary                  Per-chunk summaries (more detail, slower)\n"
            "  --summary --llmgemini      Per-chunk via Gemini\n"
            "\n"
            "  LLM fallback chain: Claude sonnet → Gemini flash → Ollama → raw\n"
            "  Engines that fail are cached for 1hr to avoid repeated timeouts.\n"
            "\n"
            "═══════════════════════════════════════════════════════════════════\n"
            " OUTPUT MODES\n"
            "═══════════════════════════════════════════════════════════════════\n"
            "\n"
            "  (default)    Windowed turns around each hit. Raw text — your current\n"
            "               LLM can always summarize if you pipe it.\n"
            "               Best for: reading context yourself, or piping to an LLM.\n"
            "\n"
            "  --compact    One line per hit — conversation list + snippets.\n"
            "               Best for: \"which conversations mentioned X?\"\n"
            "\n"
            "  --solo       One consolidated LLM summary across all hits (~6 seconds).\n"
            "               Best for: \"catch me up on what happened with X\"\n"
            "\n"
            "  --summary    Per-chunk LLM summaries (one per conversation file).\n"
            "               Best for: detailed per-session breakdown.\n"
            "\n"
            "═══════════════════════════════════════════════════════════════════\n"
            " TUNING KNOBS\n"
            "═══════════════════════════════════════════════════════════════════\n"
            "\n"
            "  --limit N           Max search hits (default: 20)\n"
            "  --window-turns N    Turns before/after each hit (default: 1)\n"
            "  --max-chars N       Truncate each turn (default: 200, 0=unlimited)\n"
            "  --recent N          Only N most recent sessions per provider (0=all)\n"
            "  --prompt \"...\"      Custom summarization prompt (implies --summary)\n"
            "\n"
            "═══════════════════════════════════════════════════════════════════\n"
            " REAL USE CASES\n"
            "═══════════════════════════════════════════════════════════════════\n"
            "\n"
            "  # Catch me up on the Drizzle migration\n"
            "  navcom --query \"drizzle migration\" --solo\n"
            "\n"
            "  # Same but use Gemini to summarize (no Claude hook noise)\n"
            "  navcom --query \"drizzle migration\" --solo --llmgemini\n"
            "\n"
            "  # Which Gemini sessions talked about Terraform?\n"
            "  navcom --query \"terraform\" --gemini --compact\n"
            "\n"
            "  # Quick: what conversations exist about Prisma?\n"
            "  navcom --query \"prisma\" --compact\n"
            "\n"
            "  # Deep dive into a specific conversation\n"
            "  navcom --query \"cognito auth\" --window-turns 5 --max-chars 0\n"
            "\n"
            "  # Pipe raw output to your current LLM session\n"
            "  navcom --query \"deploy\" --compact | claude -p \"summarize\"\n"
            "\n"
            "  # Custom prompt for a specific kind of summary\n"
            "  navcom --query \"schema\" --solo --prompt \"List every table name mentioned\"\n"
            "\n"
            "  # Detailed per-session breakdown\n"
            "  navcom --query \"migration\" --summary --claude\n"
        ),
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "--query",
        help="Search term or FTS query (AND/OR/phrases). Omit for full transcript (or pass a bare phrase).",
    )
    parser.add_argument("phrase", nargs="*", help="Phrase-only query when --query is omitted.")
    parser.add_argument("--codex", action="store_true", help="Use Codex logs.")
    parser.add_argument("--claude", action="store_true", help="Use Claude logs.")
    parser.add_argument("--gemini", action="store_true", help="Use Gemini logs.")
    parser.add_argument("--all", action="store_true", default=True, help="Search all providers (default). Use --claude/--gemini/--codex to narrow.")
    parser.add_argument("--this", action="store_true", help="Search only the current provider (auto-detected from most recent session).")
    parser.add_argument("--recent", type=int, default=0, help="Limit to N most recent logs per provider (default: 0 = all logs).")
    parser.add_argument("--all-logs", action="store_true", help="(deprecated — all logs is now default)")
    parser.add_argument("--file", help="Specific log file path or index from --list.")
    parser.add_argument("--latest", action="store_true", help="Use latest log only (same as --recent 1).")
    parser.add_argument("--list", action="store_true", help="List available logs with indexes.")
    parser.add_argument("--index", help="SQLite index path (default: $CODEX_HOME/navcom-index.sqlite).")
    parser.add_argument("--limit", type=int, default=20, help="Max search hits per provider (default: 20).")
    parser.add_argument(
        "--snippet-tokens",
        type=int,
        default=250,
        help="Snippet token size per hit (preview only; default: 250).",
    )
    parser.add_argument("--no-prefix", action="store_true", help="Disable prefix matching (mountain -> mountain*).")
    parser.add_argument(
        "--verbosity",
        type=int,
        default=DEFAULT_VERBOSITY,
        help=f"Window size 1-10 (default: {DEFAULT_VERBOSITY}).",
    )
    parser.add_argument("--window-turns", type=int, help="Override turns on each side of a hit.")
    parser.add_argument("--max-chars", type=int, default=200, help="Max chars per turn output (default: 200, 0 = no limit).")
    parser.add_argument("--compact", action="store_true", help="Show only the banner + FTS snippets, no full turn expansion. Fast and concise.")
    parser.add_argument("--summary", action="store_true", help="Summarize the extracted window or transcript.")
    parser.add_argument("--solo", action="store_true", help="One consolidated summary across all hits. Shortcut for --summary --summary-mode reduce.")
    parser.add_argument("--summary-model", default=SUMMARY_MODEL_DEFAULT, help="Summary model name.")
    parser.add_argument(
        "--summary-mode",
        default="chrono",
        choices=["chrono", "reduce"],
        help="Summary mode (chrono = per-chunk, reduce = consolidated).",
    )
    parser.add_argument("--ollama", action="store_true", help="Force ollama for summarization instead of CLI LLM.")
    parser.add_argument("--llmgemini", action="store_true", help="Force gemini as the summarizer (runs before claude in the chain).")
    parser.add_argument("--prompt", help="Inline summary prompt text (implies --summary).")
    parser.add_argument(
        "--prompt-file",
        help="Prompt template file for summarization (use {{transcript}} placeholder).",
    )
    parser.add_argument(
        "--dump-dir",
        help="Dump dir for summary artifacts (chunk inputs/outputs + final summary).",
    )

    args = parser.parse_args()

    if args.prompt:
        args.summary = True
    if args.solo:
        args.summary = True
        args.summary_mode = "reduce"

    providers = []
    specific = args.codex or args.claude or args.gemini or args.this
    if specific:
        if args.codex:
            providers.append("codex")
        if args.claude:
            providers.append("claude")
        if args.gemini:
            providers.append("gemini")
        if args.this:
            detected = clean_mod.detect_latest_provider()
            providers = [detected] if detected else ["codex"]
    else:
        providers = ["codex", "claude", "gemini"]

    logs = list_logs(providers)
    if args.list:
        if not logs:
            print("No logs found.")
            return 0
        for idx, (path, mtime, size, provider) in enumerate(logs):
            stamp = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
            print(f"{idx:03d} {stamp} {size:9d} {provider:7} {path}")
        return 0

    if not logs:
        print("No logs found.")
        return 1

    try:
        targets = select_targets(logs, providers, args.recent, args.all_logs, args.file, args.latest)
    except ValueError as exc:
        print(str(exc))
        return 1

    if not args.query and args.phrase:
        args.query = " ".join(args.phrase).strip()
    if args.query == "":
        args.query = None

    prompt_template = None
    if args.prompt:
        prompt_template = build_prompt_from_text(args.prompt)
    elif args.prompt_file:
        prompt_path = Path(args.prompt_file).expanduser()
        if not prompt_path.exists():
            print(f"Prompt file not found: {prompt_path}")
            return 1
        prompt_template = prompt_path.read_text(encoding="utf-8")
    if args.summary:
        prompt_template = ensure_markdown_prompt(prompt_template)

    index_path = Path(args.index).expanduser() if args.index else default_index_path()
    index_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(index_path))
    fts_mod.ensure_db(conn)

    index_targets(conn, targets)
    conn.commit()

    if not args.query:
        dump_dir = None
        if args.summary and args.dump_dir:
            dump_dir = clean_mod.ensure_dump_dir(args.dump_dir)
            if dump_dir:
                clean_mod.write_manifest(
                    dump_dir,
                    {
                        "query": None,
                        "providers": providers,
                        "files": [str(p) for p in targets],
                        "summary": args.summary,
                        "summary_model": args.summary_model,
                        "summary_mode": args.summary_mode,
                        "prompt_file": str(args.prompt_file) if args.prompt_file else None,
                        "prompt_inline": args.prompt if args.prompt else None,
                    },
                )
        git_section_all = ""
        if not args.summary:
            git_section_all = format_git_section(collect_git_summaries(conn, targets))
        for target in targets:
            provider = detect_provider_from_path(target)
            rows = []
            if not args.summary:
                print(f"=== {target}")
            msg_index = 0
            for role, text in iter_clean_turns(target, provider, include_tools=False, include_cmds=True):
                msg_index += 1
                if args.max_chars and len(text) > args.max_chars:
                    text = text[: args.max_chars] + "…"
                rows.append((msg_index, role, text))
                if not args.summary:
                    print(format_turn(role, text, provider))
            if args.summary:
                transcript = build_transcript_from_rows(rows, provider)
                git_section = format_git_section(collect_git_summaries(conn, [target]))
                if git_section:
                    transcript = f"{transcript}\n\n{git_section}"
                summary, error = summarize_text(
                    transcript,
                    args.summary_model,
                    prompt_template=prompt_template,
                    summary_mode=args.summary_mode,
                    dump_dir=dump_dir,
                    use_ollama=args.ollama, use_gemini_first=args.llmgemini,
                )
                if error:
                    print(f"Summary error: {error}")
                else:
                    print(summary)
                    if dump_dir:
                        clean_mod.write_dump_file(dump_dir, "window.md", transcript)
                        clean_mod.write_dump_file(dump_dir, "summary.md", summary)
                        clean_mod.write_dump_file(dump_dir, "final.md", summary)
                        convert_dump_txt_to_md(dump_dir)
        if git_section_all:
            print("")
            print(git_section_all)
        conn.close()
        return 0

    file_filter = [str(p) for p in targets] if len(targets) != len(logs) else None

    window = args.window_turns if args.window_turns is not None else VERBOSITY_WINDOW.get(args.verbosity, 6)

    hits = search_hits(conn, args.query, providers=providers, files=file_filter, limit=args.limit, snippet_tokens=args.snippet_tokens, no_prefix=args.no_prefix)
    if not hits:
        print("No hits.")
        return 0

    ranges = window_ranges_for_hits(hits, window)

    # Print a summary banner FIRST so truncated output still shows the big picture
    unique_files = list(ranges.keys())
    print(f"── NavCom: {len(hits)} hits across {len(unique_files)} conversation(s) ──")
    for i, fp in enumerate(unique_files, 1):
        spans = ranges[fp]
        hit_count = sum(1 for h in hits if h.file == fp)
        short = fp.split("/")[-1] if "/" in fp else fp
        # Show provider + project context
        provider_tag = detect_provider_from_path(fp)
        prov_colors = {"claude": "\033[95m", "gemini": "\033[94m", "codex": "\033[93m"}
        prov_color = prov_colors.get(provider_tag, "\033[0m")
        project = ""
        if "/.claude/projects/" in fp:
            parts = fp.split("/.claude/projects/")[1].split("/")
            project = f" \033[2m{parts[0]}\033[0m"
        elif "/.gemini/" in fp:
            project = f" \033[2mgemini-session\033[0m"
        print(f"  {i}. [{hit_count} hits] {prov_color}{provider_tag:7s}\033[0m {short}{project}")
    print()

    # Compact mode: just banner + snippets, no full turn expansion
    if args.compact:
        _dim = "\033[2m"
        _cyan = "\033[96m"
        _reset = "\033[0m"
        _prov_colors = {"claude": "\033[95m", "gemini": "\033[94m", "codex": "\033[93m"}
        for hit in hits:
            short = hit.file.split("/")[-1] if "/" in hit.file else hit.file
            role_label = f"{hit.role}:" if hit.role else ""
            prov = hit.provider if hit.provider else detect_provider_from_path(hit.file)
            pc = _prov_colors.get(prov, "")
            snippet = hit.snip[:200] if hit.snip else hit.text[:200]
            snippet = snippet.replace("\n", " ").strip()
            print(f"  {pc}{prov:7s}{_reset} {_dim}{short}:{hit.msg_index}{_reset}  {_cyan}{role_label}{_reset} {snippet}")
        print()
        conn.close()
        return 0

    dump_dir = None
    if args.dump_dir:
        dump_dir = clean_mod.ensure_dump_dir(args.dump_dir)
        if dump_dir:
            clean_mod.write_manifest(
                dump_dir,
                {
                    "query": args.query,
                    "providers": providers,
                    "files": [str(p) for p in targets],
                    "window": window,
                    "verbosity": args.verbosity,
                    "summary": args.summary,
                    "summary_model": args.summary_model,
                    "summary_mode": args.summary_mode,
                    "prompt_file": str(args.prompt_file) if args.prompt_file else None,
                },
            )
            clean_mod.write_dump_file(dump_dir, "hits.md", json.dumps([hit.__dict__ for hit in hits], indent=2))

    summary_engine_printed = False
    reduce_chunks = []  # for --summary-mode reduce: collect all, summarize once

    for file_path, spans in ranges.items():
        provider = detect_provider_from_path(file_path)
        rows = fetch_window_rows(conn, file_path, spans)
        output_rows = []

        # Get file date from file_state
        file_date = ""
        row = conn.execute("SELECT mtime FROM file_state WHERE file=?", (file_path,)).fetchone()
        if row:
            file_date = datetime.fromtimestamp(row[0]).strftime("%Y-%m-%d")

        if not args.summary:
            print(f"=== {file_path}")
        for msg_index, role, text in rows:
            # Summary gets full turns for better LLM context; display gets truncated
            if args.summary:
                output_rows.append((msg_index, role, text))
            else:
                display_text = text
                if args.max_chars and len(text) > args.max_chars:
                    display_text = text[: args.max_chars] + "…"
                output_rows.append((msg_index, role, display_text))
                print(format_turn(role, display_text, provider))

        if args.summary:
            transcript = build_transcript_from_rows(output_rows, provider)
            short = file_path.split("/")[-1] if "/" in file_path else file_path
            project = ""
            if "/.claude/projects/" in file_path:
                project = file_path.split("/.claude/projects/")[1].split("/")[0]

            # Prepend date + source header to transcript
            header = f"[Session: {file_date} | {provider} | {short} | {project}]"
            dated_transcript = f"{header}\n{transcript}"

            if args.summary_mode == "reduce":
                reduce_chunks.append((dated_transcript, short, provider, project, file_date))
            else:
                # Per-chunk summary
                summary, error = summarize_text(
                    dated_transcript,
                    args.summary_model,
                    prompt_template=prompt_template,
                    summary_mode=args.summary_mode,
                    dump_dir=dump_dir,
                    use_ollama=args.ollama, use_gemini_first=args.llmgemini,
                    _print_engine=not summary_engine_printed,
                )
                summary_engine_printed = True
                if error:
                    print(f"Summary error: {error}")
                else:
                    print(f"\n\033[2m{provider}  {file_date}  {short}  {project}\033[0m")
                    print(summary)
                    if dump_dir:
                        clean_mod.write_dump_file(dump_dir, "window.md", transcript)
                        clean_mod.write_dump_file(dump_dir, "summary.md", summary)
                        clean_mod.write_dump_file(dump_dir, "final.md", summary)
                        convert_dump_txt_to_md(dump_dir)

    # Reduce mode: combine all chunks, summarize once
    if args.summary and args.summary_mode == "reduce" and reduce_chunks:
        combined = "\n\n---\n\n".join(t for t, *_ in reduce_chunks)
        summary, error = summarize_text(
            combined,
            args.summary_model,
            prompt_template=prompt_template,
            summary_mode="chrono",  # use chrono internally since we're passing one big text
            dump_dir=dump_dir,
            use_ollama=args.ollama, use_gemini_first=args.llmgemini,
            _print_engine=True,
        )
        if error:
            print(f"Summary error: {error}")
        else:
            print(summary)

    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
