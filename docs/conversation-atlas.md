# Conversation Atlas

`navcom --menu` keeps the Library and adds a **Conversation Atlas** tab.
The atlas covers the whole SQLite index, including archived and older sessions.
It does not scan the whole filesystem, start an LLM, or build embeddings.

Explore Topics → Projects → Conversations, or switch to Projects, Planet
 districts, Time, or Starship families. Click a conversation to read it and see
its neighborhood: verified parent/child relationships, shared words, and shared
topics are labeled separately. The existing resume plan resolves the launch
root; no map node is used as an executable command.

Search in ordinary language, such as “where were we fixing voice latency”.
Stopword filtering, small explicit synonym groups, rarity-weighted metadata
matches and SQLite FTS5 transcript ranking build a new map. This is explainable
concept retrieval, not an LLM's claim of understanding. Titles, folders and saved
notes are checked across the whole index; transcript retrieval is capped at
2,000 ranked turns. Counts are unique conversations per region; topic regions
can overlap. Topic labels are suggestions from metadata, not authoritative tags.

The map presents at most 12 neighbors at a time. More/Previous reach remaining
regions and sessions. Back, All regions, zoom, drag, keyboard-focusable nodes and
Browse as cards provide alternate ways through the same results. The Library
remains available with its own search and selection.

