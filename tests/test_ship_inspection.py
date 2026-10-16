"""Read-only ship dossiers preserve locality, scope and readiness distinctions."""
import json
from pathlib import Path
import socket

import pytest

import navcom_ship_inspection as inspection


TOOL = Path.home() / ".codex" / "skills" / "ship-commission" / "scripts"


def entity(root, host="localhost", **extra):
    return dict(id="fleet:ship:fixture", kind="ship", label="Fixture ship",
                physical=dict(host=host, path=str(root)), **extra)


def receipt(path, root, **extra):
    data = dict(root=str(root), task="Recover the carried decision", status="completed-with-gaps",
                finished_at="2026-10-12T01:44:52+00:00", harness="Codex", native_thread="fixture-native-thread",
                native_cwd=str(root), resume_command="DO NOT EXECUTE THIS COMMAND",
                history_coverage=dict(sessions=24, messages=458, providers=["claude"], scope=["/old/source"],
                                      captured_at=["2026-10-11T04:49:19+00:00"], catalog_hashes_match=True,
                                      secret="NESTED_PRIVATE_VALUE"),
                remaining_gaps=["Cold resume untested"], secret="PRIVATE_VALUE", environment={"API_KEY": "PRIVATE_ENV"})
    data.update(extra)
    path.write_text(json.dumps(data))
    return path


def fake_tool(monkeypatch):
    calls = []
    monkeypatch.setattr(inspection, "_tool_identity", lambda root: dict(root=str(root), files={"fleet.py": "hash-one"}))
    def observe(root, tool):
        calls.append(root)
        return dict(state="recorded-descriptor", repositories=2, capture_evidence="seal-present-unverified",
                    descriptor_binding="stat-match-only", integrity="not checked", application_journey="not checked", captain="not checked")
    monkeypatch.setattr(inspection, "_observe", observe)
    return calls


def test_metadata_and_receipt_are_distinct_cached_and_whitelisted(tmp_path, monkeypatch):
    root = tmp_path / "ship"
    root.mkdir()
    record = receipt(tmp_path / "receipt.json", root)
    calls = fake_tool(monkeypatch)
    first = inspection.inspect_ship(entity(root), tmp_path / "cache", receipt_path=record)
    assert calls == [root]
    assert first["physical"]["availability"] == "present"
    assert first["physical"]["metadata_state"] == "recorded-descriptor"
    assert first["integrity"]["capture_evidence"] == "seal-present-unverified"
    assert first["integrity"]["status"] == "not checked"
    assert first["receiving"]["current_ready"] is None
    assert first["receiving"]["recorded_outcome"] == "completed-with-gaps"
    assert first["captain"]["viewpoint"]["thread"] == "fixture-native-thread"
    assert first["captain"]["route_recorded"]
    assert not first["captain"]["route_validated"] and not first["captain"]["takeover_verified"]
    assert first["context"]["messages"] == 458
    serialized = json.dumps(first)
    assert "PRIVATE" not in serialized and "DO NOT EXECUTE" not in serialized
    assert all(a["effect"] == "read-only" for a in first["next_actions"])
    second = inspection.inspect_ship(entity(root), tmp_path / "cache", receipt_path=record)
    assert len(calls) == 1 and second["cached"]
    assert second["observed_at"] == first["observed_at"]
    receipt(record, root, status="a revised historical outcome")
    changed = inspection.inspect_ship(entity(root), tmp_path / "cache", receipt_path=record)
    assert len(calls) == 2 and not changed["cached"]
    assert changed["receiving"]["recorded_outcome"] == "a revised historical outcome"
    refreshed = inspection.inspect_ship(entity(root), tmp_path / "cache", receipt_path=record, refresh=True)
    assert len(calls) == 3 and not refreshed["cached"]


@pytest.mark.parametrize("host", ["remote-test-host.invalid", None, ""])
def test_remote_or_unspecified_host_never_probes_the_physical_path(tmp_path, monkeypatch, host):
    root = tmp_path / "remote-mount-must-not-be-touched"
    root.mkdir()
    (root / "receipt.json").write_text("{}")
    record = receipt(tmp_path / "receipt.json", root)
    original_stat = inspection._stat
    original_safe = inspection._safe_path
    def stat(path):
        assert not inspection._contains(str(root), str(path)), "remote mount was probed locally"
        return original_stat(path)
    def safe(path):
        assert not inspection._contains(str(root), str(path)), "remote mount was traversed locally"
        return original_safe(path)
    monkeypatch.setattr(inspection, "_stat", stat)
    monkeypatch.setattr(inspection, "_safe_path", safe)
    monkeypatch.setattr(inspection, "_tool_identity", lambda *_: pytest.fail("Remote ship loaded local tools"))
    monkeypatch.setattr(inspection, "_observe", lambda *_: pytest.fail("Remote ship was observed locally"))
    result = inspection.inspect_ship(entity(root, host), tmp_path / "cache", receipt_path=record)
    assert result["physical"]["availability"] == "unobserved"
    assert result["context"]["sessions"] == 24  # A separate local historical receipt is allowed.
    ignored = inspection.inspect_ship(entity(root, host), tmp_path / "cache", receipt_path=root / "receipt.json")
    assert ignored["provenance"]["receipt"] is None


