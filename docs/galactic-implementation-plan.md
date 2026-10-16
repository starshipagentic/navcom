# Galactic navigation implementation — active

Latest resume point: [October 16 handoff diary](../diary/2026-10-16-galactic-navigation-handoff.md).
It reconciles all eight workstreams and the original Wirth lab ladder. Its runtime
status supersedes the dated checkpoints below: new historical landing is locally
installed, a browser-disconnect SIGPIPE crash is diagnosed but not repaired, live
microphone acceptance remains unproved, one approved expert answer completed in
its native session, and real captain takeover remains open.

The goal is a usable, beautiful galactic experience for finding and resuming work:
owner galaxy → client/venture systems → products → experiments and districts,
with real code, documents, conversations, stars, bases and ships. The spatial
vision remains authoritative. A working map alone does not finish this goal.

The previous turn made progress: installed CLI harvest plus both Starforge search
paths passed end-to-end and cache tests. This turn builds on those actual tools.

## Implementation sequence and proof

1. **Shared geographic data and CLI (in progress).** Procedural discovery from
   indexed project roots, Git identities, existing organization metadata, declared
   app manifests and cached Starforge output. Stable IDs/coordinates; distinguish
   supported declarations from suggestions. Multiple products per repository,
   offline roots, explicit experiment moons; no child-session/moon conflation.
2. **Automatic intake (in progress).** A command discovers bounded source scopes
   and invokes the existing harvest worker. No manually synchronized catalog or
   curated client-specific profiles. Unchanged content/groups/queries are cached.
3. **CLI journey gate.** Show unfamiliar systems, separate applications, an
   experiment and meaningful token-group districts. Search inside a district's
   actual file scope and return conversation evidence. Prove cached reads and
   stable identity before rendering new UI.
4. **Shared UI journey.** Consume the same service, with distinct visual objects,
   smooth bounded flight, usable labels, selected-place details, breadcrumbs,
   reliable Back/Forward and saved viewpoint. Search highlights without relayout.
   Reuse Starship artwork through a reproducible import command.
5. **Agentic navigation.** Typed and spoken intent share the same current scope.
   Plan understandable read-only steps across destination, code/document and
   conversation evidence; allow following a result and returning. An optional
   existing local model can enrich interpretation but is never required.
6. **Time and physical plane.** Historical evidence must exclude future material;
   unknown historical state stays unknown. Host/storage location is inspectable
   separately from conceptual position. Do not manufacture a historical snapshot
   from file modification time.
7. **Fleet/expertise integration.** Consume actual Starship receipts and supported
   routes. Stars are declared living expertise, not every repository. Bases/ships
   keep host identity, receipt age, gaps and actual readiness. Boarding must use a
   verified route, never a pretend readiness flag or generic conversation resume.
8. **Human E2E acceptance.** Start at galaxy, find multiple systems/products,
   navigate EXP32 then matrix within scope, inspect a district's code and related
   conversation, return without losing place, test voice availability/fallback,
   inspect a ship/base and unavailable route, revisit saved position. Test narrow
   screen, keyboard and reduced motion. Publish only when separately authorized.

Do not mark the full goal complete until all applicable behavior is verified.
Missing assets, data, routes or live readiness remain explicitly unfinished.

## Evidence checkpoint — October 16

- Shared spatial CLI and API are implemented. Real Starforge searches respect a
  district's exact file scope. An unfamiliar two-app repository stays separated.
- Discovery invokes harvest and retains registered scopes. A fresh browser with
  no space/source cache automatically produced a Polaris system and separate
  Aurora, Radar and Compass destinations. Reload left publication time unchanged.
- Bridge flight, scoped search, conversation reader, Back/Forward, saved viewpoint,
  mobile labels, pan/zoom and existing Starship artwork are connected. Browser
  EXP32 → matrix → experiment → Back preserved query and exact node positions.
- The shared Navigator executes read-only destination/source/conversation steps.
  Unique destination commands fly; exact duplicate names show choices. Back/home
  use browser history; replay cannot execute a previous navigation command again.
- Source federation now searches eligible sources in one native worker rather
  than cutting off after twelve. A real 15-source/15-conversation fixture found
  the last source and preserved narrow file/conversation exclusion. Time budgets,
  truncation and cache use remain visible.
