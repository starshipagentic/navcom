# Existing Starforge search covers the skipped files

2026-10-16. **Reuse decision: use Starforge code-search alongside gem/concept search. No search implementation or gem-selection rule needed changing for these omissions.**

## Proof

Tested the exact saved source snapshots from the local-harvest experiment, not later modified working files. Exposed them through a lab-only `harvest-cache/local-lab/<project>` layout and copied the lab catalog. Original repositories and the original Starforge catalog were unchanged.

The unchanged `starforge code-search` implementation found **40/40 files omitted by GemFinder**:

- 26 Markdown documents.
- 12 Python files.
- 2 TypeScript files.

Each coverage probe used an escaped known line from its expected file. This proves reachability with literal/regex search, not natural-language semantic relevance. All 40 probes together took 0.138 seconds inside the Python process, excluding startup. This tiny bounded sample is not a full-machine performance benchmark.

Five targeted queries also retrieved the intended files:

| Query | Expected omitted file | Result |
| --- | --- | --- |
| `class Discovery` | NavCom `navcom_discovery.py` | Found at line 79 |
| `isHumanMembershipRole` | Syra `role-grant-policy.ts` | Found |
| `Hotflywheel consumes explicit evidence events` | EXP32 `flywheel_adapter.py` | Found |
| `Signal proposals and protocol goals` | EXP32 `CONTROLLER-CONTRACT.md` | Found at line 1 |
| `MODELS\|model\|inference` | EXP32 `MODEL-MODES.md` | Found |

An absent marker returned zero rows. Searching for the Syra function within NavCom returned zero rows. Restricting the document-heading query to Python returned zero rows. Thus the positive results were not unconditional or cross-scope leakage in these checks.

## Real CLI verification

In the isolated lab directory, these actual subprocess commands succeeded:

```sh
starforge code-search 'class Discovery' --repo navcom --ext .py
starforge code-search 'Signal proposals and protocol goals' --repo exp32-hybrid-jev-cbt --ext .md
```

The code query took 0.763 seconds including process startup; the document query took 0.169 seconds. Both printed the expected file/line/content. The document's long path is truncated in the terminal table, but the untruncated Rich table cells confirm its exact identity.

Also ran existing `starforge search` and `starforge concept` for the document heading against the same catalog. They returned related code gems, not the omitted document. That is the relevant distinction: catalog/concept search does not provide all-file retrieval, while code-search reads source contents independently of gem membership.

## What already exists

`cli_reporting.py` registers `code-search`. It scans the harvest tree, accepts case-insensitive regular expressions, supports repository and extension filters, and includes `.md`, `.tsx`, `.jsx`, `.php`, configuration formats and other extensions beyond GemFinder's list. It does not require a file to pass the gem score or line-count rules.

The lab calls that registered command unchanged. Its capture adapter only records the Rich output table so tests can assert full paths; it does not implement matching, crawling, ranking, or filtering. Two subprocess checks additionally verify the real public CLI.

## Remaining integration work, not an algorithm rewrite

NavCom should retain both complementary result types: ranked gem/concept matches and source/document matches from existing code-search. Supply the current harvested source layout and preserve the conversation/source provenance. Keep query scope explicit.

Important limits before broadening:

- Code-search scans cached files each time; these measurements do not establish large-corpus latency.
- It is regex/keyword search, not semantic document retrieval.
- `--repo` is a substring filter, not an exact source-identity contract. This test's project names were distinct; an integration must isolate/validate exact scope when names overlap.
- Results are capped, and its terminal table can truncate paths. There is no JSON option on this command in the tested version. A structured adapter should preserve complete result provenance.
- Its current directory can override the global harvest location. The test explicitly chose its private working directory and environment.
- Default skipped directories and supported extensions still define coverage. Forty reachable omitted files do not prove every file in every repository is searchable.

## Reproduce

From NavCom, after the earlier local-harvest proof and skip audit exist:

```sh
~/.local/pipx/venvs/starforge/bin/python -B LABS/spatial-discovery/prove_broader_search.py
```

The script asserts all coverage/targeted probes and negative controls. It records the implementation hash, full untruncated result rows, queries, timing and CLI transcripts under ignored `private/broader-search/`. It does not publish source text.

Conclusion: the observed skipped-file gap was caused by using the gem catalog alone. Starforge already has the broader search capability we needed. Production integration remains deferred; this turn added only the lab proof and documentation.
