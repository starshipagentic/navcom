# navcom 0.9.1: every harness can revive an old session (start it, paste the prompt)

**Pain:** 0.9.0 only offered the 17 agents whose `--help` confirms an opening-prompt flag. Kimi, Crush,
goose, dsh, Hermes, Cline, Reasonix, Deep Code, Aider, Antigravity, Kiro, Amp and grok-dev were hidden.
The user's point: "that agent can use the cli like anyone else" — just give the start command and the
text to paste.

## Summary

- **`PASTE_START`** (13 harnesses): the plain start command for agents without a prompt flag.
  - `kimi`, `crush`, `goose session`, `dsh`, `hermes`, `cline --tui`, `reasonix`, `deepcode`, `aider`, `agy`, `kiro-cli chat`, `amp`, `grok`.
  - `REVIVE_AGENTS` = `FRESH_START` + `PASTE_START` = all 30 harnesses (a unit test asserts it covers `ALL_PROVIDERS`).
- **`revive_plan` gains a `paste` field.** `revive_text` renders either the one-line command or:
  ```
  cd ~/clients/syra/syrab2bdev && kimi
  # then paste this into kimi:
  We are picking up an earlier codex session … run `navcom --recap e1c66e96273f` …
  ```
- **When navcom launches a paste-type agent itself**, it copies the prompt to the clipboard first and prints it, then `exec`s the agent. This happens via `--resume` here, `--tab`, or the menu's enter/`t`, so you only press paste. Verified in a pty: the stand-in `hermes` started in `~/clients/syra/syrab2bdev` and the clipboard held the prompt.
- **The REVIVE menu screen** lists them as "start it, then paste the prompt" and shows a `start:` and a `paste:` line. `c` copies the prompt, the part you can't type yourself.
- **Picker order:** the session's own harness, then prompt-capable agents by use, then paste-type agents by use. Before this, paste-type agents with test sessions (agy, hermes) outranked codex/gemini.
- **`--with <unknown>`** errors with the full list of 30.

## Decisions

- **Clipboard + print, not keystroke injection.**
  - Rejected: typing the prompt into the agent's TUI via `cmux send` / tmux `send-keys` / AppleScript.
  - **Why:** each agent's TUI boots at a different speed and some show trust dialogs first, so injected text would land in the wrong place. Pasting is reliable and still one keystroke.
- **`c` in REVIVE copies the prompt for paste-type agents, not the two-step text.**
  - **Why:** pasting the multi-line text into a shell would run the prompt line as a command.

## Files

- `navcom.py`:
  - **revive:** `PASTE_START`, `REVIVE_AGENTS`, `_start_argv`, `fresh_harnesses` (ordering), `revive_plan` (paste), `revive_text`, `resume_here`, `resume_in_new_tab` → `_open_tab`.
  - **tui:** `_menu_revive` labels / paste line / copy.
  - **docs:** help and `--with` text; 0.9.1.
- `features/resume.feature`:
  - **bdd:** a `--with kimi --print` start+paste scenario; the unknown-agent error lists every agent.
- `tests/test_resume.py`:
  - **unit:** every harness can be revived; paste-type launch copies the prompt.
- `README.md`, `skills/navcom-session-recall/SKILL.md`, `pyproject.toml`, `features/search.feature`:
  - **docs + release.**

**tags:** navcom, revive, paste-prompt, clipboard, all-harnesses, release-0.9.1. No agent is left out of
picking an old conversation back up.
