#!/usr/bin/env python3
"""DNA speed gate: is the everyday headless CLI still fast? Manual; not part of pytest.

Runs `navcom` against your real index several times per probe and compares each median
with tests/dna_baseline.json. A probe fails when its median exceeds
max(baseline * 1.35, baseline + 0.25 s); the baselines were measured while a background
chart refresh was running, so they are noisy.

    python scripts/dna_perf.py                  # the installed navcom on PATH (what agents run)
    python scripts/dna_perf.py --source .       # this checkout; skill/daily/retention upkeep off
    python scripts/dna_perf.py --runs 9 --json
    python scripts/dna_perf.py --write-baseline # after an intended change, on a quiet machine

Searches behave exactly like daily use: they first index new transcripts into the real
index. Exit 0 = every probe within tolerance, 1 = a probe is slower, 2 = could not run.
"""
import argparse
import json
import os
import shutil
import statistics
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

BASELINE = Path(__file__).resolve().parent.parent / "tests" / "dna_baseline.json"
SEARCHES = {"sigpipe": ["sigpipe", "-n", "3"],
            "starforge harvest": ["starforge harvest", "-n", "3"],
            "the": ["the", "-n", "3"]}
RATIO, SLACK = 1.35, 0.25


def limit(baseline):
    return max(baseline * RATIO, baseline + SLACK)


def installed_python(exe):
    """The interpreter in the installed navcom's #! line (so --source compares like for like)."""
    first = Path(exe).read_bytes()[:400].split(b"\n", 1)[0].decode(errors="replace") if exe else ""
    return first[2:].strip().split()[0] if first.startswith("#!") else sys.executable


def commands(source):
    """{probe: argv} for the installed navcom, or for a checkout when source is given."""
    exe = shutil.which("navcom")
    python = installed_python(exe)
    if source:
        root = Path(source).resolve()
        if not (root / "navcom.py").is_file():
            raise SystemExit(f"dna_perf: no navcom.py in {root}")
        # like the installed console script: import the (bytecode-cached) module, call main()
        head = f"import sys; sys.path.insert(0, {str(root)!r}); "
        navcom = [python, "-c", head + "from navcom import main; sys.exit(main())"]
        importer = [python, "-c", head + "import navcom"]
    else:
        if not exe:
            raise SystemExit("dna_perf: no navcom on PATH (or pass --source DIR)")
        navcom, importer = [exe], [python, "-c", "import navcom"]
    probes = {name: navcom + argv for name, argv in SEARCHES.items()}
    probes["import navcom"] = importer
    return probes


def measure(argv, runs, env):
    times = []
    for _ in range(runs):
        start = time.perf_counter()
        # from $HOME: a navcom.py in the current directory would shadow the installed module
        proc = subprocess.run(argv, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, env=env, timeout=300,
                              cwd=str(Path.home()))
        times.append(round(time.perf_counter() - start, 3))
        if proc.returncode != 0:
            raise SystemExit(f"dna_perf: {' '.join(argv)} exited {proc.returncode}: "
                             f"{proc.stderr.decode(errors='replace')[-300:]}")
    return times


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--source", metavar="DIR", help="measure the navcom.py checkout in DIR instead of the installed navcom")
    p.add_argument("--runs", type=int, default=5, help="runs per probe (default 5)")
    p.add_argument("--json", action="store_true", help="print the measurements as JSON")
    p.add_argument("--write-baseline", action="store_true", help="replace tests/dna_baseline.json with these medians")
    args = p.parse_args(argv)
    env = dict(os.environ)
    if args.source:  # a dev checkout must not overwrite installed skill cards or schedule jobs
        env.update(NAVCOM_NO_SKILLS="1", NAVCOM_NO_DAILY="1", NAVCOM_NO_RETENTION_FIX="1")
    try:
        baseline = json.loads(BASELINE.read_text())["probes"]
    except (OSError, ValueError, KeyError) as exc:
        raise SystemExit(f"dna_perf: can't read {BASELINE}: {exc}")
    results, slow = {}, []
    for name, cmd in commands(args.source).items():
        runs = measure(cmd, max(1, args.runs), env)
        median = round(statistics.median(runs), 3)
        base = baseline.get(name, {}).get("median")
        ok = base is None or median <= limit(base)
        results[name] = {"runs": runs, "median": median, "baseline": base,
                         "limit": None if base is None else round(limit(base), 3), "ok": ok}
        if not ok:
            slow.append(name)
    if args.json:
        print(json.dumps(results, indent=1))
    else:
        print(f"{'probe':20s} {'median':>8s} {'baseline':>9s} {'limit':>7s}  status")
        for name, r in results.items():
            base = "-" if r["baseline"] is None else f"{r['baseline']:.3f}"
            lim = "-" if r["limit"] is None else f"{r['limit']:.3f}"
            print(f"{name:20s} {r['median']:8.3f} {base:>9s} {lim:>7s}  {'ok' if r['ok'] else 'SLOW'}")
    if args.write_baseline:
        BASELINE.write_text(json.dumps({
            "measured": f"{date.today()} by scripts/dna_perf.py"
                        + (f" --source {args.source}" if args.source else " (installed navcom)"),
            "probes": {name: {"runs": r["runs"], "median": r["median"]} for name, r in results.items()},
        }, indent=1) + "\n")
        print(f"wrote {BASELINE}")
        return 0
    if slow:
        print("dna_perf: slower than the gate: " + ", ".join(slow), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
