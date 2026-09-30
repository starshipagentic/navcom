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
