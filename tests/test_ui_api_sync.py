"""Real-browser proof that the dated journey's UI state equals the API state.

Runs only against a live bridge, never the default suite:

    NAVCOM_BRIDGE_URL=http://127.0.0.1:<port>/ .venv/bin/python -m pytest tests/test_ui_api_sync.py -v

Drives the installed Google Chrome (Playwright channel "chrome", headless, a
fresh profile per context, 1440x900, reduced motion) through the saved journey
syra -> syrenity-mobile -> "sign in" district -> query "login" -> pinned
sign-in.tsx, then Back / Forward / reload / copied link. At every step the UI
(URL, history.state route, visible DOM) is compared with direct calls to the
same endpoints using the page's own token. The URL carries the camera too
(``camera=SCALE_X_Y``), so a copied link reopens the same view.

Safety: every /api request from the page goes through ui_support.ApiGuard,
which lets through only the exact read-only requests of the saved journey and
aborts anything else (present-day chart refresh, a dated system request without
the saved cursor or with a query, a landing query at any other scope, district
or limit, any present-day fallback); the test fails if one was attempted. The
whole history cache (sessions and the revisions' query memos) is hashed before
the test's own API oracle runs and after every test.

Optional env: NAVCOM_BROWSER_CHANNEL (default chrome), NAVCOM_JOURNEY_JSON
(override the saved ids), NAVCOM_HISTORY_CACHE, NAVCOM_UI_ARTIFACTS (directory
for the reader screenshot; default is pytest's tmp_path).
"""
from __future__ import annotations

import json
import math
import os
import re
import time
import urllib.parse
from datetime import datetime
from pathlib import Path

import pytest

BRIDGE_URL = os.environ.get("NAVCOM_BRIDGE_URL", "")

pytestmark = pytest.mark.skipif(
    not BRIDGE_URL,
    reason="live-bridge browser journey; set NAVCOM_BRIDGE_URL=http://127.0.0.1:<port>/ to run",
)

sync_api = pytest.importorskip("playwright.sync_api")

import ui_support  # noqa: E402  (tests/ is on sys.path under pytest's default import mode)
from ui_support import (  # noqa: E402
    CLIPBOARD_INIT_JS,
    RAIL_JS,
    SETTLED_JS,
    SNAPSHOT_JS,
    ApiGuard,
    Bridge,
    CacheGuard,
    ChartGuard,
    command_text,
    tint_hue,
)

TIMEOUT_MS = 90_000  # dated payloads are 11-16 MB


def instant(value: str) -> float:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def children(payload: dict) -> list[dict]:
    center = payload["center"]["id"]
    return [n for n in payload.get("nodes") or [] if n.get("parent_id") == center and n["id"] != center]


def crumb_labels(payload: dict) -> list[str]:
    return ["Your galaxy" if b.get("kind") == "galaxy" else b["label"] for b in payload.get("breadcrumbs") or []]


def hit_rows(payload: dict) -> list[dict]:
    evidence = payload.get("evidence") or {}
    return [hit for field in ("concept_hits", "text_hits") for hit in evidence.get(field) or []]


def card_text(hit: dict) -> str | None:
    """The matched text an evidence card shows: the first non-empty of match/snippet/text/
    description/excerpt, clipped at 1200 characters (no paragraph when there is none)."""
    value = hit.get("match") or hit.get("snippet") or hit.get("text") or hit.get("description") or hit.get("excerpt")
    value = value if isinstance(value, str) else str(value) if type(value) is int else ""
    return value[:1200] + ("…" if len(value) > 1200 else "") if value else None


# --------------------------------------------------------------------------- fixtures


@pytest.fixture(scope="module")
def journey():
    return ui_support.journey()


@pytest.fixture(scope="module")
def cache(journey):
    session_dir = ui_support.history_root() / "systems" / journey["cursor"].split(":")[0]
    plan_path = session_dir / "plan.json"
    if not plan_path.is_file():
        pytest.skip(f"saved history session is not in this cache: {session_dir}")
    plan = json.loads(plan_path.read_text())
    # Only a derived (retry-larger) session takes the read-only reuse branch of
    # /api/history/system; anything else could re-explore and rewrite results.
    if not plan.get("derived_from_session_id"):
        pytest.skip("saved session is not derived; /api/history/system could rewrite its results")
    return CacheGuard()


@pytest.fixture(scope="module")
def bridge(cache):
    bridge = Bridge(BRIDGE_URL)
    task = bridge.ok("GET", "/api/task")
    if task.get("running"):
        pytest.skip("bridge is running a chart/upkeep task; not testing during intake: " + str(task.get("message")))
    return bridge


