"""One shared function per job: the CLI, the terminal UI and the bridge call the same code.

Upkeep (maintain), launch pre-flight (prepare_launch), annotations (annotate), the
dashboard snapshot (dashboard_snapshot) and the local-model excerpt (suggest_for)
used to be re-implemented in navcom_web.py; these tests pin the shared behavior
and prove every surface reaches it.
"""
import json
from pathlib import Path
import sqlite3
import time

import pytest

import navcom_intelligence as intelligence
import navcom_web


@pytest.fixture
def session(navcom, tmp_path, monkeypatch):
    """One indexed Codex conversation with 30 alternating user and assistant turns."""
    monkeypatch.setattr(navcom, "INDEX_READ_ONLY", False)
    key = tmp_path / "rollout-2026-10-12T16-36-33-01a126c8-331b-7aa2-8783-d9ff30c38f32.jsonl"
    lines = [json.dumps({"type": "session_meta", "payload": {"id": "01a126c8-331b-7aa2-8783-d9ff30c38f32", "cwd": str(tmp_path)}})]
    for turn in range(1, 31):
        role = "user" if turn % 2 else "assistant"
        kind = "input_text" if role == "user" else "output_text"
        lines.append(json.dumps({"type": "response_item", "payload": {"type": "message", "role": role,
                                 "content": [{"type": kind, "text": f"turn{turn} " + "x" * 1500}]}}))
    key.write_text("\n".join(lines) + "\n")
    logs = [(str(key), 1, key.stat().st_size, "codex")]
    index = tmp_path / "index.sqlite"
    conn = navcom.open_index(index)
    navcom.index_logs(conn, logs, progress=False)
    monkeypatch.setattr(navcom, "list_logs", lambda *_: logs)
    yield navcom, conn, str(key), index
    conn.close()


# ── maintain: `navcom --maintain`, the TUI's Upkeep and the bridge's Upkeep ─────

def test_maintain_reports_each_stage_and_the_cli_prints_its_counts(session, monkeypatch, capsys):
    navcom, conn, key, _ = session
    import navcom_discovery
    monkeypatch.setattr(navcom, "_index_logs", lambda *a, **kw: 3)
    monkeypatch.setattr(navcom, "upgrade_stale_parses", lambda *a, **kw: 2)
    monkeypatch.setattr(navcom, "archive_logs", lambda *a, **kw: (1, 2_500_000))
    refreshed = []
    monkeypatch.setattr(navcom_discovery, "refresh", lambda db: refreshed.append(db))
    stages = []
    done = navcom.maintain(conn, progress=stages.append)
    assert stages == ["Discovering conversations", "Indexing new and changed conversations",
                      "Updating older transcript parsers", "Preserving raw transcript archives",
                      "Refreshing discovery evidence"]
    assert {k: done[k] for k in ("seen", "changed", "upgraded", "files", "raw")} == dict(seen=1, changed=3, upgraded=2, files=1, raw=2_500_000)
    assert refreshed == [conn]
    assert navcom.cmd_maintain(conn) == 0
    line = capsys.readouterr().out
    assert line.endswith(f"navcom {navcom.NAVCOM_VERSION} maintain: 1 sessions seen, 3 indexed, 2 re-parsed, "
                         "1 archived (2.5 MB) in 0s\n")


def test_bridge_upkeep_runs_maintain_and_keeps_its_own_progress(session, monkeypatch):
    navcom, conn, key, index = session
    app = navcom_web.WebApp(navcom, index)
    seen = []

    def maintain(db, progress=None):
        progress("Indexing new and changed conversations")
        seen.append(dict(app.task))
        return dict(seen=1, changed=4, upgraded=0, files=2, raw=0, seconds=0)

    monkeypatch.setattr(navcom, "maintain", maintain)
    assert app.post(conn, "/api/upkeep", {})["running"]
    deadline = time.monotonic() + 5
    while app.task["running"] and time.monotonic() < deadline:
        time.sleep(.02)
    assert seen == [dict(running=True, message="Indexing new and changed conversations", error=False)]
    assert app.task == dict(running=False, error=False, message="Complete: 4 indexed, 0 updated, 2 archived (0.0 MB).")
    assert not app.mutation.locked()


