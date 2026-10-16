"""Native timestamp ingestion, ancestry and CLI historical evidence regressions."""
import json
from pathlib import Path
import shlex
import subprocess
import sys

import pytest

from navcom_atlas import identity


def codex(text, stamp=None, role="user"):
    record = dict(type="response_item", payload=dict(type="message", role=role,
                  content=[dict(type="input_text", text=text)]))
    if stamp is not None:record["timestamp"] = stamp
    return record


def write(path, records):
    path.write_text("\n".join(json.dumps(r) for r in records) + "\n")
    return str(path), path.stat().st_mtime, path.stat().st_size


@pytest.mark.parametrize("provider", ["codex", "claude", "pi", "omo", "gemini"])
def test_native_message_dates_survive_cleaning_and_index(navcom, tmp_path, provider):
    stamp = "2025-04-01T16:30:00-04:00"
    if provider == "codex":
        records = [dict(type="session_meta", payload=dict(id="dated", cwd=str(tmp_path), parent_thread_id="parent")), codex("old login", stamp), codex("unknown date")]
    elif provider == "claude":
        records = [dict(timestamp=stamp, cwd=str(tmp_path), message=dict(role="user", content="old login")),
                   dict(message=dict(role="assistant", content="unknown date"))]
    elif provider in ("pi", "omo"):
        records = [dict(type="session", cwd=str(tmp_path)),
                   dict(type="message", timestamp=stamp, message=dict(role="user", content="old login")),
                   dict(type="message", message=dict(role="assistant", content="unknown date"))]
    else:
        records = [dict(sessionId="dated", directories=[str(tmp_path)]),
                   dict(id="one", type="user", timestamp=stamp, content="old login"),
                   dict(id="two", type="gemini", content="unknown date")]
    path = tmp_path / "dated.jsonl"
    key, modified, size = write(path, records)
    turns = list(navcom.iter_clean_turns(key, provider))
    assert turns == [("user", "old login"), ("assistant", "unknown date")] if provider != "codex" else turns == [("user", "old login"), ("user", "unknown date")]
    assert [t.timestamp for t in turns] == ["2025-04-01T20:30:00Z", ""]
    conn = navcom.open_index(tmp_path / "index.sqlite")
    navcom.index_logs(conn, [(key, modified, size, provider)], progress=False)
    assert conn.execute("SELECT ts FROM session_fts ORDER BY msg_index").fetchall() == [("2025-04-01T20:30:00Z",), ("",)]
    assert conn.execute("SELECT project FROM file_meta WHERE file=?", (key,)).fetchone()[0] == str(tmp_path)
    if provider == "codex":
        assert conn.execute("SELECT parent_id FROM session_ancestry WHERE file=?", (key,)).fetchone()[0] == "parent"
    conn.close()


def test_pi_native_milliseconds_are_explicit_not_generic_epoch_guess(navcom):
    line = json.dumps(dict(type="message", message=dict(role="user", content="login", timestamp=1743539400000)))
    turn = next(navcom.iter_pi_lines([line]))
    assert turn.timestamp == "2025-04-01T20:30:00Z"
    assert navcom._native_timestamp(1743539400000) == ""
    for bad in ("2025-04-01", "2025-04-01T20:30:00", "bad", None, float("nan")):
        assert navcom._native_timestamp(bad) == ""


def test_known_gemini_patches_cannot_keep_original_date(navcom, tmp_path):
    old = dict(id="one", type="user", timestamp="2025-01-01T00:00:00Z", content="old login")
    patched = dict(old, content="future content")
    for records in ([old, {"$patch":dict(id="one", content="future content")}],
                    [old, patched], [old, {"$set":dict(messages=[patched])}],
                    [old, {"$patch":dict(id="one", content="future content")}, {"$set":dict(messages=[patched])}]):
        path = tmp_path / "gemini.jsonl"
        write(path, records)
        turns = list(navcom.iter_clean_turns(str(path), "gemini"))
        assert turns == [("user", "future content")]
        assert turns[0].timestamp == ""


def test_gemini_json_file_native_dates(navcom, tmp_path):
    path = tmp_path / "gemini.json"
    path.write_text(json.dumps(dict(messages=[dict(type="user", timestamp="2025-01-01T00:00:00Z", content="login")],startTime="2000-01-01T00:00:00Z")))
    assert next(navcom.iter_clean_turns(str(path), "gemini")).timestamp == "2025-01-01T00:00:00Z"


