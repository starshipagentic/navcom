# October 16, 2026 — The galaxy becomes a cockpit

**Pain:** "The galaxy UI is just a view." You could fly to Syra and read a
planet's details, but to *do* anything (browse its files, check its history,
search its sources, open, recap or resume a conversation, ask its expert) you
had to know a CLI command, or find one of several scattered buttons that
differed per kind. Every system was also the same gold, and inside a system you
could not tell which one you were in.

## Summary

- **One action rail per place** (`placeRail` in `navcom_space.js`).
  - Each action makes exactly one API call, the twin of a CLI command. Beside it
    sits the service's own copyable `navcom …` line (`node.commands`, or the
    response's `cli_command` / `continue_command` / `land_command` /
    `open_command`).
  - The view fills only documented `<placeholders>` with the user's input.
  - Rail panels: search harvested sources, conversations here (named collection,
    "collection N of M"), conversations by date, list places, harvested sources.
  - Commands the rail does not use stay under "More CLI commands for this place".
- **Conversation cards:** Read, Recap (`/api/recap`), Resume… and Fresh agent…
  (each behind a review dialog, then an explicit `POST /api/launch`, with turn
  focus), Search inside (`/api/session/search`), and Family / tree.
- **Consequential actions are never one click.** Ask expert and Board ship open
  reviews that show their exact command.
- **Hue families.**
  - At galaxy level `tint(id)` is unchanged, so every system keeps its own
    stable color.
  - Inside a system, each planet takes the system hue ±24°, with its own
    lightness (30–60%), stripes and ring tilt. Siblings stay distinguishable
    (pixel distance 14.5–30.9), yet clearly one family.
  - Moons and districts get an in-family halo. Stars, ships, starbases and
    archives keep their own art.
- **Sprites come from kind/form only.** Archives draw `archive.png` again; they
  had regressed to the ship sprite once services stopped sending `art_role`.
- **Polish from two adversarial reviewers:**
  - Explore time lives only in the time bar, and the arrival screen no longer
    repeats rail buttons.
  - The words box appears only when the command takes `<query>`, and typed
    words echo into the command line.
  - Keyboard focus returns to the pressed rail action.
  - A `read()` memo keyed by request and chart publication stops unrelated
    clicks from refetching panels (no more repeated 400s).
  - Reading a conversation from the bridge no longer rewrites the Library's
    saved selection (no `POST /api/state`).
  - A chosen Git copy's commits open with `repo`. The adapter now forwards it,
    with a parity test against `navcom history explore --repo`.
  - Card actions bind to the card's own conversation.
  - The favicon uses the same-origin `navcom.png` (the page's CSP blocks
    `data:` icons).
- **`docs/action-matrix.md`** is the kind × verb matrix as built: built (rail
  label → route → command key), not applicable (why), or CLI concept candidate.

## Decisions

- **The view never synthesizes CLI syntax. Rejected:** templating commands in
  JS. It would be faster to build, but it would put CLI grammar in layer 5 and
  drift silently.
  - Where a service emits no command (recap, resume, revive, search-inside,
    dated open, find-in-file), the action works but shows no CLI line, and the
    missing command strings are listed for the owner.
- **Kept and labeled:** `navcom --open REF:N` beside "Read conversation →". It
  is labeled "Nearest terminal read · a shorter window around this turn",
  because `/api/session` has no exact CLI twin (it is a `cli-gap`).
- **One place per action (KISS).** Duplicates found by reviewers were removed,
  not restyled.
- **CLI concept candidates added:**
  - name and size a place's conversation collections, or read all of them at
    once (B2B has 1,400 conversations across 31 collections);
  - structured fields beside node commands (the view still reads `--within` /
    `--path` values out of command text);
  - one shared sentence for a finished chart refresh;
  - history of one harvested file.

## Snippets

```sh
.venv/bin/python -m pytest tests/test_space_action_rail.py -q        # 16 rail controller tests
NAVCOM_BRIDGE_URL=http://127.0.0.1:57981/ .venv/bin/python -m pytest tests/test_ui_api_sync.py -v   # 7/7 live
TMPDIR=$SCRATCH .venv/bin/python navcom.py --menu --no-browser         # a private checkout bridge for UI checks
```

## Files

- `navcom_space.js`: placeRail, railPanel, conversation card actions, tint families, `read()` memo, focus return, Git-copy commits, camera links, `art()` without `art_role`.
- `navcom_space.css`: rail rows and command lines, panels, card actions, family halos, narrow layout.
- `navcom_web.html`: favicon; Library state is untouched while the bridge is active.
- `navcom_web.py`: `POST /api/history/explore` forwards `repo`.
- `tests/test_space_action_rail.py` (new), `tests/test_space_camera.py`, `tests/test_space_relationships.py`, `tests/test_space_carried_context.py`, plus shared `run_js`/`js_between` helpers across nine space tests; `tests/test_web_routes.py` (explore `--repo` parity).
- `docs/action-matrix.md` (new) and `docs/cli-concept-candidates.md` (rows merged and added).
- `docs/e2e-tours/2026-10-16/galaxy-cockpit/`: the narrated proof gif, 13 shots, `tour.json`, README. `scripts/capture_cockpit_tour.py` and `scripts/build_tour_gif.py` (a Python port of the house gif builder; it names the gif after the topic folder) regenerate it.

## Appendix

- Live checks used private checkout bridges started by agents (each killed afterwards) and, after install, the owner's default bridge, restarted at `http://127.0.0.1:57981/` (pid 38243).
- An earlier bridge the owner started (pid 33920, Oct 14, `navcom --menu`) was never touched. It still runs pre-0.11.0 code until they restart it.
- One proof wrote to the history cache: opening commit `5f8d12703cd5` of the awaliv2 copy (`/Users/t/clients/awali/awaliv2`) created a pinned snapshot under `~/.codex/navcom-history`. Nothing else was written.
- Mutation checks: 12/12 for the first rail build and 10/10 for the polish fixes. Each mutant was caught by `tests/test_space_action_rail.py` or the camera and relationship tests.

Tags: cockpit, action-rail, cli-twins, hue-families, review-dialogs, focus, memo, kiss. The bridge now acts on every place, through the same commands the CLI prints.
