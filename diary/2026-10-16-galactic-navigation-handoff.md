# October 16, 2026 — Galactic navigation handoff

This is the resume point for another LLM. The owner asked for a diary containing
the entire concept, decisions, what we learned about Starforge and Starship,
remaining Niklaus Wirth steps, and the current official plan. This entry records
the stop point; it does not authorize a new release or declare the goal complete.

**Read this first, then follow its links.** Earlier diaries are dated evidence,
not cumulative assertions that every later build is healthy. In particular, an
installed browser-disconnect crash was found after the last passing test gates.
Its repair was interrupted before any edit. The current user task is this
handoff, not another implementation pass.

## Immediate state

- Repository: `/Users/t/dev/navcom`, branch `main`, HEAD `0188ad1` at handoff.
  There are about 150 modified/untracked paths. Preserve them; do not reset,
  clean, stash wholesale, or assume they all belong to one new change.
- The official plan is [Galactic implementation](../docs/galactic-implementation-plan.md).
  The authoritative meaning is [Spatial navigation vision](../docs/spatial-navigation-vision.md).
  This diary supersedes older runtime and remaining-work summaries where stated.
- The original Wirth ladder is [Small local-harvest proof](../LABS/spatial-discovery/HARVEST-PLAN.md),
  with P0 through P3. There is **not** an existing full-galaxy P0–Pn ladder to
  pretend has been completed. The broader official plan has eight workstreams.
- The latest locally installed package is NavCom `0.10.0`, built from this dirty
  checkout. No PyPI publication, commit, push, deployment, or other-repository
  code change occurred in this galactic implementation continuation.
- The default bridge at `http://127.0.0.1:51605/` is currently **down**. It exited
  141 during a historical reload. Both preview bridges at ports 62811 and 62814
  answered HTTP 200 at handoff. The user currently has the 62811 bridge visible.
  Those previews use different caches from the default bridge.
- Dated product/district landing is installed and works through source reading.
  Its final reload/Back browser acceptance was interrupted by the server crash.
- Live microphone transcription is **not proved**. The user approved one test
  and reported allowing access, but the last observable panel still awaited
  permission and no transcript was received. The temporary test tab is gone.
- The one approved expert question **was sent exactly once**. Its terminal
  capture was interrupted, but the final answer was recovered from the native
  Hermes session. Do not resend it because a stale marker says `running`.
- Real captain boarding/takeover remains unproved; the recorded working fleet is
  remote, and local archives are not working captains.
- The broader goal remains active and incomplete. Do not mark it complete merely
  because a map renders or because this diary is finished.

## The entire concept, in the owner's terms

The problem is keeping a coherent working life across a W-2 job, paid clients,
entrepreneurial ventures, product suites, versions, experiments, and time. The
owner should return to a place and recover their train of thought without
reconstructing it from tabs. Astronomy serves this purpose; literal astronomy
must not dictate false relationships.

**Galaxy:** the owner's overall world of work, spanning machines and storage.
Visiting David's companies, projects, and commitments would mean visiting his
galaxy. A galaxy is not one Macintosh.

**Solar system:** a substantial commitment or suite of products. Syra, the
owner's W-2 work, is one system. Paid clients and entrepreneurial undertakings
can have systems of their own. Folder grouping is evidence, not proof of a
person's employment or of authoritative business ownership.

**Planet:** a product. B2B, the enterprise mobile application, and CarePlus must
be distinguishable destinations within Syra. A repository may contain several
products; a product may span repositories and physical copies. Do not equate one
repository or one conversation with one product by definition.

**Time:** products and systems evolve. The owner wants to see the ensemble at a
chosen time. Major product generations may be separate planets or successive
states; that distinction is still open. A version-family suggestion does not
establish historical replacement. Current as-of implementation reconstructs
committed code at saved navigation addresses, not past organizational ownership
or deployment state.

**Moon:** a lab experiment associated with a product or research undertaking.
Versions contribute to experiment/history navigation, but not every numbered
version becomes a moon. Parent/child chats are conversation ancestry, not
planet/moon relationships. One backend refinement is already implemented:
runnable applications strictly inside an established experiment moon, in the
same canonical Git repository, become `kind=district, form=application` beneath
that moon. Their IDs, scopes, and positions remain stable. Independent nested
Git repositories are exempt; they are not demoted just because their folders
sit inside a lab. See `_place_lab_applications` in `navcom_space.py` and
`tests/test_lab_applications.py`. The laboratory-building artwork and vocabulary
remain open; do not undo this existing containment rule while refining them.

**Cities, districts, facilities:** meaningful areas of a product's code and
thinking: authentication/Cognito, RBAC, Cerbos, Docebo, charting, infrastructure,
and strategies. The owner lands on a planet, enters an area, searches its code,
decisions, alternatives, and conversations. Exact city-versus-district boundaries
remain open. Native file groups are useful suggested districts, not certified
product boundaries.

**Star:** a significant living source of expertise, possibly an agent, maintained
codebase, repository, website, and callable interfaces on a physical or virtual
machine. It can accumulate expertise and serve multiple systems or galaxies.
Stars are their own kind of destination. Do not invent a star for every work
system, or make the primary Mac the sun just to satisfy the metaphor. Starforge
technology can improve any work; its use is not limited to public stars.

**Starbase:** a real navigable gathering, docking, storage, or resource location.
An attached SSD can embody a named base. Show its real host and paths, with
availability separate from conceptual location. Not every mounted directory is
automatically a base.

