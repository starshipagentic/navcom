---
name: navcom-session-recall
description: Search every past AI coding session on this machine (Claude Code, Codex, Gemini CLI, Copilot CLI, Cline, Continue, Qwen Code, Kimi Code, Crush, pi, omo, opencode, goose, Kilo, DeepSeek dsh/Codewhale/Reasonix/Deep Code, Grok Build) with the local `navcom` CLI. Use when the user says "use navcom", asks to find an old conversation or thread, asks what was done/decided/tried before on a topic, wants to recover context after a compaction, or needs evidence from past sessions (commands run, errors seen, decisions) before continuing work.
---
<!-- managed by navcom: updated automatically on upgrade; edit freely and it will be left alone -->

# NavCom session recall

`navcom` is a sub-second full-text search (SQLite FTS5 + BM25) over every coding-agent transcript
on this machine. Output is plain text grouped by session: date, harness, project dir, a **ref**, and
the matching turns (`#533 user: …«match»…`).

## The recipe

```bash
navcom topic words here          # 1. find  (no flag, no quotes needed)
navcom --open <ref>:<turn>       # 2. read the turns around one hit, full text
```

Step 1 prints a ready-to-run `--open` line. Do not grep the raw JSONL. `--open` is faster and
still works for sessions the harness has since deleted.

## Queries: type them as-is

- Punctuation is safe: `10.10.1.223`, `don't`, `PR #76`, `cerbos-wave-2`, `main()`, `file.py`,
  `user@x.com`. **Never strip punctuation by hand.**
- All words must appear in one turn, prefix-matched (`auth` matches `authentication`). If no turn
  has them all, navcom shows turns with ANY of them (rare words rank first) and prints a `note:`.
- `a OR b`, `a | b`, or a comma list `cognito, cerbos, fhir` means any of them. `NOT x` excludes.
- `"exact phrase"` falls back to loose words when the phrase isn't found.
- Lowercase `and` is ignored and lowercase `or` means OR.
- Awkward shell quoting? `navcom - <<'EOF'` … `EOF` reads the query from stdin.
- 2–4 distinctive words (ids, error strings, service or file names) beat long sentences.

## Narrow or widen

```bash
navcom deploy -n 50              # hits PER HARNESS (default 20). Every harness gets its own share
navcom deploy --claude           # also --codex --gemini --pi --omo --opencode --goose, or -p claude,pi
navcom deploy --here             # sessions started in this directory (or below)
navcom deploy --project syra     # working dir contains "syra"
navcom deploy --days 7           # or --since 2026-09-01 / --since 12h / --until …
navcom deploy --user             # only what the user typed;  --cmd = shell commands that were run
navcom "TypeError: x" --tool     # search TOOL OUTPUTS (command output, files read, errors, tests)
navcom deploy --newest           # newest sessions first
navcom goal --this-session       # only THIS conversation (recall after compaction)
navcom                           # no query: the 20 most recent sessions, with titles
```

- The conversation you run navcom from is skipped automatically (`--include-self` keeps it).
- `--this` = the harness you're running in. For the current directory use `--here`.

## Read more

```bash
navcom --open 7ec78a59:533       # 3 turns either side of #533 (--window-turns N for more)
navcom --open 7ec78a59:520-560   # a range of turns
navcom --open 7ec78a59 --user    # every user turn in that session
navcom deploy --context          # expand every hit in place
navcom deploy --json             # structured: sessions[] with ref, date, project, hits[]
navcom --restore 7ec78a59        # transcript deleted by its harness? put it back, then resume it
```

## Good to know

- Parallel runs are fine. Read-only sandboxes work (they search without refreshing the index).
- `--solo` / `--summary` hand the hits to another LLM CLI, so they're slow (≤150s). Usually
  better to read the hits and summarize them yourself.
- `navcom --help` is the full manual. `navcom --where` shows which harness logs exist.
- `navcom --skill` prints this card; `navcom --skill install` (re)installs it for every harness here.

## Evidence pattern

Report what navcom found (session ref, date, harness, project, turn numbers and quoted snippets)
separately from what you verified live now, and flag anything memory-derived as possibly stale.
