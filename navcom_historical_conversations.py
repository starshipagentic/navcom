"""Dated indexed turns at current project addresses, never historical ownership.

This reader does not ingest logs, recover titles, or migrate the index. Undated
turns remain unavailable rather than borrowing a file mtime or a neighboring date.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
import time

from navcom_atlas import identity
from navcom_system_history import _utc
import navcom_space


ATTRIBUTION = ("Current project address plus an individually dated indexed turn. "
               "This does not establish ownership at the cutoff, membership in a "
               "selected Git commit, deployment, or a relationship to exact district files.")
TIMESTAMPS = ("Only session_fts.ts values containing an ISO timestamp with an explicit "
              "UTC offset are eligible. These are recorded index metadata, not verified "
              "wall-clock times. Missing, ambiguous and invalid timestamps are excluded; "
              "session mtimes, titles, summaries and neighboring turns never supply dates.")
ANCESTRY = ("Parent IDs come from indexed session_ancestry metadata or Claude's indexed "
            "subagent path convention. Relationships are not independently dated; an "
            "unreturned parent is not evidence that no parent exists.")


class HistoricalConversationError(ValueError):
    pass


def _recorded(value):
    if not isinstance(value, str) or not re.match(r"^\d{4}-\d{2}-\d{2}[Tt ]\d{2}:\d{2}", value):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00").replace("z", "+00:00"))
        if parsed.tzinfo is None:
            return None
        return parsed.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        return None


@contextmanager
def _reader(connection):
    """Use a bounded, consistent read transaction without changing the caller."""
    path = connection.execute("PRAGMA database_list").fetchone()[2]
    if not path:
        yield connection
        return
    reader = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True, timeout=1)
    try:
        reader.execute("BEGIN")
        yield reader
    finally:
        reader.rollback()
        reader.close()


def _scope(cache, within):
    path = Path(cache).expanduser()
    try:
        data = navcom_space._read(path)
    except (OSError, ValueError) as error:
        raise HistoricalConversationError("Spatial catalog unavailable: " + str(error)) from error
    if not isinstance(data, dict) or data.get("schema_version") != navcom_space.SCHEMA_VERSION:
        raise HistoricalConversationError("Spatial catalog unavailable; refresh current place addresses first")
    nodes = data.get("entities")
    if not isinstance(nodes, list) or any(not isinstance(node, dict) or
            not isinstance(node.get("id"), str) or not isinstance(node.get("label"), str) for node in nodes):
        raise HistoricalConversationError("Spatial catalog has invalid place addresses; refresh the chart")
    reference = within or navcom_space.GALAXY
    selected = next((n for n in nodes if n["id"] == reference), None)
    if selected is None:
        matches = [n for n in nodes if n["label"].casefold() == reference.casefold()]
        if len(matches) != 1:
            raise HistoricalConversationError("Spatial scope is ambiguous or unavailable; use an exact place ID")
        selected = matches[0]
    selected_ids = {selected["id"]}
    while True:
        more = selected_ids | {n["id"] for n in nodes if n.get("parent_id") in selected_ids}
        if more == selected_ids:
            break
        selected_ids = more
    collections = {c for n in nodes if n["id"] in selected_ids for c in n.get("conversation_collections", [])}
    return selected, collections, data.get("published")


def _metadata(api, conn, collections, coverage, deadline):
    """Read indexed project addresses only; never ask a harness for live metadata."""
    rows = conn.execute("SELECT s.file,m.provider,m.project FROM file_state s LEFT JOIN file_meta m ON m.file=s.file ORDER BY s.file")
    members = {}
    observed = set()
    for index, (key, provider, project) in enumerate(rows):
        if index >= 50000 or time.monotonic() > deadline:
            coverage["metadata_complete"] = False
            break
        coverage["indexed_sessions_considered"] += 1
        # Encoded paths need live filesystem guessing in pretty_project(). Do not
        # do that in a historical reader; the normal index pipeline can fill them.
        if not project or not (project.startswith("/") or project.startswith("~/")):
            coverage["unresolved_project_sessions"] += 1
            continue
        display = api.pretty_project(project)
        cid = "projects:" + identity(display)
        if cid not in collections:
            continue
        observed.add(cid)
        members[key] = dict(key=key, provider=provider or "unknown", current_project=display)
    coverage["missing_collections"] = sorted(collections - observed)
    coverage["scoped_sessions"] = len(members)
    return members


def _parents(api, conn, members):
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    saved = {}
    if "session_ancestry" in tables:
        columns = {r[1] for r in conn.execute("PRAGMA table_info(session_ancestry)")}
        if {"file", "parent_id", "provider"} <= columns:
            for key, parent, provider in conn.execute("SELECT file,parent_id,provider FROM session_ancestry"):
                if key in members and provider == members[key]["provider"] and isinstance(parent, str):
                    saved[key] = (parent, "indexed_session_ancestry")
    for key, member in members.items():
        parent, basis = saved.get(key, (None, "unknown"))
        if basis == "unknown" and member["provider"] == "claude":
            # Reuse the existing helper only for Claude: this branch reads the
            # indexed key string, whereas its Codex branch opens raw transcripts.
            parent, _ = api._session_parent(conn, key, "claude")
            if parent:
                basis = "indexed_claude_subagent_path"
            else:
                parent = None
        member.update(parent_ref=parent, ancestry_basis=basis)


def _scan(conn, members, cutoff, max_turns, deadline, coverage):
    eligible = {}
    keys = sorted(members)
    for start in range(0, len(keys), 300):
        if time.monotonic() > deadline:
            coverage["scan_complete"] = False
            break
        batch = keys[start:start + 300]
        remaining = max_turns - coverage["scanned_turns"]
        sql = ("SELECT l.rid,l.file,l.msg_index,f.ts,f.role,f.provider FROM turn_loc l "
               "JOIN session_fts f ON f.rowid=l.rid WHERE l.file IN (" + ",".join("?" * len(batch)) +
               ") AND f.role IN ('user','assistant') ORDER BY l.file,l.msg_index LIMIT ?")
        for rid, key, turn, stamp, role, provider in conn.execute(sql, [*batch, remaining + 1]):
            if coverage["scanned_turns"] >= max_turns or time.monotonic() > deadline:
                coverage["scan_complete"] = False
                break
            coverage["scanned_turns"] += 1
            bucket = coverage["providers"].setdefault(provider or "unknown", dict(scanned=0, dated=0, undated=0, invalid=0, future=0))
            bucket["scanned"] += 1
            if stamp is None or str(stamp).strip() == "":
                coverage["undated_turns"] += 1
                bucket["undated"] += 1
                continue
            date = _recorded(stamp)
            if date is None:
                coverage["invalid_timestamp_turns"] += 1
                bucket["invalid"] += 1
                continue
            coverage["dated_turns"] += 1
            bucket["dated"] += 1
            if date > cutoff:
                coverage["future_turns_excluded"] += 1
                bucket["future"] += 1
                continue
            eligible[rid] = dict(key=key, start=turn, role=role, provider=provider,
                                 recorded_at=date.isoformat().replace("+00:00", "Z"),
                                 timestamp_raw=stamp, epoch=date.timestamp())
        if not coverage["scan_complete"]:
            break
    coverage["eligible_turns"] = len(eligible)
    return eligible


def _matches(api, conn, eligible, query, deadline, coverage):
    if not query:
        return [(rid, 0.0) for rid in eligible], ""
    cooked = api.fts_prefix_query(query)
    if not cooked:
        raise HistoricalConversationError("Search needs at least one word or phrase")
    if not eligible:
        return [], cooked
    found = []
    # This is the same native text-only FTS query and rank NavCom already uses.
    # The complete dated eligibility set exists before any result cap is applied.
    rows = conn.execute("SELECT rowid,rank FROM session_fts WHERE session_fts MATCH ?", (f"text : ({cooked})",))
    for rid, rank in rows:
        if time.monotonic() > deadline:
            coverage["search_complete"] = False
            break
        if rid in eligible:
            found.append((rid, rank))
    return found, cooked


def view(api, conn, *, within="", as_of, space_cache, query="", limit=20,
         max_turns=100000, seconds=5):
    """Return bounded dated-turn evidence for a saved current place (read only).

    Date-only cutoffs mean midnight UTC, consistently with system history. The
    returned current place label is navigation metadata, never historical text.
    """
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
        raise HistoricalConversationError("limit must be an integer between 1 and 200")
    if isinstance(max_turns, bool) or not isinstance(max_turns, int) or not 1 <= max_turns <= 1000000:
        raise HistoricalConversationError("max_turns must be an integer between 1 and 1000000")
    if isinstance(seconds, bool) or not isinstance(seconds, (float, int)) or not 0 < seconds <= 30:
        raise HistoricalConversationError("seconds must be between 0 and 30")
    if not isinstance(query, str) or len(query) > 2000:
        raise HistoricalConversationError("query must be text of at most 2000 characters")
    as_of = _utc(as_of)
    cutoff = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
    selected, collections, published = _scope(space_cache, within)
    unsupported = sorted(c for c in collections if not c.startswith("projects:"))
    collections -= set(unsupported)
    coverage = dict(metadata_complete=True, scan_complete=True, search_complete=True,
                    indexed_sessions_considered=0, unresolved_project_sessions=0, scoped_sessions=0,
                    collection_count=len(collections), missing_collections=[], unsupported_collections=unsupported,
                    scanned_turns=0, dated_turns=0, undated_turns=0, invalid_timestamp_turns=0,
                    future_turns_excluded=0, eligible_turns=0, matching_turns=0, matching_conversations=0,
                    providers={}, max_turns=max_turns, time_budget_seconds=seconds)
    started = time.monotonic()
    deadline = started + seconds
    errors = []
    nodes = []
    cooked = ""
    if conn is None:
        errors.append("Conversation index unavailable; no undated content was substituted.")
        coverage["scan_complete"] = False
    else:
        with _reader(conn) as reader:
            reader.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
            try:
                members = _metadata(api, reader, collections, coverage, deadline)
                _parents(api, reader, members)
                eligible = _scan(reader, members, cutoff, max_turns, deadline, coverage)
                matches, cooked = _matches(api, reader, eligible, query, deadline, coverage)
                coverage["matching_turns"] = len(matches)
                best = {}
                counts = {}
                for rid, rank in matches:
                    hit = eligible[rid]
                    key = hit["key"]
                    score = (rank, -hit["epoch"], hit["start"])
                    counts[key] = counts.get(key, 0) + 1
                    if key not in best or score < best[key][0]:
                        best[key] = (score, rid)
                coverage["matching_conversations"] = len(best)
                chosen = sorted(best.values(), key=lambda item: (item[0], item[1]))[:limit]
                terms = api._query_terms(cooked) if cooked else []
                for _, rid in chosen:
                    hit = eligible[rid]
                    if cooked:
                        row = reader.execute("SELECT substr(snippet(session_fts,0,'«','»','…',48),1,65536),length(text) "
                                             "FROM session_fts WHERE session_fts MATCH ? AND rowid=?",
                                             (f"text : ({cooked})", rid)).fetchone()
                    else:
                        row = reader.execute("SELECT substr(text,1,65536),length(text) FROM session_fts WHERE rowid=?", (rid,)).fetchone()
                    if row is None:
                        continue
                    text, text_length = row
                    member = members[hit["key"]]
                    excerpt = text if cooked else api.make_snippet(text, terms, 48)
                    label = api._one_line(api.make_snippet(text, terms, 6 if terms else 16).replace("«", "").replace("»", ""), 120)
                    node = dict(id=identity(hit["key"]), kind="conversation", key=hit["key"],
                                ref=api.session_ref(hit["key"]), label=label or "Dated conversation turn",
                                label_basis="Matching individually dated indexed turn", excerpt=excerpt,
                                current_project=member["current_project"], parent_ref=member["parent_ref"],
                                ancestry_basis=member["ancestry_basis"], children=[], matching_turns=counts[hit["key"]],
                                text_window_truncated=text_length > 65536,
                                **{k:v for k,v in hit.items() if k not in ("key", "epoch")})
                    nodes.append(node)
            except sqlite3.OperationalError as exc:
                if "interrupted" not in str(exc).lower():
                    raise HistoricalConversationError("Historical index read failed: " + str(exc)) from exc
                coverage["scan_complete"] = False
                coverage["search_complete"] = False
                errors.append("Historical conversation read reached its time budget; coverage is partial.")
            finally:
                reader.set_progress_handler(None, 0)
    lookup = {(n["provider"], n["ref"]): n for n in nodes}
    for node in nodes:
        parent = lookup.get((node["provider"], node["parent_ref"]))
        node["parent"] = parent["id"] if parent else None
        node["parent_status"] = ("returned" if parent else "not_returned_or_undated" if node["parent_ref"] else
                                 "root_recorded" if node["ancestry_basis"] == "indexed_session_ancestry" else "unknown")
        if parent:
            parent["children"].append(node["id"])
    coverage["ancestry_unknown_results"] = sum(n["ancestry_basis"] == "unknown" for n in nodes)
    coverage["results_truncated"] = coverage["matching_conversations"] > len(nodes)
    coverage["timestamp_coverage_complete"] = (coverage["scan_complete"] and not coverage["undated_turns"] and not coverage["invalid_timestamp_turns"])
    coverage["complete"] = all(coverage[k] for k in ("metadata_complete", "scan_complete", "search_complete", "timestamp_coverage_complete")) and not (
        errors or unsupported or coverage["missing_collections"] or coverage["results_truncated"] or coverage["unresolved_project_sessions"])
    coverage["elapsed_seconds"] = round(time.monotonic() - started, 4)
    gaps = list(errors)
    if coverage["undated_turns"]:
        gaps.append("Undated indexed turns were excluded. Refresh through a timestamp-aware index pipeline; filesystem mtimes cannot repair this evidence.")
    if coverage["invalid_timestamp_turns"]:
        gaps.append("Ambiguous or invalid timestamps were excluded; an explicit UTC offset is required.")
    if not coverage["scan_complete"]:
        gaps.append("The bounded scan did not cover every scoped turn. Counts describe only inspected turns.")
    if coverage["missing_collections"] or unsupported:
        gaps.append("Some saved conversation collections could not be resolved from indexed project metadata.")
    if coverage["unresolved_project_sessions"]:
        gaps.append("Some indexed sessions lack a resolved current project address; their membership in this place is unknown.")
    return dict(schema_version=1, action="conversations", as_of=as_of, query=query, cooked_query=cooked,
                selected_place={k:selected[k] for k in ("id", "kind", "label")},
                address_basis="Current navigation catalog", catalog_published=published,
                conversation_basis=dict(type="current_project_dated_turn", query=query,
                                        file_relationship="unproven", commit_relationship="unproven"),
                attribution_policy=ATTRIBUTION, timestamp_policy=TIMESTAMPS, ancestry_policy=ANCESTRY,
                search_policy="Native NavCom text-only FTS5 query and rank; matching dated turns only, no current titles or summaries. Current index corpus statistics may affect ranking.",
                conversations=nodes, nodes=nodes, coverage=coverage, gaps=gaps)
