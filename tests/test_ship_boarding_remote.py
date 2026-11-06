"""An existing remote captain is observed, never recreated from a receipt command."""
import copy
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile

import pytest

import navcom_ship_boarding as boarding


def remote_fixture(tmp_path, monkeypatch):
    root = tmp_path / "fleet-owner"
    snapshot = root / "bridge/data.json"
    config = root / "LABS/101-captain-fleet/fleet.json"
    receipt = root / ".starship/commission/quartz/captain-current/receipt.json"
    for path in (snapshot, config, receipt):
        path.parent.mkdir(parents=True, exist_ok=True)
    cwd = "/Volumes/Unknown Fleet/quartz/working-copy"
    endpoint = "/private/tmp/native-quartz.sock"
    thread = "native-quartz-thread"
    config.write_text(json.dumps(dict(ssh_host="fixture-captain", remote_root="/Volumes/Unknown Fleet")))
    snapshot.write_text(json.dumps(dict(ships=[dict(id="quartz", destination="quartz/working-copy")])))
    data = dict(root=cwd, recorded_at="2026-10-12T01:35:00+00:00", native=dict(cwd=cwd, thread_id=thread,
        actual_app_server_resume_route=shlex.join(["codex", "resume", "--remote", "unix://" + endpoint,
                                                 "-C", cwd, "--no-alt-screen", thread])))
    receipt.write_text(json.dumps(data))
    entity = dict(id="ship:quartz", kind="ship", record_id="quartz", physical=dict(host="fixture-captain", path=cwd),
                  provenance=dict(snapshot=str(snapshot), config=str(config)))
    tool = tmp_path / "independently-installed"
    tool.mkdir()
    native = Path.home() / ".codex/skills/ship-commission/scripts"
    for name in boarding.TOOL_FILES:
        (tool / name).write_text((native / name).read_text() if (native / name).exists() else "native fixture")
    target = dict(alias="fixture-captain", executable="/usr/bin/ssh", hostname="192.0.2.20", user="owner", port="22", config_sha256="recorded-ssh-config")
    observation = dict(host="actual-fixture-host", uid=501, workspace=dict(path=cwd, device=1, inode=2),
        endpoint=dict(path=endpoint, target=endpoint, alias=dict(inode=4), stat=dict(inode=4)),
        runtime={key:dict(path="/installed/"+key, resolved="/installed/"+key, stat=dict(inode=idx))
                 for idx, key in enumerate(("node", "codex", "ws_module"), 10)})
    events = []
    def observe(actual_target, payload):
        assert actual_target == target
        events.append(copy.deepcopy(payload))
        return dict(observation=copy.deepcopy(observation), validated=payload["action"] == "validate")
    monkeypatch.setattr(boarding, "_ssh_target", lambda *_: copy.deepcopy(target))
    monkeypatch.setattr(boarding, "_remote_call", observe)
    return entity, receipt, data, tool, target, observation, events


def test_remote_plan_uses_existing_receipt_and_separates_host_alias(tmp_path, monkeypatch):
    entity, receipt, _, tool, _, observation, events = remote_fixture(tmp_path, monkeypatch)
    result = boarding.plan_boarding(entity, tool_root=tool)
    assert result["state"] == "planned", result
    assert [x["action"] for x in events] == ["observe"]
    assert result["route"]["host"] == "actual-fixture-host"
    assert result["route"]["ssh_alias"] == "fixture-captain"
    assert result["route"]["cwd"] == entity["physical"]["path"]
    assert result["route"]["path"] == str(receipt)
    assert result["provenance"]["remote"] == observation
    assert result["command"]["cwd"] == str(Path.home())
    assert result["command"]["argv"][:2] == ["/usr/bin/ssh", "-tt"]
    assert "Recheck the reviewed remote identity" in result["command"]["preview"]
    assert result["validation"]["status"] == "not checked"
    assert result["handoff"]["takeover_verified"] is False
    args = shlex.split(result["command"]["argv"][-1])
    assert args[:4] == ["/usr/bin/python3", "-I", "-B", "-c"]
    payload = json.loads(args[-1])
    assert payload["expected"] == observation and payload["action"] == "launch"
    assert payload["lookup"] == (tool / "captain_lookup.cjs").read_text()
    assert payload["lookup_sha256"] == hashlib.sha256(payload["lookup"].encode()).hexdigest()


