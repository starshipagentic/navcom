"""The CLI-up law (docs/architecture.md), enforced.

(a) Only navcom.py imports the web adapter, and only inside run() for --menu; no
    service or CLI module names a view file.
(b) navcom.py imports no navcom_* module at import time.
(c) Every route navcom_web.py handles is listed in ROUTES: the one service function
    it calls plus the CLI command proven to reach that same function, or an
    exemption the owner agreed to ('view-state', or 'cli-gap:<line in
    docs/cli-concept-candidates.md>').
(d) No presentation keys in what services return: every route in ROUTES is called
    on a real fixture galaxy (PROBES) and every CLI twin's --json is run on it
    (CLI_JSON), plus a Starforge-free chart with every place kind. The one
    allowed key is evidence search's retrieval style, `query_plan.style`.

Every guard is a plain function that also runs against a deliberately broken copy,
so each test proves the guard can fail as well as that the real tree passes.
"""
import ast
import base64
import importlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import NamedTuple

import fake_home
import pytest

ROOT = Path(__file__).resolve().parent.parent
NAVCOM = str(ROOT / "navcom.py")
MODULES = sorted(ROOT.glob("navcom_*.py")) + [ROOT / "navcom.py"]
WEB = ROOT / "navcom_web.py"
CONCEPTS = ROOT / "docs" / "cli-concept-candidates.md"
VIEW_NAMES = re.compile(r"navcom_space\.(js|css)|navcom_atlas\.(js|css)|navcom_web\.html|navcom_voice\w*\.js|assets/starship")
PRESENTATION = {"color", "colour", "hue", "art_role", "sprite", "icon", "camera", "zoom", "css", "style", "class"}
LAW = ("Every /api route calls one service function that a CLI command also reaches (docs/architecture.md, "
       "'Every route has a CLI twin'). Write the service and its CLI command first, then add the route to ROUTES "
       "in tests/test_architecture.py as a Twin. If the view needs something no CLI can do, add one line to "
       "docs/cli-concept-candidates.md and tag the route 'cli-gap:<that route or line>' for the owner to decide; "
       "never glue it into the adapter or the view.")


# ── (a) and (b): imports and view files ────────────────────────────────────────

def web_imports(source):
    """[(line, enclosing function or None)] for every import of navcom_web in one module."""
    found = []

    def visit(node, function):
        for child in ast.iter_child_nodes(node):
            inner = child.name if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else function
            if isinstance(child, ast.Import) and any(a.name.split(".")[0] == "navcom_web" for a in child.names):
                found.append((child.lineno, function))
            elif isinstance(child, ast.ImportFrom) and (child.module or "").split(".")[0] == "navcom_web":
                found.append((child.lineno, function))
            elif (isinstance(child, ast.Call) and child.args and isinstance(child.args[0], ast.Constant)
                  and child.args[0].value == "navcom_web"
                  and getattr(child.func, "attr", getattr(child.func, "id", "")) in ("import_module", "__import__")):
                found.append((child.lineno, function))
            visit(child, inner)

    visit(ast.parse(source), None)
    return found


def adapter_import_violations(name, source):
    """Why one module's imports of navcom_web break the law (empty when they don't)."""
    if name == "navcom_web.py":
        return []
    if name != "navcom.py":
        return [f"{name}:{line} imports the web adapter; services and CLI modules never do"
                for line, _ in web_imports(source)]
    return [f"navcom.py:{line} imports the web adapter outside run() (only the --menu entry may, lazily)"
            for line, function in web_imports(source) if function != "run"]


def view_literals(source):
    """String literals naming a view file, plus 'assets' / 'starship' path joins."""
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and VIEW_NAMES.search(node.value):
            found.append((node.lineno, node.value[:80]))
        if (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div) and isinstance(node.right, ast.Constant)
                and node.right.value == "starship" and isinstance(node.left, ast.BinOp)
                and isinstance(node.left.right, ast.Constant) and node.left.right.value == "assets"):
            found.append((node.lineno, "assets/starship"))
    return found


def import_time_navcom_imports(source):
    """navcom_* modules a module imports while it is being imported (outside every function body)."""
    found = []

    def visit(node):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                continue
            if isinstance(child, ast.Import):
                found.extend(a.name for a in child.names if a.name.startswith("navcom_"))
            elif isinstance(child, ast.ImportFrom) and (child.module or "").startswith("navcom_"):
                found.append(child.module)
            visit(child)

    visit(ast.parse(source))
    return found


def test_only_the_menu_entry_imports_the_web_adapter():
    problems = [p for path in MODULES for p in adapter_import_violations(path.name, path.read_text())]
    assert problems == [], "\n".join(problems)
    assert [function for _, function in web_imports((ROOT / "navcom.py").read_text())] == ["run"]


def test_adapter_import_guard_fails_on_broken_modules():
    assert adapter_import_violations("navcom_space.py", "import json\nimport navcom_web\n")
    assert adapter_import_violations("navcom_space.py", "def view():\n    from navcom_web import WebApp\n")
    assert adapter_import_violations("navcom_atlas_cli.py", "import importlib\nweb = importlib.import_module('navcom_web')\n")
    assert adapter_import_violations("navcom.py", "import navcom_web\n")
    assert adapter_import_violations("navcom.py", "def cmd_where():\n    import navcom_web\n")
    assert not adapter_import_violations("navcom.py", "def run():\n    import navcom_web\n")


def test_no_service_or_cli_module_names_a_view_file():
    found = {path.name: view_literals(path.read_text()) for path in MODULES if path != WEB}
    assert {name: hits for name, hits in found.items() if hits} == {}
    assert view_literals(WEB.read_text())  # the adapter's static routes are the one place that serves them


