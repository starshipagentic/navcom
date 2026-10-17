#!/usr/bin/env python3
"""Capture the galaxy-cockpit proof tour against a LIVE NavCom bridge.

Usage:
    NAVCOM_BRIDGE_URL=http://127.0.0.1:PORT/ .venv/bin/python scripts/capture_cockpit_tour.py docs/e2e-tours/<date>/<topic>
    .venv/bin/python scripts/build_tour_gif.py docs/e2e-tours/<date>/<topic>

Read-only by construction: the automatic chart refresh is answered with a benign
"refresh paused for capture" reply, and dated requests may only reuse the saved
journey cursor (anything that would pin a new session is aborted). The repository
is public, so source-code bodies, match snippets and conversation titles are
blurred before each screenshot; paths, places, commands and structure stay visible.
"""
import html
import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlencode

SYRA = "system:9b1f5d1b7914f7de9de3"
MOBILE = "planet:ace3e3d93a9b103549f8"
DISTRICT = "historical-district:95b25495c938190a84b1"
AT = "2026-10-01T12:00:00Z"
CURSOR = "001f730234d6f2cb0a9a669291867283e68d4727c5bfa744335dfa290a928faf:0"
RESULT = "e1fe4a30019ca396636a321a98f2a143dcb85388052ce572a046147b21e7d077"
BLUR = """.space-source-code,.space-source-line,.space-match-text,.space-matching-children li,
.space-conversation-result strong,.space-conversation-result h3,.space-conversation-result .space-small,
.space-rail-results .space-match-text{filter:blur(5px)!important}"""


def url(base, **params):
    return base + "?" + urlencode({"view": "space", **params, "local": "1"})


def guard(route):
    request = route.request
    if request.method == "POST" and request.url.endswith("/api/space/refresh"):
        return route.fulfill(status=200, content_type="application/json",
                             body=json.dumps(dict(running=False, message="Refresh paused for this capture")))
    if request.method == "POST" and "/api/history/system" in request.url:
        body = json.loads(request.post_data or "{}")
        if body.get("cursor") != CURSOR or body.get("q"):
            return route.abort()
    return route.continue_()


def settle(page, seconds=1.6):
    page.wait_for_load_state("networkidle")
    time.sleep(seconds)


def shot(page, out, name):
    page.add_style_tag(content=BLUR)
    time.sleep(0.3)
    page.screenshot(path=str(out / name))
    print("captured", name)


def terminal(page, out, name, command, output):
    lines = html.escape(output.strip()[:3500])
    page.set_content(f"""<body style="margin:0;background:#06101b;color:#d7e4e0;font:15px/1.45 ui-monospace,Menlo,monospace;padding:34px">
      <div style="color:#8fd3c9;margin-bottom:14px">THE SAME ACTION FROM THE CLI — real output of the rail's copied command</div>
      <div style="color:#f0cf89;margin-bottom:18px;white-space:pre-wrap">$ {html.escape(command)}</div>
      <pre style="margin:0;white-space:pre-wrap">{lines}</pre></body>""")
    page.screenshot(path=str(out / name))
    print("captured", name)


def main(argv):
    base = os.environ.get("NAVCOM_BRIDGE_URL", "").rstrip("/") + "/"
    if not base.startswith("http") or len(argv) != 1:
        sys.exit("usage: NAVCOM_BRIDGE_URL=http://127.0.0.1:PORT/ capture_cockpit_tour.py <tourDir>")
    out = Path(argv[0]); out.mkdir(parents=True, exist_ok=True)
    from playwright.sync_api import sync_playwright
    with sync_playwright() as play:
        browser = play.chromium.launch(channel="chrome", headless=True)
        try:
            context = browser.new_context(viewport={"width": 1440, "height": 900})
            context.route("**/api/**", guard)
            page = context.new_page()
            page.goto(url(base, place="")); page.wait_for_selector("[data-place]"); settle(page)
            shot(page, out, "01-galaxy-system-hues.png")

            page.goto(url(base, place=SYRA)); page.wait_for_selector(f'[data-place="{MOBILE}"]'); settle(page)
            shot(page, out, "02-syra-hue-family.png")

            page.click(f'[data-place="{MOBILE}"]'); settle(page)
            shot(page, out, "03-product-action-rail.png")

            command = page.locator(".space-inspector").get_by_text("navcom atlas files", exact=False).first.inner_text().lstrip("$ ").strip()
            page.get_by_role("button", name="Browse saved files").first.click(); settle(page, 2.5)
            page.locator(".space-files-panel").first.scroll_into_view_if_needed(); settle(page, 0.6)
            shot(page, out, "04-rail-files-panel.png")
            argv = shlex.split(command.replace("…", ""))
            result = subprocess.run(argv, capture_output=True, text=True, timeout=120)
            terminal(context.new_page(), out, "05-cli-twin-same-files.png", command, result.stdout or result.stderr)

            page.goto(url(base, place="")); page.wait_for_selector("[data-place]"); settle(page)
            page.locator('[data-place*="star"]').first.click(); settle(page)
            shot(page, out, "06-star-rail.png")
            ask = page.get_by_role("button", name="Ask expert")
            if ask.count():
                ask.first.click(); settle(page, 1)
                shot(page, out, "07-ask-opens-review-not-send.png")
                page.keyboard.press("Escape"); settle(page, 0.5)

            page.goto(url(base, place=SYRA, at=AT, time_cursor=CURSOR)); page.wait_for_selector(f'[data-place="{MOBILE}"]'); settle(page, 2.5)
            shot(page, out, "08-syra-as-of-oct-1.png")

            landed = dict(place=DISTRICT, q="login", at=AT, time_cursor=CURSOR, time_product=MOBILE, time_group=DISTRICT,
                          time_result=RESULT, time_origin=SYRA, time_origin_q="", time_origin_cursor=CURSOR)
            page.goto(url(base, **landed)); page.wait_for_selector(".space-evidence, .space-match-text"); settle(page, 2.5)
            shot(page, out, "09-dated-district-login.png")
            page.get_by_role("button", name="Open source").first.click(); page.wait_for_selector(".space-source-code"); settle(page, 1)
            shot(page, out, "10-pinned-source-reader.png")
            page.keyboard.press("Escape"); settle(page, 1)
            page.reload(); page.wait_for_selector(".space-evidence, .space-match-text"); settle(page, 4.5)
            shot(page, out, "11-reload-keeps-dated-journey.png")

            narrow = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True)
            narrow.route("**/api/**", guard)
            small = narrow.new_page(); small.goto(url(base, place=SYRA)); small.wait_for_selector(f'[data-place="{MOBILE}"]'); settle(small)
            small.click(f'[data-place="{MOBILE}"]'); settle(small)
            small.locator(".space-inspector").scroll_into_view_if_needed(); settle(small, 0.6)
            shot(small, out, "12-narrow-390-product-rail.png")

            calm = browser.new_context(viewport={"width": 1440, "height": 900}, reduced_motion="reduce")
            calm.route("**/api/**", guard)
            still = calm.new_page(); still.goto(url(base, place=SYRA)); still.wait_for_selector(f'[data-place="{MOBILE}"]'); settle(still)
            still.click(f'[data-place="{MOBILE}"]'); still.get_by_role("button", name="Fly to").first.click(); settle(still, 1.2)
            shot(still, out, "13-reduced-motion-arrival.png")
        finally:
            browser.close()


if __name__ == "__main__":
    main(sys.argv[1:])
