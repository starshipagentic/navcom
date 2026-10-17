# October 16, 2026 — Services hold the law: no paint in the data, one path resolver

**Pain:** the owner asked whether Atlas/Starship/web were "bleeding into each
other". A read-only audit of all 34 web routes and every service said: mostly
clean, but with real leaks.
- Services painted the map: `color` hex in `navcom_atlas`/`navcom_discovery`, and
  `art_role` sprite names in `navcom_fleet`, `navcom_commission_archives` and
  the chart cache.
- The history-cache path was hand-derived 8–9 times across the web and CLI.
- The web adapter owned a chart-refresh driver the CLI could not reach.
- Six modules raced macOS `killpg` (EPERM on zombie process groups), and one of
  them failed a test at baseline.

## Summary

- **Presentation out of services.**
  - `color` is gone from service output, and `navcom_atlas.js` derives its own
    tint.
  - `art_role` is gone from fleet, archives and the chart copy;
    `navcom_space.load_catalog()` (now the one chart read path) strips it from
    charts published earlier.
  - The view picks sprites from `kind`/`form` (an archive is
    `kind: ship, form: archive`).
- **One cache-path resolver:** `navcom_navigation.history_cache(index)` beside
  `paths()`. The CLI and service sites use it. The web sites followed in round 2.
- **Service-owned CLI syntax for the cockpit.** Every chart node's `commands` now
  lists the exact `navcom …` argv for each read-only or review-first verb its
  kind accepts: explore, show, search, navigate, files, related, inspect (with
  `--refresh`/`--observe`), history timeline/explore/system/conversations,
  ship context/handover/board `--validate`, ask, source and conversation search,
  stored copies, sources list.
  - Commands are rebuilt on read, so older charts get them too.
  - They are pinned to the caches in use. That pinning fixed a latent bug:
    `sources search` commands used to carry `--index`, which that command rejects.
  - The view fills documented `<placeholders>` and never writes CLI syntax itself.
- **One refresh driver:** `navcom_chart_refresh.drive()` holds the multi-pass
  loop (slices, `stop_reason='time_budget'`, cancel, progress). The CLI calls it
  with `passes=1`, so its behavior is unchanged; the bridge runs 120 s in 60 s
  slices.
- **One tolerant `navcom_space.kill_group()`** replaced the unguarded `killpg` at
  six sites, which fixed the baseline `test_star_chat` failure.
- **The dated-conversation service builds its own replay `cli_command`,** so API
  responses carry it too.
- **Help no longer imports the discovery/navigation stack.** All 102 help pages
  are byte-identical to HEAD.
- **Proven-dead or duplicated code removed:** `resolve_destination`,
  never-passed parameters (refresh `max_roots`/`max_boundaries` became module
  constants), one `source_id()`, one `worker_argv()`, one call-time
  `commission_tools()`, `in_scopes()`, `subtree()`, `load_catalog()`, public
  `position()`, and CLI-only routing (`KINDS`/`PREFIXES`/`is_spatial`) moved into
  `navcom_atlas_cli`.
- **`docs/architecture.md` and `docs/cli-concept-candidates.md` are new.**

## Decisions

- **Durable `position` stays in service output, as documented chart data.**
  **Rejected:** moving coordinates to the view. Stable places must survive
  refresh and be shared by the CLI and every view, and historical views pin
  current addresses.
- **`navcom_history.py` and `navcom_sources_worker.py` are frozen against
  cleanup.**
  - `navcom_history.py:243` keys every historical snapshot on the sha256 of the
    file's own bytes. The worker's `extractor_signature()` does the same for
    every harvested source.
  - Round 1 made three cosmetic refactors to `navcom_history.py` (a
    `MAX_BOUNDARIES` constant, `worker_argv()`, `in_scopes()`). Shipping them
    would have silently re-snapshotted and re-harvested every dated repository:
    B2B alone is 2,069 files, the mobile app 190.
  - The coordinator restored the file to HEAD byte for byte (70 history tests
    pass), and `docs/architecture.md` now has a "Modules whose own bytes are
    cache keys" table.
  - Saved dated cursors are unaffected either way, because a cursor loads its
    `plan.json` directly and the adapter hash feeds only new session IDs.
