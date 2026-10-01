# navcom 0.2.3: Claude Code was deleting your history after 30 days; navcom now stops it

**Pain:** Claude Code deletes local transcripts older than `cleanupPeriodDays` (default 30) on
startup. On this Mac the oldest surviving Claude transcript was from 2026-09-02, and only 178
remained. Separately, navcom's 700 MB index (a plain-text copy of those transcripts) was `0644`
inside a home folder that every standard macOS user can traverse (`drwxr-x---`, group `staff`).
Claude keeps the originals `0600`, and navcom was quietly undoing that.

## Summary

- **History of the deletion,** from npm tarballs bisected with `npm pack` and grep:
  - First npm release: 0.2.9, on 2025-02-24.
  - Hard-coded 30-day cleanup (`2592000000` ms): **present in the very first public release,
    v0.2.9 (2025-02-24, launch day)**. On every startup, `setImmediate(...)` reads the `messages()`
    (conversation logs) and `errors()` directories and `unlink`s every file whose timestamped name is
    older than 30 days. It is also confirmed in 0.2.14, 0.2.18, 0.2.19, 0.2.25, 0.2.27, 0.2.29, 0.2.33 …
  - CORRECTION: the first pass said "since v0.2.33 (2025-03-07)". That search grepped only
    `*.js`, but releases up to 0.2.32 ship `cli.mjs`. Always grep `*.*js`.
  - It became the setting `cleanupPeriodDays` in **v0.2.118 (2025-05-18)**; absent in 0.2.113.
  - Current 2.1.280 (2026-09-22): schema `int().positive()`, default 30. `0` is rejected, and the
    binary's own text says 0 "previously silently disabled all transcript writes".
  - The sweep also prunes history entries, session files and artifacts.
  - Claude Desktop/Cowork transcripts are exempt unless `desktopSessionCleanupPeriodDays` is set.
- **This Mac:** set `"cleanupPeriodDays": 36500` by hand. Backup at
  `~/.claude/settings.json.bak-before-retention-20261001-111529`. No managed policy:
  `/Library/Application Support/ClaudeCode/` does not exist.
- **navcom 0.2.3:**
  - `ensure_claude_retention()` runs silently on every call. If the key is missing it sets 36500,
    keeps a one-time backup (`settings.json.navcom-backup`) and writes atomically. It respects an
    explicit value and never touches non-JSON (JSONC) files. `NAVCOM_NO_RETENTION_FIX=1` opts out.
    `--where` shows the retention.
  - `private_file()` sets the index and its `-wal`/`-shm` files to 0600 (the side files right after
    the connection opens), and new indexes are created 0600. `navcom-skills.json` is 0600 too.
- **What survived:**
  - navcom's index still holds 4,097 Claude sessions back to 2026-03-24: the text, commands and
    replies, but NOT tool outputs.
  - Codex, Gemini, pi and omo never delete. Their oldest files are from 2025-06 and 2025-07.
  - Time Machine destination `TM-CAPTAINS-MBPRO` (local, 1.5 TB) reports "No machine directory
    found for host", and listing needs Full Disk Access. Unverified.
- **Tool outputs:** navcom never indexed them. Measured on disk now: 33,837 Claude tool outputs,
  86 MB of text, 5,437 of them over 4 KB; at 4 KB each, about 45 MB. Proposal pending with the owner.

## Decisions

- **Respect explicit values; only fill a missing one.** "My data, my control" applies to the
  user's own choice too. The danger is the silent default, not a deliberate setting.
- **36500, not 0.** Zero is invalid now, and historically it meant "write nothing".
- **Skip JSONC/invalid settings.** Corrupting Claude's settings would pause its cleanup but break
  the user's config, and `/doctor` would complain.

## Snippets

```bash
# which version introduced the deletion (bisect npm releases)
f=$(npm pack @anthropic-ai/claude-code@0.2.9 --silent); mkdir x; tar -xzf $f -C x
grep -a -o 2592000000 x/package/*.*js           # *.*js: early releases ship cli.mjs!
npm view @anthropic-ai/claude-code time --json   # release dates
# check / fix retention by hand
python3 -c "import json,os;print(json.load(open(os.path.expanduser('~/.claude/settings.json'))).get('cleanupPeriodDays'))"
navcom --where | grep retention
```

## Files changed

- `navcom.py`: the retention section (`CLAUDE_RETENTION_DAYS`, `claude_settings_path`,
  `claude_retention_status`, `ensure_claude_retention`, `private_file`). The index is created
  0600; `--where` gains a retention line; version 0.2.3.
- `features/skills.feature` and its steps: the missing key gets set, the other keys are untouched
  and backed up, explicit 90 is respected, JSONC is untouched, `--where` reports it, the index is
  private.
- `README.md`: a "Your history stays yours" section. `pyproject.toml`: 0.2.3.

**tags:** navcom, claude-code, cleanupPeriodDays, data-retention, transcripts-deleted, privacy,
file-permissions, 0600. The release where navcom started protecting your history instead of just
searching it.
