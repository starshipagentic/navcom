# navcom 0.7.0: `navcom --menu`, a CAPCOM-style retro dashboard that shows people what they're keeping

**Pain:** people don't know they are missing their own history. The 30-day wipes, the rescued
sessions and the 30 harnesses were invisible unless you typed the right flags. Bare `navcom` also
printed a session list instead of the manual every LLM and human starts from.

## Summary

- **Bare `navcom` prints `--help`.** The old recents view moved to `navcom --sessions`. Running with
  filters but no query (e.g. `navcom --claude`) still lists recent sessions.
- **`navcom --menu`** (also `--tui` and `--ui`) is a stdlib-only full-screen TUI in the locked
  CAPCOM style (`~/dev/EXP31-pi-dev-tools/docs/retro-raster-tui-style.md`):
  - **Splash:** blue-sky raster stripes; a block-glyph **NAVCOM** wordmark (5×7 masks drawn with
    ▀▀, so it is font-independent) in the vertical sunset gradient `#fdc170 → #975b0a`; the slogan
    band **"YOUR CONVERSATIONS · YOUR MACHINE · YOUR DATA"**; the tagline "every coding agent's
    history — searchable in a blink, archived, kept for 100 years"; and footer stripes from sunset
    down to black.
  - **Live dashboard** (1s clock tick, `r` refresh):
    - HISTORY: sessions, turns, tool outputs, "since YYYY-MM-DD", rescued count, archive and index
      size.
    - RETENTION: the hero panel. A one-cell red bar for "Claude's default 30 days" sits against a
      full green bar for "navcom keeps 100 years". Each harness row reads "wipes at Nd → kept 100y",
      with a "saved so far: N Claude chats > 30d old" line.
    - ACTIVITY: a 30-day sqrt-scaled sparkline, per-harness meters, the daily-upkeep LED and the
      active-harness count.
    - ACTIONS: solid cards with the selection highlighted on amber, as in the guide. Search, recent,
      open-by-ref, harnesses, learn, skill card, run upkeep, quit.
  - **Every screen shows a `CLI ▸` line**, for example `navcom drizzle migration → navcom --open
    7ec78a59:533`, so using the TUI teaches the commands that agents and scripts use.
  - **Search** accepts `--claude`, `--codex` and `--tool` typed inline. Results are grouped by
    session, and pressing Enter opens a scrollable reader positioned at the hit.
- **Real numbers on this Mac at release:**
  - 6,461 sessions, 572,347 turns and 223,188 tool outputs.
  - History since 2023-10-04, from Aider.
  - **2,802 rescued**, and **76 Claude chats already past day 30 that the 100-year fix saved today.**
  - Retention is kept for Claude, Gemini, Qwen and Hermes.
- **Verification:**
  - Drove the real TUI in a pty through the splash, dashboard, search, a hit, the reader, the
    harness table and LEARN, then quit. Exit 0, no traceback (`scratchpad/drive_menu.py`).
  - Rendered PNGs with Charm `freeze` (feed it an ANSI file, not `--execute`, which hangs).
    Visual QA caught truncated retention text and a flat sparkline; both fixed.
  - `tests/test_menu.py`: every row is exactly the terminal width at 80, 118 and 160 columns; the
    dashboard contains the retention claims; bare `navcom` prints help; `--menu` without a TTY exits
    gracefully.

## Decisions

- **Stdlib key loop** (termios cbreak + select + the alternate screen), the same approach as
  capcom's own live dashboard, **instead of gum.** It keeps navcom free of dependencies; gum fits
  static menus, but a live dashboard needs its own frame loop.
- **The TUI is for humans only.** Agents keep the plain commands. The skill card says so, and
  `--menu` without a TTY prints the pointer to `--help`.
- **The `--sessions` flag replaces the old `--sessions` alias of `--list`.** `--list`/`--ls` keep the
  file-index view.

## Files changed

- `navcom.py`:
  - The `navcom --menu` section: `MENU_P`, `_GLYPHS`, `_line`/`_stripe`/`_band`/`_box`/`_meter`/
    `_spark`/`_wordmark`, `splash_frame`, `dashboard_stats`, `dashboard_frame`, `_screen`, `_Term`,
    `_menu_search`, `_menu_view`, `_menu_list`, `LEARN_PAGES`, `run_menu`.
  - The `--menu` and `--sessions` flags, bare help, the help lines and a skill-card line.
  - Version 0.7.0.
- `tests/test_menu.py`, `features/reading.feature` (`--sessions`).
- `docs/menu-splash.png`, `docs/menu-dashboard.png`; a README section with screenshots;
  `pyproject.toml` sdist now includes `docs`.

**tags:** navcom, tui, capcom, retro-raster, atari, dashboard, retention, data-ownership, freeze,
pty-testing. navcom now shows people, at a glance, the history it has been keeping for them.
