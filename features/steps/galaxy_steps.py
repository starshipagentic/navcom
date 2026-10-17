"""Steps for the cockpit verb families: places, search inside, dated history,
conversation verbs and fleet verbs.

Every step runs the real CLI (`python navcom.py ...`) in a throwaway HOME built
by features/support/galaxy_world.py. Place references in step text are written
{kind:label} or {kind:label@parent label} and resolved against the chart this
scenario published; {source:label} names a harvested source, {commit:classic},
{commit:modern}, {commit:later} or {commit:mirror} an Orchard commit, and
{repo:orchard}, {repo:radar-classic} or {repo:orchard-mirror} a fixture Git
repository (the mirror exists only after its Given step).

A machine without native Starforge skips the galaxy scenarios, as the pytest
suite does; set NAVCOM_BDD_REQUIRE_STARFORGE=1 (CI) to fail them instead.

This module deliberately does not import navcom_steps (behave would register
its steps twice); it sets the same context.rc / context.out / context.err, so
the shared "it succeeds" / "the output contains" steps apply.
"""
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from behave import given, then, when

import galaxy_world

PLACE = re.compile(r"\{(\w+):([^{}]+)\}")


def _resolve(context, text):
    def one(match):
        kind, label = match.group(1), match.group(2)
        if kind == "commit":
            assert label in context.world["commits"], f"no {label!r} Orchard commit: {context.world['commits']}"
            return context.world["commits"][label]
        if kind == "repo":
            repos = {"orchard": context.world["repo"], "radar-classic": context.world["legacy"],
                     "orchard-mirror": context.world.get("mirror")}
            assert repos.get(label), f"no {label!r} fixture repository in this scenario: {repos}"
            return str(repos[label])
        if kind == "source":
            state = json.loads((Path(context.env["NAVCOM_SOURCES_CACHE"]) / "current.json").read_text())
            found = [s["id"] for s in state["sources"] if s.get("label") == label]
            assert len(found) == 1, f"expected one harvested source labelled {label!r}: {state['sources']}"
            return found[0]
        return galaxy_world.place(context, kind, label)
    return PLACE.sub(one, text)


def _run(context, argv, cwd=None):
    proc = subprocess.run([sys.executable, context.navcom] + list(argv), capture_output=True, text=True,
                          env=context.env, cwd=str(cwd or context.workdir), timeout=300)
    context.rc, context.out, context.err = proc.returncode, proc.stdout, proc.stderr
    context.argv = list(argv)
    assert "Traceback" not in proc.stderr, f"navcom crashed:\nnavcom {shlex.join(argv)}\n{proc.stderr}"


def _navcom_argv(command):
    """A printed `navcom ...` command as argv for this checkout's navcom.py."""
    argv = shlex.split(command) if isinstance(command, str) else list(command)
    assert argv and argv[0] == "navcom", f"not a navcom command: {command!r}"
    return argv[1:]


def _follow(context, command, extra=()):
    """Run a command printed inside a result, in the same output mode as that result.

    Printed commands are replay commands (text by default); following one from
    a --json result keeps --json, as a script or the web adapter would.
    """
    argv = _navcom_argv(command) + list(extra)
    if "--json" in getattr(context, "argv", []) and "--json" not in argv:
        argv.append("--json")
    _run(context, argv)


def _json(context):
    try:
        return json.loads(context.out)
    except ValueError as error:
        raise AssertionError(f"stdout is not one JSON document ({error}):\n{context.out[:2000]}") from None


def _field(data, path):
    for part in path.split("."):
        assert isinstance(data, dict) and part in data, f"no {part!r} in {json.dumps(data)[:1500]}"
        data = data[part]
    return data


def _text(value):
    return value if isinstance(value, str) else json.dumps(value)


# ── Given ──────────────────────────────────────────────────────────────────

@given("a charted Orchard galaxy")
def step_galaxy(context):
    if not galaxy_world.starforge_available():  # Same policy as the pytest suite's native tests.
        reason = "Native Starforge is required to harvest the Orchard galaxy"
        assert os.environ.get("NAVCOM_BDD_REQUIRE_STARFORGE") != "1", reason + " (NAVCOM_BDD_REQUIRE_STARFORGE=1)"
        context.scenario.skip(reason)
        return
    context.cache_watch = galaxy_world.cache_watch()
    galaxy_world.build(context)
    scratch = str(context.world["scratch"])
    for name in ("HOME", "CODEX_HOME", "CLAUDE_CONFIG_DIR", "NAVCOM_INDEX", "NAVCOM_SPACE_CACHE",
                 "NAVCOM_SOURCES_CACHE", "NAVCOM_HISTORY_CACHE", "NAVCOM_FLEET_CACHE", "HERMES_HOME"):
        assert context.env[name].startswith(scratch), f"{name} escapes the scratch home: {context.env[name]}"


