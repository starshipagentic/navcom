# Starforge history: verified contract

2026-10-16. This is a bounded lab result, not an implemented NavCom time slider. No Starforge or production NavCom code changed.

## What can be reused

| Existing API | Actual evidence and limits |
| --- | --- |
| [`file_evolution.trace_file_evolution(repo, relative_file, max_commits=50)`](../../starforge/src/starforge/file_evolution.py) | Runs `git log --follow`, then `git show SHA:path`. Returns commit summaries, line counts, and function additions/removals. Historical code comes from Git blobs, not the working tree. Dates are **author dates**, reduced to a day; SHAs are shortened to eight characters. |
| `starforge file-evolution FILE --repo ROOT --max-commits N` | Existing CLI over that same function; useful explanatory timeline, not a historical tree or as-of selector. |
| [`catalog_evolution.get_repo_creation_date(repo)` / `build_timeline(harvest_dir)`](../../starforge/src/starforge/catalog_evolution.py) | **Failed the fixture:** reports the latest commit date as creation. It uses `git log --reverse --format=%ai --max-count=1`; the limit selects the latest commit before reversing. Do not use this field as repository birth until fixed upstream and retested. |
| [`LineageDetector`](../../starforge/src/starforge/lineage.py) / `starforge timeline` | Name/qualifier-based version relationships, not historical states. CLI dates use gem filesystem `mtime`; those are not as-of evidence. |
| [`ProjectAnalyzer(dispatcher=False).analyze(snapshot, name)`](../../starforge/src/starforge/analyzer.py) | Works unchanged on an isolated committed tree. In the fixture it describes the old and new product using their respective historical README. This is the reusable analysis stage for a future snapshot adapter. |

`trace_file_evolution` does not return file bodies or complete historical products. Markdown/JSON changes produce commit and line-count evidence, without semantic product-change descriptions. Source inspection also shows that rename-following retains the requested pathname when reading old blobs, so earlier names can be omitted. Git failures can become empty output, and a capped history is not the repository's complete history. These limitations need explicit coverage in any adapter.

## Disposable proof

Reproduce from the NavCom checkout:

```sh
~/.local/pipx/venvs/starforge/bin/python -B LABS/spatial-discovery/prove_history.py
```

The [script](../LABS/spatial-discovery/prove_history.py) creates a temporary Git repository with two dated commits, changes its README, app manifest and Python implementation, and then adds uncommitted marker text to all three files. Their filesystem mtimes are deliberately set to 2001. Git configuration is isolated; the temporary fixture is removed after the run.

| Commit | Author date | Committer date | Recorded state |
| --- | --- | --- | --- |
| `6a4214663352436b33fcfe0f32660912f8cd750d` | 2025-01-01 10:00 UTC | 2025-01-02 11:00 UTC | `quartz-classic`; Password login; `password_login` |
| `aba5df5b802b7e606bb81ae210c7f757196c38fc` | 2025-06-01 10:00 UTC | 2025-06-02 11:00 UTC | `quartz-cloud`; Cognito login; `cognito_login` and `refresh_token` |

Measured on this Mac:

- Three native file-history calls: **0.144 seconds**; entire disposable proof: **0.422 seconds**.
- Native Python history reports two commits, the expected function removal/additions, and line counts **2 → 5**. README history is **3 → 3**; package manifest history is **4 → 4**.
- Native creation-date detection incorrectly reports **2025-06-01**, retained as a failed check rather than hidden.
- `git archive` at each full SHA, followed by unchanged Starforge analysis, returns **Quartz Classic** and **Quartz Cloud**, respectively. The January tree contains neither Cognito content nor the uncommitted marker. Both snapshots exclude the dirty marker; source Git status remains unchanged.

This proves a historical Git-tree → existing Starforge-analysis route. It does not prove historical deployment, runtime availability, complete product ownership, cross-repository synchronization, renames, shallow histories, submodules, or Git LFS contents.

## Current harvest is observation, not chronology

Live inspection of the published NavCom source cache found:

- Generation: `catalog`, `published`, `sources`.
- Artifact receipt: `source`, `signature`, `extractor`, `coverage`, `gems`.
- Snapshot: selected working-tree bytes, **no `.git`**.
- Starforge catalog `created`, `updated`, `last_scan` are ingestion timestamps; gem `mtime` reflects snapshot filesystem state.

There is no recorded commit, tree identity, authored/committed timestamp, or link to a historical branch. Existing artifact directories preserve bytes, but their names and timestamps cannot reconstruct when those bytes were the project's real state. Their `published` time can support “observed by NavCom at this time,” not “this product existed exactly like this on that date.”

## Narrow next adapter

1. Resolve a selected Git ref to an immutable full SHA. Record both author and committer timestamps, selected ref/tip, tree SHA, and observation time. A calendar selection must name its rule—for example, a recorded commit on the selected branch before the cutoff. Commit dates are editable metadata, not proof of real-world availability.
2. Materialize bounded selected paths from that **one commit tree** using Git's existing object/archive interfaces. Inspect historical manifests to select historical app roots; never fill missing old files from the current working tree. Reject/disclose missing objects, oversized material, shallow history and unsupported object types.
3. Feed the tree into existing Starforge harvest, analyzer, token grouping, concept search and broad document search. Cache by repository identity, full commit/tree SHA, selected scope and extractor signature. Preserve explicit `git_revision` versus `working_tree_observation` provenance.
4. Rebuild the displayed product/district descriptions from those historical artifacts. Use native `trace_file_evolution` as explanatory change evidence; do not substitute its short SHAs, function counts, or mtime-based lineage labels for the historical snapshot.
5. Scope conversation evidence by **turn timestamps** and disclose independent chronology. Today's session last-activity date, current ship readiness and current machine location must not silently appear as historical facts.

The new work is revision selection, bounded snapshot intake and temporal provenance. Starforge remains the analysis/search engine. Its catalog-creation-date bug is an upstream repair candidate, not a reason to invent a competing history classifier.
