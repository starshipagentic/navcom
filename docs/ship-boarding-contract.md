# Native captain boarding adapter

2026-10-17. This checkpoint implements the shared service in
`navcom_ship_boarding.py`; it is now wired as `navcom atlas board` and the
bridge's `POST /api/space/board`. No actual
captain was resumed, messaged or reassigned during this work. No ship was
restored, commissioned or moved.

## Existing native contract

The installed
[ship-commission skill](/Users/t/.codex/skills/ship-commission/SKILL.md) provides
[`captain_locate.py`](/Users/t/.codex/skills/ship-commission/scripts/captain_locate.py)
and its adjacent `captain_lookup.cjs`. The locator accepts an owned host-local
route with these fields: `host`, `socket`, `thread`, `cwd`, `codex`, `node`,
`ws_module`. It checks current host, owned Unix socket, executable availability
and exact native thread/workspace through `initialize` and
`thread/read(includeTurns:false)`. It prints a reconnect command without running
it or sending a turn:

```text
codex resume --remote unix://SOCKET THREAD
```

Native `runtime_owner.py` observes a PID's root; it has no captain route registry.
The inspected Starship bridge registry represents LLMCom message routes, not
Codex terminal attachments. Neither a receipt's shell string nor a searchable
transcript supplies a validated local route.

Receiving receipts can preserve a native thread, workspace and resume command
without containing a complete locator route. The remote adapter uses only a
strictly parsed socket/thread/workspace binding from those receipts. It never
executes their command text or trusts their executable paths. Runtime selection
remains independent. For `ws`, the installed AgentWorkforce package declares the
dependency; bounded Node module resolution can reuse that installation without
invoking its wrapper, installing anything or using a project's modules.

## Shared service

```python
plan_boarding(entity, *, route_path=None, tool_root=None, trusted_runtime=None)
validate_boarding(entity, *, route_path=None, tool_root=None, trusted_runtime=None)
launch_boarding(entity, *, approved_fingerprint, launcher,
               route_path=None, tool_root=None, trusted_runtime=None)
```

`entity` must be an exact catalog working ship with an explicitly recorded
physical host and absolute directory. Archives and unspecified locations cannot
board. The route's native workspace must equal that ship directory; a common
parent or similar project name is insufficient. Remote paths are never probed
as local paths.

### Local working ships

Local preparation automatically considers declared `captain_route_path` and
`captain.route_path` references plus immediate JSON files in the existing
`.starship/runtime/captain/` directory. The lookup reads at most 128 directory
entries and 24 candidate files, each at most 16 KiB. It follows no metadata links
or credential directories. Owner, regular-file and write-permission checks apply
to route files. Unknown fields are ignored, not exposed. A unique host/workspace
match is required; ambiguity or truncation requires an explicit selected route.
The optional `route_path` is a fallback, not a requirement to maintain a second
catalog manually.

Tool/runtime selection is separate from route metadata. The adapter uses the
installed skill, checks the two tool files, and independently resolves the
operator's installed `codex`, `node` and `ws` module. For `ws`, it reuses the
native skill and declared installed AgentWorkforce package resolution roots.
Callers may supply a trusted
operator runtime mapping instead; never construct that mapping from entity,
receipt or route contents. Runtime paths in the route must match those selected
installations. Ship-carried code is rejected. Node preloads and project cwd are
absent during the fixed module-resolution and native-validation calls.

Local preparation returns fixed `argv`, `cwd`, a minimal `PATH` addition,
provenance and a fingerprint. It does not connect to the captain. Explicit local
validation calls only the native locator, checks its result against the fixed
command, and rejects changes to route bytes, installed entry points, socket
identity or workspace during validation.

### Recorded remote working ships

An explicit boarding request binds the selected ship to its existing fleet
snapshot and config, including the configured SSH alias and exact remote path.
Bounded existing commission-receipt discovery must produce one unambiguous
socket/thread/workspace binding. Identical receipt bindings can agree; conflicting
threads, directories, routes or incomplete discovery stop preparation. No manual
route registry is maintained. `--route` and the optional trusted-runtime mapping
apply only to local ships.

Preparation performs bounded read-only SSH metadata checks using the existing
SSH configuration, batch mode and strict known-host checking. Forwarding and
connection reuse are disabled. The SSH alias and observed host are reported
separately. A fixed observer checks owned workspace/socket paths and independently
installed Node, Codex and `ws` identities. It does not contact the captain socket.

Explicit validation streams the unchanged, independently installed local
Starship `captain_lookup.cjs` helper to that host. It uses only `initialize`,
`initialized` and `thread/read(includeTurns:false)` to verify the exact thread and
workspace. This does not require installing the full locator on the remote host.
No remote files are written, services started, ships restored or prompts sent.
Ordinary browsing and inspection do not run boarding SSH checks.

The review fingerprint covers the fleet/config/receipt bytes, effective SSH
destination/config, helper and observer bytes, and observed remote
host/user/workspace/socket/runtime identities. `route.cwd` is the remote ship
directory; `command.cwd` is a local directory for NavCom's terminal launcher.
`command.preview` describes the identity recheck followed by the native SSH resume;
it is not the literal wrapper command. JSON retains the actual structured `argv`
for audit. Readiness and receiving status remain separate from route validation.

### Explicit launch boundary

For an explicit human launch, pass the reviewed plan fingerprint and NavCom's
trusted terminal-launch callback. The adapter refreshes validation, rejects
changed plans, then gives the callback structured `argv`, `cwd`, `env`; it never
executes an arbitrary metadata command. Remote launch checks the reviewed identity
and native thread again on the actual SSH connection before invoking the installed
Codex resume command. It creates no captain and sends no prompt. The callback
reuses NavCom's existing new-tab launcher and preserves existing windows. A failed callback is
not a dispatch. A successful dispatch still leaves visible arrival, retained
context, actual input/reply, message-route continuity and human takeover
unverified. Application and receiving readiness are separate unknown fields.

## Proof and remaining limits

The focused local/remote suite passed 44 cases, independently reviewed and rerun,
including the real installed locator against
an isolated Node protocol stub and temporary Unix socket. The protocol log
contained only `initialize`, `initialized`, `thread/read`. A separate fake Codex
executable received the exact resume arguments and ship cwd after revalidation.
This proves adapter execution and rejection boundaries; it is not a live captain
or human takeover test.

Other cases cover local/remote namespace confusion, wrong host/workspace, untrusted runtimes,
project-carried tools, thread option injection, route links/permissions/size,
automatic declarations, ambiguous/truncated discovery, changed route/tool/runtime/
socket identity, cached-plan rejection, exact receipt/fleet binding, conflicting
receipts, SSH alias/observed-host separation and remote launch rechecks. Tests required local Unix-socket
permission; the temporary endpoint and fixtures were cleaned up.

The source-checkout CLI also prepared and validated the recorded Syra working
ship on Bertha on October 17, 2026. Preparation took 1.451 seconds; validation took
4.667 seconds and retained the same review identity. The observed host was
`starshipengine.lan`, and the native thread/workspace matched the selected receipt.
These are dated read-only observations, not a terminal attachment or takeover
test. No live launch or turn was performed.

No unsupported harness is silently translated to Codex. Actual remote terminal
arrival, retained context and human input/reply remain unproved. Cold restart
recovery, restored original sessions and receiving checks are also separate.
Remote carried-conversation reading is not implied by SSH boarding support.
Runtime state can change after any validation; the launch operation narrows that
gap but cannot certify arrival.
