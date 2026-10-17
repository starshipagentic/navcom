# October 16, 2026 — Command words search again, and `import navcom` halves

**Pain:** the galaxy work had quietly broken NavCom's oldest promise, that no
query crashes. `navcom history of the sigpipe fix` exited with
`invalid choice: 'of'`. `navcom sources of truth` failed the same way, and
`navcom help me find login` said "Unknown help subject". LLM agents search like
that constantly. This was the galaxy "perverting" the CLI, exactly what the owner
warned about.

## Summary

- **Leading words are commands only when a real subcommand follows.** A leading
  `atlas` / `history` / `sources` / `voice` is a command only before one of its
  real subcommands, before `-h`/`--help`, or alone. `help` is a command alone or
  before a known help subject. Anything else is an ordinary search.
  `navcom.leading_command()` reads the subcommand lists from each module's own
  `parser()` (via `COMMAND_MODULES`), so no copied list can drift. The BDD
  scenarios were written first and went 27/31 → 31/31. All 19 forms that worked
  before give byte-identical output.
- **Import diet on the hot path.** `import navcom` went from 51.6 ms to 28.6 ms
  (later about 24 ms; median of 15 alternating `-X importtime` runs).
  dataclasses (plus the inspect/dis/ast/tokenize it pulls in), uuid, base64,
  tempfile, struct, html and urllib.parse (on 3.13+) no longer load.
- **Proven-dead code deleted.** The two exec'd blobs shrank from 75.7k to 14.9k
  characters: `LOG_CLEAN_QUICK_CODE` 901 → 330 lines and `LOG_SEARCH_FTS5_CODE`
  1,256 → 139 lines. Both `signal.signal(SIGPIPE, SIG_DFL)` lines are kept, and
  every surviving def is byte-identical. Also deleted: nine test-fixture builders
  that had been copied into production, `run_match`, `_LinesSource`,
  `_AND_WORDS`, a dead help branch and `DEFAULT_VERBOSITY`. Eleven identical
  harness helpers were merged into `_json_args`, `_read_json`, `_read_json_dict`
  and `_split_db_key`. `navcom.py` dropped about 280 lines.
- **DNA gate.** New `tests/test_cli_dna.py` (19 tests) checks that:
  - `import navcom` loads zero `navcom_*` modules;
  - search, `--open`, `--recap` and `--resume --print` load zero galaxy modules;
  - command-word searches never error;
  - the output shapes LLMs parse stay fixed.

  `scripts/dna_perf.py` is a manual speed gate. It times the real index against
  `tests/dna_baseline.json`, allowing medians up to max(+35%, +0.25 s).
- **Extra:** `navcom WORDS --json` with zero hits now prints
  `{"query":…,"note":…,"sessions":[]}` instead of plain "No hits.", which used to
  break JSON parsing.

## Decisions

- **Chosen:** read subcommands from the real parsers. **Rejected:** hard-coded
  lists. They are cheaper (they save 2–9 ms only on queries that start with a
  command word) but they drift. Ordinary searches load no `navcom_*` module, and
  test_cli_dna checks that.
- **Chosen:** keep 0.10.0's layered `--help` overview. **Deferred to the owner:**
  making the three-line agent recipe (`navcom <words>` / `--open REF:TURN` /
  `--recap REF`) lead `--help`. Today an agent that runs `--help` sees a 14-row
  command map, and the recipe appears only in `navcom help search` or
  `help all` (1,183 lines).
- **Not done (they change tested or visible behavior; owner decides):**
  - the legacy flat Recents;
  - commit sniffing in `--latest`;
  - merging the two whole-session readers;
  - the hidden `--all-logs` / `--verbosity` flags;
  - turning the remaining exec'd blob code into normal module code (name
    collisions; a few ms at most).
- `tests/test_discovery_cli.py` used `navcom atlas unknown` as its "bad
  subcommand" probe. That is now a search by design, so the probe became
  `atlas list nonsense`, which still exits 2 with "invalid choice".

## Snippets

```sh
.venv/bin/behave features/query_forgiveness.feature --format progress3   # 31/31
.venv/bin/python -m pytest tests/test_cli_dna.py -q                      # 19 passed
.venv/bin/python -X importtime -c 'import navcom' 2>&1 | grep navcom      # only navcom itself
.venv/bin/python scripts/dna_perf.py                 # installed navcom vs tests/dna_baseline.json
.venv/bin/python scripts/dna_perf.py --source .      # this checkout, as the console script runs it
.venv/bin/python scripts/sync_skill_card.py --check  # repo SKILL.md == embedded card
```

## Files

- `navcom.py`: `leading_command()`/`COMMAND_MODULES` routing; plain `Hit` class;
  lazy stdlib imports; dead-code and blob pruning; merged harness helpers; JSON for
  zero hits; help note restating the rule.
- `features/query_forgiveness.feature`: command-word searches, `help me …`, and
  real subcommands still dispatching.
- `tests/test_cli_dna.py`: the DNA gate. `scripts/dna_perf.py` and
  `tests/dna_baseline.json`: the manual speed gate and its noisy seed baseline.
- `navcom_atlas_cli.py` OVERVIEW and `README.md`: the same rule in user-facing help.
- `tests/test_discovery_cli.py`: the bad-subcommand probe is now `atlas list nonsense`.
- `skills/navcom-session-recall/SKILL.md`: regenerated with the tool, matching
  the embedded card again (one of the two baseline test failures).

## Appendix

- Baseline before changes (installed 0.10.0, 5-run medians, with a chart refresh
  running on the bridge): `sigpipe` 0.672 s, `"starforge harvest"` 0.769 s,
  `the` 5.092 s, `import navcom` 0.232 s. On a quieter machine the installed
  version measured 0.184 / 0.185–0.200 / 1.40–1.44 / 0.082 s, and this checkout
  0.149 / 0.155 / 1.37–2.20 / 0.060 s. Rewrite the baseline on a quiet machine
  after release with `scripts/dna_perf.py --write-baseline`.
- Test baseline at session start: 936 passed and 2 failed (stale skill card;
  macOS `killpg` EPERM race). BDD: 130/130. After round 1: core-dna full suite
  972 passed, 6 skipped. BDD: 136/136 (739 steps).

Tags: dna, llm-proof-search, reserved-words, import-time, dead-code, bdd,
cli-first. The headless CLI is simple and fast again, and the galaxy commands can
no longer take over ordinary searches.
