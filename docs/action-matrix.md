# Action matrix: every place kind × verb, as built

The Galactic bridge offers each place's actions in one **action rail** in the inspector.
Each rail action makes exactly one existing API call and shows, beside its button, the
service's own copyable `navcom …` command for it. The view fills only documented
`<placeholders>` (`<query>`, `<question>`, `<commit>`, `<YYYY-MM-DD>`) with what you typed,
and never adds options of its own ([architecture](architecture.md)). Where a response
carries its own exact command (`cli_command`, `continue_command`, `land_command`,
`next_command`), the panel shows that one after the call. A conversation's `open_command` is
shown as the *nearest terminal read*: `GET /api/session` has no CLI twin.

Consequential actions never run from the rail or a card. They open their review dialog first:
Ask expert, Board ship, Resume…, and Fresh agent… all read the exact command before a
second, explicit button launches it.

The rail is the one place for a place's actions. The arrival state (*You've arrived*) points at
it instead of repeating its buttons, and **Explore time** lives in the time bar above the chart
(its command is under *More CLI commands* until the bar is open). Every rail click rebuilds the
inspector, but an open panel whose request did not change shows the answer (or failure) it
already has: only the panel whose input changed calls its route again, and each failure's
*Try again* / *Check again* button is what asks again. Keyboard focus stays on the rail action
that was pressed. Reading a conversation from the bridge uses `GET /api/session` only; it
never writes the Library's saved view (`POST /api/state`). A copied journey link carries the
camera ([landing contract](historical-landing-contract.md)).

How to read the tables:

- **Built**: rail label (or where else it lives) → route → command key in `node.commands`,
  or the response field that carries the command.
- **N/A**: the service rejects this kind, or the verb has no meaning for it. The reason is given.
- **Built (no CLI twin)**: built on a route that `tests/test_architecture.py` tags `cli-gap:`. A command shown
  beside it is labeled as the nearest terminal equivalent, never as its twin.
- **Candidate**: wanted, but no CLI does it today. See [CLI concept candidates](cli-concept-candidates.md).