@pytest.mark.parametrize("broken", [
    "PAGE = Path(__file__).with_name('navcom_space.js')",
    "STYLE = 'navcom_atlas.css'",
    "SHELL = open('navcom_web.html').read()",
    "WORKLET = 'navcom_voice_worklet.js'",
    "ART = Path(__file__).parent / 'assets' / 'starship' / 'ship.png'",
    "ART = 'assets/starship/ship.png'",
], ids=["space-js", "atlas-css", "web-html", "voice-js", "sprite-join", "sprite-literal"])
def test_view_file_guard_fails_on_a_service_that_reads_the_view(broken):
    source = (ROOT / "navcom_space.py").read_text() + "\n" + broken + "\n"
    assert view_literals(source)


def test_navcom_imports_no_service_module_at_import_time():
    assert import_time_navcom_imports((ROOT / "navcom.py").read_text()) == []


def test_import_time_guard_fails_on_a_module_level_service_import():
    source = (ROOT / "navcom.py").read_text()
    assert import_time_navcom_imports(source + "\nimport navcom_space\n") == ["navcom_space"]
    assert import_time_navcom_imports(source + "\ntry:\n    from navcom_web import serve\nexcept ImportError:\n    pass\n") == ["navcom_web"]
    assert import_time_navcom_imports(source + "\nclass Lazy:\n    import navcom_atlas_cli\n") == ["navcom_atlas_cli"]


# ── (c): every route has a CLI twin ────────────────────────────────────────────

class Twin(NamedTuple):
    service: str   # dotted path of the service callable the route calls
    cli: list      # a CLI argv that reaches the same callable ({ref}, {dead}, {wav} filled per run)
    web: dict      # GET params or POST body that pass the route's validation


STATIC = ("/", "/navcom_atlas.js", "/navcom_atlas.css", "/navcom_space.js", "/navcom_space.css",
          "/navcom_voice.js", "/navcom_voice_worklet.js", "/assets/starship/")
VIEW_STATE = {"GET " + path for path in STATIC} | {"GET /api/state", "POST /api/state", "GET /api/task",
                                                     "POST /api/space/refresh/pause"}
PLACE, SHIP, STAR = "planet:fixture", "ship:fixture", "star:fixture"

ROUTES = {
    **{route: "view-state" for route in VIEW_STATE},
    "GET /api/recent": "cli-gap:GET /api/recent",
    "GET /api/status": "cli-gap:GET /api/status",
    "GET /api/session": "cli-gap:GET /api/session",
    "POST /api/suggest": "cli-gap:POST /api/suggest",
    "POST /api/annotation": "cli-gap:POST /api/annotation",
    "GET /api/voice": Twin("navcom_voice.status", ["voice", "status"], {}),
    "POST /api/voice": Twin("navcom_voice.transcribe", ["voice", "transcribe", "{wav}"],
                            {"audio": base64.b64encode(b"RIFF0000WAVE").decode()}),
    "GET /api/space": Twin("navcom_navigation.view", ["atlas", "explore", "galaxy:owner"], {"within": ["galaxy:owner"]}),
    "GET /api/navigate": Twin("navcom_navigation.navigate", ["atlas", "navigate", "fly", "to", "Coast"], {"q": ["fly to Coast"]}),
    "GET /api/space/inspect": Twin("navcom_navigation.inspect", ["atlas", "inspect", PLACE], {"within": [PLACE]}),
    "GET /api/space/context": Twin("navcom_navigation.context", ["atlas", "context", SHIP], {"within": [SHIP]}),
    "GET /api/space/files": Twin("navcom_place_files.files", ["atlas", "files", PLACE], {"within": [PLACE]}),
    "GET /api/space/related": Twin("navcom_relationships.related", ["atlas", "related", PLACE], {"within": [PLACE]}),
    "POST /api/space/ask": Twin("navcom_navigation.interact", ["atlas", "ask", STAR, "where is calibration?"],
                                {"within": STAR, "question": "where is calibration?"}),
    "POST /api/space/board": Twin("navcom_navigation.interact", ["atlas", "board", SHIP], {"within": SHIP}),
    "POST /api/space/refresh": Twin("navcom_chart_refresh.drive", ["atlas", "refresh", "--space", "--harvest"], {}),
    "GET /api/atlas": Twin("navcom_discovery.Discovery.view", ["atlas", "list", "projects"], {"grouping": ["projects"]}),
    "GET /api/sources": Twin("navcom_sources.sources_list", ["sources", "list"], {}),
    "GET /api/sources/search": Twin("navcom_sources.search", ["sources", "search", "login", "--within", "fixture", "--path", "src"],
                                    {"q": ["login"], "within": ["fixture"], "path": ["src"]}),
    "GET /api/source": Twin("navcom_source_reader.read_source", ["sources", "read", "fixture", "README.md"],
                            {"source": ["fixture"], "path": ["README.md"]}),
    "GET /api/history": Twin("navcom_history.view", ["history", "timeline", PLACE, "--repo", "/tmp", "--include", "src"],
                             {"within": [PLACE], "repo": ["/tmp"], "include": ["src"]}),
    "POST /api/history/explore": Twin("navcom_history.view", ["history", "explore", PLACE, "abc1234"],
                                      {"within": PLACE, "revision": "abc1234"}),
    "POST /api/history/system": Twin("navcom_system_history.view", ["history", "system", "galaxy:owner", "--at", "2026-09-01"],
                                     {"within": "galaxy:owner", "at": "2026-09-01"}),
    "POST /api/history/land": Twin("navcom_historical_landing.landing",
                                   ["history", "land", PLACE, "--cursor", "c" * 16, "--result-key", "k" * 16],
                                   {"within": PLACE, "cursor": "c" * 16, "result_key": "k" * 16}),
    "GET /api/history/conversations": Twin("navcom_historical_conversations.view",
                                           ["history", "conversations", PLACE, "--at", "2026-09-01"],
                                           {"within": [PLACE], "at": ["2026-09-01"]}),
    "GET /api/recap": Twin("navcom.session_recap", ["--recap", "{ref}"], {"key": ["{key}"]}),
    "GET /api/session/search": Twin("navcom.search_hits", ["cognito", "--file", "{ref}"], {"key": ["{key}"], "q": ["cognito"]}),
    "GET /api/harnesses": Twin("navcom.fresh_harnesses", ["--resume", "{dead}", "--print"], {"provider": ["pi"]}),
    "GET /api/plan": [Twin("navcom.resume_plan", ["--resume", "{ref}", "--print"], {"key": ["{key}"]}),
                      Twin("navcom.revive_plan", ["--resume", "{ref}:2", "--with", "claude", "--print"],
                           {"key": ["{key}"], "harness": ["claude"], "turn": ["2"]})],
    "POST /api/launch": Twin("navcom.prepare_launch", ["--resume", "{ref}", "--tab"], {"key": "{key}"}),
    "POST /api/upkeep": Twin("navcom.maintain", ["--maintain"], {}),
}
TWINS = [(route, twin) for route, entry in ROUTES.items() if not isinstance(entry, str)
         for twin in (entry if isinstance(entry, list) else [entry])]


