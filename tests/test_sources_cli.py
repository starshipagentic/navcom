"""Real console/Starforge integration. Optional runtime; no replacement search implementation."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]


def invoke(*args, env=None):
    return subprocess.run(
        [sys.executable, str(ROOT / "navcom.py"), "sources", *map(str, args)],
        capture_output=True,
        text=True,
        env=env,
    )


def test_help_and_list_need_no_starforge(tmp_path):
    env = dict(os.environ, NAVCOM_STARFORGE_PYTHON=str(tmp_path / "missing"))
    for args in [
        ("--help",),
        ("search", "--help"),
        ("list", "--cache", tmp_path, "--json"),
    ]:
        assert invoke(*args, env=env).returncode == 0
    result = invoke("search", "anything", "--cache", tmp_path, env=env)
    assert result.returncode != 0
    assert "navcom sources:" in result.stderr
    assert "Traceback" not in result.stderr


@pytest.mark.skipif(
    not shutil.which("starforge"), reason="Optional installed Starforge required"
)
def test_real_harvest_both_paths_and_atomic_cache(tmp_path):
    alpha = tmp_path / "alpha"
    beta = tmp_path / "beta"
    alpha.mkdir()
    beta.mkdir()
    code = "\n".join(
        ['"""Marmot workflow for orchestration."""', "def execute(value):"]
        + ["    step_" + str(i) + " = value + " + str(i) for i in range(22)]
        + ["    return step_21", ""]
    )
    for root in (alpha, beta):
        (root / "worker.py").write_text(code)
        (root / "README.md").write_text("# Signal proposals and protocol goals\n")
        (root / "tiny.ts").write_text("export const tinyMarmotPolicy = true;\n")
    # Broad search retains larger source files even when bounded grouping skips them.
    (alpha / "large.py").write_text("# largeSourceDiscoveryMarker\n" + "# filler\n" * 32000)
    (alpha / ".env").write_text("PRIVATE_ENV_MARKER=never-index")
    (alpha / "escape.py").symlink_to(beta / "worker.py")
    cache = tmp_path / "cache"

    def call(*args, ok=True):
        result = invoke(*args, "--cache", cache, "--json")
        if not ok:
            assert result.returncode != 0, result.stdout
            assert "Traceback" not in result.stderr
            return result
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)

    for root in (alpha, beta):
        data = call("harvest", root, "--index", tmp_path / "missing-index")
        assert data["analyzed_sources"] == 1
    assert call("refresh")["analyzed_sources"] == 0
    state = json.loads((cache / "current.json").read_text())
    assert len(state["sources"]) == 2
    coverage = state["sources"][0]["coverage"]
    assert ".env" in coverage["excluded"] and "escape.py" in coverage["excluded"]
    results = call("search", "marmot", "--within", "alpha")
    assert results["concept_hits"] and results["text_hits"]
    assert all(
        h["source"] == "alpha"
        for k in ("concept_hits", "text_hits")
        for h in results[k]
    )
    assert call("search", "marmot", "--within", "alpha")["query_cache_hit"]
    scoped = call("search", "marmot", "--within", "alpha", "--path", "tiny.ts")
    assert scoped["text_hits"] and all(h["source_path"].endswith("tiny.ts") for h in scoped["text_hits"])
    assert not scoped["concept_hits"]
    scoped_code = call("search", "marmot", "--within", "alpha", "--path", "worker.py")
    assert scoped_code["concept_hits"] and all(h["source_path"].endswith("worker.py") for h in scoped_code["concept_hits"])
    call("search", "marmot", "--path", "worker.py", ok=False)
    call("search", "marmot", "--within", "alpha", "--path", "../beta", ok=False)
    assert (Path(state["sources"][0]["artifact"]) / "structure.json").is_file()
    alpha_source = next(source for source in state["sources"] if source["label"] == "alpha")
    structure = json.loads((Path(alpha_source["artifact"]) / "structure.json").read_text())
    assert structure["coverage"]["max_file_bytes"] == 250000
    assert structure["coverage"]["oversized_paths"] == ["large.py"]
    assert not structure["coverage"]["complete"]
    large_hits = call("search", "largeSourceDiscoveryMarker", "--within", "alpha")["text_hits"]
    assert any(hit["source_path"] == str(alpha / "large.py") for hit in large_hits)

    for query, filename in [
        ("Signal proposals and protocol goals", "README.md"),
        ("tinyMarmotPolicy", "tiny.ts"),
    ]:
        data = call("search", query, "--within", "alpha", "--mode", "text")
        assert any(h["source_path"] == str(alpha / filename) for h in data["text_hits"])
    assert not call("search", "PRIVATE_ENV_MARKER")["text_hits"]
    assert not call("search", "ABSENT_3491")["text_hits"]
    call("search", "marmot", "--within", "unknown", ok=False)
    call("search", "[", "--regex", "--mode", "text", ok=False)
    # A literal regex metacharacter is accepted without --regex.
    call("search", "[", "--mode", "text")
    pointer = (cache / "current.json").read_bytes()
    # Searches remain on the published snapshot, even when source contents change.
    target = alpha / "README.md"
    pinned_read = call("read", "alpha", "README.md", "--limit", "4")
    assert "Signal proposals" in pinned_read["lines"][0]["text"]
    assert pinned_read["provenance"]["current_file_read"] is False
    stat = target.stat()
    target.write_text("# Otter revised protocol\n")
    os.utime(target, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert call("read", "alpha", "README.md", "--snapshot", pinned_read["snapshot"])["sha256"] == pinned_read["sha256"]
    assert call("search", "Signal proposals and protocol goals", "--within", "alpha")[
        "text_hits"
    ]
    assert call("refresh")["analyzed_sources"] == 1
    call("read", "alpha", "README.md", "--snapshot", pinned_read["snapshot"], ok=False)
    assert "Otter revised" in call("read", "alpha", "README.md")["lines"][0]["text"]
    assert not call(
        "search", "Signal proposals and protocol goals", "--within", "alpha"
    )["text_hits"]
    assert call("search", "Otter revised protocol", "--within", "alpha")["text_hits"]
    (alpha / "tiny.ts").unlink()
    assert call("refresh")["analyzed_sources"] == 1
    assert not call("search", "tinyMarmotPolicy", "--within", "alpha")["text_hits"]
    # A failed refresh leaves both paths readable at the previous generation.
    pointer = (cache / "current.json").read_bytes()
    (alpha / "huge.py").write_bytes(b"x" * (2 * 1024 * 1024 + 1))
    call("refresh", ok=False)
    assert (cache / "current.json").read_bytes() == pointer
    assert call("search", "marmot")["concept_hits"]
    (alpha / "huge.py").unlink()
    import fcntl

    with (cache / "writer.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert "Another source harvest" in call("refresh", ok=False).stderr
        assert call("search", "marmot")["text_hits"]
    call("harvest", alpha, "--include", "../beta", ok=False)
    assert (cache / "current.json").read_bytes() == pointer


@pytest.mark.skipif(not shutil.which("starforge"), reason="Optional installed Starforge required")
def test_selected_harvest_retains_offline_published_sources(tmp_path):
    old,new=tmp_path/'old',tmp_path/'new'
    for root in (old,new):
        root.mkdir()
        (root/'README.md').write_text(root.name+' marshmallow protocol decisions\n')
    cache=tmp_path/'cache'
    def cli(*args,ok=True):
        result=invoke(*args,'--cache',cache,'--json')
        assert (result.returncode==0)==ok,result.stderr
        return json.loads(result.stdout) if ok else result
    cli('harvest',old,'--index',tmp_path/'no-index')
    before=json.loads((cache/'current.json').read_text())
    original=before['sources'][0]
    old.rename(tmp_path/'offline-original')
    appended=cli('harvest',new,'--index',tmp_path/'no-index')
    assert appended['analyzed_sources']==1 and appended['retained_sources']==1 and appended['sources']==2
    after=json.loads((cache/'current.json').read_text())
    assert after['sources'][0]==original
    assert [s['label'] for s in after['sources']]==['old','new']
    assert cli('search','marshmallow','--within','old')['text_hits']
    pointer=(cache/'current.json').read_bytes()
    repeat=cli('harvest',new,'--index',tmp_path/'no-index')
    assert repeat['analyzed_sources']==0 and repeat['cached_sources']==1 and repeat['retained_sources']==1
    assert not repeat['published'] and (cache/'current.json').read_bytes()==pointer
    cli('refresh',ok=False)
    assert (cache/'current.json').read_bytes()==pointer


@pytest.mark.skipif(not shutil.which("starforge"), reason="Optional installed Starforge required")
def test_both_search_paths_open_exact_snapshots_after_an_unrelated_harvest(tmp_path):
    root, other = tmp_path / 'quartz', tmp_path / 'violet'
    root.mkdir(); other.mkdir()
    (root / 'worker.py').write_text('\n'.join(
        ['"""Marmot optical calibration workflow."""', 'def calibrate(value):']
        + [f'    step_{i} = value + {i}' for i in range(24)] + ['    return step_23', '']))
    (root / 'README.md').write_text('# Marmot calibration\nThe retained documentation.\n')
    (other / 'README.md').write_text('# Violet\nUnrelated source.\n')
    cache = tmp_path / 'cache'

    def cli(*args, ok=True):
        result = invoke(*args, '--cache', cache, '--json')
        assert (result.returncode == 0) is ok, result.stderr
        return json.loads(result.stdout) if ok else result

    cli('harvest', root, '--index', tmp_path / 'no-index')
    found = cli('search', 'marmot', '--within', 'quartz')
    cached = cli('search', 'marmot', '--within', 'quartz')
    assert cached['query_cache_hit']
    assert cached['concept_hits'] == found['concept_hits']
    assert cached['text_hits'] == found['text_hits']
    hits = [next(hit for hit in found['concept_hits'] if hit['relative_path'] == 'worker.py'),
            next(hit for hit in found['text_hits'] if hit['relative_path'] == 'README.md')]
    opened = []
    for hit in hits:
        ref = hit['source_ref']
        assert ref['source_id'] == hit['source_id'] and ref['relative_path'] == hit['relative_path']
        assert ref['published'] == found['published']
        args = ('read', ref['source_id'], ref['relative_path'], '--line', ref['line'], '--limit', 2,
                '--snapshot', ref['snapshot'], '--published', ref['published'])
        opened.append((args, cli(*args)))
    # Live edits do not replace the published code/documents underneath a hit.
    (root / 'README.md').write_text('UNHARVESTED_FUTURE_CONTENT\n')
    cli('harvest', other, '--index', tmp_path / 'no-index')
    for args, before in opened:
        after = cli(*args)
        assert after['lines'] == before['lines'] and after['sha256'] == before['sha256']
        assert after['published'] != before['published']
        assert after['provenance']['current_file_read'] is False
        assert after['provenance']['publication_changed'] is True
    # Once that source actually refreshes, neither old artifact pin may be
    # silently redirected to the newly published source.
    cli('harvest', root, '--index', tmp_path / 'no-index')
    for args, _ in opened:
        assert 'snapshot changed' in cli(*args, ok=False).stderr
