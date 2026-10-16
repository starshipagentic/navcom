"""Authored historical names never come from synthetic snapshot addresses."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

import navcom_system_history as system


def chart(clues, manifests=(), *, files=("README.md",), scope="."):
    anchor = dict(id="planet:orchard", kind="planet", parent_id="system:coast",
                  current_label="CURRENT ORCHARD", position=dict(x=145, y=83))
    plan = dict(parents=[], anchors=[anchor], pins={anchor["id"]:dict(include=[scope])})
    data = dict(repository="/fixture/orchard", commit="b"*40, tree="c"*40,
                authored_at="2025-03-01T00:00:00Z", committed_at="2025-03-01T00:00:00Z",
                snapshot=dict(files=[dict(path=p) for p in files], snapshot_path="/cache/"+"a"*64),
                manifests=list(manifests), product_clues=clues, structure=dict(token_groups=[]))
    return system._chart(plan, {"saved":dict(scope_ids=[anchor["id"]], data=data)})["nodes"][0]


def test_saved_analysis_is_evidence_not_historical_identity():
    analysis = dict(text="a"*64+" repository.", basis="starforge_project_analysis", relative_root=".")
    readme = dict(text="Original Orchard Field research notes.", basis="harvested_readme",
                  path="/cache/artifact/source/README.md", relative_root=".")
    row = chart([analysis, readme])
    assert row["label"] == readme["text"]
    assert row["label_source"]["basis"] == "harvested_readme"
    assert row["label_source"]["path"] == readme["path"]
    assert row["label_source"]["commit"] == row["commit"]
    assert row["clues"] == [analysis, readme]  # Keep attributed native evidence.
    assert row["current_label"] == "CURRENT ORCHARD"
    assert row["id"] == "planet:orchard" and row["position"] == dict(x=145, y=83)


def test_committed_manifest_name_stays_authoritative_even_when_hash_shaped():
    name = "d"*64  # Authored identity must not be rejected by a hash heuristic.
    row = chart([dict(text="README heading", basis="harvested_readme", relative_root=".")],
                [dict(path="package.json", metadata=dict(name=name))])
    assert row["label"] == name
    assert row["label_source"]["basis"] == "committed_manifest"
    assert row["label_source"]["path"] == "package.json"


def test_no_authored_name_keeps_unknown_identity_and_scope():
    clues = [dict(text="Opaque generated repository.", basis="starforge_project_analysis", relative_root="."),
             dict(text="Nested unrelated product", basis="harvested_readme", relative_root="apps/nested")]
    row = chart(clues, files=("source.py", "apps/nested/README.md"))
    assert row["label"] == "Committed source"
    assert row["label_source"]["basis"] == "unknown"
    assert row["historical_state"] == "committed"  # Files exist; their product name is unknown.
    missing = chart(clues, files=("source.py",), scope="renamed/path")
    assert missing["historical_state"] == "unknown"
    assert missing["label"] == "Historical content unknown"
    assert missing["current_label"] == "CURRENT ORCHARD"


@pytest.mark.skipif(not shutil.which("starforge"), reason="Optional native Starforge required")
def test_native_no_manifest_readme_label_and_pinned_replay(tmp_path):
    root = tmp_path/"orchard-field-notes"
    root.mkdir()
    env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1",
               GIT_AUTHOR_DATE="2025-03-01T00:00:00Z", GIT_COMMITTER_DATE="2025-03-01T00:00:00Z")
    def git(*args):
        return subprocess.run(["git", "-C", str(root), "-c", "user.name=Fixture", "-c",
                               "user.email=fixture@example.invalid", "-c", "commit.gpgsign=false",
                               "-c", "core.hooksPath="+os.devnull, *args],
                              env=env, capture_output=True, text=True, check=True).stdout.strip()
    git("init", "-q", "-b", "main")
    (root/"README.md").write_text("# Original Orchard\n\nField notes for coastal growing seasons.\n")
    (root/"orchard.py").write_text('"""Record seasonal field observations."""\ndef observation(day):\n    return day\n')
    git("add", "."); git("commit", "-qm", "Recorded orchard")
    commit = git("rev-parse", "HEAD")
    (root/"README.md").write_text("# UNCOMMITTED FUTURE NAME\n")
    galaxy = dict(id="galaxy:owner", kind="galaxy", label="Owner", parent_id=None,
                  position=dict(x=0,y=0), locations=[], evidence=[])
    planet = dict(id="planet:orchard", kind="planet", label="CURRENT DISPLAY", parent_id=galaxy["id"],
                  position=dict(x=200,y=300), locations=[dict(path=str(root))], evidence=[])
    cache = tmp_path/"space.json"
    cache.write_text(json.dumps(dict(schema_version=1,published=123,entities=[galaxy,planet],edges=[],coverage={})))
    first = system.view(galaxy["id"], "2025-04-01", space_cache=cache, cache_path=tmp_path/"history")
    row = next(n for n in first["nodes"] if n["id"] == planet["id"])
    assert row["historical_state"] == "committed"
    assert row["label"].startswith("Original Orchard ")
    assert row["label_source"]["basis"] == "harvested_readme"
    assert row["label_source"]["commit"] == commit
    assert "UNCOMMITTED FUTURE NAME" not in row["label"]
    assert not row["manifests"]
    assert any(c["basis"] == "starforge_project_analysis" for c in row["clues"])
    replay = subprocess.run([sys.executable, str(Path(system.__file__).with_name("navcom.py")),
                             "history", "system", "--cursor", first["cursor"], "--space-cache", str(cache),
                             "--cache", str(tmp_path/"history"), "--json"],
                            capture_output=True, text=True, check=True, timeout=60)
    repeated = json.loads(replay.stdout)
    again = next(n for n in repeated["nodes"] if n["id"] == planet["id"])
    assert repeated["session_id"] == first["session_id"]
    assert (again["label"], again["label_source"], again["position"]) == (row["label"], row["label_source"], row["position"])
