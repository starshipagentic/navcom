# Starforge reuse survey and Starship alignment

2026-10-15. Supersedes the first lab's implication that two tested algorithms represented Starforge's capabilities. No production modules changed.

## Decision

Reuse existing Starforge techniques and Starship's inspection/intake contracts before writing another classifier. The strongest immediate fit is **Starforge concept search plus polyglot token groups, lineage/scaffolding evidence, and Starship's bounded inspection**. The missing current catalog inputs matter at least as much as the algorithms.

This is still an experiment. The survey inventoried 203 CLI commands from live help, inspected 15 focused help screens, ran 17 CLI trials, ten library trials, three current-metadata search trials, and Starship's existing inspector. It did not evaluate every Starforge function.

## Same foundation as Starship?

Yes. I traced the promoted `~/.codex/skills/ship-commission/scripts` implementation as well as `~/dev/starship` lab records. The installed borrowed copies of all six modules below are **byte-for-byte identical** to `~/dev/starforge/src/starforge` today. Hashes and exact paths are recorded in the private receipt.

| Starforge module already carried by Starship | Starship use | NavCom relationship |
| --- | --- | --- |
| `file_dupes.py` | Exact duplicate evidence during intake | Reuse duplicate evidence; do not conflate copies with products |
| `utils.py` | Shared helper/skip rules supporting duplicate detection | Supporting module, not a separate classifier |
| `env_vars.py` | Environment-reference names and locations | Useful dependency/facility clues; never secret values or proof of requiredness |
| `build_systems.py` | Build/runtime discovery | Reuse existing observations rather than a second scanner |
| `config_files.py` | Root configuration inventory | Reuse and explicitly inspect nested application roots |
| `portability.py` | Python import analysis | Dependency leads with disclosed language/runtime limitations |

Starship's `intake.py` itself groups Git workspaces by common Git directory. That is Starship's code, not Starforge lineage detection. Its report explicitly says shared Git storage does not mean identical workspaces. `readiness.py` wraps borrowed extractors with file/byte/time limits and coverage disclosure. The bridge separately borrows Starforge artwork.

I ran the unchanged Starship inspector on Syra B2B with a deliberately limited 200-file budget: 0.887 seconds, five build-system findings, 34 environment-reference names, and an explicit `scan budget` limitation with `ready: false`. This is a successful bounded inspection, not proof of readiness or complete dependency coverage.

Source pointers:

- `~/.codex/skills/ship-commission/scripts/intake.py`: `repository`, `scan`, `borrowed_duplicates`.
- `~/.codex/skills/ship-commission/scripts/readiness.py`: `inspect_source` and its `tools_used` list.
- `~/dev/starship/LABS/101-captain-fleet/STARFORGE.md`: receiving tests preserve the 183-project/3,451-gem catalog and explicitly leave cross-project path remapping open.
- `~/dev/starship/bridge/build.py` and `borrow_ships.py`: artwork reuse.

The grouping/search capabilities below are complementary to these inspected Starship paths. This is not proof that no historical Starship lab ever tried them.

## Test checklist and outcomes

| Existing capability | Actual trial | Result and appropriate role |
| --- | --- | --- |
| Catalog health/export | Existing private catalog copy | 183 projects, 3,451 gems; 91 missing technology stacks and 44 projects with no gems. Current B2B, mobile, CarePlus, EXP29/30/32, Observatory and NavCom are absent by exact project name. Coverage is a major blocker. |
| Full concept search | Existing catalog, broad research query | Returned historical chatbot/tools results; none of the four current research targets. Missing input, not proof that its search is unusable. |
| Full concept search | 74 current metadata adapter records | `exp32 matrix`: EXP32 first, Observatory second, 0.067 s. Broad research query found EXP29/30/32 in eight results but still missed Observatory. No algorithm changes. |
| Scoped relevance | Current metadata, `cognito authorization` | B2B first, but global results also include unrelated projects. Apply NavCom's existing scope before ranking; do not infer shared ownership from the matches. |
| `explore` | Existing catalog, EXP32 | No results. Current catalog coverage must be fixed before judging this journey. |
| Repo lineage | Current NavCom destination names through unchanged detector | Found recognizable Diaryflow, dialog-super-intent-builder, DBTool and other sequences. Also produced broad Awali/Clients families that cannot safely mean one product. |
| Version/experiment distinction | Unfamiliar synthetic names | Grouped quartz-v1/v2/v3; did not group exp91/92 or lab71/72 as versions. Existing machinery already handles an important distinction. |
| Scaffolding detection | Existing catalog | 80 scaffolding groups, three lineage groups, five mixed groups. Useful guard against treating generic `auth`, `main`, `server` filenames as product ancestry. |
| Polyglot token groups | 1,278 tracked Syra source files, default parameters | 95 groups covering 837 files in 3.061 s. Recognizable Cerbos, login, access-service and chart groups. Largest group spans 425 files with cohesion 0.037 and no shared tokens: too broad to label as one district. |
| Import groups | 99 bounded EXP32 Python files | Five multi-file groups, largest ten files, 0.268 s. Useful package evidence, not automatic product identity. |
| Semantic import groups | Same EXP32 sample | Two groups of 14 and eight files, 0.214 s. Existing comment/test-reference merging works, but can increase over-grouping. |
| Monorepo boundary challenge | Two synthetic products share a helper | Import grouping merges all three files. A code dependency component is not necessarily a product. |
| Code ancestry | Changed billing function plus unrelated control | Correct similar implementation returned, unrelated function omitted. Combined similarity 0.987. It establishes resemblance; it does not independently prove historical direction. |
| Paradigms | Same 99 EXP32 files | Classified libraries, ML models, CLI tools, tests and scripts; one unknown. Useful card descriptions; not client/suite ownership. |
| API extraction | Same Syra source inventory | 59 endpoint findings across 31 files, 0.441 s. Useful facility leads; route accuracy/coverage not independently validated. |
| Entry points | Bounded EXP32 source mirror | Existing detector ran; output saved. No commands executed and no runtime-readiness claim. |
| `why` / `profile` / `apis` / `entry-points` | Existing catalog, B2B | Missing target; `profile` exits 1 while several others return 0 with no useful result. Inspect output, not exit code alone. |
| Captain's logs | Context at NavCom; Syra catalog-log search | No local captain's log; historical Syra matches available. Useful supplemental intent evidence, not complete current organization. |
| `timeline` | Existing catalog, listener | No lineage found. Source inspection shows heuristic version/qualifier ordering, not reconstructed historical states. |

