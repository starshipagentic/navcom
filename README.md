# navcom

Super-fast search over your past AI coding sessions, from one command.

navcom indexes the transcripts your coding agents already write to disk (SQLite FTS5, incremental) and
answers "where did we talk about X?" in well under a second. It's built to be called by LLM agents
from their shell tool, and by you.

| Harness | Where navcom reads it |
|---|---|
| Claude Code | `$CLAUDE_CONFIG_DIR/projects` (default `~/.claude/projects`) |
| Codex CLI | `$CODEX_HOME/sessions` (default `~/.codex/sessions`) |
| Gemini CLI | `~/.gemini/tmp/*/chats` |
| pi | `$PI_CODING_AGENT_SESSION_DIR` or `~/.pi/agent/sessions` |
| omo (OmO) | `$OMO_CODING_AGENT_SESSION_DIR` or `~/.omo/agent/sessions` |
| opencode | `$XDG_DATA_HOME/opencode/opencode.db` (and legacy `storage/message`) |
| goose | `$XDG_DATA_HOME/goose/sessions/sessions.db` (and legacy `*.jsonl`) |

Run `navcom --where` to see what it found on your machine.

## Install

```bash
pipx install navcom        # or: uv tool install navcom
pipx upgrade navcom
```

No dependencies. Python 3.10+.

## Use

```bash
navcom drizzle migration            # every harness; compact hits grouped by session
navcom --open 395e14b4:73           # read the turns around hit #73 of that session
navcom drizzle --context            # expand every hit with the turns around it
navcom                              # your most recent sessions, with titles
navcom drizzle --solo               # one LLM summary of all the hits
```

Output is plain text when piped (no color codes), so agents can read it:

```
navcom: 7 hits in 3 sessions · query: drizzle* migration*
[1] 2026-09-28  claude   ~/clients/syra/syrab2bdev  ref 7ec78a59  (4 hits)
    #533 assistant: The «migration» runner looks correct — it reads `«drizzle»/*.sql` …
    #570 cmd: git add «drizzle».config.ts Dockerfile …
[2] 2026-09-27  codex    ~/dev/api  ref 0174f1b5255f  (3 hits)
    …
→ read around a hit: navcom --open 7ec78a59:533   · expand all: add --context
```

### Queries never break

Type anything. navcom never throws an FTS5 syntax error.

- **words**: every word must appear in the same turn, prefix-matched (`auth` finds `authentication`).
  If no turn contains all of them, navcom falls back to *any* word and tells you so.
- **`"exact phrase"`** (curly quotes work too).
- **`a OR b`**, `a or b`, `a | b`: either one.
- **`a, b, c`**: a comma or semicolon list means any of the groups.
- **`NOT x`**: exclude.
- **Punctuation is fine**: `don't`, `main()`, `v0.1.3`, `log-search`, `C++`, `~/dev/x`, `role:user`.
- **Shell quoting awkward?** Pipe the query in:
  ```bash
  navcom - <<'EOF'
  it's the "weird"; query, (really)
  EOF
  ```
- **A half-remembered `"exact phrase"`** that matches nothing is retried as loose words.
- `--query` and bare words combine, and a leading `search` / `find` is ignored.
- Only the turn text is matched. Words that appear in project paths don't produce false hits.

### Narrow it

```bash
navcom auth --claude              # or --codex --gemini --pi --omo --opencode --goose
navcom auth -p claude,pi          # several harnesses (aliases like omo-ai, pi-dev work)
navcom auth --here                # sessions whose working dir is the current directory
navcom auth --project syra        # sessions whose project path contains "syra"
navcom auth --days 7              # active in the last week (also --since 2026-09-01, --since 12h)
navcom auth --user                # only what you typed; --cmd for shell commands the agent ran
navcom auth -n 50                 # more hits (default 20)
navcom auth --newest              # order sessions by date instead of relevance
navcom auth --json                # machine-readable
```

`--compact` is the default and still accepted, so old scripts keep working.

By default a search leaves out the conversation navcom runs inside when the harness exposes its id
(`CLAUDE_CODE_SESSION_ID`, `CODEX_THREAD_ID`, …). Your own session is noise when you want prior
work. `--include-self` brings it back. `--this-session` searches only the current conversation,
which is useful after a context compaction. navcom's own past invocations never show up as hits.

### Read

```bash
navcom --open 7ec78a59            # whole session (turns truncated to 400 chars)
navcom --open 7ec78a59:533        # 3 turns either side of #533, full length
navcom --open 7ec78a59:520-560    # a range
navcom --latest                   # dump the most recent session
```

### Summaries

`--solo` produces one consolidated summary and `--summary` produces one per session. Both use the
first LLM CLI that works (`claude`, `gemini`, `codex`, then local `ollama`). `--ollama` or `--llmgemini`
picks a specific one.

## Safe to call from agents

- Parallel calls are fine. If another navcom is writing, a call waits at most ~3s. It then searches
  the index as it stands and prints a one-line note on stderr.
- In a read-only sandbox navcom searches the index without refreshing it.
- Unknown flags print a hint on stdout as well, so a `2>/dev/null` doesn't turn a typo into an empty
  result that looks like "nothing found".
- `--solo` and `--summary` have a hard time budget (`NAVCOM_SUMMARY_TIMEOUT`, default 150s). A
  summarizer that hangs is killed along with its child processes.

## The index

The index lives at `$NAVCOM_INDEX` (default `$CODEX_HOME/navcom-index.sqlite`) and updates itself on every
call. Only new or changed sessions are read, and a growing JSONL is read from where it left off.
A session stays searchable after its harness deletes the transcript. Claude Code, for example,
prunes old sessions. `navcom --where` shows the counts, and `navcom --reindex` rebuilds.
