"""Plan and validate native captain reconnection through installed Starship tools.

Routes are host-local metadata, not portable authority. Only the installed
captain locator may validate them. No receipt command, project script, agent
message, restore operation or readiness check is executed. An explicit handoff
revalidates the exact plan before giving fixed argv to NavCom's trusted launcher.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import socket
import stat
import subprocess
import sys
import time

from navcom_ship_inspection import _absolute, _contains, _safe_path, commission_tools


VERSION = 1
ROUTE_BYTES = 16 * 1024
ROUTE_LIMIT = 24
FIELDS = ("host", "socket", "thread", "cwd", "codex", "node", "ws_module")
TOOL_FILES = ("captain_locate.py", "captain_lookup.cjs")
GAPS = [
    "Route validation proves a native thread/workspace binding at the observation time only.",
    "Application readiness, restored context, visible arrival and human takeover remain unverified.",
]


class BoardingError(ValueError):
    """A selected boarding route cannot be used without widening its scope."""

    def __init__(self, message, *, coverage=None, candidates=None):
        super().__init__(message)
        self.coverage = coverage
        self.candidates = candidates


def _signature(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _stamp(path):
    value = Path(path).stat()
    return dict(device=value.st_dev, inode=value.st_ino, size=value.st_size,
                mtime_ns=value.st_mtime_ns, ctime_ns=value.st_ctime_ns)


def _path(value):
    if not isinstance(value, str) or len(value) > 4096 or any(ord(c) < 32 for c in value):
        raise BoardingError("A route path is missing or invalid.")
    absolute = _absolute(value)
    if absolute is None:
        raise BoardingError("Route paths must be absolute and contain no parent traversal.")
    return Path(absolute)


def _selection(entity):
    if not isinstance(entity, dict) or entity.get("kind") != "ship" or not entity.get("id"):
        raise BoardingError("Select an exact catalog ship.")
    physical = entity.get("physical") if isinstance(entity.get("physical"), dict) else {}
    host = physical.get("host")
    local = isinstance(host, str) and host.casefold().rstrip(".") in {
        "localhost", "127.0.0.1", "::1", socket.gethostname().casefold().rstrip(".")}
    # This test must precede *any* filesystem access to the ship namespace.
    if not local:
        raise BoardingError("Ship location is remote or unspecified; no local boarding route was inspected.")
    root = _path(physical.get("path"))
    if not _safe_path(root) or not root.is_dir():
        raise BoardingError("The exact local ship directory is missing or linked through an unsafe path.")
    return root


def _read_route(path):
    path = _path(str(path))
    if not _safe_path(path):
        raise BoardingError("Captain routes cannot traverse links or private credential directories.")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
            raise BoardingError("Captain route must be an owned regular file, not writable by other users.")
        if info.st_size > ROUTE_BYTES:
            raise BoardingError("Captain route exceeds the 16 KiB metadata limit.")
        raw = os.read(fd, ROUTE_BYTES + 1)
        if len(raw) > ROUTE_BYTES:
            raise BoardingError("Captain route exceeds the 16 KiB metadata limit.")
    finally:
        os.close(fd)
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeError):
        raise BoardingError("Captain route is not valid JSON metadata.") from None
    if not isinstance(data, dict) or any(not isinstance(data.get(k), str) or not data[k] for k in FIELDS):
        raise BoardingError("Captain route lacks the native locator's required fields.")
    route = {k: data[k] for k in FIELDS}  # No arbitrary commands or private extras escape.
    if any(len(v) > 4096 or any(ord(c) < 32 for c in v) for v in route.values()):
        raise BoardingError("Captain route contains invalid scalar metadata.")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}", route["thread"]):
        raise BoardingError("Captain route has an invalid native thread ID.")
    for key in ("socket", "cwd", "codex", "node", "ws_module"):
        _path(route[key])
    return route, dict(path=str(path), sha256=hashlib.sha256(raw).hexdigest(), stat=_stamp(path))


def _route_paths(entity, root, explicit):
    if explicit is not None:
        return [_path(str(Path(explicit).expanduser()))], dict(basis="explicit route", truncated=False)
    # These are path declarations only, never shell commands extracted from a receipt.
    declared = [entity.get("captain_route_path")]
    captain = entity.get("captain")
    if isinstance(captain, dict):
        declared.append(captain.get("route_path"))
    paths = []
    for value in declared:
        if isinstance(value, str):
            paths.append(_path(value))
    directory = root / ".starship" / "runtime" / "captain"
    truncated = False
    entries = 0
    if _safe_path(directory) and directory.is_dir():
        # A directory with pathological fanout cannot make chart actions scan forever.
        with os.scandir(directory) as iterator:
            for entry in iterator:
                entries += 1
                if entries > 128:
                    truncated = True
                    break
                if entry.name.endswith(".json") and entry.is_file(follow_symlinks=False):
                    paths.append(Path(entry.path))
    paths = sorted(set(paths), key=str)
    truncated = truncated or len(paths) > ROUTE_LIMIT
    return paths[:ROUTE_LIMIT], dict(basis="declared route paths and native ship runtime/captain metadata",
                                   directories=1, entries=entries, truncated=truncated)


def _tool_identity(tool_root, root):
    path = _path(str(Path(tool_root).expanduser()))
    if ".starship" in path.parts or _contains(str(root), str(path)) or not _safe_path(path):
        raise BoardingError("Use installed ship-commission tools, never project-carried code.")
    hashes = {}
    for name in TOOL_FILES:
        item = path / name
        if not _safe_path(item) or not item.is_file() or item.stat().st_size > 256 * 1024:
            raise BoardingError("Installed captain locator is unavailable.")
        _installed_path(str(item), root)
        hashes[name] = hashlib.sha256(item.read_bytes()).hexdigest()
    return dict(root=str(path), files=hashes)


def _installed_path(value, root, *, executable=False):
    path = _path(value)
    resolved = path.resolve(strict=True)
    if ".starship" in path.parts or ".starship" in resolved.parts or _contains(str(root), str(resolved)):
        raise BoardingError("Captain runtime must be installed independently of the selected ship.")
    info = resolved.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid not in (0, os.getuid()) or info.st_mode & 0o022:
        raise BoardingError("Captain runtime must be an owner-controlled installed file.")
    if executable and not os.access(resolved, os.X_OK):
        raise BoardingError("An installed captain executable is unavailable.")
    return str(path), dict(path=str(resolved), stat=_stamp(resolved))


def _runtime(root, tool_root, trusted_runtime):
    """Resolve installations independently; no executable path is trusted from a route.

    An explicit trusted_runtime is operator configuration, never an entity or
    receipt field. Default command lookup uses the operator's PATH. The fixed
    Node expression resolves the ws module without importing or executing it.
    """
    configured = dict(trusted_runtime) if trusted_runtime is not None else {
        "codex": shutil.which("codex"), "node": shutil.which("node")}
    runtime, identity = {}, {}
    for key in ("codex", "node"):
        runtime[key], identity[key] = _installed_path(configured.get(key), root, executable=True)
    module = configured.get("ws_module")
    if module is None and trusted_runtime is None:
        bases = [str(tool_root)]
        # Existing LLMCom/AgentWorkforce installation contract. Inspect its
        # package declaration directly: invoking the wrapper can refresh skills.
        stack = Path.home() / ".local/share/agentworkforce/stack"
        package = stack / "package.json"
        try:
            if (_safe_path(package) and not _contains(str(root), str(stack)) and
                    package.is_file() and package.stat().st_size <= 64 * 1024):
                declared = json.loads(package.read_text())
                if (isinstance(declared, dict) and declared.get("name") == "exp31-agentworkforce-stack"
                        and isinstance(declared.get("dependencies"), dict) and "ws" in declared["dependencies"]):
                    bases.append(str(stack))
        except (OSError, ValueError):
            pass
        # Node startup flags/preloads are deliberately absent. No project cwd.
        completed = subprocess.run([runtime["node"], "-e",
            "process.stdout.write(require.resolve('ws',{paths:JSON.parse(process.argv[1])}))", json.dumps(bases)],
            cwd=str(tool_root), env={"PATH": os.defpath}, capture_output=True, text=True, timeout=5)
        if completed.returncode or len(completed.stdout) > 4096:
            raise BoardingError("Installed Node ws module is unavailable; configure a trusted runtime explicitly.")
        module = completed.stdout.strip()
    runtime["ws_module"], identity["ws_module"] = _installed_path(module, root)
    return runtime, identity


def _endpoint(route):
    endpoint = Path(route["socket"])
    info = endpoint.lstat()
    actual = endpoint.resolve(strict=True)
    target = actual.stat()
    if info.st_uid != os.getuid() or target.st_uid != os.getuid() or not stat.S_ISSOCK(target.st_mode):
        raise BoardingError("Captain endpoint is not an owned local Unix socket.")
    return dict(path=str(endpoint), target=str(actual),
                alias=dict(device=info.st_dev, inode=info.st_ino, mtime_ns=info.st_mtime_ns, ctime_ns=info.st_ctime_ns),
                target_stat=_stamp(actual))


def _same_runtime(key, declared, installed):
    selected = Path(installed).resolve(strict=True)
    recorded = Path(declared).resolve(strict=True)
    if selected == recorded:
        return True
    if key != "ws_module" or not recorded.is_dir():
        return False
    # Native require('/installed/node_modules/ws') and its entry file are both
    # valid. Compare only to the independently resolved package; never resolve
    # or import a route-selected module.
    for parent in list(selected.parents)[:3]:
        package = parent / "package.json"
        if not package.is_file():
            continue
        if not _safe_path(package) or package.stat().st_size > 64 * 1024:
            return False
        try:
            data = json.loads(package.read_text())
        except (OSError, ValueError):
            return False
        return isinstance(data, dict) and data.get("name") == "ws" and parent == recorded
    return False


def _command(route):
    return dict(argv=[route["codex"], "resume", "--remote", "unix://" + route["socket"], route["thread"]],
                cwd=route["cwd"], env={"PATH": str(Path(route["node"]).parent) + os.pathsep + os.defpath})


def _shell(spec):
    return "cd " + shlex.quote(spec["cwd"]) + " && " + shlex.join(
        ["env", "PATH=" + spec["env"]["PATH"]] + spec["argv"])


def _native_locate(route, tool_root):
    script = """import json,sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import captain_locate
