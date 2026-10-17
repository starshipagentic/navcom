"""The cockpit's read-only routes return what the matching CLI command prints.

Each route here is validation plus one service call (docs/architecture.md); the
tests run the CLI in a throwaway HOME and the adapter in-process on the same index.
"""
import json
import os
from pathlib import Path
import sqlite3
import stat
import subprocess
import sys
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import fake_home
import pytest

import navcom_sources
import navcom_web

ROOT = Path(__file__).resolve().parent.parent
NAVCOM = str(ROOT / "navcom.py")
REF = "eeeeeeeeeeee"  # the throwaway HOME's Codex session


def build(home):
    """One session per harness under `home`, indexed by the real CLI."""
    sessions, workdir = fake_home.build(home)
    env = fake_home.env_for(home)
    subprocess.run([sys.executable, NAVCOM, "--maintain"], env=env, cwd=workdir, check=True,
                   capture_output=True, timeout=120)
    with sqlite3.connect(env["NAVCOM_INDEX"]) as conn:
        key = next(f for (f,) in conn.execute("SELECT file FROM file_state") if f.endswith(REF + ".jsonl"))
    return dict(env=env, workdir=workdir, index=Path(env["NAVCOM_INDEX"]), key=key, sessions=sessions)


@pytest.fixture(scope="module")
def indexed(tmp_path_factory):
    return build(tmp_path_factory.mktemp("routes") / "home")


@pytest.fixture
def app(navcom, indexed, monkeypatch):
    """The adapter on the throwaway index, with this process's environment matching the CLI's."""
    for name in set(os.environ) - set(indexed["env"]):
        monkeypatch.delenv(name)
    for name, value in indexed["env"].items():
        monkeypatch.setenv(name, value)
    web = navcom_web.WebApp(navcom, indexed["index"])
    conn = web.connect()
    yield web, conn
    conn.close()


def cli(indexed, *args, env=None):
    proc = subprocess.run([sys.executable, NAVCOM, *args], env=env or indexed["env"], cwd=indexed["workdir"],
                          stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120)
    assert "Traceback" not in proc.stderr, proc.stderr
    return proc


# ── GET /api/recap = navcom --recap REF ─────────────────────────────────────────

def test_recap_route_returns_the_cli_recap(app, indexed):
    web, conn = app
    for extra, params in (([], {}), (["--max-chars", "400"], {"max_chars": ["400"]})):
        printed = cli(indexed, "--recap", REF, *extra)
        assert printed.returncode == 0, printed.stderr
        result = web.get(conn, "/api/recap", dict(key=[indexed["key"]], **params))
        assert result["key"] == indexed["key"]
        assert result["recap"] + "\n" == printed.stdout
    assert "navcom --recap" in result["recap"]
    for bad in (dict(key=["/etc/passwd"]), dict(key=[indexed["key"]], max_chars=["-1"])):
        with pytest.raises(ValueError):
            web.get(conn, "/api/recap", bad)


# ── GET /api/session/search = navcom WORDS --file REF ──────────────────────────

def test_session_search_route_returns_what_file_ref_json_prints(app, indexed, navcom):
    web, conn = app
    raw, _, _ = navcom.search_hits(conn, "zebracornaider")
    aider = raw[0].file  # the Aider chat whose matching turns span several lines
    assert ".aider.chat.history.md#" in aider and any("\n" in hit.snip for hit in raw)
    for key, ref, words in ((indexed["key"], REF, "cognito"), (indexed["key"], REF, "zebracorn"),
                            (aider, aider, "zebracornaider"), (indexed["key"], REF, "nothingmatchesthis")):
        printed = json.loads(cli(indexed, words, "--file", ref, "--json").stdout)
        result = web.get(conn, "/api/session/search", dict(key=[key], q=[words]))
        assert result == printed  # same sessions, hit order and whitespace-collapsed snippets
        assert [s["key"] for s in printed["sessions"]] == ([key] if words != "nothingmatchesthis" else [])
    snippets = [h["snippet"] for s in web.get(conn, "/api/session/search", dict(key=[aider], q=["zebracornaider"]))["sessions"]
                for h in s["hits"]]
    assert snippets and all("zebracornaider" in s and "\n" not in s for s in snippets)
    for bad in (dict(key=[indexed["key"]], q=[" "]), dict(key=[indexed["key"]], q=["x"], limit=["0"]),
                dict(key=["missing"], q=["cognito"])):
        with pytest.raises(ValueError):
            web.get(conn, "/api/session/search", bad)


