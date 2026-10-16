# CLI audit: making the geography real

Date: 2026-10-15. Read-only audit; no runtime behavior changed.

Meaning comes from [the spatial vision](spatial-navigation-vision.md) and [the diary](../diary/2026-10-15-a-universe-you-can-return-to.md). This audit distinguishes existing capabilities from proposed work.

## Verdict

NavCom already has the right basic verbs and shared CLI/web query service. It does **not** yet have the entities and relationships needed for this geography. This requires a procedural discovery and identity layer beneath those verbs, followed by a visual representation. Renaming current collections would produce a misleading map.

The first deliverable should be a terminal journey that lists systems, lists their products, lists a product's experiments and districts, and searches within each. The exact same output must drive the UI. Syra is an acceptance example, never a special branch in the implementation.

## What actually ran

Read-only commands against the existing index:

```sh
navcom atlas list topics --limit 200 --json
navcom atlas list research --limit 200 --json
navcom atlas list projects --limit 200 --json
navcom atlas list districts --limit 200 --json
navcom atlas list time --limit 200 --json
navcom atlas list starships --limit 200 --json
```

The snapshot contained 6,671 indexed conversations. Its discovery evidence cache reported stale; these are observed indexed results, not a claim of complete current inventory. No refresh or reindex was performed.

| Existing grouping | Reported total | What it means today |
| --- | ---: | --- |
| Topics | 9 | Fixed vocabulary classifications |
| Research | 133 | Four defined profiles plus 129 suggested project families |
| Projects | 338 | Exact conversation working directories; first 200 retrieved |
| Districts | 4 | Broad folder classifications |
| Time | 31 | Last-activity calendar months |
| Starships | 52 | Snapshot source-folder groups, including Unlinked projects; not 52 verified commissioned ships |

Probes for `atlas list systems`, `planets`, `moons`, `stars`, and `starbases` all exited 2 as unsupported. A probe for `atlas list projects --at 2026-01-01` also exited 2. These probes do not establish final command names.

## Definition versus implementation

| Desired place | Current support | Required change |
| --- | --- | --- |
| Galaxy: owner's work across hosting locations | Local conversation index | Owner identity and inventory scope independent of machine |
| Solar system: commitment or product suite | No corresponding entity; Clients & business mixes work | Generalized suite/ownership relationships |
| Planet: product | `list projects` groups exact cwd strings | Product identity with multiple repositories, worktrees, and historical locations |
| Moon: experiment | Research families and version/approach mentions | Explicit experiment identity and relationship to product or research undertaking; never equate child conversations with moons |
| Cities/districts: product capabilities and strategies | `list districts` classifies `/clients/`, `/dev/`, hidden paths, and everything else | Product-scoped areas backed by source evidence, such as authentication or integrations |
| Time: evolution of products and suites | `--since`/`--until` filter session-file modification time | Historical entities/relationships and evidence cutoffs; last activity is not an as-of state |
| Star: living expertise across systems | No star inventory | Consume actual Starforge/Starship expertise records and interfaces; preserve cross-system relationships |
| Starbase: docking/storage/resource destination | No starbase inventory | Consume actual base identities, locations, and ship membership |
| Ship: recoverable working environment and viewpoint | Source-directory matches from Starship bridge snapshot | Preserve ship identity, mission, conceptual location, checkpoint and readiness; delegate boarding to Starship |
| Hardware: underlying hosting plane | Some filesystem paths | Separate physical copies/runtime availability from conceptual identity |

For example, the live project list has separate Syra B2B, ML lab, iOS, old mobile and other working-directory entries. It does not establish which constitute a single product, its experiments, or separate products. A common path prefix alone cannot prove W-2 employment or product ownership.

## What to keep

`list`, `explore`, `search`, `show`, `tree`, `refresh`, and layered `help` already exist. `--within` restricts a whole collection before ranking, across pagination; intersected collection scopes also work. JSON, provider/date/children filters, conversation evidence, and ancestry-aware launch previews are useful foundations.

The web `/api/atlas` route and CLI both use `Discovery`. Keep that single service. Keep provider ancestry separate from conceptual relationships. Keep original resume, new-tab resume and fresh-harness handoff separate from ship boarding.

Sources: [CLI parser](../navcom_atlas_cli.py), [shared discovery](../navcom_discovery.py), [web routes](../navcom_web.py).

## Important limitations to fix at the source

