"""Build a small, real galaxy inside a scenario's throwaway HOME.

Everything is produced by the real CLI against fixture inputs:

- the Orchard suite: a Git repository at the fixture sessions' project folder
  (~/work/proj-alpha) with a declared system, two workspace apps and two dated
  commits, harvested with `navcom sources harvest` (native Starforge) and
  charted with `navcom atlas refresh --space`;
- one Claude conversation in that project whose turns carry explicit dates;
- a Hermes expert profile plus a fixture Hermes install (no model, no network),
  discovered by the same refresh as a star; it records every gateway status
  check (HERMES_HOME/OBSERVED) and any start of Hermes itself (HERMES_HOME/STARTED);
- a Starship fleet snapshot: one remote working ship and, when the owner's
  ship-commission tools are installed, its local stored archive carrying a
  conversation catalog;
- recorders in place of every agent CLI and terminal launcher on PATH, so a
  scenario can prove nothing was started;
- on request (second_copy), a second Git copy of the suite: a linked worktree
  at ~/work/orchard-mirror whose branch has one Lantern commit of its own.

The Orchard repository has the same shape as the unfamiliar dated-landing
fixture (tests/test_historical_landing.py:create_landing_fixture: lantern and
radar "classic" apps with password/identity auth modules) plus a later commit,
so `navcom history system/land` can show what a date excludes.

Every cache (index, chart, sources, history, fleet, Hermes, commission tools)
lives under the scenario's resolved scratch directory. Paths are resolved
because ship/star checks reject any symlinked ancestor (macOS /var -> /private/var).
"""
import functools
import hashlib
import json
import os
import shutil
import socket
import stat
import subprocess
import sys
import time
from pathlib import Path

import fake_home

REAL_HOME = Path(os.path.expanduser("~")).resolve()
INSTALLED_COMMISSION_TOOLS = REAL_HOME / ".codex" / "skills" / "ship-commission" / "scripts"


def real_caches():
    """The owner's default NavCom caches these scenarios must never write.

    The conversation index itself is left out: it is 1-2 GB and other sessions
    legitimately write it all day.
    """
    codex = REAL_HOME / ".codex"
    return ([codex / "navcom-sources", codex / "navcom-history", REAL_HOME / ".cache" / "navcom"]
            + sorted(codex.glob("navcom-index.sqlite.space.json*")))


def starforge_available():
    return bool(os.environ.get("NAVCOM_STARFORGE_PYTHON") or shutil.which("starforge"))


def git(repo, *args, date="2025-03-01T00:00:00Z"):
    env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1",
               GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date)
    return subprocess.run(["git", "-C", str(repo), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
                           "-c", "commit.gpgsign=false", "-c", "core.hooksPath=" + os.devnull, *args],
                          env=env, capture_output=True, text=True, check=True).stdout.strip()


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def _module(name, words):
    """A small Python module whose identifiers give Starforge a clear token group."""
    head = '"""' + " ".join(words) + ' evidence."""\n'
    body = "def " + "_".join(words) + "_" + name + "(identity, token):\n"
    body += "".join(f"    {words[i % len(words)]}_{i} = identity + token + {i}\n" for i in range(24))
    return head + body + f"    return {words[23 % len(words)]}_23\n"


AUTH = ["password", "identity", "authentication", "token", "permission", "credentials", "session", "policy"]
TELEMETRY = ["telemetry", "signal", "sweep", "echo", "antenna", "frequency", "radar", "pulse"]


def legacy_repo(repo):
    """radar-classic: the standalone predecessor of Orchard's Radar app (same name, no system)."""
    repo.mkdir(parents=True, exist_ok=True)
    git(repo, "init", "-q", "-b", "main")
    _write(repo / "package.json", json.dumps(dict(name="radar-classic")))
    _write(repo / "README.md", "# radar-classic\n\nThe original standalone telemetry radar.\n")
    _write(repo / "radar" / "beacon.py", _module("beacon", TELEMETRY))
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "Standalone radar", date="2024-11-01T00:00:00Z")


