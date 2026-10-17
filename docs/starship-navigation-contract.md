# Reuse Starship's existing inspection and recovery contracts

Read-only audit, 2026-10-16. No ship was restored, launched, contacted, commissioned,
or boarded. No credentials were opened. This records supported interfaces and
observed metadata, not present application or captain readiness.

## What is installed

The installed [ship-commission skill](/Users/t/.codex/skills/ship-commission/SKILL.md)
is `ship-commission lab101 recovery-first candidate2`, confirmed with:

```sh
python3 -B /Users/t/.codex/skills/ship-commission/scripts/ship.py --version
python3 -B /Users/t/.codex/skills/ship-commission/scripts/ship.py --help
python3 -B /Users/t/.codex/skills/ship-commission/scripts/fleet.py --help
```

There is no installed global `starship` or `ship-commission` command. The skill
explicitly says there is no global `ship commission SOURCE to DESTINATION` CLI.
Use its scripts, or a ship's carried `.starship/ship.py`; do not invent a command.

## Reusable operations and their actual boundaries

| Existing interface | What it proves / does | NavCom treatment |
| --- | --- | --- |
| `fleet.py SECTOR [SECTOR ...] --json --limit N` | Bounded, immediate-child metadata inspection. Descriptor binding, seal presence, handover location; no integrity/application/captain certification. | Reuse for explicit local physical-plane observation. Preserve truncation/errors. |
| `fleet.inspect_ship(Path(ROOT))` | Same observer for one selected known ship. Avoids treating every directory containing `.starship` as a commissioned ship. | Best narrow adapter for an existing ship destination. |
| `ship.py inspect --source ROOT` | Bounded static build/config/environment-reference inspection; returns `ready: false`. Does not run project code or reveal environment values. | Optional inspection, not a boarding check. |
| `ship.py capture-status --record RECORD` | Existing operation status receipt. | Inspect the exact operation; do not restart because an observation timed out. |
| `captain_locate.py ROUTE.json` | Validates trusted host-local route, owned socket, tools, thread ID and native cwd; prints a reconnect command. | Read-only validation on explicit request. A validated route is not application readiness. |
| `.starship/navcom.py --ship ROOT search WORDS` / `open REF` | Searches/opens carried indexed dialogue. | Reuse for a ship's context rather than conflating it with local native session resume. |
| `ship.py verify --ship ARCHIVE` | Archive integrity check; may be substantial. | Separate explicit operation, never silently run during map browsing. |
| `ship.py check --ship WORKING --contract CHECKS.json [--station STATION.json]` | Executes the declared receiving checks (commands/HTTP), with a total budget. `ready` only covers that contract. | Review the actual contract and scope before execution; not a read-only metadata action. |
| `ship.py restore --ship ARCHIVE --to NEW_COPY` / `recover --label LABEL ...` | Creates working/restored material. | A deliberate recovery operation; do not execute on map navigation. |

Authoritative implementations:
[fleet.py](/Users/t/.codex/skills/ship-commission/scripts/fleet.py),
[readiness.py](/Users/t/.codex/skills/ship-commission/scripts/readiness.py),
[ship.py](/Users/t/.codex/skills/ship-commission/scripts/ship.py),
[station_binding.py](/Users/t/.codex/skills/ship-commission/scripts/station_binding.py),
[commands guide](/Users/t/.codex/skills/ship-commission/references/commands.md).

The optional fleet `--live-config` path additionally requires explicit Docker,
socket and Node paths. Its current live observer knows a particular Node app,
Postgres and policy-service arrangement. It is not a generic probe for every
ship. Keep unsupported applications unknown.

## Real observations from this audit

The installed observer inspected this existing local archive:

```text
/Users/t/dev/starship/.starship/commission/cbt-origins/archive
state: recorded-descriptor
repositories: 1
descriptor_binding: stat-match-only
capture_evidence: seal-present-unverified
integrity / application_journey / captain: not checked
```

This is a current metadata observation. It establishes an inspectable archive,
not working code, current receiving readiness, or a restored viewpoint. The
broader `cbt-origins` sector scan at limit 30 reported `truncated: true`; do not
present that scan as complete fleet discovery.

A real NavCom receiving viewpoint is recorded in
[the receiving receipt](/Users/t/dev/starship/.starship/commission/navcom/evidence/captain-receiving-current/receipt.json):

