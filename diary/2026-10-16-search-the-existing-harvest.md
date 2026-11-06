# October 16 — Search the harvest we already have

The captain searched `solve2` inside ThriveCart, then across the galaxy. Global
search found seven conversation families (including this troubleshooting chat)
but no source files. The actual command was preserved in Starforge's native
`claude-skills-backup` harvest under `project-learnv3-commands/solve2.md`.

Three gaps were verified: NavCom intake considered conversation project roots
but none of the 183 local repositories already recorded by Starforge; authored
agent-command Markdown was excluded, including hidden instruction folders; and
global navigation searched only source IDs represented on the saved chart.

## Decisions implemented

- Read native `Catalog.list_projects` through bounded read-only TinyDB storage in
  the installed Starforge runtime. Honor its directory resolver. Do not create a
  catalog, clone repositories, run an LLM, or modify Starforge/Starship.
- Share the combined inventory between `sources discover` and automatic chart
  upkeep. Pin the bounded queue, retain native provenance and exact conversation
  memberships. Native account names do not establish NavCom client ownership.
- Add `sources discover --inventory all|indexed|starforge` (default `all`). Existing
  offset/limit/harvest parameters still work. Native-only discovery needs no
  conversation index. Missing inventories cannot claim full coverage.
- Include conventional command/agent/skill Markdown and visible exported
  instruction folders. Preserve Git ignores, symlink exclusions, directory/file
  budgets and the exclusion of settings, secrets and unrelated hidden folders.
- Global search includes every published source using one immutable source
  publication for both native search paths and pinned file references. Explicit
  place scopes remain strict. A fresh source need not wait for chart publication.
- Inventory-policy upgrades retain explicit pauses, including legacy saved
  cursors. The next explicit continuation repins the upgraded queue.

## Proof, performed through the tools

The native inventory returned 183/183 existing repository roots in about 0.27 s;
the original catalog's hash and mtime were unchanged. Native inventory page 38
contains the command backup. These commands selected it through the catalog,
without manually registering a source or copying catalogs:

```sh
navcom sources discover --inventory starforge --offset 38 --limit 1 --harvest \
  --cache /tmp/navcom-galaxy/sources --json
navcom atlas navigate solve2 --global --space-cache /tmp/navcom-galaxy/space.json \
  --source-cache /tmp/navcom-galaxy/sources \
  --index /Users/t/.codex/navcom-index.sqlite --limit 40 --json
navcom sources read 6bdda158e6fe89c2 project-learnv3-commands/solve2.md \
  --limit 8 --cache /tmp/navcom-galaxy/sources --json
```

Page 38 is this observed native inventory order, not a persistent project identity.
Normal upkeep visits the complete bounded queue. The selected backup retained
153 files, including `solve2.md` and all eight companion agent definitions.
Initial harvest analyzed one source in 6.76 s. Repeating it analyzed zero,
reused one artifact, and took 0.071 s inside the worker.

Global CLI search found 21 native text matches and seven conversation families;
the command itself was first. Concept search returned zero gems, which is an
honest result for this command document. All 146 published source scopes were
searched. The installed CLI, run outside the checkout, repeated with 146 cache
hits and a 3.43 s source-search phase. The pinned reader returned the original
298-line command without reading its live working file.

Browser proof: typed `solve2`, submitted galaxy search, saw “21 source hits,
7 conversations”, clicked the original `solve2.md` result, and read its published
snapshot. Evidence is in `/tmp/navcom-solve2-results.png` and
`/tmp/navcom-solve2-reader.png`; command receipts use `/tmp/navcom-solve2-*.json`.

Regression evidence: 184 existing discovery/submodule/source/architecture tests;
17 inventory/union tests after final fixes; 35 navigation/cache tests; 57 instruction
intake/discovery/submodule tests (these groups overlap). Independent reviews found
and verified fixes for false complete-inventory reporting and legacy pause
migration. Native test fixtures isolate the owner's real Starforge catalog.

## Installed state and remaining work

Built `/tmp/navcom-solve2-dist/navcom-0.11.0-py3-none-any.whl`, installed locally,
and restarted the verified idle bridge with its token/task state retained:
`http://127.0.0.1:62550/`. Server PID 37514 runs the installed environment via
`/tmp/navcom-solve2-restart.py`. No PyPI publication or commit. Opening the bridge
started its ordinary bounded automatic inventory sweep using the new queue.

This is a general intake/search correction, not a curated `solve2` rule. The
backup is searchable globally; an authoritative link from preserved LearnV3
material to the ThriveCart place remains unresolved. The remaining native
catalog queue and inaccessible carried ship context mean whole-machine coverage
is still incomplete. No new ownership classifier was added.

The larger [galactic implementation plan](../docs/galactic-implementation-plan.md)
remains active. Continue with the [handoff](2026-10-16-galactic-navigation-handoff.md)
and [arrival/berth work](2026-10-16-arrivals-berths-and-place-questions.md); this
entry supersedes the earlier assumption that conversation-root discovery covered
the existing Starforge harvest catalog.
