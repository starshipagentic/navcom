# Search carried context and publish charts — October 16

The previous goal turn made progress: native archive discovery, submodule intake,
installed flight/search proof, and the source-reader return race changed and
verified the working product. The full galactic objective remains active.

## Small stepwise plan

1. Repair the chart scheduler so a saved publication obligation cannot be
   starved by another intake batch. Preserve the native queue and cancellation.
2. Federate carried-context search through Starship's installed reader, with
   bounded work and caches keyed to the actual catalog, records and reader.
3. Prove exact scope, physical identity, cached reuse and original-turn CLI
   replay before exposing those same results in the Navigator.
4. Test typed search → ship passage → Back in a separate browser, then install
   the verified local build without changing the captain's open viewpoint.

## Decisions and boundaries

- NavCom orchestrates the existing tools. It does not copy a separate search
  algorithm or maintain a hand-edited ship inventory.
- Exact ship searches mean that physical copy. Product associations use only
  saved native source-context links and their recorded archive copies. District
  searches do not silently inherit broader product cargo.
- Carried passages stay distinct from current host history and source evidence.
  Empty native titles use explicitly labeled verbatim excerpts; no invented
  title, conversation date, ownership or captain readiness.
- No external publishing, captain launch, expert message, restoration, or edits
  in Starship/Starforge. Real microphone, expert-response and captain takeover
  proof remain separate unresolved requirements.

## CLI and regression proof

The current complete regression suite passed **732 tests in 172.19 seconds**.
Carried search also passed its focused native-reader and independent review
gates, including termination of both the bounded wrapper and its native child.

Navigator cargo search now delegates matching to the installed Starship reader.
Every passage retains its exact physical ship, session, original turn index and
catalog SHA. Cache validation reads the public catalog and no-follow record
metadata, with the installed reader identity; fresh native reads validate the
dialogue hashes. Changed, missing or redirected records cannot replay old hits.
Private query caches include zero-hit results. Repeating a bounded search moves
on to unsearched ships instead of repeatedly paying for the first ships.

On the real tool-generated chart, **13 local archives had readable carried
catalogs**. The other **107 ship records were remote**, and **nine local archives
lacked the public catalog**; none of these real copies exceeded the byte limit.
The service searched eight readable archives in 1.20 seconds, the remaining five
in 0.83 seconds on repeat, then reused all 13 in 0.029 seconds with no native
calls. These are bounded first pages, with omitted matches reported explicitly.
Remote records were not probed locally or substituted with an archive.

The public CLI's real CBT search returned **12 hits in 0.1523 seconds fresh and
0.0034 seconds warm**. Its returned reference reopened original **turn 2** through
the native reader with the exact same catalog SHA. The service proof and CLI
replay used existing tool-produced inventory, not manually synchronized catalogs.

Chart publication now gets a dedicated continuation when it was deferred or
failed. It preserves the pinned intake cursor and explicit Pause. Measured
publication time reserves enough of later passes; when a full native job and
publication cannot both fit, intake and publication alternate rather than
starving one another. In the isolated public CLI fixture, an initial one-second
budget stopped with publication pending at cursor 0/2; the next continuation
published without moving that cursor, and the next completed both projects and
publication. The three invocations took 0.451, 0.477 and 1.182 seconds. The native
parser/index and refresh commands produced all state automatically. Exact argv,
JSON and the longer-budget/cancellation fixtures are recorded in
[/tmp/navcom-chart-budget-e2e/report.md](/tmp/navcom-chart-budget-e2e/report.md).

## Remaining for this checkpoint

The typed Navigator → carried passage → Back browser proof and installation of
this continuation are **pending**. The root task will record those outcomes after
verification. The full galactic goal remains active: broader coverage and real
microphone, expert response and visible captain takeover are still separate gaps.

## Installed flight-deck proof

- Real browser typing `find context in cbt-origins` selects the recorded working
  ship and honestly reports that remote copy unavailable. Selecting its separate
  local archive and typing `context` returns 37 native carried passages.
- Clicking original turn 2 opens session `fb390fd668c2fdc50d57a874` in the exact
  archive with its catalog pin. Reload preserves the pin; Back restores the query,
  archive scope and 37 matches, now from cache.
- Peer review caught matching-but-missing pins/turns; validation now rejects them
  while preserving turn zero. Another 28 focused tests and JS syntax passed.
- Offline wheel installed locally. All 49 runtime/asset files match checkout,
  wheel and installation. Installed CLI returns 12 bounded hits, zero native
  calls on cache reuse (0.003 seconds), and reopens the same pinned turn 2.
- The idle live server was replaced on port 62811 retaining its session token.
  Existing flight views were not reloaded or moved. A separate installed-browser
  check opens the same pinned turn; the temporary test server and tab were closed.
- Opened the live galaxy for the captain in Codex and a full browser tab.
  Evidence: `/tmp/navcom-carried-installed-proof.json`,
  `/tmp/navcom-carried-reader-installed.jpg`, `/tmp/navcom-flight-deck-open.jpg`.

The browser's ordinary intake continued automatically and saved its own cursor
when its two-minute budget expired; no manual inventory or catalog syncing.
This turn is progress, not completion of the full galactic goal. Real microphone,
expert response and captain takeover proof remain unresolved.