# ── GET /api/plan and POST /api/launch = navcom --resume REF[:TURN] [--with H] ──

def test_plan_route_focuses_a_turn_like_resume_ref_turn(app, indexed):
    web, conn = app
    for turn, ref in (("2", REF + ":2"), ("", REF)):
        printed = cli(indexed, "--resume", ref, "--with", "claude", "--print")
        assert printed.returncode == 0, printed.stderr
        plan = web.get(conn, "/api/plan", dict(key=[indexed["key"]], harness=["claude"], turn=[turn]))
        assert plan["line"] + "\n" == printed.stdout
    assert f"navcom --open {REF}:2" in web.get(conn, "/api/plan", dict(key=[indexed["key"]], harness=["claude"], turn=["2"]))["line"]
    assert f"navcom --open {REF}:2" not in plan["line"]
    original = cli(indexed, "--resume", REF, "--print")
    assert web.get(conn, "/api/plan", dict(key=[indexed["key"]]))["line"] + "\n" == original.stdout
    for turn in ("x", "0", "-3"):
        with pytest.raises(ValueError, match="Turn"):
            web.get(conn, "/api/plan", dict(key=[indexed["key"]], harness=["claude"], turn=[turn]))
    with pytest.raises(ValueError, match="Unknown harness"):
        web.get(conn, "/api/plan", dict(key=[indexed["key"]], harness=["sh; echo bad"]))


def test_launch_route_starts_the_focused_plan_after_the_shared_preflight(app, indexed, navcom, monkeypatch):
    web, conn = app
    launched, checked = [], []
    monkeypatch.setattr(navcom, "resume_in_new_tab", lambda plan: (launched.append(plan) or True, "opened"))
    real = navcom.prepare_launch
    monkeypatch.setattr(navcom, "prepare_launch", lambda db, plan: checked.append(plan) or real(db, plan))
    monkeypatch.setattr(navcom.shutil, "which", lambda exe: "/usr/bin/" + exe)
    result = web.post(conn, "/api/launch", dict(key=indexed["key"], harness="claude", turn=2))
    focused = web.get(conn, "/api/plan", dict(key=[indexed["key"]], harness=["claude"], turn=["2"]))
    assert result == dict(ok=True, message="opened", command=focused["line"])
    assert launched == checked == [focused]
    monkeypatch.setattr(navcom.shutil, "which", lambda exe: None)
    with pytest.raises(ValueError, match="codex isn't installed here"):
        web.post(conn, "/api/launch", dict(key=indexed["key"]))
    with pytest.raises(ValueError, match="Turn"):
        web.post(conn, "/api/launch", dict(key=indexed["key"], harness="claude", turn=True))
    assert len(launched) == 1


STUB_TAB = r"""
import sys
sys.path.insert(0, sys.argv[1])
import navcom
navcom.resume_in_new_tab = lambda plan: (True, "opened (test)")  # never a real terminal tab
sys.exit(navcom.run(sys.argv[2:]))
"""


