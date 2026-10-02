# navcom 0.8.0: get back into any conversation (`--resume`, and r / t / c in the menu)

**Pain:** navcom found the conversation, then left you holding a "funny short id". To get back into it you
had to work out which folder it ran in, which harness it was, that harness's resume flag, and which id that
flag wants. For example, Kimi wants `session_<uuid>`, Amp wants `T-<uuid>`, and Gemini wants the
`sessionId` *inside* the file.

## Summary

- **Every search** now ends with a copy-paste line:
  `→ get back into [1] yourself: cd ~/proj && claude --resume <uuid> · any session: navcom --resume <ref> (--tab: new tab)`.
- **`navcom --resume REF`** cds to the session's folder and `exec`s the harness in this terminal.
  - `--tab` opens it in a new tab of the terminal you're in.
  - `--print`, or any non-tty, prints the command. Agents and pipes never launch an interactive agent.
  - Hit refs (`abc:73`) work too.
- **`--open`** prints a `resume:` line, and `--json` gains `"resume"`.
- **`--menu`:** the search and session screens, and RECENT SESSIONS, have a RESUME line with the command and `r`/`t`/`c` key chips.
  - `r` restores the terminal and hands it to the harness.
  - `t` opens a new tab.
  - `c` copies the command.
- **Deleted sessions:**
  - Gone but archived: restored from navcom's archive first.
  - Gone and never archived: navcom says it is read-only and points to `--open`.
- **Also fixed:**
  - 45 index rows from deleted old Gemini `.json` sessions showed `{'text': '…'}`. The schema v3 migration rewrites them in place, including one capped repr with no closing quote.
  - The integrator spliced the shared Codewhale/Reasonix/Deep Code parser three times: 1,459 dead lines. It is now spliced once.

## Decisions

- **Exec in the same terminal by default.**
  - **Why:** it's trivial (`os.chdir` + `os.execvp`) and needs no terminal-specific code. When the agent exits you are back at your shell.
- **New tab: detect the terminal and use its own control channel.**
  - **cmux:** the user's terminal (Ghostty-based, `CMUX_WORKSPACE_ID`). Uses `cmux new-workspace --cwd --command`. The command is typed into a login shell, so the tab stays after the agent exits. Verified live and cleaned up.
  - **tmux:** `tmux new-window -c`.
  - **WezTerm:** `wezterm cli spawn --cwd`.
  - **kitty:** `kitty @ launch --type=tab` (needs remote control).
  - **iTerm2:** AppleScript `create tab` + `write text`.
  - **Terminal.app:** `do script`. That makes a *window*; a tab would need Accessibility keystrokes, which we rejected.
  - **Plain Ghostty:** `open -na Ghostty.app --args --working-directory -e` (a new window; Ghostty has no tab API).
  - **Linux:** gnome-terminal `--tab`.
  - **Otherwise:** copy to the clipboard and say so.
- **Always `cd` first.**
  - **Why:** more than half the harnesses look sessions up per folder (Claude, Gemini, Qwen, Kimi, Deep Code, Cursor, opencode/kilo, Crush). The rest run their tools in the current folder. Kiro even rewrites the stored cwd to wherever you resume from.
- **Claude's folder comes from the transcript's own `cwd` field**, not from decoding `-Users-t-x`.
  - **Why:** the decode is ambiguous when real paths contain dashes, and it made a BDD scenario flaky.
- **No resume-by-id (Continue, Aider):**
  - **Chose:** give the closest command (`cn --fork`, `aider --restore-chat-history`) plus a stderr note on what it really does.
  - **Rejected:** the `touch <id>.json && cn --resume` hack. It mutates mtimes, and it is unconfirmed.
- **Cline VS Code extension tasks** and **Kiro v1 SQLite** conversations:
  - Cline extension tasks: nothing exact exists. They return None, so the menu shows "can't reopen".
  - Kiro v1: falls back to `kiro-cli chat --resume` (the latest one in that folder).
- **`--continue` as an alias:** rejected. It is already the Continue harness flag (argparse conflict).
- **Grok Build** is called as `~/.grok/bin/grok`.
  - **Why:** `/opt/homebrew/bin/grok` on this Mac is the old `@vibe-kit/grok-cli`, and the shell has a `grok` alias.

## Snippets

```bash
navcom --resume 5c255b74 --print          # cd ~/dev/navcom && claude --resume 5c255b74-767c-…
navcom --resume e1c66e96273f:42           # hit refs work; execs codex resume <uuid> in ~/clients/syra/syrab2bdev
navcom --resume <ref> --tab               # cmux: new workspace named "claude · navcom"
CMUX_QUIET=1 cmux new-workspace --name T --cwd DIR --command "codex resume <id>"   # what --tab runs in cmux
cat frame.ansi | freeze -o docs/menu-resume.png --language ansi --window=false     # file arg form HANGS; pipe it
.venv/bin/behave features/resume.feature --format progress3                          # 35 scenarios, every harness
```