Voice uses the browser's on-device speech recognition only when both the API
and the language pack are already available. No pack is installed, no remote
recognition fallback is enabled. When unavailable, use the search box with
system dictation or type. System dictation's processing settings belong to the OS.
The implementation follows the [Web Speech on-device explainer](https://github.com/WebAudio/web-speech-api/blob/main/explainers/on-device-speech-recognition.md).

## Source ideas and optional Starship connection

Read-only reference inspection on 2026-10-14:

- Starship `bridge/build.py` and `bridge/admiral.js`: broad path districts,
  progressively revealed folders, source-to-ship relationships, explicit coverage.
- Starforge `src/starforge/fusion_planner.py`: metadata-based thematic categories.
- Starforge `src/starforge/concept_search.py`: meaningful words, multiple retrieval
  strategies, relevance ranking, related discoveries and provenance.

NavCom implements these ideas independently, with no imports from either project
and no changes to their checkouts. It optionally reads a bounded local snapshot
at `~/dev/starship/bridge/data.json`, or `$NAVCOM_STARSHIP_ROOT/bridge/data.json`.
Longest matching recorded source path selects a Starship family. The snapshot's
date is visible. Unmapped conversations remain browsable as Unlinked projects.
No snapshot is required, and this is not a live fleet-readiness check.

**Copy journey link** preserves the map's query, grouping, project and selected
conversation in a local URL. A future Starship launcher can start `navcom --menu
--no-browser`, read the loopback URL, and open it with `?view=atlas&q=...&lens=project`.
`group` and `project` select nested regions; `key` selects an indexed conversation.
Parameters must be URL-encoded. Links work while that server/port remains alive;
there is no installed URL handler or Starship-side launcher yet.

## Resource and lock behavior

One in-memory metadata catalog per server, invalidated by index or annotation
changes, with a maximum 120-second age. Browsing and classification are read-only;
no SQLite transaction is held between requests. The original transcript is
loaded only through the existing reader. Catalog construction reads native session headers for ancestry, never full
transcript bodies. Parent and child connections can cross project folders.

## Research discovery and navigation proof (2026-10-14)

Visible grouping buttons replace the hidden select. Cards show example titles,
project folders, main/child counts, and (for research) questions, approaches,
version clues and indexed excerpts. Cards are the default; the map remains optional.
Searches and drilled paths preserve Back history; browser Back and reloaded
journeys work too. Direct journey links can step up to their containing region.

Four source-grounded research profiles recognize indexed project identities,
not session IDs: EXP29, EXP30, EXP32 and Semantic Observatory. Other projects
remain available through Topics/Projects and All topic matches. No model is
needed for these profiles. Descriptions are curated and may need maintenance;
branch counts are bounded to 1,500 ranked user/assistant passages. An indexed
user-role passage may include a compacted summary, not literal human speech.

Actual Chrome testing with typed queries and clicks:

| Query | Path and verified conversation |
| --- | --- |
| my chatbot experiemnts | Four separate lab cards; EXP29 → v34 → main Claude 9694bd89, matching pipeline passage at turn 13252 |
| that exp 30 listener with the trained small model | EXP30 → V2/V2.1 → main Codex 605763e593de, blend request at turn 6329 |
| that other epx32 jev attempt | EXP32 → Reader replacement/hybrid → main Codex 7a57817bed77, reader evidence at turn 50 |
| sematic observtory | Observatory → SSDB → main Claude 4cea1172; separate EXP32 origin/handoff branch shows turn 9528 |

Opened reader and checked cwd/native resume command for each; no live harness
was launched by these discovery tests. Back twice from EXP32 reader returned to
branches and allowed trying the Observatory origin path. Browser Back and Back
after reload were exercised. Original Library shows research clues and an
Explore versions & approaches action. This verifies these concrete journeys,
not arbitrary semantic understanding or exhaustive version coverage.

## CLI-first discovery (2026-10-15)

`navcom atlas` now runs independently of the browser through the same discovery
service used by `/api/atlas`. Layered help is available through `navcom help`,
`navcom atlas help SUBJECT`, and each subcommand's `--help`. `navcom help all`
retains the comprehensive option manual. Existing search flags and resume paths
are unchanged; literal leading command words can be searched with `--query`.

Collections have stable IDs. `--within` filters the entire collection before
transcript ranking; grouping changes reorganize that scope. Compound IDs joined
with `+` intersect collections. Parent context may appear outside a search scope
when its child matches; the evidence ref identifies that child explicitly.
`--children` expands matching tasks. `show --start N` preserves an evidence turn.
Commands never launch a harness; printed open/resume commands use existing logic.

CLI JSON schema version 1 reports `effective_scope`, `nodes`, `total`, `offset`,
`limit`, `more`, `freshness`, and `cli_command`. Legacy `scope` remains the numeric
conversation count. All warnings/progress go to stderr. Empty results are valid
JSON with exit 0; invalid arguments return 2 and I/O failures return 1.

Suggested families now cover additional indexed projects. They require indexed
user/assistant passages containing at least two research vocabulary terms.
They are project-local suggestions, never automatic cross-project merges.
Extractive descriptions keep up to three supporting passages per conversation;
version/approach extraction retains at most 80 distinct branch names per
conversation. These mentions do not prove a version was built, deployed or
succeeded. Defined family descriptions remain explicitly distinguished.

Evidence is stored atomically with owner-only permissions in `INDEX.atlas.json`.
`atlas refresh` streams only changed indexed user/assistant turns, with no model
or raw-log scan and no SQLite writer. Upkeep also refreshes it. Browsing uses
cached evidence; missing or changed evidence is labeled instead of silently
triggering expensive work. Snapshot signature changes during refresh may leave
it stale; another refresh reconciles those changes. Unknown project identities
are not manufactured into suggested research families.

The web checkbox defaults to local search inside a collection. New phrases
replace the prior phrase; they do not narrow to the current page. Unchecking
searches the archive while retaining visible filters. Copy-view commands include
scope, query, filters and pagination. Full paths wrap in cards, Library rows,
reader metadata and breadcrumbs, with copy actions. Back and reload preserve
scope and checkbox state. Suggested similarities remain separate from tree edges.

Validation for the CLI-first update: 149 Python tests and 130 BDD scenarios
passed. Fixture checks cover unfamiliar suggested families, scoped ranking,
compound scopes, CLI/web equality, copied-command replay, missing parents,
metadata refresh, invalid scopes and a concurrent SQLite writer. Live Chrome
journeys again reached EXP29 v34 (turn 13252), EXP30 V2 (6329), EXP32 reader
(50), and Observatory SSDB (46), with their native resume commands inspected
without launching harnesses. A scoped EXP29 search regrouped into project
folders and produced its equivalent CLI command; nested scope survived reload.

## 0.10.0 help and missing-title behavior

`navcom --help` is the overview. `navcom help all` includes the complete classic
option manual and Atlas subcommand reference; `navcom help browse` explains web
scope and terminal controls. `navcom atlas help search` describes Atlas search,
while `navcom help search` describes classic full-text search.

Untitled/unknown conversation nodes derive a temporary display label from their
indexed evidence, preserving short file-path clues. This is procedural text
formatting, with no model call or saved rename. Map tooltips include the passage
and nodes show short references to distinguish similar results.
