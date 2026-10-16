# Spatial discovery moon — lab 01

Follow-up: [Starforge reuse survey and Starship alignment](STARFORGE-FINDINGS.md) tests substantially more existing capabilities and corrects the initial narrow assessment. [Ranked investigation checklist](STARFORGE-PLAN.md).

**Result: useful partial discovery, not a proven automatic universe.** This is a runnable experiment inside NavCom. No NavCom production modules, Starforge code, Starship code, or client repositories were changed.

The lab reuses Starforge's actual repository graph and BM25 scorer through read-only source imports. It compares those with typed structural evidence and TF-IDF retrieval. The later reference-link experiment follows mentions of known repositories without treating those mentions as ownership.

## Run it

From the NavCom repository:

```sh
# Read existing NavCom inventory and bounded local metadata; write lab snapshots.
python3 LABS/spatial-discovery/lab.py

# These use the saved snapshot, with no Git probes or project rescan.
python3 LABS/spatial-discovery/lab.py --list-systems
python3 LABS/spatial-discovery/lab.py --system syra
python3 LABS/spatial-discovery/lab.py --query 'exp32 matrix'
python3 LABS/spatial-discovery/lab.py --system syra --query 'cognito authorization'
python3 LABS/spatial-discovery/lab.py --system awali --query 'data engineering workflows'

python3 -m unittest discover -s LABS/spatial-discovery -v
```

`--starforge-source PATH` selects the existing Starforge source directory for the comparison run. Default: `~/dev/starforge/src/starforge`. No package installation or resident model is required. Ordinary lab browsing uses only Python's standard library and the saved snapshot.

## What happened on October 15

The indexed inventory had 338 path groups. Six non-absolute/non-path labels were excluded. Of 332 usable paths, 228 currently existed locally. Collapsing working directories to local repository roots produced 288 destinations, including missing paths; only 74 had text in the bounded sample. These are repository/path candidates, not 288 established planets.

- **Systems:** seven client-folder candidates; 246 of 288 root destinations remained unassigned. It recovered the three selected same-client pairs and kept the three selected cross-client pairs separate. This relies on `/clients/<owner>/...`, not an understanding of W-2 versus personal ventures. Historical paths outside that layout remain a substantial gap.
- **Syra destinations:** B2B, `syrenity-mobile`, and CarePlus appeared separately without Syra-specific classifier code. Their metadata does not fully establish product boundaries: B2B/mobile have scaffold README content, and CarePlus's README describes upstream OpenEMR.
- **District clues:** the Syra-scoped query `cognito authorization` returned mobile and B2B, with Cerbos/authentication headings available as evidence. This is useful retrieval, not a finished district taxonomy. Some extracted headings are incidental debugging text.
- **Research:** the preregistered broad query found EXP29/30/32 in TF-IDF's top eight; the actual Starforge BM25 scorer found EXP29/32. Both missed Observatory. This one selected query cannot establish that one ranker is generally better.
- **Source relationships:** the exploratory second pass recovered Observatory through two explicit references between its documents and EXP32. No `navcom_research` profiles were used. It added a separate eight-result linked section; this is **not** four-of-four recall at the original eight-result budget. Linked results also included irrelevant destinations such as resumes and generic client directories.
- **Known failure:** two products in one repository are still conflated. Repository identity is useful evidence but cannot be the product model. Moons are only lab/name candidates; their product ownership is not established.

The exploratory `exp32 matrix` query returned Observatory first and EXP32 second. That is useful research proximity but does not satisfy an exact-project navigation request by itself. A named-project scope must remain distinct from broad text ranking.

## Starforge conclusion

Its graph uses dependency/technology overlap. On the available inputs it produced three clusters, including the Awali copies and a Syra prototype/B2B pair. It missed all three selected positive same-client pairs. Missing manifest coverage contributes to that result; the tool is designed for similarity, not business ownership.

The controlled identical-stack example also clustered unrelated projects. Therefore similarity edges can help find neighbors, but cannot safely become solar-system or product membership. The useful combination is structural evidence for candidate containment, text/code similarity for related places, and explicit source references for cross-project trails. None of these alone establishes all the desired meanings.

## Cost and cache measurements

Single runs on this Mac; not a performance benchmark:

| Operation | Measured wall time |
| --- | ---: |
| Initial inventory/metadata collection | 9.797 s |
| Repeated collection, all 332 metadata lookups reused | 9.628 s |
| Graph/ranking evaluation | about 0.4 s |
| First query including reference extraction | 5.803 s |
| Same query from cached references | 0.132 s |

Peak Python RSS during comparison was about 50 MiB; subprocess memory was not measured. No LLM calls, model downloads, GPU use or paid inference occurred. Warm collection is still slow because it repeats NavCom/Git/stat probes. Saved-snapshot browsing skips those probes. Reference caches are keyed by source signatures, scope and lab code, so changing scopes does not discard another scope's cache.

## Evidence and limits

- [Experiment definition](EXPERIMENT.md): initial checks and constraints, before classifier execution.
- [First-run comparison](RESULTS-v1.md): retained including misses; its original limitation paragraph predates inspection of the discovered CarePlus/mobile roots.
- [Current comparison report](RESULTS.md): measured pair checks, retrieval rankings and candidate headings.
- [Executable lab](lab.py) and [mechanism tests](test_lab.py): six passing tests and one explicit expected failure for the unresolved monorepo case. Expected failure records a missing capability, not success.
- Ignored `private/`: bounded source snapshots, detailed results, source hashes, reference evidence and timing receipts. Do not publish these machine-derived snapshots.

The checks are selected examples with owner-context labels, not a blinded representative benchmark. The reference-link revision was developed after inspecting the first miss and is exploratory. Synthetic unfamiliar-name checks show that linking is not tied to EXP names; they do not establish real-world precision. Current cached index freshness was reported stale throughout.

**Promotion decision: do not wire this into the real UI yet.** It demonstrates useful automatic clues and inexpensive cached navigation, but leaves ownership, monorepo products, missing historical locations, ranking noise and true moon relationships unresolved. The next experiment should supply richer existing ownership/product evidence and a held-out labeled sample, then measure abstention and false containment—not add more special project names to the classifier.

Next lab completed: [local harvest flow proof](HARVEST-RESULTS.md), with a [small stepwise plan](HARVEST-PLAN.md). NavCom orchestrates existing Starforge analysis, caches unchanged sources and links results back to conversations; Starship is not required.

Skipped-file follow-up: [existing Starforge broader-search proof](BROADER-SEARCH-RESULTS.md) retrieved all 40 omitted code/document files using unchanged `code-search`.