def handled_routes(source):
    """{'GET /api/x', 'POST /api/y', ...}: every literal the adapter compares a request path with."""
    methods = {"get": "GET", "do_GET": "GET", "post": "POST", "do_POST": "POST"}
    found = set()

    def literals(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return [node.value]
        if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
            return [value for item in node.elts for value in literals(item)]
        return []

    def is_path(node):
        return (isinstance(node, ast.Name) and node.id == "route") or (isinstance(node, ast.Attribute) and node.attr == "path")

    def visit(node, method):
        for child in ast.iter_child_nodes(node):
            inner = methods.get(child.name, method) if isinstance(child, ast.FunctionDef) else method
            if method and isinstance(child, ast.Compare) and is_path(child.left):
                for op, right in zip(child.ops, child.comparators):
                    if isinstance(op, (ast.Eq, ast.In)):
                        found.update(f"{method} {value}" for value in literals(right) if value.startswith("/"))
            if (method and isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute)
                    and child.func.attr == "startswith" and is_path(child.func.value)):
                found.update(f"{method} {value}" for arg in child.args for value in literals(arg) if value.startswith("/"))
            visit(child, inner)

    visit(ast.parse(source), None)
    return found


def route_violations(source, table, concepts):
    """Why the adapter's routes and the table disagree with the law (empty when they agree)."""
    handled = handled_routes(source)
    anchors = [line for line in concepts.splitlines() if line.lstrip().startswith(("|", "#"))]
    paths = {route.split(" ", 1)[1] for route in handled}
    stray = sorted({node.value for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Constant)
                    and isinstance(node.value, str) and node.value.startswith("/api/")} - paths)
    problems = [f"{path} appears in navcom_web.py but is not compared with the request path as `route == ...`, "
                f"so this test cannot check it. {LAW}" for path in stray]
    problems += [f"{route} has no entry in ROUTES. {LAW}" for route in sorted(handled - set(table))]
    problems += [f"{route} is in ROUTES but navcom_web.py no longer handles it; remove the entry."
                 for route in sorted(set(table) - handled)]
    for route, entry in sorted(table.items(), key=lambda item: item[0]):
        if entry == "view-state" and route not in VIEW_STATE:
            problems.append(f"{route} is tagged view-state, but only the browser's own state, task progress, the "
                            f"refresh pause and static files are exempt by design. {LAW}")
        elif isinstance(entry, str) and entry.startswith("cli-gap:"):
            anchor = entry.removeprefix("cli-gap:")
            if not any(f"`{anchor}`" in line for line in anchors):
                problems.append(f"{route}: cli-gap anchor `{anchor}` is not a heading or table row in "
                                f"docs/cli-concept-candidates.md. {LAW}")
        elif isinstance(entry, str) and entry != "view-state":
            problems.append(f"{route}: {entry!r} is not a Twin, 'view-state' or 'cli-gap:<anchor>'. {LAW}")
    return problems


def test_every_route_has_a_cli_twin_or_an_agreed_exemption():
    assert route_violations(WEB.read_text(), ROUTES, CONCEPTS.read_text()) == []
    assert len(handled_routes(WEB.read_text())) == len(ROUTES)


def test_route_guard_fails_on_a_new_route_without_a_twin():
    source = WEB.read_text().replace("        if route == '/api/task':",
                                     "        if route == '/api/glue':\n            return {}\n        if route == '/api/task':", 1)
    problems = route_violations(source, ROUTES, CONCEPTS.read_text())
    assert problems == [f"GET /api/glue has no entry in ROUTES. {LAW}"]
    laundered = dict(ROUTES, **{"GET /api/glue": "view-state"})
    assert "only the browser's own state" in route_violations(source, laundered, CONCEPTS.read_text())[0]
    unanchored = dict(ROUTES, **{"GET /api/glue": "cli-gap:GET /api/glue"})
    assert "not a heading or table row" in route_violations(source, unanchored, CONCEPTS.read_text())[0]
    hidden = WEB.read_text().replace("        if route == '/api/task':",
                                     "        if request_path == '/api/hidden':\n            return {}\n        if route == '/api/task':", 1)
    assert "/api/hidden appears in navcom_web.py but is not compared" in route_violations(hidden, ROUTES, CONCEPTS.read_text())[0]
    removed = WEB.read_text().replace("if route == '/api/recap':", "if route == '/api/recap-renamed':", 1)
    assert any("GET /api/recap is in ROUTES but" in p for p in route_violations(removed, ROUTES, CONCEPTS.read_text()))


@pytest.fixture(scope="module")
def home(tmp_path_factory):
    """A throwaway HOME with one session per harness, indexed; the pi session's file is then deleted."""
    home = tmp_path_factory.mktemp("law") / "home"
    sessions, workdir = fake_home.build(home)
    env = fake_home.env_for(home)
    subprocess.run([sys.executable, NAVCOM, "--maintain"], env=env, cwd=workdir, check=True,
                   capture_output=True, timeout=120)
    Path(sessions["pi"]).unlink()  # its harness can no longer reopen it, so --resume offers fresh harnesses
    wav = home / "clip.wav"
    wav.write_bytes(b"RIFF0000WAVE")
    import sqlite3
    with sqlite3.connect(env["NAVCOM_INDEX"]) as conn:
        key = next(f for (f,) in conn.execute("SELECT file FROM file_state") if f.endswith("eeeeeeeeeeee.jsonl"))
    return dict(env=env, workdir=workdir, index=Path(env["NAVCOM_INDEX"]),
                fill=dict(ref="eeeeeeeeeeee", dead="123456789abc", wav=str(wav), key=key))