@pytest.fixture(scope="module")
def oracle(bridge, journey, cache):
    """API truth for each step, fetched with the exact bodies the page sends."""
    j = journey
    bodies = ui_support.journey_requests(j)
    payloads = {"system": bridge.ok("POST", "/api/history/system", bodies["system"])}
    for key in ("product", "district", "search"):
        payloads[key] = bridge.ok("POST", "/api/history/land", bodies[key])
    file_row = next(f for f in payloads["district"]["files"] if f["path"] == j["file"])
    ref, snapshot = file_row["source_ref"], payloads["district"]["snapshot"]
    source_params = {"source": snapshot["source_id"], "path": j["file"], "line": "1", "limit": "80",
                     "history": snapshot["id"], "snapshot": ref["snapshot"], "published": str(ref["published"])}
    payloads["source"] = bridge.ok("GET", "/api/source", source_params)
    # These direct calls bypass ApiGuard, so prove they wrote nothing either. A new
    # memo under revisions/<snapshot>/harvest/queries/ means the memo key moved
    # (it hashes the installed Starforge and search-worker code): that run wrote.
    assert cache.changes() == CacheGuard.CLEAN, "the test's own API oracle wrote to the history cache"
    return {"bodies": bodies, "payloads": payloads, "source_params": source_params, "file_ref": ref}


@pytest.fixture(scope="module")
def browser():
    channel = os.environ.get("NAVCOM_BROWSER_CHANNEL", "chrome")
    with sync_api.sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(channel=channel, headless=True)
        except Exception as error:  # Chrome not installed / channel missing
            pytest.skip(f"cannot launch Chromium channel {channel!r}: {error}")
        yield browser
        browser.close()


@pytest.fixture
def artifacts(tmp_path):
    target = Path(os.environ.get("NAVCOM_UI_ARTIFACTS") or tmp_path)
    target.mkdir(parents=True, exist_ok=True)
    return target


class Session:
    """One browser context (fresh profile) with the write guard installed."""

    def __init__(self, browser, bridge, journey, guard=ApiGuard):
        self.bridge, self.journey = bridge, journey
        self.guard = guard(journey)
        self.context = browser.new_context(viewport={"width": 1440, "height": 900}, reduced_motion="reduce",
                                           locale="en-US", timezone_id="UTC")
        self.context.add_init_script(CLIPBOARD_INIT_JS)
        self.guard.install(self.context)

    def page(self):
        return self.context.new_page()

    def system_url(self):
        j = self.journey
        params = {"view": "space", "place": j["system"], "at": j["cutoff"], "time_cursor": j["cursor"], "local": "1"}
        return self.bridge.base + "/?" + urllib.parse.urlencode(params)

    def close(self):
        self.context.close()


@pytest.fixture
def session(browser, bridge, journey):
    sessions = []

    def make(guard=ApiGuard):
        sessions.append(Session(browser, bridge, journey, guard))
        return sessions[-1]

    yield make
    for item in sessions:
        item.close()


# --------------------------------------------------------------------------- page helpers


def response_for(path: str, method: str = "POST"):
    return lambda r: urllib.parse.urlparse(r.url).path == path and r.request.method == method


def settle(page, reader: bool = False):
    page.wait_for_function(SETTLED_JS, arg=reader, timeout=TIMEOUT_MS)
    return page.evaluate(SNAPSHOT_JS)


def act(page, action, path="/api/history/land", method="POST", reader=False):
    """Run a UI action, wait for the API call it must make, then for the UI to settle."""
    with page.expect_response(response_for(path, method), timeout=TIMEOUT_MS) as response:
        action()
    assert response.value.status == 200, f"{method} {path} failed with {response.value.status}"
    return settle(page, reader)


def camera(snap):
    route = snap["route"]
    return {"zoom": route["zoom"], "pan": route["pan"], "cameraScale": route["cameraScale"],
            "transform": snap["dom"]["transform"]}


def assert_camera(actual, expected, label):
    assert actual["zoom"] == pytest.approx(expected["zoom"], rel=1e-6), f"{label}: zoom"
    assert actual["cameraScale"] == pytest.approx(expected["cameraScale"], rel=1e-6), f"{label}: camera scale"
    assert actual["pan"]["x"] == pytest.approx(expected["pan"]["x"], abs=0.5), f"{label}: pan x"
    assert actual["pan"]["y"] == pytest.approx(expected["pan"]["y"], abs=0.5), f"{label}: pan y"
    assert actual["transform"] == expected["transform"], f"{label}: rendered transform"


def assert_camera_close(actual, expected, label):
    """A copied link's camera: the URL keeps the scale to 4 significant digits and the pan to whole pixels."""
    assert actual["cameraScale"] == pytest.approx(expected["cameraScale"], rel=1e-3), f"{label}: camera scale"
    assert actual["zoom"] == pytest.approx(expected["zoom"], rel=1e-3), f"{label}: zoom"
    assert actual["pan"]["x"] == pytest.approx(expected["pan"]["x"], abs=0.5), f"{label}: pan x"
    assert actual["pan"]["y"] == pytest.approx(expected["pan"]["y"], abs=0.5), f"{label}: pan y"
    number = re.compile(r"-?\d+(?:\.\d+)?")
    (ax, ay, az), (ex, ey, ez) = (map(float, number.findall(c["transform"])[:3]) for c in (actual, expected))
    assert (ax, ay) == (pytest.approx(ex, abs=0.5), pytest.approx(ey, abs=0.5)), f"{label}: rendered position"
    assert az == pytest.approx(ez, rel=1e-3), f"{label}: rendered scale"


