# navcom 0.5.0: 12 more harnesses, built by parallel agents and proven on live sessions

**Pain:** every AI vendor now ships its own coding harness, and each one hides your history in a
different place and format. Some (Qwen subagents after 30 days, Hermes after 90 from v2026.9.7) delete
it on their own. Devs don't know what they're missing until they search for it.

## Summary

- **Harness registry** (`register_harness`):
  - A harness is a self-contained block providing `<id>_list`, `<id>_iter`, `<id>_project`,
    `<id>_title`, `<id>_roots` and optionally `<id>_retention`.
  - Registration wires listing, parsing, titles, projects, `--where`, the `--<id>` flags, aliases,
    colour and archive eligibility. One broken harness can never break search: its errors are caught
    per harness.
- **Parallel build:** five general-purpose agents worked to a written contract
  (`scratchpad/harness/CONTRACT.md`). Each agent installed its CLIs, ran a real codeword session,
  reverse-engineered the files on disk and delivered a `parser.py`, a fixture builder and a
  `verify.py`.
  - `harness/integrate.py` splices parsers into one generated, marked section of navcom.py via
    `ast`. It drops the agent-side loaders and fixtures, prefixes private helpers per harness, and
    emits the `register_harness` calls.
  - It also copies each parser to `features/support/harness_fixtures/<id>.py`, so the test home
    builds every fixture.
- **Live-verified this release** (the codeword prompt, cmd, tool output and reply were all found):

  | Harness | Run | Real data on this Mac |
  |---|---|---|
  | Qwen Code 0.24.7 | `qwen --yolo --auth-type openai` via OpenRouter | |
  | Kimi Code 2.1.1 | `KIMI_MODEL_*` env via OpenRouter | |
  | Crush 0.97.1 | `crush run -m openrouter/…` | |
  | GitHub Copilot CLI 1.0.91 | BYOK `COPILOT_PROVIDER_*` | |
  | Cline 3.0.67 | `cline -P openrouter -k …` | **36 VS Code-extension tasks, 2024–25** |
  | Continue `cn` 1.5.47 | config referencing `${{ secrets.OPENROUTER_API_KEY }}` | **3 IDE sessions** |
  | Codewhale 0.10.0 | `exec --output-format stream-json` (plain `exec` saves nothing) | |
  | Reasonix 1.39.6 + Studio 2.25 | both storage formats, including the RX4F zstd frames | |
  | Deep Code 0.4.2 | `DEEPCODE_*` env | |
  | Hermes v0.17.0 | `hermes chat -Q --yolo --provider openrouter` | **3 June sessions** |
  | OpenHands CLI 1.16 | `--headless --override-with-envs` | |
  | Mistral Vibe 2.25.8 | `-p --output streaming` | |

- **Real-data cross-check after integration** (inside navcom against a copy of the real index): every
  count matches the agent's independent figure. Cline shows 485 assistant turns against 491; the
  difference is consecutive-duplicate collapse.
- **Retention:**
  - `ensure_json_setting` and `json_setting` handle Qwen's `general.cleanupPeriodDays` (→ 36500).
  - `ensure_yaml_setting` and `yaml_setting` handle Hermes' `sessions.auto_prune` (→ false). The YAML
    edit is a single line under an existing `sessions:` block (matching its indent), or a new block
    at the end. Flow style is never touched, an explicit choice is always kept, and a backup is
    written.
  - `--where` lists the retention for every harness that declares one.
- **Refs:** the generic transcript file names (`wire.jsonl`, `events.frames`, `*.messages.json`,
  `transcript*.jsonl` …) now take the nearest ancestor folder that names the session; folders such
  as `main`, `agents` and `agent-*` are skipped. Before this, every Kimi session's ref was `main`.

## Findings (privacy / telemetry, from the agents)

- **On by default:**
  - Qwen: usage stats go to Alibaba RUM, and an automatic memory-extractor re-sends conversations.
  - Kimi: telemetry (`KIMI_DISABLE_TELEMETRY=1` turns it off).
  - Crush: PostHog. Codewhale: PostHog with counts only.
  - Deep Code: every prompt POSTs to deepcode.vegamo.cn with a machine-id token and no body.
  - Cline: spawns a background hub daemon on 127.0.0.1:25463 that outlives the run.
  - OpenHands: without overrides, LLM calls route through the All-Hands proxy.
- **Retention traps:** Hermes turns on 90-day auto-prune in v2026.9.7, so upgrading Hermes would start
  deleting. Qwen deletes subagent transcripts after 30 days.
- **Keys in files:** Reasonix only reads keys from a plaintext `~/.reasonix/.env`. The agent wrote the
  key there for each run and deleted it afterwards.

## Still in flight

- Aider, Antigravity CLI (`agy`), Factory Droid, Cursor CLI, Kiro, Amp, Augment and grok-dev are with
  the fifth agent.
- agy's `-p` mode hard-codes a 60s Google auth wait and makes a new PKCE challenge each attempt.
  `~/.antigravity/antigravity/bin/agy` is the IDE launcher, not the CLI. The agent is trying BYOK
  (`GOOGLE_GEMINI_BASE_URL` → an OpenRouter translator).

## Files changed

- `navcom.py`:
  - Registry: `EXTRA_HARNESSES`, `register_harness`, dispatch hooks in list/parse/project/title/
    detect/roots/archive.
  - The generated `# >>> registered harnesses` section (12 harnesses).
  - Retention: `ensure_json_setting`, `ensure_yaml_setting`, `ensure_registered_retention`.
  - `harness_names_wrapped` for `--help`, plus the generic refs. Version 0.5.0.
- `features/support/harness_fixtures/*.py` (12 fixture modules), `fake_home.build_registered`.
- `features/search.feature`: the four-role check for every registered harness.
- `tests/test_harness_parsers.py`: the YAML edit.
- `README.md`, `skills/…/SKILL.md`, `pyproject.toml`.
- **Outside the repo:**
  - Trial installs under `scratchpad/harness/<id>/install`; `uv tool install openhands mistral-vibe`.
  - `~/.vibe/config.toml` (OpenRouter provider by env name, telemetry off).
  - `~/.reasonix/config.toml` (provider entry, no key).
  - The lab sessions in each harness's store.

**tags:** navcom, harness-registry, parallel-agents, copilot-cli, cline, continue, qwen-code, kimi-code,
crush, codewhale, reasonix, deep-code, hermes, openhands, mistral-vibe, retention, yaml. The release
where navcom went from 10 harnesses to 22, each one proven against sessions it actually wrote.
