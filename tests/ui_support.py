"""Helpers for the real-browser UI == API sync tests (tests/test_ui_api_sync.py).

Everything here is read-only against the live bridge and the history cache:
- Bridge talks to a running ``navcom --menu`` bridge with the page's own token.
- journey_requests() builds the exact request bodies of the saved journey; the
  test's API oracle and ApiGuard share them.
- ApiGuard sits in front of every /api request the browser makes, lets exactly
  those read-only journey requests through and aborts (and records) anything
  else: a present-day chart refresh, a dated system request that would pin new
  HEADs, or a landing query at any other scope/district/limit that would cook a
  new memo.
- CacheGuard hashes the whole history cache (systems/ and revisions/, where
  landing query memos live) before and after a test.
- SNAPSHOT_JS reads UI state from the URL, history.state and the visible DOM.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# The saved dated journey from the owner's diary (2026-10-16). Override the whole
# dict with NAVCOM_JOURNEY_JSON when the saved session changes.
DEFAULT_JOURNEY = {
    "system": "system:9b1f5d1b7914f7de9de3",
    "system_label": "syra",
    "cutoff": "2026-10-01T12:00:00Z",
    "cutoff_label": "2026-10-01 12:00:00 UTC",
    "cursor": "001f730234d6f2cb0a9a669291867283e68d4727c5bfa744335dfa290a928faf:0",
    "result_key": "e1fe4a30019ca396636a321a98f2a143dcb85388052ce572a046147b21e7d077",
    "product": "planet:ace3e3d93a9b103549f8",
    "product_label": "syrenity-mobile",
    "product_files": 190,
    "product_districts": 5,
    "commit": "1325eaa77fed0521f58317fa191ebf2f82756be6",
    "district": "historical-district:95b25495c938190a84b1",
    "district_label": "sign in",
    "district_files": 4,
    "file": "apps/uapp-app/app/(auth)/sign-in.tsx",
    "query": "login",
}

TOKEN_PATTERN = re.compile(r'const TOKEN=("[^"]+");')


def journey() -> dict:
    raw = os.environ.get("NAVCOM_JOURNEY_JSON")
    return {**DEFAULT_JOURNEY, **json.loads(raw)} if raw else dict(DEFAULT_JOURNEY)


def history_root() -> Path:
    return Path(os.environ.get("NAVCOM_HISTORY_CACHE", Path.home() / ".codex" / "navcom-history"))


def journey_requests(journey: dict) -> dict:
    """The exact POST bodies the page sends on the saved journey (and nothing else is allowed).

    The search landing is the one memoized query: its memo key hashes the whole
    request (scope, district paths, limit), so any other combination would write.
    """
    j = journey

    def land(group, q):
        return {"cursor": j["cursor"], "within": j["product"], "result_key": j["result_key"],
                "group": group, "q": q, "limit": 20}

    return {
        "system": {"within": j["system"], "at": j["cutoff"], "cursor": j["cursor"], "q": "", "limit": 4},
        "product": land(None, ""),
        "district": land(j["district"], ""),
        "search": land(j["district"], j["query"]),
    }


class Bridge:
    """Direct API client using the same token, Host and endpoints as the page."""

    def __init__(self, url: str):
        parsed = urllib.parse.urlparse(url)
        if parsed.hostname != "127.0.0.1" or not parsed.port:
            raise ValueError("NAVCOM_BRIDGE_URL must be http://127.0.0.1:<port>/ (localhost is refused by the bridge)")
        self.base = f"http://127.0.0.1:{parsed.port}"
        html = urllib.request.urlopen(self.base + "/", timeout=30).read().decode("utf-8")
        match = TOKEN_PATTERN.search(html)
        if not match:
            raise RuntimeError("The bridge page did not embed a session token")
        self._token = json.loads(match.group(1))

    def _call(self, method: str, route: str, body=None, timeout: float = 120.0):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"X-Navcom-Token": self._token}
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(self.base + route, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read() or b"{}")

    def get(self, route: str, params: dict | None = None, timeout: float = 120.0):
        query = "?" + urllib.parse.urlencode(params) if params else ""
        return self._call("GET", route + query, timeout=timeout)

    def post(self, route: str, body: dict, timeout: float = 120.0):
        return self._call("POST", route, body, timeout=timeout)

    def ok(self, method: str, route: str, payload=None):
        status, data = self.get(route, payload) if method == "GET" else self.post(route, payload)
        if status != 200:
            raise AssertionError(f"{method} {route} returned {status}: {data.get('error', data)}")
        return data


class ApiGuard:
    """Context-wide /api interceptor: record everything, abort anything that could write.

    Allowed (read-only on this saved journey):
      GET  /api/state, /api/history/conversations, /api/source
      POST /api/history/system  only the exact saved system request (journey_requests()["system"])
      POST /api/history/land    only the exact product, district and memoized district+query
                                requests (journey_requests()); a query at any other scope,
                                district or limit has a different memo key and would write one
    Everything else (POST /api/space/refresh, /api/space, /api/navigate, /api/status,
    /api/recent, POST /api/state, ...) is aborted and listed in ``forbidden``.
    """

    READ_ONLY_GETS = {"/api/state", "/api/history/conversations", "/api/source"}

    def __init__(self, journey: dict):
        self.journey = journey
        requests = journey_requests(journey)
        self.system_body = requests["system"]
        self.landing_bodies = [requests["product"], requests["district"], requests["search"]]
        self.calls: list[dict] = []
        self.forbidden: list[dict] = []

    def verdict(self, method: str, path: str, body, params: dict | None = None) -> str | None:
        cursor, result_key = self.journey["cursor"], self.journey["result_key"]
        if method == "GET" and path in self.READ_ONLY_GETS:
            return None
        if method == "POST" and path == "/api/history/system":
            if body == self.system_body:
                return None
            if not isinstance(body, dict) or body.get("cursor") != cursor:
                return "dated system request without the saved cursor would pin new HEADs"
            if body.get("q"):
                return "dated system query would explore and write a new result set"
            if body.get("retry_larger"):
                return "retry_larger derives a new session"
            return "dated system request differs from the saved journey request"
        if method == "POST" and path == "/api/history/land":
            if body in self.landing_bodies:
                return None
            if not isinstance(body, dict) or body.get("cursor") != cursor or body.get("result_key") != result_key:
                return "landing outside the saved cursor/result"
            if body.get("q"):
                return "landing query outside the memoized request (scope, district, query or limit) would cook a new memo"
            return "landing outside the saved journey's product and district"
        if path == "/api/space/refresh":
            return "present-day chart refresh (resumes chart intake and writes caches)"
        return "not part of the read-only dated journey (present-day fallback or write)"

    def install(self, context) -> None:
        context.route("**/api/**", self._handle)

    def _handle(self, route) -> None:
        request = route.request
        parsed = urllib.parse.urlparse(request.url)
        body = None
        if request.method == "POST":
            try:
                body = json.loads(request.post_data or "null")
            except ValueError:
                body = request.post_data
        record = {"method": request.method, "path": parsed.path,
                  "params": dict(urllib.parse.parse_qsl(parsed.query)), "body": body}
        reason = self.verdict(request.method, parsed.path, body, record["params"])
        self.calls.append(record)
        if reason:
            self.forbidden.append({**record, "reason": reason})
            route.abort()
        else:
            route.continue_()

    def mark(self) -> int:
        return len(self.calls)

    def since(self, mark: int) -> list[str]:
        return [c["method"] + " " + c["path"] for c in self.calls[mark:]]


class ChartGuard(ApiGuard):
    """For the present-day chart: only the explore view and the saved view position pass.

    Selecting a place and reading its rail needs nothing else; every rail action is lazy.
    The automatic chart refresh on first load is aborted (and listed), like any other call.
    """

    def verdict(self, method: str, path: str, body, params: dict | None = None) -> str | None:
        if method == "GET" and path == "/api/state":
            return None
        if method == "GET" and path == "/api/space" and (params or {}).get("action") == "explore":
            return None
        if path == "/api/space/refresh":
            return "present-day chart refresh (resumes chart intake and writes caches)"
        return "not needed to read the present-day rail"


def shell_quote(word: str) -> str:
    """navcom_space.js shellQuote: bare when safe, else single-quoted."""
    return word if re.fullmatch(r"[A-Za-z0-9_./:@=-]+", word) else "'" + word.replace("'", "'\\''") + "'"


def command_text(command, fills: dict | None = None) -> str:
    """navcom_space.js commandText: the service argv as shown; only <placeholders> are filled."""
    if isinstance(command, str):
        return command
    fills = fills or {}
    return " ".join((shell_quote(fills[w].strip()) if fills.get(w, "").strip() else w)
                    if re.fullmatch(r"<[^<>\s]+>", w) else shell_quote(w) for w in command)


def tint_hue(identity: str, system: str = "") -> tuple[int, int]:
    """navcom_space.js tint(): (hue, saturation) for a place; inside a system it takes the family hue."""
    def seed(text):
        h = 2166136261
        for char in text:
            h = ((h ^ ord(char)) * 16777619) & 0xFFFFFFFF
        return h
    h = seed(identity)
    inside = bool(system) and system != identity
    f = seed(system) if inside else h
    hue = (f % 360 + h % 49 - 24 + 360) % 360 if inside else h % 360
    return hue, 32 + (f >> 9) % 34


RAIL_JS = r"""() => ({
  rail: [...document.querySelectorAll('section.space-inspector .space-action-rail .space-rail-item')].map(item => ({
    label: item.querySelector('button').textContent,
    cli: item.querySelector('.space-cli code') ? item.querySelector('.space-cli code').textContent : null,
    expanded: item.querySelector('button').getAttribute('aria-expanded')})),
  more: [...document.querySelectorAll('section.space-inspector details.space-commands .space-cli code')].map(c => c.textContent),
  heading: (document.querySelector('section.space-inspector h2') || {}).textContent,
  styles: Object.fromEntries([...document.querySelectorAll('.space-places [data-place]')].map(b => [b.dataset.place,
    (b.firstElementChild && b.firstElementChild.getAttribute('style')) || ''])),
})"""


class CacheGuard:
    """Content hashes of everything under the history cache root.

    That covers the saved session (systems/<session>/), every other session a
    stray request could create, and revisions/<snapshot>/harvest/queries/, where
    a landing query writes its memo. About 8k files / 100 MB: ~1 s per capture.
    Directories and symlinks are listed too (links are not followed).
    """

    CLEAN = {"added": [], "removed": [], "changed": []}

    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root else history_root()
        self.before = self.capture()

    def capture(self) -> dict:
        entries = {}
        for folder, dirs, files in os.walk(self.root, followlinks=False):
            base = Path(folder)
            for name in dirs + files:
                path = base / name
                key = str(path.relative_to(self.root))
                if path.is_symlink():
                    entries[key] = "symlink:" + os.readlink(path)
                elif path.is_dir():
                    entries[key] = "dir"
                else:
                    entries[key] = hashlib.sha256(path.read_bytes()).hexdigest()
        return entries

    def changes(self) -> dict:
        before, after = self.before, self.capture()
        return {
            "added": sorted(set(after) - set(before)),
            "removed": sorted(set(before) - set(after)),
            "changed": sorted(k for k in set(before) & set(after) if before[k] != after[k]),
        }


# One evaluate() that reads the three places UI state lives: the URL, the
# history entry (history.state.navcomSpace is a JSON copy of the route) and the
# visible DOM. The bridge exposes no window debug hook, by design.
SNAPSHOT_JS = r"""() => {
  const q = (s, root = document) => root.querySelector(s);
  const qa = (s, root = document) => [...root.querySelectorAll(s)];
  const txt = n => n ? n.textContent : null;
  const shown = n => !!n && !n.classList.contains('hidden');
  const st = history.state || {};
  const r = st.navcomSpace || null;
  const results = q('.space-time-results');
  const reader = q('dialog.space-source-reader');
  const footer = qa('.space-chart-footer').find(n => !n.hasAttribute('aria-label'));
  const empty = q('.space-empty');
  const inspector = q('section.space-inspector');
  return {
    href: location.href,
    url: Object.fromEntries(new URL(location.href).searchParams),
    journeyId: st.navcomJourney ? st.navcomJourney.id : null,
    route: r && {
      place: r.place, timeAt: r.timeAt, timeCursor: r.timeCursor, timeQ: r.timeQ,
      timeLanding: r.timeLanding && {product: r.timeLanding.product, group: r.timeLanding.group,
        resultKey: r.timeLanding.resultKey, origin: r.timeLanding.origin && {
          place: r.timeLanding.origin.place, timeCursor: r.timeLanding.origin.timeCursor,
          timeQ: r.timeLanding.origin.timeQ, selected: r.timeLanding.origin.selected}},
      sourceRead: r.sourceRead, selected: r.selected, step: r.step,
      zoom: r.zoom, pan: r.pan, cameraScale: r.cameraScale, cameraReady: r.cameraReady},
    dom: {
      title: txt(q('#spaceTitle')),
      caption: txt(q('.space-subtitle')),
      timeEyebrow: shown(q('.space-time-bar')) ? txt(q('.space-time-bar .space-eyebrow')) : null,
      query: q('#spaceQuery') ? q('#spaceQuery').value : null,
      crumbs: qa('nav.space-crumbs button').map(b => b.textContent),
      currentCrumb: txt(q('nav.space-crumbs [aria-current="page"]')),
      places: qa('.space-places [data-place]').map(b => ({id: b.dataset.place,
        label: txt(q('strong', b)), selected: b.classList.contains('selected'),
        unknown: b.classList.contains('space-history-unknown')})),
      destinations: qa('.space-time-destination[data-time-place]').map(b => b.dataset.timePlace),
      inspectorEyebrow: inspector ? txt(q('.space-eyebrow', inspector)) : null,
      inspectorHeading: inspector ? txt(q('h2', inspector)) : null,
      resultsHeading: shown(results) ? txt(q('h2', results)) : null,
      filesLine: shown(results) && q('h2 + p', results) ? txt(q('h2 + p', results)) : null,
      files: qa('.space-time-results button.space-time-file').map(b => b.textContent),
      evidence: qa('.space-time-results article.space-result').map(a => ({
        title: txt(q('strong', a)), path: txt(q('.space-path code', a)),
        text: txt(q('.space-match-text', a)), places: txt(q('.space-source-places', a)),
        open: q('button[aria-label^="Open source"]', a) ? q('button[aria-label^="Open source"]', a).getAttribute('aria-label') : null})),
      mapStatus: txt(q('.space-map-status')),
      navigatorNote: txt(q('p.space-navigator-note')),
      footer: footer ? qa(':scope > span', footer).map(s => s.textContent) : [],
      arrived: shown(empty) ? txt(q('h2', empty)) : null,
      reader: reader && reader.open ? {
        eyebrow: txt(q('.space-source-heading .space-eyebrow', reader)),
        title: txt(q('.space-source-heading h2', reader)),
        status: txt(q('.space-source-status', reader)),
        originalPath: txt(q('.space-path code', reader)),
        window: txt(q('.space-source-window', reader)),
        lines: qa('.space-source-line', reader).map(n => ({number: Number(n.dataset.line), text: txt(q('code', n))})),
        provenance: qa('details.space-source-provenance > p', reader).map(p => p.textContent),
        busy: reader.hasAttribute('aria-busy')} : null,
      transform: q('.space-universe') ? q('.space-universe').style.transform : null,
      zoomLabel: txt(q('.space-zoom span')),
      backDisabled: q('button[aria-label="Back to previous viewpoint"]').disabled,
      forwardDisabled: q('button[aria-label="Forward to next viewpoint"]').disabled,
      busy: q('.space-stage').hasAttribute('aria-busy'),
      unavailable: /unavailable/i.test(txt(q('.space-map-status')) || '') || /unavailable/i.test(txt(q('#spaceTitle')) || ''),
    },
  };
}"""

# Settled = the stage is not busy and the map status reports the dated view as ready.
SETTLED_JS = r"""(expectReader) => {
  const stage = document.querySelector('.space-stage'), status = document.querySelector('.space-map-status');
  if (!stage || stage.hasAttribute('aria-busy') || !status || status.classList.contains('loading')) return false;
  if (!/ready · saved/.test(status.textContent)) return false;
  const reader = document.querySelector('dialog.space-source-reader');
  if (expectReader) return !!reader && reader.open && !reader.hasAttribute('aria-busy') && !!reader.querySelector('.space-source-line');
  return !reader || !reader.open;
}"""

# Records the copied journey link: headless clipboard reads are unreliable.
CLIPBOARD_INIT_JS = r"""Object.defineProperty(navigator, 'clipboard', {configurable: true,
  value: {writeText: async text => { window.__navcomCopied = String(text); }, readText: async () => window.__navcomCopied || ''}});"""