@pytest.mark.parametrize("change", ["host", "path", "thread", "shell", "prompt", "config", "multiple", "symlink", "public_write", "no_socket"])
def test_inconsistent_or_unsafe_receipt_stops_before_ssh(tmp_path, monkeypatch, change):
    entity, receipt, data, tool, _, _, events = remote_fixture(tmp_path, monkeypatch)
    if change == "host": entity["physical"]["host"] = "-oProxyCommand=bad"
    elif change == "path": data["native"]["cwd"] = "/other/working-copy"
    elif change == "thread": data["native"]["thread_id"] = "different-thread"
    elif change == "shell": data["native"]["actual_app_server_resume_route"] += "; touch /never"
    elif change == "prompt": data["native"]["actual_app_server_resume_route"] += " 'send a prompt'"
    elif change == "config":
        Path(entity["provenance"]["config"]).write_text(json.dumps(dict(ssh_host="another-host")))
    elif change == "multiple":
        second = receipt.parent.parent / "other/receipt.json"
        second.parent.mkdir()
        other = copy.deepcopy(data)
        other["native"]["thread_id"] = "other-thread"
        other["native"]["actual_app_server_resume_route"] = other["native"]["actual_app_server_resume_route"].replace("native-quartz-thread", "other-thread")
        second.write_text(json.dumps(other))
    elif change == "no_socket": data["native"]["actual_app_server_resume_route"] = "codex resume native-quartz-thread"
    receipt.write_text(json.dumps(data))
    if change == "symlink":
        target = receipt.with_name("actual.json");receipt.rename(target);receipt.symlink_to(target)
    if change == "public_write": receipt.chmod(0o666)
    result = boarding.plan_boarding(entity, tool_root=tool)
    assert result["state"] == "blocked", result
    assert not events and result["command"] is None


def test_duplicate_same_route_receipts_are_not_ambiguous(tmp_path, monkeypatch):
    entity, receipt, data, tool, _, _, _ = remote_fixture(tmp_path, monkeypatch)
    duplicate = receipt.parent.parent / "supplement/receipt.json"
    duplicate.parent.mkdir();duplicate.write_text(json.dumps(data))
    result = boarding.plan_boarding(entity, tool_root=tool)
    assert result["state"] == "planned", result
    assert len(result["provenance"]["selected_receipts"]) == 2


def test_validation_and_launch_recheck_pins_and_never_send_prompt(tmp_path, monkeypatch):
    entity, _, _, tool, _, observation, events = remote_fixture(tmp_path, monkeypatch)
    validated = boarding.validate_boarding(entity, tool_root=tool)
    assert validated["state"] == "validated", validated
    assert sum(x["action"] == "validate" for x in events) == 1
    assert validated["validation"]["turn_sent"] is False
    calls = []
    result = boarding.launch_boarding(entity, approved_fingerprint=validated["fingerprint"], tool_root=tool,
                                     launcher=lambda **kwargs: calls.append(kwargs))
    assert result["handoff"]["status"] == "dispatched" and len(calls) == 1
    assert calls[0]["argv"] == validated["command"]["argv"]
    assert result["handoff"]["takeover_verified"] is False
    observation["endpoint"]["stat"]["inode"] += 1
    with pytest.raises(boarding.BoardingError, match="changed"):
        boarding.launch_boarding(entity, approved_fingerprint=validated["fingerprint"], tool_root=tool,
                                 launcher=lambda **_: pytest.fail("Stale route launched"))


@pytest.mark.parametrize("change", ["receipt", "ssh", "host", "runtime", "socket", "helper"])
def test_every_remote_identity_change_invalidates_review(tmp_path, monkeypatch, change):
    entity, receipt, data, tool, target, observed, _ = remote_fixture(tmp_path, monkeypatch)
    before = boarding.plan_boarding(entity, tool_root=tool)
    assert before["state"] == "planned", before
    if change == "receipt": receipt.write_text(json.dumps(dict(data, recorded_at="2026-10-13T00:00:00Z")))
    elif change == "ssh": target["hostname"] = "192.0.2.21"
    elif change == "host": observed["host"] = "other-host"
    elif change == "runtime": observed["runtime"]["node"]["stat"]["inode"] += 1
    elif change == "socket": observed["endpoint"]["stat"]["inode"] += 1
    else: (tool / "captain_lookup.cjs").write_text("changed helper")
    after = boarding.plan_boarding(entity, tool_root=tool)
    assert after["state"] == "planned", after
    assert before["fingerprint"] != after["fingerprint"]