def orchard_repo(repo, legacy):
    """The Orchard suite: a declared system with two workspace apps and two dated commits."""
    repo.mkdir(parents=True, exist_ok=True)
    git(repo, "init", "-q", "-b", "main")
    _write(repo / ".navcom-space.json", json.dumps(dict(label="Orchard suite", system=dict(id="orchard", label="Orchard tools"))))
    _write(repo / "package.json", json.dumps(dict(name="orchard-suite", workspaces=["apps/*"])))
    _write(repo / "README.md", "# Orchard suite\n\nLantern signs people in; Radar watches the telemetry.\n\n"
           f"Radar replaced the standalone radar at {legacy} (kept for reference).\n")
    for app, words, files in (("lantern", AUTH, ("signin", "tokens", "permissions")),
                              ("radar", TELEMETRY, ("signal", "sweep", "echo"))):
        folder = repo / "apps" / app
        _write(folder / "package.json", json.dumps(dict(name=app + "-classic", scripts=dict(start="python main.py"))))
        _write(folder / "README.md", f"# {app} classic\n\n{' '.join(words[:4]).capitalize()} research.\n")
        for name in files:
            _write(folder / ("auth" if app == "lantern" else "telemetry") / (name + ".py"), _module(name, words))
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "Classic Orchard products")
    classic = git(repo, "rev-parse", "HEAD")
    # A later commit: Lantern is renamed and learns passkeys. Dated views before
    # 2025-06-01 must never show either change.
    _write(repo / "apps" / "lantern" / "package.json", json.dumps(dict(name="lantern-modern", scripts=dict(start="python main.py"))))
    _write(repo / "apps" / "lantern" / "auth" / "passkeys.py", _module("passkeys", AUTH + ["passkey", "webauthn"]))
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "Lantern learns passkeys", date="2025-06-01T00:00:00Z")
    return dict(classic=classic, modern=git(repo, "rev-parse", "HEAD"))


def dated_conversation(home, cwd):
    """One Claude conversation in the Orchard project whose turns carry explicit UTC dates."""
    encoded = str(cwd).replace("/", "-").replace(".", "-").replace("_", "-")
    path = home / ".claude" / "projects" / encoded / "a7c3e1d2-3333-4444-8555-666666666666.jsonl"
    turns = [
        ("2025-03-10T09:00:00Z", "user", "How should orchard login keep amber tokens? orchardamber"),
        ("2025-03-10T09:01:00Z", "assistant", "Keep the amber tokens in the Lantern signin module. orchardamber"),
        ("2025-05-20T09:00:00Z", "user", "Lantern now needs passkeys for orchard login. orchardpasskey"),
        ("2025-05-20T09:01:00Z", "assistant", "Add a passkeys module beside signin. orchardpasskey"),
    ]
    records = []
    for stamp, role, text in turns:
        message = dict(role=role, content=text if role == "user" else [dict(type="text", text=text)])
        records.append(dict(type=role, timestamp=stamp, cwd=str(cwd), sessionId="a7c3e1d2-3333-4444-8555-666666666666",
                            message=message))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records))
    return path


@functools.lru_cache(maxsize=1)
def yaml_interpreter():
    """A Python with PyYAML for the fixture Hermes install (Hermes' own venv has it)."""
    candidates = []
    starforge = shutil.which("starforge")
    if starforge:
        try:
            line = Path(starforge).read_text().splitlines()[0]
            if line.startswith("#!") and len(line[2:].split()) == 1:
                candidates.append(line[2:].strip())
        except (OSError, UnicodeError, IndexError):
            pass
    candidates.append(sys.executable)
    for interpreter in candidates:
        try:
            if subprocess.run([interpreter, "-I", "-c", "import yaml"], capture_output=True, timeout=30).returncode == 0:
                return interpreter
        except (OSError, subprocess.SubprocessError):
            continue
    return None


HERMES_PROFILES = '''"""Fixture Hermes profile API: the subset NavCom's native inventory calls."""
import os
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass
class ProfileInfo:
    name: str
    path: Path
    description: str = ""
    description_auto: bool = False
    distribution_name: str = ""
    distribution_version: str = ""
    distribution_source: str = ""


def _home():
    return Path(os.environ["HERMES_HOME"])


def _get_wrapper_dir():
    return _home() / "bin"


def list_profiles():
    found = []
    root = _home() / "profiles"
    for folder in sorted(root.iterdir()) if root.is_dir() else []:
        meta = folder / "profile.yaml"
        data = (yaml.safe_load(meta.read_text()) if meta.is_file() else {}) or {}
        found.append(ProfileInfo(folder.name, folder, data.get("description", ""), bool(data.get("description_auto", False))))
    return found


def resolve_profile_env(name):
    home = _home()
    return str(home if name == "default" else home / "profiles" / name)


def _check_gateway_running(profile_dir):
    """Fixture gateway status (what `atlas inspect STAR --observe` calls): a live PID in
    the profile's gateway.pid. Every check is recorded in HERMES_HOME/OBSERVED."""
    profile_dir = Path(profile_dir)
    with open(profile_dir.parents[1] / "OBSERVED", "a") as record:
        record.write(profile_dir.name + "\\n")
    try:
        os.kill(int((profile_dir / "gateway.pid").read_text()), 0)
        return True
    except (OSError, ValueError):
        return False
'''


