"""Disposable native Starforge chronology proof; no production/cache changes."""
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import time

from starforge.analyzer import ProjectAnalyzer
from starforge.catalog_evolution import build_timeline, get_repo_creation_date
from starforge.file_evolution import trace_file_evolution


def main():
    started = time.perf_counter()
    env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
    with tempfile.TemporaryDirectory(prefix="navcom-history-") as temporary:
        base = Path(temporary)
        repo = base / "harvest" / "fixture" / "quartz"
        repo.mkdir(parents=True)

        def git(*args, extra=None, binary=False):
            completed = subprocess.run(
                ["git", "-c", "user.name=NavCom Fixture", "-c", "user.email=fixture@example.invalid",
                 "-c", "commit.gpgsign=false", "-c", "core.hooksPath=" + os.devnull,
                 "-C", str(repo), *args],
                check=True, capture_output=True, text=not binary, env=dict(env, **(extra or {})), timeout=15,
            )
            return completed.stdout if binary else completed.stdout.strip()

        git("init", "-q", "-b", "main")
        commits = []
        for name, month, mechanism, code in [
            ("Quartz Classic", "01", "Password login", "def password_login():\n    return 'password'\n"),
            ("Quartz Cloud", "06", "Cognito login", "def cognito_login():\n    return 'cognito'\n\ndef refresh_token():\n    return 'refresh'\n"),
        ]:
            (repo / "README.md").write_text(f"# {name}\n\n{mechanism}.\n")
            (repo / "package.json").write_text(json.dumps({"name": name.lower().replace(" ", "-"), "description": mechanism}, indent=2) + "\n")
            (repo / "app.py").write_text(code)
            git("add", "README.md", "package.json", "app.py")
            git("commit", "-qm", name, extra={"GIT_AUTHOR_DATE": f"2025-{month}-01T10:00:00Z",
                                             "GIT_COMMITTER_DATE": f"2025-{month}-02T11:00:00Z"})
            commits.append(git("rev-parse", "HEAD"))
        # Uncommitted changes and fabricated mtimes must not enter historical views.
        for filename in ("README.md", "package.json", "app.py"):
            with (repo / filename).open("a") as target:
                target.write("\nCURRENT_ONLY_UNCOMMITTED_MARKER\n")
            os.utime(repo / filename, (978307200, 978307200))
        status = git("status", "--porcelain")
        trace_start = time.perf_counter()
        traces = {filename: trace_file_evolution(repo, filename, max_commits=10)
                  for filename in ("app.py", "README.md", "package.json")}
        trace_seconds = round(time.perf_counter() - trace_start, 4)
        creation = get_repo_creation_date(repo)
        timeline = build_timeline(base / "harvest")
        views = []
        for sha in commits:
            snapshot = base / sha
            snapshot.mkdir()
            archive = git("archive", "--format=tar", sha, binary=True)
            with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
                tar.extractall(snapshot, filter="data")
            manifest = json.loads((snapshot / "package.json").read_text())
            assert all("CURRENT_ONLY_UNCOMMITTED_MARKER" not in file.read_text()
                       for file in snapshot.iterdir() if file.is_file())
            analysis = ProjectAnalyzer(dispatcher=False).analyze(str(snapshot), manifest["name"])
            views.append({"commit": sha, "manifest_name": manifest["name"], "summary": analysis["summary"],
                          "files": sorted(p.name for p in snapshot.iterdir()), "dirty_marker_absent": True})
        assert views[0]["manifest_name"] == "quartz-classic"
        assert "Cognito" not in (base / commits[0] / "README.md").read_text()
        assert traces["app.py"]["commits"][0]["added"] == ["password_login"]
        assert traces["app.py"]["commits"][1]["removed"] == ["password_login"]
        assert traces["app.py"]["commits"][1]["added"] == ["cognito_login", "refresh_token"]
        assert git("status", "--porcelain") == status
        report = {
            "git_dates": git("log", "--reverse", "--format=%H|%aI|%cI").splitlines(),
            "native_file_evolution": traces,
            "native_reported_creation_date": creation,
            "native_catalog_timeline": timeline,
            "creation_matches_first_commit": creation == "2025-01-01",
            "git_snapshot_native_analysis": views,
            "working_tree_unchanged": True, "fixture_removed_after_run": True,
            "native_trace_seconds": trace_seconds, "total_seconds": round(time.perf_counter() - started, 4),
        }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
