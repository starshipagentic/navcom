# Native captain boarding adapter

2026-10-16. This checkpoint implements the shared service in
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

The existing Lab 54 route names another host. The NavCom and Syra receiving
receipts preserve native thread/workspace and historical resume strings, but
neither receipt contains the complete locator route. Those strings were not
executed or converted into trusted runtime configuration. Local Node cannot
resolve `ws` from the skill directory alone. The installed LLMCom wrapper's
existing AgentWorkforce package declares that dependency, however, and bounded
Node module resolution from that installation succeeds. The adapter reads the
package declaration without invoking the wrapper (which can refresh skills),
installing anything or using a project's module. Actual independent resolution
found `~/.local/bin/codex`, `/opt/homebrew/bin/node` and
`~/.local/share/agentworkforce/stack/node_modules/ws/index.js`.

## Shared service

```python
plan_boarding(entity, *, route_path=None, tool_root=None, trusted_runtime=None)
validate_boarding(entity, *, route_path=None, tool_root=None, trusted_runtime=None)
launch_boarding(entity, *, approved_fingerprint, launcher,
               route_path=None, tool_root=None, trusted_runtime=None)
```

`entity` must be an exact catalog ship with an explicitly local physical host and
absolute directory. Remote or unspecified locations stop before filesystem
access. The route's native workspace must equal that ship directory; a common
parent or similar project name is insufficient.

Plan automatically considers declared `captain_route_path` and
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

Plan returns fixed `argv`, `cwd`, a minimal `PATH` addition, provenance and a
fingerprint. It does not connect to the captain. Explicit validation calls only
the native locator, checks its result against the fixed command, and rejects
changes to route bytes, installed entry points, socket identity or workspace
during validation. No automatic background liveness probes run.

For an explicit human launch, pass the reviewed plan fingerprint and NavCom's
trusted terminal-launch callback. The adapter refreshes validation, rejects
changed plans, then gives the callback structured `argv`, `cwd`, `env`; it never
executes an arbitrary metadata command. The callback should reuse NavCom's
existing new-tab launcher and preserve existing windows. A failed callback is
not a dispatch. A successful dispatch still leaves visible arrival, retained
context, actual input/reply, message-route continuity and human takeover
unverified. Application and receiving readiness are separate unknown fields.

## Proof and remaining limits

The focused suite passed 22 cases, including the real installed locator against
an isolated Node protocol stub and temporary Unix socket. The protocol log
contained only `initialize`, `initialized`, `thread/read`. A separate fake Codex
executable received the exact resume arguments and ship cwd after revalidation.
This proves adapter execution and rejection boundaries; it is not a live captain
or human takeover test.

Other cases cover remote namespaces, wrong host/workspace, untrusted runtimes,
project-carried tools, thread option injection, route links/permissions/size,
automatic declarations, ambiguous/truncated discovery, changed route/tool/runtime/
socket identity, and cached-plan rejection. Tests required local Unix-socket
permission; the temporary endpoint and fixtures were cleaned up.

No unsupported harness is silently translated to Codex. Cold restart recovery,
remote attachment, restored original sessions, receiving checks and actual
visible takeover remain separate work. Runtime state can change after any
validation; the launch operation narrows that gap but cannot certify arrival.
