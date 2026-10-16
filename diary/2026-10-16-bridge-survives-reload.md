# October 16, 2026 — The bridge survives a reload

**Pain:** reloading the galaxy page while a response was in flight killed the
whole web bridge (exit 141), leaving "Historical view unavailable · Failed to fetch".

## Summary

Root cause: `navcom.py` loads its two original embedded scripts
(`log_clean_quick`, `log_search_fts5`) at import time. Both set
`SIGPIPE → SIG_DFL` so `navcom … | head` exits quietly. `navcom --menu` runs the
web bridge in that same process, so any browser that left mid-response sent a
fatal SIGPIPE. The fix is two small edits in `navcom_web.py` and leaves the CLI unchanged.

## Decisions

- **Chosen (KISS):** `serve()`, the long-running web entry only, restores
  `SIGPIPE → SIG_IGN`, and `Handler.send` wraps the header writes as well as the
  body in the existing `BrokenPipeError/ConnectionResetError` catch.
- **Rejected:** removing `SIG_DFL` from the embedded scripts would change the
  headless CLI that has worked daily for months. Putting it in `make_server`
  was also rejected, because `signal.signal` only works on the main thread and
  tests build servers in threads. A server rewrite was also rejected.
- **Owner caution recorded:** NavCom started as the simplest CLI for LLMs. Keep
  the web/atlas/starship growth from making that core feel like an integration.
  Prefer fixes at the edge (the web entry), not in the CLI.

## Snippets

```sh
.venv/bin/python -m pytest tests/test_web_disconnect.py tests/test_web.py -q   # 13 passed
uv build --offline --wheel --out-dir SCRATCH/build
uv pip install --python /Users/t/.local/pipx/venvs/navcom/bin/python --offline --no-deps --reinstall SCRATCH/build/navcom-0.10.0-py3-none-any.whl
nohup /Users/t/.local/bin/navcom --menu --no-browser > bridge.log 2>&1 &
```

The regression test failed first (connection refused partway through the abort
loop) and passed after the fix. On the live installed bridge, 50 RST-aborted
`GET /navcom_space.js` requests were followed by a 200 from the same PID.

## Files

- `navcom_web.py`: `serve()` ignores SIGPIPE, and `send()` catches disconnects during headers too.
- `tests/test_web_disconnect.py`: real `navcom.py --menu` subprocess, 20 aborted large
  responses, then the same process must answer 200.

## Appendix

- Default bridge relaunched at `http://127.0.0.1:63962/`, PID 76562, real
  default caches. The port is random per launch; the old 51605 is gone.
- The preview bridges 62811/62814 (PIDs 81521/81431) were already gone at resume.
- Still open from the [handoff](2026-10-16-galactic-navigation-handoff.md):
  the browser reload/Back/Forward/link proof of the dated journey. The connected
  Chrome extension showed an error page for the bridge URL while curl on this
  Mac got 200, likely because that Chrome isn't on this Mac. Also still open:
  the live microphone test and a real captain arrival.

## Follow-up: systems get their own colors (UI-only)

The owner found every solar system the same gold ("boring"). `art()` in
`navcom_space.js` now gives system and planet spheres a `tint(node.id)` style
(an FNV hash of the stable ID → `--hue`, `--sat`, `--light`, ring `--band`, and
`--stripe` density). `navcom_space.css` `.sphere-system`/`.sphere-planet` read
those variables, with the old colors as fallbacks. Nothing was added to
space.json or CLI output: color is presentation, the CLI-up layering rule.
**Rejected:** spreading hues evenly by rank among visible systems. That gives
more distinct colors, but a system's color would shift whenever a system is
added, and the owner should recognize Syra by color. Hash-only hues can collide,
so depth and banding vary too. A headless Chrome screenshot confirmed nine
distinguishable systems. 115 space/web tests passed.

The owner confirmed by hand that **voice and the Back button work** on the live bridge.

Tags: web-bridge, planet-colors, sigpipe, reload, kiss, cli-unchanged, regression-test. The web
bridge now survives visitors leaving mid-response, without touching CLI pipe behavior.