assert Path(captain_locate.__file__).resolve() == (Path(sys.argv[1])/'captain_locate.py').resolve()
try:
    print(captain_locate.locate(json.load(sys.stdin)))
except Exception:
    raise SystemExit(1)
"""
    completed = subprocess.run([sys.executable, "-I", "-B", "-c", script, str(tool_root)],
        input=json.dumps(route), capture_output=True, text=True, timeout=15,
        env={"PATH": os.defpath, "HOME": str(Path.home())}, cwd=str(tool_root))
    if completed.returncode or len(completed.stdout) > 16 * 1024:
        raise BoardingError("Native captain validation failed; no session was resumed or turn sent.")
    if completed.stdout.strip() != _shell(_command(route)):
        raise BoardingError("Native captain locator returned an unexpected command; nothing was launched.")


def _prepare(entity, route_path, tool_root, trusted_runtime):
    if entity.get("form") == "archive":
        raise BoardingError("This is a stored ship archive. Read its carried context or select a working ship; archives cannot board a captain.")
    root = _selection(entity)
    paths, coverage = _route_paths(entity, root, route_path)
    matched, rejected = [], []
    for path in paths:
        try:
            route, provenance = _read_route(path)
            if route["host"] != socket.gethostname():
                raise BoardingError("Route belongs to another host.")
            if route["cwd"] != str(root):
                raise BoardingError("Route native workspace does not match the exact ship location.")
            matched.append((route, provenance))
        except (OSError, ValueError):
            rejected.append(str(path))
    coverage.update(inspected=len(paths), rejected_paths=rejected)
    if not matched:
        raise BoardingError("No owned route matches this host and exact ship workspace.", coverage=coverage)
    if len(matched) > 1 or coverage["truncated"]:
        raise BoardingError("Captain route discovery is ambiguous or incomplete; select an exact route file.",
                            coverage=coverage, candidates=[dict(path=p["path"], thread=r["thread"], cwd=r["cwd"])
                                                          for r, p in matched])
    route, provenance = matched[0]
    tool_path = Path(tool_root or commission_tools()).expanduser()
    tool = _tool_identity(tool_path, root)
    runtime, identity = _runtime(root, tool_path, trusted_runtime)
    for key in ("codex", "node", "ws_module"):
        if not _same_runtime(key, route[key], runtime[key]):
            raise BoardingError("Route runtime does not match the independently trusted installation.")
        # Use the independently selected executable paths, not metadata aliases.
        route[key] = runtime[key]
    endpoint = _endpoint(route)
    signature = dict(version=VERSION, ship_id=entity["id"], physical=entity["physical"],
                     route=provenance, fields=route, workspace=_stamp(root), tool=tool,
                     runtime=identity, endpoint=endpoint)
    return route, dict(schema_version=VERSION, ship_id=entity["id"], state="planned",
        fingerprint=_signature(signature), route=dict(path=provenance["path"], host=route["host"],
            thread=route["thread"], cwd=route["cwd"], socket=route["socket"], provider="codex"),
        provenance=dict(route=provenance, tool=tool, runtime=identity, endpoint=endpoint), coverage=coverage,
        command=_command(route), validation=dict(status="not checked", observed_at=None,
            methods=["initialize", "thread/read"], turn_sent=False),
        handoff=dict(status="not launched", visible_arrival_verified=False, takeover_verified=False),
        readiness=dict(application="not checked", receiving_context="not checked"), gaps=list(GAPS))


def plan_boarding(entity, *, route_path=None, tool_root=None, trusted_runtime=None):
    """Resolve a bounded, exact local route without contacting its captain socket.

    Missing/remote/unsupported routes return a blocked plan. Only direct operator
    configuration can select tools/runtime; do not pass untrusted metadata there.
    """
    try:
        _, result = _prepare(entity, route_path, tool_root, trusted_runtime)
        return result
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        reason = str(exc) if isinstance(exc, BoardingError) else "Required local route metadata or installed tooling is unavailable."
        return dict(schema_version=VERSION, ship_id=entity.get("id") if isinstance(entity, dict) else None,
                    state="blocked", reason=reason, command=None,
                    coverage=getattr(exc, "coverage", None), candidates=getattr(exc, "candidates", None),
                    validation=dict(status="not checked", observed_at=None, turn_sent=False),
                    handoff=dict(status="not launched", visible_arrival_verified=False, takeover_verified=False),
                    readiness=dict(application="not checked", receiving_context="not checked"), gaps=list(GAPS))


def validate_boarding(entity, *, route_path=None, tool_root=None, trusted_runtime=None):
    """Explicit read-only native thread/cwd validation; never resume or send a turn."""
    result = plan_boarding(entity, route_path=route_path, tool_root=tool_root, trusted_runtime=trusted_runtime)
    if result["state"] == "blocked":
        return result
    try:
        route, check = _prepare(entity, result["route"]["path"], tool_root, trusted_runtime)
        if check["fingerprint"] != result["fingerprint"]:
            raise BoardingError("Captain route changed during validation; inspect a fresh plan.")
        _native_locate(route, check["provenance"]["tool"]["root"])
        # Validation cannot bless bytes or socket identity changed during the call.
        _, after = _prepare(entity, result["route"]["path"], tool_root, trusted_runtime)
        if after["fingerprint"] != result["fingerprint"]:
            raise BoardingError("Captain route changed during validation; inspect a fresh plan.")
        result["state"] = "validated"
        result["validation"].update(status="validated", observed_at=time.time())
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        result["state"] = "blocked"
        result["reason"] = str(exc) if isinstance(exc, BoardingError) else "Native captain validation is unavailable."
        result["validation"].update(status="rejected", observed_at=time.time())
        result["command"] = None
    return result


def launch_boarding(entity, *, approved_fingerprint, launcher, route_path=None, tool_root=None, trusted_runtime=None):
    """User-initiated handoff only: revalidate, then call a trusted NavCom launcher.

    ``launcher`` receives keyword argv/cwd/env. It must be supplied by NavCom,
    never decoded from route or plan data. The callback must preserve existing
    terminals. Dispatch is explicitly not evidence of visible captain takeover.
    """
    if not isinstance(approved_fingerprint, str) or not approved_fingerprint or not callable(launcher):
        raise BoardingError("Launching requires an approved exact plan and a trusted NavCom launcher.")
    current = plan_boarding(entity, route_path=route_path, tool_root=tool_root, trusted_runtime=trusted_runtime)
    if current["state"] != "planned" or current["fingerprint"] != approved_fingerprint:
        raise BoardingError("Captain route changed or is unavailable; review and validate a fresh plan.")
    validated = validate_boarding(entity, route_path=current["route"]["path"], tool_root=tool_root, trusted_runtime=trusted_runtime)
    if validated["state"] != "validated" or validated["fingerprint"] != approved_fingerprint:
        raise BoardingError("Captain route could not be freshly validated; nothing was launched.")
    # Reconstruct from this validation, never a client-supplied command or shell string.
    spec = validated["command"]
    dispatched = launcher(argv=list(spec["argv"]), cwd=spec["cwd"], env=dict(spec["env"]))
    if dispatched is False:
        raise BoardingError("NavCom's terminal launcher rejected the handoff; arrival is unverified.")
    validated["handoff"].update(status="dispatched", dispatched_at=time.time())
    return validated
