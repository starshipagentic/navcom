# navcom 0.2.0: LLMs stop fighting the search box, and pi/omo/opencode/goose are in

**Pain:** LLM agents call navcom constantly. In 1,093 real invocations mined from Codex, Claude and
OMO logs, 89 crashed on punctuation (`cerbos-wave-2`, `10.10.1.223`, `don't`, `PR #76`), 109 returned
"No hits." on long keyword lists, 17 died on `database is locked`, and calls ran 30–211s because
every search re-parsed the caller's own 1–4GB Codex log. `--file` and `--latest` were silently
ignored, output carried ANSI codes into pipes, and agents stripped punctuation by hand, avoided
parallel calls, and ended up grepping the raw JSONL.

## Summary

- **Mined** every navcom call in `~/.claude/projects`, `~/.codex/sessions`, `~/.omo`, `~/.gemini`
  and opencode.db with a subagent, then replayed all 918 distinct queries through the 0.1.3, HEAD
  and new cookers.
- **Rewrote the query cooker** (`_split_query` → `_assemble`):
  - It validates operator and paren placement and adds the explicit `AND` that FTS5 needs next to parens.
  - It quotes punctuation tokens and drops punctuation-only ones.
  - Comma and semicolon lists become OR groups.
  - Fallback chain: raw (`--no-prefix`) → cooked → all-literal. Then, if zero hits: a quoted phrase
    retries as loose words, and multiple words retry as ANY word.
- **Compact output is the default**, grouped by session with date, harness, decoded project path
  and a short **ref**. `--compact` is a no-op for compatibility. `--context` gives the old windowed view.
- **New commands:**
  - `--open REF[:N|A-B]` for drill-down.
  - Filters: `--here`, `--project`, `--days`, `--since`, `--until`, `--user`, `--cmd`, `--role`,
    `--this-session`.
  - Output: `--json`, `--newest`.
  - Index: `--where`, `--reindex`.
  - `-V`, plus aliases LLMs reach for (`-q`, `--search`, `-n`, `--max-results`, `-p`/`--provider`).
- **New harnesses:** pi, omo, opencode (SQLite plus legacy JSON storage) and goose (sessions.db
  plus legacy JSONL).
- **Index hygiene:**
  - `turn_loc` B-tree lookup table: `--context` went from 5s to 0.3s.
  - Incremental JSONL append from the stored offset.
  - WAL mode, a 3s busy timeout, and falling back to the stale index when locked or read-only.
  - Old rows get re-parsed gradually within a 1s budget per call.
- **Result quality:**
  - MATCH is scoped to `text :` only, so paths no longer inflate hits.
  - The calling session is excluded by default (`CLAUDE_CODE_SESSION_ID`, `CODEX_THREAD_ID`).
  - navcom's own past commands and duplicate turns are filtered out.
  - ANSI codes are stripped at index and display time.
- **Summaries:** `run_bounded` sets a process group, a per-engine cap of 90s and a total cap of 150s,
  and kills the group on timeout. Ollama now has a timeout too.
- **Skill doc** rewritten and installed to `~/.codex/skills`, `~/.claude/skills` and `~/.agents/skills`.

## Decisions

- **Compact by default. Kept `--compact` as a no-op instead of removing it:** 591 historical calls pass it.
- **Kept the per-turn bm25 ranking, grouped by session** (sessions ordered by their best hit). Also
  added `--newest` rather than switching to date order: the DNA is "search engine".
- **`--limit` is now a total, not per provider.** With 7 harnesses, per-provider meant up to 140 hits.
- **Comma lists mean OR.** LLMs write `cognito, cerbos, terraform` meaning "any". BM25 still ranks
  all-term matches first. A comma without a following space stays a literal (`a,b`).
- **Lowercase `or` is an operator, lowercase `not` is not** ("do not use" is a phrase). Lowercase
  `and` is dropped, since AND is implicit.
- **Strict argparse, with the error echoed to stdout when captured.** Rejected lenient
  unknown-flag skipping: a following value would silently become a query word.
- **No forced reindex on upgrade.** A fresh index takes 77s (14GB of Codex logs), which would time
  out agent shells. Chose a progressive re-parse: at most 1s per call, newest first, size-aware at
  40MB/s. Files over 200MB stay incremental.
