# navcom 0.6.0: 30 harnesses (830 forgotten Aider sessions found), and still about 0.3s

**Pain:** adding 8 more harnesses (Aider, Antigravity, Factory, grok-dev, Cursor, Kiro, Amp, Auggie)
threatened navcom's DNA, speed. With 30 harnesses listed and searched separately, a search went from
0.28s to 0.8s; a common word took 3.5s, and `the` took **70s**. Aider's parser also re-read 62 MB of
history on every call.

## Summary

- **New harnesses:**
  - Live-verified: aider (0.86.2), agy (1.2.14), droid (0.231.0), grokdev (1.1.7).
  - Fixture/source only, because each needs a vendor login: cursor, kiro, amp, auggie.
  - **Real data found: 830 Aider sessions in 134 project history files (62 MB, back to 2025)**, with
    10,591 prompts and 3,654 shell commands.
- **How the logins were avoided:**
  - agy: a local Gemini→OpenAI proxy (`harness/agy/gemini2openai_proxy.py`) driven via
    `GOOGLE_GEMINI_BASE_URL` with `{"modelProvider":"gemini"}`. The settings file was restored
    afterwards. Note that `~/.antigravity/antigravity/bin/agy` is the IDE launcher, not the CLI.
  - droid: a BYOK `customModels` settings file using `${OPENROUTER_API_KEY}` expansion.
  - grokdev: Groq's OpenAI endpoint (grok-dev's stream parser rejects OpenRouter tool deltas).
- **Speed:**
  - `_search_once`: one streaming pass of `(rowid, provider, rank)` over all matches, with a heap
    per harness for top-N fairness. A window function would materialise and sort every match
    (3.5s for `error`), and per-harness queries cost 30 × a full match.
  - Snippets are computed in Python (`make_snippet`, a two-pointer best window with «» marks) from
    text fetched by plain rowid lookup. FTS5 `snippet()` with `rowid IN (…)` re-evaluates the whole
    MATCH (≈73ms per row for `the`), and it can't run inside a windowed query ("unable to use
    function snippet in the requested context").
  - The freshness check loads `file_state` once instead of 3,700 single-row queries.
  - `_rglob` uses `os.walk` with rglob-equivalent tail matching (2.5× faster; output identical on 5
    real trees).
  - `CREATE INDEX turn_loc_rid`: `max(rid)` was a 48ms full scan on every call.
  - aider's section split is cached per file by (mtime, size) in `navcom-aider-sections.json`:
    0.378s → 0.002s.
  - **Results:**

    | Query | Before | After |
    |---|---|---|
    | drizzle migration | 0.343s | 0.047s (end to end 0.29–0.37s) |
    | error | 3.5s | 0.25s |
    | the | 70s | 1.4s |

- **Refs:** aider keys are `file#N`, so they display as `<project>@N`. `_ref_like` maps refs to
  LIKE patterns. An exact ref match wins over a prefix match, so `proj@3` no longer opens `proj@31`.

## Decisions

- **Python snippets instead of FTS5 `snippet()`.** They are the same shape («match» marks plus …
  ellipses) at a fraction of the cost. The window prefers the densest run of matches.
- **The aider discovery walk** stays at depth 5 with a 1h rescan: depth 6 found 3 more histories but
  took 2.3s. The per-file split cache makes ordinary calls free.
- **Cursor, Kiro, Amp and Auggie ship as fixture-proven** and are marked ¹ in the README. They read the
  documented and bundle-confirmed formats and stay dormant until those directories exist.

## Files changed

- `navcom.py`: the streaming-heap `_search_once`, `make_snippet`/`_query_terms`, the batched
  `_index_logs` freshness check, the os.walk `_rglob`, the `turn_loc_rid` index, aider refs and
  `_ref_like`, the exact-ref preference, and the generated section (now 20 harnesses). Version 0.6.0.
- `features/support/harness_fixtures/{aider,agy,droid,cursor,kiro,amp,auggie,grokdev}.py`.
- `features/reading.feature`: the recents list uses `-n 100`.
- `README.md`: the ¹ footnote. `skills/…`, `pyproject.toml`.
- **Outside the repo:**
  - The agy CLI in scratch.
  - `~/.cursor/cli-config.json`, created by a probe.
  - `~/.grok/user-settings.json`, restored byte-identical.

**tags:** navcom, aider, antigravity, factory-droid, cursor, kiro, amp, auggie, grok-dev, performance,
fts5, bm25, heap, snippet, os.walk. With 30 harnesses navcom is still about 0.3s per search, and 830
lost Aider sessions are now searchable.
