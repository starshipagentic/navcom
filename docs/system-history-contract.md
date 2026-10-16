# System history: a pinned, dated view of current navigation addresses

The shared service is [`navcom_system_history.view()`](/Users/t/dev/navcom/navcom_system_history.py). It reuses [`navcom_history`](/Users/t/dev/navcom/navcom_history.py) for Git-object snapshots, historical metadata, the existing Starforge harvest worker and both native search paths. It does not introduce another source parser, classifier or search index.

```python
view(place="", as_of="", *, space_cache, source_cache=None, cache_path,
     query="", limit=4, cursor=None, seconds=30, max_commits=10000,
     max_files=None, max_bytes=None, max_file_bytes=None,
     search_limit=20, progress=None, retry_larger=False)
```

`place` must resolve to a cached system or galaxy. `as_of` accepts an ISO date (midnight UTC) or an ISO timestamp with an explicit offset; the result normalizes it to UTC. This is a view of the **current catalog's repository-backed planets and moons** at recorded commits. Current IDs, containment, physical addresses and positions select and stabilize the view; they do not establish historical ownership or prove a product existed. A deleted product absent from the current catalog cannot be inferred.

## Selection and continuity

The first request copies the catalog addresses and source metadata, resolves each eligible address with the existing history resolver and pins its full repository HEAD. Multiple products in a repository share one reconstruction with the union of their selected paths. A session stores these full HEADs, addresses, positions, cutoff and budgets. The returned `next_cursor` includes the immutable session ID and next repository offset. Continued pages use those pins even when today's HEAD or catalog changes.

For each repository, selection walks the pinned HEAD's first-parent ancestry and chooses its first commit with recorded committer date at or before the UTC cutoff. Full SHA, tree ID, author date and committer date remain in evidence. Author dates and filesystem mtimes never select state. Non-monotonic first-parent dates, an exhausted ancestry limit, and future-dated merge ancestry are explicit unknown states. Git dates are recorded metadata; this does not establish deployment, actual historical existence or external service configuration.

The observed committer dates are returned as `available_dates`, with separate `date_coverage`. They come only from repositories whose selection walk ran. No synthetic earliest date is invented. A shallow clone remains disclosed by the reused snapshot service, and a cutoff preceding available history remains unknown.

## What is displayed

Every current eligible planet/moon anchor is returned on every page, including unvisited, unavailable and missing-path scopes. Nodes keep `id`, `position`, `kind` and `parent_id`; a separate `current_label` is navigation metadata. The visible historical `label`, `description`, manifests, source clues and groups come only from the selected committed tree. No supported files at an old address means unknown; paths are not guessed through renames and current files never fill the gap.

Successful nodes include exact dated tree evidence, committed file paths, historical manifests/clues and the native Starforge structure restricted to their file scope. The existing metadata readers supply product clues; the native worker supplies groups. System/galaxy labels are explicitly marked current navigation anchors. No current conversation is joined to a historical snapshot because no trustworthy commit-to-conversation attribution exists.

Top-level output includes `center`, `breadcrumbs`, `nodes`/`entities`, `edges`, `chart`, `repositories` (full historical service evidence or errors), `completed_scope_ids`, `coverage`, `available_dates`, `date_coverage`, `session_id`, `cursor`, `next_cursor`, `cli_command` and `continue_command`. Current containment edges are labeled as current navigation addresses. A `query` runs both existing historical search paths against the selected immutable snapshots, never current source caches.

## CLI journey

```sh
navcom history system 'Coastal tools' --at 2025-04-01 --query login --limit 4
navcom history system --cursor <failed-cursor> --retry-larger --query login
navcom history system --help
```

Plain output prints each historical state, full commit SHA and recorded date, useful description and file/group counts. Unknown places retain their reason and separate current address label. It renders both historical search paths and concise coverage instead of empty nested objects or a raw JSON coverage dump. Progress identifies the address being inspected or dated repository being reconstructed; structured JSON stays on stdout when `--json` is used.

The shared DTO supplies shell-quoted `cli_command` for replaying the current **pinned** page and `continue_command` for its next page (null when complete). Both retain the exact session cursor, cutoff, cache paths, query, pagination/time bounds and any nondefault snapshot/search bounds. A query beginning with `-` or containing shell punctuation remains literal data. The commands never resolve a fresh HEAD by accident. The plain renderer prints them under **Replay this pinned page** and **Continue**.

