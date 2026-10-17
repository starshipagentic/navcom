#!/usr/bin/env python3
"""Turn a captured e2e proof tour into ONE animated .gif with multiple slides.

A narrated title card (story beats), every numbered screenshot as its own
captioned slide, then a closing verdict card. Python port of the house
``build-tour-gif.mjs`` so NavCom can rebuild its tours from this repository.

Usage:
    .venv/bin/python scripts/build_tour_gif.py docs/e2e-tours/<date>/<topic>

Reads <tourDir>/tour.json for narration:
    {title, eyebrow, plan, context, proofTarget, beats: [], captions: {"01-x.png": "..."},
     verdict: {headline, lines: []}}
Needs Playwright (Python) with Google Chrome, and ffmpeg. Emits <tourDir>/<topic>.gif.
"""
import base64
import html
import json
import shutil
import subprocess
import sys
from pathlib import Path

W, H = 1600, 1000
CSS = f"""
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ width: {W}px; height: {H}px; background: #0b1220; color: #e6edf7;
         font-family: -apple-system, "Helvetica Neue", Arial, sans-serif; display: flex; }}
  .rail {{ width: 34%; background: #0f1b2e; padding: 56px 44px; display: flex;
          flex-direction: column; gap: 26px; }}
  .num {{ width: 96px; height: 96px; border-radius: 50%; background: #3b82f6; color: #fff;
         font-size: 46px; font-weight: 700; display: flex; align-items: center; justify-content: center; }}
  .eyebrow {{ color: #38bdf8; font-size: 15px; font-weight: 700; letter-spacing: .14em; }}
  h1 {{ font-size: 44px; line-height: 1.12; font-weight: 800; }}
  .chip {{ border: 2px solid #3b82f6; border-radius: 12px; padding: 14px 16px; font-size: 17px;
          font-weight: 600; color: #dbeafe; background: #12213a; }}
  .ctx {{ font-size: 19px; line-height: 1.5; color: #b6c6dd; }}
  .target {{ border: 2px solid #f59e0b; border-radius: 12px; padding: 14px 16px;
            font-size: 16px; color: #fde68a; margin-top: auto; }}
  .main {{ flex: 1; padding: 56px 52px; display: flex; flex-direction: column; gap: 22px; }}
  h2 {{ font-size: 38px; font-weight: 800; margin-bottom: 8px; }}
  .beat {{ border: 2px solid #22c55e; border-radius: 14px; padding: 18px 22px;
          font-size: 21px; font-weight: 600; background: #0e1d2b; }}
  .verdict {{ border-color: #38bdf8; }}
"""
SHOT_CSS = f"""
  body {{ display: block; padding: 0; }}
  .cap {{ height: 132px; padding: 26px 44px; background: #0f1b2e; display: flex;
         align-items: center; gap: 20px; border-bottom: 3px solid #3b82f6; }}
  .badge {{ min-width: 62px; height: 62px; border-radius: 50%; background: #3b82f6; color: #fff;
           font-size: 27px; font-weight: 700; display: flex; align-items: center; justify-content: center; }}
  .capText {{ font-size: 25px; font-weight: 600; line-height: 1.3; }}
  .stage {{ height: {H - 132}px; display: flex; align-items: center; justify-content: center;
           background: #0b1220; padding: 22px; }}
  .stage img {{ max-width: 100%; max-height: 100%; border-radius: 10px;
               box-shadow: 0 12px 40px rgba(0,0,0,.55); }}
"""


def esc(value):
    return html.escape(str(value or ""))


def main(argv):
    if len(argv) != 1:
        sys.exit("usage: build_tour_gif.py <tourDir>")
    tour = Path(argv[0]).resolve()
    meta = json.loads((tour / "tour.json").read_text()) if (tour / "tour.json").exists() else {}
    shots = sorted(p.name for p in tour.iterdir()
                   if p.suffix.lower() in {".png", ".jpg", ".jpeg"} and p.name[:1].isdigit())
    if not shots:
        sys.exit(f"no numbered screenshots found in {tour}")
    slides = tour / ".slides"
    shutil.rmtree(slides, ignore_errors=True)
    slides.mkdir()
    from playwright.sync_api import sync_playwright
    with sync_playwright() as play:
        browser = play.chromium.launch(channel="chrome", headless=True)
        try:
            page = browser.new_page(viewport={"width": W, "height": H})

            def card(body, name):
                page.set_content(f"<style>{CSS}</style>{body}", wait_until="domcontentloaded")
                page.screenshot(path=str(slides / name))

            card(f"""<div class="rail"><div class="num">0</div>
                 <div class="eyebrow">{esc(meta.get('eyebrow', 'E2E PROOF TOUR'))}</div>
                 <h1>{esc(meta.get('title', tour.name))}</h1>
                 {f'<div class="chip">{esc(meta["plan"])}</div>' if meta.get('plan') else ''}
                 <div class="ctx">{esc(meta.get('context'))}</div>
                 {f'<div class="target">Proof target: {esc(meta["proofTarget"])}</div>' if meta.get('proofTarget') else ''}
                 </div><div class="main"><h2>Story beats</h2>
                 {''.join(f'<div class="beat">{esc(b)}</div>' for b in meta.get('beats', []))}</div>""",
                 "000-title.png")
            for number, shot in enumerate(shots, 1):
                caption = meta.get("captions", {}).get(shot) or Path(shot).stem.split("-", 1)[-1].replace("-", " ")
                mime = "image/png" if shot.lower().endswith(".png") else "image/jpeg"
                data = base64.b64encode((tour / shot).read_bytes()).decode()
                page.set_content(f"""<style>{CSS}{SHOT_CSS}</style>
                    <div class="cap"><div class="badge">{number}</div><div class="capText">{esc(caption)}</div></div>
                    <div class="stage"><img src="data:{mime};base64,{data}"/></div>""", wait_until="load")
                page.screenshot(path=str(slides / f"{number:03d}-shot.png"))
            if meta.get("verdict"):
                verdict = meta["verdict"]
                card(f"""<div class="rail"><div class="num">&#10003;</div><div class="eyebrow">VERDICT</div>
                     <h1>{esc(verdict.get('headline', 'What this proves'))}</h1></div>
                     <div class="main"><h2>Captured live</h2>
                     {''.join(f'<div class="beat verdict">{esc(line)}</div>' for line in verdict.get('lines', []))}</div>""",
                     f"{len(shots) + 1:03d}-verdict.png")
        finally:
            browser.close()
    out = tour / f"{tour.name}.gif"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", "1/2.6", "-pattern_type", "glob",
                    "-i", str(slides / "*.png"), "-vf",
                    "scale=1200:-1:flags=lanczos,split[s0][s1];[s0]palettegen=stats_mode=diff[p];"
                    "[s1][p]paletteuse=dither=bayer:bayer_scale=3", "-loop", "0", str(out)], check=True)
    shutil.rmtree(slides, ignore_errors=True)
    print(f"built {out} ({out.stat().st_size / 1024 / 1024:.1f} MB, {len(shots) + 1 + bool(meta.get('verdict'))} slides)")


if __name__ == "__main__":
    main(sys.argv[1:])
