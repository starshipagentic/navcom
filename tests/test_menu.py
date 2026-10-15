"""navcom --menu: every frame row is exactly the terminal width, and the dashboard tells the truth."""
import re
import subprocess
import sys
from pathlib import Path

import fake_home

ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
ROOT = Path(__file__).resolve().parent.parent


def visible(row):
    return len(ANSI.sub("", row))


def test_splash_and_screens_are_exact_width(navcom):
    for width in (80, 118, 160):
        for row in navcom.splash_frame(width):
            assert visible(row) == width
        rows = navcom._screen("TITLE", [navcom._line([("x" * 500, None, None)], width)], width, 30, "keys", "navcom x")
        assert all(visible(r) == width for r in rows) and len(rows) == 30
    assert "YOUR CONVERSATIONS · YOUR MACHINE · YOUR DATA" in ANSI.sub("", "".join(navcom.splash_frame(100)))


def test_dashboard_reports_retention_and_history(navcom, tmp_path, monkeypatch):
    home = tmp_path / "home"
    fake_home.build(home)
    for k, v in fake_home.env_for(home).items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    conn = navcom.open_index(tmp_path / "idx.sqlite")
    navcom.index_logs(conn, navcom.list_logs(navcom.ALL_PROVIDERS), progress=False)
    navcom.ensure_claude_retention()
    stats = navcom.dashboard_stats(conn)
    assert stats["sessions"] > 20 and stats["turns"] > 0
    frame = navcom.dashboard_frame(stats, 0, 120, 40)
    assert all(visible(r) == 120 for r in frame)
    text = ANSI.sub("", "\n".join(frame))
    for needle in ("HISTORY", "RETENTION", "Claude's default", "30 days", "100 years", "ACTIVITY", "SEARCH", "CLI ▸"):
        assert needle in text, needle
    assert "Claude Code" in text and "kept 100y" in text


def test_bare_navcom_prints_help_and_menu_needs_a_terminal(tmp_path):
    env = fake_home.env_for(tmp_path / "home")
    out = subprocess.run([sys.executable, str(ROOT / "navcom.py")], capture_output=True, text=True, env=env)
    assert out.returncode == 0 and "navcom atlas list research" in out.stdout and "navcom help all" in out.stdout
    out = subprocess.run([sys.executable, str(ROOT / "navcom.py"), "--tui"], capture_output=True, text=True, env=env)
    assert out.returncode == 0 and "run it in a terminal" in out.stdout


def test_loading_bar_animates_and_fits(navcom):
    for width in (60, 80, 118, 160):
        first = navcom.loading_frame(width, 24, 4, 'Counting indexed tool messages', 0)
        later = navcom.loading_frame(width, 24, 4, 'Counting indexed tool messages', 0.2)
        assert len(first) == 24 and all(visible(row) == width for row in first)
        assert first != later
        assert 'press any key' not in '\n'.join(first)
        assert '4/8' in '\n'.join(first)
        assert 'Opening automatically' in '\n'.join(first)


class LoadingTerm:
    def __init__(self): self.frames = []
    def size(self): return 100, 24
    def draw(self, rows): self.frames.append(rows)


def disable_setup(navcom, monkeypatch):
    for name in ('auto_install_skills', 'ensure_claude_retention', 'ensure_gemini_retention',
                 'ensure_registered_retention', 'auto_install_daily_job'):
        monkeypatch.setattr(navcom, name, lambda: None)


def test_startup_cache_survives_reopen_and_skips_discovery(navcom, tmp_path, monkeypatch):
    import time
    home = tmp_path / 'home'
    fake_home.build(home)
    for k, v in fake_home.env_for(home).items(): monkeypatch.setenv(k, v)
    monkeypatch.setattr(Path, 'home', classmethod(lambda cls: home))
    disable_setup(navcom, monkeypatch)
    path = tmp_path / 'idx.sqlite'
    term = LoadingTerm()
    conn, fresh = navcom._load_menu_dashboard(term, index_path=path)
    assert not fresh['cached']
    conn.close()
    def forbidden(*args, **kwargs): raise AssertionError('warm startup repeated expensive discovery')
    monkeypatch.setattr(navcom, 'dashboard_stats', forbidden)
    monkeypatch.setattr(navcom, 'auto_install_skills', forbidden)
    term = LoadingTerm()
    conn, cached = navcom._load_menu_dashboard(term, index_path=path)
    assert cached['cached'] and cached['sessions'] == fresh['sessions']
    assert len(term.frames) >= 2  # Even an immediate cache hit shows a bar and completion.
    cache, _ = navcom._dashboard_cache_context(conn)
    import json
    saved = json.loads(cache.read_text())
    saved['at'] = time.time() - navcom.DASHBOARD_CACHE_TTL - 1
    cache.write_text(json.dumps(saved))
    assert navcom._read_dashboard_cache(conn) is None
    cache.write_text('{broken')
    assert navcom._read_dashboard_cache(conn) is None
    conn.close()