def without_camera(url: dict) -> dict:
    return {key: value for key, value in url.items() if key != "camera"}


def assert_link_camera(snap, label):
    """The URL carries the camera on screen (replaceState): absolute scale (4 digits), whole-pixel pan."""
    route = snap["route"]
    scale, x, y = (float(part) for part in snap["url"]["camera"].split("_"))
    assert scale == pytest.approx(route["cameraScale"], rel=1e-3), f"{label}: link camera scale"
    assert (x, y) == (math.floor(route["pan"]["x"] + 0.5), math.floor(route["pan"]["y"] + 0.5)), f"{label}: link camera pan"


def visible_state(snap):
    """The URL-, route- and DOM-level state a user sees (no camera, journey id or step)."""
    route, dom = snap["route"], snap["dom"]
    landing = route["timeLanding"]
    return {
        "url": snap["url"],
        "place": route["place"], "timeAt": instant(route["timeAt"]), "timeCursor": route["timeCursor"],
        "timeQ": route["timeQ"], "sourceRead": route["sourceRead"],
        "landing": landing and {k: landing[k] for k in ("product", "group", "resultKey")},
        **{k: dom[k] for k in ("title", "caption", "timeEyebrow", "query", "crumbs", "currentCrumb",
                               "places", "resultsHeading", "filesLine", "files", "evidence",
                               "mapStatus", "navigatorNote", "footer", "arrived", "reader")},
    }


def assert_dated_frame(snap, journey, label):
    """Every step: pinned date and cursor, no present-day fallback, no failure screen."""
    route, dom = snap["route"], snap["dom"]
    assert route is not None, f"{label}: history.state.navcomSpace missing"
    assert instant(route["timeAt"]) == instant(journey["cutoff"]), f"{label}: route date"
    assert route["timeCursor"] == journey["cursor"], f"{label}: route cursor"
    assert snap["url"]["at"] and instant(snap["url"]["at"]) == instant(journey["cutoff"]), f"{label}: URL date"
    assert snap["url"]["time_cursor"] == journey["cursor"], f"{label}: URL cursor"
    assert dom["timeEyebrow"] == "TIME / " + journey["cutoff_label"], f"{label}: time bar date"
    assert dom["footer"][:1] == ["● Pinned history · " + journey["cutoff_label"]], f"{label}: footer pin"
    assert not dom["unavailable"], f"{label}: historical view unavailable: {dom['mapStatus']}"
    assert dom["caption"].startswith("Committed history as of " + journey["cutoff_label"]), f"{label}: caption"


def assert_landing_matches_api(snap, payload, journey, label):
    """The landed product/district view equals POST /api/history/land for the same body."""
    dom, route = snap["dom"], snap["route"]
    assert payload["cursor"] == journey["cursor"] and payload["result_key"] == journey["result_key"]
    assert instant(payload["as_of"]) == instant(route["timeAt"]), f"{label}: API as_of vs UI date"
    assert dom["title"] == payload["center"]["label"], f"{label}: centre title"
    assert dom["crumbs"] == crumb_labels(payload), f"{label}: breadcrumbs"
    assert dom["currentCrumb"] == payload["center"]["label"], f"{label}: current crumb"
    assert [p["id"] for p in dom["places"]] == [n["id"] for n in children(payload)][:80], f"{label}: drawn places"
    assert [p["label"] for p in dom["places"]] == [n["label"] for n in children(payload)][:80], f"{label}: place labels"
    files = payload["files"]
    assert dom["filesLine"] == f"{len(files)} files · commit {payload['commit'][:12]}", f"{label}: file count/commit"
    assert dom["files"] == [f["path"] for f in files[:80]], f"{label}: file list"
    assert dom["footer"][1] == "Committed " + payload["commit"][:12], f"{label}: footer commit"
    assert dom["query"] == payload["query"] == route["timeQ"], f"{label}: query box"
    hits = hit_rows(payload) if payload["query"] else []
    assert [e["path"] for e in dom["evidence"]] == [h["source_path"] + f":{h['line']}" for h in hits], f"{label}: evidence"
    assert [e["text"] for e in dom["evidence"]] == [card_text(h) for h in hits], f"{label}: evidence match text"
    assert [e["places"] for e in dom["evidence"]] == [" · ".join(h.get("place_labels") or []) or None for h in hits], f"{label}: evidence places"
    assert route["timeLanding"]["product"] == payload["product"]["id"], f"{label}: landing product"
    assert route["timeLanding"]["group"] == (payload["group_id"] or ""), f"{label}: landing group"
    assert route["timeLanding"]["resultKey"] == payload["result_key"], f"{label}: landing result"
    assert route["place"] == payload["center"]["id"], f"{label}: route place"