- Local voice availability and typed fallback are connected. Actual speech
  capture is **not proven** on the tested browser: no local speech pack is ready.
- Bounded automatic intake now includes code as well as documents and respects
  native Git ignore decisions. Files up to 2 MiB remain searchable; conceptual
  grouping separately discloses its 250 kB/file limit. A real NavCom intake kept
  its large main file and excluded ignored lab copies. The next 17-source refresh
  reused every source (0.049 seconds inside the worker).
- History has a shared CLI/API/UI path for committed repository snapshots. An
  old/new fixture and the real NavCom HEAD passed native harvest and both search
  paths; current dirty content stayed out. The browser retained selection,
  camera, historical commit and search across Back/reload.
- Ship inspection discovers matching existing receipts and invokes the installed
  bounded observer for local locations. Remote paths stay unobserved. Real
  NavCom mission context and its carried history retain separate receipt dates;
  a recorded pass does not establish current readiness or captain takeover.
- 255 NavCom pytest tests and 130 BDD scenarios passed. The final grouping
  disclosure change also passed 14 source/history integration tests. The local
  wheel was rebuilt, byte-checked and installed into the existing pipx environment.
  Installed history, ship inspection and cached source search passed. Nothing
  was published.
- The user-facing bridge now uses the actual existing conversation index rather
  than a bounded preview copy: 687,873 indexed turns, 6,619 geographically placed
  conversations and 17 harvested sources at this checkpoint. The CLI refreshed
  geography; no catalog records were synchronized by hand.

## Further checkpoint — expertise, readable sources and system time

- Native Hermes profile inventory and supported Compose/OCI metadata now produce
  separate, explicitly qualified expertise candidates. Candidates attach to the
  owner galaxy and relate to exact implementation products without establishing
  client ownership. Descriptions and charters are evidence; runtime stays unknown.
  Default charters without a provider description do not become star destinations.
- Discovery pages through the current inventory with a total budget, continuation
  root and explicit omissions. Ancestor context folders cannot poison project
  batches; a failing batch is isolated per root. A read-only replay attempted all
  329 eligible roots from the 331-root inventory and rediscovered the Observatory
  candidate. Two broad ancestor roots were excluded; unavailable locations and
  unsupported metadata remained disclosed.
- `atlas inspect` shares star and ship dossier routes between CLI and API.
  Selected-star metadata refresh persists separately from the chart. Explicit
  `--observe` checks an existing provider process; status, model readiness and
  metadata dates remain separate. Explicit observation is fresh, verifies the
  exact Compose binding and records sanitized Docker-context provenance. It never
  sends a question or starts a model. The browser observed the real running
  container; expert/model readiness remained unverified.
- Source results open through `sources read` and the same browser reader. Reads
  stay inside published artifacts with exact source/path scope, bounded windows,
  generation checks and historical receipt hashes. The actual cached NavCom
  source was read successfully without opening its current working file.
- Automatic intake now includes nested README and SOUL documents through the
  existing bounded, Git-aware walk. Two unfamiliar worker fixtures and metadata
  budget fairness pass. A real Observatory dry-run includes its worker README
  and charter; its Git-ignore time-budget omission is reported. No raw provider
  config was added by this rule and no catalog record was synchronized by hand.
- `history system` reconstructs committed source across a current system or
  galaxy's repository-backed addresses. The first page pins HEADs; cursors retain
  those pins. Unknown and unvisited places stay visible, and current paths or
  labels do not substitute for historical content. Native tests cover different
  old/new product identities, dirty-file exclusion, continuation after a new
  commit, and retry against the same pinned revision.
- The bridge has shared source-reader and system-time controls. The UTC cutoff,
  observed commit-date slider, remaining-repository continuation and return to
  present use these services. Current addresses and camera remain navigation
  anchors. Browser source paging, Back, Escape and mobile overflow checks passed.
  The old/new date fixture, slider and Back preserved positions and committed
  source content. The real Syra browser continued from four to five of thirteen
  repository jobs.
- Real Syra CLI continuation visited all thirteen pinned repositories and
  recovered committed content at thirteen of forty-two current addresses.
  Earlier 25/60-second retries exposed per-file Git reads inside skipped
  dependencies. The native Git batch reader now prepares that same 1,779-file
  revision and runs Starforge harvest in 9.507 seconds. Skipped directories no
  longer trigger unnecessary LFS checks. The final continuation took 4.281
  seconds; one separate repository remains above its file/byte budget. Missing
  historical paths and other unknown addresses remain visible, not inferred.