@given("the Orchard design conversation")
def step_design_conversation(context):
    galaxy_world.dated_conversation(context.home, context.workdir)


@given("launchers that record any call")
def step_recorders(context):
    context.env, context.launch_record = galaxy_world.launch_recorders(context.env, context.tmp / "recorders")


@given("the chart has {reference}")
def step_chart_has(context, reference):
    """Skip only when this machine lacks the place's precondition; otherwise a missing place fails.

    A product regression that stops charting the archive or the expert must turn
    the scenario red, never quietly skip it.
    """
    kind = PLACE.search(reference).group(1)
    absent = {"archive": context.world["ships"]["tools"] is None
              and "the owner's ship-commission tools are not installed, so no native archive observation",
              "star": galaxy_world.yaml_interpreter() is None
              and "no Python with PyYAML is available for the fixture Hermes inventory"}.get(kind)
    if absent:
        context.scenario.skip(f"{reference} cannot be charted on this machine: {absent}")
        return
    _resolve(context, reference)


@given("the Orchard suite has a second working copy with its own Lantern commit")
def step_second_copy(context):
    """A linked worktree at ~/work/orchard-mirror, harvested and charted beside the original."""
    galaxy_world.second_copy(context)


@given("the tides gateway is running")
def step_gateway_running(context):
    """A live PID in the profile's gateway.pid: this behave process, alive for the whole step."""
    (context.world["home"] / ".hermes" / "profiles" / "tides" / "gateway.pid").write_text(str(os.getpid()))


@given("the captain's terminal is tmux")
@given("my terminal is tmux")
def step_tmux(context):
    """Make `--launch` and `--tab` pick tmux on any platform; only the recorder answers to that name."""
    recorder = shutil.which("tmux", path=context.env["PATH"])
    assert recorder and Path(recorder).parent == context.launch_record.parent, f"tmux is not a recorder: {recorder}"
    context.env["TMUX"] = f"{context.tmp / 'tmux-socket'},1,0"


# ── When ───────────────────────────────────────────────────────────────────

@when("I run on the chart: navcom {cmdline}")
def step_run_chart(context, cmdline):
    _run(context, shlex.split(_resolve(context, cmdline)))


@when('I run the printed command containing "{marker}"')
def step_run_printed(context, marker):
    marker = _resolve(context, marker)
    lines = [line for line in context.out.splitlines() if marker in line and "navcom " in line]
    assert lines, f"no printed navcom command contains {marker!r}:\n{context.out}"
    _run(context, _navcom_argv(lines[0][lines[0].index("navcom "):]))


@when('I follow the "{field}" of {reference} in that JSON')
def step_follow_place(context, field, reference):
    identity = _resolve(context, reference)
    nodes = [n for n in _json(context).get("nodes", []) if n.get("id") == identity]
    assert len(nodes) == 1 and nodes[0].get(field), f"no {field} for {identity}:\n{context.out[:3000]}"
    _follow(context, nodes[0][field])


@when('I follow the "{field}" of the node labelled "{label}" with: {extra}')
def step_follow_label_with(context, field, label, extra):
    nodes = [n for n in _json(context).get("nodes", []) if n.get("label") == label]
    assert len(nodes) == 1 and nodes[0].get(field), f"no single {label!r} node with {field}:\n{context.out[:3000]}"
    _follow(context, nodes[0][field], shlex.split(extra))


@when('I run the "{field}" of that JSON')
def step_run_field(context, field):
    _follow(context, _field(_json(context), field))


@when('I run the "{field}" of that JSON with "{old}" replaced by "{new}"')
def step_run_field_replaced(context, field, old, new):
    argv = _navcom_argv(_field(_json(context), field))
    assert old in argv, f"{old!r} is not an argument of {argv}"
    _follow(context, ["navcom"] + [new if word == old else word for word in argv])


@when('I launch "{question}" with that review token')
def step_launch_reviewed(context, question):
    """Repeat `atlas ask` with --launch --review, using the token of the first reviewed --json ask.

    The token binds the exact question: launching a different question with it
    must be refused before anything starts.
    """
    if not getattr(context, "review", None):
        interaction = _field(_json(context), "interaction")
        assert interaction.get("state") == "review_required", interaction
        context.review = dict(star=interaction["star_id"], token=interaction["review_token"])
    _run(context, ["atlas", "ask", context.review["star"], question, "--launch", "--review", context.review["token"]])


