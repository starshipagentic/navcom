# Galactic navigation implementation — active

**Status (October 17, identities for apps in one repository):** active; the full goal is not complete.
Current state lives in the diary: the
[galactic navigation handoff](../diary/2026-10-16-galactic-navigation-handoff.md)
and every newer entry in the [diary index](../diary/README.md). The law for how
pieces fit is [architecture](architecture.md); what the bridge can do per place is
the [action matrix](action-matrix.md); what the UI wants but the CLI cannot do yet
is [CLI concept candidates](cli-concept-candidates.md). Those optional proposals
are not all prerequisites for finishing the already-authorized journey.

- **Done this pass:**
  - Each already discovered application can use its own `.navcom-space.json`
    for stable identity and exact replacement declarations. Moving within a
    repository or splitting into a standalone repository preserves that declared
    identity; files and conversations stay scoped to the app. Native CLI/API,
    installed harvest/search and browser Fly/Back/reload proof is in the
    [nested-product diary](../diary/2026-10-17-products-inside-one-repository.md).
  - Existing root declarations can record exact product replacements. Normal
    refresh, `atlas related` and Connections & versions preserve distinct
    products and expose provenance/conflicts. Installed CLI/API and real browser
    Fly/Back/reload proof is in the
    [product-replacement diary](../diary/2026-10-17-declared-product-replacements.md).
  - Exact “show the experiments” and other kind-list commands reuse the cached
    `atlas list` service. Typed “take me back” restores the previous viewpoint.
    Real Syra flight/return, global paging, reload, copied links and narrow-screen
    proof is in the [Navigator diary](../diary/2026-10-17-navigator-lists-and-return.md).
  - Ship arrivals expose mission, location, context and stored copies in the
    main workspace. The carried-reader Back/Close journey returns to the
    original working ship without reopening a closed reader.
  - Native committed application candidates can be entered from their dated
    experiment. Historical leaf arrivals show exact files and matching source
    passages in the main workspace; source reads remain pinned. Installed Syra
    CLI/browser and narrow-screen proof is in the
    [arrival-workspace diary](../diary/2026-10-17-arrival-workspaces-and-historical-applications.md).
  - Successful idle bridge startup clears its connection placeholder; running
    tasks retain progress and do not load the hidden Library when they finish.
  - Ordinary slash-command search preserves bare Claude commands and keeps
    identical matches from different conversations distinct. Missing
    original ThriveCart transcripts remain an evidence-recovery gap, not a
    ranking problem; see [the basic-search diary](../diary/2026-10-16-basic-solve2-search.md).
  - `atlas explore/search --conversations` and **Conversations here** use every
    saved collection belonging to the selected place, with the existing search,
    ancestry, filtering and pagination. Installed CLI/API results agree.
  - Following an **Evidence by place** result retains the query and narrows its
    scope; Back restores the broader search and viewpoint. Real browser proof
    covers EXP32 → matrix lab → Back and B2B conversation paging/reload.
  - Current-conversation reader identity and turn survive paging, reload,
    Back/Forward and copied links. Closing restores the originating conversation
    search, and reading a matching child preserves its exact identity without
    changing Library state. Installed browser proof is in the
    [passage-continuity diary](../diary/2026-10-17-conversation-passage-continuity.md).
  - The headless CLI is protected (command words search again; a DNA gate).
  - Services carry no presentation, and the web adapter is thin. Both are
    enforced by `tests/test_architecture.py`.
  - Every cockpit verb has BDD on a real fixture galaxy.
  - The inspector is one action rail: each action is one twin API call plus
    the service's own `navcom …` command.
  - Place briefings keep valid retained source evidence when some saved paths
    are unavailable. Installed CLI proof preserves 24 native hit references and
    exposes two retained documents; missing coverage remains explicit.
  - Question briefings lead with admitted native matches and their citations
    before generic project metadata. Installed CLI/browser proof and current
    runtime details are in the [arrival and handoff diary](../diary/2026-10-17-arrival-evidence-and-native-handoff.md).
  - Remote working-ship routes reuse the native Starship captain reader over
    the configured SSH route. The Syra CLI and browser verify the same thread
    and workspace. Explicit local web launches now fall back to the user's
    macOS Terminal when the bridge has no terminal environment. The real bridge
    reports terminal dispatch; visible captain takeover still needs confirmation.
  - Systems' hue families carry into their planets, moons and districts.
  - The dated-landing reload/Back/Forward/copied-link journey is proven live
    (`tests/test_ui_api_sync.py`, UI == API, no cache writes). This closes
    workstream 4's open acceptance.