def test_progress_keeps_moving_during_blocking_work_and_refresh_bypasses_cache(navcom, tmp_path, monkeypatch):
    import time
    disable_setup(navcom, monkeypatch)
    conn = navcom.open_index(tmp_path / 'idx.sqlite')
    monkeypatch.setattr(navcom, '_read_dashboard_cache', lambda _: (_ for _ in ()).throw(AssertionError('force read cache')))
    monkeypatch.setattr(navcom, '_write_dashboard_cache', lambda *_: None)
    def slow_stats(conn, report):
        report(4, 'Counting indexed tool messages')
        time.sleep(.3)
        return {'cached': False}
    monkeypatch.setattr(navcom, 'dashboard_stats', slow_stats)
    term = LoadingTerm()
    navcom._load_menu_dashboard(term, conn, force=True)
    busy = [frame for frame in term.frames if 'Counting indexed tool messages' in '\n'.join(frame)]
    assert len(busy) >= 2 and busy[0] != busy[-1]
    conn.close()


def test_cache_invalidates_on_index_change(navcom, tmp_path):
    conn = navcom.open_index(tmp_path / 'idx.sqlite')
    _, before = navcom._dashboard_cache_context(conn)
    conn.execute('INSERT INTO file_state (file, mtime, size) VALUES (?, ?, ?)', ('new', 1, 12))
    _, after = navcom._dashboard_cache_context(conn)
    assert before != after
    conn.close()


def test_upkeep_busy_stays_in_menu_and_retries_after_writer_releases(navcom, tmp_path, monkeypatch):
    import sqlite3
    path = tmp_path / 'idx.sqlite'
    conn = navcom.open_index(path)
    conn.execute('PRAGMA busy_timeout=20')
    blocker = sqlite3.connect(path)
    blocker.execute('BEGIN IMMEDIATE')
    calls = []
    def maintain(db):
        calls.append(True)
        db.execute("INSERT INTO file_state (file, mtime, size) VALUES ('recovered', 1, 1)")
        db.commit()
    monkeypatch.setattr(navcom, 'cmd_maintain', maintain)
    monkeypatch.setattr(navcom, '_load_menu_dashboard', lambda term, db, **kw: (db, {'fresh': True}))
    class Term(LoadingTerm):
        count = 0
        def key(self):
            self.count += 1
            if self.count == 1:
                assert 'index busy' in '\n'.join(self.frames[-1])
                assert calls == []  # Preflight avoids starting expensive indexing.
                blocker.rollback()
                return 'r'
            return 'esc'
    term = Term()
    assert navcom._menu_maintain(term, conn, {}) == {'fresh': True}
    assert calls == [True]
    assert conn.execute("SELECT count(*) FROM file_state WHERE file='recovered'").fetchone()[0] == 1
    assert not conn.in_transaction
    blocker.close(); conn.close()


def test_metadata_writer_released_before_waiting_for_input(navcom, tmp_path):
    import sqlite3
    path = tmp_path / 'idx.sqlite'
    conn = navcom.open_index(path)
    conn.execute("INSERT INTO file_meta (file, title) VALUES ('test', 'title')")
    assert conn.in_transaction
    navcom._menu_release_index(conn)
    other = sqlite3.connect(path, timeout=.01)
    other.execute('BEGIN IMMEDIATE')
    other.rollback()
    assert not conn.in_transaction
    other.close(); conn.close()


def test_upkeep_operational_error_rolls_back_and_returns_to_dashboard(navcom, tmp_path, monkeypatch):
    import sqlite3
    conn = navcom.open_index(tmp_path / 'idx.sqlite')
    def fail(db):
        db.execute("INSERT INTO file_state (file, mtime, size) VALUES ('unfinished', 1, 1)")
        raise sqlite3.OperationalError('disk is full')
    monkeypatch.setattr(navcom, 'cmd_maintain', fail)
    class Term(LoadingTerm):
        def key(self): return 'esc'
    term = Term()
    original = {'old': True}
    assert navcom._menu_maintain(term, conn, original) is original
    assert 'disk is full' in '\n'.join(term.frames[-1])
    assert not conn.in_transaction
    assert conn.execute('SELECT count(*) FROM file_state').fetchone()[0] == 0
    conn.close()