PROOF = r"""
import importlib, os, sys
root, target, argv = sys.argv[1], sys.argv[2], sys.argv[3:]
sys.path.insert(0, root)
import navcom
module, *attrs = target.split(".")
owner = importlib.import_module(module)
for attr in attrs[:-1]:
    owner = getattr(owner, attr)
getattr(owner, attrs[-1])  # the service must exist under this name
setattr(owner, attrs[-1], lambda *args, **kwargs: os._exit(77))
sys.exit(navcom.run(argv))
"""


def cli_reaches(home, service, argv):
    """Run the CLI in a subprocess under the throwaway HOME; exit 77 means it called `service`."""
    argv = [part.format(**home["fill"]) for part in argv]
    proc = subprocess.run([sys.executable, "-c", PROOF, str(ROOT), service, *argv], env=home["env"],
                          cwd=home["workdir"], stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=120)
    return proc.returncode == 77, proc


class Reached(Exception):
    pass


def web_reaches(navcom, home, monkeypatch, route, service, request):
    """Call the adapter in-process with `service` replaced; True when the route called it."""
    from navcom_web import WebApp
    for name in set(os.environ) - set(home["env"]):
        monkeypatch.delenv(name)
    for name, value in home["env"].items():
        monkeypatch.setenv(name, value)
    module, *attrs = service.split(".")
    owner = navcom if module == "navcom" else importlib.import_module(module)
    for attr in attrs[:-1]:
        owner = getattr(owner, attr)
    calls = []

    def reached(*args, **kwargs):
        calls.append(args)
        raise Reached(service)

    monkeypatch.setattr(owner, attrs[-1], reached)
    fill = lambda value: value.format(**home["fill"]) if isinstance(value, str) else [fill(v) for v in value]
    request = {name: fill(value) for name, value in request.items()}
    app = WebApp(navcom, home["index"])
    method, path = route.split(" ", 1)
    conn = app.connect()
    try:
        (app.post if method == "POST" else app.get)(conn, path, request)
    except Exception:  # Reached, or the route failed before calling the service: `calls` decides
        pass
    finally:
        conn.close()
    deadline = time.monotonic() + 10
    while app.task.get("running") and time.monotonic() < deadline:  # Upkeep and chart refresh run in a thread
        time.sleep(.02)
    return bool(calls)


@pytest.mark.parametrize("route,twin", TWINS, ids=[f"{route}->{twin.service}" for route, twin in TWINS])
def test_each_cli_twin_reaches_the_routes_service(home, route, twin):
    reached, proc = cli_reaches(home, twin.service, twin.cli)
    assert reached, (f"`navcom {' '.join(twin.cli)}` did not call {twin.service} (exit {proc.returncode}). {LAW}\n"
                     + proc.stderr[-1500:])


@pytest.mark.parametrize("route,twin", TWINS, ids=[f"{route}->{twin.service}" for route, twin in TWINS])
def test_each_route_calls_its_service(navcom, home, monkeypatch, route, twin):
    assert web_reaches(navcom, home, monkeypatch, route, twin.service, twin.web), f"{route} did not call {twin.service}. {LAW}"


def test_parity_proof_fails_when_the_cli_or_route_reaches_another_function(navcom, home, monkeypatch):
    assert not cli_reaches(home, "navcom_navigation.inspect", ["atlas", "files", PLACE])[0]
    assert not cli_reaches(home, "navcom.session_recap", ["--resume", "{ref}", "--print"])[0]
    assert not web_reaches(navcom, home, monkeypatch, "GET /api/space/files", "navcom_navigation.inspect", {"within": [PLACE]})


# ── (d): no presentation keys in service output ────────────────────────────────

# The one presentation-sounding key that is data: evidence search's retrieval style
# (navcom_navigation.evidence `query_plan.style`, 'literal' or 'question'; the CLI and
# the view both branch on it). Allowed only under query_plan and only with those values.
ALLOWED = {("query_plan", "style"): {"literal", "question"}}


def presentation_keys(value, path="$", parent=None):
    """JSON paths of every key that names styling, art or camera state."""
    found = []
    if isinstance(value, dict):
        for key, item in value.items():
            name = str(key).lower()
            if name in PRESENTATION and not (isinstance(item, str) and item in ALLOWED.get((parent, name), ())):
                found.append(f"{path}.{key}")
            found += presentation_keys(item, f"{path}.{key}", str(key))
    elif isinstance(value, (list, tuple)):
        for i, item in enumerate(value):
            found += presentation_keys(item, f"{path}[{i}]", parent)
    return found


def test_the_retrieval_style_exemption_is_narrow():
    assert presentation_keys({"evidence": {"query_plan": {"style": "question", "text_terms": []}}}) == []
    assert presentation_keys({"query_plan": {"style": "color: red"}}) == ["$.query_plan.style"]
    assert presentation_keys({"query_plan": {"style": {"literal": 1}}}) == ["$.query_plan.style"]
    assert presentation_keys({"nodes": [{"style": "literal"}]}) == ["$.nodes[0].style"]
    assert presentation_keys({"query_plan": {"color": "literal"}}) == ["$.query_plan.color"]


