# navcom 0.4.0: DeepSeek Harness, Grok Build and Kilo proven live; Gemini's lost half recovered

**Pain:** navcom had silently missed **every Gemini CLI session since v0.39 (2026-04-23)**, when
Gemini moved from `.json` to `.jsonl`: 127 sessions on this Mac. Gemini also deletes chats after 30
days by default. Meanwhile every vendor now ships its own harness (DeepSeek `dsh`, xAI `grok`,
Kilo), each storing history in a different place and format, and that history belongs to the dev.

## Summary

- **Proven live:** installed the official CLIs, ran real sessions with real API keys in
  `~/dev/navcom-harness-lab` (`calc.py`), then searched and `--open`ed them with navcom. Each
  check found the prompt, reply, command and tool output:

  | Harness | Install | Run | Proof |
  |---|---|---|---|
  | DeepSeek `dsh` 0.2.0-rc.2 | `npm i -g @deepseek-ai/dsh` | `dsh headless "…"` | codeword tangerinewhale-dsh, tool `42` |
  | Kilo 7.8.3 | `npm i -g @kilocode/cli` | `kilo run -m deepseek/deepseek-flash --auto "…"` | limeotter-kilo, tool `101` |
  | Grok Build 1.0.46 | `curl -fsSL https://x.ai/cli/install.sh \| bash` | `grok -p "…" -m deepseek-flash --yolo` | cobaltbadger-grok, tool `15` |

  The xAI team key is out of credits: `403 … used all available credits or reached its monthly
  spending limit`. So Grok Build was run against DeepSeek through a `[model.deepseek-flash]`
  custom-model entry in `~/.grok/config.toml`, using `env_key = "DEEPSEEK_API_KEY"`. It is the same
  Grok harness writing the same `updates.jsonl`.
- **Gemini `.jsonl`:**
  - `replay_gemini_jsonl` handles metadata lines, `$set` (including the legacy `messages`
    checkpoints that real files start with), `$patch` (`id`, `updates`, `removeIds`, `orderIds`,
    `toolCalls` results) and `$rewindTo`. A later line with the same `id` replaces the earlier one.
  - Listing covers `chats/*.json` plus `chats/**/*.jsonl` (subagents) across `GEMINI_CLI_HOME` and
    `~/.cache/.gemini`. Project comes from the metadata's `directories[0]`.
  - Verified against an independent replay: user 206/206, assistant 79/79, tool 835 of 840 calls
    (the other 5 had empty results). My first checker was wrong because it ignored `$set`
    checkpoints; navcom was right.
- **Gemini retention:** `ensure_gemini_retention` sets `general.sessionRetention = {"enabled": false}`
  when the key is unset (backup kept, atomic write, explicit values respected, JSONC skipped). The
  archive default is now `claude,gemini`.
- **dsh:** `read_zstd` tries stdlib `compression.zstd` (3.14+), then `zstandard`, then the `zstd -dcq`
  CLI; it handles multiple frames and a truncated last frame. Only `user/message` with
  `source.kind == "user"` is indexed (runtime context and skill catalogs are injected). Handled:
  `assistant/message` text, `tool/call` (cmd plus label), `tool/result` (tool output), and the last
  `session/title`.
- **Grok:** parses `updates.jsonl` (append-only, authoritative). `chat_history.jsonl` is rewritten
  on compaction and is not used. Details:
  - Chunks are joined, and thought chunks are skipped.
  - `tool_call` carries `rawInput.command`. The real 1.0.46 lines have **no `kind`**, so a command
    is detected by the `command` key.
  - `tool_call_update` outputs are taken only with status `completed` or `failed`; real files also
    have a status-less update carrying a description.
  - The title is `summary.json` `title`, then `generated_title`, then `session_summary`. Real
    `summary.json` nests the cwd under `info.cwd`.
- **Kilo:** reuses `list_opencode_logs(db, provider)` and `iter_opencode_db`. The path is `$KILO_DB`
  or `~/.local/share/kilo/kilo.db`.
- **Refs:** harnesses that give every file the same name (`updates.jsonl`, `session.v4.jsonl.zstd`)
  take their ref from the session folder. dsh shows `7a48d7c9`, Grok `4a171a5ed837`.

