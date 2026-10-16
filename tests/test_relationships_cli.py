"""Public Atlas CLI uses the native cached relationship service end to end."""
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

import pytest

from test_relationships import example  # Shared native harvest fixture, not fake search output.


ROOT = Path(__file__).resolve().parents[1]
NATIVE = pytest.mark.skipif(not shutil.which("starforge"), reason="Optional native Starforge runtime required")


def command(*args, env=None):
    return subprocess.run(
        [sys.executable, str(ROOT / "navcom.py"), *map(str, args)],
        cwd=ROOT, capture_output=True, text=True, timeout=30,
        env=dict(os.environ, NAVCOM_NO_SKILLS="1", **(env or {})),
    )


def related_args(example, ref="planet:orchard"):
    return ["atlas", "related", ref, "--space-cache", example["chart"],
            "--source-cache", example["cache"], "--index", example["chart"].parent / "absent.sqlite"]


@NATIVE
def test_public_cli_uses_native_families_references_and_cache_without_an_index(example, navcom, monkeypatch):
    chart_before = example["chart"].read_bytes()
    state_before = (example["cache"] / "current.json").read_bytes()
    first = command(*related_args(example), "--json")
    assert first.returncode == 0, first.stderr
    data = json.loads(first.stdout)
    assert data["center"]["id"] == "planet:orchard"
    assert data["families"][0]["engine"] == "starforge.lineage.LineageDetector.detect_repo_lineages"
    assert [m["path"] for m in data["families"][0]["members"]] == ["engines/v1", "engines/v2", "engines/v3"]
    assert data["families"][0]["members"][1]["destination_ids"] == ["moon:v2"]
    reference = data["references"][0]
    assert reference["target_source_id"] == "instruments"
    assert reference["relative_path"] == "README.md" and reference["line"] == 2
    assert reference["destination_ids"] == ["planet:instrument"]
    assert data["harvest_invocations"] == 0 and not data["cached"]
    repeated = command(*related_args(example, "Orchard"), "--json")
    assert repeated.returncode == 0, repeated.stderr
    cached = json.loads(repeated.stdout)
    assert cached["cached"] and cached["fingerprint"] == data["fingerprint"]
    # The browser route consumes the identical service and server-owned caches.
    from navcom_web import WebApp
    monkeypatch.setenv("NAVCOM_SPACE_CACHE", str(example["chart"]))
    monkeypatch.setenv("NAVCOM_SOURCES_CACHE", str(example["cache"]))
    app = WebApp(navcom, example["chart"].parent / "absent.sqlite")
    web = app.get(None, "/api/space/related", {"within": ["Orchard"]})
    assert web == cached
    assert example["chart"].read_bytes() == chart_before
    assert (example["cache"] / "current.json").read_bytes() == state_before
    assert not (example["chart"].parent / "absent.sqlite").exists()
    # Follow the tool's published read command rather than opening the working tree.
    read = command(*shlex.split(reference["read_command"])[1:], "--json")
    assert read.returncode == 0, read.stderr
    passage = json.loads(read.stdout)
    assert passage["provenance"]["current_file_read"] is False
    assert any(str(example["target"]) in line["text"] for line in passage["lines"])


@NATIVE
def test_public_cli_query_keeps_native_search_inside_the_exact_place(example):
    result = command(*related_args(example, "moon:v2"), "--query", "calibration", "--json")
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["query"] == "calibration"
    assert data["source_total"] == 1 and data["next_offset"] is None
    evidence = data["evidence"][0]
    assert evidence["concept_hits"] and evidence["text_hits"]
    for kind in ("concept_hits", "text_hits"):
        assert all(hit["relative_path"].startswith("engines/v2/") for hit in evidence[kind])
    assert data["families"] == [] and data["references"] == []
    human = command(*related_args(example))
    assert human.returncode == 0, human.stderr
    assert "Suggested version family: engines" in human.stdout
    assert "Documented reference:" in human.stdout
    assert "neither changes the chart" in human.stdout


@pytest.mark.parametrize("args", [
    ("--limit", "0"), ("--limit", "101"), ("--seconds", "0"),
    ("--seconds", "31"), ("--seconds", "nan"), ("--offset", "-1"),
    ("--query", "x" * 501),
])
def test_public_cli_rejects_unbounded_inputs_before_reading_sources(tmp_path, args):
    result = command("atlas", "related", "planet:absent", "--space-cache", tmp_path / "missing.json",
                     "--source-cache", tmp_path / "missing-sources", "--index", tmp_path / "missing.sqlite", *args)
    assert result.returncode == 2 and "Traceback" not in result.stderr
    assert "limit 1–100" in result.stderr or "at most 500" in result.stderr
    assert list(tmp_path.iterdir()) == []


def test_relationship_help_is_discoverable_and_needs_no_index_or_runtime(tmp_path):
    env = {"HOME": str(tmp_path), "PATH": "/usr/bin:/bin", "NAVCOM_INDEX": str(tmp_path / "missing.sqlite")}
    for args in [("--help",), ("atlas", "--help"), ("atlas", "related", "--help"),
                 ("atlas", "help", "related"), ("help", "space"), ("help", "all")]:
        result = command(*args, env=env)
        assert result.returncode == 0, result.stderr
        assert "related" in result.stdout
        if "related" in args:
            for option in ("--query", "--limit", "--seconds", "--offset", "--space-cache", "--source-cache", "--json"):
                assert option in result.stdout
            assert "No new harvest" in result.stdout
            assert "not dated succession" in result.stdout
    assert not (tmp_path / "missing.sqlite").exists()