**Starship:** a coherent living working environment carrying an undertaking
forward: documented code, dependencies/configuration, securely carried access
material, NavCom conversations, decisions, history, a mission, and recoverable
working state. A CMS ACCESS ship may focus on one part of B2B rather than all of
Syra. It has a conceptual location, a point of view, and a state from which the
captain can answer and advance the work, even when physically hosted elsewhere.
An ordinary chat, a transcript count, a seal, or a blank resumed terminal is not
that complete ship. Boarding must restore actual context and prove arrival.
Never put credentials in chart records, screenshots, links, or this diary.

**Physical plane:** machines, disks, cloud infrastructure and running services
hold the work together, like the owner's “dark matter” analogy. Their location
and selected copy must be inspectable, but they must not determine conceptual
geography. A Mac is not automatically a planet, moon, or star.

**Conversation material:** first-class evidence at places and aboard ships.
Keep parent/child relationships and harness launch routing intact. Its final
visual symbolism remains open. The owner rejected both chat-equals-moon and
the overly restrictive claim that conversations are merely logs.

**Experience:** a beautiful, usable bridge with Starship artwork, smooth flight,
readable names and full paths, deliberate time changes, typed/spoken navigation,
scope controls, and reliable Back/Forward. Search should illuminate relevant
places without scrambling the map. The underlying CLI must provide the same
organization and evidence without requiring the visual UI or an LLM.

Earlier “NATO/NVO/NAO” speech errors refer to NavCom here; do not invent separate
products from them.

## Decisions to preserve

### Locked by the owner

- CLI/shared services first; prove the terminal journey before wiring new UI.
  Layered help must be understandable to humans and agents. No MCP rewrite is
  required merely to expose these capabilities.
- Reuse Starforge harvest and both existing search paths. Search Starforge's
  capabilities before claiming it needs a new algorithm. Prove uncertain work
  in a bounded lab with unfamiliar controls.
- Tools discover, harvest, refresh, and publish. Do not hand-edit/synchronize
  catalogs or curate a Syra/EXP32-only universe to make a demo pass.
- Keep Starship and NavCom aligned. Starship owns commissioning, secure context,
  restoration and captain recovery; NavCom navigates and delegates those actions.
- Ordinary browsing must be cached and useful without inference, model downloads,
  or starting large models. Optional intelligence may use already-running local
  CapCom-compatible routes/Bertha, but must not become a dependency or exhaust RAM.
- Show immediate progress and an explanation for bounded stops/locks. Preserve
  the last complete readable view when refresh is busy or fails.
- Parent conversations are the default; children are visibly discoverable.
  Original resume/new tab/fresh harness use the same ancestry-aware planning.
- Preserve location, query, scope, selection, camera, date, and return path.
  Unknown or ambiguous evidence must remain visible rather than be invented.

### Implemented choices, with their limits

- General procedural discovery uses indexed roots, native Git identity,
  declarations/manifests, native Starforge groups and actual fleet/provider
  records. Stable retained IDs/coordinates survive ordinary refresh/search.
- The older Conversation Atlas still has four curated research profiles in
  `navcom_research.py`. That legacy facility is not proof of universal geography.
  Do not add a new client-specific profile as a substitute for the galactic rules.
- Source content and extractor identities invalidate immutable harvests. Query
  caches are separate. Exact source/path scope applies to both search paths.
- Natural navigation is procedural. Named-place resolution happens before
  search; ambiguity or a missing place does not silently become global search.
- Current code reads use retained artifact pins. Dated reads use exact Git
  receipt/commit/tree pins. Unrelated publication changes may retain unchanged
  artifact access; changed selected content must fail explicitly.
- System history saves repository heads, cutoff, address scope and positions.
  Query-only changes preserve that session; explicit date changes start another.
  Larger retries create a separate session with the same original pins.
- Native dated groups are suggestions within exact retained product files.
  Dated conversation passages are separate evidence, not attributed to a commit.
- Native expert/captain preparations are reviewable data. Explicit action must
  revalidate the identity/route. A review token is not human authorization.

### Still open; do not silently lock these

- Authoritative product identity across arbitrary moves, reorganizations and
  multiple repositories; suggestions versus owner-confirmed corrections.
- Product generation/replacement semantics and historical organizational changes.
- Exact city/district/facility and conversation visual representations.
- General remote ingestion and remote captain access; broader expertise providers.
- Cross-owner galaxy travel and sharing/access contracts.
- Cache generation pruning/retention policy and broader-corpus performance limits.
- Optional model enrichment beyond current procedural behavior. No new model is
  necessary for the remaining disconnect repair or acceptance tests.

## Wirth ladder: what remains and what was superseded

The [original P0–P3 plan](../LABS/spatial-discovery/HARVEST-PLAN.md) is a bounded
ingestion experiment. Its “production integration deferred” wording is historical,
superseded by the later CLI implementation. Preserve its task/data separation.

**P0 — Outcome.** Current selected local material becomes discoverable without
reanalyzing unchanged material while browsing. Proven in the lab and public CLI
for cold harvest, unchanged refresh, changed/deleted material, and scoped reads.
This does not promise all-machine coverage or correct cosmic ownership.

**P1 — Boundary and parts.** Discovery selects sources and conversation scope;
harvest validates/analyzes changes; readers use the last complete published view.
Implemented. Production adds resumable bounded intake. A completed queue entry
can be unavailable/skipped; queue completion is not full source coverage.

**P2 — Data and guards.** Source selections, content/extractor receipts, and an
atomic published view have distinct writers. Failed/busy refresh keeps readable
prior data. Tests cover content changes with unchanged mtimes, deletion, changed
extractors, unavailable roots, scope escape, writer contention, and publication
failure. Production merge-refresh retains other registered sources. Do not
interpret a missing/unavailable source as an intentional removal.

