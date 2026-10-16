# Readable flight and native connections

The bridge should help a person recognize a destination and return to their train
of thought. This checkpoint keeps the existing ontology and Starforge foundation.
It does not assign new ownership or invent product succession.

## Decisions implemented

- Desktop and narrow windows use the same two-dimensional chart. The initial
  camera keeps names readable; Fit deliberately shows the whole chart. A small
  Overview pans the camera, with keyboard equivalents. Existing projected places
  retain their positions when new destinations arrive. Back restores the camera,
  query, selection, geometry and open evidence panels. Same-named products show
  distinguishing path suffixes, with full paths in their inspector.
- A normal fresh `navcom --menu` indexes native conversation logs before automatic
  discovery and harvest. Pause persists through reload; Continue resumes. Time
  and page limits explain why a pass stopped and keep its checkpoint. Explicit
  custom-index CLI refresh does not unexpectedly ingest unrelated host logs.
- `atlas related PLACE` and the bridge's Connections & versions panel share one
  service. It uses Starforge's existing lineage detector, broader code/document
  search and optional concept search over retained harvests. Actual containing
  paths supply context for bare version names; experiment namespace distinctions
  remain native. No hand-maintained project or version mapping was added.
- Version cards expose retained file counts, representative source reads and exact
  scoped CLI searches. A matching version is visible first; other returned family
  members remain expandable. Both search paths retain separate headings and
  expandable results. Documented links can be read and followed to known places.
- Literal project links are not ancestry. Broad directory references cannot turn
  an unknown child into its container. Exact-file district searches cannot widen
  to the enclosing version directory. Analysis reads one source publication and
  immutable artifact identities, with bounded source pagination and cache reuse.

## Proof and limits

Native public CLI tests preceded the UI. Real EXP29 returned the semantic
classifier version family; a returned command read v32 engine/api.py from its
saved artifact. EXP32 returned its README line 15 link to Semantic Observatory.
Repeated CLI requests reused cache, took about 0.55 seconds, and invoked no
harvest. The contract is in `docs/native-relationships-contract.md`.

A fresh installed-wheel menu test, without a seeded index or manual refresh,
automatically turned one native conversation into one harvested source and the
Aster/instrument destinations. A warm reload used cache. Pause survived reload,
and Continue completed at the same viewpoint.

Real browser tests verified narrow/desktop coordinates, readable zoom, overview
panning, keyboard navigation and a Syra product round trip with identical camera,
search, selection and positions. EXP32 connections found matrix documents; flying
to Observatory and Back restored the experiment's query and chart. Browser source
reading exposed a separate publication race: harvesting another project made an
unchanged pinned source appear stale. The final reader verification is recorded
below rather than treating the earlier CLI success as end-to-end proof.

The broad gate passed 545 pytest tests and 130 BDD scenarios (699 steps). Later
reader/UI changes require their focused gate and final installed proof below.

Coverage is still partial. v34 has two retained documents, not a complete source
snapshot. Native version families may later help balance intake across versions;
that change is not implemented here. Some native district labels remain awkward
and need evidence-preserving presentation work. Real microphone capture, an expert
reply and captain takeover are still unverified. The larger goal remains open.

## Installed checkpoint

The reader now accepts a prior publication only when an explicit artifact key
still exactly matches that source's current validated receipt. Unpinned stale
reads and changed artifacts continue to reject. Returned commands use the current
verified publication; provenance retains the originally requested publication and
does not mislabel registry time as source capture time. A real CLI sequence
harvested an unrelated source and proved the original pin still readable, then
changed the original source and proved rejection. The browser read both v34's
retained protocols/README.md and EXP32's exact Observatory passage successfully.

The final focused service/browser/HTTP gate passed 76 tests; the later version-card
presentation check passed 17 UI tests. Native-reader tests passed 31 cases.
The wheel was rebuilt offline and installed locally. Checkout, wheel and installed
bytes match across all 35 runtime files. Installed public `atlas related` and its
returned `sources read` command opened README:15, with zero harvest calls and no
live-source read. Installed browser proof opened the same passage. No external
package release was made.

The user bridge remains open at `http://127.0.0.1:62811/?view=space&local=1`.
Screenshots: `/tmp/navcom-installed-flight-bridge.jpg`,
`/tmp/navcom-installed-connection-source.jpg`, and
`/tmp/navcom-related-exp29-browser.jpg`. Installed CLI evidence is
`/tmp/navcom-galaxy/installed-related-proof.json`.
