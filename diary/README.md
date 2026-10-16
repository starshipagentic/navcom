# navcom diary

- [2026-10-16 — The bridge survives a reload](2026-10-16-bridge-survives-reload.md) — SIGPIPE crash fixed at the web entry only (CLI pipe behavior unchanged); real-subprocess regression test; default bridge relaunched on a new port.

- [2026-10-16 — Galactic navigation handoff](2026-10-16-galactic-navigation-handoff.md) — Start here to resume: full owner concept, Wirth/official-plan status, native tool reuse, commands, installed/runtime state, known crash, live-test outcomes and next steps.

- [2026-10-16 — Land in the past](2026-10-16-land-in-the-past.md)

- [2026-10-16 — Product clues and pinned history](2026-10-16-product-clues-and-pinned-history.md)

- [2026-10-16 — Overview labels and spoken courses](2026-10-16-overview-labels-and-spoken-courses.md)

- [2026-10-16 — Flight room and conversation families](2026-10-16-flight-room-and-conversation-families.md)

- [2026-10-16 — Recognizable places and return paths](2026-10-16-recognizable-places-and-return-paths.md)

- [2026-10-16 — Search carried context and publish charts](2026-10-16-search-carried-context-and-publish-charts.md)

- [2026-10-16 — Land and read carried context](2026-10-16-land-and-read-carried-context.md)

- [2026-10-16 — Scoped flight and version coverage](2026-10-16-scoped-flight-and-version-coverage.md)
- [2026-10-16 — Readable flight and native connections](2026-10-16-readable-flight-and-native-connections.md)
- [2026-10-16 — Hidden applications and physical copies](2026-10-16-hidden-apps-and-physical-copies.md)
- [2026-10-16 — Expertise candidates, readable sources and a dated system view](2026-10-16-expertise-source-windows-system-time.md)
- [2026-10-16 — Read the code and travel in time](2026-10-16-read-the-code-and-travel-in-time.md)
- [2026-10-16 — History and ship context retain their source](2026-10-16-history-and-ship-context.md)
- [2026-10-16 — First galactic flight, with evidence underneath](2026-10-16-first-galactic-flight.md)

