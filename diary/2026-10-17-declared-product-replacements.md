# October 17 — Follow an explicit product replacement

The owner resumed work after upgrading usage. The prior experiment-list review
finished cleanly; the next required boundary was product identity and generations
in the [active plan](../docs/galactic-implementation-plan.md). The
[spatial diary](2026-10-15-a-universe-you-can-return-to.md) remains the authority:
products can evolve, a substantial successor may be another planet, and exact
ownership must come from evidence rather than a name heuristic.

## Decision and implementation

This pass extends the existing `.navcom-space.json` root declaration with
`supersedes: [declared-id]`. Ordinary chart refresh resolves exact declared product
IDs into separate one-hop edges. The existing `atlas related` service, CLI and
Connections & versions panel show those declarations separately from native
Starforge version-family suggestions and document links. The CLI help and
[native relationship contract](../docs/native-relationships-contract.md) explain
the inputs, bounds and distinctions.

There is no new library, search engine, database, catalog or synchronization step.
Browsing reads the published chart. Source analysis continues through Starforge;
if it fails, available declarations remain readable with the error disclosed.
Root metadata is read during the normal refresh, not on each query.

A shared declared ID keeps its existing meaning even across multiple repositories.
A replacement edge itself never merges different product IDs, containment, files
or conversation memberships. Conflicting claims, invalid fields, missing targets,
self-links and cycles produce diagnostics. Unavailable copies retain explicitly
stale observations. Deliberate multiple predecessors/successors remain possible;
no transitive relation or replacement date is invented.

One integration check caught a usability gap: an invalid declaration with no ID
and no harvested source would hide its own error. Scoped diagnostics now also
match the exact recorded declaration path, and owner-declared places retain the
Connections & versions action so the reason can be read.

## Proof

The installed CLI created an unfamiliar disposable Orchard Lab chart through
ordinary refresh, from two actual Git roots and two natively indexed fixture
conversations. `atlas related 'Aurora Classic'` returned Aurora Next as the
explicit successor. Following its returned `atlas show` command reached the
correct product; the products' conversation collections remained disjoint. No
harvest or native runtime was required for these declaration-only reads. CLI and
HTTP results agree, and reads leave the chart and index unchanged.

The installed browser journey then opened the same fixture:

1. Enter Aurora Classic and open Connections & versions.
2. Read “Aurora Next supersedes Aurora Classic” and the declaration provenance.
3. Fly to Aurora Next: only its own scheduling conversation appears.
4. Back restores the exact previous URL and original connection panel.
5. Reload retains that original product and connection panel. Captured browser
   error logs were empty.

![Declared replacement, original context and exact Fly actions](evidence/2026-10-17-declared-product-replacement.png)

The disposable browser server disabled only unrelated automatic intake. Chart
creation and all refresh/related/show commands ran through the installed CLI;
relationship results and navigation were not mocked. The fixture did not write
any declarations to the owner's real projects or alter the owner's chart.
Receipt: `/tmp/navcom-succession-lab-receipt.json`; its `base` directory contains
`cli-proof.json`. The lab server was stopped after proof; it is not the user-facing bridge.

Verification boundaries: 18 succession tests; five service/CLI/API tests; 167
existing relationship/CLI/architecture tests; 42 UI/action-rail/historical tests.
The final chart continuity gate passed 82 tests. The last diagnostic-only rail
adjustment passed its affected test. Some suites overlap; these are not distinct
user journeys. A new native historical regression starts a fresh dated session
from an enriched current chart and proves current declarations never enter its
dated nodes, center, breadcrumbs or edges.

## Current runtime and next boundary

Installed version remains 0.11.0, from
`/tmp/navcom-succession-final-dist/navcom-0.11.0-py3-none-any.whl`.
Only four installed runtime files changed in this pass: `navcom_space.py`,
`navcom_relationships.py`, `navcom_atlas_cli.py`, and `navcom_space.js`.
The earlier bridge process was gone. The restored final bridge is
`http://127.0.0.1:62550/`, PID 47887, exec session 91624, running
`/tmp/navcom-succession-final-restart.py`. Check identity before any restart.
It uses the existing `/tmp/navcom-galaxy` chart/source/history caches and ordinary
NavCom index. The real galaxy loaded successfully in the browser and ordinary automatic intake resumed. No PyPI publication occurred.

This proves the root-product capability, not the entire identity problem.
Explicit identities for several products within one repository remain open.
The owner has not decided the exact earlier/later Syrenity successor pairing;
no real pair was asserted. Today's declaration is not a historical replacement
date. Current declarations remain excluded from dated views. Live microphone
acceptance and visible captain takeover remain the separate human gates in the
plan. Original missing ThriveCart transcripts remain unrecovered as documented
in the [basic-search diary](2026-10-16-basic-solve2-search.md).
