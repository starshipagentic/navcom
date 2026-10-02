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


@then("the output starts with the skill frontmatter")
def step_frontmatter(context):
    assert context.out.startswith("---\nname: navcom-session-recall\n"), context.out[:120]


@when("I export the skill as a tar stream")
def step_export(context):
    proc = subprocess.run([sys.executable, context.navcom, "--skill", "export"], capture_output=True,
                          env=context.env, cwd=str(context.workdir), timeout=60)
    assert proc.returncode == 0, proc.stderr
    context.tar_bytes = proc.stdout


@then('the tar holds exactly "{member}" under one top-level directory')
def step_tar(context, member):
    import io
    import tarfile
    with tarfile.open(fileobj=io.BytesIO(context.tar_bytes)) as tar:
        names = tar.getnames()
        assert member in names, names
        assert {n.split("/")[0] for n in names} == {member.split("/")[0]}, names
        assert all(m.mtime == 0 and m.uid == 0 for m in tar.getmembers())


def _claude_settings(context):
    return context.home / ".claude" / "settings.json"


@given("Claude settings without a retention value")
def step_cs_none(context):
    import json
    _claude_settings(context).write_text(json.dumps({"model": "opus", "permissions": {"allow": ["Bash(ls:*)"]}}, indent=2))
    context.orig_settings = _claude_settings(context).read_text()


@given("Claude settings with cleanupPeriodDays {n:d}")
def step_cs_n(context, n):
    import json
    _claude_settings(context).write_text(json.dumps({"cleanupPeriodDays": n}))


@given("Claude settings that are not plain JSON")
def step_cs_jsonc(context):
    _claude_settings(context).write_text('{\n  // my comment\n  "model": "opus",\n}\n')
    context.orig_settings = _claude_settings(context).read_text()


@then("Claude's cleanupPeriodDays is {n:d}")
def step_cs_is(context, n):
    import json
    assert json.loads(_claude_settings(context).read_text())["cleanupPeriodDays"] == n


@then("the other Claude settings are untouched")
def step_cs_rest(context):
    import json
    now = json.loads(_claude_settings(context).read_text())
    now.pop("cleanupPeriodDays")
    assert now == json.loads(context.orig_settings), now


@then("a backup of the original Claude settings exists")
def step_cs_backup(context):
    backup = _claude_settings(context).with_name("settings.json.navcom-backup")
    assert backup.read_text() == context.orig_settings


@then("the Claude settings file is byte-for-byte unchanged")
def step_cs_same(context):
    assert _claude_settings(context).read_text() == context.orig_settings


@then("every navcom index file is readable only by its owner")
def step_private(context):
    import os
    import stat
    from pathlib import Path
    idx = Path(context.env["NAVCOM_INDEX"])
    files = list(idx.parent.glob(idx.name + "*")) + [idx.parent / "navcom-skills.json"]
    for f in files:
        if f.exists():
            mode = stat.S_IMODE(os.stat(f).st_mode)
            assert mode & 0o077 == 0, f"{f} is {oct(mode)}"


@then("the claude transcript has a private archive copy")
def step_archived(context):
    import os
    arch = list((context.home / ".navcom" / "archive" / "claude").rglob("*.jsonl.gz"))
    assert arch, "no archive copy"
    assert all(os.stat(a).st_mode & 0o077 == 0 for a in arch)
    context.original_claude = context.sessions["claude"].read_bytes()


@when("the claude transcript is deleted")
def step_delete(context):
    if not hasattr(context, "original_claude"):
        context.original_claude = context.sessions["claude"].read_bytes()
    context.sessions["claude"].unlink()


@then("the claude transcript is back byte for byte")
def step_back(context):
    assert context.sessions["claude"].read_bytes() == context.original_claude


def _job_files(context):
    return [context.home / "Library" / "LaunchAgents" / "io.navcom.maintain.plist",
            context.home / ".config" / "systemd" / "user" / "navcom-maintain.timer"]


@then("a daily navcom --maintain job is scheduled")
def step_daily(context):
    found = [p for p in _job_files(context) if p.exists()]
    assert found, "no daily job file"
    assert "--maintain" in found[0].read_text(errors="replace") or found[0].suffix == ".timer"


@then("no daily job is scheduled")
def step_no_daily(context):
    assert not any(p.exists() for p in _job_files(context))
