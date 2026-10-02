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
    assert out.returncode == 0 and "THE RECIPE" in out.stdout and "usage: navcom" in out.stdout
    out = subprocess.run([sys.executable, str(ROOT / "navcom.py"), "--menu"], capture_output=True, text=True, env=env)
    assert out.returncode == 0 and "run it in a terminal" in out.stdout
