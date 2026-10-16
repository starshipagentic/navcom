"""Boarding plans are exact native bindings, never receipt-command execution."""
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile

import pytest

import navcom_ship_boarding as boarding


TOOL = Path.home() / ".codex/skills/ship-commission/scripts"


def fixture_route(tmp_path, monkeypatch):
    ship = tmp_path / "working ship"
    ship.mkdir()
    tools = tmp_path / "installed-tools"
    tools.mkdir()
    for filename in boarding.TOOL_FILES:
        (tools / filename).write_text("# fixture tooling\n")
    runtime = {}
    for name in ("codex", "node", "ws_module"):
        path = tools / name
        path.write_text("# installed fixture\n")
        path.chmod(0o700)
        runtime[name] = str(path)
    route = dict(host=socket.gethostname(), socket=str(tmp_path / "captain.sock"),
                 thread="native-thread-42", cwd=str(ship), **runtime)
    folder = ship / ".starship/runtime/captain"
    folder.mkdir(parents=True)
    path = folder / "route.json"
    path.write_text(json.dumps(route))
    entity = dict(id="fleet:ship:fixture", kind="ship", label="Working ship",
                  physical=dict(host="localhost", path=str(ship)))
    monkeypatch.setattr(boarding, "_endpoint", lambda route: dict(path=route["socket"], identity="fixture-socket"))
    config = dict(tool_root=tools, trusted_runtime=runtime)
    return entity, path, route, config


def test_automatic_plan_is_bounded_and_never_contacts_captain(tmp_path, monkeypatch):
    entity, path, route, config = fixture_route(tmp_path, monkeypatch)
    data = dict(route, command="touch /DO_NOT_RUN", token="PRIVATE_VALUE")
    path.write_text(json.dumps(data))
    monkeypatch.setattr(boarding, "_native_locate", lambda *_: pytest.fail("Plan contacted captain"))
    result = boarding.plan_boarding(entity, **config)
    assert result["state"] == "planned"
    assert result["route"]["path"] == str(path)
    assert result["command"]["argv"] == [route["codex"], "resume", "--remote", "unix://" + route["socket"], route["thread"]]
    assert result["command"]["cwd"] == route["cwd"]
    assert result["validation"]["status"] == "not checked"
    assert result["readiness"]["application"] == "not checked"
    assert "PRIVATE_VALUE" not in json.dumps(result) and "DO_NOT_RUN" not in json.dumps(result)


def test_declared_route_reference_outside_ship_is_automatic(tmp_path, monkeypatch):
    entity, path, route, config = fixture_route(tmp_path, monkeypatch)
    external = tmp_path / "host-route.json"
    path.rename(external)
    entity["captain"] = dict(route_path=str(external))
    result = boarding.plan_boarding(entity, **config)
    assert result["state"] == "planned" and result["route"]["path"] == str(external)


@pytest.mark.parametrize("host", [None, "", "another-machine"])
def test_remote_location_never_touches_namespace(tmp_path, monkeypatch, host):
    entity = dict(id="fleet:ship:remote", kind="ship", physical=dict(host=host, path="/remote/no-probe"))
    monkeypatch.setattr(boarding, "_route_paths", lambda *_: pytest.fail("Remote lookup"))
    monkeypatch.setattr(boarding, "_safe_path", lambda *_: pytest.fail("Remote stat"))
    assert boarding.plan_boarding(entity)["state"] == "blocked"


@pytest.mark.parametrize("change", ["host", "cwd", "runtime", "option-thread", "public-write", "symlink", "over-limit"])
def test_invalid_route_fails_before_native_code(tmp_path, monkeypatch, change):
    entity, path, route, config = fixture_route(tmp_path, monkeypatch)
    if change == "host":
        route["host"] = "other-host"
    elif change == "cwd":
        route["cwd"] = str(tmp_path)
    elif change == "runtime":
        other = tmp_path / "arbitrary-node"
        other.write_text("DO NOT EXECUTE")
        route["node"] = str(other)
    elif change == "option-thread":
        route["thread"] = "--yolo"
    path.write_text(json.dumps(route))
    if change == "public-write":
        path.chmod(0o666)
    elif change == "symlink":
        target = tmp_path / "untrusted.json"
        path.rename(target)
        path.symlink_to(target)
    elif change == "over-limit":
        path.write_text("x" * (boarding.ROUTE_BYTES + 1))
    monkeypatch.setattr(boarding, "_native_locate", lambda *_: pytest.fail("Bad route executed"))
    result = boarding.validate_boarding(entity, **config)
    assert result["state"] == "blocked" and result["command"] is None