## Findings worth knowing

- **dsh uploads your full session log to DeepSeek by default.** The
  `@deepseek-ai/dsh-session-log-deepseek` plugin is "lossless", incremental and up to 8 MiB per
  request. It is a sibling request field (`dsh_session_log`), not model input. It is on by default
  (`enabled: true`). To turn it off: Web Settings → General → "Upload Session Log when using the
  official model API", or `enabled: false` in the profile patch. navcom does not change this.
- **Gemini CLI** stopped serving individual Google AI Pro/Ultra/free accounts on 2026-06-18
  (discussion #28017). API-key and enterprise users continue. Individuals were moved to the
  closed-source Antigravity CLI (`agy`), whose primary store is unreadable (encrypted `.pb`).
- **Skills:** dsh's skill catalog already listed `navcom-session-recall` from `~/.agents/skills`.
  Grok reads `~/.claude/skills` and `~/.agents/skills`. Both are covered by the auto-install.

## Decisions

- **Live proof over fixture proof** wherever a key existed. Fixtures exist too: `fake_home.py` now
  has dsh (real two-frame zstd), Grok, Kilo and Gemini JSONL with every replay operation.
- **Grok via a custom model** rather than waiting for xAI credits: it is the same harness and the
  same files.
- **Next batch, not built yet (from the research report):** Copilot CLI, Qwen Code, Cline, Hermes
  (deletes after 90 days), Crush, Kimi Code, Codewhale, Reasonix, Factory Droid, Continue,
  Mistral Vibe, Cursor, Kiro, Amp, Auggie, OpenHands, Aider and Antigravity.

## Snippets

```bash
export DEEPSEEK_API_KEY=$(grep -E '^export DEEPSEEK_API_KEY=' ~/.zshrc | cut -d= -f2- | awk '{print $1}')  # .zshrc lines carry trailing comments
dsh headless "task"                                   # session → ~/.dsh/sessions/--<cwd>--/session-<uuid>/session.v4.jsonl.zstd
zstd -dc ~/.dsh/sessions/*/*/session.v4.jsonl.zstd | head
kilo run -m deepseek/deepseek-flash --auto "task"     # → ~/.local/share/kilo/kilo.db
grok -p "task" -m deepseek-flash --yolo               # → ~/.grok/sessions/<urlenc cwd>/<uuid7>/updates.jsonl
curl -s https://api.deepseek.com/user/balance -H "Authorization: Bearer $DEEPSEEK_API_KEY"   # $1.51 at trial time
```

## Files changed

- `navcom.py`:
  - Gemini/dsh/Grok/Kilo section: `gemini_tmp_roots`, `replay_gemini_jsonl`, `iter_gemini_jsonl`,
    `read_zstd`, `list_dsh_logs`, `iter_dsh`, `list_grok_logs`, `iter_grok_updates`, `_acp_text`,
    `_grok_summary`/`_grok_cwd`, `kilo_db_path`, `ensure_gemini_retention`/`gemini_retention_status`.
  - The provider registry, aliases (deepseek, xai, kilocode), routing, titles, projects,
    `--where`, the archive default and generic-file refs.
  - Version 0.4.0.
- `features/support/fake_home.py` (four new formats), `features/search.feature` and steps (all 10
  harnesses), `tests/test_harness_parsers.py` (gemini replay, dsh zstd, grok, kilo, gemini
  retention, real grok summary shape). `README.md`, `skills/…/SKILL.md`, `pyproject.toml`.
- **Outside the repo (trial installs):**
  - `/opt/homebrew/bin/dsh`, `/opt/homebrew/bin/kilo`, `~/.grok/bin/grok`, plus the
    `~/.local/bin/{grok,agent}` symlinks.
  - A grok installer block in `~/.zshrc`, backed up to `~/.zshrc.bak-before-grok-20261001-220656`.
  - The `[model.deepseek-flash]` entry appended to `~/.grok/config.toml`.
  - The lab project at `~/dev/navcom-harness-lab`.

**tags:** navcom, deepseek-harness, dsh, zstd, grok-build, xai, kilo, gemini-jsonl, sessionRetention,
data-ownership, live-proof. Every new harness here was proven against sessions it actually wrote.