**P3 — Flows.** Discover → refresh changed material → publish → scoped search →
original evidence/context. Proven through the public CLI before UI. The broader
source/document search investigation closed the gem-only omission. Remote
ingestion, identity across arbitrary moves, and cleanup remain open.

For remaining work, refine one owner-visible flow at a time, with its data and
failure path together. Keep technology in the command/module notes below, not
inside a new conceptual ladder. Do not invent P4–Pn completion statuses.

The immediate next refinement is:

1. When a visitor leaves during a response, discard that response without ending
   the navigation service.
2. Keep the saved journey and evidence identity intact.
3. Allow the visitor to reconnect and continue from the same saved destination.
4. Prove the same service survives, then repeat the historical return journey.

Story: Travis reloads while flying and still has a working bridge.
Outcome: a disconnected response cannot terminate the service or silently change
the saved historical view.
Proof: a deliberately disconnected response is followed by a successful request
to the same process, then real-browser reload and Back retain date/scope/query.

After that, refine the live speech and captain-arrival flows at the same level of
care. The expert-answer flow has now reached a native final answer, with the
limitations recorded below. Do not solve open ownership semantics by adding
implementation detail to the ladder.

## Official plan: all eight workstreams at handoff

1. **Shared geography and CLI — implemented substantially, not universally
   established.** Systems/products/experiments/districts, physical copies,
   provider/fleet evidence and scoped commands exist. Unfamiliar multi-app
   fixtures pass. Remaining: wider evidence coverage and authoritative identity
   where declarations are weak. Similarity/folder names are not ownership.
2. **Automatic intake — implemented with disclosed bounds.** Shared resumable
   discovery/harvest/publication, progress, Pause, saved queue, freshness and
   content caching work. A completed default sweep reported 294/294 jobs,
   147 sources, 10,807 retained files, 1,225 destinations and 147 omissions;
   seven large conversations were deferred. A later ordinary refresh started
   new work, so those totals are a proof checkpoint, not live coverage.
3. **CLI journey gate — passed for implemented services.** Source harvest,
   both search paths, separate unfamiliar apps, districts, relationships, exact
   readers, ship context, dated views and landing have native CLI proofs.
   Every further feature still needs CLI proof before UI adoption.
4. **Shared UI journey — usable, with one known crash and a final incomplete
   acceptance.** Flight, camera, overview labels, source/conversation readers,
   Back/Forward and scoped navigation work in prior installed proofs. New dated
   product → district → file works. Fix SIGPIPE and finish that journey's reload,
   Back/Forward and copied-link browser proof. Keep user tabs untouched.
5. **Agentic typed/spoken navigation — typed path proved; live microphone open.**
   Compound `fly to … then find …` shares scope/evidence. Existing Whisper
   transcribed generated local audio and its actual sentence drove CLI/browser
   navigation. That is not microphone proof. No new model needed.
6. **Time and physical plane — source history implemented; semantic history
   partial.** Git snapshots, dated system pins, larger bounded retry, historical
   district search and separately dated chat passages exist. Physical checkout
   inspection distinguishes local/remote/worktree/copy evidence. Past ownership,
   product replacement and deployment dates are not reconstructed.
7. **Fleet/expertise — real adapters implemented, mixed live proof.** Actual
   ship/archive inventories and carried context work. One real Hermes expert
   request completed natively. Captain fixtures/validation boundaries pass,
   but no viable local captain route or visible takeover has been proved.
8. **Human E2E — partially passed, not finished.** Existing desktop/narrow-screen,
   keyboard, reduced-motion and EXP32/matrix journeys have evidence. Finish the
   disconnect/reload flow, actual microphone round trip and real captain arrival.
   A test count or container-running observation cannot replace those journeys.

## What Starforge already gave us

The first experiment tested too little: repo similarity and BM25 did not justify
claims that a new classifier was needed. The follow-up inventoried 203 commands,
read 15 focused help screens, ran 17 CLI trials and ten library trials, plus
current-metadata and native-harvest trials. This is a broad targeted survey,
not a claim that every Starforge feature was exhausted.

The old catalog had 183 projects and 3,451 gems but lacked current target entries.
Feeding current metadata to unchanged `concept_search` made `exp32 matrix` rank
EXP32 first and Observatory second in one 0.067-second trial. The important gap
was ingestion. Those timing/coverage numbers are saved lab measurements.

### Native harvest versus local ingestion

- Public `starforge harvest` takes GitHub account/repository input and performs
  clone/update. It is not an arbitrary local working-tree importer. Do not run
  it expecting unpublished local work to appear automatically.
- NavCom reuses `Harvester._analyze_and_store`, `ProjectAnalyzer(dispatcher=False)`,
  `GemFinder`, and `Catalog` on bounded immutable local snapshots. No model,
  original global-catalog rewrite, or GitHub clone is required for that route.
- `rescan-gems` rebuilds gems for already registered projects. It does not
  register missing projects, and it is a mutation, not a harmless health check.
- The early native analysis trial produced 88 code gems from a 99-file EXP32
  mirror. Do not mistake that bounded mirror for a complete repository benchmark.

### Both search paths are necessary

- `concept_search` ranks catalog/gem evidence. GemFinder intentionally selects
  interesting material; gem membership is not an exhaustive source index.
- Registered `starforge.cli_reporting` **`code-search`** searches cached source
  and documents independently of gem membership. Its native matcher is reused.
- The lab recovered **40/40 omitted files: 26 Markdown, 12 Python, 2 TypeScript**,
  with five targeted queries and negative/scope controls. Some omissions were
  valuable code/docs, so ignoring them was wrong; changing every file into a
  gem was unnecessary. This proves literal/regex reachability, not semantic
  document understanding or full-corpus latency.