def test_multiple_routes_and_bounded_lookup_need_explicit_selection(tmp_path, monkeypatch):
    entity, path, route, config = fixture_route(tmp_path, monkeypatch)
    second = path.with_name("another.json")
    second.write_text(json.dumps(dict(route, thread="other-thread")))
    assert boarding.plan_boarding(entity, **config)["state"] == "blocked"
    assert boarding.plan_boarding(entity, route_path=path, **config)["state"] == "planned"
    second.unlink()
    for n in range(boarding.ROUTE_LIMIT):
        path.with_name(f"extra-{n}.json").write_text("{}")
    assert boarding.plan_boarding(entity, **config)["state"] == "blocked"
    assert boarding.plan_boarding(entity, route_path=path, **config)["state"] == "planned"


def test_validation_is_read_only_and_rejects_mid_lookup_change(tmp_path, monkeypatch):
    entity, path, route, config = fixture_route(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(boarding, "_native_locate", lambda route, tool: calls.append(route["thread"]))
    result = boarding.validate_boarding(entity, **config)
    assert calls == [route["thread"]] and result["state"] == "validated"
    assert result["validation"]["turn_sent"] is False
    assert result["handoff"]["status"] == "not launched"
    def changed(route, tool):
        path.write_text(json.dumps(dict(route, thread="changed-thread")))
    monkeypatch.setattr(boarding, "_native_locate", changed)
    assert boarding.validate_boarding(entity, **config)["state"] == "blocked"


def test_launch_revalidates_and_dispatches_only_fixed_argv(tmp_path, monkeypatch):
    entity, path, route, config = fixture_route(tmp_path, monkeypatch)
    events = []
    monkeypatch.setattr(boarding, "_native_locate", lambda *_: events.append("validated"))
    plan = boarding.plan_boarding(entity, **config)
    def launcher(**spec):
        assert events == ["validated"]
        events.append(spec)
    result = boarding.launch_boarding(entity, approved_fingerprint=plan["fingerprint"], launcher=launcher, **config)
    assert events[1] == plan["command"]
    assert result["handoff"]["status"] == "dispatched"
    assert not result["handoff"]["visible_arrival_verified"] and not result["handoff"]["takeover_verified"]
    path.write_text(json.dumps(dict(route, thread="replacement-thread")))
    with pytest.raises(boarding.BoardingError, match="changed"):
        boarding.launch_boarding(entity, approved_fingerprint=plan["fingerprint"],
                                 launcher=lambda **_: pytest.fail("Stale plan launched"), **config)


@pytest.mark.parametrize("field", ["tool", "runtime", "endpoint"])
def test_plan_identity_covers_installed_tool_runtime_and_endpoint(tmp_path, monkeypatch, field):
    entity, path, route, config = fixture_route(tmp_path, monkeypatch)
    first = boarding.plan_boarding(entity, **config)
    if field == "tool":
        (config["tool_root"] / "captain_locate.py").write_text("# changed locator")
    elif field == "runtime":
        Path(config["trusted_runtime"]["codex"]).write_text("# changed runtime")
    else:
        monkeypatch.setattr(boarding, "_endpoint", lambda route: dict(path=route["socket"], identity="replacement-socket"))
    second = boarding.plan_boarding(entity, **config)
    assert first["fingerprint"] != second["fingerprint"]


def test_project_carried_tools_and_runtime_are_rejected(tmp_path, monkeypatch):
    entity, path, route, config = fixture_route(tmp_path, monkeypatch)
    assert boarding.plan_boarding(entity, tool_root=path.parent, trusted_runtime=config["trusted_runtime"])["state"] == "blocked"
    project_node = Path(route["cwd"]) / "node"
    project_node.write_text("DO NOT EXECUTE")
    project_node.chmod(0o700)
    runtime = dict(config["trusted_runtime"], node=str(project_node))
    assert boarding.plan_boarding(entity, tool_root=config["tool_root"], trusted_runtime=runtime)["state"] == "blocked"


def test_default_ws_resolution_reuses_declared_installed_stack_without_running_wrapper(tmp_path, monkeypatch):
    entity, path, route, config = fixture_route(tmp_path, monkeypatch)
    home = tmp_path / "home"
    stack = home / ".local/share/agentworkforce/stack"
    stack.mkdir(parents=True)
    (stack / "package.json").write_text(json.dumps(dict(name="exp31-agentworkforce-stack", dependencies=dict(ws="8.22.0"))))
    monkeypatch.setattr(Path, "home", lambda: home)
    monkeypatch.setattr(boarding.shutil, "which", lambda name: config["trusted_runtime"][name])
    calls = []
    def resolve(argv, **kwargs):
        calls.append(argv)
        assert argv[1:3] == ["-e", "process.stdout.write(require.resolve('ws',{paths:JSON.parse(process.argv[1])}))"]
        assert json.loads(argv[3]) == [str(config["tool_root"]), str(stack)]
        assert kwargs["env"] == {"PATH": os.defpath}
        return subprocess.CompletedProcess(argv, 0, stdout=route["ws_module"], stderr="")
    monkeypatch.setattr(boarding.subprocess, "run", resolve)
    assert boarding.plan_boarding(entity, tool_root=config["tool_root"])["state"] == "planned"
    assert len(calls) == 1


def test_native_ws_package_directory_matches_independently_resolved_entry(tmp_path, monkeypatch):
    entity, path, route, config = fixture_route(tmp_path, monkeypatch)
    package = config["tool_root"] / "node_modules/ws"
    package.mkdir(parents=True)
    (package / "package.json").write_text(json.dumps(dict(name="ws", main="index.js")))
    entry = package / "index.js"
    entry.write_text("// installed ws entry")
    config["trusted_runtime"]["ws_module"] = str(entry)
    route["ws_module"] = str(package)
    path.write_text(json.dumps(route))
    assert boarding.plan_boarding(entity, **config)["state"] == "planned"
    route["ws_module"] = str(package.parent)
    path.write_text(json.dumps(route))
    assert boarding.plan_boarding(entity, **config)["state"] == "blocked"


def test_installed_native_locator_fixture_and_fixture_launch(tmp_path):
    """Run the real installed locator against an isolated protocol stub, not a captain."""
    node = shutil.which("node")
    if not node or not all((TOOL / name).is_file() for name in boarding.TOOL_FILES):
        pytest.skip("Optional native ship-commission tools/Node unavailable")
    ship = tmp_path / "native working ship"
    ship.mkdir()
    runtime = tmp_path / "installed-fixture"
    runtime.mkdir()
    log = runtime / "protocol.jsonl"
    ws = runtime / "ws.cjs"
    ws.write_text("""const fs=require('fs'); const {EventEmitter}=require('events');
module.exports=class extends EventEmitter {
 constructor(url) { super(); setImmediate(()=>this.emit('open')); }
 send(raw) { const m=JSON.parse(raw); fs.appendFileSync(""" + json.dumps(str(log)) + """,JSON.stringify(m)+'\\n');
  if(m.id) setImmediate(()=>this.emit('message',JSON.stringify({id:m.id,result:m.method==='thread/read'?
   {thread:{id:'fixture-thread',cwd:""" + json.dumps(str(ship)) + """}}:{}}))); }
 close() {} };
""")
    codex = runtime / "codex"
    codex.write_text("#!" + sys.executable + "\nimport json,os,sys\nprint(json.dumps({'argv':sys.argv[1:],'cwd':os.getcwd()}))\n")
    codex.chmod(0o700)
    socket_dir = tempfile.TemporaryDirectory(prefix="navboard-", dir="/private/tmp")
    endpoint = Path(socket_dir.name) / "native.sock"
    sock = socket.socket(socket.AF_UNIX)
    try:
        sock.bind(str(endpoint))
        route = dict(host=socket.gethostname(), socket=str(endpoint), thread="fixture-thread", cwd=str(ship),
                     codex=str(codex), node=node, ws_module=str(ws))
        path = ship / ".starship/runtime/captain/route.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(route))
        entity = dict(id="fleet:ship:native-fixture", kind="ship", physical=dict(host="localhost", path=str(ship)))
        config = dict(tool_root=TOOL, trusted_runtime={k: route[k] for k in ("codex", "node", "ws_module")})
        result = boarding.validate_boarding(entity, **config)
        assert result["state"] == "validated", result
        methods = [json.loads(line)["method"] for line in log.read_text().splitlines()]
        assert methods == ["initialize", "initialized", "thread/read"]
        launched = []
        def launch(**spec):
            output = subprocess.run(spec["argv"], cwd=spec["cwd"], env=spec["env"],
                                    capture_output=True, text=True, check=True)
            launched.append(json.loads(output.stdout))
        handoff = boarding.launch_boarding(entity, approved_fingerprint=result["fingerprint"], launcher=launch, **config)
        assert launched == [dict(argv=["resume", "--remote", "unix://" + str(endpoint), "fixture-thread"], cwd=str(ship))]
        assert handoff["handoff"]["status"] == "dispatched"
        assert not handoff["handoff"]["takeover_verified"]
        methods = [json.loads(line)["method"] for line in log.read_text().splitlines()]
        assert methods == ["initialize", "initialized", "thread/read"] * 2
    finally:
        sock.close()
        socket_dir.cleanup()
def test_archive_cannot_probe_or_launch_a_captain(monkeypatch):
    entity = dict(id='ship:archive', kind='ship', form='archive')
    monkeypatch.setattr(boarding, '_selection', lambda *_: pytest.fail('Archive touched a workspace'))
    result = boarding.plan_boarding(entity)
    assert result['state'] == 'blocked' and result['command'] is None
    assert 'archive' in result['reason'].lower()
    assert boarding.validate_boarding(entity)['state'] == 'blocked'

