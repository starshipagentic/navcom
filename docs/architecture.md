# NavCom architecture: built CLI-up

NavCom is one product in five layers. Each layer may use the layers below it,
never the ones above. The command line is the product; the browser is a view of
the same service results.

| Layer | What it is | Modules |
|---|---|---|
| 1. Core CLI | The fast headless tool people and LLMs use daily: search, `--open`, `--recap`, `--resume`, upkeep, the terminal UI | `navcom.py` |
| 2. Shared services | Data, evidence and bounded native work. Return plain data (including their own CLI commands), never print or style | `navcom_space`, `navcom_navigation`, `navcom_navigation_intent`, `navcom_sources` (service half: `sources_list`, `search`, `runtime`, `worker_argv`, `source_id`, `conversation_source`), `navcom_sources_worker`, `navcom_source_discovery`, `navcom_source_reader`, `navcom_history`, `navcom_system_history`, `navcom_historical_landing`, `navcom_historical_conversations`, `navcom_fleet`, `navcom_commission_archives`, `navcom_ship_inspection`, `navcom_ship_context`, `navcom_ship_boarding`, `navcom_stars`, `navcom_star_inspection`, `navcom_star_chat`, `navcom_relationships`, `navcom_place_files`, `navcom_place_overview`, `navcom_place_inspection`, `navcom_carried_search`, `navcom_chart_refresh`, `navcom_native_families`, `navcom_discovery`, `navcom_atlas`, `navcom_research`, `navcom_intelligence`, `navcom_voice` (service half: `status`, `transcribe`, `transcribe_request`) |
| 3. CLI subcommands | Argument parsing and terminal text for the services | `navcom_atlas_cli` (`navcom atlas …`, `navcom help …`, and every place/ship/star text renderer), `navcom_history_cli` (`navcom history …`), the CLI halves of `navcom_sources` (`parser`, `render`, `run`) and `navcom_voice` (`parser`, `run`) |
| 4. Web adapter | A thin HTTP adapter that calls the same service functions | `navcom_web.py` |
| 5. View | Presentation only | `navcom_web.html`, `navcom_space.js`, `navcom_space.css`, `navcom_atlas.js`, `navcom_atlas.css` (legacy Conversation Atlas), `navcom_voice.js`, `navcom_voice_worklet.js`, `assets/starship/*` |

## Allowed import directions

- `navcom.py` imports no `navcom_*` module at import time. Subcommands load
  their layer-3 module lazily inside `run()`. It may import `navcom_web` only
  lazily, inside the `--menu` entry.
- Services import other services (lazily when the work is optional) and receive
  the core module as an injected `api`. Isolated worker processes may import
  `navcom` by name (for example `navcom_chart_refresh._worker`).
- Services and CLI modules never import `navcom_web` and never read view files
  (`*.js`, `*.css`, `navcom_web.html`, `assets/starship`). Only the web
  adapter's static routes serve them.
- CLI modules import services, never the web adapter. Constant help text loads
  nothing beyond the standard library: `navcom --help` and `navcom help <subject>`
  do not import discovery, navigation or chart modules.
- Presentation never flows down: no UI parameters in the CLI, no color, sprite,
  camera or layout fields in service output, and no web-only business logic.

`tests/test_architecture.py` enforces these rules: an AST scan of every
`navcom_*.py` for `navcom_web` imports and view-file names, a check that
`navcom.py` imports no `navcom_*` module at import time, the route table below,
and a presentation-key walk. The walk fails on `color`, `colour`, `hue`,
`art_role`, `sprite`, `icon`, `camera`, `zoom`, `css`, `style` or `class` keys
anywhere in:

- the JSON every route in the table returns (`PROBES`: each route is called
  in-process on the BDD Orchard galaxy from `features/support/galaxy_world.py`,
  including the final state of the Upkeep and chart-refresh tasks);
- the `--json` output of every CLI twin that has one (`CLI_JSON`; the twins that
  print only text are listed in `TEXT_ONLY`);
- a Starforge-free fixture chart with every place kind, its fleet and Discovery
  views.

A route without a probe, or a twin with neither a `--json` command nor a
`TEXT_ONLY` reason, fails the test. `position` is chart data and stays allowed.
So does `query_plan.style` in evidence results, only with the values `literal`
or `question`: it is the retrieval style that `navcom_navigation.evidence` used,
and the CLI and the view both branch on it.

## Where each concern lives