def test_cli_tab_uses_the_same_preflight_messages(tmp_path):
    home = build(tmp_path / "home")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    env = dict(home["env"], PATH=f"{bin_dir}:/usr/bin:/bin")

    def tab(ref):
        return subprocess.run([sys.executable, "-c", STUB_TAB, str(ROOT), "--resume", ref, "--tab"], env=env,
                              cwd=home["workdir"], stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120)

    missing = tab(REF)
    assert missing.returncode == 1 and missing.stderr == "navcom: codex isn't installed here\n" and missing.stdout == ""
    for name in ("codex", "claude"):
        exe = bin_dir / name
        exe.write_text("#!/bin/sh\n")
        exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    opened = tab(REF)
    assert opened.returncode == 0 and opened.stdout.startswith("✓ opened (test)\n  cd ") and "codex resume" in opened.stdout
    Path(home["sessions"]["claude"]).unlink()  # Claude deleted it; navcom archived it during --maintain
    restored = tab("11111111")
    assert restored.returncode == 0, restored.stderr
    assert "claude had deleted this session — restored it from navcom's archive" in restored.stderr
    assert Path(home["sessions"]["claude"]).exists()


# ── GET /api/history = navcom history timeline PLACE --repo R --include P ──────

def test_history_route_forwards_repo_and_include_like_the_cli(app, indexed, navcom, monkeypatch, capsys):
    import navcom_history
    import navcom_history_cli
    web, conn = app
    calls = []
    monkeypatch.setattr(navcom_history, "view", lambda *args, **kwargs: calls.append((args, kwargs)) or {"ok": True})
    web.get(conn, "/api/history", dict(within=["planet:x"], repo=["/tmp/copy"], include=["src", "docs"], limit=["7"]))
    assert navcom_history_cli.run(navcom, ["timeline", "planet:x", "--repo", "/tmp/copy", "--include", "src",
                                           "--include", "docs", "--limit", "7", "--index", str(indexed["index"]), "--json"]) == 0
    capsys.readouterr()
    assert calls[0][0][0] == calls[1][0][0] == "planet:x" and calls[0][1] == calls[1][1]
    assert calls[0][1]["repo"] == Path("/tmp/copy") and calls[0][1]["include"] == ["src", "docs"]
    web.get(conn, "/api/history", dict(within=["planet:x"]))
    assert calls[-1][1]["repo"] is None and calls[-1][1]["include"] is None



def test_history_explore_route_forwards_the_chosen_git_copy_like_the_cli(app, indexed, navcom, monkeypatch, capsys):
    import navcom_history
    import navcom_history_cli
    web, conn = app
    calls = []
    monkeypatch.setattr(navcom_history, "view", lambda *args, **kwargs: calls.append((args, kwargs)) or {"ok": True})
    web.post(conn, "/api/history/explore", dict(within="planet:x", revision="abc123", repo="/tmp/copy", q="login", limit=7))
    assert navcom_history_cli.run(navcom, ["explore", "planet:x", "abc123", "--repo", "/tmp/copy", "--query", "login",
                                           "--limit", "7", "--index", str(indexed["index"]), "--json"]) == 0
    capsys.readouterr()
    assert calls[0][0] == calls[1][0] == ("planet:x", "abc123")
    assert calls[0][1]["repo"] == calls[1][1]["repo"] == Path("/tmp/copy")
    assert calls[0][1]["query"] == calls[1][1]["query"] == "login" and calls[0][1]["limit"] == calls[1][1]["limit"] == 7
    web.post(conn, "/api/history/explore", dict(within="planet:x", revision="abc123"))
    assert calls[-1][1]["repo"] is None
    with pytest.raises(ValueError):
        web.post(conn, "/api/history/explore", dict(within="planet:x", revision="abc123", repo=7))

# ── GET /api/sources, /api/sources/search, /api/source = navcom sources … ──────

WORKER = r"""
import json, sys
request = json.load(sys.stdin)
if request["query"] == "fail":
    print("navcom sources ▸ searching", file=sys.stderr)
    print("navcom sources: Unknown source: nowhere", file=sys.stderr)
    sys.exit(1)
print(json.dumps(dict(schema_version=1, request=request, concept_hits=[], text_hits=[], freshness="Fresh.",
                      potentially_truncated=False, query_cache_hit=False)))
"""