@when("the Orchard working copy gets a new commit")
def step_new_commit(context):
    repo = context.world["repo"]
    galaxy_world.git(repo, "commit", "-q", "--allow-empty", "-m", "Later Orchard work", date="2025-09-01T00:00:00Z")
    context.world["commits"]["later"] = galaxy_world.git(repo, "rev-parse", "HEAD")


@when("the Orchard working copy and the current chart are deleted")
def step_delete_living(context):
    shutil.rmtree(context.world["repo"])
    Path(context.env["NAVCOM_SPACE_CACHE"]).unlink()
    context.workdir = context.world["home"]  # later commands run from somewhere that still exists


# ── Then ───────────────────────────────────────────────────────────────────

@then('the output shows "{text}"')
def step_shows(context, text):
    text = _resolve(context, text)
    assert text in context.out, f"expected {text!r} in:\n{context.out}"


@then('the output does not show "{text}"')
def step_not_shows(context, text):
    text = _resolve(context, text)
    assert text not in context.out, f"did not expect {text!r} in:\n{context.out}"


@then('the JSON "{path}" is "{value}"')
def step_json_is(context, path, value):
    value = _resolve(context, value)
    actual = _field(_json(context), path)
    assert _text(actual) == value, f"{path} = {actual!r}, expected {value!r}"


@then("the JSON node {reference} is labelled \"{label}\"")
def step_json_node_label(context, reference, label):
    identity = _resolve(context, reference)
    nodes = [n for n in _json(context).get("nodes", []) if n.get("id") == identity]
    assert len(nodes) == 1, f"{identity} is not one node of:\n{context.out[:3000]}"
    assert nodes[0]["label"] == label, f"{identity} is labelled {nodes[0]['label']!r}, expected {label!r}"


@then('the JSON "{path}" is the {which} Orchard commit')
def step_json_commit(context, path, which):
    assert _field(_json(context), path) == context.world["commits"][which]


@then('the place offers the commands "{names}"')
def step_offers(context, names):
    offered = set(_field(_json(context), "center.commands"))
    missing = [name.strip() for name in names.split(",") if name.strip() not in offered]
    assert not missing, f"missing commands {missing}; offered {sorted(offered)}"


@then("the place offers no launch, board or chart refresh command")
def step_offers_no_launch(context):
    """Launching, boarding and chart refresh/harvest follow a printed review; never offered.

    `inspect --refresh` is offered: it repeats a read-only metadata observation.
    """
    offered = _field(_json(context), "center.commands")
    for name, value in offered.items():
        argvs = value if value and isinstance(value[0], list) else [value]
        for argv in argvs:
            assert not {"--launch", "--harvest", "--tab", "--resume"} & set(argv), (name, argv)
            assert argv[1:3] not in (["atlas", "refresh"], ["sources", "harvest"], ["sources", "refresh"]), argv
            assert argv[1:3] != ["atlas", "board"] or "--validate" in argv, argv
            assert "--refresh" not in argv or argv[1:3] == ["atlas", "inspect"], argv
    assert not {"board", "launch", "refresh", "harvest", "maintain"} & set(offered), sorted(offered)


@then("every offered command is pinned to this scenario's caches")
def step_pinned(context):
    scratch = context.world["scratch"]
    flags = {"--space-cache": "NAVCOM_SPACE_CACHE", "--source-cache": "NAVCOM_SOURCES_CACHE",
             "--cache": None, "--index": "NAVCOM_INDEX"}
    for name, value in _field(_json(context), "center.commands").items():
        argvs = value if value and isinstance(value[0], list) else [value]
        for argv in argvs:
            if name == "conversation_search" or not argv:
                continue
            pinned = [(flag, argv[argv.index(flag) + 1]) for flag in flags if flag in argv]
            assert pinned, f"{name} is not pinned to any cache: {argv}"
            for flag, path in pinned:
                resolved = Path(path).resolve()
                assert resolved.is_relative_to(scratch), f"{name} {flag} {path} is outside this scenario"
                if flags[flag]:
                    assert resolved == Path(context.env[flags[flag]]).resolve(), f"{name} {flag} {path}"


