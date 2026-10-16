# Dated conversation evidence at current project addresses

`navcom_historical_conversations.view()` reads the existing SQLite index without ingesting logs, writing temporary tables, running a model, or modifying the caller's connection. File-backed indexes are reopened in read-only mode for a bounded consistent read transaction; writer-lock contention does not require an index refresh.

```python
view(api, conn, *, within="", as_of, space_cache, query="", limit=20,
     max_turns=100000, seconds=5)
```

`within` selects one saved current place by ID or unique exact name. Its descendant project collections determine scope. These are **current navigation addresses**, not proof that the conversations belonged to the same organization, product, district files, or Git commit at the requested time. Unsupported collections and missing indexed project metadata are reported rather than widened to a global search. Encoded project paths that require guessing from the live filesystem remain unresolved.

`as_of` accepts a date (midnight UTC) or ISO timestamp with explicit UTC offset, matching system history. Each eligible user/assistant turn needs its own nonempty `session_fts.ts` containing an ISO timestamp with an explicit offset. Missing, date-only, offset-free, numeric, malformed and future timestamps are excluded. Recorded timestamps do not prove wall-clock accuracy. No file mtime, filename date, session title, current summary, annotation or neighboring event supplies a missing date.

The bounded timestamp scan runs before ranking or result limits. Text matching reuses NavCom's query cooker and SQLite FTS5 text-only query/rank; snippets reuse its snippet handling. Current project paths and titles do not cause text matches. One result per conversation uses its best matching eligible turn; without a query, it uses the latest eligible turn. The label and excerpt are drawn only from that dated passage. A future turn cannot consume the result limit, supply a title, or broaden the selected query.

Output has `selected_place` (explicit current label), UTC `as_of`, `query`, `cooked_query`, `catalog_published`, `conversation_basis`, the attribution/timestamp/ancestry/search policies, `conversations`/`nodes`, `coverage`, and `gaps`. Each conversation contains:

- `id`, `key`, `ref`, `provider`, and separate `current_project` navigation metadata.
- `label`, `label_basis`, `excerpt`, `start` (exact indexed turn), `role`, `recorded_at`, `timestamp_raw`, and matching-turn count.
- `parent_ref`, `parent`, `children`, `parent_status`, and `ancestry_basis`. Indexed `session_ancestry(file,parent_id,provider)` preserves recorded links; Claude's indexed subagent path can also establish a parent reference. Missing ancestry is unknown, not an assumed root. These relationships are not independently dated, and a parent excluded by query/cutoff/limit is not shown with a current title.

The scan covers at most 100,000 user/assistant turns by default (configurable up to 1,000,000), 50,000 session metadata rows, five seconds (up to thirty), and 200 returned conversations. `coverage` separately records metadata/scan/search completion, scoped sessions, unresolved or missing collections, inspected/dated/undated/invalid/future/eligible/matching turns, per-provider date counts, matched conversations, and truncation. Partial counts never claim archive-wide completeness. Raising a budget is explicit; no background full reindex happens from this reader.

On the existing October 16 index, the initial read-only audit found all 693,840 indexed turns had empty `ts`: `index_log` had inserted an empty string. The reader therefore correctly returned no dated evidence. Native timestamp preservation in normal ingestion is required for useful historical results; old undated rows cannot be safely repaired by changing their mtime. This is an ingestion gap, not a reason to invent dated text.

## Native ingestion and CLI proof

```sh
navcom history conversations Aurora --at 2025-05-01 --query login
navcom history conversations --help
```

The command opens only an existing index, renders dated excerpts and timestamp coverage, and prints a shell-quoted replay command retaining the exact place, cutoff, query, index and budgets. It does not initiate indexing. Full current-conversation readers and resume actions are separate operations: their contents must not be embedded as historical evidence without the same individual-turn cutoff.

The normal parser/index pipeline now preserves explicit native event timestamps for Codex and Claude JSONL, pi/omo JSONL (including their native message timestamp in milliseconds), and Gemini JSON/JSONL. `IndexedTurn` remains an ordinary two-item tuple for existing consumers while carrying a timestamp attribute through cleaning. Invalid or offset-free ISO values remain undated. Codex/Claude recorded ancestry and available native project addresses are persisted during ingestion. Other harnesses remain searchable but undated until their native timestamp mappings are implemented and tested.

Known Gemini JSONL content patches, changed replacements and changed checkpoint records lose historical eligibility: their original message date does not prove when revised words appeared. They remain available to normal current search. The index holds recorded current log contents; native timestamps still do not authenticate clocks, prove that source logs were never edited, or establish commit ownership.

Parser version 4 uses the existing incremental append and bounded stale-parser upgrade mechanism. Normal new/changed sessions preserve dates, while old parses are re-read within the existing one-second upgrade budget; oversized sessions can remain undated until a later bounded opportunity or an explicit reindex. The reader itself never performs that work. No direct timestamp backfill or full live reindex was used for this proof.

`tests/test_index_timestamps.py` and `tests/test_historical_conversations.py` prove native ingestion → SQLite → CLI output → printed replay. The fixtures cover exact cutoff inclusion, timezone normalization, future first prompts/titles, missing timestamps, native parent/child links, incremental append, unchanged old-parser upgrade, Gemini edited records, long-turn search snippets, read-only access under a writer lock, and one-generation catalog scope.

The persistent browser fixture is `/tmp/navcom-dated-conversation-flight/fixture.json`. It uses normal native ingestion for a dated parent, child, and undated conversation at the existing Quartz project address. The April CLI output excludes the future first prompt and Cognito turn; September returns the later Cognito passage. `old.json` and `new.json` contain the actual command results.

A separate bounded real-data proof used `index_logs` to ingest one existing Claude and one existing Codex Syra session into `/tmp/navcom-dated-real-proof/dated-index.sqlite`. All 38 extracted turns retained native timestamps; the historical service inspected 11 user/assistant turns and returned two dated conversations. The original live index was opened read-only and was not modified. This proves these two native records, not complete date coverage across the archive.
