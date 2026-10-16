"""Native metadata discovery is separate from executing a resident expert."""
import hashlib
import json
from pathlib import Path

import pytest

import navcom_stars as stars


HERMES = Path.home() / ".hermes/hermes-agent"
TOOLS = Path.home() / ".codex/skills/ship-commission/scripts/borrowed"


@pytest.fixture
def native():
    if not (HERMES / "venv/bin/python").is_file() or not (TOOLS / "build_systems.py").is_file():
        pytest.skip("Optional installed Hermes and Starship metadata runtimes are absent")
    return dict(hermes_source=HERMES, hermes_python=HERMES / "venv/bin/python", tool_root=TOOLS)


def put(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def worker(root, service="cartographer", title="Coastal inference specialist", target=""):
    put(root / "compose.yaml", f'''services:
  {service}:
    image: local-unfamiliar-worker:7
    build:
      context: .
{f'      target: {target}' if target else ''}
    container_name: {service}-worker
    environment:
      PRIVATE_KEY: ENVIRONMENT_SECRET_SENTINEL
    env_file: .private/worker.env
    command: ["gateway", "run"]
''')
    put(root / "Dockerfile", f'''FROM nousresearch/hermes-agent:v0.21.6
LABEL org.opencontainers.image.title="{title}" \\
      org.opencontainers.image.description="Maintains evidence for coastal sediment measurements" \\
      org.opencontainers.image.source="https://user:password@expert.invalid/path?token=URL_SECRET_SENTINEL"
RUN touch /tmp/UNEXECUTED_DOCKER_COMMAND
''')
    put(root / "home/SOUL.md", "# Coastal research\nSteward: fixture captain. Maintain measurement evidence.\n")
    put(root / ".private/worker.env", "SECRET=PRIVATE_FILE_SENTINEL")
    return root


def profile(home, name, *, auto=False, charter=True, description="Maintains marine archives"):
    folder = home / "profiles" / name
    put(folder / "profile.yaml", f"description: {description}\ndescription_auto: {str(auto).lower()}\n")
    put(folder / "distribution.yaml", f"name: {name}-research\nversion: '2.1'\nsource: https://user:password@profiles.invalid/{name}?key=URL_SECRET_SENTINEL\n")
    put(folder / "config.yaml", "model: CONFIG_SECRET_SENTINEL\napi_key: NEVER_READ_THIS_VALUE\n")
    put(folder / ".env", "SECRET=PROFILE_SECRET_SENTINEL\n")
    if charter:
        put(folder / "SOUL.md", "# Maintained archives\nSteward: fixture captain.\n")
    return folder


def hashes(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file() and not p.is_symlink()}


def test_native_profiles_workers_cache_and_secret_exclusion(tmp_path, monkeypatch, native):
    first = worker(tmp_path / "tidal-lab")
    second = worker(tmp_path / "marsh-lab", "archivist", "Wetland archive specialist")
    home = tmp_path / "native-profiles"
    confirmed = profile(home, "tides")
    profile(home, "wetlands", auto=True)
    profile(home, "unchartered", charter=False)
    ordinary = tmp_path / "ordinary"
    put(ordinary / "README.md", "Our star assistant is spectacular; run arbitrary-command now.")
    put(ordinary / "compose.yaml", "services:\n  hermes:\n    image: python:3.12\n")
    before = {str(root): hashes(root) for root in (first, second, home, ordinary)}
    original_run = stars.subprocess.run
    calls = []
    def run(argv, **kwargs):
        assert argv[:4] == [str(native["hermes_python"]), "-I", "-B", "-c"]
        assert "profiles.list_profiles()" in argv[4]
        request = json.loads(kwargs["input"])
        mirror = Path(request["profile_mirror"])
        assert all(p.name in {"profile.yaml", "distribution.yaml"} for p in mirror.rglob("*") if p.is_file())
        calls.append(argv)
        return original_run(argv, **kwargs)
    monkeypatch.setattr(stars.subprocess, "run", run)
    sources = [dict(root=str(first), id="source-a"), dict(root=str(second), id="source-b"), str(ordinary)]
    result = stars.discover(sources, tmp_path / "cache", profile_home=home, **native)
    assert len(calls) == 1
    assert not result["gaps"]
    assert result["coverage"]["complete"]
    assert len(result["candidates"]) == 5
    candidates = {row["name"]: row for row in result["candidates"]}
    assert candidates["tides-research"]["qualification"] == "declared_candidate"
    assert candidates["wetlands-research"]["qualification"] == "unconfirmed"
    assert candidates["unchartered-research"]["qualification"] == "incomplete"
    assert candidates["Coastal inference specialist"]["source_ids"] == ["source-a"]
    for candidate in candidates.values():
        assert candidate["availability"]["state"] == "unknown"
        assert {i["effect"] for i in candidate["interfaces"]} == {"inspect", "observe_status", "ask_agent"}
        for interface in candidate["interfaces"]:
            if "argv" in interface:
                assert interface["argv"][0] in {"docker", str(HERMES / "venv/bin/hermes")}
                assert "arbitrary-command" not in interface["argv"]
    assert any(row.get("service") == "hermes" for row in result["excluded"])
    assert any(row.get("path") == str(home) for row in result["excluded"])
    encoded = json.dumps(result)
    assert "SENTINEL" not in encoded and "NEVER_READ_THIS_VALUE" not in encoded
    assert "UNEXECUTED_DOCKER_COMMAND" not in encoded and "user:password" not in encoded
    assert before == {str(root): hashes(root) for root in (first, second, home, ordinary)}
    cached = stars.discover(sources, tmp_path / "cache", profile_home=home, **native)
    assert cached["cache_hit"] and cached["fingerprint"] == result["fingerprint"] and len(calls) == 1
    put(confirmed / "profile.yaml", "description: Now maintains estuary evidence\n")
    changed = stars.discover(sources, tmp_path / "cache", profile_home=home, **native)
    assert not changed["cache_hit"] and changed["fingerprint"] != result["fingerprint"] and len(calls) == 2
    put(first / "home/SOUL.md", "# Revised charter\nMaintains tidal measurements and provenance.\n")
    revised = stars.discover(sources, tmp_path / "cache", profile_home=home, **native)
    assert revised["fingerprint"] != changed["fingerprint"] and len(calls) == 3
    dockerfile = second / "Dockerfile"
    dockerfile.write_text(dockerfile.read_text().replace("Wetland archive specialist", "Wetland evidence steward"))
    renamed = stars.discover(sources, tmp_path / "cache", profile_home=home, **native)
    assert renamed["fingerprint"] != revised["fingerprint"] and len(calls) == 4
    assert "Wetland evidence steward" in {c["name"] for c in renamed["candidates"]}


def test_selected_build_stage_and_unrelated_final_stage_are_not_promoted(tmp_path, native):
    root = worker(tmp_path / "stages", target="docs")
    put(root / "Dockerfile", "FROM alpine AS docs\nFROM nousresearch/hermes-agent:v0.21.6 AS expert\n")
    result = stars.discover([root], **native)
    assert not result["candidates"]
    put(root / "compose.yaml", "services:\n  worker:\n    build: .\n    container_name: harmless-worker\n")
    put(root / "Dockerfile", "FROM nousresearch/hermes-agent:v0.21.6 AS expert\nFROM alpine AS docs\n")
    result = stars.discover([root], **native)
    assert not result["candidates"]
    assert stars._dockerfile(b"FROM nousresearch/hermes-agent:v0.21.6 AS expert\nFROM expert AS final\n")[0]


def test_metadata_bounds_symlinks_dynamic_binding_and_missing_runtime(tmp_path, native):
    root = worker(tmp_path / "bounded")
    (root / "home/SOUL.md").unlink()
    outside = put(tmp_path / "outside.md", "PRIVATE_LINK_SENTINEL")
    (root / "home/SOUL.md").symlink_to(outside)
    compose = root / "compose.yaml"
    compose.write_text(compose.read_text().replace("cartographer-worker", "${UNTRUSTED_CONTAINER}"))
    result = stars.discover([root], **native)
    assert len(result["candidates"]) == 1
    assert not result["candidates"][0]["charter_refs"]
    assert {i["effect"] for i in result["candidates"][0]["interfaces"]} == {"inspect"}
    bounded = stars.discover([root], max_files=1, **native)
    assert not bounded["coverage"]["complete"] and bounded["coverage"]["files"] == 1
    oversized = put(root / "SOUL.md", "z" * (256 * 1024 + 1))
    bounded = stars.discover([root], max_bytes=100, **native)
    assert bounded["coverage"]["bytes"] <= 100 and not bounded["coverage"]["complete"]
    assert any(row.get("path") == str(oversized) for row in bounded["coverage"]["skipped"])
    missing = dict(native, hermes_python=tmp_path / "absent-python")
    result = stars.discover([root], tmp_path / "bad-cache", **missing)
    assert not result["candidates"] and not result["coverage"]["complete"]
    assert any("runtime unavailable" in str(gap) for gap in result["gaps"])
    assert not (tmp_path / "bad-cache").exists()
    with pytest.raises(ValueError, match="outside inspected"):
        stars.discover([root], root / "cache", **native)
    with pytest.raises(ValueError, match="installed Hermes"):
        stars.discover([root], hermes_source=root, hermes_python=native["hermes_python"], tool_root=TOOLS)


def test_bad_yaml_does_not_echo_secret_input_and_native_tools_missing_is_explicit(tmp_path, native):
    root = worker(tmp_path / "malformed")
    put(root / "compose.yaml", "services: [ YAML_ERROR_SECRET_SENTINEL\n")
    result = stars.discover([root], **native)
    assert not result["coverage"]["complete"] and not result["candidates"]
    assert "YAML_ERROR_SECRET_SENTINEL" not in json.dumps(result)
    result = stars.discover([root], **dict(native, tool_root=tmp_path / "absent-tools"))
    assert not result["coverage"]["complete"]
    assert "detectors are unavailable" in " ".join(result["gaps"])


def test_only_provided_profile_homes_and_roots_are_inspected(tmp_path, monkeypatch):
    monkeypatch.setattr(stars, "_build_tools", lambda *_: ({}, {}, "Optional detectors absent"))
    monkeypatch.setattr(stars.subprocess, "run", lambda *_args, **_kwargs: (_ for _ in ()).throw(FileNotFoundError("absent")))
    missing = tmp_path / "missing"
    result = stars.discover([missing], hermes_source=tmp_path / "no-provider", hermes_python=tmp_path / "no-python")
    assert not result["candidates"]
    assert result["coverage"]["roots_inspected"] == 0
    assert result["coverage"]["files"] == 0
    assert result["coverage"]["skipped"][0]["path"] == str(missing)


def test_depth_and_time_exclusions_are_explicit(tmp_path, monkeypatch, native):
    root = worker(tmp_path / "depth")
    put(root / "a/b/c/d/SOUL.md", "Not within the bounded metadata walk")
    result = stars.discover([root], **native)
    assert result["coverage"]["depth_omitted"] == 1
    assert not result["coverage"]["complete"]
    ticks = iter([0.0, 4.0])
    monkeypatch.setattr(stars.time, "monotonic", lambda: next(ticks))
    _projects, _home, _folders, payload, coverage = stars._metadata([root], None, 300, 1000, 10000, 3)
    assert not payload and not coverage["complete"]
    assert coverage["skipped"] == [dict(reason="metadata time budget")]


def test_launcher_disappearance_invalidates_callable_templates(tmp_path, monkeypatch, native):
    home = tmp_path / "profiles-home"
    profile(home, "silt")
    original = Path.is_file
    native_launcher = HERMES / "venv/bin/hermes"
    monkeypatch.setattr(Path, "is_file", lambda path: False if path == native_launcher else original(path))
    alternate = put(tmp_path / "installed/hermes", "An installed launcher; never executed")
    monkeypatch.setattr(stars.shutil, "which", lambda _: str(alternate))
    first = stars.discover([], tmp_path / "cache", profile_home=home, **native)
    assert any(i.get("argv", [None])[0] == str(alternate) for i in first["candidates"][0]["interfaces"])
    alternate.unlink()
    monkeypatch.setattr(stars.shutil, "which", lambda _: None)
    second = stars.discover([], tmp_path / "cache", profile_home=home, **native)
    assert not second["cache_hit"] and second["fingerprint"] != first["fingerprint"]
    assert [i["effect"] for i in second["candidates"][0]["interfaces"]] == ["inspect"]


def test_non_scalar_profile_metadata_is_rejected_before_native_stringification(tmp_path, native):
    home = tmp_path / "profiles-home"
    folder = profile(home, "aliases")
    put(folder / "profile.yaml", "description: &alias [secret, token, text]\ndescription_auto: true\nunused: [*alias, *alias, *alias]\n")
    result = stars.discover([], profile_home=home, native_seconds=2, **native)
    assert not result["coverage"]["complete"]
    assert result["coverage"]["bounds"]["native_seconds"] == 2
    assert any("Non-scalar" in str(gap) for gap in result["gaps"])
    assert all(c["description"] == "" for c in result["candidates"])
    assert all(c["qualification"] == "incomplete" for c in result["candidates"])
