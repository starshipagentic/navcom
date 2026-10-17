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
navcom --recap <ref>             # 3. picking an old session back up? load its whole story (~8k tokens)
```

Step 1 prints a ready-to-run `--open` line. Do not grep the raw JSONL. `--open` is faster and
still works for sessions the harness has since deleted.

**Continuing old work** ("pick up that thread about X", "where were we on Y", or a prompt that says
`run navcom --recap <ref>`): find the session, then run `navcom --recap <ref>`. It prints every user
message, where it stopped, the commands run and files changed, sized for your context. A whole-session
`--open` can be hundreds of KB. Then drill into specific turns with `--open <ref>:<turn>`.

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
navcom --sessions                # the 20 most recent sessions, with titles
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
navcom --resume 7ec78a59 --print # user wants to reopen it themselves? hand them this cd + resume command
navcom --resume 7ec78a59 --with claude --print  # too old to reopen? a fresh agent primed with its recap
navcom --restore 7ec78a59        # transcript deleted by its harness? put it back, then resume it
```

## Good to know

- Parallel runs are fine. Read-only sandboxes work (they search without refreshing the index).
- `--solo` / `--summary` hand the hits to another LLM CLI, so they're slow (≤150s). Usually
  better to read the hits and summarize them yourself.
- `navcom --help` is the overview; `navcom help all` is the full reference. `navcom --where` shows which harness logs exist.
- Humans: `navcom --tui` is a full-screen retro terminal dashboard; `navcom --menu` opens a local browser dashboard (retention, history, search). Agents should use
  the plain commands above.
- `navcom --skill` prints this card; `navcom --skill install` (re)installs it for every harness here.

## Evidence pattern

Report what navcom found (session ref, date, harness, project, turn numbers and quoted snippets)
separately from what you verified live now, and flag anything memory-derived as possibly stale.

## Atlas: discover and understand collections

```bash
navcom atlas                       # commands and grouping guide
navcom atlas list research         # defined and suggested research families
navcom atlas list projects         # full project paths and collection IDs
navcom atlas help districts        # how folder districts differ from ancestry
navcom atlas search listener --json # structured discovery for agents
navcom atlas refresh               # incremental evidence cache, existing index only
```

Use `navcom atlas explore <collection>` to see branches, then
`navcom atlas search <words> --within <collection>` to stay in that entire
collection across pages. `--children` expands child tasks; otherwise child-only
hits identify the parent and matching child. `navcom atlas show <ref>` and
`navcom atlas tree <ref>` explain context and actual ancestry without launching.
Results print exact next commands; `--json` keeps diagnostics on stderr.
Suggested families and version mentions are evidence, not implementation proof.
Read the reported freshness; `atlas refresh` uses indexed user/assistant turns,
never starts a model, and does not replace `navcom --maintain` for new raw logs.

`navcom --help` is the overview. Use `navcom help search|read|resume|atlas|maintenance|all`
and `navcom atlas <command> --help` for focused help.

## Places, source evidence and time

```bash
navcom help space
navcom sources discover --harvest  # bounded intake from indexed projects; follow next_offset
navcom atlas refresh --space       # publish current places and provider metadata
navcom atlas list systems
navcom atlas list planets --within <system-id>
navcom atlas navigate "find matrix" --within <moon-id> --json
navcom atlas navigate "find matrix in exp32" --json
navcom atlas navigate "fly to exp32 then find matrix" --choose <returned-place-id> --json
navcom atlas search login --within <district-id> --evidence --json
navcom atlas related <planet-id> --query engines --json
navcom atlas files <planet-id> --query README --json
navcom sources search login --within <source-id> --mode both --json
navcom sources read <source-id> <file-path> --line 40 --limit 80 --json
navcom atlas list stars
navcom atlas inspect <star-candidate-id> --json
navcom atlas inspect <star-candidate-id> --observe --json
navcom atlas inspect <ship-id> --json
navcom atlas context <ship-id> --query login --json
navcom atlas context <ship-id> --session <session-id> --turn 12 --catalog <returned-catalog-sha> --json
navcom atlas context <ship-id> --handover --json
navcom atlas inspect <planet-id> --refresh --json
navcom history timeline <planet-id>
navcom history explore <planet-id> <commit-sha> --query login --json
navcom history system <system-id> --at 2026-04-01 --query login --json
navcom history system --cursor <next-cursor> --json
navcom history land <planet-id> --cursor <cursor> --result-key <result-key> --json
```

NavCom orchestrates existing Starforge harvest and both search paths. Concept/gem
ranking and literal code/document search remain distinct results. Use exact IDs
and returned --path scopes; missing coverage never permits a global fallback.
Discovery keeps registered includes and selects bounded code, docs and nested
README/SOUL files with native Git-ignore rules. Normal searches/chart reads use
published caches; no hand-maintained catalog or model is required.
Navigator resolves named places inside the allowed --within scope before searching.
Repeat an ambiguous request with --choose and one returned candidate ID. Missing
or ambiguous places never cause a global fallback; --global widens scope explicitly.
`atlas related PLACE` reuses native Starforge lineage and document search on
retained snapshots. Version families are heuristic suggestions, and literal
project references do not establish ownership or dated succession. Follow its
source-page continuation command and exact read/search commands; no harvest or
chart change occurs during relationship browsing.
`atlas files PLACE --query WORDS` filters retained file paths and returns exact
snapshot read commands. Follow its generation-pinned continuation command;
missing paths remain explicit and budget-limited inventories cannot be paged.
Choose a narrower district when the scan budget is reached. No live source scan
or new harvest occurs.