@then('the offered "{name}" command runs as printed')
def step_offered_runs(context, name):
    argv = _field(_json(context), "center.commands." + name)
    if argv and isinstance(argv[0], list):
        argv = argv[0]
    _run(context, _navcom_argv(argv))
    assert context.rc == 0, f"rc={context.rc}\n{context.out}\n{context.err}"


@then('the landed files are "{paths}"')
def step_landed_files(context, paths):
    files = [item["path"] for item in _field(_json(context), "files")]
    assert files == [p.strip() for p in paths.split(",")], files


@then("the landed evidence has hits, all inside the landed files")
def step_landed_hits(context):
    data = _json(context)
    allowed = set(data["allowed_paths"])
    hits = data["evidence"]["concept_hits"] + data["evidence"]["text_hits"]
    assert data["evidence"]["concept_hits"] and data["evidence"]["text_hits"], data["evidence"]
    outside = [hit["relative_path"] for hit in hits if hit["relative_path"] not in allowed]
    assert not outside, f"hits outside the landed scope: {outside}"


@then('the committed files are "{paths}"')
def step_committed_files(context, paths):
    files = [item["path"] for item in _field(_json(context), "snapshot.files")]
    assert files == [p.strip() for p in paths.split(",")], files


@then("the revision evidence has hits, all inside the committed files")
def step_revision_hits(context):
    data = _json(context)
    allowed = {item["path"] for item in data["snapshot"]["files"]}
    hits = data["evidence"]["concept_hits"] + data["evidence"]["text_hits"]
    assert data["evidence"]["concept_hits"] and data["evidence"]["text_hits"], data["evidence"]
    assert data["evidence"]["commit"] == data["commit"], (data["evidence"]["commit"], data["commit"])
    outside = [hit["relative_path"] for hit in hits if hit["relative_path"] not in allowed]
    assert not outside, f"hits outside the committed files: {outside}"


@then("the landed evidence has no hits")
@then("the revision evidence has no hits")
def step_landed_no_hits(context):
    evidence = _json(context)["evidence"]
    assert not evidence["concept_hits"] and not evidence["text_hits"], evidence


@then('the harvested sources are "{labels}", all inside this scenario\'s home')
def step_sources(context, labels):
    sources = _field(_json(context), "sources")
    assert sorted(s["label"] for s in sources) == sorted(l.strip() for l in labels.split(",")), sources
    home = context.world["home"]
    outside = [s["root"] for s in sources if not Path(s["root"]).resolve().is_relative_to(home)]
    assert not outside, f"sources outside this scenario: {outside}"


@then('only the source "{label}" carries a conversation collection')
def step_source_collection(context, label):
    carried = {s["label"]: s.get("conversation_collection") for s in _field(_json(context), "sources")}
    assert carried.get(label), f"{label} has no conversation collection: {carried}"
    others = {name: value for name, value in carried.items() if name != label and value}
    assert not others, f"other sources carry a conversation collection: {others}"


@then("no launcher was called")
def step_no_launch(context):
    calls = galaxy_world.launches(context.launch_record)
    assert not calls, "a launcher was started:\n" + "\n".join(calls)


@then('the launcher "{name}" was called with "{text}"')
def step_launched(context, name, text):
    calls = [c for c in galaxy_world.launches(context.launch_record) if c.split(" ", 1)[0] == name]
    assert any(text in call for call in calls), f"{name} calls: {calls}\nstdout:\n{context.out}\nstderr:\n{context.err}"


@then('no launcher but "{name}" was called')
def step_only_launcher(context, name):
    calls = galaxy_world.launches(context.launch_record)
    others = [c for c in calls if c.split(" ", 1)[0] != name]
    assert calls and not others, f"expected only {name}; launched:\n" + "\n".join(calls)


@then("the expert's gateway status was never checked")
@then("the expert's gateway status was checked {count:d} time")
@then("the expert's gateway status was checked {count:d} times")
def step_gateway_checks(context, count=0):
    record = context.world["home"] / ".hermes" / "OBSERVED"
    checks = record.read_text().splitlines() if record.exists() else []
    assert checks == ["tides"] * count, f"gateway status checks: {checks}"


@then("the expert was never started")
def step_expert_idle(context):
    started = context.world["home"] / ".hermes" / "STARTED"
    assert not started.exists(), "the fixture Hermes was started: " + started.read_text()


@then("the owner's real NavCom caches were not touched")
def step_real_caches(context):
    leaks = galaxy_world.real_cache_writes(context.cache_watch, context.world["scratch"])
    assert not leaks, "the owner's real caches were written with this scenario's data:\n" + "\n".join(leaks)