def expected_landing_url(journey, *, group=None, q=None):
    url = {
        "view": "space", "place": group or journey["product"], "at": journey["cutoff"],
        "time_cursor": journey["cursor"], "time_product": journey["product"],
        "time_result": journey["result_key"], "time_origin": journey["system"], "time_origin_q": "",
        "time_origin_cursor": journey["cursor"], "local": "1",
    }
    if group:
        url["time_group"] = group
    if q:
        url["q"] = q
    return url


def land_bodies(guard, mark):
    return [c["body"] for c in guard.calls[mark:] if c["path"] == "/api/history/land"]


# --------------------------------------------------------------------------- tests


def test_initial_dated_system_state_sync(session, oracle, journey, cache):
    """The places the UI draws for the system at the cutoff == the API's nodes for the same cursor."""
    s = session()
    page = s.page()
    page.goto(s.system_url())
    snap = settle(page)
    api = oracle["payloads"]["system"]
    dom = snap["dom"]

    assert api["cursor"] == journey["cursor"] and api["session_id"] == journey["cursor"].split(":")[0]
    assert_dated_frame(snap, journey, "dated system")
    assert without_camera(snap["url"]) == {"view": "space", "place": journey["system"], "at": journey["cutoff"],
                                           "time_cursor": journey["cursor"], "local": "1"}
    assert_link_camera(snap, "dated system")
    assert snap["route"]["timeLanding"] is None and snap["route"]["timeQ"] == api["query"] == ""
    assert instant(api["as_of"]) == instant(snap["route"]["timeAt"])
    assert dom["title"] == api["center"]["label"] == journey["system_label"]
    assert dom["crumbs"] == crumb_labels(api)

    # Map: exactly the system's direct children, each labelled from its dated node.
    expected = children(api)[:80]
    by_id = {p["id"]: p for p in dom["places"]}
    assert sorted(by_id) == sorted(n["id"] for n in expected)
    for node in expected:
        drawn = by_id[node["id"]]
        committed = node.get("historical_state") == "committed"
        label = node["label"] if committed else (node.get("current_label") or node["label"])
        assert drawn["label"] == label, node["id"]
        assert drawn["unknown"] == (node.get("historical_state") not in ("committed", "navigation_anchor")), node["id"]
    assert journey["product"] in by_id and by_id[journey["product"]]["label"] == journey["product_label"]

    # Inventory: every product/experiment address the API reconstructed or left unknown.
    anchors = [n["id"] for n in api["nodes"] if n.get("kind") in ("planet", "moon")]
    assert sorted(dom["destinations"]) == sorted(anchors)
    c = api["coverage"]
    assert dom["filesLine"] == (f"{c.get('visited_repositories', 0)} / {c.get('pinned_repositories', 0)} pinned repositories visited"
                                f" · {c.get('completed_scopes', 0)} / {c.get('eligible_scopes', 0)} places reconstructed")
    assert dom["resultsHeading"] == "Through time"
    assert dom["mapStatus"] == "Historical chart ready · saved addresses held steady"

    # The page asked the API exactly what the test asked, and nothing else.
    system_calls = [c["body"] for c in s.guard.calls if c["path"] == "/api/history/system"]
    assert system_calls == [oracle["bodies"]["system"]]
    assert sorted(s.guard.since(0)) == sorted(["GET /api/state", "POST /api/history/system",
                                               "GET /api/history/conversations"])
    assert s.guard.forbidden == []
    assert cache.changes() == CacheGuard.CLEAN