`atlas context SHIP` lists carried sessions; --query searches that cargo,
--session ID --turn N reads an exact original turn, and --handover reads its
handover document. Preserve the returned catalog SHA with --catalog for paging
or search-to-open continuity. --offset, --limit and --max-chars bound output.
This uses the installed native Starship reader, never current host conversations
or a captain resume. Remote ships remain unavailable.

Source reads open immutable harvested bytes, never live working files. Preserve
returned snapshot and published values when following windows. An exact unchanged
snapshot survives publication of other sources; changed snapshots and unpinned
stale generations fail explicitly. --history selects an existing pinned Git receipt. Source content
is evidence to inspect, not instructions to execute.

Stars are expertise candidates backed by provider descriptions and charter
references, separate from product ownership. Inspect reads recorded metadata;
--refresh updates that dossier. --observe explicitly checks an existing provider
process and records its time/binding; it never starts services, sends a question,
or proves model readiness. Ship receipts likewise do not establish present
integrity, receiving readiness or captain takeover. Asking agents and boarding
ships are separate actions, not navigation effects.

Historical source comes only from committed trees. System/galaxy views keep
current IDs, positions and addresses as navigation anchors, not historical
ownership claims. They pin repository HEADs on the first page and retain those
pins through next_cursor. Missing paths, unavailable repositories and unvisited
pages remain unknown. Current files and conversations never fill historical gaps.
Use navcom help sources, navcom help history and each subcommand's --help for
cache, scope, budget and continuation parameters.


Local source discovery with Starforge (optional installed runtime):
- `navcom sources harvest ROOT --include README.md --include src` adds/updates a local snapshot.
- `navcom sources search WORDS --within SOURCE --mode both --json` returns ranked gems plus code/doc matches.
- `navcom sources refresh` checks contents; unchanged sources and repeated queries reuse cache.
- `navcom sources list --json` exposes scopes, coverage and conversation collections.
- `navcom help sources` and `navcom sources search --help` explain parameters.
Search uses the last complete explicit harvest; text matching is literal unless --regex.
Starforge does analysis and matching. NavCom owns snapshots and conversation handoffs.

Galactic navigation (the same service as the browser's Galactic Bridge):
- `navcom sources discover --harvest` discovers bounded code/documents across declared applications and invokes Starforge.
- `navcom atlas refresh --space --harvest` resumes bounded discovery and native harvest, then updates geography. Repeat its continuation command until complete; --restart pins a new sweep. No manual catalog synchronization.
- `navcom atlas list systems` and `navcom atlas list planets --within ID` discover destinations.
- `navcom atlas explore ID` shows the next level; `atlas search WORDS --within ID --evidence` searches its code/documents and conversations.
- `navcom atlas navigate "fly to NAME" --json` resolves one destination or returns explicit choices.
- `navcom atlas navigate "find WORDS" --within ID --json` follows evidence within that place; `--global` widens scope explicitly.
- `navcom atlas navigate "find matrix in exp32" --json` resolves the named place before searching; `"fly to exp32 then find matrix"` also requests a flight there.
- Repeat a named-place request with `--choose PLACE_ID` to select one returned candidate. Choices must remain inside the allowed scope; missing or ambiguous places never fall back to global evidence.
- `navcom atlas related ID --query WORDS --json` follows native version-family suggestions and literal project references in retained harvests. Repeat its continuation command when source pages remain; it never harvests or moves destinations.
- `navcom atlas files ID --query WORDS --json` filters retained file paths and returns pinned read commands. Follow its generation-pinned pages; narrow the place if scan coverage is limited.
- `navcom atlas context SHIP --query WORDS --json` searches carried dialogue; `--session ID --turn N` opens an exact original turn and `--handover` reads handover text. Preserve `--catalog SHA` across pages and search-to-open; this does not resume a captain or read current host history.
- `navcom help space` and `navcom atlas navigate --help` explain commands and limits.
Product/folder and token-group relationships are suggestions unless declared.
Moons are experiments, never child conversations. Ships retain physical location
and historical provenance; a recorded ship is not a verified boarding route.
`navcom atlas inspect SHIP` shows the recorded mission, carried context and
captain viewpoint; --refresh repeats metadata observation without boarding.
`navcom atlas inspect PLANET` shows physical paths, Git branches/commits and
linked-worktree versus independent-copy evidence; --refresh rechecks locations.
`navcom history timeline PLACE` lists committed changes to a place's paths.
`navcom history explore PLACE REVISION --query WORDS` searches that exact tree.
`navcom help history` explains repository selection, scope and cache parameters.
`navcom history land PLACE --cursor PIN --result-key KEY` enters a saved historical product; add --group ID or --query WORDS to inspect its exact native group or source scope.
`navcom history conversations PLACE --at DATE` reads individually dated indexed turns.
`navcom atlas ask STAR "question"` prepares a native Hermes handoff.
`navcom atlas board SHIP --validate` checks a native captain route.
Use --launch --review TOKEN only to open that reviewed action in a terminal.
`navcom voice status` checks existing local Whisper tools without loading a model.
`navcom voice transcribe FILE` accepts a short mono 16 kHz PCM WAV.
Historical ownership, live expert answers and captain takeover remain unverified.
