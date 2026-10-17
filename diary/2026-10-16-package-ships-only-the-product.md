# October 16, 2026 — The package ships only the product

**Pain:** the repository and PyPI are both public, and the sdist rules were
loose. The unanchored `README.md` and `docs` patterns pulled in nested READMEs,
all 17 internal contract docs, the galactic plan and 4.6 MB of TUI screenshots.
A proof build showed that without the new root `.gitignore` rule
`LABS/**/private/`, the old config would have shipped **3,188 private lab files
(an 18.0 MB sdist)**: machine-derived snapshots, catalogs and timing receipts.
Hatch does not read the nested `LABS/spatial-discovery/.gitignore`.

## Summary

- `.gitignore` now ignores `LABS/**/private/`, as the lab README always intended.
  The galaxy groundwork commit `4e18553` went in after this rule and a secret
  scan of 183 paths (no keys or tokens matched).
- The `pyproject.toml` sdist include is anchored with `/`. It ships:
  - the runtime files (the same set as the wheel);
  - README and pyproject;
  - features, tests, skills and `/scripts` (shipped tests need
    `scripts/import_starship_art.py`);
  - only `docs/conversation-atlas.md` from docs.
- Comparing builds from the same snapshot:
  - sdist: 187 → 171 files and 4,248,736 → 2,644,716 bytes (−38% compressed,
    −50% uncompressed);
  - wheel: unchanged, 55 files, every SHA-256 identical.
- `tests/test_packaging.py` (new) fails if a root `navcom*.py/js/css/html` file is
  missing from the wheel list, or if the sdist list stops being anchored.
- Docs cleanup:
  - The galactic plan went from 465 to 62 lines: the goal and eight steps stay,
    the stale header is now a status pointer, and 14 checkpoint sections were
    dropped after checking each against its diary entry. The original stays at
    `git show 4e18553:docs/galactic-implementation-plan.md`.
  - `docs/cli-spatial-gap-audit.md` was deleted: its "unsupported" verdicts are
    now false.
  - Five contracts lost stale "next step" sentences.
  - The LABS README notes it is superseded by `navcom_sources_worker.py` /
    `navcom_history.py` and that `private/` never ships.

## Decisions

- **Chosen:** anchor and narrow the sdist, and keep the wheel list as it was.
  **Rejected:** merging both lists into globs. It is fewer lines, but it risks
  silently dropping a runtime module. The packaging test is the guard instead.
- **Owner awareness:** client and employer names (Syra) and local paths
  already appear in committed code, the README, features and tests. That was true
  before this session, and the new diaries follow the same practice. Scrubbing
  them is a separate decision for the owner.
- `docs/architecture.md` and `docs/cli-concept-candidates.md` stay in the repo
  but out of the sdist, like the other internal docs. Four README links point to
  repo docs that are not in the sdist. They resolve on GitHub; inside the sdist
  they are dangling.

## Snippets

```sh
uv build --offline --out-dir "$SCRATCH/pkgcheck"
tar -tzf "$SCRATCH"/pkgcheck/navcom-*.tar.gz | cut -d/ -f2 | sort | uniq -c
unzip -l "$SCRATCH"/pkgcheck/navcom-*.whl | tail -3
.venv/bin/python -m pytest tests/test_packaging.py -q
git check-ignore -v LABS/spatial-discovery/private/snapshot.json   # .gitignore:… LABS/**/private/
```

## Files

- `.gitignore`: lab machine-derived snapshots stay local.
- `pyproject.toml`: anchored, narrowed sdist; `/scripts` added.
- `tests/test_packaging.py`: wheel completeness and sdist anchoring guard.
- `docs/galactic-implementation-plan.md`: trimmed to the goal, steps and status pointer.
- `docs/cli-spatial-gap-audit.md`: deleted (superseded).
- `docs/ship-boarding-contract.md`, `docs/starforge-history-contract.md`, `docs/starship-navigation-contract.md`, `docs/living-star-discovery-contract.md`, `docs/historical-landing-contract.md`: stale next-step sentences.
- `LABS/spatial-discovery/README.md`: superseded / private-stays-local line.
- `diary/2026-10-16-galactic-navigation-handoff.md`: one reading-trail line for the deleted audit.

## Appendix

- Final working-tree build after round 1: sdist 172 files (2,636,516 bytes; root 46, assets 9, docs 1, features 29, scripts 2, skills 1, tests 84), wheel 55 files (2,337,444 bytes).
- The wheel holds all 35 `navcom_*` modules imported anywhere (AST scan) and all 8 sprites in the web asset allowlist.
- The verifier installed the wheel into a throwaway venv, and `import navcom, navcom_web, navcom_space, navcom_navigation, navcom_atlas_cli` succeeded.

Tags: packaging, sdist, privacy, public-repo, labs-private, docs-cleanup. The
public package now carries the product and its tests, and none of the owner's
machine data.