- Focused discovery tests passed 14 cases; the spatial/native-star suite passed
  27 cases before the document-intake extension. Source-reader, star-inspection
  and navigation tests passed 43 cases before the latest status-binding changes.
  These are component checkpoints, not a replacement for the final combined run.
- The updated help-example suite passed all five tests with loopback access for
  its isolated browser test. Overview and focused source/history/inspection help
  passed direct checks; the generated skill card matches the embedded source.
  Wheel and source-package allowlists contain all four new service modules.
- The combined regression covered all 319 pytest cases: 309 passed in the
  sandbox, and the socket-dependent web/help cases passed with local loopback
  permission. The BDD suite passed 130 scenarios and 699 steps; JavaScript syntax
  and diff checks passed. The final native batch change passed 52 focused
  history/system/reader tests, including two new regressions (321 total cases
  covered by passing runs). The local package was built offline, byte-checked
  and installed; installed source/history/inspection help and dated search passed.
  The final batch/layout rebuild also passed byte comparison and installed CLI
  replay. Desktop/mobile label-collision checks passed; the installed bridge is
  left open at the same URL. No release was published.

Remaining requirements include wider source coverage and clearer ownership where
evidence is weak, historical conversation attribution and organization changes,
broader expertise-provider support and verified ask-agent behavior, and verified
ship boarding/restored context. On-device speech capture remains unproven on this
browser. The full goal is not complete. See `starforge-history-contract.md`,
`system-history-contract.md`, `starship-navigation-contract.md` and
`living-star-discovery-contract.md`.

## Interaction checkpoint — October 16

The shared CLI/web services now prepare native Hermes questions, discover and
validate exact local captain routes, and transcribe short recordings through an
already installed Whisper model. Reviewed actions revalidate before terminal
dispatch. The bridge has explicit review dialogs; typing and flight stay available.

Historical conversation lookup now uses original recorded turn timestamps saved
by normal indexing. Legacy rows upgrade within the existing parser time budget;
unsupported/undated rows remain excluded. Dated passages have their own reader
and current-project attribution, separate from Git commit evidence. Browser
April/September filtering, parent-child clues, passage Escape and date/query Back
passed. The real expert preparation passed without sending a question.

Actual microphone capture, real expert response and visible captain takeover are
still unverified. Native action fixtures establish routing boundaries only. See
[the diary](../diary/2026-10-16-voice-native-handoffs-and-dated-turns.md),
[boarding contract](ship-boarding-contract.md) and
[dated-conversation contract](historical-conversation-contract.md).

This interaction build was installed locally and byte-verified across 32 runtime
files. Installed speech, expert preparation and dated-conversation CLI replay
passed. Normal CLI indexing—not a manual backfill—upgraded 53 live sessions and
recorded 25,189 dated rows; legacy coverage remains partial. Browser tests verified
that editing an expert question invalidates its launch review and remote ships
explain their unavailable route. The bridge stays open at its original address.

## Coverage and continuity checkpoint — October 16

The shared `atlas refresh --space --harvest` service now pins and groups its own
project inventory, resumes bounded workers, checkpoints geography, and retains
other published sources when a selected source is updated. It provides the web
bridge's progress, Pause, resume and completed-sweep freshness behavior. Broad
unversioned containers delegate descendant projects instead of harvesting their
code again. Native Git policy uses one streaming process per repository.

Exact nested LAB/app identities and same-folder system containers now reconcile
without moving retained destination IDs/positions. Conflicting ownership and
containment cycles stay explicit. Natural questions use Starforge's native term
extraction and both search paths; result cards show exact saved place memberships.
All parts of a request read one chart publication, including restored questions.

468 pytest cases and 130 BDD scenarios (699 steps) passed. The local wheel was
rebuilt offline, installed and byte-verified across 33 runtime files. Installed
refresh help and flight resolution passed. Browser tests verified separate Syra
products, native Cognito evidence, cached source reading, Escape/Back/Forward,
refresh reconnection and preservation of a draft through Pause. The installed
bridge remains open at its original address.