def test_exact_current_host_and_tool_identity_invalidate_cache(tmp_path, monkeypatch):
    root = tmp_path / "ship"
    root.mkdir()
    calls = fake_tool(monkeypatch)
    target = entity(root, socket.gethostname())
    inspection.inspect_ship(target, tmp_path / "cache")
    monkeypatch.setattr(inspection, "_tool_identity", lambda path: dict(root=str(path), files={"fleet.py": "hash-two"}))
    result = inspection.inspect_ship(target, tmp_path / "cache")
    assert len(calls) == 2 and not result["cached"]


@pytest.mark.parametrize('suffix',['','/.starship/commission/archive'])
def test_remote_snapshot_reference_never_scans_remote_commission_directory(tmp_path,monkeypatch,suffix):
    root='/Volumes/RemoteFixture'
    target=entity(root+suffix,'remote-test-host.invalid',record_id='archive',
                  provenance=dict(snapshot=root+'/bridge/data.json'))
    monkeypatch.setattr(inspection,'_discover_receipts',lambda *_:pytest.fail('Remote snapshot namespace was probed'))
    result=inspection.inspect_ship(target,tmp_path/'cache')
    assert result['physical']['availability']=='unobserved'
    assert result['provenance']['receipt'] is None


def test_wrong_receipt_cannot_apply_other_ship_readiness(tmp_path, monkeypatch):
    root = tmp_path / "ship"
    root.mkdir()
    calls = fake_tool(monkeypatch)
    record = receipt(tmp_path / "receipt.json", tmp_path / "another-ship", status="ready")
    result = inspection.inspect_ship(entity(root), tmp_path / "cache", receipt_path=record)
    assert len(calls) == 1 and not result["provenance"]["receipt"]["identity_match"]
    assert "recorded_outcome" not in result["receiving"]
    assert result["context"] == {} and result["receiving"]["current_ready"] is None
    assert any("does not match" in gap for gap in result["gaps"])


def test_private_or_linked_receipts_and_project_carried_tools_are_not_opened(tmp_path, monkeypatch):
    root = tmp_path / "ship"
    root.mkdir()
    private = tmp_path / "secrets"
    private.mkdir()
    record = receipt(private / "receipt.json", root)
    alias = tmp_path / "receipt.json"
    alias.symlink_to(record)
    monkeypatch.setattr(inspection, "_observe", lambda *_: pytest.fail("Untrusted tool invoked"))
    for source in (record, alias):
        result = inspection.inspect_ship(entity(root), tmp_path / "cache", tool_root=root / ".starship", receipt_path=source)
        assert result["provenance"]["receipt"] is None
        assert result["provenance"]["tool"] is None
        assert any("project-carried" in g for g in result["gaps"])


def test_snapshot_receipt_references_are_bounded_and_missing_runtime_is_useful(tmp_path):
    project = tmp_path / "starship"
    metadata = project / ".starship" / "commission" / "fixture"
    metadata.mkdir(parents=True)
    physical = "/remote/working/ship"
    record = receipt(metadata / "RESULT.json", physical)
    target = entity(physical, "remote-test-host.invalid", provenance=dict(snapshot=str(project / "bridge" / "data.json")),
                    evidence=[dict(path=str(record))])
    result = inspection.inspect_ship(target, tmp_path / "cache")
    assert result["provenance"]["receipt"]["path"] == str(record)
    assert result["receiving"]["mission"] == "Recover the carried decision"
    target["evidence"] = [dict(path=str(tmp_path / "receipt.json"))]
    receipt(tmp_path / "receipt.json", physical)
    outside = inspection.inspect_ship(target, tmp_path / "cache")
    assert outside["provenance"]["receipt"] is None


@pytest.mark.skipif(not (TOOL / "fleet.py").is_file(), reason="Optional installed Starship tools required")
def test_real_installed_observer_on_tiny_fixture_without_project_code(tmp_path):
    root = tmp_path / "ship"
    meta = root / ".starship"
    meta.mkdir(parents=True)
    (meta / "manifest.json").write_text(json.dumps(dict(repositories=[dict(target="active")], secret="NEVER_RETURN_MANIFEST_VALUE")))
    (meta / "seal.json").write_text("{}")
    (meta / "HANDOVER.md").write_text("Historical instructions only")
    # A carried module must never override the installed observer's imports.
    (meta / "fleet.py").write_text("raise RuntimeError('PROJECT CODE MUST NOT RUN')")
    result = inspection.inspect_ship(entity(root), tmp_path / "cache")
    assert result["physical"]["metadata_state"] == "stored-unverified"
    assert result["physical"]["repositories"] == 1
    assert result["integrity"]["capture_evidence"] == "seal-present-unverified"
    assert result["receiving"]["current_ready"] is None
    assert "NEVER_RETURN" not in json.dumps(result)
    assert any(a["id"] == "read-handover" for a in result["next_actions"])
    assert inspection.inspect_ship(entity(root), tmp_path / "cache")["cached"]


