# October 16, 2026 — The dated journey is proven live: UI == API, reload and link included

**Pain:** the handoff left the dated journey half-proven. Syra at 2026-10-01 →
mobile → sign-in → `login` → pinned file worked, but the bridge crashed on
reload (SIGPIPE, fixed earlier today), and Back/Forward, reload and copied-link
acceptance never finished. The Chrome extension also cannot reach this Mac's
`127.0.0.1` bridge, so there was no way to automate a browser proof.

## Summary

- **`tests/test_ui_api_sync.py` and `tests/ui_support.py`.**
  - Playwright (Python, `.venv`) drives the installed Google Chrome (headless,
    `channel="chrome"`, fresh profile, 1440×900, reduced motion) against a live
    bridge given by `NAVCOM_BRIDGE_URL`. The tests skip cleanly without it.
  - At every step the test compares the UI with the API: URL params,
    `history.state`, DOM (title, crumbs, inspector, evidence cards with match
    text, the reader's path, commit and 14 lines) against direct API calls with
    the page's own token.
  - Steps: open the saved system URL → land on the product → enter the district
    → search `login` → open the pinned file → close → Back → Forward → reload →
    open the copied link in a new page.
- **Write guards:**
  - `ApiGuard` allows only the saved journey's exact request bodies and aborts
    `POST /api/space/refresh`.
  - `CacheGuard` hashes the whole history cache (about 8.1k files, 104 MB,
    about 1 s per capture) before and after, and fails on any change.
  - A run is therefore read-only by proof, not just by intent.
- **The test found a real bug.** Reloading on a dated product dropped the origin
  selection and camera, so "← Back to dated system" opened with nothing selected.
  It was fixed in the view (`keptLanding()` keeps `history.state`'s landing when
  the URL names the same landing), and the strict xfail was removed.
- **Copied links carry the camera:** `camera=SCALE_X_Y` (scale to 4 significant
  digits, pan in whole pixels). Camera moves use replaceState and never add a
  history entry. A link opened in a new profile restores scale 0.2851 and pan
  (−45, −45), the same as the original view.
- **The reader is honest about dates.** It shows "committed …" only when the
  response carries a commit date, and "captured …" otherwise.
- **Result:** 7/7 against private checkout bridges, then **7/7 against the
  installed 0.11.0 bridge** (`http://127.0.0.1:57981/`), with the history cache
  unchanged.

## Decisions

- **Chosen:** Python Playwright with the installed Chrome. **Rejected:**
  - Selenium: not installed, and no chromedriver matches Chrome 155.
  - The Chrome extension: it drives the owner's real Chrome and cannot reach
    this Mac's loopback.
  - A raw CDP client: feasible, but more code to own.
- **Chosen:** start every run from the saved cursor URL. A present-day view
  auto-POSTs a chart refresh, and typing a query at system level pins a new
  session (writes). The guards make both visible failures.
- **Playwright 1.64.0 is installed only in `.venv`** (a dev tool) and is not
  declared in `pyproject.toml`.

## Snippets

```sh
uv pip install --python .venv/bin/python playwright      # no `playwright install`; channel="chrome"
NAVCOM_BRIDGE_URL=http://127.0.0.1:57981/ .venv/bin/python -m pytest tests/test_ui_api_sync.py -v
```

The saved journey (default caches):

```text
system:9b1f5d1b7914f7de9de3  at 2026-10-01T12:00:00Z
cursor 001f730234d6f2cb0a9a669291867283e68d4727c5bfa744335dfa290a928faf:0
result_key e1fe4a30019ca396636a321a98f2a143dcb85388052ce572a046147b21e7d077
product planet:ace3e3d93a9b103549f8 (syrenity-mobile, 190 files, 5 districts)
district historical-district:95b25495c938190a84b1 ('sign in', 4 files)
commit 1325eaa77fed0521f58317fa191ebf2f82756be6
```

## Files

- `tests/test_ui_api_sync.py`: the live UI == API journey, reload/Back restoration, the present-day rail with its commands and family hue, and guard self-tests.
- `tests/ui_support.py`: Bridge client, ApiGuard, CacheGuard, `journey_requests()`, Python twins of the view helpers (`command_text`, `shell_quote`, `tint_hue`).
- `navcom_space.js`: `keptLanding()`, camera links, reader date labels.
- `docs/historical-landing-contract.md`: journey links carry the camera.

## Appendix

- Live step timings (s): open system 1.33, land product 0.56, district 0.55, search 1.31, open file 0.08, close 1.30, back 0.55, forward 1.22, reload 1.52, copied link 1.27.
- Expected-state fetches: the system response is 15.6 MB, plus three landings of about 11.5 MB each.
- After a Starforge or navcom upgrade that changes the search worker, the `login` memo key changes. The first live run then fails loudly in CacheGuard instead of quietly writing.

Tags: e2e, playwright, ui-api-sync, dated-journey, reload, copied-link, camera, write-guard. The saved Syra Oct 1 journey now survives every navigation, and a test proves it.
