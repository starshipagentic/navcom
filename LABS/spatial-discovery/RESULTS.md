# Lab 01 measured results

Inventory: {"cwds": 332, "local_directories": 228, "repository_roots": 288, "with_text": 74, "system_candidates": 7, "unassigned_roots": 246, "experiment_candidates": 38}

Timings (this process): {"collection_seconds": 9.628, "evaluation_seconds": 0.407, "peak_rss_mb": 53.95}
Metadata extracted/reused: 0/332

## Selected real-data pair checks

| A | B | Expected | Typed evidence | Starforge clusters used as ownership |
| --- | --- | --- | --- | --- |
| syrab2bdev | syrenity-ios | same_system | PASS | MISS |
| syrab2bdev | mlmodel | same_system | PASS | MISS |
| awaliv2 | awalilessons2 | same_system | PASS | MISS |
| syrab2bdev | awaliv2 | different_system | PASS | PASS |
| syrenity-ios | awalilessons2 | different_system | PASS | PASS |
| mlmodel | awaliv2 | different_system | PASS | PASS |
| syrab2bdev | syrenity-ios | different_product | PASS | PASS |
| navcom | starforge | different_product | PASS | PASS |
| exp29-llm-cbt-aug2026 | exp30-cbt-mlxmodel-sep2026 | different_product | PASS | PASS |
| exp30-cbt-mlxmodel-sep2026 | exp32-hybrid-jev-cbt | different_product | PASS | PASS |

These are selected owner-context checks, not population accuracy. Separate repository identities do not prove separate products. A singleton in a similarity graph is not evidence of different ownership.

## Related-research retrieval

Query: `chatbot listener protocol mental health`. Top eight, all available roots as distractors.

### tfidf
Found: exp29-llm-cbt-aug2026, exp30-cbt-mlxmodel-sep2026, exp32-hybrid-jev-cbt
Missed: semanticobservatory
- mental-health-zimber: 0.4554
- Syra%20-%20Chatbot: 0.3516
- 9 - syra health phrases: 0.1832
- chitchat-hsl-dsl-2: 0.1154
- exp29-llm-cbt-aug2026: 0.0724
- exp30-cbt-mlxmodel-sep2026: 0.0626
- product-strategy: 0.0442
- exp32-hybrid-jev-cbt: 0.0421

### starforge_bm25
Found: exp29-llm-cbt-aug2026, exp32-hybrid-jev-cbt
Missed: exp30-cbt-mlxmodel-sep2026, semanticobservatory
- exp29-llm-cbt-aug2026: 25.9484
- chitchat-hsl-dsl-2: 20.4882
- syrenity-mobile: 19.0928
- awaliv2-screen-gov: 14.6957
- awaliv2-real-linux-users: 14.6957
- awaliv2: 14.6957
- exp32-hybrid-jev-cbt: 13.3934
- capcom: 12.441

## Controlled checks

- PASS: move preserves repository identity
- PASS: same technology does not establish ownership
- PASS: comparative product mention does not establish ownership
- PASS: missing metadata abstains
- FAIL: monorepo yields separate product identity
- PASS: Starforge identical-stack baseline merges unrelated fixtures

## District candidates within Syra

- syrab2bdev: Local Cerbos PDP (README.md:21)
- syrab2bdev: Authorization Org-Scope Exceptions (authz-org-scope-exceptions.md:1)
- syrab2bdev: Cerbos local PDP — developer setup (cerbos.md:1)
- syrenity-mobile: 1. Mobile now runs entirely on Hub — client-side Cognito is gone (2026-06-02-status-for-hub-team.md:54)
- syrenity-mobile: 3. The new mobile auth endpoints are live and talking to real Cognito (2026-06-02-status-for-hub-team.md:129)
- syrenity-mobile: Web/universal app CORS issue — duplicate `Access-Control-Allow-Origin` (2026-06-08) (2026-06-08-cors-cloudflare-issue.md:1)
- syrenity-mobile: access-control-allow-origin: http://localhost:8094 (2026-06-08-cors-cloudflare-issue.md:65)
- syrenity-mobile: Expect: no access-control-allow-origin header (2026-06-08-cors-cloudflare-issue.md:70)
- syrenity-mobile: 🔴 Security — blocking (PRE-PRODUCTION-CHECKLIST.md:7)
- syrenity-mobile: Path 1 — Members (regular patients) via Cognito User Pool (api-surface.md:44)
- syrenity-mobile: Authentication (guardian path) (api-surface.md:85)
- CarePlus: Reporting Security Vulnerabilities (README.md:27)

## Limits

Client systems are folder-derived suggestions, not verified employment or ownership. Repo roots are candidate destinations, not solved product boundaries. Experiments are name/folder candidates, not proven moon ownership. Text-related edges never establish containment.
Bounded input: current NavCom cwd inventory; at most 12 README/manifest/docs files per root and 24,000 characters per file, at most eight top-level docs. No recursive code scan, transcripts, curated research profiles, model calls, raw session reads, downloads or external writes. Missing local roots remain visible.
The inventory includes B2B, syrenity-mobile and CarePlus as separate repository candidates under Syra. Product boundaries are still not proven: CarePlus exposes an upstream OpenEMR README and mobile a scaffold README. This lab cannot reliably identify multiple products inside one repository. There is no historical reconstruction or star/base/ship boarding.
Private machine-derived snapshots and detailed relationships are under ignored private/. No production behavior has changed.
