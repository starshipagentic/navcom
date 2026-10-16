# Local harvest flow — measured proof

2026-10-15. **The bounded orchestration flow works; exhaustive source search and cosmic classification are not proven.** All implementation remains in this lab. No Starship dependency, original Starforge catalog writes, GitHub cloning, model calls or production NavCom changes.

## What ran

The lab CLI asks the installed NavCom Atlas CLI for exact indexed project roots and their conversation collection IDs. The selected test scopes are:

- NavCom: README, Atlas module, discovery module — 3 files, 1 selected gem.
- EXP32: README and signal_lab subtree — 123 files, 88 selected gems.
- Syra B2B: README and src/lib/auth subtree — 29 files, 26 selected gems.

These paths are test selection data, not special-case rules inside the adapter. The algorithm accepts any discovered root with explicit includes. File/byte limits fail visibly rather than silently truncating. Exclusions and selected scope are retained in receipts. This is not a complete harvest of those repositories.

Flow: discover → snapshot selected local bytes → unchanged Starforge harvest analysis stage → private catalog → unchanged Starforge concept search with scope applied → original source path and NavCom conversation command.

## Measurements

One run on this Mac, function wall times; discovery, interpreter startup and conversation handoff latency are not included in these timings.

| Operation | Result | Seconds |
| --- | --- | ---: |
| Initial harvest | 3 sources analyzed, 155 files, 115 gems | 0.683 |
| Unchanged refresh | 0 analyzed, 3 cached, no new publication | 0.019 |
| EXP32 `reader` | 8 scoped hits | 0.049 |
| Syra B2B `cerbos` | 6 scoped hits | 0.002 |
| NavCom `discovery` | **0 hits — retained failure** | 0.001 |
| NavCom `atlas` | 1 scoped hit | 0.001 |

The returned EXP32 conversation command was actually executed: it returned two result nodes within the expected project collection. Atlas reported stale discovery suggestions; that limitation remains visible. The flow does not refresh NavCom's separate conversation index.

## What was verified

Two automated test methods exercise the incremental journey and input boundaries. They passed after the final adapter changes:

- Initial harvest populates a catalog with searchable material from two independent synthetic sources.
- Unchanged refresh and repeated searches cannot invoke harvesting: the test patches that call to raise if invoked.
- Changing content while preserving the old modification timestamp still reharvests exactly one source.
- Deleting a source file removes its former searchable gem.
- Changed extractor identity invalidates both source analyses.
- Injected analyzer failure and unavailable input leave the previous published pointer unchanged.
- A held writer lock rejects another refresh while cached search remains usable.
- Scoped search excludes the other source even when both contain the same term; unknown scope is rejected.
- Removing a source from the selection removes its results from the next published catalog.
- Hidden environment files and symlinks are excluded with coverage records; escaping scopes and oversized input are rejected.

These synthetic mutations occur only in temporary test folders. The real project sources are read-only inputs. Publication uses immutable artifacts/catalog generations and an atomic current-view pointer. Failed attempts may leave unreferenced lab artifacts; garbage collection is deliberately deferred.

## Failure retained rather than hidden

The first real-data run stopped on `discovery` returning no hits. Inspection showed Starforge selected `navcom_atlas.py` as a gem but not `navcom_discovery.py`. The second run retains that query/result and additionally proves the `atlas` query. This is not a fix for the missed file.

Starforge GemFinder selects interesting files; it is not an exhaustive source index. It also excludes some extensions supported by the broader Starforge token tools. The adapter must not promise every source file is searchable just because harvest succeeded. A later experiment should test existing Starforge code-search alongside gem search before inventing another indexer.

Other limits: no automatic product ownership, no background refresh scheduling, no complete repo/worktree identity across moves, no remote ingestion, and no reader-side freshness scan. Search explicitly identifies its data as the last complete harvest. Root identity is path-derived for this lab. Analysis-stage failures are guarded with an independent gem-count check, which repeats gem extraction on changed sources and is included in the measured cost.

## Run the proof

From the NavCom repository:

```sh
~/.local/pipx/venvs/starforge/bin/python -B LABS/spatial-discovery/run_harvest_proof.py
~/.local/pipx/venvs/starforge/bin/python -B -m unittest discover -s LABS/spatial-discovery -p test_harvest_flow.py -v
```

The proof prints its isolated cache path. To browse it, substitute that exact path:

```sh
~/.local/pipx/venvs/starforge/bin/python -B LABS/spatial-discovery/harvest_flow.py --cache <printed-cache-path> search reader --within exp32-hybrid-jev-cbt
```

For another bounded selection, use `harvest_flow.py discover ROOT --include RELATIVE_PATH` (repeat `--include`), collect returned records in a JSON array, then `harvest_flow.py --cache LAB_CACHE refresh SELECTION.json`. Public NavCom syntax is not changed or finalized.

Private receipt: `private/local-harvest-proof/receipt.json`; selection: `private/local-harvest-proof/selection.json`; immutable snapshots, coverage and catalogs live in the receipt's cache path. They remain Git-ignored.

Decision: keep the orchestration approach, reuse Starforge, and preserve the boundary between selected gems and exhaustive search. Do not promote this into the production UI yet.