| Date | Entry | Summary |
|---|---|---|
| 2026-10-15 | [A universe you can return to](2026-10-15-a-universe-you-can-return-to.md) | Owner-defined galaxy, product systems and planets, experimental moons, cities, expertise stars, starbases, and commissioned ships carrying a recoverable viewpoint; machines and cloud form the underlying physical plane. |
| 2026-10-02 | [navcom 0.9.1: every harness can revive an old session](2026-10-02-navcom-091-revive-every-harness.md) | PASTE_START for the 13 agents without a prompt flag (kimi, crush, goose, dsh, hermes, cline, reasonix, deepcode, aider, agy, kiro, amp, grok-dev): start command + prompt to paste, prompt auto-copied to clipboard when navcom launches them; REVIVE picker lists all 30, prompt-capable first. |
| 2026-10-02 | [navcom 0.9.0: revive old sessions with their context](2026-10-02-navcom-090-recap-revive.md) | navcom --recap REF = ~30k-char context pack (user msgs, where it stopped, commands, files changed); --resume REF --with HARNESS starts a fresh agent (17 harnesses) primed to run it; dead sessions ask which agent; menu REVIVE picker (r on dead / n anywhere); search footer + --open + --json + skill card point at it; live: fresh claude rebuilt a 5-month-old Codex review in 3 turns, $0.29. |
| 2026-10-02 | [navcom 0.8.0: get back into any conversation](2026-10-02-navcom-080-resume.md) | navcom --resume REF (cd + exec the harness here; --tab via cmux/tmux/iTerm2/WezTerm/kitty/Terminal; --print), resume line in search footer / --open / --json, menu RESUME line with r/t/c; per-harness table for all 30 (Kimi session_, Amp T-, Gemini sessionId, Grok Build ~/.grok/bin); deleted sessions auto-restored from archive or marked read-only; Gemini repr rows repaired (schema v3); 1,459 duplicate parser lines removed. |
| 2026-10-02 | [navcom 0.7.1: skill card reaches every harness, once](2026-10-02-navcom-071-skill-card-every-harness.md) | Data-driven skill_target_table: ~/.claude + ~/.agents (24 harnesses) + Continue/Hermes(+profiles)/Kiro/Antigravity folders; ~/.codex/skills retired (Codex listed the card twice) — managed unedited copy auto-removed; --skill install shows who reads each folder; side findings: broken apple-script-control YAML, invalid opencode.json. |
| 2026-10-01 | [navcom 0.7.0: CAPCOM-style --menu dashboard](2026-10-01-navcom-070-capcom-menu.md) | Bare navcom prints --help; navcom --menu = stdlib retro TUI (NAVCOM block wordmark, slogan, live HISTORY/RETENTION/ACTIVITY panels: Claude 30d vs navcom 100y, 2,802 rescued, 76 chats saved past day 30), search+reader, learn, CLI line on every screen; pty-driven + freeze-rendered QA. |
| 2026-10-01 | [navcom 0.6.0: 30 harnesses, still ~0.3s](2026-10-01-navcom-060-thirty-harnesses-fast.md) | Aider (830 real sessions found), Antigravity (login-free via local proxy), Factory, grok-dev live; Cursor/Kiro/Amp/Auggie fixture-proven; search rebuilt as one streaming rank pass + per-harness heap + Python snippets (the: 70s→1.4s, typical 0.05s); aider refs project@N. |
| 2026-10-01 | [navcom 0.5.0: 12 more harnesses via parallel agents](2026-10-01-navcom-050-twelve-more-harnesses.md) | Harness registry + ast-based integrator; Copilot, Cline (36 real VS Code tasks), Continue, Qwen, Kimi, Crush, Codewhale, Reasonix, Deep Code, Hermes, OpenHands, Vibe all live-verified; real-data counts match; Qwen/Hermes auto-deletion fixed (JSON + minimal YAML edit); telemetry findings logged. |
| 2026-10-01 | [navcom 0.4.0: DeepSeek, Grok, Kilo live; Gemini recovered](2026-10-01-navcom-040-deepseek-grok-kilo-gemini.md) | Installed + ran real dsh / Kilo / Grok Build sessions (Grok via DeepSeek custom model: xAI key out of credits) and proved navcom indexes prompt/reply/cmd/tool; Gemini .jsonl (since 0.39) was entirely missed — replay of $set/$patch/$rewindTo, verified 206/206 + 79/79; Gemini 30-day deletion disabled; dsh uploads full session logs to DeepSeek by default (documented). |
| 2026-10-01 | [navcom 0.3.0: keep everything](2026-10-01-navcom-030-keep-everything.md) | Tool outputs indexed for all 7 harnesses (role tool, capped head+tail, --tool/--everything); Codex exec_command + JS exec commands now captured; raw gzip archive of Claude transcripts with byte-exact --restore; daily launchd/systemd --maintain job (off sticks); real data: 208k outputs, index 1.12 GB, archive 415 MB, search 0.3s. |
| 2026-10-01 | [navcom 0.2.3: stop Claude deleting history; private index](2026-10-01-navcom-023-retention-privacy.md) | Claude Code deletes transcripts after 30 days (hard-coded since launch, v0.2.9 2025-02-24, setting since v0.2.118); navcom now sets cleanupPeriodDays=36500 when unset (backup, atomic, respects explicit, skips JSONC); index made 0600 (was 0644 copy of 0600 transcripts); tool outputs measured (86 MB Claude) — not yet indexed. |
| 2026-09-30 | [navcom 0.2.2: `navcom --skill`](2026-09-30-navcom-022-skill-flag.md) | `--skill` prints the stock SKILL.md, `--skill install` full-service install; Skillflag-compatible list/export (deterministic tar), interop proven with `npx skillflag install`; rejected its never-install rule. |
| 2026-09-30 | [navcom 0.2.1: self-installing skill, --help as manual, fair per-harness -n](2026-09-30-navcom-021-skills-help-fairness.md) | Skill card embedded + silently installed into ~/.claude/skills, $CODEX_HOME/skills, ~/.agents/skills (hash-guarded, never clobbers edits); -n per harness merged by BM25; --help rewritten as the LLM manual, all 37 documented examples tested. |
| 2026-09-30 | [navcom 0.2.0: LLM-proof search + 4 new harnesses](2026-09-30-navcom-020-llm-proof-search.md) | Mined 1,093 real LLM navcom calls (89 crashes, 109 zero-hit, 17 locks, 4GB-log slowness). Rewrote query cooker (0 errors / 60k fuzz, 911/918 historical queries now hit), compact default, --open drill-down, --here/--days/--this-session, text-only matching, self-exclusion, incremental+WAL+lock-tolerant index, bounded summarizers; added pi/omo/opencode/goose; BDD+pytest; published 0.2.0. |
- [2026-10-15 — NavCom orchestrates local Starforge harvest](2026-10-15-navcom-orchestrates-local-harvest.md)
- [2026-10-16 — Starforge already searches skipped files](2026-10-16-starforge-already-searches-skipped-files.md)
- [2026-10-16 — Starforge source search is now a NavCom CLI capability](2026-10-16-starforge-source-cli.md)

- [Voice, native handoffs and dated turns](2026-10-16-voice-native-handoffs-and-dated-turns.md) — shared CLI/UI actions, native timestamp ingestion and local speech proof.
- [Resumable chart intake](2026-10-16-resumable-chart-intake.md) — shared automatic harvest, native root grouping, stable lab identities, question evidence and browser continuity.

- [Stored ships and native submodules](2026-10-16-stored-ships-and-native-submodules.md) — automatic archive discovery, carried-context navigation and native Git ownership.