@pytest.fixture
def sources(app, tmp_path, monkeypatch):
    real = tmp_path / "real-sources"
    real.mkdir()
    (real / "current.json").write_text(json.dumps(dict(published=1234, sources=[dict(
        id="fixture", root="/tmp/fixture", include=["."], coverage=dict(files=2, excluded=[]))])))
    link = tmp_path / "linked-sources"
    link.symlink_to(real)
    monkeypatch.setenv("NAVCOM_SOURCES_CACHE", str(link))  # the CLI resolves its cache; so does the route
    worker = tmp_path / "worker.py"
    worker.write_text(WORKER)
    monkeypatch.setattr(navcom_sources, "worker_argv", lambda: [sys.executable, str(worker)])
    return real.resolve()


def cli_json(navcom, capsys, argv):
    assert navcom_sources.run(navcom, argv + ["--json"]) == 0
    return json.loads(capsys.readouterr().out)


def test_sources_list_route_returns_sources_list(app, sources, navcom, capsys):
    web, conn = app
    listed = web.get(conn, "/api/sources", {})
    assert listed == cli_json(navcom, capsys, ["list"])
    assert listed["sources"][0]["id"] == "fixture" and listed["published"] == 1234


def test_sources_search_route_runs_the_same_search(app, sources, navcom, capfd):
    web, conn = app
    found = web.get(conn, "/api/sources/search", dict(q=["login flow"], within=["fixture"], path=["src", "docs"], ext=["ts"]))
    assert found == cli_json(navcom, capfd, ["search", "login", "flow", "--within", "fixture", "--path", "src",
                                              "--path", "docs", "--ext", "ts"])
    assert found["request"] == dict(action="search", cache=str(sources), paths=["src", "docs"], query="login flow",
                                    within="fixture", mode="both", regex=False, ext="ts", limit=20)
    with pytest.raises(navcom_sources.WorkerError, match="^Unknown source: nowhere$"):
        web.get(conn, "/api/sources/search", dict(q=["fail"]))
    assert navcom_sources.run(navcom, ["search", "fail"]) == 1  # the CLI streams the worker's own words
    assert capfd.readouterr().err == ("navcom sources ▸ starting Starforge search\n"
                                       "navcom sources ▸ searching\nnavcom sources: Unknown source: nowhere\n")
    for bad, message in ((dict(q=[""]), "words"), (dict(q=["x"], mode=["fuzzy"]), "mode"),
                         (dict(q=["x"], mode=["concept"], regex=["1"]), "text path"), (dict(q=["x"], limit=["500"]), "limit")):
        with pytest.raises(ValueError, match=message):
            web.get(conn, "/api/sources/search", bad)


def test_source_route_reads_from_the_resolved_cache_like_sources_read(app, sources, navcom, monkeypatch, capsys):
    import navcom_source_reader
    web, conn = app
    calls = []
    monkeypatch.setattr(navcom_source_reader, "read_source",
                        lambda *args, **kwargs: calls.append((args, kwargs)) or dict(lines=[], source_path="README.md"))
    web.get(conn, "/api/source", dict(source=["fixture"], path=["README.md"]))
    cli_json(navcom, capsys, ["read", "fixture", "README.md", "--index", str(web.index_path)])
    assert calls[0] == calls[1]
    assert calls[0][1]["cache_path"] == sources


# ── the new routes are as private as the old ones ──────────────────────────────

def test_new_routes_need_the_local_session(navcom, indexed):
    server = navcom_web.make_server(navcom, indexed["index"])
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        for route in ("/api/recap?key=x", "/api/session/search?key=x&q=y", "/api/sources", "/api/sources/search?q=y",
                      "/api/plan?key=x&turn=2"):
            for headers in ({}, {"X-Navcom-Token": server.app.token, "Host": "evil.example"}):
                with pytest.raises(HTTPError) as caught:
                    urlopen(Request(f"http://127.0.0.1:{server.server_port}{route}", headers=headers), timeout=5)
                assert caught.value.code == 403
    finally:
        server.shutdown()
        server.server_close()
        worker.join()
