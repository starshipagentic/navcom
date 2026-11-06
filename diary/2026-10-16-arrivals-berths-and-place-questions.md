# Arrivals should contain the work

The captain pointed out three connected problems: too much vertical chrome,
a starbase full of identical evenly spaced ships, and an empty arrival scene
whose search could not answer “what does it do?” about the selected project.

We kept the [spatial vision](../docs/spatial-navigation-vision.md) and the
[active implementation plan](../docs/galactic-implementation-plan.md).
This is a checkpoint, not completion of the galactic goal.

## What changed

- Compact bridge headers leave more room for the chart and its evidence.
- Starbase berths use recorded system and exact source relationships, computed
  over the full fleet before filtering. Related ships park together without
  inventing ownership. The inspected Bertha fleet had 107 ships: 30 had supported
  berth assignments and 77 remained explicitly unassigned.
- The reproducible Starship art importer now carries 33 additional original
  fleet/cargo images with provenance. Stable ship IDs choose consistent hulls;
  appearance does not assert a ship class or readiness. Stored archives retain
  their archive art. No Starship source changes were needed.
- Current product, experiment and district arrivals expose a shared briefing.
  Leaf destinations use the empty map area for that briefing and linked excerpts.
- Natural questions use the selected place's saved description, bounded retained
  documents and exact-membership indexed conversations, alongside Starforge's
  existing concept and text retrieval. This does not replace Starforge search.
- Optional synthesis uses NavCom's existing local-model discovery and transport.
  Every accepted claim names supplied evidence IDs. This validates references,
  not factual entailment. Successful answers are cached by question, place,
  evidence, prompt and model route. Arrival itself never runs inference.

## Shared commands and boundaries

```sh
navcom atlas explore <place-id>
navcom atlas navigate "what does it do?" --within <place-id>
navcom atlas list ships --within <starbase-id>
```

These use the same services as the browser; `--json` exposes the briefing and
fleet layout. No new CLI verb, independent UI search engine, curated project
profile or manual catalog synchronization was introduced.

Briefings read bounded known retained README/manifest names through the existing
snapshot reader and at most three exact-scope conversations through the index.
They do not scan live source or run harvest. Missing inputs remain visible.
Dated views do not acquire today's briefing. Broad galaxy/system questions do
not borrow three arbitrary conversations as an answer.

## The concrete Lauren example

`planet:8f58e3ddb5a8e8e51784` has three indexed conversations, but its recorded
code location is unavailable and no harvested source is attached. Starforge's
question-term extractor produced no terms for “what does it do?”; retrieval alone
therefore returned nothing useful. The new shared context exposes recorded
research, planning and implementation replies, at turns 13, 38 and 98. Their
claims are historical statements, not verification of current code or metrics.

The installed CLI recovered all three with zero live-file reads and zero harvest
invocations. In the browser, the same question returned that briefing, its
research citation opened turn 13, and Back to chart retained the project and
question. The current code-folder gap remains explicit.
Reload also restored the question and its briefing. The final density pass passed
24 focused UI checks; the browser reported no console errors. Screenshot proof:
`/tmp/navcom-arrival-briefing.jpg`.

No suitable local answer model was running during this proof. Local Ollama had
no resident models, and the configured CapCom endpoint was unavailable. No model
was started or downloaded. Generated-answer/cache/citation paths have fixture
coverage; live generated-answer acceptance remains open.

## Verification and continuation

The backend's 51 focused tests, frontend's 72 controller regressions and 143
architecture checks passed. Independent review covered exact scope, source
receipts, historical separation and per-claim citation links. Browser testing
also found an inherited narrow paragraph rule; the final layout pass fixes that
and makes long Markdown excerpts readable without inventing new content.

The local 0.11.0 installation was updated from a local wheel, without publishing.
The verified preview is `http://127.0.0.1:62550/`; the older 62811 address is stale.
Its source cache is `/tmp/navcom-galaxy/sources`, chart is
`/tmp/navcom-galaxy/space.json`, and host index is
`/Users/t/.codex/navcom-index.sqlite`. Temporary proof output is under
`/tmp/navcom-lauren-briefing-*`.

Remaining larger-plan work is unchanged: live microphone acceptance, real
captain boarding/takeover, authoritative owner/product-generation decisions,
and a live grounded-answer check when a suitable model is already available.
An existing zoom-out camera jump was observed during fleet testing and remains
separate follow-up work. No commit or PyPI publication was made in this pass.

## Header correction after the captain's next screenshot

The previous compact treatment still left four stacked rows. We replaced that
with two working strips: logo/view tabs/Guide/upkeep, then breadcrumbs and chart
controls. The separate decorative title banner is gone; its heading remains
available to assistive technology. Existing view controls move together and
return to their original position for Library/Atlas; focus is preserved.

At the verified 1667×963 desktop viewport, the workspace starts at 108px rather
than 270px (60% less header). Its height uses the recovered space. Thirty existing
controller checks passed; live Library → Bridge preserved focus, project and
question, with no console errors. Updated installed static files are served from
62550 without restarting the bridge. Proof: `/tmp/navcom-compact-header.jpg`.
