# CLI concept candidates

Things a view wants that no CLI command can do today. Under the
[CLI-up rule](architecture.md#cli-concept-candidates) none of these may be
built as adapter or view glue. The owner decides, one line each: make it a CLI
concept (service + subcommand first, then a thin route), or drop it.

## From the place and conversation action matrix

| Wanted | For | Why no CLI does it today |
|---|---|---|
| A place's conversations as one list: name and size its collections, read them all at once, and resume or recap the newest in one step | galaxy, system, product, experiment, district, lab application, star | Nodes list `conversation_collections` as bare `projects:ID`s with no label or count, so *Conversations here* can name a collection (`effective_scope.label`) only after reading it, one at a time. A product such as syrab2bdev has 31 (one per worktree or focus folder), and the first by ID may hold 1 of its 1,400 conversations. `atlas explore projects:ID` reads one collection and `--within` scopes intersect, so no command lists a place's conversations across its collections. Every launch verb (`--resume`, `--recap`, `GET /api/recap`) needs a conversation REF, and a place reaches one only through `history conversations PLACE --at now --limit 1` (dated turns only) or one collection. A label and count per collection in the node, or a place-wide conversation listing with its newest REF, would serve all of it. |
| Start a fresh agent in a place's working directory | product, experiment, lab application | `FRESH_START`/`PASTE_START` and `resume_in_new_tab` exist, but only `--resume REF --with HARNESS` reaches them, which needs an indexed session. |
| Rename, annotate or favorite a conversation | conversation | One shared `navcom.annotate` now serves the TUI keys e/d/f and `POST /api/annotation`; no headless CLI flag reaches it (for example `navcom --annotate REF --name …`). |
| Suggest a title and note with the local model | conversation | `navcom_intelligence.suggest_for` builds the excerpt (turns 1–3 plus the last 10) and asks an already-running model; only `POST /api/suggest` calls it. |
| Browse retained files under an expert's scope | star | `navcom atlas files` rejects stars although star nodes carry `source_scopes`. |
| Inspect a starbase's storage location and availability | starbase | `navcom atlas inspect` has no starbase branch; the node carries only snapshot physical metadata. |
| Continue from a stored archive's carried session (recap or revive) | ship archive | Archives cannot board, and `--recap`/`--resume` work only on indexed sessions, so carried sessions can be read (`atlas context`) but not handed off. |
| Pause or cancel a running chart refresh from the CLI | galaxy | The route `POST /api/space/refresh/pause` is exempt by design (`view-state` in `ROUTES`): it sets the cancel event that `navcom_chart_refresh.drive()` honors in the adapter's thread. The CLI stops only with `--seconds` or Ctrl+C; a cancel file that `drive()` checks would be the CLI concept. |
| Sync the conversation index and keep going for a total budget during chart refresh | galaxy | The bridge calls `drive(automatic=True, sync_index=True)` for two minutes; `atlas refresh --space --harvest` exposes neither (a `--sync-index` / `--budget` pair would give it parity). |
| One sentence for a finished chart refresh | galaxy | `navcom_web.refresh_space` composes the bridge's sentence ("Chart intake 12/40 projects · more remain; progress saved · …") from the `drive()` result in the adapter, and `navcom atlas refresh` prints its own differently worded line from the same result. A `summary` field from `drive()` (or one shared formatter in the service) would make both say the same thing and keep that text out of layer 4. |
| Restore a dated system view strictly read-only | galaxy, system (dated) | `POST /api/history/system` with a saved cursor rewrites `results/<query_key>/<job>.json` when saved outcomes are missing or invalid; a `--reuse-only` mode on `navcom history system --cursor C` that fails instead of re-exploring would give the bridge's back, reload and boot paths a no-write contract. |

## Web routes with no CLI twin

`tests/test_architecture.py` tags each of these `cli-gap:` and fails if its row
disappears while the route still exists.

| Route | What it does | Why it has no twin |
|---|---|---|
| `GET /api/recent` | Library families, matches and research-family notes | Built from `navcom._recent_families`/`_recent_matches` with a 30-second memo, display project names and `navcom_research` profile notes in the adapter; only the interactive TUI Recents screen reaches the same family functions (without the notes). `--sessions` is a different flat list. A shared `recent_catalog()` would fit the bridge but not the TUI's in-place re-matching, so it was not forced. |
| `GET /api/status` | Dashboard snapshot | One shared `navcom.dashboard_snapshot()` serves the TUI dashboard and this route. `--where` computes different numbers; a `navcom --where --json` from `dashboard_snapshot()` would be the twin. |
| `GET /api/session` | Conversation detail: title precedence, 80-turn window, resume plan, last reply | Assembled in the adapter. The TUI reader uses a different window (around the focused turn) and title rule (no agent nickname), and the `preview` sentence is TUI-worded ("n chooses a fresh harness"), so a shared `session_detail()` would change TUI output. `--open REF:N` shows a different window. A twin would return structured plan fields instead of the preview sentence. |
| `POST /api/suggest` | Local-model title/note suggestion | See above: `navcom_intelligence.suggest_for` has no CLI path. |
| `POST /api/annotation` | Rename, note, favorite | See above: `navcom.annotate` has no headless CLI flag. |

## From the cockpit action rail

| Wanted | For | Why no CLI does it today |
|---|---|---|
| History of one harvested file | source file | `navcom history timeline PLACE --include P` needs a place and a repository-relative path. A harvested file knows only its source ID and source-relative path, and nothing maps one to the other: a source root can sit below its Git root, so the same text is a different `--include`. |
| Structured fields beside a node's commands | every place with harvested sources, collections or children | The view reads API parameters out of service argv: `--within` and `--path` values from `source_search[]` and `conversation_search[]`, and the grouping word after `list` in `list[]`. It never writes CLI syntax, but it does depend on CLI grammar, so a reordered or newly pinned argv would silently send other parameters. A field per command (for example `source_search: [{source_id, paths, argv}]`) would let the view stop parsing argv. |

## Command strings the services do not emit yet

The CLI already does each of these, but the result the view receives carries no command
string for it. The view never composes CLI syntax, so the rail shows these actions without a
CLI line. A service field per row would let the view show the twin, as `open_command`,
`next_command`, `land_command` and node `commands` already do.

| Action | Where the view gets its data | The CLI that does it | Field that would carry it |
|---|---|---|---|
| Recap a conversation | Discovery conversation nodes (search results, collections) and `/api/history/conversations` items | `navcom --recap REF` | `recap_command` (`/api/session/search` sessions already carry `recap`) |
| Resume the original in a tab | the same | `navcom --resume REF --tab` (the review is `--print`) | `resume_command` |
| Fresh agent with the recap | the same | `navcom --resume REF[:TURN] --with HARNESS --tab` | `revive_command` with a `<harness>` placeholder |
| Search inside one conversation | the same | `navcom WORDS --file REF` | `search_command` with a `<query>` placeholder |
| Open a dated conversation turn | `/api/history/conversations` items | `navcom --open REF:TURN` | `open_command` (Discovery nodes already carry it) |
| Find words in one harvested file | `/api/source` | `navcom sources search WORDS --within SOURCE --path FILE --mode text` | `search_command` with a `<query>` placeholder |
