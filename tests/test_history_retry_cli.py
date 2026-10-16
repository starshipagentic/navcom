"""Explicit bounded historical retries share the CLI/API service contract."""
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

import pytest

import navcom_history_cli as cli
import navcom_system_history as system
from navcom_web import WebApp


def test_system_retry_parser_omits_budgets_and_preserves_explicit_values():
    parsed = cli.parser().parse_args(["system", "--cursor", "a" * 64 + ":0", "--retry-larger"])
    assert parsed.retry_larger is True
    assert parsed.max_files is None and parsed.max_bytes is None and parsed.max_file_bytes is None
    explicit = cli.parser().parse_args(["system", "--max-files", "17", "--max-bytes", "8192", "--max-file-bytes", "4096"])
    assert (explicit.max_files, explicit.max_bytes, explicit.max_file_bytes) == (17, 8192, 4096)
    assert explicit.retry_larger is False


def test_cli_retry_requires_cursor_and_help_explains_resource_and_pin_limits(navcom, capsys):
    with pytest.raises(SystemExit) as error:
        cli.run(navcom, ["system", "Coastal tools", "--at", "2025-04-01", "--retry-larger"])
    assert error.value.code == 2
    assert "--retry-larger requires --cursor" in capsys.readouterr().err
    with pytest.raises(SystemExit) as done:
        cli.run(navcom, ["system", "--help"])
    assert done.value.code == 0
    help_text = " ".join(capsys.readouterr().out.split())
    for text in ("--retry-larger", "snapshot-size failure", "10000 files/64 MiB", "same pinned HEADs/date", "original view", "local cache", "inherit the cursor's budget"):
        assert text in help_text


def test_cli_forwards_retry_without_a_new_place_or_budget(navcom, tmp_path, monkeypatch, capsys):
    calls = []
    def view(*args, **kwargs):
        calls.append((args, kwargs))
        return {"forwarded": True}
    monkeypatch.setattr(system, "view", view)
    cursor = "a" * 64 + ":2"
    assert cli.run(navcom, ["system", "--cursor", cursor, "--retry-larger", "--index", str(tmp_path / "index.sqlite"), "--json"]) == 0
    assert calls[0][0] == ("", "")
    forwarded = calls[0][1]
    assert forwarded["cursor"] == cursor and forwarded["retry_larger"] is True
    assert forwarded["max_files"] is None and forwarded["max_bytes"] is None and forwarded["max_file_bytes"] is None
    output = capsys.readouterr()
    assert json.loads(output.out) == {"forwarded": True}
    assert "same pinned repository heads" in output.err


@pytest.mark.parametrize("body", [
    {"retry_larger": True}, {"retry_larger": True, "cursor": ""},
    {"retry_larger": "true", "cursor": "a" * 64 + ":0"},
    {"retry_larger": 1, "cursor": "a" * 64 + ":0"},
    {"retry_larger": None, "cursor": "a" * 64 + ":0"},
    {"cursor": ["a" * 64 + ":0"]}, {"cursor": 1},
])
def test_api_rejects_unpinned_or_nonboolean_retry_before_service(navcom, tmp_path, monkeypatch, body):
    def forbidden(*args, **kwargs):
        pytest.fail("Invalid retry reached the historical service")
    monkeypatch.setattr(system, "view", forbidden)
    with pytest.raises(ValueError):
        WebApp(navcom, tmp_path / "index.sqlite").post(None, "/api/history/system", body)


def test_api_preserves_server_caches_and_inherits_pinned_snapshot_budgets(navcom, tmp_path, monkeypatch):
    configured = {"NAVCOM_SPACE_CACHE": tmp_path / "space.json", "NAVCOM_SOURCES_CACHE": tmp_path / "sources", "NAVCOM_HISTORY_CACHE": tmp_path / "history"}
    for name, path in configured.items():
        monkeypatch.setenv(name, str(path))
    calls = []
    def view(*args, **kwargs):
        calls.append((args, kwargs))
        return {"forwarded": True}
    monkeypatch.setattr(system, "view", view)
    app = WebApp(navcom, tmp_path / "index.sqlite")
    body = dict(cursor="a" * 64 + ":1", retry_larger=True, q="login", limit=2,
                cache_path="/wrong", space_cache="/wrong", source_cache="/wrong", seconds=120,
                max_files=999999, max_bytes=9999999999, max_file_bytes=9999999999)
    assert app.post(None, "/api/history/system", body) == {"forwarded": True}
    args, options = calls[-1]
    assert args == ("", "") and options["retry_larger"] is True and options["cursor"] == body["cursor"]
    assert options["space_cache"] == configured["NAVCOM_SPACE_CACHE"]
    assert options["source_cache"] == configured["NAVCOM_SOURCES_CACHE"]
    assert options["cache_path"] == configured["NAVCOM_HISTORY_CACHE"]
    assert options["query"] == "login" and options["seconds"] == 30 and options["limit"] == 2
    assert not {"max_files", "max_bytes", "max_file_bytes"} & options.keys()
    app.post(None, "/api/history/system", {"cursor": body["cursor"]})
    assert calls[-1][1]["retry_larger"] is False


def test_plain_retry_output_is_explicit_and_copyable(capsys):
    command = "navcom history system --cursor " + "a" * 64 + ":0 --retry-larger"
    cli.render(dict(action="system", center={"label": "Coastal tools"}, as_of="2025-04-01T00:00:00Z",
                    derived_from_session_id="b" * 64, retry_larger_command=command))
    output = capsys.readouterr().out
    assert "original view retained" in output and command in output
    assert "larger bounded local cache" in output and "pinned HEADs and date" in output