def test_claim_index_writer_fails_fast_while_another_process_writes(session):
    navcom, conn, key, index = session
    conn.execute("PRAGMA busy_timeout=20")
    blocker = sqlite3.connect(index)
    blocker.execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            navcom.claim_index_writer(conn)
    finally:
        blocker.rollback()
        blocker.close()
    conn.rollback()
    navcom.INDEX_READ_ONLY = True
    navcom.claim_index_writer(conn)
    assert navcom.INDEX_READ_ONLY is False and not conn.in_transaction


# ── prepare_launch: `navcom --resume REF --tab`, the TUI keys r/t and the bridge ─

def plan_for(tmp_path, **changes):
    return dict({"cwd": str(tmp_path), "argv": ["codex", "resume", "x"], "line": "codex resume x", "exact": True,
                 "note": "", "provider": "codex", "key": str(tmp_path / "gone.jsonl"), "gone": False, "archived": False},
                **changes)


def test_prepare_launch_checks_restore_binary_and_folder(navcom, tmp_path, monkeypatch):
    monkeypatch.setattr(navcom.shutil, "which", lambda exe: "/usr/bin/" + exe)
    plan = plan_for(tmp_path)
    assert navcom.prepare_launch(None, plan) == (True, "", plan)
    assert navcom.prepare_launch(None, plan_for(tmp_path, cwd=str(tmp_path / "moved"))) == \
        (False, f"its folder {tmp_path / 'moved'} no longer exists", plan_for(tmp_path, cwd=str(tmp_path / "moved")))
    blocked = plan_for(tmp_path, argv=[], blocked=True, note="parent conversation is unavailable", gone=True)
    assert navcom.prepare_launch(sqlite3.connect(":memory:"), blocked)[:2] == (False, "parent conversation is unavailable")
    restored = []
    monkeypatch.setattr(navcom, "ensure_resumable", lambda conn, p: restored.append(p) or (True, "restored it"))
    ok, message, ready = navcom.prepare_launch(sqlite3.connect(":memory:"), plan_for(tmp_path, gone=True, archived=True))
    assert (ok, message, ready["gone"]) == (True, "restored it", False) and len(restored) == 1
    monkeypatch.setattr(navcom.shutil, "which", lambda exe: None)
    assert navcom.prepare_launch(None, plan)[:2] == (False, "codex isn't installed here")


@pytest.mark.parametrize("key", ["r", "t"])
def test_tui_resume_keys_use_the_shared_preflight(navcom, tmp_path, monkeypatch, key):
    checked = []
    monkeypatch.setattr(navcom, "prepare_launch", lambda conn, plan: checked.append(plan) or (False, "codex isn't installed here", plan))
    monkeypatch.setattr(navcom, "resume_in_new_tab", lambda plan: pytest.fail("launched without a pre-flight"))
    assert navcom._resume_action(None, plan_for(tmp_path), key) == "· codex isn't installed here"
    assert checked == [plan_for(tmp_path)]


def test_tui_fresh_agent_picker_uses_the_shared_preflight(session, monkeypatch):
    navcom, conn, key, _ = session
    monkeypatch.setattr(navcom, "fresh_harnesses", lambda provider: ["claude"])
    monkeypatch.setattr(navcom.shutil, "which", lambda exe: None)

    class Term:
        keys = iter(["t", "esc"])
        frames = []
        def size(self): return 140, 30
        def draw(self, frame): self.frames.append("\n".join(frame))
        def key(self): return next(self.keys)

    term = Term()
    assert navcom._menu_revive(term, conn, key, "codex") == ""
    assert "claude isn't installed here" in term.frames[-1]


# ── annotate: the Recents keys e/d/f and the browser Library ───────────────────

def test_annotate_merges_one_line_text_and_favorite(session):
    navcom, conn, key, _ = session
    assert navcom.annotate(conn, key, name="  My\n  name ") == {"name": "My name"}
    assert navcom.annotate(conn, key, note="n" * 300, favorite=1) == {"name": "My name", "note": "n" * 239 + "…", "favorite": True}
    assert navcom.annotate(conn, key, name="") == {"name": "", "note": "n" * 239 + "…", "favorite": True}
    assert navcom._ui_read(conn, "annotations")[key]["favorite"] is True
    with pytest.raises(ValueError, match="text"):
        navcom.annotate(conn, key, note=5)


def test_annotate_reports_a_locked_index(session):
    navcom, conn, key, index = session
    conn.execute("PRAGMA busy_timeout=20")
    blocker = sqlite3.connect(index)
    blocker.execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(sqlite3.OperationalError, match="changes were not saved"):
            navcom.annotate(conn, key, note="blocked")
    finally:
        blocker.rollback()
        blocker.close()