- **Stale sessions stay searchable.** 2,802 indexed sessions are gone from disk because Claude prunes
  them. We don't filter to on-disk logs, so the index is the archive.
- **UUIDv7 short refs use the random tail** (`[-12:]`). The head is a timestamp and collided for
  pi/omo sessions started the same minute.
- **Gemini project resolution:** `.project_root` if present, then the `projects.json` name map, then
  sha256 of known cwds. The old hash-named dirs are sha256(project path).
- **Deferred: omp (oh-my-pi) `~/.omp/agent/agent.db` and `~/.gjc`.** Not installed here and the
  formats are unverified. Aider writes a per-project `.aider.chat.history.md`, and finding those needs
  a filesystem crawl, which is against the DNA. Continue has only 4 sessions locally, so it's low value.
- **No license added to pyproject.** The repo has none, and that's the owner's call.

## Gritty snippets

```bash
# the replay harness that proves the fixes on YOUR real history (918 queries, ~45s)
SP=/private/tmp/claude-501/-Users-t-dev-navcom/5c255b74-767c-43f4-9161-0222cc866719/scratchpad
sqlite3 ~/.codex/navcom-index.sqlite ".backup $SP/idx.sqlite"   # never test on the live index
NAVCOM_INDEX=$SP/idx.sqlite python3 navcom.py drizzle migration

# tests (hermetic fake HOME with all 7 harnesses: features/support/fake_home.py)
uv venv -q .venv --python 3.13 && uv pip install -q --python .venv/bin/python behave pytest
.venv/bin/behave --format progress3        # 59 scenarios
.venv/bin/python -m pytest tests -q        # 44 tests incl. 15k-query fuzz

# publish: the navcom-scoped token is starforge's ~/.pypi-keys.json ["pypi"] (prefix pypi-AgEIcHl…),
# NOT ~/.pypirc (that token → 403 Forbidden on navcom)
uv build
TWINE_USERNAME=__token__ TWINE_PASSWORD=$(python3 -c "import json,os;print(json.load(open(os.path.expanduser('~/.pypi-keys.json')))['pypi'])") \
  uvx twine upload --non-interactive --config-file /dev/null dist/navcom-0.2.0*
pipx install --force navcom==0.2.0

# push: repo is owned by starshipagentic; the active gh account is tsomerville2 (403). Don't switch accounts,
# pin a token for this push only (found via: navcom "gh auth token --user starshipagentic" --cmd)
TOK=$(gh auth token --user starshipagentic)
git -c credential.helper= -c "http.https://github.com/.extraheader=AUTHORIZATION: basic $(printf 'x-access-token:%s' "$TOK" | base64)" push origin main
```

FTS5 gotchas learned:

- `x (y)` is a syntax error: FTS5 needs an explicit `x AND (y)`.
- Raw `a-b` is parsed as a column filter (`no such column: b`).
- `snippet()` caps at 64 tokens.
- A column filter over a whole expression works: `text : (a* OR "b c"*)`.

## Files changed

- `navcom.py`: **core rewrite**. Provider registry, the 7 harness parsers, the query cooker,
  index v2 (`turn_loc`, `file_meta`, `file_parser`), the compact/context/open/json renderers, the new
  CLI and bounded summarizers. The embedded `log_clean_quick` and `log_search_fts5` are untouched.
- `pyproject.toml`: **0.2.0 packaging**. readme, keywords, URLs, sdist includes.
- `README.md`: **new**. User docs, harness table, query rules, agent-safety notes.
- `skills/navcom-session-recall/SKILL.md`: **agent skill**. Two-step recipe (find, then `--open`) and
  the "never strip punctuation" rule.
- `features/*.feature`, `features/steps/navcom_steps.py`, `features/environment.py`: **BDD**.
  Search, query forgiveness, reading and narrowing.
- `features/support/fake_home.py`: **fixture home**. Realistic sessions for claude, codex, gemini,
  pi, omo, opencode (db + legacy) and goose (db + legacy).
- `tests/test_query_cooker.py`, `tests/test_harness_parsers.py`, `tests/conftest.py`: **unit tests**
  and the fuzz.