def test_dated_journey_round_trip(session, oracle, journey, cache, artifacts):
    j, api, bodies = journey, oracle["payloads"], oracle["bodies"]
    s = session()
    page = s.page()
    guard = s.guard
    timings = {}

    def timed(name, fn):
        started = time.monotonic()
        result = fn()
        timings[name] = round(time.monotonic() - started, 2)
        assert guard.forbidden == [], f"{name}: forbidden API request attempted: {guard.forbidden}"
        return result

    # 1) Saved system URL (date + cursor) -> historical system with syra and the mobile product.
    mark = guard.mark()
    s1 = timed("1 open saved system", lambda: (page.goto(s.system_url()), settle(page))[1])
    assert_dated_frame(s1, j, "1 system")
    assert s1["dom"]["title"] == api["system"]["center"]["label"] == j["system_label"]
    assert {p["id"] for p in s1["dom"]["places"]} == {n["id"] for n in children(api["system"])}
    product = next(p for p in s1["dom"]["places"] if p["id"] == j["product"])
    assert product["label"] == j["product_label"] and not product["unknown"]
    assert [c["body"] for c in guard.calls[mark:] if c["path"] == "/api/history/system"] == [bodies["system"]]

    # 2) Land on the product through the UI: select it on the map, then the inspector's fly button.
    page.locator(f'.space-places [data-place="{j["product"]}"]').click()
    page.get_by_role("button", name="Fly to this dated product →", exact=True).wait_for()
    picked = page.evaluate(SNAPSHOT_JS)
    dated_product = next(n for n in api["system"]["nodes"] if n["id"] == j["product"])
    assert picked["route"]["selected"] == j["product"] and picked["url"] == s1["url"], "selection is replaceState only"
    assert [p["id"] for p in picked["dom"]["places"] if p["selected"]] == [j["product"]]
    assert (picked["dom"]["inspectorEyebrow"], picked["dom"]["inspectorHeading"]) == ("SELECTED HISTORICAL ADDRESS", dated_product["label"])
    assert dated_product["historical_state"] == "committed" and dated_product["commit"] == j["commit"]
    # The fly button shows the service's own land command for this dated product, unchanged.
    assert page.locator("section.space-inspector .space-cli code").first.text_content() == dated_product["land_command"]
    mark = guard.mark()
    s2 = timed("2 land on product", lambda: act(page, lambda: page.get_by_role("button", name="Fly to this dated product →", exact=True).click()))
    assert land_bodies(guard, mark) == [bodies["product"]]
    assert_dated_frame(s2, j, "2 product")
    assert without_camera(s2["url"]) == expected_landing_url(j)
    assert_link_camera(s2, "2 product")
    assert "time_group" not in s2["url"]
    assert_landing_matches_api(s2, api["product"], j, "2 product")
    assert len(children(api["product"])) == j["product_districts"] == len(s2["dom"]["places"])
    assert len(api["product"]["files"]) == j["product_files"]
    assert s2["dom"]["resultsHeading"] == "Committed product"
    origin = s2["route"]["timeLanding"]["origin"]
    assert (origin["place"], origin["timeCursor"], origin["selected"]) == (j["system"], j["cursor"], j["product"])
    assert s2["route"]["step"] == s1["route"]["step"] + 1

    # 3) Enter the sign-in district -> time_group set.
    page.locator(f'.space-places [data-place="{j["district"]}"]').click()
    page.get_by_role("button", name="Land in this dated district →", exact=True).wait_for()
    picked = page.evaluate(SNAPSHOT_JS)
    district = next(n for n in children(api["product"]) if n["id"] == j["district"])
    assert picked["route"]["selected"] == j["district"] and picked["url"] == s2["url"], "selection is replaceState only"
    assert (picked["dom"]["inspectorEyebrow"], picked["dom"]["inspectorHeading"]) == ("COMMITTED DISTRICT", district["label"])
    assert page.locator("section.space-inspector").get_by_text(f"{district['file_count']} committed files", exact=True).count() == 1
    assert page.locator("section.space-inspector .space-cli code").first.text_content() == district["land_command"]
    mark = guard.mark()
    s3 = timed("3 land in district", lambda: act(page, lambda: page.get_by_role("button", name="Land in this dated district →", exact=True).click()))
    assert land_bodies(guard, mark) == [bodies["district"]]
    assert_dated_frame(s3, j, "3 district")
    assert without_camera(s3["url"]) == expected_landing_url(j, group=j["district"])
    assert_link_camera(s3, "3 district")
    assert_landing_matches_api(s3, api["district"], j, "3 district")
    assert s3["dom"]["title"] == j["district_label"] and len(s3["dom"]["files"]) == j["district_files"]
    assert s3["dom"]["places"] == [] and s3["dom"]["arrived"] == "You’ve arrived."
    assert s3["dom"]["resultsHeading"] == "Committed district files"
    assert s3["dom"]["navigatorNote"] == "Search is limited to this committed district."
    assert s3["route"]["step"] == s2["route"]["step"] + 1
    c3 = camera(s3)

    # 4) Search 'login' at district level -> q=login, evidence list == the API's hits.
    query = page.locator("#spaceQuery")
    query.fill(j["query"])
    mark = guard.mark()
    s4 = timed("4 search login", lambda: act(page, lambda: query.press("Enter")))
    assert land_bodies(guard, mark) == [bodies["search"]]
    assert_dated_frame(s4, j, "4 search")
    assert without_camera(s4["url"]) == expected_landing_url(j, group=j["district"], q=j["query"])
    assert_landing_matches_api(s4, api["search"], j, "4 search")
    hits = hit_rows(api["search"])
    assert len(s4["dom"]["evidence"]) == len(hits) > 0
    assert [e["open"] for e in s4["dom"]["evidence"]] == [f"Open source {h['source_path']} at line {h['line']}" for h in hits]
    assert [e["title"] for e in s4["dom"]["evidence"]] == [h["source_path"].split("/")[-1] for h in hits]
    assert all(e["text"] for e in s4["dom"]["evidence"]), "every login hit shows its matched line"
    assert s4["route"]["step"] == s3["route"]["step"] + 1
    # Move the camera so reload/back/forward/link have something non-default to restore.
    entries = page.evaluate("() => history.length")
    page.get_by_role("button", name="Zoom out", exact=True).click()
    page.get_by_role("button", name="Zoom out", exact=True).click()
    page.locator(".space-stage").focus()
    page.keyboard.press("ArrowRight")
    page.keyboard.press("ArrowDown")
    page.wait_for_function("() => { const p = history.state.navcomSpace.pan; return p.x === -45 && p.y === -45; }")
    page.wait_for_function("() => new URL(location.href).searchParams.get('camera').endsWith('_-45_-45')")
    s4 = page.evaluate(SNAPSHOT_JS)
    c4 = camera(s4)
    assert c4["zoom"] == pytest.approx(c3["zoom"] * 0.64, rel=1e-6) and c4["pan"] == {"x": -45, "y": -45}
    assert_link_camera(s4, "4 moved camera")
    assert page.evaluate("() => history.length") == entries and s4["route"]["step"] == s3["route"]["step"] + 1, \
        "camera moves replace the current entry; they never push one"

    # 5) Open the pinned file -> reader shows sign-in.tsx at the pinned commit, text == GET /api/source.
    mark = guard.mark()
    file_button = page.locator(".space-time-results button.space-time-file").filter(has_text=j["file"])
    s5 = timed("5 open pinned file", lambda: act(page, lambda: file_button.first.click(), "/api/source", "GET", reader=True))
    page.screenshot(path=str(artifacts / "journey-reader.png"))
    sources = [c for c in guard.calls[mark:] if c["path"] == "/api/source"]
    assert [c["params"] for c in sources] == [oracle["source_params"]]
    source = api["source"]
    reader = s5["dom"]["reader"]
    assert reader["eyebrow"] == "PINNED GIT SOURCE"
    assert reader["title"] == j["file"].split("/")[-1]
    assert reader["originalPath"] == source["original_path"]
    assert source["relative_path"] == j["file"] and source["provenance"]["commit"] == j["commit"] == api["search"]["commit"]
    assert reader["status"].startswith("Pinned Git revision " + j["commit"][:12] + " · ")
    # The date beside a pinned revision is its commit date only when the response carries one;
    # otherwise it is the snapshot's capture time and is labeled so.
    dated = source["provenance"].get("committed_at") or source["provenance"].get("authored_at")
    assert (" · committed " if dated else " · captured ") in reader["status"]
    assert "Commit " + source["provenance"]["commit"] in reader["provenance"]
    assert "Git tree " + source["provenance"]["tree"] in reader["provenance"]
    w = source["window"]
    assert reader["window"] == f"Lines {w['start']}–{w['end']} of {w['total_lines']:,} · {w['returned_lines']} lines in this window"
    assert reader["lines"] == [{"number": line["number"], "text": line["text"]} for line in source["lines"]]
    read = s5["route"]["sourceRead"]
    ref = oracle["file_ref"]
    assert (read["path"], read["history"], read["snapshot"], read["published"]) == (j["file"], ref["history"], ref["snapshot"], ref["published"])
    assert s5["url"] == s4["url"], "the reader is history state, not URL state"
    assert s5["route"]["step"] == s4["route"]["step"] + 1

    # 6) Close the reader -> its history entry pops, the search view (camera included) is back.
    mark = guard.mark()
    s6 = timed("6 close reader", lambda: act(page, lambda: page.get_by_role("button", name="Close source reader", exact=True).click()))
    assert land_bodies(guard, mark) == [bodies["search"]]
    assert s6["dom"]["reader"] is None and s6["route"]["sourceRead"] is None
    assert visible_state(s6) == visible_state(s4)
    assert s6["route"]["step"] == s4["route"]["step"]
    assert_camera(camera(s6), c4, "6 close reader")
    assert s6["dom"]["forwardDisabled"] is False

    # 7) Back -> the district before the search (q cleared, its own camera).
    mark = guard.mark()
    s7 = timed("7 back", lambda: act(page, lambda: page.get_by_role("button", name="Back to previous viewpoint", exact=True).click()))
    assert land_bodies(guard, mark) == [bodies["district"]]
    assert visible_state(s7) == visible_state(s3)
    assert s7["route"]["step"] == s3["route"]["step"]
    assert_camera(camera(s7), c3, "7 back")
    assert_landing_matches_api(s7, api["district"], j, "7 back")

    # 8) Forward -> the search again, with the moved camera.
    mark = guard.mark()
    s8 = timed("8 forward", lambda: act(page, lambda: page.get_by_role("button", name="Forward to next viewpoint", exact=True).click()))
    assert land_bodies(guard, mark) == [bodies["search"]]
    assert visible_state(s8) == visible_state(s4)
    assert s8["route"]["step"] == s4["route"]["step"]
    assert_camera(camera(s8), c4, "8 forward")

    # 9) Reload -> same date/cursor/group/query and camera, straight to the pinned landing.
    mark = guard.mark()
    s9 = timed("9 reload", lambda: act(page, page.reload))
    assert sorted(guard.since(mark)) == ["GET /api/state", "POST /api/history/land"], "reload must not fall back to a present-day or system request"
    assert land_bodies(guard, mark) == [bodies["search"]]
    assert_dated_frame(s9, j, "9 reload")
    assert visible_state(s9) == visible_state(s4)
    assert (s9["journeyId"], s9["route"]["step"]) == (s4["journeyId"], s4["route"]["step"])
    assert_camera(camera(s9), c4, "9 reload")
    assert_landing_matches_api(s9, api["search"], j, "9 reload")

    # 10) Copied link -> a new page (same profile) and a new profile land on the same dated state.
    page.get_by_role("button", name="Copy journey link", exact=True).click()
    copied = page.evaluate("() => window.__navcomCopied")
    assert copied == page.url
    fresh_profile = session()
    for name, owner in (("10a new page", s), ("10b new profile", fresh_profile)):
        target = owner.page()
        mark = owner.guard.mark()
        snap = timed(name, lambda: act(target, lambda: target.goto(copied)))
        assert sorted(owner.guard.since(mark)) == ["GET /api/state", "POST /api/history/land"], name
        assert land_bodies(owner.guard, mark) == [bodies["search"]], name
        assert owner.guard.forbidden == [], f"{name}: {owner.guard.forbidden}"
        assert_dated_frame(snap, j, name)
        assert visible_state(snap) == visible_state(s4), name
        assert_landing_matches_api(snap, api["search"], j, name)
        assert snap["route"]["step"] == 0 and snap["journeyId"] != s4["journeyId"], name
        # The link carries the camera: it opens at the moved camera of step 4, not the default.
        assert_camera_close(camera(snap), c4, name + " (linked camera)")
        target.close()

    assert guard.forbidden == []
    assert cache.changes() == CacheGuard.CLEAN
    print("step timings (s):", json.dumps(timings))