def galaxy(tmp_path, monkeypatch):
    """A chart with every place kind: system, planets, a moon, a district, a star, a starbase and a ship."""
    import navcom_space
    import navcom_stars
    from test_space import API, database, git, package, source_cache, star_record
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "no-native-profiles"))
    for name in ("NAVCOM_FLEET_SNAPSHOT", "NAVCOM_FLEET_CONFIG", "NAVCOM_FLEET_CACHE"):
        monkeypatch.delenv(name, raising=False)
    suite = git(tmp_path / "clients" / "Arbor" / "suite")
    package(suite, name="suite", workspaces=["apps/*"])
    coast = package(suite / "apps" / "coast", name="Coastal measurements", scripts={"start": "node app.js"})
    inland = package(suite / "apps" / "inland", name="Inland measurements", scripts={"dev": "vite"})
    lab = coast / "LABS" / "tide-experiment"
    lab.mkdir(parents=True)
    groups = [dict(paths=["apps/coast/auth/login.ts", "apps/coast/auth/policy.ts"],
                   shared_tokens=["authentication", "policy"], cohesion=.5)]
    sources = source_cache(tmp_path, [suite], groups)
    bridge = tmp_path / "starship" / "bridge"
    bridge.mkdir(parents=True)
    (bridge / "data.json").write_text(json.dumps(dict(
        base="/Volumes/TestFleet", destination="Archive base", generated="2026-10-01",
        ships=[dict(name="Context vessel", sources=[str(coast)], destination="ships/context", state="passed")])))
    monkeypatch.setenv("NAVCOM_STARSHIP_ROOT", str(bridge.parent))
    monkeypatch.setattr(navcom_stars, "discover", lambda *a, **k: dict(
        candidates=[star_record(coast)], coverage=dict(complete=True), gaps=[], excluded=[],
        observed_at=1234, fingerprint="fixture", cache_hit=True))
    conn = database([(suite, "Suite setup"), (coast, "Tidal calibration"), (inland, "Inland login"), (lab, "Tide benchmark")])
    cache = tmp_path / "space.json"
    data = navcom_space.refresh(API, conn, cache, source_cache=sources)
    conn.close()
    return cache, sources, data, bridge / "data.json"


def service_outputs(navcom, tmp_path, monkeypatch):
    """Every read the CLI and the bridge share, on one fixture chart, fleet and conversation index."""
    import navcom_fleet
    import navcom_navigation as navigation
    import navcom_space
    from navcom_discovery import Discovery, refresh
    from test_atlas import add
    cache, sources, data, snapshot = galaxy(tmp_path, monkeypatch)
    kinds = {node["kind"] for node in data["entities"]}
    assert {"galaxy", "system", "planet", "moon", "district", "star", "starbase", "ship"} <= kinds
    view = lambda **kw: navigation.view(None, None, space_cache=cache, source_cache=sources, **kw)
    outputs = {"refresh": data}
    for node in data["entities"]:
        for action in ("show", "explore"):
            outputs[f"{action} {node['id']}"] = view(action=action, within=node["id"])
    for plural in navcom_space.KINDS:
        outputs[f"list {plural}"] = view(action="list", kind=plural)
    outputs["search"] = view(action="search", query="tidal")
    outputs["navigate"] = navigation.navigate(None, None, space_cache=cache, source_cache=sources, text="fly to Coastal measurements")
    outputs["fleet"] = navcom_fleet.read_fleet(snapshot)
    monkeypatch.setattr(navcom, "INDEX_READ_ONLY", False)
    index = tmp_path / "index.sqlite"
    conn = navcom.open_index(index)
    parent = add(navcom, conn, tmp_path / "main.jsonl", "Main experiment", "model benchmark v4 listener", "/dev/new-research")
    add(navcom, conn, tmp_path / "child.jsonl", "Child task", "uniqueword zebracorn", "/dev/new-research/worktree", parent="main")
    refresh(conn)
    discovery = Discovery(navcom)
    for grouping in ("projects", "research", "topics", "districts", "time"):
        outputs[f"discovery {grouping}"] = discovery.view(conn, {"grouping": [grouping]})
    outputs["discovery search"] = discovery.view(conn, {"action": ["search"], "q": ["zebracorn"]})
    outputs["discovery tree"] = discovery.view(conn, {"action": ["tree"], "ref": ["child"]})
    conn.close()
    planet = next(node["id"] for node in data["entities"] if node["kind"] == "planet")
    for argv in (["list", "planets"], ["explore", "galaxy:owner"], ["show", planet], ["list", "projects"]):
        proc = subprocess.run([sys.executable, NAVCOM, "atlas", *argv, "--space-cache", str(cache), "--source-cache", str(sources),
                               "--index", str(index), "--json"] if argv[-1] != "projects" else
                              [sys.executable, NAVCOM, "atlas", *argv, "--index", str(index), "--json"],
                              capture_output=True, text=True, timeout=120,
                              env=dict(os.environ, NAVCOM_STARSHIP_ROOT=str(snapshot.parent.parent)))
        assert proc.returncode == 0, proc.stderr
        outputs["cli atlas " + " ".join(argv)] = json.loads(proc.stdout)
    return outputs, parent


def test_service_and_cli_json_carry_no_presentation_keys(navcom, tmp_path, monkeypatch):
    outputs, parent = service_outputs(navcom, tmp_path, monkeypatch)
    assert outputs["discovery tree"]["nodes"][0]["key"] == parent  # the fixture really produced conversations
    assert any("position" in node for node in outputs["refresh"]["entities"])  # durable chart data stays allowed
    found = {name: keys[:5] for name, output in outputs.items() if (keys := presentation_keys(output))}
    assert found == {}, ("Presentation leaked into service output; the view picks colors, sprites and camera "
                         f"from kind and form (docs/architecture.md): {found}")


def test_presentation_guard_fails_on_a_service_that_names_a_sprite(navcom, tmp_path, monkeypatch):
    import navcom_navigation as navigation
    import navcom_space
    cache, sources, data, _ = galaxy(tmp_path, monkeypatch)
    original = navcom_space.load_catalog

    def decorated(*args, **kwargs):
        catalog = original(*args, **kwargs)
        for node in catalog["entities"]:
            node["sprite"] = "ship.png"
        return catalog

    monkeypatch.setattr(navcom_space, "load_catalog", decorated)
    result = navigation.view(None, None, space_cache=cache, source_cache=sources, action="list", kind="planets")
    assert presentation_keys(result)
    assert presentation_keys({"nodes": [{"id": "x", "camera": {"zoom": 2}}]}) == ["$.nodes[0].camera", "$.nodes[0].camera.zoom"]


