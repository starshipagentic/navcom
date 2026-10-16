# Dependency evidence and product destinations

NavCom now checks native dependency evidence before promoting a nested runnable manifest into a product planet. An npm package can have a `start` script for its own documentation or tests; a runnable entry alone does not establish another product in the surrounding suite.

The existing bounded manifest inspector calls Starforge's `starforge.dep_conflicts.extract_versioned_deps()` alongside its entry-point and build-system detectors. It uses the same immutable manifest views, with at most 64 manifest roots and 1 MiB per manifest. For a nested npm package, the nearest retained ancestor that declares that exact package supplies a `dependency_evidence` record: package name, declaring manifest, candidate manifest, native engine and relationship. Raw version specifications and dependency URLs are not copied into the geographic DTO.

A nonlocal dependency reference alone no longer promotes the nested candidate. Explicit workspace membership, private package declarations, local `file:`, `link:`, `workspace:` and `portal:` references, and an independently verified Git root retain their existing treatment. The normal declared-workspace discovery still runs when a source was harvested without automatic discovery metadata. Source coverage reports dependency components that did not qualify through native runnable evidence alone; the workspace pass may separately establish those addresses as products.

This is a conservative evidence rule, not a claim that every dependency is third-party code. It does not interpret npm command strings, execute scripts, use a vendor-directory blacklist, classify a client by name, or remove any retained files. Source search, file reading and native code groups remain available within the owning product. Manifests omitted by the existing budgets cannot supply dependency evidence, and malformed native dependency metadata is disclosed. Python and other package ecosystems retain their existing behavior in this bounded change.

The harvest fingerprint includes this adapter and the installed native module. Ordinary discovery/harvest recomputes changed declarations; a repeated unchanged operation reuses the artifact. Browsing only reads the published result.

## CLI proof, 2026-10-16

An unfamiliar instrument-suite fixture uses the public `sources discover --harvest`, `atlas refresh --space`, `atlas list planets` and both native source search paths. Two bundled dependencies stay inside their product; workspace, local, private and independently versioned packages remain destinations. Both search paths still find the bundled code. A separate repeated harvest is cached, and changing the ancestor manifest automatically updates the next chart through the same commands.

The real CarePlus project was discovered with its indexed collection ID into `/tmp/navcom-dependency-products-proof/sources`, without manually supplied includes or catalog edits. All 335 selected files remain. The first operation took 5.685 seconds; the second reported zero analyzed sources and one cached source. Starforge identified `konva` and `purecss` as dependencies of the retained root `package.json`. The new chart does not promote them to planets. A native search scoped to `public/assets/konva` still returns twenty text matches from `konva.js`; its concept search returns no matches for that query. The 104-test focused backend gate passed across geography, discovery, source-cache and historical navigation tests.

The same public command then updated the live source cache:

```sh
navcom sources discover --harvest --within projects:f4939af17514c879b18e --limit 1 \
  --index /Users/t/.codex/navcom-index.sqlite --cache /tmp/navcom-galaxy/sources --json
navcom atlas refresh --space --index /Users/t/.codex/navcom-index.sqlite \
  --source-cache /tmp/navcom-galaxy/sources --space-cache /tmp/navcom-galaxy/space.json --json
```

Live intake analyzed one source in 10.304 seconds; its separate repeat reported zero analyzed and one cached in 4.629 seconds. All 145 registered sources remain and every other source's root/includes are unchanged. The live Syra chart now lists 20 planets instead of 22: only the two dependency candidates disappear. B2B, nested enterprise mobile, the independent mobile copy and CarePlus retain their existing destination IDs. Proof JSON and command diagnostics are in `/tmp/navcom-dependency-products-proof/live-*.json` and adjacent `.stderr` files.