A command the rail does not use stays visible under **More CLI commands for this place**
at the bottom of the inspector: `show` (the inspector itself), `search` (the evidence replay
behind *Search this place*), the center's own `explore` (the chart on screen), `history_system`
(the time bar's own command; for a place that is not the center, fly there first), and for a
place that is not the center its `navigate`.

## Galaxy (`galaxy:owner`, always the center)

| Verb | Status | Where → route → command |
|---|---|---|
| explore | Built | ⌂ Galaxy / breadcrumb → `GET /api/space?action=explore` → `explore` |
| show | Built | The inspector itself (the explore response carries this entity) → `show` |
| list | Built | **List places** (systems, products, experiments, districts, experts, starbases, ships) → `GET /api/space?action=list&kind=…&within=galaxy:owner` → `list[]`; the panel then shows the response `cli_command` |
| list (stored copies) | Built | **Stored ship copies** catalog (from the explore response) → `stored_copies`; *List places → Ships* makes the call |
| navigate | Built | **Search this place** → `GET /api/navigate` → `navigate` (`<query>` = the Navigator's words, live) |
| search (evidence) | Built | Navigator replay on Back, reload or paging → `GET /api/space?action=search&evidence=1` → `search`; results show the response `cli_command` |
| related | Built | **Connections & versions** → `GET /api/space/related` → `related` |
| sources search | Built | **Search harvested sources** → `GET /api/sources/search?within=SOURCE[&path=…]` → `source_search[]` (one per source) |
| conversation collections | Built | **Conversations here** → `GET /api/atlas?action=explore` (newest first), then `action=search` → `conversation_search[]`. One collection per read: the panel names it from the response (`effective_scope.label`), says *collection i of N* and the place's total, and shows the response `cli_command`. Typed words fill the line's `<query>` as you type; a collection whose command has no `<query>` gets no words box. Naming every collection up front, or one read across all of them, is a [candidate](cli-concept-candidates.md#from-the-place-and-conversation-action-matrix) |
| history conversations | Built | **Conversations by date** → `GET /api/history/conversations` → `history_conversations` (`<YYYY-MM-DD>` = chosen date) previews the date; after the read the line is the response `cli_command` (with `--query` when words were given) |
| history system | Built | Time bar **Explore time** (above the chart); *Explore this time* → `POST /api/history/system` → `history_system` (`<YYYY-MM-DD>` = chosen UTC time) |
| sources list | Built | **Harvested sources** → `GET /api/sources` → `sources_list` |
| refresh chart | Built | Header **↻ Refresh chart** → `POST /api/space/refresh`. No command is listed: services never list refresh commands; it follows review |
| pause refresh | Built (exempt by design) | Header **Pause** → `POST /api/space/refresh/pause`, tagged `view-state` in `ROUTES`. A CLI pause is a [candidate](cli-concept-candidates.md#from-the-place-and-conversation-action-matrix) |
| upkeep | Built | Library header **Run upkeep** → `POST /api/upkeep` (`navcom --maintain`); not place-scoped |
| inspect, files, history timeline | N/A | `navigation.inspect`, `place_files.files` and `history.resolve_place` reject the galaxy; use history system |
| resume / recap newest here | Candidate | [A place's conversations as one list](cli-concept-candidates.md#from-the-place-and-conversation-action-matrix) |

## Solar system

| Verb | Status | Where → route → command |
|---|---|---|
| explore | Built | **Fly to …** → `GET /api/space?action=explore` → `explore` |
| show | Built | Inspector → `show` |
| list | Built | **List places** (products, experiments, districts) → `GET /api/space?action=list` → `list[]` |
| navigate | Built | **Search this place** (center) → `GET /api/navigate` → `navigate` |
| search (evidence) | Built | Navigator replay → `search` |
| related | Built | **Connections & versions** → `related` |
| sources search | Built | **Search harvested sources** → `source_search[]` |
| conversation collections | Built | **Conversations here** → `conversation_search[]` (a choice per collection) |
| history conversations | Built | **Conversations by date** → `history_conversations` |
| history system | Built | Time bar **Explore time** (center) → `POST /api/history/system` → `history_system`; a system that is not the center lists it under More CLI commands |
| inspect, files, history timeline | N/A | Rejected by the services for systems |
| resume newest here | Candidate | Collections intersect; see candidates |

## Product planet

| Verb | Status | Where → route → command |
|---|---|---|
| explore | Built | **Fly to …** → `explore` |
| show | Built | Inspector → `show` |
| list | Built | **List places** (experiments, districts) → `list[]` |
| navigate / search | Built | **Search this place** (center) → `navigate`; replay → `search` |
| inspect | Built | **Inspect code locations** (when locations are recorded) → `GET /api/space/inspect` → `inspect` |
| inspect --refresh | Built | Dossier **↻ Refresh locations** → `GET /api/space/inspect?refresh=1` → `inspect_refresh` |
| files | Built | **Browse saved files** → `GET /api/space/files` → `files`; the panel shows the response `cli_command` |
| related | Built | **Connections & versions** → `related`; the panel shows the response `cli_command` |
| history timeline | Built | **Check history** → `GET /api/history` → `history_timeline`; the panel shows the response `cli_command` |
| history timeline --repo | Built | When the place has several Git copies, the history panel lists them; choosing one → `GET /api/history?repo=ROOT`, whose `cli_command` carries `--repo`. *Choose another Git copy* lists them again |
| history explore | Built | A commit in the trail → `POST /api/history/explore` → `history_explore` (`<commit>`); the revision shows the response `cli_command`, with `--query` after *Search revision* |
| history explore --repo | Built | A commit in a chosen copy's trail → `POST /api/history/explore {…, repo}` → the revision shows the response `cli_command` (with `--repo`). Back and reload reopen the saved revision of that copy |
| history conversations | Built | **Conversations by date** → `history_conversations` |
| sources search | Built | **Search harvested sources** → `source_search[]` |
| conversation collections | Built | **Conversations here** → `conversation_search[]` |
| history system | N/A | Needs a galaxy or system center |
| board | N/A | Ships only |
| resume / recap newest here, fresh agent here | Candidate | See candidates |

## Experiment moon

Same as the product planet: **Fly to**, **Inspect code locations** (+ refresh), **Browse saved files**,
**Check history** (+ commit explore, also in a chosen Git copy), **Connections & versions**, **Search harvested sources**,
**Conversations here** (when it has collections), **Conversations by date**, **List places** (districts).
History system and board are N/A; resume newest and fresh agent here are candidates.

## District (code area)

| Verb | Status | Where → route → command |
|---|---|---|
| explore | Built | **Land in district →** → `explore`; at the district its saved files open automatically |
| show | Built | Inspector → `show` |
| navigate / search | Built | **Search this place** (center) → `navigate`; replay → `search` (conversations shown are the product's, marked *unproven*) |
| files | Built | **Browse saved files** → `files` |
| related | Built | **Connections & versions** → `related` |
| history timeline / explore | Built | **Check history** → `history_timeline`; commit → `history_explore` |
| history conversations | Built | **Conversations by date** → `history_conversations` |
| sources search | Built | **Search harvested sources** → `source_search[]` (the district's exact `--path` files) |
| conversation collections | Built | **Conversations here** → the product's collections, searched with the service's suggested query (the command has no `<query>`, so the panel has no words box and names the words it used), labeled *relationship unproven* |
| inspect | N/A | Code areas carry no locations; the service lists no `inspect` command |
| list | N/A | Districts have no listed children |
| resume newest here | Candidate | Would fall back to the product's conversations |

## Lab application (`kind: district, form: application`)

**Enter lab application →** (`explore`), **Inspect code locations** (+ refresh; `inspect`, `inspect_refresh`),
**Browse saved files** (`files`), **Check history** (`history_timeline`, commit `history_explore`),
**Connections & versions** (`related`), **Search harvested sources** (`source_search[]`),
**Conversations by date** (`history_conversations`); show in the inspector, navigate at the center.
Fresh agent here and resume newest here are candidates.

## Expertise star

| Verb | Status | Where → route → command |
|---|---|---|
| explore | Built | **Fly to …** → `explore` |
| navigate | Built | **Search this place** (center) → `navigate` |
| inspect | Built | **Inspect expert** → `GET /api/space/inspect` → `inspect` |
| inspect --refresh / --observe | Built | Dossier **↻ Refresh declaration** → `inspect_refresh`; **Observe status** → `inspect_observe` |
| ask (prepare) | Built | **Ask expert** → review dialog; *Review question* → `POST /api/space/ask` (`launch: false`) → `ask` (`<question>` = your question, live) |
| ask (launch) | Built | *Open question in Hermes →* → `POST /api/space/ask` (`launch: true`, review token). Only after the review |
| related | Built | **Connections & versions** (when it has sources) → `related` |
| history timeline / explore | Built | **Check history** → `history_timeline`; commit → `history_explore` (stars were not offered history before) |
| history conversations | Built | **Conversations by date** → `history_conversations` (related products' conversations; unproven) |
| sources search | Built | **Search harvested sources** → `source_search[]` |
| files | Candidate | [Browse retained files under an expert's scope](cli-concept-candidates.md) (`atlas files` rejects stars) |
| board, carried context | N/A | Ships only |

## Starbase

**Fly to …** (`explore`), **List places** (ships; `list[]`), **Search this place** at the center (`navigate`),
show in the inspector. Inspect is a [candidate](cli-concept-candidates.md) (no starbase branch);
history and files are N/A (no locations or source scopes).

## Working ship

| Verb | Status | Where → route → command |
|---|---|---|
| explore | Built | **Fly to …** → `explore` |
| board (check) | Built | **Board ship** → review dialog; *Check captain route* → `POST /api/space/board` (`validate: true`) → `board_validate` |
| board (launch) | Built | *Open captain in terminal →* → `POST /api/space/board` (`launch: true`, review fingerprint). Only after the check |
| inspect / --refresh | Built | **Inspect ship** → `inspect`; dossier **↻ Refresh observation** → `inspect_refresh` |
| carried context | Built | **Read carried context** → `GET /api/space/context` → `carried_context` |
| carried search | Built | Carried panel *Search context* → `action=search` → `carried_search` (`<query>`, live) |
| handover | Built | Carried panel *Handover* → `action=handover` → `handover`; the panel shows the exact `cli_command` |
| stored copies | Built | **Ships & stored context** (ship links) → fly to each copy |
| navigate | Built | **Search this place** (center) → `navigate` (searches carried context) |
| inspect --observe, history, files, resume | N/A | Raised for ships, no locations or scopes, not an indexed conversation (board is the captain analog) |

## Ship archive (`kind: ship, form: archive`)

**Fly to …** (`explore`), **Inspect archive** (+ refresh), **Read carried context** (search, handover),
**Search this place** at the center, and the working ship through its link. Board is N/A
(archives cannot board). Recap or revive of a carried session is a
[candidate](cli-concept-candidates.md).

## Conversation (cards in search results, Conversations here, and dated lists)

| Verb | Status | Where → route → command |
|---|---|---|
| open | Built (no CLI twin) | **Read conversation →** → `GET /api/session?key&start`, a [route with no CLI twin](cli-concept-candidates.md#web-routes-with-no-cli-twin) (80-turn window). The card shows `open_command` (`navcom --open REF:TURN`) labeled *Nearest terminal read*: it shows a shorter window around the turn |
| recap | Built | **Recap** → `GET /api/recap?key` → no command emitted ([candidate](cli-concept-candidates.md#command-strings-the-services-do-not-emit-yet)); *Copy recap* copies the context pack |
| resume (original) | Built | **Resume…** → review: `GET /api/plan?key` shows the exact native command → *Resume in a new tab →* → `POST /api/launch {key}` |
| resume --print | Built | The review itself is the `--print` plan (`GET /api/plan`) |
| resume --with HARNESS | Built | **Fresh agent…** → `GET /api/harnesses?provider` → `GET /api/plan?key&harness` → *Start fresh … in a new tab →* → `POST /api/launch {key, harness}` |
| search inside | Built | **Search inside** → `GET /api/session/search?key&q` (the JSON of `navcom WORDS --file REF --json`); each hit opens its turn; the result's own `recap` command is shown |
| show (family) | Built | **Family** → `GET /api/atlas?action=show&ref` → `next_command` (`navcom atlas show REF`) |
| tree | Built | *Show the whole family tree* → `GET /api/atlas?action=tree&ref` → response `cli_command` |
| restore, summarize | N/A here | Consequential with no route by design ([architecture](architecture.md#every-route-has-a-cli-twin)); a launch restores an archived transcript in its pre-flight |
| annotate, suggest title | Candidate | Library only (`POST /api/annotation`, `/api/suggest`); see candidates |

## Conversation turn

| Verb | Status | Where → route → command |
|---|---|---|
| open at turn | Built (no CLI twin) | **Read … →** with the matched turn → `GET /api/session?start=N`; `open_command` (`REF:N`) is shown as the nearest terminal read, not a twin |
| fresh agent focused on a turn | Built | **Fresh agent from turn N…** → `GET /api/plan?…&turn=N`, then `POST /api/launch {…, turn}` (`navcom --resume REF:N --with H`) |
| dated passage | Built | **Read dated passage** (no call), then *Open current conversation →* → `GET /api/session` |

## Carried turn (inside a ship's snapshot)

Read original turn → `GET /api/space/context?action=open` → the hit's `open_command` / panel `cli_command`.
Open and resume are N/A: carried sessions are ship snapshots, not NavCom index keys.

## Harvested source file

| Verb | Status | Where → route → command |
|---|---|---|
| read | Built | **Open source → / Read file →** → `GET /api/source` → response `cli_command` |
| find in this file | Built | Reader **Find in this file** → `GET /api/sources/search?within&path&mode=text`; each line jumps the reader. No command emitted ([candidate](cli-concept-candidates.md#command-strings-the-services-do-not-emit-yet)) |
| file history | Candidate | [History of one harvested file](cli-concept-candidates.md#from-the-cockpit-action-rail) |

A pinned Git file reads at its commit (`GET /api/source?history=…`); the reader names the
commit date when the response carries one and otherwise says *captured* with the snapshot's
capture time. Find is not offered there: source search reads the current harvest, not the pin.

## Conversation collection

Explore (newest first) and search are built in **Conversations here** (`GET /api/atlas`, response
`cli_command`; template `conversation_search[]`). Source discovery (`sources discover --harvest`)
is N/A: consequential with no route by design.

## Dated views

| Kind | Verb | Where → route → command |
|---|---|---|
| Git revision | explore, --query | Commit trail and *Search revision* → `POST /api/history/explore` → response `cli_command` |
| Dated system | system, continue, retry larger | Time bar → `POST /api/history/system` → `cli_command`; *Continue remaining repositories* → `continue_command`; *Retry limited histories* → `retry_larger_command` |
| Dated system | conversations | *Conversations by this time* → `GET /api/history/conversations` → response `cli_command`, shown above the list |
| Dated product | land, --query | **Fly to this dated product →** → `POST /api/history/land` → `land_command`; a search shows the landing's `cli_command` |
| Dated product | current destination | *Open current product →* → `GET /api/space?action=explore` |
| Dated district | land --group | **Land in this dated district →** → `land_command` |
| Dated district | resume | N/A: conversations are not attributed to commits |