# ── (d) on every route and every CLI twin: the Orchard world ──────────────────
#
# features/support/galaxy_world.py builds the BDD galaxy in a throwaway HOME with
# the real CLI: a Git repository with two dated commits, a native Starforge
# harvest, a chart with a system, planets, districts, a star, a working ship and
# its stored archive, plus one session per harness. Every route the adapter
# serves is called on it (PROBES), and every CLI twin that prints --json is run
# on it (CLI_JSON), so a presentation key in any service's real output fails.

def silent_wav():
    import io
    import wave
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as stream:
        stream.setnchannels(1), stream.setsampwidth(2), stream.setframerate(16000)
        stream.writeframes(b"\0\0" * 3200)  # 0.2 s of digital silence: transcribed without a model
    return buffer.getvalue()


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    import galaxy_world
    from types import SimpleNamespace
    if not galaxy_world.starforge_available():
        pytest.skip("native Starforge is needed to harvest and chart the fixture galaxy")
    tmp = tmp_path_factory.mktemp("world").resolve()
    context = SimpleNamespace(home=tmp / "home", tmp=tmp, navcom=NAVCOM)
    fake_home.build(context.home)
    galaxy_world.build(context)
    env, launched = galaxy_world.launch_recorders(context.env, tmp / "launchers")
    place = lambda kind, label: galaxy_world.place(context, kind, label)
    cli = lambda *argv: json.loads(galaxy_world.run(NAVCOM, env, [*argv, "--json"], context.workdir).stdout)
    names = dict(lantern=place("planet", "lantern-modern"), suite=place("planet", "Orchard suite"),
                 system=place("system", "Orchard tools"), ship=place("ship", "Orchard"),
                 archive=place("archive", "Orchard · archive"), star=place("star", "tides"),
                 district=place("district", "passkeys · permissions · signin (4 files)"),
                 classic=context.world["commits"]["classic"], ref="eeeeeeeeeeee")
    names["source"] = next(s["id"] for s in cli("sources", "list")["sources"] if Path(s["root"]) == context.workdir)
    dated = cli("history", "system", names["system"], "--at", "2025-04-01")  # a dated journey, as its user starts one
    names.update(cursor=dated["cursor"], result_key=dated["result_key"])
    landed = cli("history", "land", names["lantern"], "--cursor", names["cursor"], "--result-key", names["result_key"])
    names["group"] = next(n["id"] for n in landed["nodes"] if n["kind"] == "district")
    wav = tmp / "silence.wav"
    wav.write_bytes(silent_wav())
    names.update(wav=str(wav), silence=base64.b64encode(wav.read_bytes()).decode())
    import sqlite3
    with sqlite3.connect(env["NAVCOM_INDEX"]) as conn:
        names["key"] = next(f for (f,) in conn.execute("SELECT file FROM file_state") if f.endswith("eeeeeeeeeeee.jsonl"))
    return dict(env=env, workdir=context.workdir, index=Path(env["NAVCOM_INDEX"]), launched=launched, names=names)


def fill(value, names):
    """Replace {name} placeholders in a probe's strings, lists and dicts."""
    if isinstance(value, str):
        return value.format(**names)
    if isinstance(value, list):
        return [fill(item, names) for item in value]
    if isinstance(value, dict):
        return {key: fill(item, names) for key, item in value.items()}
    return value


LANDING = {"within": "{lantern}", "cursor": "{cursor}", "result_key": "{result_key}"}
PROBES = {  # every non-view-state route: the requests the cockpit sends (GET params are lists, POST bodies are JSON)
    "GET /api/voice": [{}],
    "POST /api/voice": [{"audio": "{silence}"}],
    "GET /api/space": [{"within": ["{lantern}"]}, {"action": ["list"], "kind": ["ships"]},
                       {"action": ["search"], "q": ["password"], "within": ["{lantern}"], "evidence": ["1"]}],
    "GET /api/navigate": [{"q": ["fly to lantern-modern"]}, {"q": ["find password"], "within": ["{lantern}"]}],
    "GET /api/space/inspect": [{"within": ["{lantern}"]}, {"within": ["{archive}"]}, {"within": ["{star}"]}],
    "GET /api/space/context": [{"within": ["{archive}"]}, {"within": ["{archive}"], "action": ["search"], "q": ["amber"]}],
    "GET /api/space/files": [{"within": ["{lantern}"]}, {"within": ["{district}"], "q": ["tokens"]}],
    "GET /api/space/related": [{"within": ["{suite}"]}],
    "POST /api/space/ask": [{"within": "{star}", "question": "What do the tide records say?"}],
    "POST /api/space/board": [{"within": "{ship}", "validate": True}, {"within": "{archive}"}],
    "GET /api/atlas": [{"grouping": ["projects"]}, {"grouping": ["topics"]}, {"action": ["search"], "q": ["zebracorn"]}],
    "GET /api/sources": [{}],
    "GET /api/sources/search": [{"q": ["password"], "within": ["{source}"]}],
    "GET /api/source": [{"source": ["{source}"], "path": ["apps/lantern/auth/tokens.py"]}],
    "GET /api/history": [{"within": ["{lantern}"]}],
    "POST /api/history/explore": [{"within": "{lantern}", "revision": "{classic}", "q": "password"}],
    "POST /api/history/system": [{"within": "{system}", "at": "2025-04-01"}],
    "POST /api/history/land": [LANDING, dict(LANDING, group="{group}", q="password")],
    "GET /api/history/conversations": [{"within": ["{suite}"], "at": ["2025-04-01"], "q": ["orchard login"]}],
    "GET /api/recap": [{"key": ["{key}"]}],
    "GET /api/session/search": [{"key": ["{key}"], "q": ["cognito"]}],
    "GET /api/harnesses": [{"provider": ["pi"]}],
    "GET /api/plan": [{"key": ["{key}"]}, {"key": ["{key}"], "harness": ["claude"], "turn": ["2"]}],
    "POST /api/launch": [{"key": "{key}"}],
    "POST /api/annotation": [{"key": "{key}", "name": "Cognito fix", "note": "Stopped at the login test.", "favorite": True}],
    "GET /api/recent": [{}, {"q": ["cognito"]}],
    "GET /api/status": [{}],
    "GET /api/session": [{"key": ["{key}"]}],
    "POST /api/suggest": [{"key": "{key}"}],
    "POST /api/upkeep": [{}],
    "POST /api/space/refresh": [{}],  # last: it re-charts the world (addresses are durable)
}
BACKGROUND = {"POST /api/upkeep", "POST /api/space/refresh"}  # the route starts a task; its result lands in /api/task

