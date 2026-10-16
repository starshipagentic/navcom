"""Automatic intake discloses native cache containment skips without scanning."""
import json
import sys

import pytest

import navcom_chart_refresh as service
import navcom_source_discovery as discovery


@pytest.mark.parametrize("same_root", [False, True])
def test_cache_containing_job_skips_before_discovery_or_harvest(tmp_path, monkeypatch, same_root):
    root = tmp_path / "workspace-container"
    cache = root if same_root else root / "tool-state" / "sources"
    cache.mkdir(parents=True)
    monkeypatch.setattr(discovery, "discover", lambda *_args, **_kwargs: pytest.fail("Container was scanned"))
    result = service._worker(dict(action="intake", job=dict(root=str(root), projects=[]),
                                  sources=str(cache), index="unused", boundaries=[], runtime="unused"))
    assert result["sources"] == 0 and not result["published"]
    assert result["skipped"][0]["path"] == str(root)
    assert "contains the source cache" in result["skipped"][0]["reason"]


def test_containment_skip_advances_pinned_queue_and_keeps_sibling_job(tmp_path, monkeypatch):
    root = tmp_path / "workspace-container"
    cache = root / "tool-state" / "sources"
    sibling = tmp_path / "independent-project"
    root.mkdir(); sibling.mkdir()
    index = tmp_path / "index.sqlite"; index.touch()
    chart = tmp_path / "space.json"
    rows = [dict(label=str(path), collection="projects:" + path.name) for path in (root, sibling)]
    scanned = []
    def discover(*args, **kwargs):
        scanned.extend(node["label"] for node in kwargs["projects"])
        return dict(sources=[], coverage=dict(skipped=[]))
    monkeypatch.setattr(discovery, "discover", discover)
    def run(request, *_args, **_kwargs):
        if request["action"] == "inventory":
            return dict(projects=rows, jobs=[dict(root=row["label"], projects=[row]) for row in rows],
                        grouping={}, truncated=False)
        if request["action"] == "runtime": return sys.executable
        if request["action"] == "intake": return service._worker(request)
        chart.write_text("{}"); return dict(destinations=2)
    monkeypatch.setattr(service, "_run", run)
    first = service.refresh(index, chart, cache, limit=1)
    assert first["visited"] == 1 and first["more"] and not first["failures"]
    assert len(first["skipped"]) == 1 and scanned == []
    second = service.refresh(index, chart, cache, limit=1)
    assert second["complete"] and second["visited"] == 2
    assert scanned == [str(sibling)] and len(second["skipped"]) == 1
    state = json.loads(service.state_path(cache, index_path=index, space_cache=chart).read_text())
    assert state["next"] == 2 and not state["failures"]
