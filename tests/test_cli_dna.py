"""NavCom's DNA: the fast, simple, LLM-proof headless CLI.

Agents run `navcom <words>`, `--open`, `--recap` and `--resume` every day and parse what
they print. These tests pin that contract: `import navcom` stays light, the core verbs
never load the galaxy (navcom_* service modules), words that look like commands still
search, and the output shapes LLMs read stay put. Change them only on purpose.
The matching speed gate against the owner's real index is scripts/dna_perf.py.
"""
import importlib
import json
import re
import subprocess
import sys
from pathlib import Path

import fake_home
import pytest

ROOT = Path(__file__).resolve().parent.parent
NAVCOM = str(ROOT / "navcom.py")
CODEX_UUID = "0199aaaa-bbbb-7ccc-8ddd-eeeeeeeeeeee"  # UUIDv7: ref is the random tail
CLAUDE_UUID = "11111111-2222-4333-8444-555555555555"  # UUIDv4: ref is the head
# Stdlib modules `import navcom` used to pull in for nothing (dataclasses drags in inspect,
# dis, ast and tokenize). Parsers that need one import it inside the function.
DIETED = ("dataclasses", "inspect", "uuid", "tempfile", "base64", "struct", "html")


@pytest.fixture(scope="module")
def home(tmp_path_factory):
    home = tmp_path_factory.mktemp("dna") / "home"
    _, workdir = fake_home.build(home)
    return fake_home.env_for(home), workdir


def run(home, *args, importtime=False):
    env, workdir = home
    cmd = [sys.executable] + (["-X", "importtime"] if importtime else []) + [NAVCOM, *args]
    proc = subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=str(workdir), timeout=120)
    assert "Traceback" not in proc.stderr, proc.stderr
    return proc


def imported(stderr):
    """Module names from -X importtime output."""
    return {line.rsplit("|", 1)[1].strip() for line in stderr.splitlines()
            if line.startswith("import time:") and "|" in line} - {"package"}


# (a) import cost ──────────────────────────────────────────────────────────────

