# Spatial discovery lab 01

Hypothesis, written before running the classifier: repository similarity alone is insufficient for the owner's geography. Typed structural evidence should reduce false ownership merges; Starforge's ranking may still help retrieve related research. Neither approach is assumed to solve automatic product discovery.

Scope: isolated scripts and reports here. Read existing NavCom project inventory and bounded local README/manifest metadata; do not harvest, index, invoke models, modify source projects or commission a ship. Private snapshots are ignored by Git. No existing curated `navcom_research.PROFILES` are imported.

Compare:

1. Existing directory categories and exact-path identities.
2. Actual Starforge `compute_repo_similarity`/`find_clusters` on extracted dependency/technology signals. Its graph describes similarity, so treating clusters as systems is an explicit experimental baseline, not its advertised ownership behavior.
3. Typed evidence: client-folder ownership candidates, Git common-directory/origin identity, experiment-folder candidates, and separately ranked text similarity. Never promote semantic similarity alone to ownership.

Use actual Starforge BM25 as an independent retrieval baseline against TF-IDF cosine retrieval. Threshold for related candidates is fixed at 0.12; top eight retrieval results. No tuning to these answers during the first run.

Predeclared real-data checks:

- Syra B2B, Syrenity iOS and Syra ML belong to the same client system; AwaliV2 and Awali lessons belong to another. Cross-client pairs must remain separate. These are owner-context judgments, not a comprehensive independently annotated benchmark.
- Syra B2B and Syrenity iOS are distinct product destinations. NavCom and Starforge are distinct products even when technology overlaps. EXP29, EXP30 and EXP32 remain distinct experiments rather than versions of a single repository.
- Query `chatbot listener protocol mental health` should retrieve EXP29, EXP30, EXP32 and Semantic Observatory in the first eight research destinations. Semantic Observatory is intentionally a difficult related-research case, not necessarily a chatbot.
- Find three requested Syra product destinations: B2B, enterprise mobile and CarePlus. Missing evidence or a generic repo label is a miss; finding three paths is not proof of three products.
- District retrieval should surface authentication/security evidence within Syra B2B, without treating similarly named capabilities in Awali as the same place.

Controlled checks use unfamiliar randomized names: same Git identity at moved paths, unrelated repositories with identical stacks, nested labs, a comparative mention that must not establish ownership, missing metadata, and multi-product monorepos. Controlled checks validate mechanisms only, not real discovery accuracy.

Report false merges, misses, abstentions, coverage, cold/warm time and memory. Keep all failed cases. Success on selected pairs is not proof of the entire universe. No code is promoted into NavCom based on this lab alone.
