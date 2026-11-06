# October 17 — Ask for the experiments, fly, and return

The preceding turn repaired the basic matcher so identical commands in different
conversations remain separate results. That installed fix and the unresolved
original ThriveCart transcript gap remain recorded in the
[basic-search diary](2026-10-16-basic-solve2-search.md).

This turn closes a concrete promise from the
[owner's spatial diary](2026-10-15-a-universe-you-can-return-to.md): “show the
experiments” and “take me back” refer to the place currently being explored.
Previously the first phrase became a literal source/conversation search, even
though `atlas list moons` already provided the required operation.

## Chosen behavior

- Exact `show/list [me] [the] KIND` requests use the existing cached place list.
  Products map to planets, experiments to moons, and districts to cities.
  Systems/solar systems, stars, starbases and ships work too. Longer sentences,
  quoted text and paths retain their existing search behavior.
- The selected scope stays exact. Global is an explicit choice. Empty lists
  stay empty; they never fall back to another place or evidence search.
- `take me back` uses the existing Back action. The CLI describes the request;
  it does not pretend to move a shell or control browser history itself.
- Browser listings expose the same nodes/counts and the canonical CLI command.
  Listing does not rearrange the chart. The user chooses a Fly action to move.
  Scope, kind, page and camera survive Back, reload and copied links.
- No source harvest, model or conversation query runs for a listing. No new
  endpoint, library, catalog or cache was introduced. Pagination uses the
  existing `/api/space?action=list` and `atlas list` paths.

The implementation uses one catalog publication through scope resolution and
listing. Page changes reject mismatched publications/scopes rather than mixing
results. Typed-list metadata is emitted only when a kind was requested; the
legacy untyped direct-child API is not relabeled as a typed list.

## Evidence

CLI first: the installed command below returned 27 Syra experiments. Following
its returned `atlas list moons ... --offset 4` command produced the next four
distinct experiments within the same system.

```sh
navcom atlas navigate "show the experiments" \
  --within system:9b1f5d1b7914f7de9de3 \
  --space-cache /tmp/navcom-galaxy/space.json \
  --source-cache /tmp/navcom-galaxy/sources --limit 4 --json
```

The real browser journey then proved:

1. Type “show the experiments” in Syra: 27 experiments; chart node styles remain
   unchanged and the camera remains `0.3958_0_0`.
2. Fly to decision-engine. Type “take me back”: the exact original listing URL,
   scope, query and camera return. Reload restores that same listing.
3. Uncheck local scope and repeat: 237 experiments across the galaxy. More
   reaches 41–80; reload preserves page two; Back restores page one. The chart
   remains at Syra throughout these list operations.
4. Open the saved local-list URL in a fresh tab: query, scope, list and camera
   restore without relying on that tab's history state.
5. At 390×844, the list, full wrapped paths and Fly controls remain usable with
   document width equal to the viewport. Captured browser error logs were empty.

Those counts describe the observed published chart, not hard-coded fixtures.
Automatic intake continued during browsing; no catalog was hand-synchronized.

The first screenshot exposed duplicated instructions above the list. The final
layout has one meaningful heading and one CLI command, with count/scope in the
existing status line. Screenshots:

![Experiments listed beside the unchanged system](evidence/2026-10-17-navigator-experiment-list.png)

[Narrow-screen proof](evidence/2026-10-17-navigator-experiment-list-narrow.png)

Verification: 118 intent tests; six listing/service/CLI tests; the catalog-cache
gate; 161 navigation/architecture tests; 63 focused UI continuity tests. The
final compact-render adjustment passed its 13 affected UI tests. JavaScript
syntax and whitespace checks passed. Installed CLI receipt:
`/tmp/navcom-installed-listing-cli.json`.

## Current runtime and remaining work

Local version remains 0.11.0. Final installed wheel:
`/tmp/navcom-listing-compact-dist/navcom-0.11.0-py3-none-any.whl`.
Bridge: `http://127.0.0.1:62550/`, PID 41449, exec session 11747, running
`/tmp/navcom-listing-restart.py`. Verify identity before any later restart.
The final compact change was JavaScript only, so it needed reload, not another
server restart. No PyPI publication, microphone capture, expert question or
captain relaunch occurred.

The full goal remains active. Product succession/identity needs authoritative
evidence distinct from name-family and similarity suggestions. Existing
Starforge lineage and Starship commissioning provenance do not settle which
product the owner considers a replacement. Live microphone acceptance and
visible captain takeover also remain open. Use the
[active implementation plan](../docs/galactic-implementation-plan.md) and
[arrival handoff](2026-10-17-arrival-workspaces-and-historical-applications.md)
for the already-proven journeys; do not repeat them merely to produce more notes.
