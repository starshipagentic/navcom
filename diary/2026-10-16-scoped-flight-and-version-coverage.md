# Scoped flight and version coverage

NavCom still orchestrates Starforge. This checkpoint improves automatic inputs,
readable native evidence, and procedural navigation; it does not introduce a
separate classifier or a curated project catalog.

## Decisions implemented

- Bounded source discovery reuses the native Starforge version-family adapter.
  Versions share the existing total code budget instead of early versions taking
  it all. Native experiment exclusions, Git ignores, explicit scopes, symlink
  limits and a three-second analysis deadline remain enforced. The adapter is
  shared with Connections & versions.
- District labels use a common terminal module path when one is supported by the
  actual members; otherwise they use filename-anchored terms or actual filenames.
  Raw tokens remain searchable. District IDs, parents and positions do not change.
- Both native search paths return an exact source/artifact/publication reference,
  including cached answers. Harvest and retrieval have separate dependency-aware
  fingerprints. Search-only edits no longer cause reharvest. Existing artifacts
  transition once on their next normal refresh; no forced full refresh occurs.
- The shared CLI/API Navigator resolves `find matrix in EXP32` before scanning.
  Unknown places return no evidence; ambiguous names return explicit path-bearing
  choices. `--choose` validates one returned ID inside the allowed boundary.
  `fly to EXP32 then find matrix` resolves, searches and returns a destination.
  These are procedural clauses; quoted/path queries remain literal.
- Browser search preserves its resolved scope and clean query through paging,
  Back, reload and journey links. Search alone leaves the camera in place. Travel
  carries the query into the destination. Clear invalidates pending responses.
  A changed scope checkbox applies to the next query, not existing result pages.

## Native and CLI proof

Ordinary live `sources discover --harvest` now retains 49 EXP29 v34 files,
including 46 Python files, versus the prior two documents. All 145 existing source
IDs and other source scopes were preserved. Repeating intake used cache:
0 analyzed / 1 cached, 0.089 seconds inside the worker. CLI `atlas refresh --space`
updated the chart; `atlas related` and `sources read` opened retained v34 API code.
No source records were synchronized by hand.

Public `atlas navigate "find matrix in exp32"` resolved one source and returned
both native evidence and related conversations. Public source CLI proofs opened
code and README evidence from saved bytes (`current_file_read=false`). Search
cache reuse was false, then true, then true at one publication.

Evidence: `/tmp/navcom-version-intake-proof/`,
`/tmp/navcom-scoped-matrix-cli.json`, `/tmp/navcom-search-pins-proof.json` and
`/tmp/navcom-district-label-proof/cli-proof.json`.

## Browser proof

In the real browser, `find matrix in exp32` preserved the galaxy's camera and
visible place positions while returning EXP32 evidence. Reload restored the same
scope. `fly to exp32 then find matrix` arrived with `matrix` still in the input;
Back returned to the original query and viewpoint. An ordinary result opened
README:9 from the retained harvest, with current working files unread.

`find login in syrenity-mobile` offered the separate standalone and nested app
paths before scanning. Choosing the nested app searched only it. Reload retained
the choice, and Back restored the unresolved choices without flying or scanning
globally. Controller regressions additionally prove that Clear cancels in-flight
work and pagination cannot widen a previous search after a checkbox change.

## Boundaries

No other codebases were changed. Names and documentary links do not establish
ownership or product succession. Coverage remains bounded and reported. Real
microphone capture, expert replies and captain takeover remain unverified; the
larger galactic goal is still active. No external publication was performed.

## Installed checkpoint

581 pytest tests and 130 BDD scenarios (699 steps) passed. Independent review
found two browser-state bugs; both were reproduced and fixed before installation.
The offline wheel was installed locally; all 36 runtime files match checkout,
wheel and installation byte-for-byte. The original flight bridge remains at
`http://127.0.0.1:62811/?view=space&local=1`.

Installed public CLI proof: `/tmp/navcom-installed-scoped-flight.json` resolves
EXP32 and searches one source. Compound CLI proof is
`/tmp/navcom-compound-flight-cli.json`. Live browser EXP29 now displays real
module labels such as `engine / grammar`, `engine / jobs` and
`engine / committee`. The temporary development tab/server were closed.

The installed browser completed `fly to exp32 then find matrix`, with EXP32 as
the destination and `matrix` retained in the input; Back returned to the galaxy.
Preview screenshot: `/tmp/navcom-installed-scoped-flight-bridge.jpg`.