Coverage remains partial: 338 indexed folders become 294 native-root source jobs;
the bounded sweep is ongoing. Broader text matching can contain loose matches;
ranked code clues are displayed first. Real live microphone capture, expert replies
and captain takeover remain unverified. No external release was published and the
full goal is not complete. See the resumable-intake diary for the exact decisions.

## Nested applications and physical copies checkpoint — October 16

Automatic bounded intake now preserves native runnable app manifests inside a
repository. Starforge entry/build detectors and conceptual grouping establish
app-scoped destinations and districts. Overlapping ancestor catalogs reconcile
through native Git ownership; existing saved evidence remains scoped to its exact
subtree. Missing and substituted locations preserve the previous placement while
being marked unavailable. The live Syra harvest and CLI refresh found the nested
mobile and universal apps without client-specific profiles or manual catalog sync.

CLI and UI share a dated physical-location inspector showing paths, branches,
commits and native Git copy relationships. Destination pagination, reader return,
keyboard Fly focus, long voice transcript review and refresh continuity were also
verified. EXP29's first native grouped intake took 5.61 seconds and its separate
cached invocation took 1.28 seconds with no reanalysis.

The full regression gate passed 499 tests and 130 BDD scenarios (699 steps).
Later ownership edge fixes passed focused and independent review gates. The local
wheel's 34 runtime files were byte-verified after installation. Installed CLI
mobile search and physical inspection passed; real browser flight and dossier
inspection passed. The user's flight bridge stays open. Broader coverage, product
generation relationships and real voice/expert/captain journeys remain incomplete.

## Readable flight and native connections checkpoint — October 16

The bridge now keeps one two-dimensional chart across desktop and narrow windows,
with readable initial zoom, an overview control, preserved positions and explicit
Fit. Back restores camera/query/selection and evidence state. Duplicate product
names carry distinguishing paths. Fresh menu startup now indexes native logs;
persisted Pause and bounded-stop explanations were proved in an installed build.

`atlas related` proved native version families, exact retained source reads and
documented project links before the UI adopted that same service. It reuses
Starforge lineage and both search paths, caches results, preserves scope and does
not infer ownership or chronology. Browser testing found an unrelated-publication
race in source reading; exact unchanged artifact pins now remain valid, while
changed or unpinned stale results still reject.

The broad gate passed 545 pytest tests and 130 BDD scenarios (699 steps). Final
reader/UI focused tests and installed proof are recorded in the
[checkpoint diary](../diary/2026-10-16-readable-flight-and-native-connections.md).
Remaining work includes version-balanced intake, clearer native district labels,
and real voice/expert/captain journeys. The full goal is not complete.

## Scoped flight and version coverage checkpoint — October 16

Automatic intake now uses native version families to share the bounded code
budget; live v34 has 49 retained files including 46 Python files. District names
come from actual module/file members, preserving IDs and positions. Both search
paths carry exact source pins and separate retrieval/harvest fingerprints.

The procedural Navigator resolves `find QUERY in PLACE` and `fly to PLACE then
find QUERY` before source search. Ambiguity is explicit; missing places never
widen to global. CLI/API proof preceded UI. Real browser tests preserve scope,
query and viewpoint through choices, travel, Back and reload. Pending results
cannot undo Clear; paging retains the original scope after checkbox changes.

581 pytest tests and 130 BDD scenarios (699 steps) passed. The offline local wheel
was installed and all 36 runtime files match checkout/wheel/installation bytes.
See [the checkpoint diary](../diary/2026-10-16-scoped-flight-and-version-coverage.md).
Real voice capture, expert replies and captain takeover remain unverified. The
full goal is still active; no external release was made.

## Landing and carried-context checkpoint — October 16

`atlas files` and `atlas context` are shared CLI/web services. A landing can list
retained code/docs and open pinned source. A ship can list/search/read carried
history through the installed native reader, with catalog continuity and separate
handover reading. Browser Back/reload, stale responses and focus are covered.
Native dependency evidence prevents bundled libraries from becoming extra product
planets. General numbered-experiment destination aliases accept spoken wording
without rewriting content queries or resolving genuine ambiguity.