@pytest.mark.parametrize("reload_first", [False, True], ids=["without-reload", "after-reload"])
def test_back_to_dated_system_restores_origin(session, oracle, journey, cache, reload_first):
    """'← Back to dated system' returns to the selected product and the system camera, reload or not."""
    j = journey
    s = session()
    page = s.page()
    page.goto(s.system_url())
    settle(page)
    page.locator(f'.space-places [data-place="{j["product"]}"]').click()
    page.get_by_role("button", name="Zoom out", exact=True).click()
    page.locator(".space-stage").focus()
    page.keyboard.press("ArrowLeft")
    page.wait_for_function("() => history.state.navcomSpace.pan.x === 45")
    system = page.evaluate(SNAPSHOT_JS)
    assert system["route"]["selected"] == j["product"]
    landed = act(page, lambda: page.get_by_role("button", name="Fly to this dated product →", exact=True).click())
    assert landed["route"]["timeLanding"]["origin"]["selected"] == j["product"]
    if reload_first:
        mark = s.guard.mark()
        landed = act(page, page.reload)
        assert sorted(s.guard.since(mark)) == ["GET /api/state", "POST /api/history/land"]
        assert visible_state(landed)["landing"] == {"product": j["product"], "group": "", "resultKey": j["result_key"]}
    mark = s.guard.mark()
    back_button = page.locator(".space-time-bar").get_by_role("button", name="← Back to dated system", exact=True)
    back = act(page, back_button.click, "/api/history/system")
    assert [c["body"] for c in s.guard.calls[mark:] if c["path"] == "/api/history/system"] == [oracle["bodies"]["system"]]
    assert_dated_frame(back, j, "back to dated system")
    assert back["route"]["timeLanding"] is None and back["route"]["place"] == j["system"]
    assert back["dom"]["title"] == oracle["payloads"]["system"]["center"]["label"]
    assert back["route"]["selected"] == j["product"], "origin selection lost"
    assert back["dom"]["inspectorHeading"] == j["product_label"]
    assert [p["id"] for p in back["dom"]["places"] if p["selected"]] == [j["product"]]
    assert_camera(camera(back), camera(system), "system camera")
    assert s.guard.forbidden == []
    assert cache.changes() == CacheGuard.CLEAN


