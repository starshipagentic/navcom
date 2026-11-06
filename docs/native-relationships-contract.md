# Native relationship evidence

NavCom exposes explicit product replacement declarations, retained version families and literal links between known source roots. These are separate kinds of evidence. Browsing reads the published chart and immutable Starforge harvest artifacts; it neither harvests nor scans the current project tree.

## Explicit product replacements

A `.navcom-space.json` at a repository root or an already discovered application
boundary can name a stable product ID and the IDs it supersedes. For example,
`apps/mobile-v1/.navcom-space.json` declares `{"id":"aurora-v1","kind":"planet"}`;
`apps/mobile-v2/.navcom-space.json` declares:

```json
{"id":"aurora-v2","label":"Aurora Next","kind":"planet","supersedes":["aurora-v1"]}
```

The ordinary `navcom atlas refresh --space` reads this metadata from discovered
roots and applications. Applications come from the existing runnable workspace
and native app discovery; declaration files do not trigger a recursive scan or
turn arbitrary directories into products. There is no separate catalog to
synchronize. `navcom atlas related PLACE`
then exposes the resolved declarations and exact commands for either endpoint.
No Starforge runtime or source harvest is required to read declarations already
in the chart. Native family and document analysis still uses the existing
Starforge path; if that analysis fails, available declarations remain readable
and the source error is disclosed.

Only literal IDs belonging to declared products resolve. Missing endpoints,
conflicting declarations, self-links and cycles stay unresolved with reasons.
An explicit shared ID retains its existing meaning: repositories can belong to
the same declared product. Conflicting replacement declarations for that identity
remain unresolved. Multiple intentional predecessors or successors
are allowed; no transitive relationship is manufactured. Descendant applications
do not inherit their containing repository's product replacement claim.

Each application declaration belongs to that exact application: its ID, label,
description and replacement links do not leak to siblings. Application kind is
omitted or `planet`; the repository's system is used unless explicitly declared
otherwise. Files retain their exact application scopes, and conversations retain
the existing most-specific application attribution. A declared application uses
the same identity rule as a declared root product, so moving it within a
repository or splitting it into its own repository preserves its ID. Adding an
explicit ID for the first time changes an automatically derived ID; old automatic
bookmarks are not redirected. Linked paths and linked declaration files are not
followed.

The chart stores `supersedes` edges separately from containment. A successor and
predecessor remain distinct places with their own files, conversations and
coordinates. Declaration paths and observation times are retained; an unavailable
location is marked stale. An observation time is **not a replacement date**.
Historical views continue to exclude current declarations. No real project is
assigned a successor by this feature.

## Shared interface

`navcom_relationships.related(space_cache, source_cache, within, query='', limit=20, seconds=15, offset=0)` returns the selected chart `center`, `declared_relations`, `declaration_diagnostics`, `families`, `references`, optional native search `evidence`, `coverage`, publication/fingerprint, and copyable CLI/continuation commands. CLI: `navcom atlas related PLACE [--query TEXT] [--offset N]`.

Declared relationships touch the selected place or one of its descendants;
parent declarations do not widen a child query. `--query` filters their labels
and literal declared IDs. `--limit` caps each category, and result counts expose
truncation. Source offsets continue to paginate native scopes; declarations are
chart metadata and do not change between source pages.

Each family is a `version_family_suggestion`. Its members preserve exact source-relative directory paths, retained file counts, any exact existing chart destination IDs, and `scope_paths` intersected with the originally selected scope. Generated native search commands repeat those exact paths, including file-only scopes; they never widen a district to the containing version directory. Each member also exposes at most three `representative_files`, selecting a retained README first, supported code next, then other retained files. Each file has a `source_ref` containing `source_id`, actual file `relative_path`, `line`, immutable artifact `snapshot`, and source publication `published`. Destination matching uses the source roots pinned in the native result, not a newer source-cache publication.

Each reference is a `documented_path_reference` with the originating file and line, target root, exact existing destination IDs, and the same pinned `source_ref`. Cards receive only the matched target path as their excerpt, so unrelated environment assignments on that line are not copied into cards. The source reader can open the cited document. Literal links are not lineage claims.

## Existing Starforge operations reused

