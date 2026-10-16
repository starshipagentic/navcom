"""Individual recorded turn dates must precede every historical content decision."""
import json
import io
import os
from pathlib import Path
import sqlite3

import pytest

from navcom_atlas import identity
import navcom_historical_conversations as history


@pytest.fixture
def archive(navcom, tmp_path):
    path = tmp_path / "index.sqlite"
    conn = navcom.open_index(path)
    conn.execute("CREATE TABLE IF NOT EXISTS session_ancestry(file TEXT PRIMARY KEY,parent_id TEXT,provider TEXT)")
    project = str(tmp_path / "Aurora")
    other = str(tmp_path / "Other")
    cache = tmp_path / "space.json"
    def node(id, kind, parent, project=None):
        return dict(id=id, kind=kind, parent_id=parent, label=id,
                    conversation_collections=["projects:" + identity(navcom.pretty_project(project))] if project else [],
                    locations=[], evidence=[], examples=[], position=dict(x=0, y=0))
    cache.write_text(json.dumps(dict(schema_version=1, published=123, coverage={}, edges=[], entities=[
        node("galaxy:owner", "galaxy", None),
        node("planet:aurora", "planet", "galaxy:owner", project),
        node("planet:other", "planet", "galaxy:owner", other)])))
    def add(ref, entries, *, provider="codex", parent="", current_project=None):
        key = str(tmp_path / (ref + ".jsonl"))
        conn.execute("INSERT INTO file_state VALUES (?,?,?,?,?)", (key, 9999999999, 999, 999, len(entries)))
        conn.execute("INSERT INTO file_meta VALUES (?,?,?,?)", (key, provider, current_project or project, "FUTURE_TITLE_SECRET"))
        conn.execute("INSERT INTO session_ancestry VALUES (?,?,?)", (key, parent, provider))
        for index, entry in enumerate(entries, 1):
            stamp, text, *role = entry
            cursor = conn.execute("INSERT INTO session_fts(text,role,file,ts,msg_index,provider) VALUES (?,?,?,?,?,?)",
                                  (text, role[0] if role else "user", key, stamp, index, provider))
            conn.execute("INSERT INTO turn_loc VALUES (?,?,?)", (key, index, cursor.lastrowid))
        conn.commit()
        return key
    def read(**kwargs):
        return history.view(navcom, conn, space_cache=cache, within="planet:aurora", as_of="2025-05-01", **kwargs)
    yield conn, add, read, cache, other
    conn.close()


def test_future_first_prompt_titles_and_annotations_never_label_old_turn(archive, navcom):
    conn, add, read, _, _ = archive
    key = add("old", [("2026-01-01T00:00:00Z", "FUTURE_FIRST_PROMPT"),
                       ("2025-04-01T00:00:00Z", "Aurora password login decision"),
                       ("2026-01-01T00:00:00Z", "FUTURE_SUMMARY Cognito")])
    navcom._ui_write(conn, "annotations", {key:dict(name="FUTURE_ANNOTATION_SECRET")})
    result = read(query="login")
    assert len(result["conversations"]) == 1
    node = result["conversations"][0]
    assert node["start"] == 2 and node["recorded_at"] == "2025-04-01T00:00:00Z"
    assert "password" in node["label"]
    assert "FUTURE_" not in json.dumps(result)
    assert result["coverage"]["future_turns_excluded"] == 2
    assert not read(query="Cognito")["conversations"]


def test_timezone_cutoff_is_inclusive_date_only_means_midnight(archive):
    _, add, read, _, _ = archive
    add("equal", [("2025-04-30T20:00:00-04:00", "equal login")])
    add("late", [("2025-05-01T00:00:00.000001Z", "future login")])
    add("earlier", [("2025-05-01T00:30:00+01:00", "earlier login")])
    result = read(query="login")
    assert {n["ref"] for n in result["nodes"]} == {"equal", "earlier"}
    assert result["as_of"] == "2025-05-01T00:00:00Z"


def test_missing_ambiguous_invalid_dates_do_not_borrow_mtime(archive):
    _, add, read, _, _ = archive
    add("undated", [("", "undated login"), (None, "missing login"),
                    ("2025-04-01", "date-only login"), ("2025-04-01T00:00:00", "naive login"),
                    ("nonsense", "bad login"), ("1743465600", "epoch login"),
                    ("2025-04-01T00:00:00Z", "dated login")])
    result = read(query="login")
    assert len(result["nodes"]) == 1 and result["nodes"][0]["start"] == 7
    c = result["coverage"]
    assert (c["scanned_turns"], c["dated_turns"], c["undated_turns"], c["invalid_timestamp_turns"]) == (7, 1, 2, 4)
    assert not c["complete"] and result["gaps"]