641 pytest tests and 130 BDD scenarios passed; the final controller, alias and
file gate passed another focused 41 tests. The local offline install was verified
across 38 runtime and nine asset/license files. Installed CLI source reading,
carried search and natural experiment navigation passed; the real browser proved
flight, landing, filtered files, source reading and carried-context behavior.
See [the checkpoint diary](../diary/2026-10-16-land-and-read-carried-context.md).

Next: native discovery of separate local commission archives, broader coverage,
and real microphone/expert/captain journeys. Remote records remain remote; no
manual inventory sync or external release occurred. The full goal remains active.

## Stored ship copies and submodule coverage checkpoint — October 16

Native commission evidence now discovers separate local archives through a
bounded, cached Starship observer. Ship/product links and an explicit galaxy
catalog make their carried context reachable without crowding the conceptual
map. CLI proof preceded UI; real archive search, exact-turn reading, Back/reload,
remote-copy distinction and archive boarding refusal passed. Ordinary browsing
uses the chart cache, and copied CLI commands retain their selected caches.

Native Git ownership now isolates submodule ignore checks. The real EXP32 CLI
harvest retained 448 bounded files, then reused its cache. Both Starforge search
paths recovered an engine laboratory file. The installed live source was updated
through the same command; no manually maintained inventory or copying was used.

684 regression tests and 130 CLI scenarios passed, followed by 36 focused checks
for final review fixes. The local wheel and all 48 runtime/asset files were
verified. The existing flight deck session and viewpoint were retained.
See [the checkpoint diary](../diary/2026-10-16-stored-ships-and-native-submodules.md).

The final normal continuation published the current harvest at 259/294 intake
projects. A real EXP32 search also caught an abbreviation collision with a
path-derived district label; the generic resolver fix retains exact-name and
multi-experiment ambiguity. Another 43 focused navigation checks passed before
the local installed deck was updated.

Next gaps: viable chart-publication time in busy intake batches, clearer carried
session labels and Navigator cargo search, broader source coverage, and real
voice/expert/captain journeys. The full objective remains active.

## Carried search and chart publication checkpoint — October 16

The shared Navigator can search allowed ship cargo through Starship's installed
native reader. Exact ship selection stays exact; product links use recorded
source-context associations, and district searches do not inherit product cargo.
Hits preserve the physical copy, session, original turn and catalog SHA. Private
caches validate catalog, record metadata and reader identity, retain zero-hit
results and advance bounded repeated searches through remaining ships. Remote
paths are never probed locally, and no captain action is part of search.

The real inventory has 13 readable local carried catalogs, 107 remote ship
records and nine local archives missing the public catalog; no real copy hit a
byte-size limit. All 13 cached searches repeated in 0.029 seconds without native
calls. The public CBT CLI journey returned 12 hits in 0.1523 seconds fresh and
0.0034 seconds warm, then reopened original turn 2 with the same catalog SHA.

Deferred chart publication now runs before another intake batch, preserving the
pinned queue and Pause. Measured publication time controls later phase budgets;
intake and publication alternate when both cannot fit. The isolated public CLI
proved pending publication → publication at the same cursor → completed two-job
intake and publication. The scheduler's exact commands, timings and cancellation
proof are in [/tmp/navcom-chart-budget-e2e/report.md](/tmp/navcom-chart-budget-e2e/report.md).

The current full regression gate passed **732 tests in 172.19 seconds**. Browser
proof and local installation for this continuation remain **pending**; see
[the checkpoint diary](../diary/2026-10-16-search-carried-context-and-publish-charts.md).
The full goal remains active, including broader evidence coverage and real
microphone/expert/captain journeys. No external release was made.

Installed follow-through: real typed archive search returned 37 carried passages;
opening native turn 2, reloading its catalog pin, and Back to the cached search
passed. A review fix rejects missing pins/turns (28 further focused tests). The
offline wheel is installed and all 49 runtime/asset files match. Installed CLI
cache replay and pinned reading passed; the idle deck server retained its session,
port and the captain's existing viewpoint. The user now has the flight deck open.
The full goal remains active.

## Flight room and normal launch checkpoint — October 16

The flight chart now retains usable room and visible zoom controls on narrow and
short screens. Native conversation-family evidence includes exact child keys and
matching turns; expandable child cards keep parent reading distinct and return
to the same search. No ancestry is inferred for older unlinked chats.

