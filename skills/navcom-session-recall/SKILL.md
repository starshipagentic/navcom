---
name: navcom-session-recall
description: Recover prior coding-session context with the local navcom command (searches Claude Code, Codex, Gemini CLI, pi, omo, opencode and goose transcripts). Use when the user asks to find old conversations; says to use navcom; wants a previous thread/session recovered; asks what happened before on a topic; wants to recall something from earlier in the current conversation after compaction; or needs compact evidence from past CLI coding logs before continuing work.
---

# NavCom Session Recall

`navcom` is a sub-second full-text search over every coding-agent transcript on this machine.
Output is plain text grouped by session, with a date, the harness, the project dir and a **ref**
for each session.

## The two-step recipe

```bash
navcom topic words here                 # 1. find: compact hits, grouped by session (default 20 hits)
navcom --open <ref>:<turn>              # 2. read: the turns around one hit, full length
```

Step 1 prints refs like `ref 7ec78a59` and turn numbers like `#533`, and ends with a ready-to-run
`--open` line. Don't `find`/`rg` the raw JSONL. `--open` reads the same content faster, and it still
works for sessions the harness has since deleted.

## Queries: just type them

- No flag and no quoting needed: `navcom cerbos wave 2`. `--query "…"` also works, and both combine.
- Punctuation is safe: `10.10.1.223`, `don't`, `PR #76`, `cerbos-wave-2`, `main()`,
  `file.py`, `sg-0f12a…`, `user@x.com`. **Never strip punctuation by hand.**
- All words must be in one turn, prefix-matched. If nothing has them all, navcom automatically shows
  any-word matches and prints a `note:` line.
- Alternatives: `a OR b`, or a comma list `cognito, cerbos, terraform`.
- `"exact phrase"` falls back to its loose words if the exact phrase isn't found.
- Awkward shell quoting? Send the query on stdin: `navcom - <<'EOF'` … `EOF`.
- Prefer 2–4 distinctive words (ids, service names, error strings, file names) over sentences.

## Narrowing

```bash
navcom deploy --here                    # sessions from the current working directory
navcom deploy --project syrab2b         # project path contains "syrab2b"
navcom deploy --days 7                  # or --since 2026-09-01 / --since 12h, --until …
navcom deploy --claude                  # or --codex --gemini --pi --omo --opencode --goose, -p claude,pi
navcom deploy --user                    # only what the user typed;  --cmd = shell commands run
navcom deploy --newest -n 40            # newest sessions first, more hits
navcom goal --this-session              # only THIS conversation (recall after compaction)
navcom                                  # recent sessions with titles
```

- The current conversation is excluded from normal searches automatically. `--include-self` brings it back.
- `--this` means "the harness I'm running in", not the current directory. Use `--here` for the directory.

## Reading more

```bash
navcom --open 7ec78a59:533              # 3 turns either side of #533
navcom --open 7ec78a59:520-560          # a range of turns
navcom --open 7ec78a59 --user           # every user turn in that session
navcom deploy --context --window-turns 4   # expand every hit in place (larger output)
navcom deploy --json                    # structured output
```

## Behaviour worth knowing

- Parallel navcom calls are fine. A locked index costs about 3 seconds, then navcom searches what's
  already indexed.
- Read-only sandboxes work: it searches without refreshing and notes this on stderr.
- `--solo` and `--summary` call another LLM CLI, so they are slow (a hard 150s cap). Prefer the
  two-step recipe and summarize yourself.
- Unknown flags print a hint on stdout as well, so an empty result after `2>/dev/null` really does
  mean no hits.
- `navcom --where` shows which harness logs exist and index stats. `navcom --version` shows the version.

## Evidence pattern

When answering, separate:

- What navcom found: session ref, date, harness, project, turn numbers and the quoted snippets.
- What you verified now: current repo state, files and live services.
- What is memory-derived or stale: old deploys, cloud state and credentials, until revalidated.