- Completed 2026-10-12; status `completed-with-source-cli-format-gap`.
- Mission: recover an attributable carried NavCom design decision and test the
  transported source CLI without host history.
- Working/native cwd:
  `/Volumes/TM-ML-WORLD/starship/navcom/uss-navcom-lab99-run2-working`.
- Native Codex thread: `01a12dc3-c695-7f70-8742-9827293ac8ad`.
- Carried history: 24 Claude sessions, 458 messages, scoped to `/Users/t/dev/navcom`.
- The receipt records a dedicated app-server reconnect route. Cold resume,
  idle wake and native historical resume were not tested. The current route was
  not executed or validated by this audit.

The corresponding Syra
[receiving receipt](/Users/t/dev/starship/.starship/commission/syra/captain-current/receipt.json)
likewise separates native cwd/thread, a carried decision, local/demo checks and
unproved owner takeover. These receipts are good source records for a dossier;
do not collapse their separate evidence into a single green "ready" badge.

The locator was exercised against the existing
[Lab 54 route](/Users/t/dev/starship/LABS/54-captain-locator/run2/route.json).
It rejected it with `Cannot reconnect: route belongs to another host`. That is
the correct distinction: a saved route is not a valid route on this machine.
The script stopped before contacting a socket or launching anything.

The locator's
[Node helper](/Users/t/.codex/skills/ship-commission/scripts/captain_lookup.cjs)
uses app-server `initialize` and `thread/read(includeTurns:false)`. It does not
resume a thread or send a turn. Required route fields are `host`, `socket`,
`thread`, `cwd`, `codex`, `node`, and `ws_module`; obtain them from the actual host
record, not from a transcript or copied receipt. See
[captain reconnect](/Users/t/.codex/skills/ship-commission/references/captain-reconnect.md).

## Small NavCom adapter, without a competing ship system

Now implemented: `navcom_ship_inspection.py` (`navcom atlas inspect`) and
`navcom_ship_boarding.py` (`navcom atlas board`), shared with the bridge. The
steps below remain the boundary contract; do not rebuild them.

1. Keep `navcom_fleet`'s existing snapshot inventory. Add a bounded whitelist of
   historical dossier fields from each recorded receipt: mission, working root,
   thread/harness identity, evidence time, context coverage and explicit gaps.
   Preserve the receipt path and its signature so unchanged reads stay cached.
2. Offer **Inspect location** for the selected exact ship. Call the installed
   `fleet.inspect_ship` through an optional tool runtime; cache that observation
   separately with its timestamp. A remote path remains remote/unobserved unless
   an actual supported host route is configured; never test it as a local path.
3. Offer **Validate captain route** only when a trusted host-local route record
   exists. Reuse `captain_locate`; report absent, wrong-host, stale, rejected or
   validated. Return the validated command as reviewable data. Executing it is a
   distinct user action with its own visible takeover proof.
4. Show independent statuses: physical observation, archive integrity, receiving
   contract scope/time, carried-history coverage, captain-route validation and
   actual takeover. Do not derive any of these from a transcript count or seal.
5. For restoration, hand off to the existing `ship.py` contract and receiving
   handover procedure. NavCom should preserve location and viewpoint references,
   not implement credential projection, service restoration or captain dispatch.

## Stars: a real remaining inventory gap

Superseded: [living-star discovery](living-star-discovery-contract.md) now finds
declared expertise through native Hermes profiles (`navcom_stars.py`). The
finding below records the state before that adapter; its rules still apply.

The current Starship first-voyage
[decisions](/Users/t/dev/starship/plans/first-voyage/DECISIONS.md) explicitly reserve
autonomous stars. The broader
[vision](/Users/t/dev/starship/conversation-one.md) defines a maintained body of
expertise with usable interfaces; it does not provide a populated star registry.

No declared living-expertise registry was found in the current Starship bridge,
first-voyage implementation, or installed ship-commission interfaces inspected
here. This is a bounded finding, not proof that none exists in another project.
The bridge's `/api/routes` is an LLMCom captain registry, not an expertise/star
registry. A source folder named `star-family`, a Starforge package, or a ship
named `starforge` does not establish a running star or a callable expert.

Do not fabricate stars from those names. The next star integration requires an
actual declaration or registry from the owner's living-expertise project,
including its supported endpoint/CLI, scope and access contract. Keep declared
identity separate from a currently verified working interface.