| Concern | Owner | Notes |
|---|---|---|
| CLI syntax (`cli_command`, `next_command`, `open_command`, `land_command`, node `commands`) | The service that produced the result, or the CLI module | Chart nodes carry `commands`: exact argv for every read-only or review-first verb their kind accepts (`navcom_space.commands`); `navcom_navigation.view` pins them to the caches in use. Angle-bracket words (`<query>`, `<question>`, `<commit>`, `<YYYY-MM-DD>`) are for the caller to fill. Launch and refresh commands are never listed; they follow a printed review. |
| Terminal text | Layer 3 | `navcom_atlas_cli.render_*`, `navcom_history_cli.render`, `navcom_sources.render`. `--json` prints the service result unchanged. |
| Cache locations | `navcom_navigation.paths()` and `navcom_navigation.history_cache()` | One resolver for the chart (`NAVCOM_SPACE_CACHE`, else `<index>.space.json`), sources (`NAVCOM_SOURCES_CACHE`, else `navcom-sources` beside the index) and historical snapshots (`NAVCOM_HISTORY_CACHE`, else `navcom-history` beside the index). |
| Reading a published chart | `navcom_space.load_catalog()` | The one read path. It drops fields older charts saved for the view (`art_role`). |
| Place containment | `navcom_space.subtree()`, `navcom_space.in_scopes()` | Shared by navigation, dated landing and dated conversations. `navcom_history.py` keeps its own copy on purpose (see below). |
| Durable coordinates (`position`) | Chart data, owned by `navcom_space.position()` | Explicitly allowed in service output: stable places must survive refresh and be shared by the CLI and every view, and historical views pin current addresses. The seeding radii are frozen; changing them moves every saved address. |
| Colors, sprites, art, camera, zoom, layout projection, collision avoidance | View | Services never name a sprite. The view picks one from `kind` and `form` (an archive ship is `kind: ship, form: archive`; a lab application is `form: application`). `navcom_atlas.js` derives a stable tint per label. Visual spacing is tuned only in the view. |
| Bounded subprocesses | The service that runs them | `navcom_space.kill_group()` stops a still-running isolated worker group and tolerates the group exiting first. |
| Chart refresh driving | `navcom_chart_refresh.drive()` | One driver for repeated bounded passes, `stop_reason='time_budget'`, cancel and progress. The CLI runs one pass (`passes=1`); the bridge runs two minutes in one-minute slices. |
| Upkeep | `navcom.maintain()`, `navcom.claim_index_writer()` | `navcom --maintain`, the daily job, the TUI and the bridge run the same stages; `progress(message)` reports each one. The TUI and the bridge first claim the index writer so a busy index fails fast. |
| Launch pre-flight | `navcom.prepare_launch()` | Restore a transcript its harness deleted, then check the harness binary and the folder. `navcom --resume REF --tab`, the TUI keys `r`/`t`/`n` and `POST /api/launch` call it before `resume_in_new_tab`. |
| Annotations | `navcom.annotate()` | One merge rule (one line, at most 240 characters; a blank name or note restores the default) for the Recents keys `e`/`d`/`f` and `POST /api/annotation`. |
| Dashboard snapshot | `navcom.dashboard_snapshot()` | Read the saved snapshot while fresh, else compute and save it. The TUI passes its local setup as `prepare`; `GET /api/status` calls it plainly. |
| Local-model suggestion | `navcom_intelligence.suggest_for()` | Builds the excerpt (first three and last ten turns) and asks an already-running local model. |
| Source listing and search | `navcom_sources.sources_list()`, `navcom_sources.search()` | `navcom sources list/search` and `GET /api/sources`, `/api/sources/search`. Without a terminal, `search` captures the worker's own reason as its error. |

## Modules whose own bytes are cache keys

Some modules hash their own source into the identity of what they cache, so any
edit, even a pure refactor, invalidates that cache:

| Module | What an edit invalidates | Cost |
|---|---|---|
| `navcom_sources_worker.py` | `extractor_signature()`: every harvested source | Re-harvest of every source |
| `navcom_history.py` | Every historical Git snapshot (`prepare()` key) | Re-snapshot and re-harvest of every dated repository |
| `navcom_system_history.py` | New dated sessions only; saved cursors keep loading their `plan.json` | None for saved journeys |
| `navcom_relationships.py`, `navcom_native_families.py`, `navcom_stars.py` | Their query/metadata memos | One cache miss each |

Change the first two only for behavior, never for cleanup or shared-helper
refactors. That is why `navcom_history.py` keeps its own scope predicate and
worker argv instead of `in_scopes()` / `worker_argv()`.

## Every route has a CLI twin

Every `/api` route calls a named service function that a CLI command also
reaches. The adapter validates request fields, derives cache paths with
`navcom_navigation.paths()` / `history_cache()` (`navcom sources` routes resolve
the source cache, as the CLI does), and returns the service result.
`tests/test_architecture.py` keeps this table as `ROUTES`: for every twin it runs
the CLI command in a throwaway HOME and the route in-process, and both must call
the same function. A route the adapter handles without an entry fails that test.

