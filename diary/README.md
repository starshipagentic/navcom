# navcom diary

| Date | Entry | Summary |
|---|---|---|
| 2026-09-30 | [navcom 0.2.1: self-installing skill, --help as manual, fair per-harness -n](2026-09-30-navcom-021-skills-help-fairness.md) | Skill card embedded + silently installed into ~/.claude/skills, $CODEX_HOME/skills, ~/.agents/skills (hash-guarded, never clobbers edits); -n per harness merged by BM25; --help rewritten as the LLM manual, all 37 documented examples tested. |
| 2026-09-30 | [navcom 0.2.0: LLM-proof search + 4 new harnesses](2026-09-30-navcom-020-llm-proof-search.md) | Mined 1,093 real LLM navcom calls (89 crashes, 109 zero-hit, 17 locks, 4GB-log slowness). Rewrote query cooker (0 errors / 60k fuzz, 911/918 historical queries now hit), compact default, --open drill-down, --here/--days/--this-session, text-only matching, self-exclusion, incremental+WAL+lock-tolerant index, bounded summarizers; added pi/omo/opencode/goose; BDD+pytest; published 0.2.0. |