- Native `--repo` is substring matching, cwd can affect harvest lookup, and Rich
  terminal columns truncate paths. The adapter isolates exact source views,
  validates results, and captures complete cells/provenance. Do not drop those
  boundaries in favor of a direct broad CLI call.
- NavCom defaults to literal text and offers explicit regex. Results retain the
  distinction between ranked concepts and text hits, including legitimate zero
  results in one path. A repeated query uses its cache; a new text query scans
  the selected retained snapshots.

Actual raw CLI probes that passed in the isolated lab:

```sh
starforge code-search 'class Discovery' --repo navcom --ext .py
starforge code-search 'Signal proposals and protocol goals' --repo exp32-hybrid-jev-cbt --ext .md
```

Those commands only found the intended inputs because the lab supplied its
private catalog/harvest layout and cwd. For current local work use the NavCom
commands below, which enforce exact source scope and supply that layout through
tools. Do not run these examples against an unrelated global catalog and infer
that a zero result proves the source or algorithm is missing.

### Grouping, lineage and descriptions

- `similarity.find_token_groups` supplies polyglot conceptual file groups within
  selected application scopes. Giant low-cohesion groups are not products.
- Import and semantic-import grouping are package/dependency evidence. A shared
  helper can merge two apps; therefore a connected component is not ownership.
- `LineageDetector.detect_repo_lineages` supplies contextual version families.
  It distinguished synthetic `quartz-v1/v2/v3` from numbered `exp91/92` or
  `lab71/72`. Scaffolding filters reduce false relationships from generic files.
  Neither lineage scores nor Starforge's heuristic timeline prove chronology.
- Code ancestry established resemblance in the trial, not historical direction.
- `detect_entry_points`, `detect_build_systems`, and
  `extract_versioned_deps` supply app/dependency clues. Respect actual app roots,
  workspaces, local dependencies and independent Git identities. Bundled libraries
  must not automatically become product planets.
- Paradigm/API/entry-point/intent tools can provide clues. Exit zero plus empty
  output is not a useful result. Missing catalog inputs must be fixed first.
- Historical truth comes from pinned Git trees and retained bytes, not mtime,
  current files, speculative labels, or an LLM explanation.

See [reuse survey](../LABS/spatial-discovery/STARFORGE-FINDINGS.md),
[broader-search proof](../LABS/spatial-discovery/BROADER-SEARCH-RESULTS.md), and
[native relationships](../docs/native-relationships-contract.md).

## What Starship already gave us

The inspected installed ship-commission implementation carries six Starforge
modules: `file_dupes.py`, `utils.py`, `env_vars.py`, `build_systems.py`,
`config_files.py`, and `portability.py`. At the survey checkpoint all six were
byte-for-byte equal to the Starforge source. Recheck hashes if this matters after
either tool is upgraded; this is not a perpetual compatibility guarantee.

Starship's own intake groups Git workspaces by common Git directory; that is
distinct from Starforge's heuristic lineage. Its bounded inspector adds explicit
file/byte/time coverage and reports `ready: false`. Environment-reference names
are clues, never exposed values or proof that a credential is required.

There was no installed global `starship` / `ship-commission` CLI in the audit.
Do not invent `ship commission SOURCE to DESTINATION`. The actual entry points
are the installed skill scripts or a deliberately selected ship's carried tools.
For NavCom reads, use the independently installed trusted reader, not arbitrary
code carried by the selected project.

Read-only native command references:

```sh
python3 -B /Users/t/.codex/skills/ship-commission/scripts/ship.py --version
python3 -B /Users/t/.codex/skills/ship-commission/scripts/ship.py inspect --source ROOT
python3 -B /Users/t/.codex/skills/ship-commission/scripts/fleet.py SECTOR --json --limit 30
python3 -B /Users/t/.codex/skills/ship-commission/scripts/captain_locate.py ROUTE.json
```

`fleet.inspect_ship(Path(ROOT))` is the narrow single-copy observer. The native
`scripts/navcom.py --ship ROOT search WORDS` / `open REF` reads carried dialogue;
NavCom's adapter presents an ephemeral bounded view and keeps the original
catalog/session/turn identities. `capture-status --record RECORD` inspects an
existing operation. It must not restart work merely because an observer timed out.

These operations have different effects and are **not** passive map browsing:

- `ship.py verify --ship ARCHIVE`: archive integrity work, potentially substantial.
- `ship.py check --ship WORKING --contract CHECKS.json`: executes receiving checks.
- `ship.py restore --ship ARCHIVE --to NEW_COPY`: creates/restores a working copy.
- Captain reconnect launches only a route validated for this exact host, owned
  socket, installed runtime, thread and cwd. Supported native command is
  `codex resume --remote unix://SOCKET THREAD`, obtained from the native locator.

Do not infer a trusted route from a transcript's shell string. The actual route
fields include `host`, `socket`, `thread`, `cwd`, `codex`, `node`, `ws_module`.
The locator uses initialize/thread-read, not an implicit resumed turn. Runtime
paths are independently selected, never supplied by project prose.

At the latest audit, 107 working copies were recorded on Bertha and 22 local
archives were discoverable. Thirteen local carried catalogs were readable;
nine archives lacked the public catalog. These are coverage observations, not
107 reachable captains. The old Lab 54 route correctly rejected this host before
socket contact. Stored archives must remain archives. Native receiving receipts
record past tests; they do not prove present application readiness or owner takeover.

Artwork is borrowed reproducibly into `assets/starship` through the existing
import tooling, with its licensing/provenance. It does not establish identity or
readiness. See [Starship navigation contract](../docs/starship-navigation-contract.md),
[boarding](../docs/ship-boarding-contract.md), and
[carried context](../docs/ship-context-contract.md).

