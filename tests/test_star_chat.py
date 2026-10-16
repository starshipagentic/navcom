"""Only metadata inspection runs; fixture subprocesses are not expert answers."""
import copy
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time

import pytest

import navcom_star_chat as chat
import navcom_star_inspection as inspection
import navcom_stars as stars


def put(path, text, executable=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    if executable:
        path.chmod(0o700)
    return path


def profile(tmp_path, name="tides"):
    home = tmp_path.resolve() / "profile home"
    folder = home if name == "default" else home / "profiles" / name
    put(folder / "profile.yaml", "description: Maintains estuary measurements\n")
    put(folder / "SOUL.md", "# Estuary researcher\nMaintains measured coastal records.\n")
    put(folder / "config.yaml", "PRIVATE_CONFIGURATION_SENTINEL")
    put(folder / ".env", "PRIVATE_CREDENTIAL_SENTINEL")
    candidate = dict(id="star-candidate:" + hashlib.sha256(str(folder).encode()).hexdigest()[:20],
        provider="hermes-profile", provider_identity=str(folder), name="Estuary researcher",
        description="Maintains estuary measurements", qualification="declared_candidate",
        physical_binding=dict(kind="local_profile", path=str(folder), profile=name, hermes_home=str(home)),
        interfaces=[dict(effect="ask_agent", argv=["touch", "/DO_NOT_EXECUTE"])], gaps=[])
    return dict(id=candidate["id"], kind="star", label=candidate["name"], star=candidate)


def installed(tmp_path, monkeypatch):
    root = tmp_path / "installed-provider"
    put(root / "hermes_cli/_parser.py", """import argparse
PRE_ARGPARSE_INHERITED_FLAGS: list = [("--profile", True)]
parser = argparse.ArgumentParser()
parser.add_argument('--query')
def _inherited_flag(parser, *args): pass
_inherited_flag(parser, '--cli')
""")
    for name in ("hermes_cli/main.py", "hermes_cli/profiles.py", "hermes_constants.py", "toolsets.py", "hermes_cli/oneshot.py"):
        put(root / name, "# Fixed installed fixture; no model\n")
    put(root / "venv/bin/python", "# fixture interpreter identity\n", True)
    put(root / "venv/bin/hermes", "#!/usr/bin/env python3\nfrom hermes_cli.main import main\nmain()\n", True)
    monkeypatch.setattr(chat, "_installed", lambda: root)
    return root


def fake_inventory(monkeypatch, center):
    fresh = copy.deepcopy(center["star"])
    def discover(*args, **kwargs):
        assert kwargs["max_files"] == 250 and kwargs["max_bytes"] == 1024 * 1024
        return dict(candidates=[copy.deepcopy(fresh)], fingerprint=chat._digest(fresh),
                    observed_at=time.time(), coverage=dict(complete=True, files=2))
    monkeypatch.setattr(stars, "discover", discover)
    monkeypatch.setattr(chat, "_run", lambda request, seconds: chat._worker(request))
    monkeypatch.setattr(chat, "_profile_destination", lambda runtime, home, profile:
                        str(home if profile == "default" else home / "profiles" / profile))
    return fresh


def test_review_and_handoff_preserve_literal_question_and_default_profile(tmp_path, monkeypatch):
    center = profile(tmp_path, "default")
    provider = installed(tmp_path, monkeypatch)
    fake_inventory(monkeypatch, center)
    monkeypatch.setattr(inspection, "observe", lambda _: pytest.fail("Local metadata review observed a runtime"))
    question = "--profile=evil $(touch /BAD); `false`\nWhat does the charter say?"
    review = chat.prepare(center, question, tmp_path / "cache")
    assert review["state"] == "review_required"
    assert review["handoff"]["argv"] == [str(provider / "venv/bin/python"), "-I", "-B", "-c", chat.ENTRYPOINT,
                                          str(provider), "--profile=default", "chat", "--cli", "--query=" + question]
    assert review["handoff"]["cwd"] == center["star"]["physical_binding"]["path"]
    command = shlex.split(review["handoff"]["command"])
    assert command[-1] == "--query=" + question
    assert "/DO_NOT_EXECUTE" not in json.dumps(review)
    assert review["readiness"] == "unverified" and not review["execution"]["question_sent"]
    assert not review["execution"]["tools_disabled"]
    opened = chat.handoff(center, question, tmp_path / "cache", review_token=review["review_token"])
    assert opened["state"] == "ready_for_native_handoff"
    assert opened["handoff"] == review["handoff"]
    assert not opened["execution"]["agent_started"]
    assert "PRIVATE_" not in json.dumps(opened)


@pytest.mark.parametrize("change", ["question", "description", "launcher", "charter"])
def test_stale_review_requires_new_review(tmp_path, monkeypatch, change):
    center = profile(tmp_path)
    provider = installed(tmp_path, monkeypatch)
    fresh = fake_inventory(monkeypatch, center)
    before = chat.prepare(center, "Explain the evidence", tmp_path / "cache")
    question = "Explain the evidence"
    if change == "question":
        question = "A different question"
    elif change == "launcher":
        with (provider / "venv/bin/hermes").open("a") as stream:
            stream.write("# changed installed provider\n")
    else:
        fresh[change] = "Changed metadata evidence"
    with pytest.raises(chat.StarChatError, match="changed"):
        chat.handoff(center, question, tmp_path / "cache", review_token=before["review_token"])


def test_missing_or_changed_binding_is_rejected(tmp_path, monkeypatch):
    center = profile(tmp_path)
    installed(tmp_path, monkeypatch)
    fresh = fake_inventory(monkeypatch, center)
    fresh["physical_binding"]["path"] += "-changed"
    with pytest.raises(chat.StarChatError, match="physical binding"):
        chat.prepare(center, "Where are you?", tmp_path / "cache")
    fresh["id"] = "another-id"
    with pytest.raises(chat.StarChatError, match="no longer discoverable"):
        chat.prepare(center, "Where are you?", tmp_path / "cache")


def test_native_profile_resolution_cannot_redirect_to_another_home(tmp_path, monkeypatch):
    center = profile(tmp_path)
    installed(tmp_path, monkeypatch)
    fake_inventory(monkeypatch, center)
    monkeypatch.setattr(chat, "_profile_destination", lambda *args: str(tmp_path / "other-profile"))
    with pytest.raises(chat.StarChatError, match="different home"):
        chat.prepare(center, "Question", tmp_path / "cache")


def compose(tmp_path):
    root = tmp_path.resolve() / "unfamiliar research"
    file = put(root / "compose.yaml", "# fixture declaration\n")
    candidate = dict(id="star-candidate:coast", provider="hermes-compose", provider_identity=str(file) + "#worker",
        name="Coastal expert", description="Maintains coastal evidence", qualification="declared_candidate",
        physical_binding=dict(kind="compose_service", repository=str(root), compose=str(file), service="worker",
                              container_name="coastal-worker", image="coast:7", ports_declared=False),
        interfaces=[dict(effect="ask_agent", argv=["arbitrary", "wrapper"])], gaps=[])
    return dict(id=candidate["id"], kind="star", star=candidate)


def test_compose_handoff_verifies_and_pins_current_context(tmp_path, monkeypatch):
    center = compose(tmp_path)
    fake_inventory(monkeypatch, center)
    docker = put(tmp_path / "installed/docker", "# fixture docker; never executed\n", True)
    monkeypatch.setattr(chat.shutil, "which", lambda _: str(docker))
    monkeypatch.delenv("DOCKER_HOST", raising=False)
    monkeypatch.delenv("DOCKER_CONTEXT", raising=False)
    monkeypatch.setenv("DOCKER_CONFIG", str(tmp_path / "docker config"))
    monkeypatch.setattr(inspection, "_runtime_identity", lambda _: "context-fingerprint")
    calls = []
    monkeypatch.setattr(inspection, "observe", lambda candidate: calls.append(candidate["id"]) or
        dict(state="container_running", binding_matches=True, runtime=dict(context="coastal-local")))
    review = chat.prepare(center, "Summarize the methods", tmp_path / "cache")
    assert calls == []
    result = chat.handoff(center, "Summarize the methods", tmp_path / "cache", review_token=review["review_token"])
    assert calls == [center["id"]]
    assert result["handoff"]["argv"] == [str(docker), "--context", "coastal-local", "exec", "coastal-worker", "hermes", "chat", "--query=Summarize the methods"]
    assert not result["execution"]["question_sent"] and result["readiness"] == "unverified"
    assert result["handoff"]["env"]["DOCKER_CONFIG"] == str(tmp_path / "docker config")
    monkeypatch.setattr(inspection, "observe", lambda _: dict(state="binding_unverified"))
    with pytest.raises(chat.StarChatError, match="does not match"):
        chat.handoff(center, "Summarize the methods", tmp_path / "cache", review_token=review["review_token"])
    monkeypatch.setattr(inspection, "_runtime_identity", lambda _: "different-context")
    monkeypatch.setattr(inspection, "observe", lambda _: dict(state="container_running", binding_matches=True, runtime=dict(context="other")))
    with pytest.raises(chat.StarChatError, match="changed"):
        chat.handoff(center, "Summarize the methods", tmp_path / "cache", review_token=review["review_token"])


def test_unsupported_host_override_and_project_docker_are_blocked(tmp_path, monkeypatch):
    center = compose(tmp_path)
    fake_inventory(monkeypatch, center)
    docker = put(tmp_path / "installed/docker", "# installed fixture\n", True)
    monkeypatch.setattr(chat.shutil, "which", lambda _: str(docker))
    monkeypatch.setenv("DOCKER_HOST", "ssh://private:secret@host.invalid")
    monkeypatch.delenv("DOCKER_CONTEXT", raising=False)
    with pytest.raises(chat.StarChatError, match="DOCKER_HOST") as error:
        chat.prepare(center, "Question", tmp_path / "cache")
    assert "secret" not in str(error.value)
    monkeypatch.delenv("DOCKER_HOST")
    project_docker = put(Path(center["star"]["physical_binding"]["repository"]) / "bin/docker", "DO_NOT_RUN", True)
    monkeypatch.setattr(chat.shutil, "which", lambda _: str(project_docker))
    with pytest.raises(chat.StarChatError, match="outside the project"):
        chat.prepare(center, "Question", tmp_path / "cache")


def test_broad_inventory_parent_refreshes_the_selected_git_repository(tmp_path, monkeypatch):
    center = compose(tmp_path / "inventory")
    actual = Path(center["star"]["physical_binding"]["repository"])
    subprocess.run(["git", "init", "-q", str(actual)], check=True)
    original = actual.parent
    center["star"]["physical_binding"]["repository"] = str(original)
    fresh = fake_inventory(monkeypatch, center)
    fresh["physical_binding"]["repository"] = str(actual)
    calls = []
    def discover(roots, *args, **kwargs):
        calls.append(roots)
        return dict(candidates=[copy.deepcopy(fresh)], fingerprint="fixture-selected-repo",
                    observed_at=1, coverage=dict(complete=True))
    monkeypatch.setattr(stars, "discover", discover)
    docker = put(tmp_path / "installed/docker", "# fixture\n", True)
    monkeypatch.setattr(chat.shutil, "which", lambda _: str(docker))
    monkeypatch.delenv("DOCKER_HOST", raising=False)
    monkeypatch.setattr(inspection, "_runtime_identity", lambda _: "fixture-context")
    monkeypatch.setattr(inspection, "observe", lambda _: pytest.fail("Preparation contacted Docker"))
    result = chat.prepare(center, "Research question", tmp_path / "cache")
    assert calls[0][0]["root"] == str(actual)
    assert result["coverage"]["recorded_inventory_root"] == str(original)
    assert result["coverage"]["selected_root"] == str(actual)
    assert result["state"] == "review_required"


@pytest.mark.parametrize("question", ["", "  ", "x" * 4001, "bad\x00", "bad\x1b", "bad\x9b"])
def test_invalid_questions_never_inspect_or_execute(tmp_path, monkeypatch, question):
    monkeypatch.setattr(chat, "_run", lambda *a, **k: pytest.fail("Invalid question caused work"))
    with pytest.raises(chat.StarChatError):
        chat.prepare(profile(tmp_path), question, tmp_path / "cache")


def test_metadata_worker_has_time_and_output_bounds(tmp_path, monkeypatch):
    monkeypatch.setattr(chat, "SCRIPT", "import time; time.sleep(10)")
    start = time.monotonic()
    with pytest.raises(chat.StarChatError, match="time budget"):
        chat._run({}, .1)
    assert time.monotonic() - start < 2
    monkeypatch.setattr(chat, "SCRIPT", "import sys;sys.stderr.write('x'*70000)")
    with pytest.raises(chat.StarChatError, match="output budget"):
        chat._run({}, 2)


def test_actual_native_inventory_and_installed_parser_no_chat(tmp_path):
    provider = chat._installed()
    tools = Path.home() / ".codex/skills/ship-commission/scripts/borrowed"
    if not (provider / "venv/bin/hermes").is_file() or not (tools / "build_systems.py").is_file():
        pytest.skip("Optional installed Hermes/Starship metadata providers are absent")
    center = profile(tmp_path)
    home = Path(center["star"]["physical_binding"]["hermes_home"])
    found = stars.discover([], profile_home=home)
    center["star"] = next(row for row in found["candidates"] if row["id"] == center["id"])
    before = {str(p): p.read_bytes() for p in home.rglob("*") if p.is_file()}
    review = chat.prepare(center, "LITERAL_PRIVATE_QUESTION", tmp_path / "review-cache")
    assert "--profile=tides" in review["handoff"]["argv"]
    assert "--cli" in review["handoff"]["argv"]
    final = chat.handoff(center, "LITERAL_PRIVATE_QUESTION", tmp_path / "review-cache", review_token=review["review_token"])
    assert final["state"] == "ready_for_native_handoff"
    assert before == {str(p): p.read_bytes() for p in home.rglob("*") if p.is_file()}
    assert all(b"LITERAL_PRIVATE_QUESTION" not in p.read_bytes() for p in (tmp_path / "review-cache").rglob("*") if p.is_file())
    assert not final["execution"]["question_sent"]


def test_fixture_terminal_receives_literal_argv_and_context(tmp_path, monkeypatch):
    """The only executed handoff program is this explicit Python argv recorder."""
    center = profile(tmp_path)
    installed(tmp_path, monkeypatch)
    fake_inventory(monkeypatch, center)
    question = "--profile=evil; $(touch bad)\nWhat now?"
    review = chat.prepare(center, question, tmp_path / "cache")
    handoff = chat.handoff(center, question, tmp_path / "cache", review_token=review["review_token"])["handoff"]
    recorder = put(tmp_path / "recorder.py", "import json,os,sys; print(json.dumps({'argv':sys.argv[1:],'cwd':os.getcwd(),'home':os.environ['HERMES_HOME']}))")
    recorded = subprocess.run([sys.executable, str(recorder)] + handoff["argv"][1:], cwd=handoff["cwd"],
        env=dict(os.environ, **handoff["env"]), capture_output=True, text=True, timeout=3, check=True)
    data = json.loads(recorded.stdout)
    assert data["argv"][-1] == "--query=" + question
    assert data["cwd"] == handoff["cwd"] and data["home"] == handoff["env"]["HERMES_HOME"]
    assert not (Path(handoff["cwd"]) / "bad").exists()


def test_native_entrypoint_isolated_from_ambient_import_overrides(tmp_path, monkeypatch):
    """Run only a disposable Hermes-shaped module, never the installed agent."""
    center = profile(tmp_path)
    provider = installed(tmp_path, monkeypatch)
    interpreter = provider / "venv/bin/python"
    interpreter.unlink()
    interpreter.symlink_to(sys.executable)
    put(provider / "hermes_cli/__init__.py", "")
    put(provider / "hermes_cli/main.py", "import json,sys\ndef main(): print(json.dumps({'provider':__file__,'argv':sys.argv[1:]}))\n")
    malicious = tmp_path / "ambient"
    put(malicious / "hermes_cli/__init__.py", "")
    marker = tmp_path / "ambient-import-ran"
    put(malicious / "hermes_cli/main.py", "from pathlib import Path\nPath(" + repr(str(marker)) + ").touch()\n")
    monkeypatch.setenv("PYTHONPATH", str(malicious))
    monkeypatch.setenv("PYTHONHOME", str(malicious))
    fake_inventory(monkeypatch, center)
    review = chat.prepare(center, "Fixture question", tmp_path / "cache")
    spec = chat.handoff(center, "Fixture question", tmp_path / "cache", review_token=review["review_token"])["handoff"]
    completed = subprocess.run(spec["argv"], cwd=spec["cwd"], env=dict(os.environ, **spec["env"]),
                               capture_output=True, text=True, timeout=3, check=True)
    data = json.loads(completed.stdout)
    assert data["provider"] == str(provider / "hermes_cli/main.py")
    assert data["argv"] == ["--profile=tides", "chat", "--cli", "--query=Fixture question"]
    assert not marker.exists()
