# October 16, 2026 — The web adapter goes thin, and the law becomes a test

**Pain:** `navcom_web.py` had become a second brain. It re-implemented
`--maintain` step by step, and it flipped the core's `INDEX_READ_ONLY` global.
It owned a launch pre-flight that `--resume --tab` and the TUI each did
differently. It duplicated the TUI's annotation merge and dashboard cache, built
the suggest excerpt inline, and derived the history-cache path five times.
"Each route calls the same service its CLI command calls" was a hope, not a
check.

## Summary

- **Shared functions** that the CLI, TUI and web now all call:
  - `navcom.maintain()` + `navcom.claim_index_writer()`: `cmd_maintain`, TUI
    Upkeep and `/api/upkeep`. `--maintain` output is identical to HEAD.
  - `navcom.prepare_launch()`: `/api/launch`, `--resume REF --tab`, TUI `r`/`t`/`n`.
  - `navcom.annotate()`: TUI `e`/`d`/`f` and `/api/annotation`.
  - `navcom.dashboard_snapshot()`: TUI dashboard (with a `prepare` hook) and
    `/api/status`.
  - `navcom_intelligence.excerpt()` / `suggest_for()`: `/api/suggest`.
  - `navcom.search_json()`: what `navcom WORDS --json` prints, now also returned
    by `/api/session/search`, byte for byte.
- **Round-1 follow-ups:**
  - `navigation.history_cache()` replaced all five inline copies.
  - `/api/source` resolves the source cache the same way `sources read` does.
  - The bridge's refresh runs `navcom_chart_refresh.drive()` with identical
    messages and Pause behavior.
- **New read-only routes,** each validation plus one service call:
  - `GET /api/recap` (= `--recap REF`)
  - `GET /api/session/search` (= `WORDS --file REF`)
  - `turn` on `GET /api/plan` / `POST /api/launch` (= `--resume REF:TURN --with H`)
  - `repo`/`include` on `/api/history` (= `history timeline --repo --include`)
  - `GET /api/sources` and `GET /api/sources/search`, backed by the new
    `navcom_sources.sources_list()` / `search()` that the CLI now calls too.
  - Restore, summarize and discover/harvest deliberately got no route.
- **`tests/test_architecture.py`** (143 tests) makes the law executable:
  - (a) AST import scan: only `navcom.py` imports `navcom_web`, and only inside
    `run()`. No other module names a view file.
  - (b) `navcom.py` imports no `navcom_*` at import time.
  - (c) A `ROUTES` table covers every route literal. Each CLI twin is proved by a
    subprocess under a throwaway HOME, where the service is swapped for a
    function that exits 77, and the web side by an in-process patch.
    `view-state` exemptions are a fixed set, and every `cli-gap:` anchor must
    exist in `docs/cli-concept-candidates.md`.
  - (d) A presentation-key walk over `PROBES` (31 routes) and `CLI_JSON`
    (27 `--json` twins) on the real BDD "Orchard" galaxy. Adding `color` to any
    of 13 services makes it fail.
  - Every guard was shown failing on a deliberately broken copy.

## Decisions

- **Kept in the adapter, with the reason recorded:** `/api/recent` (a 30 s memo,
  display names, research-profile notes that only the Library uses) and
  `/api/session` (an 80-turn page vs. the TUI's focus window). Sharing them now
  would force one surface's behavior onto the other. Both are listed as CLI
  concept candidates.
- **No new CLI flags.** The five web/TUI-only features (recent, status, session,
  suggest, annotation) stay on `docs/cli-concept-candidates.md`, for example
  `navcom --where --json` from `dashboard_snapshot()` and
  `navcom --annotate REF --name/--note/--favorite` from `annotate()`. The owner
  decides.
- **One narrow, documented exemption in guard (d):** `query_plan.style`
  (`literal`/`question`) is retrieval-style data that both the CLI and view
  branch on, not styling.
- **Behavior changes, all deliberate:**
  - `--resume --tab` now refuses with "codex isn't installed here" or "its
    folder … no longer exists" (exit 1) instead of opening a doomed tab. The TUI
    `t` key and the picker check the same things.
  - A failed TUI annotation is no longer shown as saved.
  - The `--maintain` summary line prints after the discovery refresh.
  - A JSON `null` name or note in `/api/annotation` means "unchanged".

## Snippets

```sh
.venv/bin/python -m pytest tests/test_architecture.py -q        # 143 passed
.venv/bin/python -m pytest tests/test_web_routes.py tests/test_web_shared.py -q
curl -s -H "Host: 127.0.0.1:$PORT" -H "X-Navcom-Token: $TOKEN" "http://127.0.0.1:$PORT/api/recap?key=$KEY" | head -c 300
```

Adding an `/api` route now requires a `ROUTES` entry (a twin or a `cli-gap`), a
`PROBES` request, and a `CLI_JSON` command or a `TEXT_ONLY` reason. Otherwise
`test_architecture` fails and explains the rule.

## Files

- `navcom_web.py`: a thin adapter. Per-request `caches()`, `drive()`, shared functions, new read routes, one `local()` loopback check, unused imports removed.
- `navcom.py`: `maintain`, `claim_index_writer`, `prepare_launch`, `annotate`, `dashboard_snapshot`, `search_json` (no new top-level imports; test_cli_dna stays green).
- `navcom_intelligence.py`: `excerpt()` and `suggest_for()`.
- `navcom_sources.py`: `sources_list()`, `search()`, `WorkerError`.
- `tests/test_architecture.py`: the law as tests. `tests/test_web_routes.py`: route ↔ CLI parity. `tests/test_web_shared.py`: shared functions across surfaces.
- `docs/architecture.md`: final route table and enforcement description. `docs/cli-concept-candidates.md`: cli-gap anchors.

## Appendix

- After the fix, the full suite ran twice: 1138 passed, 6 skipped (live-bridge opt-ins), in 3:59 and 4:02. BDD: 11 features, 166 scenarios, 1044 steps.
- The verifier found two medium issues, both fixed. Guard (d) had walked only a few services, and `/api/session/search` used its own projection. Two low findings (dynamic-dispatch bypass of route parsing; pre-existing recent/session logic) are recorded, not changed.
- One BDD stream agent stalled for about 90 minutes on an unanswerable permission prompt (`rm -rf` outside the scratchpad) after finishing its work. The run was stopped, and the follow-up workflow told agents to keep temp files inside the scratchpad.

Tags: web-adapter, thin-adapter, architecture-tests, route-parity, shared-functions, cli-concept-candidates. Every bridge route is now provably the same service its CLI command runs.