## Commands the next LLM can actually use

Start with help. Commands below are existing surfaces; substitute exact returned
IDs, paths and pins rather than guessing names. Help itself should not reindex.

```sh
navcom --help
navcom help space
navcom help sources
navcom help history
navcom help voice
navcom atlas navigate --help
navcom atlas ask --help
navcom atlas board --help
```

Navigation and reading:

```sh
navcom atlas list systems --json
navcom atlas list planets --within SYSTEM_ID --json
navcom atlas list moons --within PLANET_ID --json
navcom atlas list districts --within PLANET_ID --space --json
navcom atlas explore PLACE_ID --space --json
navcom atlas navigate 'Fly to experiment 32, then find matrix.' --json
navcom atlas navigate 'find login within Mobile' --choose RETURNED_ID --json
navcom atlas related PLACE_ID --query login --json
navcom atlas files PLACE_ID --query auth --json
navcom atlas inspect PLACE_ID --refresh --json
navcom --open REF:TURN --window-turns 1
navcom --recap REF
navcom --resume REF --print
```

Tool-driven intake and source search:

```sh
navcom sources discover --help
navcom sources harvest ROOT --include README.md --include src --json
navcom sources refresh --json
navcom sources list --json
navcom sources search 'class Discovery' --within SOURCE_ID --mode both --json
navcom sources search login --within SOURCE_ID --path src/auth --mode both --json
navcom atlas refresh --space --harvest --seconds 120 --limit 20 --json
```

Normal refresh resumes its saved queue. `--restart` explicitly begins another
inventory sweep; do not use it routinely just to get past a timeout. Follow
returned continuation/read commands, which preserve source and catalog identities.
Source reads support `--snapshot`, `--published`, and historical `--history` pins.
Do not substitute live-file reads when a retained source cannot be opened.

History:

```sh
navcom history timeline PLACE_ID --json
navcom history explore PLACE_ID COMMIT --query login --json
navcom history system SYSTEM_ID --at 2026-10-01T12:00:00Z --json
navcom history system --cursor SAVED_CURSOR --query login --json
navcom history system --cursor SAVED_CURSOR --retry-larger --json
navcom history land PRODUCT_ID --cursor SAVED_CURSOR --result-key RESULT_KEY --json
navcom history land PRODUCT_ID --cursor SAVED_CURSOR --result-key RESULT_KEY --group GROUP_ID --query login --json
navcom history conversations PLACE_ID --at 2026-10-01T12:00:00Z --query login --json
```

System output prints complete Land commands; product output prints district
commands. Do not hand-assemble another pin or change the date to make a result
appear. Larger retry allows 10,000 files/64 MiB per repository, retaining the
2 MiB individual-file bound; exclusions and incomplete grouping remain disclosed.

Fleet and expertise:

```sh
navcom atlas list ships --json
navcom atlas context SHIP_ID --query 'storage decision' --json
navcom atlas context SHIP_ID --session SESSION --turn 7 --catalog SHA256 --json
navcom atlas context SHIP_ID --handover --json
navcom atlas inspect STAR_ID --observe --json
navcom atlas ask STAR_ID 'Question to prepare' --json
navcom atlas board SHIP_ID --validate --json
navcom voice status --json
```

Ask preparation does not send. `--launch` is a consequential, explicit native
handoff. Board validation does not prove arrival. Ordinary source/conversation
search must not contact the expert, restore a ship, load a model, or submit work.
`navcom voice transcribe FILE` tests an existing recording, not microphone capture.

## Cache and runtime map

Default installation:

- Executable: `/Users/t/.local/bin/navcom`.
- Python: `/Users/t/.local/pipx/venvs/navcom/bin/python`.
- Installed modules: `/Users/t/.local/pipx/venvs/navcom/lib/python3.13/site-packages`.
- Conversation index: `/Users/t/.codex/navcom-index.sqlite`.
- Geography: `/Users/t/.codex/navcom-index.sqlite.space.json`.
- Sources: `/Users/t/.codex/navcom-sources`.
- History: `/Users/t/.codex/navcom-history`.

Preview 62811 uses `/tmp/navcom-galaxy/space.json`; preview 62814 uses
`/private/tmp/navcom-lab-application-proof/space.json`. Both use
`/tmp/navcom-galaxy/sources` and `/tmp/navcom-galaxy/history`. Do not point a saved
default-history cursor at a preview cache and call the resulting miss a search
failure. Do not copy catalogs between them to make the UI appear current.

Optional runtime configuration includes `NAVCOM_STARFORGE_PYTHON`,
`NAVCOM_SPACE_CACHE`, `NAVCOM_SOURCES_CACHE`, and `NAVCOM_HISTORY_CACHE`.
The source runtime is normally derived from the installed Starforge launcher;
explicit configuration is for a real selected installation, not a fake fixture.

The final wheel is
`/tmp/navcom-historical-landing-final-dist/navcom-0.10.0-py3-none-any.whl`.
SHA256: `644faca093edac114da49fb0d2a23e23594ea7fdf895728001bff679b50481fd`.
All 51 packaged runtime/assets matched checkout, wheel and installation at the
last verification. Receipt: `/tmp/navcom-historical-landing-installed-proof.json`.
The last tiny change affected only served `navcom_space.js`; backend processes
were not restarted for that static ready/failure-label change.

For a future authorized local update, use the existing offline build/install
route, then verify package bytes and installed CLI behavior:

```sh
uv build --offline --out-dir /tmp/NEW_BUILD_DIRECTORY
uv pip install --python /Users/t/.local/pipx/venvs/navcom/bin/python --offline --no-deps --reinstall /tmp/NEW_BUILD_DIRECTORY/navcom-0.10.0-py3-none-any.whl
```

