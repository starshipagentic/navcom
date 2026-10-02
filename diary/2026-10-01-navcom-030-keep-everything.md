# navcom 0.3.0: keep everything (tool outputs searchable, raw transcripts archived, daily upkeep)

**Pain:** Claude Code had already deleted the tool outputs (command output, files read, errors)
of 2,802 sessions, and navcom had never indexed tool outputs at all. Protection also depended on
someone running navcom: a harness's 30-day sweep could beat it.

## Summary

- **Tool outputs indexed, role `tool`, for all 7 harnesses:**
  - Claude `tool_result`, labelled from the `tool_use` id map.
  - Codex `function_call_output` and `custom_tool_call_output`, labelled from the `call_id` map.
    Codex's JSON envelopes `{"exit_code","output"}` are unwrapped.
  - Gemini `toolCalls[].resultDisplay`.
  - pi/omo `toolResult` and `bashExecution.output`.
  - opencode `part.state.output`.
  - goose `toolResponse`.

  Each output is capped at a 3 KB head plus a 1 KB tail; base64 and data: blobs become
  `[binary data]`. navcom's own output is never indexed: it's detected by the originating command
  or by its output markers.

  Outputs are excluded from normal searches. `--tool` searches only outputs, `--everything`
  searches turns plus outputs, and `--role tool` also works. `PARSER_VERSION` is now 3.
- **Codex commands fixed:** newer Codex logs commands as `function_call exec_command {cmd}` and as
  `custom_tool_call exec` (JS: `await tools.exec_command({"cmd": …})`). Before this, only the old
  `shell_command` form was understood. Indexed cmd rows went from about 130k to 187k.
- **Raw archive:** `~/.navcom/archive/<harness>/<path>.jsonl.gz`, files 0600 and dirs 0700.
  - Appends are written as extra gzip members, so the archive decompresses byte-identical to the
    original (tested).
  - The fingerprint covers only already-archived bytes, so appends stay incremental. That was a
    bug found by tests, for files under 4 KB.
  - Oldest files are archived first, since they're the closest to a deletion sweep. Normal calls
    get a 1-second budget; `--maintain` has none.
  - `--restore REF` and `--restore all` write the file back with its original mtime and print
    `cd <cwd> && claude --resume <uuid>`.
  - Default harness is Claude only (`NAVCOM_ARCHIVE=all|off|list`). Codex logs barely compress
    (1.5x, encrypted reasoning blobs), and Codex never deletes.
- **Daily job:**
  - macOS: launchd `~/Library/LaunchAgents/io.navcom.maintain.plist`, at 12:17 daily, with missed
    runs firing on wake. It logs to `~/.navcom/maintain.log`.
  - Linux: a systemd user timer, `OnCalendar=daily`, `Persistent=true`.
  - Auto-installed silently. `--daily off` writes `~/.navcom/daily-off`, so it stays off.
    `NAVCOM_DRY_SCHEDULER=1` in tests writes the files without calling launchctl.
- **`--maintain`** (with `--reindex` to force) runs a full pass with no budgets.

## Measured (copy of the real index, this Mac)

- `--maintain --reindex`: 2,607 sessions in 175s; 1,344 Claude transcripts archived, 1.15 GB raw
  down to **415 MB**.
- Index went from 686 MB to **1.12 GB**. Rows: tool 208,395 · cmd 186,763 · assistant 111,941 · user 24,361.
- Search is still **0.26–0.30s**, and `--tool` is the same.

## Decisions

- Tool outputs are kept out of default search, since file dumps would drown conversation hits;
  turning them on is one flag.
- The archive is Claude-only by default: it's the harness that deletes. Codex would add about
  10 GB for little benefit.
- The archive goes oldest-first: protect what's nearest a 30-day sweep.
- The daily job installs silently, per the owner's "full-turn service" rule, but `off` sticks.

## Files changed

- `navcom.py`:
  - Tool-output layer: `cap_tool_output`, `tool_turn`, `_call_label`, `_shell_cmd`,
    `iter_claude_lines`, `iter_codex_lines`, `iter_gemini_file`, plus extensions to the
    pi/opencode/goose parsers.
  - Search plumbing: `include_tools`, `--tool`, `--everything`.
  - Archive: `archive_*`, `cmd_restore`.
  - Daily job: `install_daily_job`, `remove_daily_job`, `daily_job_status`.
  - `cmd_maintain`, `--restore`, `--maintain`, `--daily`, new `--help` sections, skill card lines.
  - Version 0.3.0.
- `features/keep_everything.feature` and its steps, `features/support/fake_home.py` (tool outputs
  in every harness), and `tests/test_harness_parsers.py`. That last file covers per-harness tool
  turns, the Codex new formats, the JSON envelope, capping, incremental archive and restore.
- `README.md`, `skills/.../SKILL.md`, `pyproject.toml`.

**tags:** navcom, tool-outputs, raw-archive, gzip-members, restore, launchd, systemd-timer,
maintain, codex-exec_command. The release where navcom keeps everything, on its own schedule.