1. **Research knowledge is partly bespoke.** `navcom_research.py` contains four curated profiles: EXP29, EXP30, EXP32 and Semantic Observatory. Their aliases, descriptions, branch expressions and routing rules improve those cases. Other suggested families are mostly per-directory groups found through research words. This is not generalized product/experiment understanding. Move such profiles toward evidence-backed data; do not add a Syra-specific equivalent.
2. **Identity is mostly a label/path hash.** A rename or move can change collection identity. There is no durable domain relationship registry. Entities without indexed conversations cannot appear in the current catalog.
3. **Mentions are not structure.** A transcript mentioning v34 proves a mention, not which product owns that version or whether it was implemented. Extraction should retain that distinction.
4. **The map is not a stable topology.** The shared discovery response returns empty edges; the UI draws a center-based layout whose positions depend on result count/order. Search can change apparent geography. Stable entity anchors and actual relationship edges are required.
5. **The ship view discards important context.** `fleet_snapshot()` reduces bridge records to ship name/source-folder pairs and snapshot date. It cannot establish boarding readiness or restore the captain's working state.
6. **Dates do not reconstruct history.** Filtering on conversation-file mtime can exclude an old discussion that was continued recently. Selecting a conversation does not restrict all its evidence to an earlier historical cutoff.

Sources: [research profiles](../navcom_research.py), [identity/classification/fleet catalog](../navcom_atlas.py), [discovery registry and filters](../navcom_discovery.py), [map layout](../navcom_atlas.js).

## Smallest coherent implementation boundary

### 1. Give existing verbs durable things to query

Add persistent entities and relationships to the shared discovery service. Each entity needs a stable ID, kind, label, source references, and coverage. Relationships need a type, evidence, and whether they are established or suggested. Store physical locations separately. Preserve historical validity where it is known; do not invent retrospective dates.

One product can have several repositories; one repository can contain several products. Experiments and shared stars can relate to multiple places. Filesystem nesting and provider conversation ancestry must not impose those relationships.

### 2. Discover and update those records procedurally

Reuse the conversation index; ingest available project metadata, Git identity/worktree information, and actual Starship/Starforge records through bounded adapters. Reuse existing identity/ownership declarations before inferring anything. Folder and text evidence can suggest missing relationships, with provenance. Persist corrections so a subsequent refresh does not erase them.

The same rules must operate on unfamiliar clients and products. Where evidence cannot establish a relationship, return an inspectable unresolved candidate rather than quietly assigning it to a fictional system. Automatic discovery is the default; per-client code and manual rebuilding of every map are not the solution.

### 3. Expose this through the existing CLI shape

Illustrative **proposed, currently unsupported** additions:

```sh
navcom atlas list systems --json
navcom atlas list planets --within <system-id> --json
navcom atlas list moons --within <planet-id> --json
navcom atlas list districts --within <planet-id> --json
navcom atlas search login --within <district-id> --json
navcom atlas explore <entity-id> --at <date> --json
```

Keep the verbs small. Extend their kinds, scoped behavior and help rather than creating a separate universe CLI. `show` must explain an entity's membership and evidence as well as support conversations. Exact noun aliases and compatibility for today's folder-based `districts` need an explicit migration decision. An as-of option must wait for genuine historical support.

Expose stars, bases and ships through the same query contract, with actual supported actions and availability. Starship remains responsible for commissioning, secure access material, checkpoints and restoration. NavCom discovers and navigates those resources; a resume command is not proof of boarding.

### 4. Render the proven output

Only after the terminal journey works, make systems/products/experiments physically recognizable. Keep entity positions stable through search, retain scope/back/time state, and display actual relationships. Voice and typing should address the same navigation state. Artwork does not decide membership.

## Compute and caching

Current Atlas extraction is procedural Python/SQL/regular expressions, not LLM inference. Evidence refresh skips unchanged files using indexed mtime/size/turn signatures and writes a separate atomic cache. Collection construction still runs in a new CLI process; the server has an in-memory catalog cache. Neither is a persistent product model.

The new discovery records should update incrementally using source signatures plus extractor/schema versions. Ordinary navigation/search must require no model. Any optional model enrichment should be bounded, separately cached by source and enrichment version, and never required to open a system or repeatedly charged on each search. No performance improvement is claimed by this audit; cold/warm measurements belong to implementation acceptance.

## Proof required before calling it done

- An unfamiliar fixture suite produces systems, products and experiment relationships through the same rules as Syra; no fixture/client-name conditions in code.
- Duplicate worktrees and moved repositories retain the same product identity. Multiple products in one repository remain distinguishable when supported by metadata.
- An inventoried product or ship with no conversations still appears. An offline starbase stays identifiable with availability shown separately.
- A transcript mentioning another product/version does not silently relocate the conversation or create verified ownership. Child tasks remain conversation ancestry.
- Historical views exclude later evidence and distinguish unknown history from known absence.
- CLI JSON and web views return identical membership, evidence and scope. Search/back preserves location; search does not reshuffle the whole map.
- Warm navigation uses cached discovery without model calls or full rescans. Refresh exposes progress and tolerates concurrent indexing.
- A ship action reports the actual Starship checkpoint/readiness result; it does not claim recovery from merely launching a harness.

First implementation milestone: the generalized system → product → experiment/district → evidence journey in CLI JSON and readable terminal output. Then expose the same journey visually. Historical reconstruction and live boarding remain explicit capabilities with their own proof, not implied by the first map.
