# Small local-harvest proof

Inputs: the owner's instruction that NavCom orchestrates Starforge harvest; the reuse survey; the existing analysis-stage trial. Starship is outside this experiment.

## P0 — Outcome

Make current selected local material discoverable with existing analysis tools, without rebuilding unchanged material during browsing.

Story: Travis searches work he has not pushed anywhere.
Outcome: results identify the actual source and associated conversation scope.
Proof: initial harvest finds material; an unchanged repeat analyzes zero sources; a changed source updates alone; deleted material disappears.

Decided: a bounded local experiment, preserving original sources and catalogs.
Deferred: production integration and cosmic classification.
Check: this proves ingestion and reuse, not an automatic universe.

## P1 — Boundary and parts

Refines P0 by separating discovery, harvesting, and reading.
Discovery supplies selected sources and conversation references. Harvesting validates and analyzes changed material. Reading queries the last complete harvest and never triggers analysis.

Decided: failed/busy refresh leaves the last complete result readable.
Deferred: scheduled maintenance and remote ingestion.
Check: no ship commissioning or other-codebase changes are required.

## P2 — Data and guards

Refines P1 by defining the exchanged records.
Source selection: discovery writes identity, origin, selected scope and conversation collection reference.
Source receipt: harvesting writes content signature, extractor signature, file count and cached analysis location.
Published view: harvesting alone writes the complete selected set and its receipts; readers treat it as immutable.

A source is absent, unchanged, changed or unavailable relative to the published view. Harvesting publishes a replacement only after all selected sources succeed. Removal from a selection removes it from the next published view. Missing sources are failures, not silent removals. Scan limits must be reported, not silently treated as full coverage.

Decided: source bytes and extractor changes invalidate cached analysis; source scope is explicit.
Deferred: identity across moves and catalog migration.
Check: each record has one writer and an inspectable origin.

## P3 — Flows

Refines P2 into execution steps.

When discovery is requested, list indexed source locations, resolve selected local roots, and emit the selected scope with conversation references.
When refresh is requested, show progress, acquire the writer slot, compare selected material with receipts, analyze changed material, then publish the complete result. On error or a busy writer, retain the previous result and explain why.
When search is requested, read the published result, restrict it to the chosen scope, call existing search, and return source paths plus conversation destinations.

Decided: repeated browsing does no harvesting.
Deferred: ranking changes, product ownership and visual representation.
Check: execute cold, unchanged, edit, delete, failed refresh, busy writer and scoped-search drills.

## Representation / borrowing (outside the ladder)

Lab-only Python CLI; existing NavCom Atlas project listing; unchanged Starforge Harvester analysis stage, Catalog, ProjectAnalyzer with dispatcher=False, GemFinder and concept_search. A small adapter snapshots explicit local scopes, fingerprints bytes and extractor code, serializes writers, and atomically publishes catalog generations. Private inputs/results stay under ignored private/. No external model or Starship dependency.

## Decisions

Locked by owner: NavCom orchestrates; reuse Starforge harvest; prove in a small lab first; Starship not required.
Assumed for this experiment: three bounded real source scopes plus synthetic edit/failure controls, content hashing, immutable local snapshots, no model calls.
Open: public CLI syntax, background refresh cadence, packaging Starforge dependency, full-source scan policy, product/experiment ownership, final UI.

## Execution ledger

Plan and diary written before implementation. Adapter built only in this lab. Controlled incremental/failure drills passed. Real three-source harvest and conversation handoff passed; the original discovery-query miss is retained. See HARVEST-RESULTS.md. Production integration and all open decisions remain deferred.