def test_ssh_failure_unknown_host_and_archive_never_launch(tmp_path, monkeypatch):
    entity, _, _, tool, _, _, _ = remote_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(boarding, "_remote_call", lambda *_: (_ for _ in ()).throw(subprocess.TimeoutExpired("ssh", 28)))
    assert boarding.plan_boarding(entity, tool_root=tool)["state"] == "blocked"
    for altered in (dict(entity, form="archive"), dict(entity, physical={"path":"/remote/unknown"})):
        monkeypatch.setattr(boarding, "_remote_receipt", lambda *_: pytest.fail("Unsupported ship probed"))
        assert boarding.plan_boarding(altered)["state"] == "blocked"


def test_native_remote_worker_checks_real_socket_and_fixed_native_lookup(tmp_path):
    """Execute shipped observer with isolated paths and the unchanged native helper."""
    node = shutil.which("node")
    tool = Path.home() / ".codex/skills/ship-commission/scripts/captain_lookup.cjs"
    if not node or not tool.is_file(): pytest.skip("Optional installed Node/Starship helper absent")
    home = tmp_path / "host-home";home.mkdir()
    ship = tmp_path / "working-copy";ship.mkdir()
    installed = tmp_path / "installed";installed.mkdir()
    codex = installed / "codex"
    codex.write_text("#!"+sys.executable+"\nimport json,sys,os\nprint(json.dumps({'argv':sys.argv[1:],'cwd':os.getcwd()}))\n");codex.chmod(0o700)
    stack = home / ".local/share/agentworkforce/stack"
    module = stack / "node_modules/ws";module.mkdir(parents=True)
    (stack / "package.json").write_text(json.dumps(dict(name="exp31-agentworkforce-stack", dependencies={"ws":"fixture"})))
    log = tmp_path / "protocol.jsonl"
    (module / "index.js").write_text("""const fs=require('fs');const {EventEmitter}=require('events');
module.exports=class extends EventEmitter {constructor(){super();setImmediate(()=>this.emit('open'))}
send(raw){const m=JSON.parse(raw);fs.appendFileSync("""+json.dumps(str(log))+""",raw+'\\n');
if(m.id)setImmediate(()=>this.emit('message',JSON.stringify({id:m.id,result:m.method==='thread/read'?{thread:{id:'fixture-thread',cwd:"""+json.dumps(str(ship))+"""}}:{}})))}close(){}};""")
    # Only independent installation lookup paths differ from the shipped worker.
    code = boarding.REMOTE_WORKER.replace("Path.home()", "Path("+repr(str(home))+")")
    code = code.replace("Path('/opt/homebrew/bin/node')", "Path("+repr(node)+")")
    code = code.replace("Path('/opt/homebrew/bin/codex')", "Path("+repr(str(codex))+")")
    with tempfile.TemporaryDirectory(prefix="navboard-remote-", dir="/private/tmp") as folder:
        endpoint = Path(folder) / "captain.sock"
        sock = socket.socket(socket.AF_UNIX)
        try:
            sock.bind(str(endpoint))
            route = dict(cwd=str(ship),socket=str(endpoint),thread="fixture-thread")
            def run(payload):
                return subprocess.run([sys.executable,"-I","-B","-c",code],input=json.dumps(payload),text=True,capture_output=True,timeout=15)
            observed = run(dict(action="observe",route=route))
            assert observed.returncode == 0, observed.stdout+observed.stderr
            observation = json.loads(observed.stdout)["observation"]
            assert not log.exists(), "Preparation must not contact the captain"
            payload = dict(action="validate",route=route,expected=observation,lookup=tool.read_text(),lookup_sha256=hashlib.sha256(tool.read_bytes()).hexdigest())
            validated = run(payload)
            assert validated.returncode == 0, validated.stdout+validated.stderr
            assert json.loads(validated.stdout)["validated"] is True
            protocol = [json.loads(line) for line in log.read_text().splitlines()]
            assert [item["method"] for item in protocol] == ["initialize","initialized","thread/read"]
            assert protocol[-1]["params"] == dict(threadId="fixture-thread",includeTurns=False)
            launched = run(dict(payload,action="launch"))
            assert launched.returncode == 0, launched.stdout+launched.stderr
            assert json.loads(launched.stdout) == dict(argv=["resume","--remote","unix://"+str(endpoint),"fixture-thread"],cwd=str(ship))
            before = log.read_text()
            stale = copy.deepcopy(payload);stale["expected"]["host"] = "wrong-host"
            rejected = run(dict(stale,action="launch"))
            assert rejected.returncode == 1 and "identity changed" in rejected.stdout
            assert log.read_text() == before, "Wrong host must stop before native RPC"
        finally:
            sock.close()