A bounded shared Atlas metadata cache preserves request scope and validates
connection provenance across replaced indexes. The installed EXP32 HTTP query
returned 13 families in 1.404 seconds, then 0.687 seconds. The full gate passed
784 tests, followed by 59 checks for the final cache fix and independent review.
All 50 installed runtime/asset files match the tested checkout.

The default chart was built by the ordinary CLI, with no cache copying or custom
environment: eight systems, 245 planets and 232 moons. The real default menu flew
into Syra and back while its normal native harvest continued with visible
progress. Wider source coverage and the actual microphone/expert/captain journeys
remain open. See [the flight checkpoint](../diary/2026-10-16-flight-room-and-conversation-families.md).

## Readable overview and spoken course checkpoint — October 16

Fit now uses full 13px labels with bounded collision placement. Historical names
and selected beacons follow the active dated evidence; failed loads hide stale
labels. The installed desktop chart shows all ten names. Narrow charts use the
selected destination panel when names cannot all fit, without changing geography.

Compound flight/search reuses the exact resolved evidence and publication, saving
one retrieval. An actual existing local Whisper test produced “Fly to experiment
32, then find matrix.” General command punctuation handling fixed that journey;
installed CLI and browser both reach EXP32 and its 13 conversation families.
The full gate passed 834 tests, with 47 focused tests and independent review for
the final historical/empty-state corrections. All 50 installed files match.

Normal tool-driven intake published 1,148 destinations from 94 sources and 9,551
saved files. The installed menu continued its bounded queue in the background.
No catalog was copied by hand. Real microphone capture, expert reply and captain
takeover remain open; the goal is still active. See
[the checkpoint diary](../diary/2026-10-16-overview-labels-and-spoken-courses.md).

## Product clues and pinned history checkpoint — October 16

Default tool-driven intake completed 294/294 jobs: 147 sources, 10,807 retained
files and 1,225 destinations. Its 147 omissions are disclosed, with no failed
jobs or pending chart publication. Seven oversized conversation logs remain for
normal upkeep. The real CarePlus journey opened harvested code and an original
conversation turn, then returned to the same scoped question. Missing local Git
HEAD prevented a separate historical recovery and was reported explicitly.

Description selection now preserves owner declarations and prefers exact-scope
harvested README prose over component package metadata, with provenance and
unchanged identities. Historical route state and copied links retain the native
session cursor; Reload/Back/fresh-link tests reject silent repinning or mismatched
sessions. The final gate passed 852 tests in 198.31 seconds, followed by clear
independent review.

The frozen wheel is installed offline; all 50 packaged files match. The ordinary
installed refresh republished the default chart, and installed CLI/browser checks
confirmed CarePlus's retained README description. The three observed idle decks
retained their origins, sessions and cache settings during guarded restarts. The
galaxy is open for the user. The follow-through below supersedes the originally
pending installed-browser dated-pin proof. The full goal stays active, including microphone,
approved expert reply and captain takeover. See
[the diary](../diary/2026-10-16-product-clues-and-pinned-history.md).

## Dated navigation and larger pinned recovery checkpoint — October 16

The installed browser now preserves the exact Syra cutoff/session across reload,
paging, committed source reading, Return to present and Back. The separate dated
conversation reader opens an original pre-cutoff turn and returns to that pin.
Shared bounded chart reading fixes large-chart rejection; exact-scope committed
authored names replace synthetic snapshot labels, leaving absent names unknown.

An explicit CLI/API recovery now increases only the snapshot file/total-byte
bounds to the existing native 10,000-file / 64 MiB limits. It derives a separate
immutable session with the same date, repository heads, scopes and positions;
validated successes are reused. The real pinned Syra command recovered B2B's
2,069 files and the mobile application's 190 files at original commit
`1325eaa77fed0521f58317fa191ebf2f82756be6`, reusing ten repositories in about ten
seconds. Disclosed unknowns and native exclusions remain. The installed UI recovery button passed: mobile sign-in source at the original
commit, close reader, Back to the old limited view, Forward to recovery and reload
all retained the expected pin and selection. The final regression passed 892
tests; all 50 installed runtime/assets match the offline wheel and checkout.
No alternate classifier, hand catalog synchronization or other-repo change was
needed. See the [updated diary](../diary/2026-10-16-product-clues-and-pinned-history.md).
