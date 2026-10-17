# Galactic navigation implementation — active

**Status (October 16, cockpit pass):** active; the full goal is not complete.
Current state lives in the diary: the
[galactic navigation handoff](../diary/2026-10-16-galactic-navigation-handoff.md)
and every newer entry in the [diary index](../diary/README.md). The law for how
pieces fit is [architecture](architecture.md); what the bridge can do per place is
the [action matrix](action-matrix.md); what the UI wants but the CLI cannot do yet
is [CLI concept candidates](cli-concept-candidates.md) (owner decides).

- **Done this pass:**
  - The headless CLI is protected (command words search again; a DNA gate).
  - Services carry no presentation, and the web adapter is thin. Both are
    enforced by `tests/test_architecture.py`.
  - Every cockpit verb has BDD on a real fixture galaxy.
  - The inspector is one action rail: each action is one twin API call plus
    the service's own `navcom …` command.
  - Systems' hue families carry into their planets, moons and districts.
  - The dated-landing reload/Back/Forward/copied-link journey is proven live
    (`tests/test_ui_api_sync.py`, UI == API, no cache writes). This closes
    workstream 4's open acceptance.
- **Still open:**
  - Live microphone acceptance. Voice is deliberately untouched and is meant to
    become a living star.
  - Real captain boarding/takeover (step 7). Every working ship is hosted on
    Bertha, and boarding refuses remote hosts and archives.
    `navcom_ship_boarding` needs either a CLI-first remote-attachment concept or
    a local working ship. That ship needs: this Mac as `physical.host`; one owned
    `<ship>/.starship/runtime/captain/*.json` route (host, socket, thread, cwd ==
    ship dir, codex, node, ws_module); and a live owned Unix socket whose Codex
    app-server answers `initialize` and `thread/read`.
  - Authoritative product identity, product generations, and owner decisions on
    the candidates list.

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