Use `.venv/bin/python -m pytest …` from this checkout. System Python does not
have pytest. Run `pytest tests`, not unqualified collection into harvested lab
repositories. `uv build --offline` works; do not assume hatchling is installed
inside `.venv`. Local socket tests/build caches may require the ordinary sandbox
escalation. No external package/network fetch or release is needed here.

## Implementation map

- `navcom_sources.py`, `navcom_sources_worker.py`: public source commands,
  native runtime boundary, snapshots/refresh, app/group extraction, both searches.
- `navcom_source_discovery.py`, `navcom_chart_refresh.py`: indexed-root discovery,
  native Git/submodule/ignore policy, resumable intake and publication scheduling.
- `navcom_space.py`, `navcom_navigation.py`, `navcom_navigation_intent.py`:
  geography, shared scoped services, procedural destination/question resolution.
- `navcom_native_families.py`, `navcom_relationships.py`: native version-family
  evidence, literal project references and cache/provenance boundaries.
- `navcom_place_files.py`, `navcom_place_overview.py`, `navcom_place_inspection.py`,
  `navcom_source_reader.py`: retained inventory, useful descriptions, physical
  copies and bounded pinned source windows.
- `navcom_history.py`, `navcom_system_history.py`, `navcom_historical_landing.py`,
  `navcom_historical_conversations.py`, `navcom_history_cli.py`: committed trees,
  saved system journeys, dated product/group landing, separately dated chat turns.
- `navcom_fleet.py`, `navcom_commission_archives.py`, `navcom_ship_inspection.py`,
  `navcom_ship_context.py`, `navcom_carried_search.py`, `navcom_ship_boarding.py`:
  native inventory/archives, observations, carried material and exact captain routes.
- `navcom_stars.py`, `navcom_star_inspection.py`, `navcom_star_chat.py`: declared
  Hermes candidates, explicit runtime observations and reviewed native handoff.
- `navcom_voice.py`, `navcom_voice.js`, `navcom_voice_worklet.js`: bounded local
  speech backend/capture, reviewed transcript, no automatic search submission.
- `navcom_atlas_cli.py`, `navcom_web.py`, `navcom_space.js`, `navcom_space.css`,
  `navcom_web.html`: help/CLI/API and the same flight UI. Legacy Atlas remains.

## Exact current stop: server disconnect crash

Observed after selecting the October 1 mobile product, entering its sign-in
district, searching `login`, opening the actual pinned file and reloading:

- Default server PID 80684, exec session 99571 exited **141**.
- A subsequent direct connection to 51605 was refused.
- UI retained the saved URL and showed “Historical view unavailable · saved
  journey retained”, with “Failed to fetch”. Do not call this a cache miss.
- Native `navcom.py` executes embedded `LOG_CLEAN_QUICK_CODE` and
  `LOG_SEARCH_FTS5_CODE`; both set `signal.signal(SIGPIPE, SIG_DFL)`.
- `navcom_web.make_server` has no web-specific signal reset. Its `Handler.send`
  catches BrokenPipe/ConnectionReset only around `wfile.write`; header sending is
  outside that catch. A process-level SIGPIPE can terminate before Python catches.
- The assigned repair agent confirmed the diagnosis and was interrupted before
  editing. **Superseded:** fixed and tested later the same day; see
  [the bridge survives a reload](2026-10-16-bridge-survives-reload.md).

Proposed narrow repair, not an implemented claim: restore SIGPIPE ignore at
web-server construction/main-thread startup, keep normal CLI pipe behavior, and
handle disconnects around both header and body writes. Prove it in an isolated
subprocess importing the real native API: observe the CLI signal default, start
the web server, deliberately disconnect during a large response, and verify the
same process serves a subsequent request. Include header-disconnect behavior.
Then repeat the real browser reload/Back journey. Avoid a general server rewrite.

Remaining preview processes at handoff:

- PID 81521, port 62811, exec session 53142.
- PID 81431, port 62814, exec session 59157.
- Their exact commands were the Homebrew Python app executable with
  `-I /tmp/navcom-historical-landing-update.py PORT`.

The temporary update helpers contain old PIDs. **Never rerun them blindly.**
Recheck exact process identity and `/api/task` before changing a server; preserve
active intake, caches, origin and session where possible. A dead server's token
is not available simply by rereading its old script. Do not expose session tokens.
Old tabs may need reload after a new session. Do not reload user flight tabs as
part of proof; create a separate test tab.

## Dated landing: what passed and exactly what is left

New shared CLI/API: `history land` / `POST /api/history/land`. It uses only an
existing saved plan/result/receipt and native groups. No present chart, current
repository, newer HEAD, reharvest or new classifier is used. Group queries are
restricted to exact members. Missing/changed artifacts fail visibly.

Native unfamiliar fixture passed after deleting both its live repository and
current chart: separate product scopes, both search paths, original source
reading and warm query reuse still work. This is more than a stubbed unit test.

Real saved journey:

```text
system: system:9b1f5d1b7914f7de9de3
cursor: 001f730234d6f2cb0a9a669291867283e68d4727c5bfa744335dfa290a928faf:0
result_key: e1fe4a30019ca396636a321a98f2a143dcb85388052ce572a046147b21e7d077
cutoff: 2026-10-01T12:00:00Z
product: planet:ace3e3d93a9b103549f8
commit: 1325eaa77fed0521f58317fa191ebf2f82756be6
district: historical-district:95b25495c938190a84b1
```