TUI QA ran in a pty (`scratchpad/drive_resume.py`), with fake `pbcopy` and `codex` on PATH:
- `c` → clipboard holds the exact line.
- `r` → `FAKE-CODEX cwd=/Users/t/clients/syra/syrab2bdev args=resume 019f49ce-…`.

## Files

- `navcom.py`:
  - **resume:** `RESUME_COMMANDS` (28 harnesses), `RESUME_FALLBACKS`, `resume_plan`, `ensure_resumable`, `resume_here`, `resume_in_new_tab`, `copy_to_clipboard`, `cmd_resume`.
  - **footer:** `resume_hint` (search footer), the `--open` `resume:` line, the JSON `resume` field, the `--sessions` tip.
  - **tui:** `_ResumeNow`, `_resume_span`, `_resume_action`, `_screen(resume=)`, r/t/c in search, view and recent, and the `run_menu` wrapper.
  - **docs:** a LEARN "GET BACK IN" page, a help "GET BACK INTO A CONVERSATION" section, and a skill card line.
  - **index-repair:** schema v3 `_repair_part_reprs`.
  - **dedupe:** the generated section, one copy of the DeepSeek-family parser.
- `features/resume.feature` + `features/steps/navcom_steps.py`:
  - **bdd:** every harness's command, fallbacks, `--open`/`--json`, hit refs, the deleted+unarchived case and the archived-restore case.
- `features/support/fake_home.py`:
  - **fixture:** Claude records carry `cwd`, like the real thing.
- `tests/test_resume.py`:
  - **unit:** exact-width RESUME line, copy key, `r` raises `_ResumeNow`, new-tab dispatch per terminal (recorder binaries), clipboard fallback, the repr repair.
- `README.md`:
  - **docs:** the "Get back into a conversation" section + `docs/menu-resume.png`.
- `skills/navcom-session-recall/SKILL.md`:
  - **skill:** regenerated with the `--resume --print` line.
- `pyproject.toml`, `features/search.feature`:
  - **release:** 0.8.0.
- Scratchpad `harness/integrate.py` (not in the repo):
  - **integrator:** CONFIG order = navcom order, and each parser source is spliced once.

## Appendix: resume table (verified by `--help` on installed harnesses + agent research from help/source/docs)

| harness | command | id |
|---|---|---|
| claude | `claude --resume <uuid>` | file stem; a subagent → its parent session |
| codex | `codex resume <uuid>` | rollout uuid |
| gemini | `gemini --resume <sessionId>` | `sessionId` field in the file (not `session-…` name) |
| opencode / kilo | `opencode --session ses_…` / `kilo --session ses_…` | |
| pi / omo | `pi --session <uuid>` / `omo --session <uuid>` | |
| goose | `goose session --resume --session-id <id>` (legacy .jsonl: `--name <stem>`) | |
| dsh | `dsh tui --resume session-<uuid>` | |
| grok (Build) | `~/.grok/bin/grok --resume <uuid>` | |
| qwen | `qwen --resume <uuid>` | |
| kimi | `kimi -S session_<uuid>` | folder name |
| crush | `crush --session <id>` | per-project `.crush/crush.db` → cd |
| copilot | `copilot --resume <uuid>` | |
| cline | `cline --id <id>` | VS Code extension tasks: none |
| continue | `cn --fork <id>` (fallback: copy of the history) | |
| codewhale | `codewhale --resume <id>` (legacy `~/.deepseek`: `deepseek resume <id>`) | |
| reasonix | `reasonix --resume <stem>` | |
| deepcode | `deepcode -r <uuid>` | |
| hermes | `hermes --resume <id>` | |
| openhands | `openhands --resume <32hex>` | |
| vibe | `vibe --resume <8-char short id>` | |
| agy | `agy --conversation <uuid>` (the `agy` on PATH here is the editor launcher) | |
| droid | `droid --resume <uuid>` | |
| cursor | `cursor-agent --resume <chatId>` | |
| kiro | `kiro-cli chat --resume-id <uuid>`, v3 `kiro-cli --v3 --resume-id sess_…`; v1 SQLite → `kiro-cli chat --resume` | |
| amp | `amp threads continue T-<uuid>` | |
| auggie | `auggie --resume <id>` | |
| grokdev | `grok --session <id>` | |
| aider | `aider --restore-chat-history` (fallback: whole folder history) | |

**tags:** navcom, resume, cmux, terminal-tabs, tui, clipboard, osc52, gemini-repair, integrator-dedupe,
release-0.8.0. Every hit now carries the exact command to step back into the conversation yourself.