def test_incremental_append_keeps_dates_and_ancestry(navcom, tmp_path):
    path = tmp_path / "dated.jsonl"
    spawn = dict(subagent=dict(thread_spawn=dict(parent_thread_id="parent")))
    records = [dict(type="session_meta", payload=dict(id="dated", cwd=str(tmp_path), source=spawn)),
               codex("old login", "2025-01-01T00:00:00Z")]
    key, modified, size = write(path, records)
    conn = navcom.open_index(tmp_path / "index.sqlite")
    navcom.index_logs(conn, [(key, modified, size, "codex")], progress=False)
    old_row = conn.execute("SELECT rowid FROM session_fts").fetchone()[0]
    with path.open("a") as stream:stream.write(json.dumps(codex("new login", "2026-01-01T00:00:00Z")) + "\n")
    navcom.index_logs(conn, [(key, modified+1, path.stat().st_size, "codex")], progress=False)
    assert conn.execute("SELECT rowid,ts FROM session_fts ORDER BY msg_index").fetchall() == [(old_row,"2025-01-01T00:00:00Z"), (old_row+1,"2026-01-01T00:00:00Z")]
    assert conn.execute("SELECT parent_id FROM session_ancestry").fetchone()[0] == "parent"
    conn.close()


def test_unchanged_old_parser_upgrades_within_existing_budget(navcom, tmp_path):
    path = tmp_path / "dated.jsonl"
    key, modified, size = write(path, [dict(type="session_meta", payload=dict(id="dated", cwd=str(tmp_path))), codex("old login", "2025-01-01T00:00:00Z")])
    conn = navcom.open_index(tmp_path / "index.sqlite")
    navcom.index_logs(conn, [(key,modified,size,"codex")],progress=False)
    conn.execute("UPDATE session_fts SET ts=''")
    conn.execute("UPDATE file_parser SET ver=3")
    conn.execute("DELETE FROM session_ancestry");conn.commit()
    navcom.index_logs(conn, [(key,modified,size,"codex")],progress=False)
    assert conn.execute("SELECT ts FROM session_fts").fetchone()[0] == "2025-01-01T00:00:00Z"
    assert conn.execute("SELECT ver FROM file_parser").fetchone()[0] == 4
    assert conn.execute("SELECT parent_id FROM session_ancestry").fetchone()[0] == ""
    conn.close()


def test_native_index_to_historical_cli_replay_no_future_title(navcom, tmp_path):
    path = tmp_path / "dated.jsonl"
    records = [dict(type="session_meta", payload=dict(id="dated", cwd=str(tmp_path))),
               codex("native password login", "2025-01-01T00:00:00Z"),
               codex("FUTURE_COGNITO_SECRET", "2026-01-01T00:00:00Z")]
    key, modified, size = write(path, records)
    index = tmp_path / "index.sqlite"
    conn = navcom.open_index(index)
    navcom.index_logs(conn, [(key,modified,size,"codex")],progress=False)
    conn.close()
    cache = tmp_path / "space.json"
    nodes = [dict(id="galaxy:owner",kind="galaxy",parent_id=None,label="Owner",conversation_collections=[]),
             dict(id="planet:aurora",kind="planet",parent_id="galaxy:owner",label="Aurora",conversation_collections=["projects:"+identity(navcom.pretty_project(str(tmp_path)))])]
    cache.write_text(json.dumps(dict(schema_version=1,published=1,entities=nodes,edges=[],coverage={})))
    script = Path(__file__).resolve().parents[1]/"navcom.py"
    argv = [sys.executable,str(script),"history","conversations","Aurora","--at","2025-05-01","--query","login","--index",str(index),"--space-cache",str(cache),"--json"]
    result = subprocess.run(argv,capture_output=True,text=True)
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert len(data["nodes"]) == 1 and data["nodes"][0]["start"] == 1
    assert "FUTURE_COGNITO_SECRET" not in result.stdout
    replay = subprocess.run([sys.executable,str(script),*shlex.split(data["cli_command"])[1:]],capture_output=True,text=True)
    assert replay.returncode == 0, replay.stderr
    assert "native password login" in replay.stdout and "2025-01-01T00:00:00Z" in replay.stdout
    assert "FUTURE_COGNITO_SECRET" not in replay.stdout