CLI_JSON = {  # every Twin whose CLI prints --json: the commands that print the route's service result
    "GET /api/voice": [["voice", "status"]],
    "POST /api/voice": [["voice", "transcribe", "{wav}"]],
    "GET /api/space": [["atlas", "explore", "{lantern}"], ["atlas", "list", "ships"],
                       ["atlas", "search", "password", "--within", "{lantern}", "--evidence"]],
    "GET /api/navigate": [["atlas", "navigate", "fly", "to", "lantern-modern"]],
    "GET /api/space/inspect": [["atlas", "inspect", "{lantern}"], ["atlas", "inspect", "{star}"]],
    "GET /api/space/context": [["atlas", "context", "{archive}", "--query", "amber"]],
    "GET /api/space/files": [["atlas", "files", "{district}", "--query", "tokens"]],
    "GET /api/space/related": [["atlas", "related", "{suite}"]],
    "POST /api/space/ask": [["atlas", "ask", "{star}", "What do the tide records say?"]],
    "POST /api/space/board": [["atlas", "board", "{ship}", "--validate"]],
    "GET /api/atlas": [["atlas", "list", "projects"], ["atlas", "search", "zebracorn"]],
    "GET /api/sources": [["sources", "list"]],
    "GET /api/sources/search": [["sources", "search", "password", "--within", "{source}"]],
    "GET /api/source": [["sources", "read", "{source}", "apps/lantern/auth/tokens.py"]],
    "GET /api/history": [["history", "timeline", "{lantern}"]],
    "POST /api/history/explore": [["history", "explore", "{lantern}", "{classic}", "--query", "password"]],
    "POST /api/history/system": [["history", "system", "{system}", "--at", "2025-04-01"]],
    "POST /api/history/land": [["history", "land", "{lantern}", "--cursor", "{cursor}", "--result-key", "{result_key}",
                                "--group", "{group}", "--query", "password"]],
    "GET /api/history/conversations": [["history", "conversations", "{suite}", "--at", "2025-04-01", "--query", "orchard login"]],
    "GET /api/session/search": [["cognito", "--file", "{ref}"]],
    "POST /api/space/refresh": [["atlas", "refresh", "--space", "--harvest"]],
}
TEXT_ONLY = {  # Twins whose CLI prints text, not JSON; the route's own JSON is still walked above
    "GET /api/recap": "`navcom --recap REF` prints the recap the route returns as one string",
    "GET /api/harnesses": "`navcom --resume REF --print` names the fresh harnesses in text",
    "GET /api/plan": "`navcom --resume REF --print` prints the plan's command line",
    "POST /api/launch": "`navcom --resume REF --tab` prints the opened command",
    "POST /api/upkeep": "`navcom --maintain` prints one summary line",
}
REFUSED = {("atlas", "board"): 2}  # board --validate refuses a remote ship (exit 2) and still prints its JSON


def walk_gaps(routes, probes, cli, text):
    """Routes and CLI twins the presentation walk would miss (empty when it covers them all)."""
    walked = {route for route, entry in routes.items() if entry != "view-state"}
    twins = {route for route, entry in routes.items() if not isinstance(entry, str)}
    problems = [f"{route} is never called by the presentation walk; add the request the view sends to PROBES."
                for route in sorted(walked - set(probes))]
    problems += [f"PROBES calls {route}, which ROUTES does not list (or tags view-state)."
                 for route in sorted(set(probes) - walked)]
    problems += [f"{route}'s CLI twin is not walked: add its --json command to CLI_JSON, or say in TEXT_ONLY "
                 f"why it prints only text." for route in sorted(twins - set(cli) - set(text))]
    problems += [f"{route} is in CLI_JSON and TEXT_ONLY; choose one." for route in sorted(set(cli) & set(text))]
    problems += [f"{route} is in CLI_JSON or TEXT_ONLY but has no CLI twin in ROUTES."
                 for route in sorted((set(cli) | set(text)) - twins)]
    return problems


def test_every_route_and_cli_twin_is_walked_for_presentation_keys():
    assert walk_gaps(ROUTES, PROBES, CLI_JSON, TEXT_ONLY) == []


def test_walk_coverage_guard_fails_on_an_unwalked_route():
    glue = dict(ROUTES, **{"GET /api/glue": Twin("navcom_glue.view", ["glue"], {})})
    assert walk_gaps(glue, PROBES, CLI_JSON, TEXT_ONLY) == [
        "GET /api/glue is never called by the presentation walk; add the request the view sends to PROBES.",
        "GET /api/glue's CLI twin is not walked: add its --json command to CLI_JSON, or say in TEXT_ONLY why it "
        "prints only text."]
    gap = dict(ROUTES, **{"GET /api/glue": "cli-gap:GET /api/glue"})
    assert len(walk_gaps(gap, PROBES, CLI_JSON, TEXT_ONLY)) == 1
    assert walk_gaps(ROUTES, PROBES, CLI_JSON, dict(TEXT_ONLY, **{"GET /api/space": "x"})) == [
        "GET /api/space is in CLI_JSON and TEXT_ONLY; choose one."]