@pytest.mark.skipif(not shutil.which("starforge"), reason="Optional native Starforge required")
def test_public_cli_and_api_retry_keep_original_heads_date_and_view(navcom, tmp_path, monkeypatch):
    repo = tmp_path / "quartz"
    repo.mkdir()
    def git(*arguments, date="2025-01-02T00:00:00Z"):
        env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1",
                   GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date)
        return subprocess.run(["git", "-C", str(repo), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                               "-c", "commit.gpgsign=false", "-c", "core.hooksPath=" + os.devnull, *arguments],
                              env=env, capture_output=True, text=True, check=True).stdout.strip()
    git("init", "-q", "-b", "main")
    (repo / "README.md").write_text("# Quartz classic\n\nPassword login evidence.\n")
    (repo / "package.json").write_text(json.dumps(dict(name="quartz-classic", description="Password login service")))
    (repo / "login.py").write_text('"""Password login evidence."""\ndef password_login(value):\n' +
                                  ''.join(f'    phase_{i} = value + {i}\n' for i in range(22)) + '    return phase_21\n')
    git("add", "."); git("commit", "-qm", "Original login")
    original_head = git("rev-parse", "HEAD")
    space = tmp_path / "space.json"
    cache = tmp_path / "history"
    sources = tmp_path / "sources"
    index = tmp_path / "index.sqlite"
    nodes = [dict(id="galaxy:owner", kind="galaxy", label="Fixture galaxy", parent_id=None, position=dict(x=0, y=0), locations=[], evidence=[]),
             dict(id="system:coast", kind="system", label="Coastal tools", parent_id="galaxy:owner", position=dict(x=100, y=100), locations=[], evidence=[]),
             dict(id="planet:quartz", kind="planet", label="Quartz now", parent_id="system:coast", position=dict(x=200, y=200), locations=[dict(path=str(repo))], evidence=[])]
    space.write_text(json.dumps(dict(schema_version=1, published=123, entities=nodes, edges=[], coverage={})))
    for name, path in {"NAVCOM_SPACE_CACHE": space, "NAVCOM_SOURCES_CACHE": sources, "NAVCOM_HISTORY_CACHE": cache}.items():
        monkeypatch.setenv(name, str(path))
    entry = Path(cli.__file__).with_name("navcom.py")
    def invoke(arguments, *, expect=0):
        result = subprocess.run([sys.executable, str(entry), *map(str, arguments)], capture_output=True, text=True, timeout=60)
        assert result.returncode == expect, result.stderr
        return result
    initial = json.loads(invoke(["history", "system", "system:coast", "--at", "2025-12-01", "--query", "Password",
                                 "--max-files", "1", "--index", index, "--json"]).stdout)
    assert initial["retry_larger_available"] and initial["retry_larger_command"]
    original_plan = cache / "systems" / initial["session_id"] / "plan.json"
    original_bytes = original_plan.read_bytes()
    (repo / "README.md").write_text("# Quartz future\n\nFUTURE_CONTENT Cognito\n")
    git("add", "."); git("commit", "-qm", "Later before cutoff", date="2025-10-01T00:00:00Z")
    assert git("rev-parse", "HEAD") != original_head
    (repo / "login.py").write_text("DIRTY_CURRENT_CONTENT\n")
    retry_argv = shlex.split(initial["retry_larger_command"])[1:]
    retried = json.loads(invoke([*retry_argv, "--json"]).stdout)
    assert retried["session_id"] != initial["session_id"]
    assert retried["derived_from_session_id"] == initial["session_id"]
    assert retried["as_of"] == initial["as_of"]
    node = next(n for n in retried["nodes"] if n["id"] == "planet:quartz")
    assert node["commit"] == original_head and node["historical_state"] == "committed"
    assert node["label"] == "quartz-classic" and node["position"] == nodes[2]["position"]
    assert "FUTURE_CONTENT" not in json.dumps(retried) and "DIRTY_CURRENT_CONTENT" not in json.dumps(retried)
    result = next(r["data"] for r in retried["repositories"] if r.get("data"))
    assert result["evidence"]["concept_hits"] and result["evidence"]["text_hits"]
    assert original_plan.read_bytes() == original_bytes

    # Omitted budget flags inherit the derived cursor; no new HEAD is pinned.
    replay_process = invoke(["history", "system", "--cursor", retried["cursor"], "--query", "Password",
                             "--index", index, "--json"])
    replay = json.loads(replay_process.stdout)
    assert replay["session_id"] == retried["session_id"]
    assert "Reading dated repository" not in replay_process.stderr
    assert next(r["data"] for r in replay["repositories"] if r.get("data"))["snapshot"] == result["snapshot"]
    app = WebApp(navcom, index)
    api_retry = app.post(None, "/api/history/system", dict(cursor=initial["cursor"], q="Password", retry_larger=True))
    assert api_retry["session_id"] == retried["session_id"] and api_retry["as_of"] == initial["as_of"]
    api_replay = app.post(None, "/api/history/system", dict(cursor=retried["cursor"], q="Password"))
    assert next(n for n in api_replay["nodes"] if n["id"] == "planet:quartz")["commit"] == original_head
    assert original_plan.read_bytes() == original_bytes

    changed = invoke(["history", "system", "--cursor", retried["cursor"], "--max-files", "2", "--index", index, "--json"], expect=2)
    assert "same snapshot" in changed.stderr
    old_replay = json.loads(invoke([*shlex.split(initial["cli_command"])[1:], "--json"]).stdout)
    assert old_replay["session_id"] == initial["session_id"]
    assert next(n for n in old_replay["nodes"] if n["id"] == "planet:quartz")["historical_state"] == "unknown"