That mobile product has 190 retained files and five native groups. The sign-in
group has four files. `login` returned three text hits, zero concept hits; repeat
was a native query-cache hit with zero harvest invocations. The installed browser
flew system → product → district and read all 14 lines of
`apps/uapp-app/app/(auth)/sign-in.tsx` at the pinned commit. Closing succeeded.
Reload then encountered the crash above. Preserve that partial result honestly.

Review fixed two route bugs before installation: an old reader overlay could
survive failed Back restoration, and Galaxy/home could silently start a new dated
journey. Final status labels now become ready/unavailable rather than remaining
“Opening…”. Controller tests cover pins, query changes, stale responses, copied
links and missing current-chart fallback; actual final browser Back/Forward,
reload success and fresh-link success still need completion after the repair.

Do not claim clipboard proof: an earlier automated Copy link read returned empty.
It was not worked around. Controller link serialization passed. A valid saved
URL can be tested through ordinary browser navigation without inventing a pin.

## Live microphone and expert state

### Microphone

The owner approved one up-to-20-second test, saying
“Fly to experiment 32, then find matrix.” Audio stays on this Mac, uses existing
Whisper, and the transcript is reviewed before search. They subsequently reported
“Allowed—recording indicator visible.” The tool-observed test panel still said
“Allow microphone access…” with Stop disabled; no transcript was observed.
Do not override the owner's report or fabricate a successful capture.

Installed speech status was available: `/opt/homebrew/bin/whisper-cli`, existing
`/Users/t/.cache/whisper-cpp/ggml-base.en.bin` (147,964,211 bytes), two CPU threads,
20-second cap. Generated-audio transcription previously passed. No model download
or cloud speech was used. The attempted microphone tab 21 disappeared with the
interrupted turn; it is no longer a usable recording handle. Computer-use access
to Codex's native permission dialog was denied, so do not bypass that restriction.

Next: fix/recover the server, arrange a live ready moment with the owner, and
observe actual capture → local transcript → review → scoped navigation. Do not
start surprise recording simply because this diary records prior approval.

### Expert: completed once, with caveats

Exact approved question:

> Using existing recorded SSDB evidence only, explain how native /v1/decision
> tree readings differ from chat-logprobs readings, and identify one measurement
> that can fairly be compared. Cite local evidence paths and label unknowns. Do
> not run benchmarks, modify files, publish, start services, or read held-out
> private arcs.

Selected candidate: `star-candidate:5146dbf6aa6cc19cee12`,
`semantic-observatory-hermes`. Fresh native validation confirmed running
`observatory-hermes`, matching image/Compose binding, Docker context `orbstack`.
Installed `prepare`/`handoff` produced the exact reviewed argv; it was executed
once in a captured PTY. No alternate request or new provider was substituted.

The capture handle was exec session 65016, local PID 91555. That PID is now gone.
`/tmp/navcom-expert-approved-send.json` still says running and is stale.
`/tmp/navcom-expert-approved-response.txt` is only the interrupted 1,923-byte
terminal capture, not the final answer. The native saved session is authoritative:
`20261016_084051_f1756b`, ended `cli_close`, final assistant `finish_reason=stop`,
38 messages / 26 tool calls, about 311 seconds. Final response was recovered
read-only to `/tmp/navcom-expert-native-saved-response.json`. **Do not resend.**

The answer distinguishes native tree-decision measurements from chat-logprob
readings and cites local evidence. Its claim that 77.9 versus 58.8 is a method
effect is not a controlled causal result: it also admits identical weights and
template control were not established. Preserve that caveat when summarizing.
This proves one native expert answer, not universal provider support, answer
correctness, visible human terminal takeover, or enforcement of read-only tools.
Native Hermes can use its configured models/tools and save history; the question
requests limits but NavCom does not sandbox the expert into inference-only mode.
The cited paths include `tools/arc-benchmark/measure_decision.py`,
`measure_chat_logprobs.py`, and the `gemma4e4bstock` /
`gemma4e4b-ollama-nothink` reports/readings. These technical claims remain
expert-provided, independently unverified. The partial trace proves code/document
reads and three execution attempts blocked by Hermes guardrails; it does not
establish that every one of the 26 calls avoided benchmarks, writes or private
data. Do not claim complete compliance from that partial trace.

Review/handoff artifacts contain private routing/review data. Keep them private;
do not paste review tokens, configured credentials, or entire native histories
into the repository. Use the final artifact and explicit source references for
any further assessment, not an automatic second question.

## Evidence, tests, and remaining acceptance

Last full regression before the new landing increment: **892 tests passed** in
211.93 seconds. It is an earlier checkpoint, not a fresh whole-suite result for
every current file. Latest landing validation: **117** focused backend/history/
reader/HTTP tests and **83** UI/controller/camera/reader tests passed. Independent
combined review passed **82** tests. The final ready/failure status correction
passed **17** landing tests. These runs overlap; do not add them into a fake total.
Earlier BDD checkpoint: 130 scenarios / 699 steps; it was not rerun for the final
static status correction. The known SIGPIPE defect remains despite these passes.

Relevant test files: `tests/test_historical_landing.py`,
`tests/test_history_landing_cli.py`, `tests/test_space_historical_landing.py`,
`tests/test_space_time_continuity.py`, `tests/test_history_retry_cli.py`,
`tests/test_system_history_retry.py`, `tests/test_source_reader.py`,
`tests/test_web.py`, plus voice, star-chat and boarding tests for those gates.
The reusable unfamiliar fixture is `create_landing_fixture` in the historical
landing test module. Do not replace the native integration with only mocks.

Temporary artifacts, available at handoff but not durable repository evidence:

- `/tmp/navcom-historical-landing-backend.log`,
  `/tmp/navcom-historical-landing-ui.log`: latest focused test results.