- **The `KINDS` aliases are kept.** The KISS map called them unreachable, but the
  verifier proved `navcom atlas list districts --space` uses them. They were
  restored and pinned by
  `tests/test_space_commands.py::test_every_plural_kind_alias_still_lists_its_places`.
- **The KISS map was wrong about two standalone `main()`s.** Tests used both. The
  relationships test moved onto `navcom atlas related`, and the redundant
  ship-context script test was dropped in favor of `test_ship_context_cli`.
- **Not done (for the owner):**
  - Merge the eight bounded isolated-subprocess runners into one `run_isolated`.
    Error messages and exception classes are asserted and drive retry
    classification.
  - Merge the sha256/atomic-JSON/flock helpers. They change persisted keys or
    fingerprints.
  - Merge `place_overview` into `space`, `commission_archives` into `fleet`, and
    `historical_landing` into `system_history`.
  - Add `--sync-index`/`--budget` to `atlas refresh`. That is a CLI concept
    candidate.
- **One-time cache costs from this round:** single misses in the relationships,
  native-families, stars and carried-search memos, redone star-chat reviews,
  and new IDs for *new* system-history sessions. Saved journeys are unaffected.

## Snippets

```sh
.venv/bin/python navcom.py atlas list ships --json | grep -c art_role     # 0
.venv/bin/python navcom.py atlas show <planet-id> --json | python3 -c 'import json,sys; print(sorted(json.load(sys.stdin)["center"]["commands"]))'
grep -n "__file__).read" navcom_*.py      # every module whose own bytes are a cache key
.venv/bin/python -m pytest tests/test_space_commands.py tests/test_star_chat.py -q
```

## Files

- `navcom_navigation.py`: `history_cache()` beside `paths()`; CLI routing moved out; view pins node commands to the caches in use.
- `navcom_space.py`: `load_catalog()`, `kill_group()`, `subtree()`, `in_scopes()`, `position()`, node `commands`, constants for the refresh limits, `art_role` stripping.
- `navcom_chart_refresh.py`: `drive()`; `kill_group` use.
- `navcom_atlas.py`, `navcom_discovery.py`, `navcom_atlas.js`: color moved into the legacy view.
- `navcom_fleet.py`, `navcom_commission_archives.py`: no sprite names.
- `navcom_atlas_cli.py`: lazy help imports; CLI routing; the new reserved-word note.
- `navcom_history_cli.py`, `navcom_sources.py`, `navcom_historical_conversations.py`: resolver, `worker_argv()`/`source_id()`, service-built `cli_command`.
- `navcom_historical_landing.py`, `navcom_system_history.py`, `navcom_native_families.py`, `navcom_star_chat.py`, `navcom_carried_search.py`: `kill_group`; never-passed parameters removed.
- `navcom_ship_*.py`, `navcom_relationships.py`, `navcom_place_*.py`, `navcom_stars.py`, `navcom_source_discovery.py`: one `commission_tools()`, dead mains removed, shared helpers.
- `docs/architecture.md`: the five-layer law, import directions, where each concern lives, cache-identity modules, the route-twin rule.
- `docs/cli-concept-candidates.md`: actions the UI wants but the CLI cannot do yet. The owner decides.
- Tests: `test_space_commands.py`, plus updates to `test_space.py`, `test_navigation.py`, `test_fleet_archives.py`, `test_space_archives.py`, `test_relationships.py`, `test_ship_context.py`, `test_place_overview.py`, `test_historical_conversations.py`, `test_chart_phase_budget.py`, `test_space_pagination.py`.

## Appendix

- Command payload growth: `explore` of 80 nodes +1.9%, `list planets` of 80 nodes +13.5% (about 20 pinned commands per node).
- After round 1 plus the coordinator fixes, the full suite gave 973 passed, 6 skipped, 0 failed (177.9 s) and BDD 136/136 (739 steps).
- Audit maps (session scratchpad, not durable): `arch.json` (34 routes; 17 clean at start), `matrix.json` (20 kinds × 48 verbs = 165 rows), `kiss1-3.json` (76 candidates).

Tags: architecture, layering, presentation-out-of-services, cache-identity, kill-group, node-commands, kiss. The service layer now holds the CLI's syntax and none of the view's paint.