def use_env(monkeypatch, env):
    for name in set(os.environ) - set(env):
        monkeypatch.delenv(name)
    for name, value in env.items():
        monkeypatch.setenv(name, value)


def local_model(endpoint, path, data=None, timeout=1):
    """An already-running local model, answering as Ollama does (no network)."""
    if path == "/api/ps":
        return {"models": [{"name": "fixture-model", "size_vram": 1 << 30}]}
    if path == "/api/chat":
        return {"message": {"content": json.dumps({"title": "Cognito fix", "note": "Stopped at the login test."})}}
    raise OSError(f"no fixture model route {path}")


def route_json(navcom, world, monkeypatch, route):
    """What the bridge sends back for each probe of `route` on the world (plus a background task's final state)."""
    import navcom_intelligence
    from navcom_web import WebApp
    use_env(monkeypatch, world["env"])
    monkeypatch.setattr(navcom, "resume_in_new_tab", lambda plan: (True, "opened (test)"))  # never a real tab
    monkeypatch.setattr(navcom_intelligence, "_request", local_model)
    app = WebApp(navcom, world["index"])
    method, path = route.split(" ", 1)
    outputs = []
    for request in PROBES[route]:
        conn = app.connect()
        try:
            result = (app.post if method == "POST" else app.get)(conn, path, fill(request, world["names"]))
            conn.commit()
        finally:
            conn.close()
        outputs.append(json.loads(json.dumps(result)))  # exactly what the handler serializes
        if route in BACKGROUND:
            deadline = time.monotonic() + 180
            while app.task.get("running") and time.monotonic() < deadline:
                time.sleep(.05)
            assert not app.task.get("running") and not app.task.get("error"), app.task
            outputs.append(json.loads(json.dumps(app.task)))
    return outputs


@pytest.mark.parametrize("route", list(PROBES))
def test_route_json_carries_no_presentation_keys(navcom, world, monkeypatch, route):
    outputs = route_json(navcom, world, monkeypatch, route)
    found = {f"{route} #{i}": keys[:5] for i, output in enumerate(outputs) if (keys := presentation_keys(output))}
    assert found == {}, ("Presentation leaked into what the bridge sends; the view picks colors, sprites and camera "
                         f"from kind and form (docs/architecture.md): {found}")
    if route == "POST /api/suggest":
        assert outputs[0]["available"] is True and outputs[0]["title"] == "Cognito fix"  # the answer itself was walked
    if route == "GET /api/space":
        assert outputs[2]["evidence"]["query_plan"]["style"] == "literal"  # the one allowed 'style' was walked
    if route == "POST /api/space/refresh":
        assert outputs[-1]["coverage"]["visited"] >= 1  # the chart refresh result itself was walked
    if route in ("POST /api/space/ask", "POST /api/space/board", "POST /api/launch"):
        import galaxy_world
        assert galaxy_world.launches(world["launched"]) == []


def cli_json(world, argv, env=None, prelude=""):
    """Run a CLI twin with --json under the world's HOME; its parsed stdout."""
    argv = fill(argv, world["names"]) + ["--json"]
    script = f"import sys\nsys.path.insert(0, {str(ROOT)!r})\nimport navcom\n{prelude}\nsys.exit(navcom.run(sys.argv[1:]))\n"
    proc = subprocess.run([sys.executable, "-c", script, *argv], env=env or world["env"], cwd=world["workdir"],
                          stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=300)
    expected = REFUSED.get(tuple(argv[:2]), 0)
    assert proc.returncode == expected and "Traceback" not in proc.stderr, (
        f"navcom {' '.join(argv)} exited {proc.returncode}:\n{proc.stderr[-1500:]}")
    return json.loads(proc.stdout)


CLI_CASES = [(route, argv) for route, commands in CLI_JSON.items() for argv in commands]


@pytest.mark.parametrize("route,argv", CLI_CASES, ids=[" ".join(argv) for _, argv in CLI_CASES])
def test_cli_twin_json_carries_no_presentation_keys(world, route, argv):
    keys = presentation_keys(cli_json(world, argv))
    assert keys == [], f"`navcom {' '.join(argv)} --json` (twin of {route}) prints presentation keys: {keys[:5]}"


DECORATED = {  # services the route walk must catch when they name a color (the verifier's blind spots and more)
    "GET /api/space/files": "navcom_place_files.files",
    "GET /api/space/related": "navcom_relationships.related",
    "GET /api/space/inspect": "navcom_navigation.inspect",
    "GET /api/space/context": "navcom_navigation.context",
    "GET /api/sources": "navcom_sources.sources_list",
    "GET /api/sources/search": "navcom_sources.search",
    "GET /api/history/conversations": "navcom_historical_conversations.view",
    "POST /api/history/land": "navcom_historical_landing.landing",
    "POST /api/history/system": "navcom_system_history.view",
    "GET /api/status": "navcom.dashboard_snapshot",
    "GET /api/session": "navcom.resume_plan",
    "POST /api/suggest": "navcom_intelligence.suggest_for",
    "GET /api/voice": "navcom_voice.status",
}


@pytest.mark.parametrize("route,service", DECORATED.items(), ids=list(DECORATED.values()))
def test_route_walk_fails_when_a_service_names_a_color(navcom, world, monkeypatch, route, service):
    module, *attrs = service.split(".")
    owner = navcom if module == "navcom" else importlib.import_module(module)
    original = getattr(owner, attrs[-1])
    monkeypatch.setattr(owner, attrs[-1], lambda *args, **kwargs: dict(original(*args, **kwargs), color="red"))
    outputs = route_json(navcom, world, monkeypatch, route)
    assert any(path.endswith(".color") for output in outputs for path in presentation_keys(output))


def test_cli_walk_fails_when_a_service_names_a_color(world):
    prelude = ("import navcom_place_files\noriginal = navcom_place_files.files\n"
               "navcom_place_files.files = lambda *a, **k: dict(original(*a, **k), hue=210)")
    printed = cli_json(world, ["atlas", "files", "{district}"], prelude=prelude)
    assert presentation_keys(printed) == ["$.hue"]