When a saved journey has a snapshot-size failure, use its printed `retry_larger_command`. The explicit `--retry-larger` action requires that existing cursor and creates a separate journey with up to 10,000 files and 64 MiB per repository in the local historical cache. It retains the original repository HEADs, UTC cutoff, address scopes, per-file limit and ancestry limit. The original view remains available. This retries a file-count or total-byte failure; it does not recover missing history or increase the page deadline. A repository that exceeds the larger bound still reports its gap.

`POST /api/history/system` accepts `retry_larger: true` with the existing `cursor` and original query in `q`. The switch must be a JSON boolean. The shared service validates the cursor and eligible saved failure before deriving the new journey. Cache paths, snapshot sizes and execution time remain server controlled; request fields cannot override them. Later pages use the derived cursor with `retry_larger` omitted or false. Omitted CLI snapshot budgets also inherit the cursor's saved limits; explicitly supplied different limits are rejected. For a new journey, omitted limits use the ordinary 2,000-file, 16 MiB total and 2 MiB per-file defaults.

## Bounds, cache and progress

The default request has a 30-second total deadline and visits at most four repository jobs. All eligible anchors are accounted for; this is explicit pagination, not a hidden first-N search. Pinning reserves up to 40% of the total request time. A pin not obtained in that interval remains unknown throughout the session; a new session can retry it. Cursor pages never replace an unpinned repository with an opportunistically newer HEAD.

Each complete native operation runs in an isolated process group with the remaining deadline and bounded output; timeout kills its harvest children as well. Repository snapshots default to 2,000 files, 16 MiB total, 2 MiB per file. Existing history eligibility and exclusions apply. Progress events distinguish `pin` from `reconstruct` and carry completed/total counts and scope IDs. The caller can render progress without inventing a percentage for unmeasured work.

Immutable revision and query caches are reused through the existing history/Starforge APIs, at the same configured history root (`cache/revisions/...`) used by one-repository exploration and source readers. Published page results let later pages retain prior reconstructed anchors. A time-budget or busy-worker failure leaves `next_cursor` on that repository with `retryable: true`; continuing retries its original pinned HEAD. `reconstruction_complete` describes whether every anchor has dated contents; `complete` also accounts for snapshot exclusions. Unknown scopes, unvisited repository pages and per-snapshot coverage remain explicit.

## Native lab proof

[`tests/test_system_history.py`](/Users/t/dev/navcom/tests/test_system_history.py) has **seven tests**, including the actual local Starforge runtime and repository CLI entrypoint. The service gate passed **25 combined tests in 26.91 seconds** before the two CLI-polish tests were added; the seven-test system suite then passed in **14.56 seconds**. The fixture contains two unfamiliar repositories with different commit dates, an unavailable repository and a current-only path:

- April selects `quartz-classic` / Password and `basalt-archive` / Archive. September selects `quartz-cloud` / Cognito and `basalt-graph` / Graph.
- Both historical search paths return the old Password evidence; newer content and dirty/current-only files are absent from old snapshots.
- Missing repositories and newly created paths remain unknown, while all map IDs and positions stay fixed.
- Repeated requests reuse revision and native query caches.
- A new August commit created between pages does not replace the previously pinned August commit.
- An exhausted ancestry cap, backdated non-monotonic history, missing date offset and malformed cursor produce explicit errors rather than guessed state.
- A timed-out reconstruction retries successfully within the same immutable session and HEAD; snapshot paths use the existing shared history cache.
- The CLI's printed replay and continuation arguments execute successfully against the repository entrypoint, preserve the pinned session and query, and render the actual flat historical state/commit fields. A literal query containing shell punctuation and a leading hyphen survives command serialization unchanged.

Reproducible UI fixture: `/tmp/navcom-system-history-flight/proof-kifkwtcs/fixture.json`, with `space_cache`, `history_cache`, dates and repository addresses. `early.json` and `late.json` beside it record the complete service output. The saved April and September runs took 1.903 and 2.168 seconds respectively; these are local fixture measurements, not a prediction for a large system.

CLI proof is beside the fixture: `cli-page-one.json`, `cli-command-proof.json`, `cli-replay.txt` and `cli-continue.txt`. Both printed command argument lists completed with exit zero through the repository entrypoint; progress contains readable address/repository counts rather than Python dictionary representations. Installing a build containing these modules is a separate release step.

This service does not invoke an agent/model, deploy a revision, modify a source checkout or reconstruct a whole historical organization. CLI and browser integration consume this shared contract separately.