def test_parent_child_remain_linked_without_reading_logs_or_current_titles(archive, navcom, monkeypatch):
    _, add, read, _, _ = archive
    add("parent", [("2025-04-01T00:00:00Z", "old parent login")])
    add("child", [("2025-04-02T00:00:00Z", "old child login")], parent="parent")
    monkeypatch.setattr(navcom, "_session_parent", lambda *_: pytest.fail("Codex raw logs must not be opened"))
    monkeypatch.setattr(navcom, "session_meta", lambda *_: pytest.fail("Current titles must not be recovered"))
    monkeypatch.setattr(navcom, "_project_from_key", lambda *_: pytest.fail("Current raw metadata must not be recovered"))
    result = read()
    parent, child = [next(n for n in result["nodes"] if n["ref"] == ref) for ref in ("parent", "child")]
    assert child["parent"] == parent["id"] and child["id"] in parent["children"]
    assert parent["parent_status"] == "root_recorded" and child["parent_status"] == "returned"
    limited = read(limit=1)["nodes"][0]
    assert limited["ref"] == "child" and limited["parent_ref"] == "parent"
    assert limited["parent_status"] == "not_returned_or_undated"


def test_older_index_without_ancestry_is_unknown_not_root(archive):
    conn, add, read, _, _ = archive
    add("alone", [("2025-04-01T00:00:00Z", "login")])
    conn.execute("DROP TABLE session_ancestry");conn.commit()
    node = read()["nodes"][0]
    assert node["parent_status"] == "unknown" and node["parent_ref"] is None


def test_native_fts_is_scoped_before_result_limit_future_cannot_crowd_out(archive):
    _, add, read, _, other = archive
    for i in range(24):
        add("future-" + str(i), [("2026-01-01T00:00:00Z", "login")])
    add("wrong-project", [("2025-01-01T00:00:00Z", "login")], current_project=other)
    add("real", [("2025-01-01T00:00:00Z", "The old native login plan")])
    result = read(query="login", limit=1)
    assert [n["ref"] for n in result["nodes"]] == ["real"]
    assert result["coverage"]["future_turns_excluded"] == 24
    assert result["coverage"]["matching_turns"] == 1
    assert result["coverage"]["complete"]


def test_one_conversation_result_uses_matching_turn_not_unrelated_old_prompt(archive):
    _, add, read, _, _ = archive
    add("two", [("2025-01-01T00:00:00Z", "Unrelated welcome prompt"),
                ("2025-02-01T00:00:00Z", "password login strategy"),
                ("2025-02-02T00:00:00Z", "password login refinement")])
    result = read(query='"password login"')
    assert len(result["nodes"]) == 1 and result["nodes"][0]["matching_turns"] == 2
    assert "Unrelated" not in json.dumps(result)


def test_match_beyond_initial_text_window_has_readable_dated_evidence(archive):
    _, add, read, _, _ = archive
    add("long", [("2025-01-01T00:00:00Z", "irrelevant "*10000 + "native zebracornneedle decision")])
    node = read(query="zebracornneedle")["nodes"][0]
    assert "zebracornneedle" in node["excerpt"] and "zebracornneedle" in node["label"]


def test_catalog_is_one_bounded_generation(archive, monkeypatch):
    _, add, read, cache, _ = archive
    add("old", [("2025-01-01T00:00:00Z", "login")])
    original = Path.read_text
    monkeypatch.setattr(Path, "read_text", lambda self,*a,**k: pytest.fail("Do not reread the catalog") if self == cache else original(self,*a,**k))
    assert read()["catalog_published"] == 123


def test_tool_sized_catalog_reuses_shared_bound_without_widening_dated_scope(archive, monkeypatch):
    _, add, read, cache, other = archive
    add("old", [("2025-01-01T00:00:00Z", "Retained login decision")])
    add("future", [("2026-01-01T00:00:00Z", "FUTURE login decision")])
    add("elsewhere", [("2025-01-01T00:00:00Z", "OTHER login decision")], current_project=other)
    catalog = json.loads(cache.read_text())
    # Published source evidence can make a normal chart larger than the dated
    # reader's former 16 MiB cap. Its payload must not become dated turn text.
    catalog["entities"][1]["evidence"] = [{"type": "retained_source_metadata", "detail": "x" * (16 * 1024 * 1024)}]
    cache.write_text(json.dumps(catalog))
    assert 16 * 1024 * 1024 < cache.stat().st_size < history.navcom_space.MAX_JSON
    original = history.navcom_space._read
    calls = []
    def shared(path, *args, **kwargs):
        calls.append(path)
        return original(path, *args, **kwargs)
    monkeypatch.setattr(history.navcom_space, "_read", shared)
    result = read(query="login")
    assert calls == [cache]
    assert [node["ref"] for node in result["conversations"]] == ["old"]
    assert result["catalog_published"] == 123
    assert result["coverage"]["future_turns_excluded"] == 1


