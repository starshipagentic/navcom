# Keep the passage, not just the place

The installed bridge now restores the exact indexed conversation and turn. This
closes the reader gap from [whole-place conversation search](2026-10-16-search-whole-places-and-follow-evidence.md),
not the full galactic goal. The [official plan](../docs/galactic-implementation-plan.md)
remains active.

## The real journey

Before: galaxy → **Conversations here** → `solve2` → Paircode → **Read
conversation** opened turn 77, but the URL did not identify the passage. Reload
lost the reader.

After, the installed browser acceptance run proved:

- Paircode `e17fd186-45a3-4151-af99-26082778453d`, exact indexed key, turn 77;
  **Next 80** opened 157, and reload kept 157.
- Back restored the galaxy's `solve2` conversation panel. Forward reopened 157;
  Escape returned to the chart.
- A copied URL opened 157 in a fresh tab. Close stayed inside NavCom and retained
  the originating `solve2` panel.
- A real NavCom matching child, `01a1430e…`, opened its own turn 1665 even though
  its native resume preview targeted the parent. Library's prior parent selection
  survived the bridge child read.

The source and installed static-file hashes matched in installed NavCom 0.11.0,
at `http://127.0.0.1:62550/?view=space`. This was actual browser acceptance,
separate from the controller tests below, with no browser error logs. The
[inspected screenshot](evidence/2026-10-17-conversation-reader.png) shows actual
turns 77/78 beside the galaxy.
No ship UI journey is claimed by this entry.

## Small change, existing reader

The bridge saves the full indexed key and positive turn in its existing route and
URL. Reader links also carry the validated conversation-panel query, child filter
and page. Paging replaces the reader's history entry. Close returns through a
known in-app predecessor; a copied link or a new tab closes in place.

The existing `GET /api/session` still performs the read. Reader and native detail
tickets reject late successes/errors after Close, a newer read or a Library
switch. Library's saved selection is separate. A current transcript opened over
a dated chart explicitly warns that its content can extend beyond that date.
No new search layer, model, catalog, or backend was added.

## Common-sense audit

- **Guidance:** the [spatial vision](../docs/spatial-navigation-vision.md),
  [active plan](../docs/galactic-implementation-plan.md),
  [architecture](../docs/architecture.md), [action matrix](../docs/action-matrix.md)
  and [conversation BDD](../features/conversation_verbs.feature) remain the
  anchors. The stale open-reader item is now marked done; optional CLI candidates
  are not universal owner-approval gates. Keep the next task tied to one real
  journey rather than expanding that candidate list.
- **Intervention and autonomy:** a reproduced reload loss selected this bounded
  repair. Work continued through controller fixes, independent review, local
  installation and real browser acceptance. Review also covered a stale
  localStorage history step: a new tab must not Close by navigating outside the
  app. Result: the reader journey moved from broken to proven. Continue with one
  remaining owner-visible boundary; do not substitute more green tests for it.
- **Testing reality:** the final controller execution passed 79 cases in 8.22s;
  the existing web execution passed 14 in 9.04s after temporary localhost binding
  was permitted. The initial socket restriction was a recoverable test-environment
  gate, not a product failure. Independent reviews found no remaining blocker.
  Good: exact child identity, cancellation, history and Library isolation are
  regression-tested and the installed journey passed. Test cases are not E2E cycles.
- **Time:** only those test-run durations were measured. Total elapsed time and
  the five buckets—product work, useful QA, QA plumbing, external waiting and
  avoidable rework—are unmeasured; no percentage or productivity claim is justified.
  Record timestamps around the next bounded journey instead of reconstructing them.

## Still unfinished

The 44 missing original ThriveCart Claude session IDs/transcripts remain
unavailable; we cannot prove which contained `solve2`. Parser repair did not
recover them. Only Macintosh HD was mounted under `/Volumes` at this checkpoint;
the backup was unavailable. Live microphone acceptance, authoritative product identity
and generations, and real captain takeover remain open. Starship's existing
same-host native reconnect is useful prior art, not proof of remote boarding or
human takeover. Inspect/reuse that route before inventing a replacement.

Next: finish one remaining real product-to-ship/context journey with explicit
readiness limits, preserve the proven reader and scoped-return behavior, and
append its own observed evidence. Do not mark the overall goal complete from
this checkpoint.
