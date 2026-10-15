"""--help is how LLMs learn navcom: every example in it must actually run."""
import re
import shlex
import subprocess
import sys
from pathlib import Path

import fake_home
import pytest

ROOT = Path(__file__).resolve().parent.parent


def help_examples(navcom, text=None):
    examples = []
    for line in (text or navcom.HELP_TEXT).splitlines():
        m = re.match(r"\s*(?:\d\.\s+)?(navcom(?:\s[^←]*?)?)(?:\s{2,}|\s*←|$)", line)
        if not m:
            continue
        cmd = m.group(1).strip()
        cmd = cmd.split("#")[0].strip() if " # " in cmd or "  #" in line else cmd
        if "<" in cmd or "…" in cmd or cmd.endswith("-") or "—" in cmd:
            continue  # placeholders / the stdin form (covered by BDD)
        examples.append(cmd)
    return examples


def test_help_has_examples_for_every_section(navcom):
    ex = help_examples(navcom)
    assert len(ex) >= 20, ex
    for needle in ("--open", "--here", "--project", "--days", "--user", "--this-session", "--context", "-n 50"):
        assert any(needle in e for e in ex), needle


def test_every_help_example_runs(navcom, tmp_path):
    home = tmp_path / "home"
    _, workdir = fake_home.build(home)
    env = fake_home.env_for(home)
    env["NAVCOM_SUMMARY_TIMEOUT"] = "1"
    env["PATH"] = "/usr/bin:/bin"  # no LLM CLIs: --solo must degrade, not hang
    subprocess.run([sys.executable, str(ROOT / "navcom.py"), "--maintain"],
                   env=env, cwd=workdir, capture_output=True, check=True)
    failures = []
    for cmd in help_examples(navcom) + help_examples(navcom, navcom.SKILL_MD):
        args = shlex.split(cmd)[1:]
        if "--menu" in args:
            import select, signal
            from urllib.request import urlopen
            child = subprocess.Popen([sys.executable, str(ROOT / "navcom.py")] + args + ["--no-browser"],
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env, cwd=workdir)
            try:
                assert select.select([child.stdout], [], [], 15)[0], "web menu did not start"
                line = child.stdout.readline()
                url = re.search(r"http://127\.0\.0\.1:\d+/", line)
                assert url, line
                with urlopen(url.group(), timeout=5) as response:
                    assert b"Mission control" in response.read()
            finally:
                child.send_signal(signal.SIGINT)
                _, stderr = child.communicate(timeout=5)
            assert child.returncode == 0 and "Traceback" not in stderr
            continue
        proc = subprocess.run([sys.executable, str(ROOT / "navcom.py")] + args, capture_output=True,
                              text=True, env=env, cwd=workdir, timeout=60)
        if "Traceback" in proc.stderr or proc.returncode not in (0, 1):
            failures.append((cmd, proc.returncode, proc.stderr[-300:]))
    assert not failures, failures


def test_repo_skill_file_matches_embedded_card(navcom):
    assert (ROOT / "skills" / "navcom-session-recall" / "SKILL.md").read_text() == navcom.SKILL_MD


def test_skill_card_frontmatter(navcom):
    head = navcom.SKILL_MD.split("---")
    assert "name: navcom-session-recall" in head[1] and "description:" in head[1]


def test_complete_help_contains_atlas_and_browse_controls(navcom):
    import navcom_atlas_cli as cli
    all_help=cli.help_text(navcom,'all')
    for command in ('list','explore','search','show','tree','refresh'):
        assert 'navcom atlas '+command in all_help
    assert '--within' in all_help and '--children' in all_help
    browse=cli.help_text(navcom,'browse')
    assert 't opens a new tab' in browse and 'n chooses a fresh harness' in browse
    assert 'no LLM' in browse
    assert '--within' in cli.help_text(navcom,'search',atlas=True)
    assert '--project' in cli.help_text(navcom,'search')
