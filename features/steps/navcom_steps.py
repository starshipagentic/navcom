import json
import re
import shlex
import subprocess
import sys

from behave import given, then, when


def _run(context, args, stdin=None, cwd=None):
    proc = subprocess.run(
        [sys.executable, context.navcom] + args,
        input=stdin, capture_output=True, text=True, env=context.env,
        cwd=cwd or str(context.workdir), timeout=120,
    )
    context.rc, context.out, context.err = proc.returncode, proc.stdout, proc.stderr
    assert "Traceback" not in proc.stderr, f"navcom crashed:\n{proc.stderr}"


@given("a home with sessions from every harness")
def step_home(context):
    assert context.sessions, "fixture home was not built"


@when("I run: navcom {cmdline}")
def step_run(context, cmdline):
    _run(context, shlex.split(cmdline))


@when("I search with these literal arguments")
def step_run_table(context):
    _run(context, [row["arg"] for row in context.table])


@when("I pipe this query into navcom")
def step_pipe(context):
    _run(context, ["-"], stdin=context.text)


@when("I run from outside the project: navcom {cmdline}")
def step_run_elsewhere(context, cmdline):
    elsewhere = context.home / "work" / "some-other-project"
    elsewhere.mkdir(parents=True, exist_ok=True)
    _run(context, shlex.split(cmdline), cwd=str(elsewhere))


@when('I open the ref of the first "{harness}" session at turn {n:d}')
def step_open_first(context, harness, n):
    refs = re.findall(rf"^\[\d+\] \S+\s+{harness}\s+\S+\s+ref (\S+)", context.out, re.M)
    assert refs, f"no {harness} session in output:\n{context.out}"
    _run(context, ["--open", f"{refs[0]}:{n}"])


@then("it succeeds")
def step_ok(context):
    assert context.rc == 0, f"rc={context.rc}\nstdout:\n{context.out}\nstderr:\n{context.err}"


@then("it fails with exit code {code:d}")
def step_fail(context, code):
    assert context.rc == code, f"rc={context.rc}\n{context.out}\n{context.err}"


@then('the output contains "{text}"')
def step_contains(context, text):
    assert text in context.out, f"expected {text!r} in:\n{context.out}"


@then('the output does not contain "{text}"')
def step_not_contains(context, text):
    assert text not in context.out, f"did not expect {text!r} in:\n{context.out}"


@then('stderr contains "{text}"')
def step_err_contains(context, text):
    assert text in context.err, f"expected {text!r} in stderr:\n{context.err}"


@then("the output has no terminal escape codes")
def step_no_ansi(context):
    assert "\x1b[" not in context.out, repr(context.out[:500])


@then("the output lists {n:d} sessions")
def step_n_sessions(context, n):
    got = len(re.findall(r"^\[\d+\] ", context.out, re.M))
    assert got == n, f"expected {n} sessions, got {got}:\n{context.out}"


@then('the "{harness}" harness is in the results')
def step_harness(context, harness):
    assert re.search(rf"^\[\d+\] \S+\s+{harness}\s", context.out, re.M), f"{harness} missing:\n{context.out}"


@then("every harness is in the results")
def step_every(context):
    for harness in ("claude", "codex", "gemini", "pi", "omo", "opencode", "goose"):
        step_harness(context, harness)


@then("the output is valid JSON with {n:d} sessions")
def step_json(context, n):
    data = json.loads(context.out)
    assert len(data["sessions"]) == n, data


@when("I run navcom with no arguments")
def step_run_bare(context):
    _run(context, [])


@when("I run with {var}={value}: navcom {cmdline}")
def step_run_with_env(context, var, value, cmdline):
    context.env = dict(context.env, **{var: value})
    _run(context, shlex.split(cmdline))


@when("I make the index read-only")
def step_ro(context):
    import os
    from pathlib import Path
    idx = Path(context.env["NAVCOM_INDEX"])
    for p in idx.parent.glob(idx.name + "*"):
        os.chmod(p, 0o444)
    os.chmod(idx.parent, 0o555)
    context.add_cleanup(os.chmod, idx.parent, 0o755)


@given("a summarizer CLI that hangs forever")
def step_hang(context):
    import os
    bindir = context.tmp / "bin"
    bindir.mkdir(exist_ok=True)
    for name in ("claude", "gemini", "codex", "ollama"):
        script = bindir / name
        script.write_text("#!/bin/sh\nsleep 600 &\nsleep 600\n")
        os.chmod(script, 0o755)
    context.env["PATH"] = f"{bindir}:/usr/bin:/bin"
    skip = context.home / ".codex" / "navcom-skip-cache"
    if skip.exists():
        skip.unlink()


def _skill_path(context, which):
    base = {"claude": ".claude", "codex": ".codex", "agents": ".agents"}[which]
    return context.home / base / "skills" / "navcom-session-recall" / "SKILL.md"


@then('the skill card exists for "{which}"')
def step_skill_exists(context, which):
    p = _skill_path(context, which)
    assert p.exists() and "name: navcom-session-recall" in p.read_text(), p


@then('the skill card is missing for "{which}"')
def step_skill_missing(context, which):
    assert not _skill_path(context, which).exists()


@then("stderr does not mention skills")
def step_quiet(context):
    assert "skill" not in context.err.lower(), context.err


@when('I edit the "{which}" skill card')
def step_edit(context, which):
    p = _skill_path(context, which)
    p.write_text(p.read_text() + "\nMY LOCAL EDIT\n")


@then('the "{which}" skill card still has my edit')
def step_kept(context, which):
    assert "MY LOCAL EDIT" in _skill_path(context, which).read_text()


@when('the "{which}" skill card is from an older navcom')
def step_older(context, which):
    import hashlib
    import json
    p = _skill_path(context, which)
    old = p.read_text().replace("# NavCom session recall", "# NavCom session recall (old)")
    p.write_text(old)
    state = context.home / "navcom-skills.json"
    data = json.loads(state.read_text())
    data[str(p)] = hashlib.sha256(old.encode()).hexdigest()
    state.write_text(json.dumps(data))


@then('the "{which}" skill card is current')
def step_current(context, which):
    assert "(old)" not in _skill_path(context, which).read_text()
