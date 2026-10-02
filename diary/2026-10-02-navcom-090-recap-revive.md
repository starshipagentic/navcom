# navcom 0.9.0: revive any old session in a fresh agent (`--recap`, `--resume --with`)

**Pain:** a session too old to reopen was a dead end. Its harness had deleted it, or the harness can't
resume, or the context was stale. navcom said "read it with `--open`". But a whole-session `--open` is
**400 KB** for a long session (this build session: 4,964 lines), which floods a fresh agent's context.
There was no pointed "run this to get your context back" for an LLM.

## Summary

- **`navcom --recap REF`** prints a context pack (~30k chars ≈ 8k tokens; `--max-chars` changes it):
  - a header, and a "reopen it:" line (or "not possible")
  - every user message, oldest first; #1 (the goal) gets 2,000 chars, the others 700, and the middle is elided with a pointer when over budget
  - where it stopped: the last 14 user/assistant turns
  - the last 25 distinct commands
  - files changed, parsed from `[Write|Edit|…: path]` tool labels and `*** Update File:` patches, shown relative to the session folder
  - "Dig deeper" pointers
- **`navcom --resume REF --with HARNESS`** starts a *fresh* session of any of 17 harnesses in that folder, primed with:
  "We are picking up an earlier <h> session from <date> in this folder ("<title>"). Before anything else, run
  `navcom --recap <ref>` [and `navcom --open <ref>:<n>` for the part I was looking at]. Then tell me … where it
  left off and what the next step was."
- **Dead sessions** (deleted and unarchived, or a harness with no resume):
  - `--resume` asks which agent to use: a numbered picker on stderr, the session's own harness first, then the others by how often you use them.
  - Non-tty or `--print`: prints the primed line for the best installed agent.
- **Menu:**
  - `r`/`t` on a dead session, or `n` on any session, open a **REVIVE ▸ ref** picker: ↑↓ agent, enter here, `t` tab, `c` copy.
  - The RESUME line on a dead session says "start a fresh agent that reloads it".
- **Pointers everywhere:**
  - Search footer: `whole story: navcom --recap <ref>`. A dead top session gets a "revive it: navcom --resume <ref> --with claude" line.
  - `--open` prints `recap:` and revive lines.
  - `--json` has `"recap"`.
  - The skill card's recipe has step 3 "`navcom --recap <ref>`" plus a "Continuing old work" paragraph.
  - Help recipe and GET BACK section; LEARN page.
- **`--recap` output is marked**, so it is never indexed as a search hit.

## Decisions

- **The user chose "let me pick the harness"** over auto-starting the same harness or only printing a line.
  - Start in the same harness: rejected, because the old harness may be gone, or worse.
  - Only print the line: rejected, because the user wanted it actionable.
  - So the same harness is listed first, and any installed primed-capable agent can be picked.
- **Named `--recap`, not `--brief`:** `--brief` is already an alias of `--compact`.
  - Repurposing it would make `navcom deploy --brief` swallow the next word as a REF.
  - The aliases `--catchup`, `--rehydrate` and `--handoff` were added.
- **A fresh session that loads a pack, not stuffing the transcript into the prompt.**
  - **Why:** the prompt stays a short, shell-safe line (no apostrophes, so no `'"'"'` escaping). The agent pulls context itself and can drill in with `--open`.
- **`FRESH_START` only lists harnesses whose interactive-with-prompt syntax is confirmed in `--help`:**
  - Positional prompt: claude, codex, pi, omo, Grok Build, vibe, droid, auggie, cursor-agent, codewhale, cn.
  - A flag: gemini `-i`, qwen `-i`, opencode/kilo `--prompt`, copilot `-i`, openhands `-t`.
  - Left out: kimi (only non-interactive `-p`), crush/amp/reasonix/deepcode/dsh/goose/aider/kiro/agy/grokdev/hermes/cline (unconfirmed).
- **Budget 30k chars:** the user said "LLMs are beasts, stop worrying about rows". It is still about 7% of the raw 400 KB.

## Snippets

```bash
navcom --recap e1c66e96273f                         # the pack
navcom --resume e1c66e96273f --with claude --print  # cd ~/clients/syra/syrab2bdev && claude 'We are picking up …'
# live proof (dev build on PATH via a shim; installed 0.8.0 had no --recap, so the first run flailed to max-turns):
cd ~/clients/syra/syrab2bdev && claude -p "$PROMPT" --allowedTools "Bash(navcom:*)" --max-turns 12 --output-format stream-json --verbose
```

Live result: 3 turns, $0.29.
- **Tool calls:** `navcom --recap e1c66e96273f | head -300`, then `navcom --open e1c66e96273f:70` plus `git ls-files`.
- **What it rebuilt:** the 2026-04-30 Codex pre-push review of commit 3327c2f9.
  - 22 permissions; SuperAdmin admin-only; the ECS env; the bus-monitor guard; `tsc` passed.
  - It flagged a MEDIUM leftover (`src/app/tour/policy-blocks-cross-org/page.tsx`) and a LOW one (412 `tours/**` files).
- **It then verified today's state:** the tour page is gone; `tours/` was kept.

## Files

- `navcom.py`:
  - **recap:** `session_recap`, `cmd_recap`, `RECAP_BUDGET`.
  - **revive:** `FRESH_START`, `fresh_harnesses`, `revive_prompt`, `revive_plan`, `_pick_harness_cli`; `--recap`/`--with` flags; `cmd_resume` revive branch.
  - **tui:** `_menu_revive`, the `n` key, `_resume_action(term, key, provider, focus)`, the dead-session span.
  - **pointers:** `resume_hint` (top session), the `--open` recap/revive lines, JSON `recap`.
  - **docs:** skill card / help / LEARN text; the output marker.
- `features/resume.feature`, `features/steps/navcom_steps.py`:
  - **bdd:** dead → primed fresh agent, recap sections, footer pointer, `--with gemini`, a `--with aider` error.
- `tests/test_resume.py`:
  - **unit:** recap sections and budget, the revive prompt (shell-safe, every `FRESH_START` carries it), copy on a dead session.
- `README.md`, `skills/navcom-session-recall/SKILL.md`, `pyproject.toml`, `features/search.feature`:
  - **docs + release:** 0.9.0.

**tags:** navcom, recap, revive, context-pack, fresh-agent, cross-harness, tui-picker, skill-card,
release-0.9.0. An old conversation is now one command away from a fully briefed agent.