* `starforge.lineage.LineageDetector.detect_repo_lineages`, with its native normalization, namespace exclusions, version extraction and score. Input rows come from sibling directories in the retained source snapshot. Bare version names erased by native normalization receive their actual containing path as context; other names remain unchanged, preserving the native distinction between numbered experiments and versions. At least two distinct native positive versions are required. Scores are native scores, not probabilities; returned ordering is heuristic, not chronology.
* Existing `navcom_sources_worker.combined_search(mode='text', regex=True)` calls Starforge's `code-search` for known absolute source-root references in retained Markdown. Longest roots take precedence. Existing discovery container policy and cached repository evidence constrain broad containers to exact-root mentions, so an unharvested child path cannot be mislabeled as its ancestor container.
* Optional query evidence uses existing `combined_search(mode='both')`, preserving native concept and broader text search and the selected source paths. The query filters family labels/paths; literal project references remain a separate unfiltered evidence list within the selected scope.

All computation is procedural. No model, embedding service, project command, agent, or network endpoint runs.

## Bounds and caching

Each request processes at most eight source scopes, with explicit `next_offset`/`continue_command`; no eligible scope is silently dropped. Per source: at most 20,000 retained file paths, 2,000 directories, 500 siblings per native grouping, 128 families, and 100 Markdown reference hits. Requests have a 1–30 second process deadline and bounded output. Omitted sets and original harvest limits are disclosed. Invalid or missing saved scopes fail without global fallback; absent snapshot paths remain disclosed rather than reading current files. Snapshot links are rejected.

The relationship memo fingerprint includes the exact request, source publication state, Starforge extractor signature and adapter code. Repeating a stable request reuses the memo. A source harvest or adapter change invalidates it. Source reader citations pin the publication and immutable artifact; they do not substitute changed live files.

## Measured CLI proof, 2026-10-16

The public `navcom atlas related` command against the automatically harvested `/tmp/navcom-galaxy` cache found EXP29's `services/semantic-classifier` family, including v32 (41 retained files), v33 (29), and v34 (2). EXP32 returned the literal Observatory link at `README.md:15`; the command it returned opened that exact line through `navcom sources read`. It says Observatory has its own home and that chatbot implementation remains in EXP32. Repeating the public command reused cache with zero harvest calls (about 0.55 seconds in this run). The misleading `/Users/t/dev` ancestor reference is excluded.

Unfamiliar native fixtures cover `engines/v1`–`v3`, preserve separate `LABS/exp91`/`exp92`, exact scoped search, independent project links, unchanged-chart behavior, cache invalidation after harvest, dirty-live-tree isolation, pagination, broad ancestor rejection and linked snapshot rejection.

## Native version-balanced intake

The shared input adapter now lives in `navcom_native_families.py`. Automatic discovery passes it only directory paths already accepted by the existing bounded code walk. The resulting native version-family member roots become round-robin sampling buckets alongside application and retained manifest roots. They are sampling boundaries, not new moons, product ownership or historical succession. Git ignore rules, symlink exclusions, code/metadata byte and file budgets, and explicit registered includes are unchanged.

The optional native operation has a three-second total deadline covering runtime resolution, cache lookup and analysis. Its cache is outside the source tree beneath the configured source cache. Its fingerprint covers accepted directory paths, containing-source label, native lineage implementation, shared adapter and Python version. Cache-hit telemetry stays out of source metadata so repeating automatic discovery does not invalidate an unchanged harvest. Unavailable native analysis retains existing application sampling and discloses the gap.

The ordinary CLI was rerun for the one indexed EXP29 collection into `/tmp/navcom-version-intake-proof/sources`; no includes or project mappings were manually supplied. Under the unchanged 400-code-file budget, v32 retained 43 files, v33 retained 48, and v34 retained 49 (46 Python files), replacing v34's earlier two-document-only coverage. Native `sources search committee --path services/semantic-classifier/v34-8034 --mode both` returned six concept hits and twenty text hits, all inside that exact version. The source reader opened twenty lines of its retained `engine/committee.py` with `current_file_read=false`. A second separate discovery/harvest invocation reused the artifact: zero sources analyzed, one cached, worker time 0.067 seconds (initial harvest 3.927 seconds). Remaining depth/byte/file omissions stay explicit; this is still a bounded sample, not the whole repository.
