# October 16, 2026 — BDD for every cockpit verb, on a real fixture galaxy

**Pain:** the cockpit was about to put buttons on every place. The owner's rule is
"BDD first: CLI scenario green before the UI is wired". But the galaxy verbs
(places, scoped search, dated landing, conversation verbs, fleet actions) had no
feature files, and no fixture galaxy small enough for scenarios yet real enough to
mean something.

## Summary

- **`features/support/galaxy_world.py` builds the "Orchard" galaxy inside each
  scenario's throwaway HOME, using only the real CLI.** It contains:
  - a Git repo with a declared system, two workspace apps ("lantern", "radar")
    and two dated commits;
  - a native Starforge harvest (`navcom sources harvest`) and a chart from
    `navcom atlas refresh --space`;
  - a dated Claude conversation;
  - a Hermes expert profile discovered as a star;
  - a Starship fleet with a remote ship and a local stored archive;
  - recorders in place of every agent CLI and terminal launcher on PATH, so a
    scenario can prove that nothing started.

  It builds in about 1.5 s. `tests/test_architecture.py` reuses it for its
  presentation-key walk.
- **Five verb-family features (31 scenarios):**
  - `places.feature`: list within a system; show carries every CLI command;
    files, related, inspect.
  - `search_inside.feature`: evidence search stays inside the place; "fly to X
    then find Y"; ambiguity returns choices, not a galaxy-wide search; sources
    search; search inside one conversation.
  - `dated_history.feature`: timeline; land through the printed Land command;
    dated district + query; dated conversations exclude later turns.
  - `conversation_verbs.feature`: `--open REF:TURN`, `--recap`,
    `--resume --print`, and `--resume --with H --print` for each harness.
  - `fleet_verbs.feature`: list ships/starbases; context; `board --validate`
    refuses a remote ship; ask prepares without sending; only the reviewed
    question opens, and only in a new tab; with no known terminal, a reviewed
    launch hands over the command and starts nothing.
- **A reviewer mutation-tested the scenarios and found three that passed on
  broken code:**
  - "fly then find" passed when the search went galaxy-wide;
  - a missing archive or star became a *skip* instead of a failure;
  - "timeline" passed when it ignored the place's paths.

  All three are fixed, and each mutant (M06, M19–M25) now fails for the
  intended reason.
- **Product bug found and fixed (present at HEAD):**
  - `navcom atlas ask/board --launch --review TOKEN` (and
    `POST /api/space/ask|board`) crashed with `KeyError: 'line'` in
    `navcom._open_tab` whenever no supported terminal was detected. Native
    handoff plans carry only argv/cwd.
  - The fallback now shows `plan.get("line")` or the `cd … && argv` line it
    already built, and the new no-terminal scenario pins this.

## Decisions

- **Chosen:** one real fixture galaxy built by the CLI itself. **Rejected:**
  hand-written chart JSON. It is faster, but it proves nothing about harvest,
  charting or the CLI's real output.
- Scenarios assert on CLI output and recorder logs, never on their own input. A
  missing fixture object is a failure, not a skip.
- **Owner note:** `atlas ask --launch` prints "dispatched" whenever the launcher
  returns, even if it opened nothing. A tmux-recorder scenario now catches a
  launcher that does nothing, but the owner may want "dispatched" to require
  launcher evidence.
- **Closed in the polish round:**
  - The `--tab` recorder scenario now uses a TMUX recorder, so it runs on any
    platform.
  - `NAVCOM_BDD_REQUIRE_STARFORGE=1` fails, instead of skips, the Orchard
    scenarios that need native Starforge.

## Snippets

```sh
export TMPDIR="$SCRATCH/tmp"     # keep scenario worlds inside the scratchpad
.venv/bin/behave --format progress3                               # 11 features, 176 scenarios
.venv/bin/behave features/fleet_verbs.feature --format pretty --no-capture
.venv/bin/behave --tags @critical --format progress3
```

## Files

- `features/support/galaxy_world.py`: the Orchard fixture galaxy (real CLI, isolated HOME, launcher recorders).
- `features/steps/galaxy_steps.py`: chart, run, launch and recorder steps.
- `features/places.feature`, `features/search_inside.feature`, `features/dated_history.feature`, `features/conversation_verbs.feature`, `features/fleet_verbs.feature`: the verb families.
- `navcom.py`: `_open_tab` fallback no longer needs `plan["line"]`.

## Appendix

- behave: 136 scenarios before this stream → 166 (drafts) → 167 (review fixes plus the reviewed `--launch` scenario) → 168 (the no-terminal scenario) → 176 (polish coverage: `history explore --query`, timeline `--include`/`--repo` including a real two-Git-copy worktree fixture, `atlas show/tree REF`, `sources list`, `inspect --refresh/--observe`, `context --handover`; 17 + 7 more mutants killed). All pass, 0 skipped on this Mac. `NAVCOM_BDD_REQUIRE_STARFORGE=1` turns a missing-Starforge skip into a failure; set it on machines meant to have Starforge.
- The drafting agent stalled after finishing, on a permission prompt for `rm -rf` in the system temp dir. Scenario worlds now go under `$TMPDIR`, which should point into the scratchpad.

Tags: bdd, behave, fixture-galaxy, mutation-testing, launch-fallback, cockpit-verbs. Every action the cockpit exposes now has a green CLI scenario that fails when the verb breaks.
