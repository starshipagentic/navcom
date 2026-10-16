# Starforge source search is now a NavCom CLI capability

Implemented `navcom sources harvest`, `refresh`, `list`, and `search`. NavCom
orchestrates local source selection, immutable snapshots and atomic publication;
Starforge's existing Harvester analysis stage, ProjectAnalyzer, GemFinder,
concept_search and registered code-search callback do the analysis and retrieval.
No classification or search algorithm was recreated. Starforge and Starship code
were not changed. Starforge is optional for normal conversation search.

Synchronization is performed by commands, not by maintaining catalogs manually.
`harvest ROOT` registers/updates the scope; `refresh` checks every registered source
by content hash, reanalyzing only changed sources. The adapter's and Starforge's
implementation fingerprints also invalidate stale harvests. Search reads the
last completed snapshot and memoizes queries by snapshot and options. It does not
silently harvest on every query. Writer contention and failed refreshes leave the
previous snapshot searchable. No model is invoked or downloaded.

Built a wheel, installed it into an isolated environment, and ran its actual
`navcom` executable from `/tmp`, outside the checkout. Then installed that wheel
into the existing local NavCom environment and verified the normal `navcom`
command. Used `navcom --skill install` to distribute the updated skill card through
NavCom's own installer. No PyPI publication.

## Observed CLI proof

Selected bounded scopes, not whole-machine coverage:

| Source | Scope | Files |
|---|---|---:|
| NavCom | README, atlas and discovery modules | 3 |
| EXP32 | README and signal_lab | 132 |
| Syra B2B | README and src/lib/auth | 29 |

- `class Discovery`: text search found navcom_discovery.py despite zero concept hits.
- `Signal proposals and protocol goals`: text search found CONTROLLER-CONTRACT.md;
  concept search returned related gems separately. The printed conversation command
  returned nine matching EXP32 conversations in the correct project collection.
- `isHumanMembershipRole`: text search found the small role-grant-policy.ts omitted
  by gem selection; concept path had no hits.
- `reader`: sixteen concept hits and twenty capped text hits within EXP32.
- Repeated queries all hit the query cache. Packaged process times were about
  0.25–0.27 seconds for those repeats, including startup.
- Unchanged refresh analyzed zero of three sources: 0.019 seconds in the worker,
  0.232 seconds including packaged CLI startup. Normal installed CLI repeated the
  zero-analysis result, with 0.018 seconds in its worker.

Machine-readable proof: `LABS/spatial-discovery/private/cli-integration/receipt.json`
(private/ignored). Full NavCom test suite: **153 passed**. BDD: **130 scenarios,
699 steps passed**. Integration tests exercise real Starforge through the CLI,
including edit/delete invalidation, literal versus regex matching, source scope,
failed publication, lock contention, and continued reads of the old snapshot.
An initial unqualified pytest run collected tests inside harvested lab repositories;
the project suite was correctly rerun as `pytest tests`.

## Boundaries retained

No UI changes. No automatic planet/product ownership claims. Source discovery
links an exact root to NavCom's existing indexed project collection. Text search is
Starforge's existing regex scanner over cached files (literal phrases by default),
not semantic document retrieval. A new text query scans its selected snapshots;
an identical query uses the query cache. Starforge's private local-harvest API and
Rich table output adapter are compatibility seams covered by integration tests.
Refresh remains explicit, and old cache generations are retained without automatic
pruning. Original source trees and Starforge's global catalog are not synchronized
or modified by this feature.