- **Still open:**
  - Live microphone acceptance. Voice is deliberately untouched and is meant to
    become a living star.
  - Real captain takeover (step 7). Syra's working ship on Bertha now validates
    and dispatches through the native route. Computer-use policy blocks this
    agent from inspecting Terminal, so a user observation is pending; dispatch
    is not takeover or application-readiness proof. Archives remain non-boardable.
    Routes must still bind host, owned socket, thread, workspace and installed
    runtime, and pass `initialize` plus `thread/read` before launching.
  - Evidence for the owner's actual product generations. Root and discovered-app
    identities/supersession are implemented; specific Syrenity predecessor/
    successor choices and historical replacement dates remain unestablished.
    Keep native suggestions distinct from explicit declarations and these
    remaining evidence gaps.

The goal is a usable, beautiful galactic experience for finding and resuming work:
owner galaxy → client/venture systems → products → experiments and districts,
with real code, documents, conversations, stars, bases and ships. The spatial
vision remains authoritative. A working map alone does not finish this goal.

## Implementation sequence and proof

1. **Shared geographic data and CLI (in progress).** Procedural discovery from
   indexed project roots, Git identities, existing organization metadata, declared
   app manifests and cached Starforge output. Stable IDs/coordinates; distinguish
   supported declarations from suggestions. Multiple products per repository,
   offline roots, explicit experiment moons; no child-session/moon conflation.
2. **Automatic intake (in progress).** A command discovers bounded source scopes
   and invokes the existing harvest worker. No manually synchronized catalog or
   curated client-specific profiles. Unchanged content/groups/queries are cached.
3. **CLI journey gate.** Show unfamiliar systems, separate applications, an
   experiment and meaningful token-group districts. Search inside a district's
   actual file scope and return conversation evidence. Prove cached reads and
   stable identity before rendering new UI.
4. **Shared UI journey.** Consume the same service, with distinct visual objects,
   smooth bounded flight, usable labels, selected-place details, breadcrumbs,
   reliable Back/Forward and saved viewpoint. Search highlights without relayout.
   Reuse Starship artwork through a reproducible import command.
5. **Agentic navigation.** Typed and spoken intent share the same current scope.
   Plan understandable read-only steps across destination, code/document and
   conversation evidence; allow following a result and returning. An optional
   existing local model can enrich interpretation but is never required.
6. **Time and physical plane.** Historical evidence must exclude future material;
   unknown historical state stays unknown. Host/storage location is inspectable
   separately from conceptual position. Do not manufacture a historical snapshot
   from file modification time.
7. **Fleet/expertise integration.** Consume actual Starship receipts and supported
   routes. Stars are declared living expertise, not every repository. Bases/ships
   keep host identity, receipt age, gaps and actual readiness. Boarding must use a
   verified route, never a pretend readiness flag or generic conversation resume.
8. **Human E2E acceptance.** Start at galaxy, find multiple systems/products,
   navigate EXP32 then matrix within scope, inspect a district's code and related
   conversation, return without losing place, test voice availability/fallback,
   inspect a ship/base and unavailable route, revisit saved position. Test narrow
   screen, keyboard and reduced motion. Publish only when separately authorized.

Do not mark the full goal complete until all applicable behavior is verified.
Missing assets, data, routes or live readiness remain explicitly unfinished.

## Checkpoint history

The dated checkpoints that used to follow are recorded in the diary, from
[first galactic flight](../diary/2026-10-16-first-galactic-flight.md) to
[product clues and pinned history](../diary/2026-10-16-product-clues-and-pinned-history.md).
Their original text remains at `git show 4e18553:docs/galactic-implementation-plan.md`.
