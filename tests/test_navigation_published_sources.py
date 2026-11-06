"""Global search includes published source evidence before chart publication."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest

import navcom_navigation as navigation
import navcom_sources
from test_navigation import catalog


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("within", [None, "", "galaxy:owner", "planet:fixture", "district:fixture"])
def test_only_unscoped_galaxy_requests_published_inventory(tmp_path, monkeypatch, within):
    space = catalog(tmp_path)
    requests = []
    monkeypatch.setattr(navcom_sources, "runtime", lambda: "native-runtime")

    def run(argv, **kwargs):
        request = json.loads(kwargs["input"])
        requests.append(request)
        return SimpleNamespace(returncode=0, stderr="", stdout=json.dumps(dict(
            sources=[], errors=[], coverage=dict(complete=True, published=77))))

    monkeypatch.setattr(navigation.subprocess, "run", run)
    result = navigation.evidence(None, None, space, tmp_path / "sources", within, "opal")
    assert len(requests) == 1
    assert requests[0].get("include_published_sources", False) is (not within)
    assert requests[0]["mode"] == "both"
    assert requests[0]["scopes"] == [dict(source_id="0", paths=["auth/login.py"] if within == "district:fixture" else [])]
    assert result["coverage"]["source_scope_policy"] == ("all_published_sources" if not within else "saved_place_paths")


def test_global_without_chart_sources_still_attempts_native_inventory(tmp_path, monkeypatch):
    space = catalog(tmp_path, source_count=0)
    monkeypatch.setattr(navcom_sources, "runtime", lambda: "native-runtime")
    calls = []

    def unavailable(argv, **kwargs):
        calls.append(json.loads(kwargs["input"]))
        return SimpleNamespace(returncode=1, stderr="No harvested sources; source cache unavailable", stdout="")

    monkeypatch.setattr(navigation.subprocess, "run", unavailable)
    result = navigation.evidence(None, None, space, tmp_path / "missing", "", "opal")
    assert calls == [dict(action="batch-search", cache=str(tmp_path / "missing"), query="opal",
                          scopes=[], mode="both", limit=12, time_budget_seconds=20,
                          include_published_sources=True)]
    assert not result["coverage"]["complete"]
    assert "source cache unavailable" in result["errors"][0]


@pytest.mark.skipif(not shutil.which("starforge"), reason="Optional installed Starforge required")
def test_global_worker_selects_and_searches_one_publication(tmp_path):
    script = '''
import json,sys
from pathlib import Path
import navcom_sources_worker as worker
cache=Path(sys.argv[1]);cache.mkdir()
worker.write(cache/'current.json',dict(published=41,sources=[dict(id='amber'),dict(id='cobalt')]))
worker.query_signature=lambda:'native-query'
calls=[]
def search(request,cache,*,state,extractor):
    calls.append(dict(id=request['within'],paths=request['paths'],published=state['published']))
    worker.write(cache/'current.json',dict(published=99,sources=[dict(id='future')]))
    return dict(concept_hits=[],text_hits=[],query_cache_hit=True,potentially_truncated=False,published=state['published'])
worker.combined_search=search
result=worker.batch_search(dict(query='opal',include_published_sources=True,
    scopes=[dict(source_id='amber',paths=['narrow.py'])]),cache)
print(json.dumps(dict(result=result,calls=calls)))
'''
    run = subprocess.run([navcom_sources.runtime(), "-c", script, str(tmp_path / "cache")],
                         cwd=ROOT, capture_output=True, text=True, timeout=20)
    assert run.returncode == 0, run.stderr
    data = json.loads(run.stdout)
    assert data["calls"] == [dict(id=sid, paths=[], published=41) for sid in ("amber", "cobalt")]
    assert data["result"]["coverage"]["published"] == 41
    assert data["result"]["coverage"]["searched_source_scopes"] == 2
    assert data["result"]["coverage"]["complete"]


@pytest.mark.skipif(not shutil.which("starforge"), reason="Optional installed Starforge required")
def test_public_cli_finds_uncharted_native_source_and_opens_pinned_snapshot(tmp_path):
    source = tmp_path / "unfamiliar-toolkit"
    source.mkdir()
    (source / "README.md").write_text("# Opal workflow\nAn authored retained command guide.\n")
    code = '\n'.join(['"""Opal workflow orchestration protocol."""', "def execute(value):"] +
                     [f"    step_{i} = value + {i}" for i in range(25)] + ["    return step_24", ""])
    (source / "workflow.py").write_text(code)
    sources = tmp_path / "sources"
    index = tmp_path / "absent.sqlite"

    def cli(*args):
        result = subprocess.run([sys.executable, str(ROOT / "navcom.py"), *map(str, args)],
                                capture_output=True, text=True, timeout=35)
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)

    harvested = cli("sources", "harvest", source, "--cache", sources, "--index", index, "--json")
    assert harvested["analyzed_sources"] == 1
    state = json.loads((sources / "current.json").read_text())
    sid = state["sources"][0]["id"]
    # The saved chart predates this publication and has no source associations.
    space = catalog(tmp_path, source_count=0)
    chart_bytes = space.read_bytes()
    source.rename(tmp_path / "offline-original")
    common = ["--space-cache", space, "--source-cache", sources, "--index", index, "--json"]
    result = cli("atlas", "navigate", "opal", "--global", *common)
    proof = result["evidence"]
    assert not proof["errors"]
    assert proof["coverage"]["searched_source_scopes"] == 1
    assert proof["coverage"]["published"] == state["published"]
    assert proof["coverage"]["source_hits_without_place_membership"] > 0
    hit_source = proof["sources"][0]
    assert hit_source["source_id"] == sid
    assert hit_source["concept_hits"] and hit_source["text_hits"]
    hit = next(h for h in hit_source["text_hits"] if h["relative_path"] == "README.md")
    assert hit["place_ids"] == []
    ref = hit["source_ref"]
    opened = cli("sources", "read", ref["source_id"], ref["relative_path"],
                 "--snapshot", ref["snapshot"], "--published", ref["published"],
                 "--cache", sources, "--json")
    assert any("Opal" in row["text"] for row in opened["lines"])
    assert opened["provenance"]["current_file_read"] is False
    repeated = cli("atlas", "navigate", "opal", "--global", *common)
    assert repeated["evidence"]["coverage"]["query_cache_hits"] == 1
    for within in ("planet:fixture", "district:fixture", "galaxy:owner"):
        scoped = cli("atlas", "navigate", "opal", "--within", within, *common)
        assert scoped["evidence"]["sources"] == []
        assert scoped["evidence"]["coverage"]["source_scopes"] == 0
    assert space.read_bytes() == chart_bytes
    assert not index.exists()