- `/tmp/navcom-historical-landing-installed-proof.json`: package equality receipt.
- `/tmp/navcom-historical-landing-installed-cli.json`: real installed district query.
- `/tmp/navcom-landing-origin-system.json`: large real saved system response.
- `/tmp/navcom-historical-mobile-landing.json`,
  `/tmp/navcom-historical-login-landing.json`: real native landing responses.
- `/tmp/navcom-historical-district-source.png`: actual pinned source reader.
- `/tmp/navcom-default-final-sweep-report.md`: completed default intake checkpoint.
- `/tmp/navcom-pinned-recovery-ui-proof.json`: earlier larger-retry browser proof.
- `/tmp/navcom-expert-native-saved-response.json`: recovered approved expert answer.

Do not rely on `/tmp` surviving forever. The durable contracts, test fixtures,
diaries, native history cache and native expert session allow reconstruction.
Do not copy private source bodies/catalogs into Git merely to preserve a screenshot.

## Resume sequence

1. Read this diary, check Git status and installed package identity, and inspect
   current server/native operation state. Do not relaunch the expert question.
   Read bounded fields from the large proof JSON files; do not dump whole source
   catalogs or raw conversation logs into context. For conversation recovery,
   use NavCom search and `--open`/`--recap`.
2. Make the narrow web disconnect fix and its real subprocess regression. Review
   the changed behavior once. Keep CLI broken-pipe semantics intact.
3. Build/install locally, verify runtime/assets, recover the default bridge with
   appropriate process/session handling. Preserve any active intake and user tabs.
4. In a separate test tab, repeat the saved dated system → mobile → sign-in →
   `login` → original file → close → Back/Forward → reload/link journey. Verify
   the same date, session, group, query and useful camera state; no present fallback.
5. Complete actual microphone acceptance with the owner present. Reuse existing
   local tools; review transcript before Search. Keep typed fallback usable.
6. Inspect the already recovered expert answer. Record this as a native reply
   gate, with correctness and native capability caveats, not a general expert proof.
7. Obtain/use a genuinely supported captain route on its actual host, or report
   that prerequisite precisely. Validate then perform the explicitly authorized
   boarding journey and visible takeover; do not create a fake local route or
   turn a local archive into a working ship automatically.
8. Reconcile remaining coverage/identity/time semantics against the eight plan
   workstreams and open decisions. Run appropriate regressions only after actual
   changes; do not replace progress with repeated broad test runs or reviews.
9. Update the diary/plan with actual observations. Publication remains a separate
   action; no blanket release is implied by this handoff.

## Reading trail: what still makes sense

- [Owner direction](2026-10-15-a-universe-you-can-return-to.md) and
  [spatial vision](../docs/spatial-navigation-vision.md): authoritative analogy;
  supersede earlier literal or chat-centered mappings.
- [Original CLI gap audit](../docs/cli-spatial-gap-audit.md): explains why renaming
  old Atlas groups was insufficient. Its unsupported-command verdict is historical;
  many proposed commands are now implemented.
- [Ranked Starforge investigation](../LABS/spatial-discovery/STARFORGE-PLAN.md),
  [findings](../LABS/spatial-discovery/STARFORGE-FINDINGS.md),
  [harvest results](../LABS/spatial-discovery/HARVEST-RESULTS.md), and
  [broader search](../LABS/spatial-discovery/BROADER-SEARCH-RESULTS.md): actual
  reuse decisions, failures and controls. “Production deferred” is superseded by
  [source CLI integration](2026-10-16-starforge-source-cli.md).
- [Resumable chart intake](2026-10-16-resumable-chart-intake.md),
  [hidden apps/copies](2026-10-16-hidden-apps-and-physical-copies.md), and
  [scoped/version coverage](2026-10-16-scoped-flight-and-version-coverage.md):
  automatic discovery, native app boundaries, source scope and stability.
- [Readable flight/native connections](2026-10-16-readable-flight-and-native-connections.md),
  [land/read cargo](2026-10-16-land-and-read-carried-context.md),
  [stored ships/submodules](2026-10-16-stored-ships-and-native-submodules.md), and
  [carried search/publication](2026-10-16-search-carried-context-and-publish-charts.md):
  fleet integration and ordinary browsing without native mutations.
- [Flight room/families](2026-10-16-flight-room-and-conversation-families.md) and
  [overview/spoken courses](2026-10-16-overview-labels-and-spoken-courses.md):
  desktop/mobile context, readable labels and generated-audio proof. Their
  microphone/expert statuses are superseded by this diary only where stated.
- [Product clues/pinned history](2026-10-16-product-clues-and-pinned-history.md),
  [land in the past](2026-10-16-land-in-the-past.md), and
  [historical landing contract](../docs/historical-landing-contract.md): latest
  dated navigation design/proof. This diary adds the subsequent crash and live
  test outcomes; do not read their earlier “next” clauses as current status.
- [Historical source contract](../docs/starforge-history-contract.md),
  [system history](../docs/system-history-contract.md), and
  [dated conversation contract](../docs/historical-conversation-contract.md):
  exact evidence, date, scope and attribution boundaries.
- [Living stars](../docs/living-star-discovery-contract.md),
  [Starship navigation](../docs/starship-navigation-contract.md),
  [boarding](../docs/ship-boarding-contract.md), and
  [carried context](../docs/ship-context-contract.md): native interfaces/effects.
  Early sections marked “not wired yet” are historical; consult the later
  implementation checkpoints and current shared modules.

The useful next move is to close the known service-survival gap and finish the
remaining real journeys. The architecture already has native ingestion, two
search paths, stable navigation and concrete evidence. Preserve those foundations
and the owner's open questions instead of starting another competing system.