def test_present_day_rail_shows_the_api_commands_and_family_hue(session, bridge, journey, cache, artifacts):
    """Selecting a product in the present-day system: its rail lines are exactly the API node's commands."""
    j = journey
    s = session(ChartGuard)
    page = s.page()
    page.goto(s.bridge.base + "/?" + urllib.parse.urlencode({"view": "space", "place": j["system"], "local": "1"}))
    page.wait_for_function("() => !document.querySelector('.space-stage').hasAttribute('aria-busy') && "
                           "document.querySelector('.space-places [data-place]')", timeout=TIMEOUT_MS)
    view = bridge.ok("GET", "/api/space", {"action": "explore", "within": j["system"], "limit": "80", "offset": "0"})
    product = next(n for n in view["nodes"] if n["id"] == j["product"])
    page.locator(f'.space-places [data-place="{j["product"]}"]').click()
    page.wait_for_function("() => document.querySelector('section.space-inspector .space-action-rail')")
    shown = page.evaluate(RAIL_JS)
    page.screenshot(path=str(artifacts / "present-rail.png"))
    commands = {key: value for key, value in product["commands"].items() if value}
    first = {key: value[0] if isinstance(value[0], list) else value for key, value in commands.items()}
    lines = [item["cli"] for item in shown["rail"]]
    assert shown["heading"] == product["label"]
    assert shown["rail"][0]["label"] == f"Fly to {product['label']} →"
    assert lines[0] == command_text(commands["explore"]), "the primary action shows the service's explore command"
    assert all(line in {command_text(v) for v in first.values()} for line in lines), "every rail line is a service command"
    assert len(set(lines)) == len(lines), "one rail action per verb"
    # Nothing the service offers is dropped: each command is a rail line, lives in the panel a rail
    # action opens, or is listed under More CLI commands.
    inside = {"history_explore": "history_timeline", "inspect_refresh": "inspect", "inspect_observe": "inspect",
              "carried_search": "carried_context", "handover": "carried_context"}
    for key, value in commands.items():
        entries = value if isinstance(value[0], list) else [value]
        opener = inside.get(key)
        assert (command_text(entries[0]) in lines or (opener and command_text(first[opener]) in lines)
                or all(command_text(e) in shown["more"] for e in entries)), key
    assert "'<" not in " ".join(lines + shown["more"]), "unfilled placeholders stay bare"
    # Family hue: the product takes its system's hue (within 24 degrees) and saturation.
    style = shown["styles"][j["product"]]
    family_hue, family_sat = tint_hue(j["system"])
    hue, sat = (int(x) for x in re.search(r"--hue:(\d+);--sat:(\d+)%", style).groups())
    assert (hue, sat) == tint_hue(j["product"], j["system"]) and min(abs(hue - family_hue), 360 - abs(hue - family_hue)) <= 24
    assert sat == family_sat
    assert sorted(s.guard.since(0)) == ["GET /api/space", "GET /api/state", "POST /api/space/refresh"]
    assert [f["path"] for f in s.guard.forbidden] == ["/api/space/refresh"], "only the automatic chart refresh was refused"
    assert cache.changes() == CacheGuard.CLEAN