def test_shared_catalog_reader_limits_actual_stream_and_preserves_missing_default(tmp_path, monkeypatch):
    cache = tmp_path / "space.json"
    cache.write_text("{}")
    reads = []
    class GrowingPublication(io.BytesIO):
        def read(self, size=-1):
            reads.append(size)
            assert size == 65, "The shared reader must never request unbounded input"
            return super().read(size)
    with monkeypatch.context() as patch:
        patch.setattr(Path, "open", lambda *args, **kwargs: GrowingPublication(b"x" * 1000))
        with pytest.raises(ValueError, match="size limit"):
            history.navcom_space._read(cache, max_bytes=64)
    assert reads == [65]
    assert history.navcom_space._read(tmp_path / "missing.json", {"missing": True}) == {"missing": True}


def test_catalog_replacement_keeps_one_opened_scope_generation(archive, monkeypatch):
    _, add, read, cache, other = archive
    add("old", [("2025-01-01T00:00:00Z", "Original login decision")])
    add("elsewhere", [("2025-01-01T00:00:00Z", "Replacement login decision")], current_project=other)
    changed = json.loads(cache.read_text())
    changed["published"] = 456
    changed["entities"][1]["conversation_collections"] = changed["entities"][2]["conversation_collections"]
    replacement = cache.with_suffix(".next")
    replacement.write_text(json.dumps(changed))
    original = Path.open
    opened = []
    def replace_after_open(path, *args, **kwargs):
        stream = original(path, *args, **kwargs)
        if path == cache:
            opened.append(path)
            os.replace(replacement, cache)
        return stream
    monkeypatch.setattr(Path, "open", replace_after_open)
    result = read(query="login")
    assert opened == [cache]
    assert result["catalog_published"] == 123
    assert [node["ref"] for node in result["conversations"]] == ["old"]


@pytest.mark.parametrize("raw", ['{"schema_version":', '[]', '{"schema_version":1,"entities":{}}'])
def test_invalid_catalog_is_readable_error_never_global_fallback(archive, raw):
    _, _, read, cache, _ = archive
    cache.write_text(raw)
    with pytest.raises(history.HistoricalConversationError, match="Spatial catalog"):
        read()


def test_historical_catalog_keeps_shared_upper_bound(archive):
    _, _, read, cache, _ = archive
    with cache.open("wb") as stream:
        stream.truncate(history.navcom_space.MAX_JSON + 1)
    with pytest.raises(history.HistoricalConversationError, match="size limit"):
        read()


def test_budget_partial_counts_never_claim_full_history(archive):
    _, add, read, _, _ = archive
    add("many", [("2025-01-01T00:00:00Z", "login " + str(i)) for i in range(5)])
    result = read(query="login", max_turns=2)
    assert result["coverage"]["scanned_turns"] == 2
    assert not result["coverage"]["scan_complete"] and not result["coverage"]["complete"]
    assert result["gaps"]


def test_exact_turn_budget_with_no_remaining_turns_is_complete(archive):
    _, add, read, _, _ = archive
    add("one", [("2025-01-01T00:00:00Z", "login")])
    assert read(max_turns=1)["coverage"]["scan_complete"]


def test_no_writes_with_concurrent_writer_and_read_only_source(archive, navcom):
    conn, add, _, cache, _ = archive
    add("one", [("2025-01-01T00:00:00Z", "login")])
    db = conn.execute("PRAGMA database_list").fetchone()[2]
    writer = sqlite3.connect(db)
    ro = sqlite3.connect(Path(db).as_uri() + "?mode=ro", uri=True)
    before = conn.total_changes
    writer.execute("BEGIN IMMEDIATE")
    try:
        result = history.view(navcom, ro, within="planet:aurora", as_of="2025-05-01", space_cache=cache)
        assert len(result["nodes"]) == 1
        assert conn.total_changes == before and ro.total_changes == 0 and not ro.in_transaction
    finally:
        writer.rollback();writer.close();ro.close()


def test_unsupported_or_missing_scope_is_never_global(archive):
    _, add, read, cache, _ = archive
    add("one", [("2025-01-01T00:00:00Z", "login")])
    data = json.loads(cache.read_text())
    data["entities"][1]["conversation_collections"] = ["research:all", "projects:missing"]
    cache.write_text(json.dumps(data))
    result = read()
    assert not result["nodes"] and not result["coverage"]["complete"]
    assert result["coverage"]["unsupported_collections"] == ["research:all"]


@pytest.mark.parametrize("options", [dict(limit=0), dict(limit=True), dict(max_turns=0), dict(seconds=31), dict(seconds=float("nan")), dict(query="a"*2001)])
def test_bounds_are_validated(archive, options):
    with pytest.raises(ValueError):
        archive[2](**options)


def test_naive_cutoff_rejected(archive, navcom):
    conn, _, _, cache, _ = archive
    with pytest.raises(ValueError, match="offset"):
        history.view(navcom, conn, within="planet:aurora", space_cache=cache, as_of="2025-05-01T01:00:00")