- `diary/`: this entry.
- Outside the repo: `~/.codex/skills/navcom-session-recall/SKILL.md` (rewritten; the backup is in the
  scratchpad), and new `~/.claude/skills/navcom-session-recall/` and `~/.agents/skills/navcom-session-recall/`.

## Appendix

- **Harness storage (verified on this Mac):**
  - pi: `~/.pi/agent/sessions/--<cwd>--/<iso>_<uuid7>.jsonl`. Env vars `PI_CODING_AGENT_DIR` and
    `PI_CODING_AGENT_SESSION_DIR`.
  - omo: `~/.omo/agent/sessions`. Env vars `OMO_CODING_AGENT_DIR` and `OMO_CODING_AGENT_SESSION_DIR`.
    Records are `{"type":"message","message":{role: user|assistant|toolResult|bashExecution|system}}`,
    and assistant content items are `text|thinking|toolCall{name:"bash",arguments:{command}}`.
  - opencode: `~/.local/share/opencode/opencode.db`, with tables `session(directory,title,time_updated)`,
    `message(data.role)` and `part(data.type text|tool|reasoning; tool.state.input.command)`. Legacy
    layout: `storage/message/<ses>/*.json`, `storage/part/<msg>/*.json`, `storage/session/*/<ses>.json`.
  - goose (from block/goose `session_manager.rs` and `goose-provider-types/src/conversation/message.rs`):
    `$XDG_DATA_HOME/goose/sessions/sessions.db`, or `$GOOSE_PATH_ROOT/data/sessions`. Tables:
    `sessions(id,name,description,working_dir,updated_at)` and
    `messages(session_id,role,content_json,created_timestamp)`. The content is tagged
    camelCase: `text`, and `toolRequest{toolCall{status,value{name,arguments}}}`. Legacy format:
    `*.jsonl`, with metadata on the first line.
  - Gemini: `~/.gemini/projects.json {path: name}`. Hash dirs are sha256(path). Newer content is a
    list of `{text}` parts, which 0.1.3 indexed as `{'text': ...}` repr garbage.
  - Claude: `isMeta:true` lines are hook injections, which are now skipped. Slash commands are stored
    as `<command-name>` and `<command-args>`, and are now kept as `/goal …`.
- **Session env:**
  - Claude Code exports `CLAUDECODE=1`, `CLAUDE_CODE_ENTRYPOINT=cli` and `CLAUDE_CODE_SESSION_ID=<uuid>`.
  - Codex 0.159.2 exposes `CODEX_THREAD_ID`: the binary is
    `~/.codex/packages/standalone/releases/0.159.2-aarch64-apple-darwin/bin/codex`, and the rollout
    filename ends in the same uuid.
- **Index:** `~/.codex/navcom-index.sqlite` was 670MB before the upgrade. It holds about 5,200
  sessions and 204k turns; 2,802 of those sessions are no longer on disk. `PRAGMA user_version=2`,
  `PARSER_VERSION=2`.
- **Timings on this Mac** (M-series, 1GB Claude + 14GB Codex):
  - Warm search: 0.3s.
  - A fresh Claude-only index: 9s; a fresh index of everything: 77s.
  - Under a held write lock: ≤3.8s.
- **Released:** https://pypi.org/project/navcom/0.2.0/. Pushed as commits `9761126`, `a2a9a4f`
  and `7f75022` on starshipagentic/navcom main. pipx now runs 0.2.0 from
  `/Users/t/.local/pipx/venvs/navcom`.
- **Replay results:** 0/918 crash (0.1.3: 89); 911/918 return hits; 140/143 historical "No hits."
  now return hits.
- **Mining artifacts** (scratchpad): `navcom_calls.jsonl` (1,237 records), `extract_navcom.py`,
  `replay.py`, `replay.jsonl`, `report_data.txt`, `narration.txt`.

**tags:** navcom, fts5, sqlite, query-cooker, llm-ux, claude-code, codex, gemini-cli, pi, omo,
opencode, goose, pypi, bdd, behave, session-recall. This is the release where navcom stopped making
LLMs retry, and learned four more harnesses.
