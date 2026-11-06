# October 17 — Products inside one repository

The owner asked what "identities for multiple products inside one repository"
meant and agreed to extend the existing mechanism. The concrete distinction is
between sharing a Git repository and being the same product. A mobile app, its
substantial successor and an admin app can be separate planets with separate
context, even when all three live in one checkout.

This continues [explicit product replacements](2026-10-17-declared-product-replacements.md)
and the [owner's spatial concept](2026-10-15-a-universe-you-can-return-to.md).
The [active plan](../docs/galactic-implementation-plan.md) remains open for the
specific product-generation facts and human voice/captain gates described below.

## Decision

Reuse `.navcom-space.json` inside each application already discovered through
the existing runnable workspace or native Starforge app evidence. The normal
chart refresh reads it. There is no new declaration registry, library, search
engine or manual synchronization step; no recursive search for arbitrary
declaration files. The root's declaration does not supply child IDs or replacement
claims. Child `id`, `label`, `description`, optional `system`, and `supersedes`
belong only to that exact application.

For example, the disposable proof has `apps/mobile-v1` and `apps/mobile-v2`, each
with its own ID, and the latter names the former in `supersedes`. The sibling
admin app is independent. The existing `atlas related` CLI, API and browser
Connections & versions panel consume the resulting edges unchanged. Help,
README, the bundled recall card, and the
[relationship contract](../docs/native-relationships-contract.md) explain the
root/application boundary.

Each app uses the existing root-product identity hash. Once declared, its ID
survives a folder move or split into a standalone Git repository. Coordinates
and existing system placement are retained. First adding an explicit ID to an
automatically named product still changes its ID; old automatic bookmarks are
not redirected. The old exact location's position is retained when available.

A valid declared ID with omitted kind now consistently means `planet`, including
at a root named `exp7`. This fixed a real split-out inconsistency. Explicit root
`moon`/`star` declarations still work; discovered app declarations are planets.
Undeclared experiment names retain their existing interpretation.

## Evidence and fixes found by tests

The new unit cases cover workspace and native app discovery, moves within and
outside a repository, independent nested Git roots, shared explicit IDs,
conflicting declarations, invalid metadata, exact stale observations, symlinked
files and intermediate directories, and application-specific systems. A
declaration cannot create a product from an unrelated directory or a build-only
shared package.

The native CLI/API cases use one real Git repository with three apps, actual
Starforge harvest, both native search paths and a separate conversation index.
They prove `refresh → related → returned show command`, exact app files and
conversation memberships, CLI/API agreement, and cached reads with zero harvests.
Moving the app before reharvest retains its old snapshot at its old recorded
address, marked unavailable/stale, rather than pretending those bytes came from
the new address. After reharvest, only the new source scope is attached. This
test caught and fixed an obsolete scope that otherwise produced a missing-path
error. Old snapshot read commands correctly reject a changed snapshot.

Checks passed: 84 focused identity/chart compatibility tests; the final affected
16 passed after a bounded prior-location lookup optimization; three native CLI/
API cases; and 187 architecture, declared-relationship, historical, action-rail
and relationship tests. The focused suites overlap. Historical tests retain the
existing rule that today's declarations do not become facts in a dated view.
The focused independent code review found no remaining actionable issue.

## Installed journey

Installed wheel: `/tmp/navcom-nested-products-dist/navcom-0.11.0-py3-none-any.whl`.
Version remains 0.11.0. Checkout, wheel and installed bytes match for the only
three runtime modules changed from the prior wheel: `navcom_space.py`,
`navcom_atlas_cli.py` and `navcom.py`. No browser implementation change was needed.

`/tmp/navcom-nested-products-lab.py` created a disposable Orchard Lab monorepo,
natively indexed three fixture conversations, and ran the installed public CLI:

1. `sources harvest` and ordinary `atlas refresh --space`.
2. `atlas related`, then its exact successor `atlas show` command.
3. `atlas files` and scoped `atlas search --evidence`, checking both concept and
   text matches and only the selected app's conversation.
4. Repeat `atlas related` and prove cache reuse with zero harvest invocations.

All installed assertions passed. In the real browser, entering Mobile Classic
showed only its own retained README/package and conversation. Connections &
versions showed Mobile Next as the declared successor. Fly reached Next with
only Next's sources/conversation. Back restored the exact earlier URL and panel;
reload preserved both. Captured browser error logs were empty.

![Separate app context and exact replacement navigation](evidence/2026-10-17-nested-product-identities.png)

The test server disabled only unrelated automatic intake. The data came from
installed CLI commands; no relationship or search result was mocked. Receipt:
`/tmp/navcom-nested-products-lab-receipt.json`; its `base` directory contains
`cli-proof.json`. The fixture server (PID 22066, port 62549) was stopped after
proof. No declarations were written to the owner's real project codebases.

The prior owner bridge process was no longer running. The regular bridge was
restored at `http://127.0.0.1:62550/?view=space&local=1` with the installed build,
existing `/tmp/navcom-galaxy` caches and `/Users/t/.codex/navcom-index.sqlite`.
It is PID 26964, exec session 92426, running
`/tmp/navcom-succession-bridge.py`. Verify that identity before any later restart.
The real galaxy loaded its systems, expert and starbase, and normal automatic
intake resumed. No PyPI publication or Git commit occurred.

## Remaining boundaries

This completes the mechanism for explicit identities and replacement links for
multiple discovered products in one repository. It does not decide the owner's
actual Syrenity predecessor/successor pairings or replacement dates. No real
product history was inferred or relabeled. Native version suggestions remain
separate from explicit declarations.

The full plan still has live microphone acceptance and visibly verified captain
takeover as human gates. The missing original ThriveCart transcripts remain the
recovery gap recorded in the [basic-search diary](2026-10-16-basic-solve2-search.md).
Do not reopen those gaps as new ranking/catalog work or mark the full goal done.
