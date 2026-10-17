# October 16, 2026 — KISS ledger: what got simpler, and what waits for the owner

**Pain:** the owner felt NavCom drifting from "one simple CLI for LLMs" toward an
integration. Three independent reviewers read the whole tree: core and legacy,
galaxy services, and web/view/tests/docs. Together they proposed 76 candidates.
This entry records what was done and why the rest was not, so nobody has to
re-litigate it.

## Summary of what got simpler (details in the linked entries)

- **Core CLI** ([command words](2026-10-16-command-words-search-again.md)):
  - about 280 lines and 40 unreachable exec'd defs gone;
  - nine fixture builders out of production;
  - 11 harness helpers merged into 4;
  - `import navcom` 51.6 → about 24 ms, with dataclasses/inspect/uuid/base64/
    tempfile/struct/html no longer loaded.
- **Services** ([services hold the law](2026-10-16-services-hold-the-law.md)):
  - one path resolver, `load_catalog()`, `kill_group()`, `subtree()`,
    `in_scopes()`, `source_id()`, `worker_argv()` and `commission_tools()`;
  - dead `resolve_destination` and standalone mains removed;
  - never-passed parameters removed;
  - CLI routing moved into the CLI module;
  - no color or sprite fields.
- **Web** ([web adapter goes thin](2026-10-16-web-adapter-goes-thin.md)):
  - shared `maintain`, `prepare_launch`, `annotate`, `dashboard_snapshot`,
    `suggest_for` and `search_json`;
  - one loopback check;
  - unused imports gone.
- **View** ([cockpit](2026-10-16-galaxy-becomes-a-cockpit.md)):
  - one rail instead of per-kind buttons;
  - duplicate buttons removed;
  - one `read()` memo;
  - shared JS test helpers;
  - two dead legacy CSS rules gone.
- **Packaging and docs**
  ([package ships only the product](2026-10-16-package-ships-only-the-product.md)):
  - the sdist is 38% smaller;
  - the plan went from 465 to 62 lines;
  - the superseded gap audit was deleted;
  - stale "next step" sentences were fixed.

## Decisions: corrected or refused

- **Refused for cache-key reasons:** any refactor of `navcom_history.py` or
  `navcom_sources_worker.py`. Their own bytes key every historical snapshot and
  every harvested source.
  - Round 1 made three cosmetic edits to `navcom_history.py`. They were restored
    to HEAD byte for byte, because they would have re-harvested every dated
    repository.
  - `docs/architecture.md` lists every self-hashing module.
- **Wrong in the KISS maps (verifiers proved it):**
  - The "unreachable" `KINDS` aliases are used by `atlas list districts --space`.
    They were kept and pinned by a test.
  - The "unused" `const icons` in `overviewLabelPlan` keeps overview labels off
    other icons. Kept.
  - The "dead" standalone mains were used by tests. The tests moved to the
    public CLI first.

## Waiting for the owner (each changes tested or visible behavior)

| Candidate | Why not now |
|---|---|
| Remove the legacy browser **Conversation Atlas** view, the third web view | Biggest concept reduction left. It loses browser lens browsing, `?view=atlas` links and the Library's "Explore versions" button. The lenses stay in `navcom atlas list/explore/search`. |
| Drop the Atlas view's own **Web Speech voice button** | It is a second voice concept next to local Whisper. Voice is meant to become a living star. |
| Make the three-line agent recipe lead `navcom --help` | 0.10.0 shipped the layered overview. Agents now need `help search` for the recipe. |
| Remove the legacy flat Recents, **commit sniffing** in `--latest`, and one of the **two whole-session readers** | Each changes visible output. |
| Hidden `--all-logs` / `--verbosity` flags | Old scripts would exit 2. |
| Merge the eight **isolated-subprocess runners** into one `run_isolated` | Error texts and exception classes are asserted and drive retry classification. |
| Merge the sha256, atomic-JSON and flock helpers | They change persisted keys and fingerprints. |
| Merge `place_overview` → `space`, `commission_archives` → `fleet`, `historical_landing` → `system_history` | Import paths and packaging change; no behavior gain. |
| Collapse `bases` into `starbases`, and drop `atlas list galaxies` (always 0) | Documented CLI choices. |
| "district" means two things (Atlas folder class vs galaxy code area, shown as `cities`) | Renaming either changes the CLI vocabulary. |
| Six reading verbs per place (show, explore, inspect, context, files, related) | Each has a distinct, tested job. Consider folding them later. |
| Wheel/sdist lists merged into globs | Risks silently dropping a runtime module. `tests/test_packaging.py` guards it instead. |
| Rename evidence `query_plan.style` → `retrieval` | It needs CLI, service and view together. A narrow exemption is documented in guard (d). |
| `/api/recent` memo and `/api/session` assembly still in the adapter | Sharing them with the TUI would force one surface's windowing on the other. |

## Snippets

```sh
python3 -c 'import json; [print(c["paths"], c["action"], c["safe_now"]) for f in ("kiss1","kiss2","kiss3") for c in json.load(open(f"$SCRATCH/map/{f}.json"))["candidates"]]'
grep -n "__file__).read" navcom_*.py      # self-hashing modules: never refactor for cleanliness
```

## Files

This entry changes no code. It indexes the KISS outcomes recorded in the linked entries and in `docs/cli-concept-candidates.md`.

## Appendix

- The candidate maps (session scratchpad, not durable): `kiss1.json` (25: core/legacy), `kiss2.json` (30: services), `kiss3.json` (21: web/view/tests/docs).
- Concept-count observations: three browser views plus the TUI; "atlas" means both the CLI namespace and a web view; `list` takes 15 groupings in one positional (9 spatial, 6 Atlas lenses); two voice paths.

Tags: kiss, simplification, owner-decisions, cache-identity, concept-count. Simpler where it was safe; everything else is waiting on one owner decision each.