def test_recents_keys_and_library_save_through_annotate(session, monkeypatch):
    navcom, conn, key, index = session
    calls = []
    real = navcom.annotate
    monkeypatch.setattr(navcom, "annotate", lambda *a, **kw: calls.append((a[1], kw)) or real(*a, **kw))

    class Term:
        keys = iter(["f", "e", "q"])
        prompts = iter(["Renamed in the TUI"])
        def size(self): return 110, 34
        def draw(self, rows): pass
        def key(self): return next(self.keys)
        def prompt(self, *args): return next(self.prompts)

    navcom._menu_recent(Term(), conn)
    app = navcom_web.WebApp(navcom, index)
    web = app.post(conn, "/api/annotation", dict(key=key, note="From the Library"))
    assert calls == [(key, dict(favorite=True)), (key, dict(name="Renamed in the TUI")),
                     (key, dict(name=None, note="From the Library", favorite=None))]
    assert web == navcom._ui_read(conn, "annotations")[key] == dict(favorite=True, name="Renamed in the TUI", note="From the Library")


# ── dashboard_snapshot: the TUI dashboard and GET /api/status ───────────────────

STATS = dict(sessions=1, on_disk=1, rescued=0, turns=30, tools=0, oldest=0, days=[0] * 30, per_harness={"codex": 1},
             retention=[], claude_old_kept=0, archive_files=0, archive_bytes=0, daily="no daily job", index_bytes=1)


def test_dashboard_snapshot_reuses_a_fresh_snapshot_for_tui_and_bridge(session, monkeypatch):
    navcom, conn, key, index = session
    computed, prepared = [], []
    monkeypatch.setattr(navcom, "dashboard_stats", lambda db, progress=None: computed.append(progress) or dict(STATS))
    first = navcom.dashboard_snapshot(conn, prepare=lambda: prepared.append(1))
    assert not first["cached"] and computed == [None] and prepared == [1]
    status = navcom_web.WebApp(navcom, index).get(conn, "/api/status", {})
    assert status["stats"]["cached"] and status["stats"]["sessions"] == 1 and len(computed) == 1
    assert status["task"] == dict(running=False, message="Ready", error=False)
    navcom.dashboard_snapshot(conn, force=True, progress="report")
    assert computed == [None, "report"] and prepared == [1]

    class Term:
        def size(self): return 100, 24
        def draw(self, rows): pass

    for name in ("auto_install_skills", "ensure_claude_retention", "ensure_gemini_retention",
                 "ensure_registered_retention", "auto_install_daily_job"):
        monkeypatch.setattr(navcom, name, lambda name=name: prepared.append(name))
    snapshots = []
    real = navcom.dashboard_snapshot
    monkeypatch.setattr(navcom, "dashboard_snapshot", lambda *a, **kw: snapshots.append(kw) or real(*a, **kw))
    _, stats = navcom._load_menu_dashboard(Term(), conn, force=True)
    assert snapshots[0]["force"] is True and stats["cached"] is False
    assert prepared[1:] == ["auto_install_skills", "ensure_claude_retention", "ensure_gemini_retention",
                            "ensure_registered_retention", "auto_install_daily_job"]


# ── suggest_for: POST /api/suggest ─────────────────────────────────────────────

def test_suggest_reads_the_first_three_and_last_ten_turns(session, monkeypatch):
    navcom, conn, key, index = session
    sent = []
    monkeypatch.setattr(intelligence, "suggest", lambda text: sent.append(text) or dict(available=False, message="none"))
    excerpt = intelligence.excerpt(navcom, conn, key)
    turns = [line.split(" ", 2)[1] for line in excerpt.splitlines()]
    assert turns == ["turn1", "turn2", "turn3"] + [f"turn{n}" for n in range(20, 31)]
    assert all(len(line) <= len("assistant: ") + 1200 for line in excerpt.splitlines())
    assert navcom_web.WebApp(navcom, index).post(conn, "/api/suggest", dict(key=key)) == dict(available=False, message="none")
    assert intelligence.suggest_for(navcom, conn, key) == dict(available=False, message="none")
    assert sent == [excerpt, excerpt]
    with pytest.raises(ValueError, match="Conversation not found"):
        navcom_web.WebApp(navcom, index).post(conn, "/api/suggest", dict(key=str(Path("/etc/passwd"))))