def test_only_exact_ship_entities_are_accepted(tmp_path):
    with pytest.raises(ValueError, match="exact catalog ship"):
        inspection.inspect_ship(dict(id="planet:a", kind="planet"), tmp_path)


def test_linked_metadata_cannot_probe_an_external_directory(tmp_path, monkeypatch):
    root = tmp_path / "ship"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "manifest.json").write_text("{}")
    (root / ".starship").symlink_to(outside, target_is_directory=True)
    monkeypatch.setattr(inspection, "_observe", lambda *_: pytest.fail("Linked metadata observer ran"))
    result = inspection.inspect_ship(entity(root), tmp_path / "cache")
    assert result["physical"]["availability"] == "unsafe-path"
    assert result["integrity"]["status"] == "not checked"


def test_receipt_discovery_uses_record_identity_and_latest_matching_record(tmp_path):
    project=tmp_path/'starship'
    meta=project/'.starship'/'commission'/'unfamiliar'
    old=meta/'captain-old';new=meta/'evidence'/'captain-current';other=meta/'captain-other'
    for p in (old,new,other):p.mkdir(parents=True)
    root='/remote/exact-working-root'
    receipt(old/'receipt.json',root,finished_at='2025-01-01T00:00:00Z',task='Old mission')
    receipt(new/'receipt.json',root,finished_at='2026-01-01T00:00:00Z',task='Current recorded mission')
    receipt(other/'receipt.json','/remote/different-working-root',finished_at='2027-01-01T00:00:00Z',task='Wrong ship')
    target=entity(root,'remote-test-host.invalid',record_id='unfamiliar',
                  provenance=dict(snapshot=str(project/'bridge'/'data.json')))
    result=inspection.inspect_ship(target,tmp_path/'cache')
    assert result['receiving']['mission']=='Current recorded mission'
    assert result['provenance']['receipt']['path']==str(new/'receipt.json')
    assert not result['provenance']['receipt_discovery']['truncated']
    assert inspection.inspect_ship(target,tmp_path/'cache')['cached']
    # A supplemental check must not erase the separately attributed history inventory.
    receipt(new/'receipt.json',root,finished_at='2026-01-01T00:00:00Z',history_coverage={})
    supplemental=inspection.inspect_ship(target,tmp_path/'cache')
    assert supplemental['context']['sessions']==24
    assert supplemental['context']['receipt_path']==str(old/'receipt.json')
    assert supplemental['context']['recorded_at']=='2025-01-01T00:00:00Z'
    assert supplemental['provenance']['context_receipt']['identity_match']
    # Changes are discovered without a manual catalog sync or explicit refresh.
    receipt(new/'receipt.json',root,finished_at='2026-02-01T00:00:00Z',task='New recorded mission')
    assert inspection.inspect_ship(target,tmp_path/'cache')['receiving']['mission']=='New recorded mission'
    target['record_id']='../unfamiliar'
    assert inspection.inspect_ship(target,tmp_path/'cache')['provenance']['receipt'] is None


def test_cli_and_web_use_same_exact_ship_dossier(tmp_path):
    import os
    import subprocess
    import sys
    import navcom
    import navcom_web
    root='/remote/fixture-ship'
    target=entity(root,'remote-test-host.invalid')
    target.update(parent_id='galaxy:owner',locations=[],evidence=[],position=dict(x=0,y=0))
    galaxy=dict(id='galaxy:owner',kind='galaxy',label='Your galaxy',parent_id=None,locations=[],evidence=[],position=dict(x=0,y=0))
    cache=tmp_path/'space.json'
    cache.write_text(json.dumps(dict(schema_version=1,published=123,entities=[galaxy,target],edges=[],coverage={})))
    script=Path(__file__).resolve().parents[1]/'navcom.py'
    command=[sys.executable,str(script),'atlas','inspect',target['id'],'--space-cache',str(cache),'--index',str(tmp_path/'missing.sqlite'),'--json']
    process=subprocess.run(command,capture_output=True,text=True)
    assert process.returncode==0,process.stderr
    first=json.loads(process.stdout)
    assert first['inspection']['physical']['availability']=='unobserved'
    assert first['inspection']['receiving']['current_ready'] is None
    second=json.loads(subprocess.run(command,capture_output=True,text=True,check=True).stdout)
    assert second['inspection']['cached']
    assert second['inspection']['observed_at']==first['inspection']['observed_at']
    assert not (tmp_path/'missing.sqlite').exists()
    # Route the web request through its normal manager, with identical cache selection.
    from unittest.mock import patch
    with patch.dict(os.environ,{'NAVCOM_SPACE_CACHE':str(cache)}):
        manager=navcom_web.WebApp(navcom,tmp_path/'missing.sqlite')
        served=manager.get(None,'/api/space/inspect',{'within':[target['id']]})
    assert served==second