def test_write_guard_blocks_and_reports(session, journey):
    """The guard really aborts writes. Requests carry no token, so even a leak would get a 403."""
    j = journey
    s = session()
    page = s.page()
    page.goto(s.bridge.base + "/navcom_space.css")  # same origin, no app boot, no token on the page
    requests = ui_support.journey_requests(j)
    # Exactly the saved journey's requests pass; that is all the page may send.
    for name, body in requests.items():
        path = "/api/history/system" if name == "system" else "/api/history/land"
        assert s.guard.verdict("POST", path, body) is None, name
    system, search = requests["system"], requests["search"]
    attempts = [
        ["POST", "/api/space/refresh", {"automatic": True}],
        ["POST", "/api/history/system", {k: v for k, v in system.items() if k != "cursor"}],
        ["POST", "/api/history/system", {**system, "q": j["query"]}],
        ["POST", "/api/history/system", {**system, "limit": 80}],
        ["POST", "/api/history/land", {**search, "q": "never memoized"}],
        # The memoized query at another scope or limit has another memo key and would write one.
        ["POST", "/api/history/land", {**search, "group": None}],
        ["POST", "/api/history/land", {**search, "limit": 80}],
        ["POST", "/api/history/land", {**search, "within": j["system"], "group": None}],
        ["GET", "/api/space?action=explore&within=&limit=80&offset=0", None],
        ["POST", "/api/state", {"query": ""}],
    ]
    outcomes = page.evaluate("""async attempts => Promise.all(attempts.map(async ([method, path, body]) => {
        try {
          await fetch(path, {method, body: body ? JSON.stringify(body) : undefined,
                             headers: body ? {'Content-Type': 'application/json'} : {}});
          return 'sent';
        } catch (error) { return 'blocked'; }
      }))""", attempts)
    assert outcomes == ["blocked"] * len(attempts)
    assert sorted(f["method"] + " " + f["path"] for f in s.guard.forbidden) == sorted(a[0] + " " + a[1].split("?")[0] for a in attempts)
    assert all(f["reason"] for f in s.guard.forbidden)
    landing_reasons = [f["reason"] for f in s.guard.forbidden if f["path"] == "/api/history/land"]
    assert len(landing_reasons) == 4 and all("memo" in reason for reason in landing_reasons)


def test_cache_guard_sees_memo_and_session_writes(tmp_path):
    """CacheGuard covers the query memos under revisions/, not only the saved session."""
    session = tmp_path / "systems" / "s1"
    memos = tmp_path / "revisions" / "r1" / "harvest" / "queries"
    session.mkdir(parents=True)
    memos.mkdir(parents=True)
    (session / "plan.json").write_text("{}")
    (memos / "old.json").write_text("{}")
    guard = CacheGuard(tmp_path)
    assert guard.changes() == CacheGuard.CLEAN
    (memos / "new.json").write_text("{}")
    (session / "plan.json").write_text('{"rewritten": true}')
    (tmp_path / "systems" / "s2").mkdir()
    assert guard.changes() == {"added": ["revisions/r1/harvest/queries/new.json", "systems/s2"], "removed": [],
                               "changed": ["systems/s1/plan.json"]}