def hermes(home, interpreter):
    """A Hermes expert profile plus a fixture Hermes install (it lists profiles and reports gateway
    status; it never answers)."""
    hermes_home = home / ".hermes"
    profile = hermes_home / "profiles" / "tides"
    _write(profile / "profile.yaml", "description: Maintains estuary tide measurements\n")
    _write(profile / "SOUL.md", "# Estuary researcher\nMaintains measured coastal tide records.\n")
    _write(profile / "config.yaml", "PRIVATE_CONFIGURATION_SENTINEL\n")
    install = hermes_home / "hermes-agent"
    _write(install / "hermes_cli" / "_parser.py", "import argparse\n"
           "PRE_ARGPARSE_INHERITED_FLAGS: list = [('--profile', True)]\n"
           "parser = argparse.ArgumentParser()\nparser.add_argument('--query')\n"
           "def _inherited_flag(parser, *args): pass\n_inherited_flag(parser, '--cli')\n")
    _write(install / "hermes_cli" / "profiles.py", HERMES_PROFILES)
    if interpreter is None:  # No PyYAML anywhere: the star stays undiscovered and its scenario skips.
        interpreter = "/nonexistent/python-with-pyyaml"
    for name in ("hermes_cli/__init__.py", "hermes_constants.py", "toolsets.py", "hermes_cli/oneshot.py"):
        _write(install / name, "# Fixture Hermes install: it never answers questions.\n")
    # Canary: if anything ever starts this Hermes, it leaves a record.
    _write(install / "hermes_cli" / "main.py", "import sys\n\ndef main():\n"
           f"    with open({str(hermes_home / 'STARTED')!r}, 'a') as record:\n"
           "        record.write(' '.join(sys.argv) + '\\n')\n")
    # The launcher finds its install like the real one does, so running it trips the canary.
    launcher = _write(install / "venv" / "bin" / "hermes", "#!/usr/bin/env python3\nimport sys\n"
                      f"sys.path.insert(0, {str(install)!r})\nfrom hermes_cli.main import main\nmain()\n")
    python = _write(install / "venv" / "bin" / "python", f'#!/bin/sh\nexec "{interpreter}" "$@"\n')
    for path in (launcher, python):
        path.chmod(0o700)
    return hermes_home


def carried_catalog(root):
    """A ship's carried conversation catalog, records and handover (Starship's documented layout)."""
    store = root / ".starship" / "secrets" / "navcom"
    sessions = []
    for number, messages in enumerate([
            [(3, "user", "Why did Orchard choose amber storage?"),
             (7, "assistant", "Amber storage preserves the original evidence and recovery trail.")],
            [(2, "assistant", "Next: verify orchard login after restore.")]]):
        identity = f"session-{number}"
        raw = json.dumps(dict(id=identity, provider="fixture",
                              messages=[dict(index=i, role=r, text=t) for i, r, t in messages])).encode()
        path = store / f"fixture-{identity}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        sessions.append(dict(id=identity, provider="fixture", file=str(path.relative_to(root)),
                             sha256=hashlib.sha256(raw).hexdigest(), title="Orchard design",
                             project="/original/orchard", messages=len(messages)))
    _write(root / ".starship" / "navcom" / "index.json", json.dumps(dict(version=1, sessions=sessions)))
    _write(root / ".starship" / "HANDOVER.md", "# Orchard\nRecover amber storage decisions, then verify login.\n")


