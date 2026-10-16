# NavCom orchestrates local Starforge harvest

The owner corrected the direction: NavCom should ensure relevant sources are harvested and use Starforge's established functions. Starship commissioning is not a dependency. The earlier survey tested too little of Starforge; the broader survey found reusable grouping, lineage and search, with current catalog coverage a major gap.

Decided today: prove discovery → local harvest → cached search in a small lab. Reuse the real analyzer/gem finder and concept search. Preserve originals, disclose the selected scope, show progress, and prove unchanged material does not get reanalyzed. Test edits, deletion and failed refresh before considering integration.

Not decided: final command names, scheduling, packaging, broad machine scans, semantic ownership, cosmic layout, or production rollout. Fast ingestion is not proof that similarity groups equal products or moons. No new classifier is part of this step.

Plan and evidence: [local harvest plan](../LABS/spatial-discovery/HARVEST-PLAN.md). Implementation and measured outcome will be recorded in the lab after the drills.

## Lab outcome

The bounded flow now runs: NavCom discovery → local Starforge harvest → cached scoped search → NavCom conversation handoff. Three scopes supplied 155 files and 115 gems. Initial harvest measured 0.683 seconds; unchanged refresh measured 0.019 seconds with zero source analyses. Synthetic edit/delete/failure/lock/scope checks passed.

One original assertion failed: `discovery` found no NavCom gem because the existing gem finder omitted that file. The report preserves the miss; `atlas` succeeds. We have proven orchestration and caching, not exhaustive source retrieval or product ownership. Next investigate existing code-search for that gap, before adding another indexer. [Measured proof and reproduction](../LABS/spatial-discovery/HARVEST-RESULTS.md).