| Route | Service function | CLI that reaches it |
|---|---|---|
| `GET /api/voice`, `POST /api/voice` | `navcom_voice.status`, `transcribe` (via `transcribe_request`) | `navcom voice status`, `navcom voice transcribe FILE` |
| `GET /api/space` | `navcom_navigation.view` → `navcom_space.view` | `navcom atlas list/explore/show/search … --space` |
| `GET /api/navigate` | `navcom_navigation.navigate` | `navcom atlas navigate WORDS` |
| `GET /api/space/inspect` | `navcom_navigation.inspect` | `navcom atlas inspect PLACE [--refresh] [--observe]` |
| `GET /api/space/context` | `navcom_navigation.context` | `navcom atlas context SHIP …` |
| `GET /api/space/files` | `navcom_place_files.files` | `navcom atlas files PLACE` |
| `GET /api/space/related` | `navcom_relationships.related` | `navcom atlas related PLACE` |
| `POST /api/space/ask`, `/api/space/board` | `navcom_navigation.interact` | `navcom atlas ask STAR "question"`, `navcom atlas board SHIP` |
| `POST /api/space/refresh` | `navcom_chart_refresh.drive` | `navcom atlas refresh --space --harvest` |
| `GET /api/atlas` | `navcom_discovery.Discovery.view` | `navcom atlas list/explore/search/show/tree` |
| `GET /api/sources` | `navcom_sources.sources_list` | `navcom sources list` |
| `GET /api/sources/search` | `navcom_sources.search` | `navcom sources search WORDS --within SOURCE [--path P]…` |
| `GET /api/source` | `navcom_source_reader.read_source` | `navcom sources read SOURCE PATH` |
| `GET /api/history` | `navcom_history.view(action='timeline')` | `navcom history timeline PLACE [--repo ROOT] [--include P]…` |
| `POST /api/history/explore` | `navcom_history.view(action='explore')` | `navcom history explore PLACE COMMIT [--repo ROOT]` |
| `POST /api/history/system` | `navcom_system_history.view` | `navcom history system PLACE --at DATE` |
| `POST /api/history/land` | `navcom_historical_landing.landing` | `navcom history land PLACE --cursor C --result-key K` |
| `GET /api/history/conversations` | `navcom_historical_conversations.view` | `navcom history conversations PLACE --at DATE` |
| `GET /api/recap` | `navcom.session_recap` | `navcom --recap REF [--max-chars N]` |
| `GET /api/session/search` | `navcom.search_hits(keys=[key])`, shaped by `navcom.search_json` (the same JSON) | `navcom WORDS --file REF --json` |
| `GET /api/harnesses` | `navcom.fresh_harnesses` | `navcom --resume REF --print` when its harness can't reopen it |
| `GET /api/plan` | `navcom.resume_plan`, or `revive_plan(focus=turn)` with a harness | `navcom --resume REF[:TURN] [--with HARNESS] --print` |
| `POST /api/launch` | the same plan, then `navcom.prepare_launch` and `resume_in_new_tab` | `navcom --resume REF[:TURN] [--with HARNESS] --tab` |
| `POST /api/upkeep` | `navcom.claim_index_writer`, `navcom.maintain` | `navcom --maintain` |

Consequential verbs (`--restore`, `--summary`, `sources discover/harvest`) have
no route: they follow a printed review in a terminal.

**Exempt by design** (owner-visible list; nothing else may join it without the
owner's agreement; the test tags them `view-state`):

- `GET /api/state`, `POST /api/state`: the browser's own view position.
- `GET /api/task`: progress of the adapter's background threads.
- `POST /api/space/refresh/pause`: sets the cancel event that `drive()` already
  honors; the CLI is bounded by `--seconds` and Ctrl+C.
- Static assets (`/navcom_*.js`, `/navcom_*.css`, `/assets/starship/*.png`) and `/`.

**No CLI twin yet** (the test tags them `cli-gap:` and requires their line in
[CLI concept candidates](cli-concept-candidates.md)): `GET /api/recent`,
`GET /api/status`, `GET /api/session`, `POST /api/suggest`, `POST /api/annotation`.
Their logic already sits in shared functions the TUI also uses where it has the
same feature (`dashboard_snapshot`, `annotate`; `suggest_for` for the excerpt);
the owner decides whether each becomes a headless CLI command.

## Adding a feature

1. Write the service function (layer 2). It returns plain data, including the
   exact `cli_command` that repeats it, and takes cache paths as arguments.
2. Add the CLI subcommand (layer 3) that calls it, with `--json` printing the
   result unchanged and a short text renderer.
3. Add a thin route in `navcom_web.py` that validates input, derives paths with
   `navcom_navigation.paths()` / `history_cache()`, and calls the same function.
4. Build the view (layer 5) from that result. Presentation stays in the view.
5. Test the service, the CLI, and API/CLI parity (the same JSON from both), and
   add the route to `ROUTES`, a request to `PROBES` and its `--json` command to
   `CLI_JSON` in `tests/test_architecture.py`.

## CLI concept candidates

If the view needs something that no CLI command can do, do not add glue to the
adapter or the view. Add one line to
[docs/cli-concept-candidates.md](cli-concept-candidates.md) saying what is wanted
and why no CLI does it today. The owner decides whether it becomes a CLI
concept (and then follows the steps above) or is dropped.
