# Evidence retrieval (0.12)

`navcom_evidence.EvidenceCorpus(records, entities, coverage=(), parameters=None)`
provides `origin_context(entity, boundary)`, `related_evidence(entities, scope)` and
`evidence_pack(requirements, budget=4800)`. `FrozenEvidence` is a compatible alias.
Call `close()` when finished. All work stays in memory; no filesystem survey,
model calls, network calls or changes to the persistent conversation index occur.

Records have unique `id`, `session`, conversation `order`, `role`, `text`, `citation`,
and optionally `cwd`, `event_time`, `observed_at`, `source_kind`, `inventory`, `quoted`.
Entities have unique `id` and absolute `paths`. Requirements contain `entities`,
`slots` (request, action, change, contradiction, fact, outcome), optional `query`,
`scope` (session IDs) and absolute `boundary`. Output contains cited passages,
covered/missing slots, truncation and coverage, parameters, version and fingerprint.
Pass independently captured coverage; absence of a hit does not prove absence of work.

Opening implementation requests remain candidates before a project has a name.
Requests, actions, quotations, inventories and tool echoes remain distinct. Creation
attempts never establish successful creation. Event dates are not observation dates.
A transcript's user role does not authenticate owner decisions.

RRF blends lexical, origin and action rankings (k=60); MMR reduces repeated passages
(lambda=.7); fractional pair counts divide one episode across its pairs. Pair scores
never authorize an identity or exclude an explicit statement. NPMI remains an
experimental comparison, not an identity threshold. These are retrieval heuristics,
not semantic truth or a demonstrated general accuracy improvement.

Use `tests/test_evidence.py` for executable public examples. The 4800 limit is evidence
characters, not tokens. Model prompts and interpretations belong to the consumer.
