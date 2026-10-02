# navcom 0.7.1: the skill card reaches every harness, once

**Pain:** the user saw navcom's skill card land in "just three" folders (`~/.claude/skills`, `~/.codex/skills`,
`~/.agents/skills`) while navcom reads 30 harnesses. Worse, the Codex copy was harmful: Codex reads both
`~/.codex/skills` and `~/.agents/skills` and listed `navcom-session-recall` twice.

## Summary

Two research agents checked, harness by harness (from source and live runs), which folders each one reads
skills from. The result became a data-driven table, `skill_target_table()`. Each entry is a folder, the
harness homes that must exist before it is written, and who reads it. navcom now writes:

| Folder | Read by |
|---|---|
| `$CLAUDE_CONFIG_DIR/skills` | Claude Code (opencode, Kilo, goose, Grok, Crush, Amp, Augment, Cursor read it too) |
| `~/.agents/skills` | Codex, Gemini CLI, Copilot CLI, pi, omo, opencode, Kilo, goose, Qwen, Kimi, Crush, dsh, Grok Build, Cline, Codewhale, Reasonix, Deep Code, OpenHands, Vibe, Factory, Cursor, Amp, Augment, grok-dev |
| `~/.continue/skills` | Continue (cn + IDE): reads neither shared folder |
| `$HERMES_HOME/skills` + `profiles/*/skills` | Hermes Agent |
| `$KIRO_HOME/skills` | Kiro CLI |
| `~/.gemini/config/skills` | Antigravity CLI |

The `~/.codex/skills` copy is retired: on upgrade navcom deletes it, but only if it carries the marker and
its hash matches what navcom wrote. Edited copies and symlinks onto a live target are left alone.
`--skill install` now prints who reads each folder and the Aider note.

## Decisions

- **Chose:** one copy per folder, with the fewest folders that cover everyone.
  - **Rejected:** writing every harness's own folder (`~/.factory/skills`, `~/.openhands/skills`, `~/.gemini/skills`, `~/.codex/skills`, …).
  - **Why:** Codex lists duplicates, Gemini shows a conflict warning, Factory marks a second personal copy invalid, OpenHands warns, and opencode/Kilo log a duplicate. More copies is worse.
- **Chose:** widen the `~/.agents/skills` presence list (`~/.codex`, `~/.gemini`, `~/.qwen`, `~/.kimi-code`, `~/.copilot`, `~/.config/crush`, `~/.config/kilo`, `~/.kilocode`).
  - **Why:** a machine with only one of those harnesses still gets the card.
- **Aider:** it has no global skills mechanism.
  - **Rejected:** editing `~/.aider.conf.yml`, because it is a user-owned file.
  - **Chose:** print a one-line hint instead.
- **Codewhale:** it shows a cosmetic "shadowed" note when the card is in both `~/.claude` and `~/.agents`. Acceptable.
- **grok-dev:** needs a real `~/.agents/skills` folder, not a symlink. navcom writes real files, so it is fine.
- **Left alone:** `~/.codex/skills/navcom-session-recall/agents/openai.yaml`, a July hand-made Codex display file.
  - **Why:** it is not navcom's. Codex ignores a skill folder that has no SKILL.md.

## Snippets

```bash
navcom --skill install            # shows each folder + "read by …", removes the old Codex duplicate
.venv/bin/behave features/skills.feature --format progress3   # 18 scenarios, incl. retire + edited-never-deleted
.venv/bin/python -m pytest -q     # 67 passed
```

Live result on this Mac: Codex copy removed. Card present in `~/.claude`, `~/.agents`, `~/.continue`,
`~/.hermes` and `~/.gemini/config`. `~/.kiro` is absent, so Kiro is skipped.

## Files

- `navcom.py`:
  - **skill-targets:** `skill_target_table()`, `retired_skill_targets()` and `skill_targets()`.
  - **retire:** a retirement pass in `install_skills`.
  - **report:** a "read by" line per folder.
  - **help:** `--help` lists the harnesses.
  - **version:** bumped to 0.7.1.
- `features/skills.feature` and `features/steps/navcom_steps.py`:
  - **bdd:** asserts the Continue/Hermes cards and that the Codex card is missing.
  - **retire scenarios:** a duplicate is retired; an edited Codex card is never deleted.
- `features/search.feature`:
  - **version:** expects 0.7.1.
- `README.md`:
  - **docs:** a folder → harness table.
- `pyproject.toml`:
  - **release:** 0.7.1.

## Appendix: side findings on this machine (not navcom bugs)

- `~/.agents/skills/apple-script-control/SKILL.md` has broken YAML frontmatter: an unquoted `: ` in its description. Strict loaders skip it.
- `~/.config/opencode/opencode.json` is invalid: `mcp.starforge` is missing `type` and `enabled`, so opencode refuses to start.
- An Amp device-code login (`TTHQ-NPCQ`) was started by a research agent and killed unconfirmed. Deny it if prompted.

tags: skills, agent-skills, codex-duplicate, harness-coverage, release-0.7.1. The skill card now lands in
every folder a harness reads, exactly once.