def fleet(home):
    """Starship's fleet snapshot: one remote working ship and its local commission archive."""
    project = home / "starship"
    record = project / ".starship" / "commission" / "orchard"
    _write(record / "RESULT.json", json.dumps(dict(state="recorded", target="orchard/working")))
    _write(record / "capture" / "receipt.json", json.dumps(dict(state="passed", origin=dict(host=socket.gethostname()))))
    archive = record / "archive"
    manifest = _write(archive / ".starship" / "manifest.json", json.dumps({"repositories": [{"name": "orchard"}]}))
    raw, info = manifest.read_bytes(), manifest.stat()
    _write(archive / ".starship" / "descriptor.json", json.dumps(dict(
        schema=1, repository_count=1, materialized_count=1, manifest_sha256=hashlib.sha256(raw).hexdigest(),
        manifest_size=len(raw), manifest_mtime_ns=info.st_mtime_ns, generated_at=1.0)))
    _write(archive / ".starship" / "seal.json", "{}")
    carried_catalog(archive)
    snapshot = _write(project / "bridge" / "data.json", json.dumps(dict(
        generated="2026-10-01T00:00:00Z", destination="Bertha dock", base="/remote/fleet",
        ships=[dict(id="orchard", name="Orchard", sources=["/recorded/source/orchard"], destination="orchard/working",
                    state="receiving-pass", evidence=".starship/commission/orchard/RESULT.json")])))
    config = _write(project / "fleet.json", json.dumps(dict(ssh_host="remote.example", remote_root="/remote/fleet")))
    tools = None
    if (INSTALLED_COMMISSION_TOOLS / "fleet.py").is_file() and (INSTALLED_COMMISSION_TOOLS / "navcom.py").is_file():
        # A private copy of the owner's installed ship-commission tools: Path.home()
        # is the scratch HOME, and nothing the tools do can reach the original.
        tools = home / ".codex" / "skills" / "ship-commission" / "scripts"
        shutil.copytree(INSTALLED_COMMISSION_TOOLS, tools, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    return dict(snapshot=snapshot, config=config, archive=archive, tools=tools)


# Environment that makes `--tab`/`--launch` pick a real terminal; never inherited.
TERMINAL_HINTS = ("TMUX", "WEZTERM_", "KITTY_", "CMUX_", "TERM_PROGRAM", "ITERM_", "DISPLAY", "WAYLAND_")
# Every agent CLI navcom can resume or revive, plus every terminal/clipboard launcher it can call.
LAUNCHERS = ("claude", "codex", "gemini", "opencode", "kilo", "pi", "omo", "goose", "dsh", "grok", "qwen", "kimi",
             "crush", "copilot", "cline", "cn", "aider", "codewhale", "reasonix", "deepcode", "hermes", "openhands",
             "vibe", "agy", "droid", "cursor-agent", "kiro-cli", "amp", "auggie", "osascript", "open", "cmux", "tmux",
             "wezterm", "kitty", "gnome-terminal", "x-terminal-emulator", "pbcopy", "wl-copy", "xclip", "xsel", "docker")


def launch_recorders(env, folder):
    """Put a recorder first on PATH for every launcher; return the record file."""
    folder.mkdir(parents=True, exist_ok=True)
    record = folder / "launched.log"
    for name in LAUNCHERS:
        shim = folder / name
        shim.write_text("#!/bin/sh\n"
                        f"{{ printf '%s' {name!r}; for arg in \"$@\"; do printf ' %s' \"$arg\"; done; echo; }} >> {str(record)!r}\n"
                        "exit 0\n")
        shim.chmod(0o755)
    env = {k: v for k, v in env.items() if not k.startswith(TERMINAL_HINTS)}
    env["PATH"] = str(folder) + os.pathsep + env.get("PATH", os.defpath)
    return env, record


def launches(record):
    return record.read_text().splitlines() if record.exists() else []


def scratch_env(home):
    """fake_home's isolated environment plus every NavCom cache pointed into scratch."""
    env = fake_home.env_for(home)
    for key in [k for k in env if k.startswith(("HERMES_", "DOCKER_", "STARFORGE") + TERMINAL_HINTS)]:
        env.pop(key)
    if os.environ.get("NAVCOM_STARFORGE_PYTHON"):  # The one NAVCOM_* setting kept: where Starforge lives.
        env["NAVCOM_STARFORGE_PYTHON"] = os.environ["NAVCOM_STARFORGE_PYTHON"]
    env.update({
        "NAVCOM_SPACE_CACHE": str(home / "navcom-space.json"),
        "NAVCOM_SOURCES_CACHE": str(home / "navcom-sources"),
        "NAVCOM_HISTORY_CACHE": str(home / "navcom-history"),
        "NAVCOM_FLEET_CACHE": str(home / "navcom-fleet-archives.json"),
        "NAVCOM_STARSHIP_ROOT": str(home / "starship"),
        "HERMES_HOME": str(home / ".hermes"),
        "DOCKER_CONFIG": str(home / ".docker"),
        "NAVCOM_NO_DAILY": "1",  # Never schedule the daily upkeep job from a scenario.
    })
    return env


def run(navcom, env, args, cwd, timeout=180):
    proc = subprocess.run([sys.executable, navcom] + list(args), capture_output=True, text=True,
                          env=env, cwd=str(cwd), timeout=timeout)
    if proc.returncode or "Traceback" in proc.stderr:
        raise AssertionError(f"fixture command failed: navcom {' '.join(map(str, args))}\n"
                             f"rc={proc.returncode}\n{proc.stdout[-2000:]}\n{proc.stderr[-4000:]}")
    return proc


def build(context):
    """Chart the Orchard galaxy in this scenario's HOME through the real CLI."""
    home = context.home.resolve()
    repo = home / "work" / fake_home.PROJECT
    env = scratch_env(home)
    legacy = home / "work" / "radar-classic"
    legacy_repo(legacy)
    commits = orchard_repo(repo, legacy)
    dated_conversation(home, repo)
    hermes(home, yaml_interpreter())
    ships = fleet(home)
    env["NAVCOM_FLEET_SNAPSHOT"] = str(ships["snapshot"])
    env["NAVCOM_FLEET_CONFIG"] = str(ships["config"])
    context.env = env
    context.home = home
    context.workdir = repo
    context.world = dict(home=home, repo=repo, legacy=legacy, commits=commits, ships=ships, scratch=context.tmp.resolve())
    # Index the fixture conversations, harvest the suite, then publish the chart.
    run(context.navcom, env, ["zebracorn", "-n", "1"], repo)
    run(context.navcom, env, ["sources", "harvest", str(legacy)], repo)
    run(context.navcom, env, ["sources", "harvest", str(repo)], repo)
    run(context.navcom, env, ["atlas", "refresh", "--space"], repo)
    context.chart = json.loads(Path(env["NAVCOM_SPACE_CACHE"]).read_text())
    return context.world


def second_copy(context):
    """Give the Orchard suite a second Git copy: a linked worktree on its own branch.

    The copy's HEAD has one Lantern commit the original lacks, so a place that
    now has two recorded Git copies reads different history from each. It is
    scenario-local (not in build()) because charting it changes every Orchard
    place's locations.
    """
    world = context.world
    repo, mirror = world["repo"], world["home"] / "work" / "orchard-mirror"
    git(repo, "worktree", "add", "-q", str(mirror), "-b", "mirror")
    readme = mirror / "apps" / "lantern" / "README.md"
    readme.write_text(readme.read_text() + "\nMirror-only lantern notes.\n")
    git(mirror, "commit", "-qam", "Mirror-only lantern work", date="2025-07-01T00:00:00Z")
    world["mirror"] = mirror
    world["commits"]["mirror"] = git(mirror, "rev-parse", "HEAD")
    run(context.navcom, context.env, ["sources", "harvest", str(mirror)], repo)
    run(context.navcom, context.env, ["atlas", "refresh", "--space"], repo)
    context.chart = json.loads(Path(context.env["NAVCOM_SPACE_CACHE"]).read_text())
    return mirror


def place(context, kind, label):
    """Exact chart ID for a {kind:label} or {kind:label@parent label} reference.

    `archive` selects a ship's stored copy; `ship` a working ship.
    """
    entities = context.chart["entities"]
    labels = {n["id"]: n["label"] for n in entities}
    label, _, parent = label.partition("@")
    if parent:
        entities = [n for n in entities if labels.get(n.get("parent_id")) == parent]
    if kind == "archive":
        found = [n for n in entities if n["kind"] == "ship" and n.get("form") == "archive" and n["label"] == label]
    elif kind == "ship":
        found = [n for n in entities if n["kind"] == "ship" and n.get("form") != "archive" and n["label"] == label]
    else:
        found = [n for n in entities if n["kind"] == kind and n["label"] == label]
    if len(found) != 1:
        listing = sorted(f"{n['kind']}{'/' + n['form'] if n.get('form') else ''}:{n['label']}" for n in entities)
        raise AssertionError(f"expected exactly one {kind} labelled {label!r}, found {len(found)}; chart has:\n  "
                             + "\n  ".join(listing))
    return found[0]["id"]


def cache_watch():
    """When this scenario started, for the owner's-caches-untouched check."""
    return dict(started=time.time())


def real_cache_writes(watch, scratch):
    """Files in the owner's real caches written since `watch` that mention this scenario.

    The owner's bridge and other sessions may legitimately write these caches
    while the suite runs, so only writes naming this scenario's scratch
    directory (in either macOS spelling) count as leaks.
    """
    needles = {str(scratch).encode(), str(scratch).replace("/private/var/", "/var/", 1).encode()}
    since = watch["started"] - 1
    leaks = []
    for root in real_caches():
        files = [root] if root.is_file() else [Path(folder) / name for folder, _, names in os.walk(root) for name in names]
        for path in files:
            try:
                info = path.lstat()
                if not stat.S_ISREG(info.st_mode) or info.st_mtime < since or info.st_size > 64 * 1024 * 1024:
                    continue
                data = path.read_bytes()
            except OSError:
                continue
            if any(needle in data for needle in needles):
                leaks.append(str(path))
    return leaks