def test_import_navcom_loads_no_service_modules_and_no_dieted_stdlib():
    code = ("import sys; before = set(sys.modules); sys.path.insert(0, sys.argv[1]); import navcom; "
            "print('\\n'.join(sorted(set(sys.modules) - before)))")
    proc = subprocess.run([sys.executable, "-c", code, str(ROOT)], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    loaded = set(proc.stdout.split())
    assert "navcom" in loaded
    assert sorted(m for m in loaded if m.startswith("navcom_")) == []
    assert sorted(m for m in loaded if m.split(".")[0] in DIETED) == []


# (b) the core verbs never load the galaxy ─────────────────────────────────────

@pytest.mark.parametrize("args", [
    ("cognito", "token"),
    ("--open", "eeeeeeeeeeee:2"),
    ("--recap", "eeeeeeeeeeee"),
    ("--resume", "eeeeeeeeeeee", "--print"),
], ids=["search", "open", "recap", "resume-print"])
def test_core_verbs_load_no_navcom_service_modules(home, args):
    run(home, "--maintain")  # index first, so every verb below is the everyday read path
    proc = run(home, *args, importtime=True)
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert sorted(m for m in imported(proc.stderr) if m.startswith("navcom_")) == []


# (c) words that look like commands are still a search ────────────────────────

@pytest.mark.parametrize("argv", [
    ["history", "of", "the", "cognito", "auth", "bug"],
    ["sources", "of", "the", "cognito", "auth", "bug"],
    ["atlas", "of", "the", "cognito", "auth", "bug"],
    ["voice", "of", "the", "cognito", "auth", "bug"],
    ["help", "me", "find", "the", "cognito", "auth", "bug"],
    ["history", "--json"],
])
def test_command_words_followed_by_other_words_search(home, argv):
    proc = run(home, *argv)
    assert proc.returncode == 0, proc.stderr
    assert "invalid choice" not in proc.stderr and "Unknown help subject" not in proc.stderr
    if "--json" in argv:
        assert json.loads(proc.stdout)["query"].startswith(argv[0] + "*")
    else:
        assert re.match(rf"navcom: \d+ hits? in \d+ sessions? · query: {argv[0]}\* ", proc.stdout), proc.stdout[:300]


def test_every_real_subcommand_still_starts_its_command(navcom):
    for word, module_name in navcom.COMMAND_MODULES.items():
        parser = importlib.import_module(module_name).parser()
        names = [name for action in parser._actions if hasattr(action, "choices") and isinstance(action.choices, dict)
                 for name in action.choices]
        assert names, module_name
        for name in names:
            assert navcom.leading_command([word, name, "x"]) == word, (word, name)
        for argv in ([word], [word, "-h"], [word, "--help"]):
            assert navcom.leading_command(argv) == word, argv
        assert navcom.leading_command([word, "of", "the", "fix"]) is None
    assert navcom.leading_command(["search", "history"]) is None
    assert navcom.leading_command([]) is None


def test_help_with_a_subject_is_help_and_command_help_still_works(home):
    proc = run(home, "help", "search")
    assert proc.returncode == 0 and proc.stdout.startswith("navcom <words>"), proc.stdout[:200]
    proc = run(home, "history", "timeline", "--help")
    assert proc.returncode == 0 and proc.stdout.startswith("usage: navcom history timeline"), proc.stdout[:200]
    proc = run(home, "help")
    assert proc.returncode == 0 and proc.stdout.startswith("NavCom — "), proc.stdout[:200]


# (d) output shapes LLMs parse ─────────────────────────────────────────────────

SEARCH_HEAD = re.compile(r"^navcom: \d+ hits? in \d+ sessions? · query: \S.*$")
SESSION_LINE = re.compile(r"^\[(\d+)\] (\d{4}-\d{2}-\d{2})  (\S+)\s+(\S+)  ref (\S+)  \((\d+) hits?\)$")
HIT_LINE = re.compile(r"^    #(\d+) (user|assistant|cmd|tool): ")


def test_search_output_shape(home):
    proc = run(home, "cognito", "token")
    assert proc.returncode == 0, proc.stderr
    lines = proc.stdout.splitlines()
    assert SEARCH_HEAD.match(lines[0]), lines[0]
    assert lines[0].endswith("query: cognito* token*"), lines[0]
    session = SESSION_LINE.match(lines[1])
    assert session, lines[1]
    assert session.group(3) == "codex" and session.group(4) == "~/work/proj-alpha"
    assert session.group(5) == CODEX_UUID[-12:]  # UUIDv7 → last 12 hex
    hit = HIT_LINE.match(lines[2])
    assert hit and hit.group(2) == "assistant", lines[2]
    assert "«cognito» «token»" in lines[2]
    ref, turn = session.group(5), hit.group(1)
    assert f"→ read around a hit: navcom --open {ref}:{turn}" in proc.stdout
    assert f"whole story: navcom --recap {ref}" in proc.stdout
    assert f"cd ~/work/proj-alpha && codex resume {CODEX_UUID}" in proc.stdout


def test_search_ref_formats_and_no_hits_line(home):
    proc = run(home, "drizzle", "migration", "--claude")
    assert proc.returncode == 0, proc.stderr
    refs = [m.group(5) for m in map(SESSION_LINE.match, proc.stdout.splitlines()) if m]
    assert CLAUDE_UUID[:8] in refs, proc.stdout  # UUIDv4 → first 8 hex
    proc = run(home, "zzqqxxnothinghere")
    assert proc.returncode == 0
    assert re.match(r"^No hits\. \(query: zzqqxxnothinghere\* · .+\)$", proc.stdout.splitlines()[0]), proc.stdout


def test_search_json_shape(home):
    empty = json.loads(run(home, "zzqqxxnothinghere", "--json").stdout)  # nothing found is still JSON
    assert empty == {"query": "zzqqxxnothinghere*", "note": None, "sessions": []}
    data = json.loads(run(home, "cognito", "--json").stdout)
    assert set(data) >= {"query", "note", "sessions"}
    session = data["sessions"][0]
    assert set(session) >= {"ref", "key", "provider", "date", "project", "title", "resume", "recap", "hits"}
    assert session["recap"] == f"navcom --recap {session['ref']}"
    assert set(session["hits"][0]) >= {"msg_index", "role", "snippet"}


def test_open_output_shape(home):
    proc = run(home, "--open", "eeeeeeeeeeee:2")
    assert proc.returncode == 0, proc.stderr
    lines = proc.stdout.splitlines()
    assert re.match(r"^\d{4}-\d{2}-\d{2}  codex  ~/work/proj-alpha  ref eeeeeeeeeeee  turns \d+-\d+ of \d+$", lines[0]), lines[0]
    assert lines[1].endswith(f"rollout-2026-09-01T10-00-00-{CODEX_UUID}.jsonl"), lines[1]
    assert lines[2] == f"resume: cd ~/work/proj-alpha && codex resume {CODEX_UUID}", lines[2]
    assert lines[3].startswith("recap:  navcom --recap eeeeeeeeeeee"), lines[3]
    turns = [m for m in (re.match(r"^(▶ )?#(\d+) (user|assistant|cmd|tool):", line) for line in lines) if m]
    assert [m.group(2) for m in turns if m.group(1)] == ["2"]  # the requested turn is marked
    assert all(int(m.group(2)) < int(n.group(2)) for m, n in zip(turns, turns[1:]))
    assert re.search(r"^→ more: navcom --open eeeeeeeeeeee:\d+-\d+$", proc.stdout, re.M), proc.stdout


def test_recap_output_shape(home):
    proc = run(home, "--recap", "eeeeeeeeeeee")
    assert proc.returncode == 0, proc.stderr
    lines = proc.stdout.splitlines()
    assert re.match(r"^navcom --recap · codex · \d{4}-\d{2}-\d{2} · ~/work/proj-alpha · ref eeeeeeeeeeee · \d+ turns$", lines[0]), lines[0]
    assert lines[1].startswith("title: ") and lines[2] == f"reopen it: cd ~/work/proj-alpha && codex resume {CODEX_UUID}"
    for section in ("## What the user asked", "## Where it stopped", "## Commands run", "## Dig deeper"):
        assert re.search(rf"^{section}", proc.stdout, re.M), section
    assert "navcom --open eeeeeeeeeeee:<n>" in proc.stdout


def test_resume_print_is_one_runnable_line(home):
    proc = run(home, "--resume", "eeeeeeeeeeee", "--print")
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == f"cd ~/work/proj-alpha && codex resume {CODEX_UUID}\n", proc.stdout
