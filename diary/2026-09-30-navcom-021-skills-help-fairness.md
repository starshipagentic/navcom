# navcom 0.2.1: the skill installs itself, --help is the manual, and every harness gets a turn

**Pain:** The 0.2.0 skill card was copied by hand into three folders, which helps one Mac only.
`--limit` had become a global total, so one busy harness (14GB of Codex) could crowd out the rest.
`--help` was good but not complete, even though agents ran it 82 times and read the skill doc 186
times in the mined logs.

## Summary

- **Skill card embedded in navcom.py** (`SKILL_MD`) and **installed silently on every run**
  (`auto_install_skills`) into the skill folder of every harness that is present:
  - `~/.claude/skills`: Claude Code. opencode and goose also read it.
  - `$CODEX_HOME/skills`: Codex, verified from the strings in the codex 0.159.2 binary.
  - `~/.agents/skills`: the Agent Skills location. pi documents it (`docs/skills.md`), and omo,
    opencode and goose use it too.

  Update rule:
  - A card that is missing gets written.
  - A card carrying our marker and unchanged since we wrote it gets upgraded. We track this with
    sha256 in `navcom-skills.json` next to the index.
  - A card someone edited, or one that isn't ours, is left alone.
  - `--install-skills` forces it and reports, and `NAVCOM_NO_SKILLS=1` opts out.
- **`-n` is per harness again**, and it's fair. `_search_once` runs one MATCH per harness, keeps its
  top N and merges the harnesses by the BM25 `rank`. Search is still about 0.2s. The footer names
  which harnesses had more.
- **`--help` rewritten as the manual**:
  - An agent quick card: find, then `--open`.
  - The query rules, including punctuation, comma lists, the phrase fallback and the and/or/not rule.
  - NARROW, READ, OUTPUT (with the JSON shape), SUMMARIES, and GOOD TO KNOW (self-exclusion, the
    archive, parallel-safe, exit codes).
  - Every option now has a real metavar and an example.
  - `-v` means version (the common guess) instead of `--context`.
  - `--this` spells out that it is NOT the directory. That exact trap came up in the mined logs.
- **Tests:** `tests/test_help_and_skill.py` extracts every `navcom …` example from `--help` and from
  the skill card (37 of them) and runs each one against the fake home. The docs can't drift into
  broken examples. `features/skills.feature` covers install, keeping edits, upgrading, opting out and
  `--install-skills`.

## Decisions

- **The OR fallback relies on BM25, with no stopword list.** Rare words already dominate the
  ranking, as the owner confirmed. Lowercase `and` is dropped by a cooker rule, not NLP: FTS5 only
  treats uppercase AND/OR/NOT as operators, and prefix-matching `and*` would have hit
  android/andrew.
- **Per-harness limit rather than a global total.** "LLMs are beasts, rows don't matter; every
  harness gets a turn in the sun." It costs 7 MATCH queries instead of 1, which is noise at about 0.2s.
- **Skill installed at runtime, not at install time:** pip/pipx wheels have no post-install hook.
  Silent, because the owner's philosophy is never to bother the user with a decision.
- **Not written into pi's own `~/.pi/agent/skills`**, because pi warns when the same skill name
  appears twice. `~/.agents/skills` already covers pi.
- **Marker plus hash** so upgrades refresh the card but never clobber local edits.

## Files changed

- `navcom.py`:
  - `SKILL_MD`, `skill_targets`, `install_skills`, `auto_install_skills`.
  - `_search_once`, plus a `search_hits` rewrite (per-harness, same fallback chain).
  - `Hit.rank`.
  - The `HELP_TEXT` rewrite and the `build_parser` rewrite (metavars, examples, `-v`,
    `--install-skills`).
  - `DEFAULT_LIMIT`, and `NAVCOM_VERSION` bumped to 0.2.1.
- `skills/navcom-session-recall/SKILL.md`: generated from `SKILL_MD`; a test asserts they are
  identical.
- `tests/test_help_and_skill.py`: every documented example runs.
- `features/skills.feature` and its steps; `features/search.feature` gains per-harness and `-v`
  scenarios.
- `README.md`: the skill auto-install section, and per-harness `-n`.
- `pyproject.toml`: 0.2.1.

**tags:** navcom, agent-skills, SKILL.md, auto-install, --help, bm25, per-harness-limit. The tool
now teaches every agent harness about itself, and its manual is tested.