## What exactly was adapted?

The current-catalog trial used Starforge's own `Catalog.add_project`, `Catalog.add_gem`, and complete `concept_search`. Each bounded repository description was represented as a README document record with a unique path-derived name. This changes the input shape, not the algorithm. It is **not** a full gem harvest or code-analysis benchmark: README records cannot exercise Python code-token similarity, and this small catalog has no harvest tree for source-grep expansion. The existing-catalog CLI trial exercised the normal catalog/harvest setup separately.

Three current-metadata searches took 0.126, 0.067 and 0.092 seconds in one process. They are single-run measurements, not cross-machine benchmarks. All trials used existing local code and data; no model calls or downloads.

## Where this leaves the shared architecture

1. **Starship supplies real places and state:** Git-family intake, physical copies, bounded dependency observations, ship/base identities, checkpoints and readiness. Consume their outputs with provenance and coverage. Do not duplicate commissioning or turn similarity into readiness.
2. **Starforge supplies discovery techniques:** source grouping, related-code retrieval, lineage candidates, scaffolding rejection, description/entry-point clues. Reuse these implementations through adapters rather than fork new versions into NavCom.
3. **NavCom supplies conversations and navigation:** attach conversation evidence, preserve search scope and provider ancestry, expose readable CLI/JSON, and render the result.

This division is a proposed integration boundary grounded in the observed code; it has not been wired into production. Neither Starship's physical inventory nor Starforge's similarity outputs should be renamed wholesale into planets or moons.

## Next bounded experiment

### Harvest follow-up, verified after the owner's reminder

The actual ingestion path is `harvest` → GitHub clone/update → `ProjectAnalyzer.analyze` → catalog project upsert → `GemFinder.scan` → catalog gem upserts. Search consumes those records and can inspect the cached source; it does not automatically discover uncataloged local working trees. The public harvest command accepts GitHub account or account/repo, not an arbitrary local path. Cached repos are updated using `git pull --ff-only`; local unpublished changes elsewhere are not included.

I ran the unchanged `Harvester._analyze_and_store` stage on the existing **99-file bounded EXP32 mirror**, with `ProjectAnalyzer(dispatcher=False)` and a lab-only catalog. It produced one project and **88 real code gems in 0.267 seconds**. The existing concept search for `reader` then returned `generative_reader`, `test_pair_reader`, and `pair_reader` with code-derived descriptions. No README-as-gem adaptation was used in this trial. No model call or GitHub cloning occurred. The project summary was minimal and its technology stack empty because this mirror lacks the complete repository context; this is not a full-harvest benchmark.

`rescan-gems` is another existing no-LLM path, but it only scans projects already in the catalog and clears/rebuilds the selected gem entries. It is not a substitute for registering missing projects. Do not run it against the original catalog as an incidental read-only check.

Reproduction: `~/.local/pipx/venvs/starforge/bin/python -B LABS/spatial-discovery/try_harvest_stage.py`; receipt: ignored `private/starforge-survey/harvest-stage/receipt.json`. This strengthens the reuse decision: adapt the existing harvest analysis pipeline to current local inventory rather than invent another indexer. Public GitHub harvest and local working-tree ingestion remain distinct input routes.

Before any integration, use Starship's inventory/inspection outputs to feed the **existing** Starforge catalog interfaces with current identities and paths. Test token groups within declared application roots and retain cohesion/coverage so giant mixed groups remain unlabeled. Evaluate lineage candidates against Git/source evidence rather than accepting name similarity as ownership.

Use a held-out set covering a different client, a monorepo, offline/moved copies and unrelated same-stack projects. Grade false containment, useful district clues, missed destinations and abstention. The present trials justify reusing the techniques; they do not establish a universal automatic classifier.

## Reproduction and receipts

Run from NavCom:

```sh
python3 LABS/spatial-discovery/survey_cli.py
~/.local/pipx/venvs/starforge/bin/python -B LABS/spatial-discovery/survey_library.py
~/.local/pipx/venvs/starforge/bin/python -B LABS/spatial-discovery/try_current_catalog.py
python3 -B LABS/spatial-discovery/check_starship_overlap.py
```

The CLI runner expects the private catalog copy created for this survey at `private/starforge-survey/home/catalog.json`, with `harvest-cache` referencing the existing local harvest. It sets `STARFORGE_GLOBAL_DIR` to that lab directory. It does not operate on the original catalog. Reproduction requires these local dependencies; this is not a standalone released package.

Private receipts: `cli-results.json` plus command output files; `library-results.json` with exact groups and borrowed-module hashes; `current-catalog-results.json`; `starship-inspection.json`. They remain Git-ignored. Reports intentionally summarize source analysis without publishing source bodies or private reference values.
