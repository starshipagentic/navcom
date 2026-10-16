"""Land inside a saved dated product and its existing native code groups.

The session, outcome and receipt are the authority. This service never resolves
today's chart, repository ownership or HEAD and never harvests source material.
"""
import json
import math
import os
from pathlib import Path
import re
import shlex
import signal
import subprocess
import sys
import tempfile
import time

import navcom_history as history
import navcom_source_reader as reader
import navcom_space as space
import navcom_system_history as system


KEY = re.compile(r"[0-9a-f]{64}\Z")
CURSOR = re.compile(r"([0-9a-f]{64}):(\d{1,6})\Z")
MAX_OUTPUT = 32 * 1024 * 1024
MAX_FILES = 10000
MAX_BYTES = 64 * 1024 * 1024
IDENTITY = "Saved navigation addresses and native code-group suggestions at one verified committed tree. Group membership is not historical ownership or a newly inferred product."
CONVERSATIONS = "No conversation is attributed to this commit or code group; current conversations are excluded."


def _record(cache_fd, relative):
    # Share the reader's openat/O_NOFOLLOW traversal, with the chart/result bound.
    with reader._open(cache_fd, relative) as fd:
        with os.fdopen(os.dup(fd), "rb") as stream:
            raw = stream.read(MAX_OUTPUT + 1)
    if len(raw) > MAX_OUTPUT:
        raise history.HistoryError("Saved historical metadata exceeds the landing read budget")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise history.HistoryError("Saved historical metadata is not an object")
    return data


def _path(value):
    path = reader._relative(value)
    if path.is_absolute() or str(path) != value:
        raise history.HistoryError("Saved historical scope contains a non-relative path")
    return value


def _inside(path, scopes):
    return any(scope == "." or path == scope or path.startswith(scope + "/") for scope in scopes)


def _command(request, group=None):
    argv = ["navcom", "history", "land", request["place_id"], "--cursor", request["cursor"],
            "--result-key", request["result_key"], "--cache", request["cache_path"],
            "--limit", str(request["limit"]), "--seconds", str(request["seconds"])]
    if group:
        argv.extend(["--group", group])
    if request["query"]:
        argv.append("--query=" + request["query"])
    return shlex.join(argv)


def _reference(snapshot, artifact, published, path, line=1):
    return dict(source_id=snapshot["id"], relative_path=path, line=line,
                snapshot=artifact, published=published, history=snapshot["id"])


def _execute(request):
    started = time.monotonic()
    cache = Path(request["cache_path"])
    session, offset = CURSOR.fullmatch(request["cursor"]).groups()
    fd = os.open(cache, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        plan = _record(fd, "systems/" + session + "/plan.json")
        jobs, anchors, parents = plan["jobs"], plan["anchors"], plan["parents"]
        if not all(isinstance(rows, list) and len(rows) <= 5000 for rows in (jobs, anchors, parents)) or int(offset) > len(jobs):
            raise history.HistoryError("Saved historical address set exceeds the landing bound")
        selected = [node for node in anchors if node.get("id") == request["place_id"]]
        matching = [job for job in jobs if request["place_id"] in job.get("scope_ids", [])]
        if len(selected) != 1 or len(matching) != 1:
            raise history.HistoryError("The selected product has no unique pinned repository in this journey")
        job = matching[0]
        if not KEY.fullmatch(job["id"]):
            raise history.HistoryError("Saved historical repository identity is invalid")
        outcome = _record(fd, f"systems/{session}/results/{request['result_key']}/{job['id']}.json")
        if not system._compatible_success(outcome, job):
            raise history.HistoryError("The selected product has no compatible completed snapshot in this saved result")
        data = outcome["data"]
        snapshot = data["snapshot"]
        if not isinstance(snapshot.get("id"), str) or not KEY.fullmatch(snapshot["id"]):
            raise history.HistoryError("Saved historical snapshot identity is invalid")
        prefix = "revisions/" + snapshot["id"]
        receipt = _record(fd, prefix + "/receipt.json")
        for field in ("id", "kind", "repository", "include", "commit", "tree", "files", "snapshot_path", "source_cache"):
            if receipt.get(field) != snapshot.get(field):
                raise history.HistoryError("Saved result no longer matches its immutable snapshot receipt")
        if snapshot.get("source_id") != snapshot["id"] or snapshot["source_cache"] != str(cache / prefix / "harvest"):
            raise history.HistoryError("Saved historical source cache does not match this receipt")
        records = receipt.get("files")
        if not isinstance(records, list) or len(records) > MAX_FILES:
            raise history.HistoryError("Historical snapshot exceeds the landing file bound")
        file_records = {}
        total = 0
        for record in records:
            path = _path(record["path"])
            if path == "." or path in file_records or type(record.get("bytes")) is not int or record["bytes"] < 0:
                raise history.HistoryError("Historical snapshot has invalid file records")
            total += record["bytes"]
            file_records[path] = record
        if total > MAX_BYTES:
            raise history.HistoryError("Historical snapshot exceeds the 64 MiB landing read bound")
        with reader._open(fd, prefix + "/snapshot", directory=True):
            system._worker(dict(action="validate_snapshot", snapshot=snapshot, history_cache=str(cache)))
        state = _record(fd, prefix + "/harvest/current.json")
        sources = [source for source in state.get("sources", []) if source.get("id") == snapshot["id"]]
        if len(sources) != 1 or sources[0].get("root") != snapshot["snapshot_path"]:
            raise history.HistoryError("Historical harvest no longer names the selected snapshot")
        artifact = Path(sources[0]["artifact"])
        if not KEY.fullmatch(artifact.name) or artifact != cache / prefix / "harvest/artifacts" / artifact.name:
            raise history.HistoryError("Historical harvest artifact is outside its receipt cache")
        with reader._open(fd, str(artifact.relative_to(cache)) + "/source", directory=True):
            pass
        with reader._open(fd, prefix + "/harvest", directory=True) as harvest_fd:
            reader._source_record(harvest_fd, cache / prefix / "harvest", cache / prefix / "harvest",
                                  snapshot["id"], artifact.name, state["published"])
        product = next(node for node in system._chart(plan, {job["id"]: outcome})["nodes"] if node["id"] == request["place_id"])
        if product["historical_state"] != "committed":
            raise history.HistoryError(product.get("historical_gap") or "Historical product is unavailable")
        scopes = plan["pins"][product["id"]]["include"]
        if not scopes or not all(_path(scope) for scope in scopes):
            raise history.HistoryError("Saved product scope is empty")
        product_files = sorted(path for path in file_records if _inside(path, scopes))
        if set(product_files) != set(product["files"]):
            raise history.HistoryError("Saved product files do not match its original scope")
        groups, seen = [], set()
        native_groups = product.get("structure", {}).get("token_groups", [])
        if not isinstance(native_groups, list) or len(native_groups) > 2000:
            raise history.HistoryError("Historical native groups exceed the landing bound")
        for native in native_groups:
            paths = native.get("paths")
            if not isinstance(paths, list) or not paths:
                continue
            paths = sorted(set(_path(path) for path in paths))
            if not set(paths).issubset(product_files):
                raise history.HistoryError("Historical native group exceeds its product scope")
            identity = space._id("historical-district", json.dumps([product["id"], snapshot["id"], paths]))
            if identity in seen:
                continue
            seen.add(identity)
            label, basis, terms = space._district_label(native.get("shared_tokens", []), paths)
            groups.append(dict(id=identity, kind="district", form="native_group_suggestion", label=label,
                parent_id=product["id"], position=space._position(identity, "district", product["position"]),
                historical_state="committed", commit=product["commit"], committed_at=product["committed_at"],
                files=paths, allowed_paths=paths, file_count=len(paths), group_id=identity,
                description="Existing native Starforge group in the selected committed product.",
                label_basis=basis, search_terms=terms, native_group=native,
                land_command=_command(request, identity), evidence_basis="Native grouping of immutable committed files"))
        group = None
        if request["group_id"]:
            group = next((node for node in groups if node["id"] == request["group_id"]), None)
            if group is None:
                raise history.HistoryError("The selected historical group is not in this product and snapshot")
        allowed = group["files"] if group else product_files
        files = [dict(path=path, relative_path=path, bytes=file_records[path]["bytes"],
                      source_ref=_reference(snapshot, artifact.name, state["published"], path)) for path in allowed]
        # Only saved parent metadata is used; older system pins may not record
        # ancestors above their selected system, so no current chart is consulted.
        parent_map = {node["id"]: node for node in parents}
        breadcrumbs, visited = [], set()
        parent_id = product.get("parent_id")
        while parent_id in parent_map and parent_id not in visited:
            visited.add(parent_id)
            node = parent_map[parent_id]
            breadcrumbs.insert(0, dict(node, historical_state="navigation_anchor"))
            parent_id = node.get("parent_id")
        structure = product.get("structure", {})
        product = dict(product, land_command=_command(request), file_count=len(product_files), allowed_paths=product_files,
                       structure={key: structure[key] for key in ("schema_version", "engine", "token_groups", "coverage", "meaning") if key in structure})
        breadcrumbs.append(product)
        if group:
            breadcrumbs.append(group)
        evidence = None
        if request["query"].strip():
            import navcom_sources
            worker = Path(navcom_sources.__file__).with_name("navcom_sources_worker.py")
            query = dict(action="search", cache=snapshot["source_cache"], query=request["query"], mode="both",
                         within=snapshot["id"], paths=allowed, limit=request["limit"])
            with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
                process = subprocess.Popen([navcom_sources.runtime(), str(worker)], stdin=subprocess.PIPE,
                                           stdout=output, stderr=errors)
                try:
                    process.stdin.write(json.dumps(query).encode()); process.stdin.close()
                    while process.poll() is None:
                        if time.monotonic() - started > request["seconds"]:
                            raise history.HistoryError("Historical scoped search reached its time budget")
                        if os.fstat(output.fileno()).st_size > MAX_OUTPUT or os.fstat(errors.fileno()).st_size > 65536:
                            raise history.HistoryError("Historical scoped search exceeded its output bound")
                        try: process.wait(timeout=.05)
                        except subprocess.TimeoutExpired: pass
                    if os.fstat(output.fileno()).st_size > MAX_OUTPUT or os.fstat(errors.fileno()).st_size > 65536:
                        raise history.HistoryError("Historical scoped search exceeded its output bound")
                finally:
                    if process.poll() is None:
                        process.kill(); process.wait()
                output.seek(0); errors.seek(0)
                if process.returncode:
                    raise history.HistoryError("Historical scoped search unavailable: " + errors.read(1200).decode("utf-8", "replace"))
                evidence = json.load(output)
            for field in ("concept_hits", "text_hits"):
                for hit in evidence.get(field, []):
                    path = hit.get("relative_path")
                    if path not in allowed or hit.get("source_id") != snapshot["id"]:
                        raise history.HistoryError("Historical search returned evidence outside the selected scope")
                    reference = hit.get("source_ref") or {}
                    if reference.get("snapshot") != artifact.name:
                        raise history.HistoryError("Historical search changed the selected artifact")
                    # The existing reader checks the matched artifact bytes
                    # against the Git receipt, rather than trusting a query memo.
                    reader.read_source(snapshot["id"], path, line=hit.get("line", 1), limit=1,
                                       history=snapshot["id"], history_cache=cache, snapshot=artifact.name)
                    hit["source_ref"] = dict(reference, history=snapshot["id"])
            evidence["history"] = snapshot["id"]
        nodes = [group] if group else [product, *groups]
        group_coverage = product.get("structure", {}).get("coverage", {})
        gaps = [] if parent_id is None else ["Ancestor metadata above the original saved view was not recorded."]
        if not receipt.get("coverage", {}).get("complete", False):
            gaps.append("Historical snapshot exclusions remain; see coverage.snapshot.rejected and snapshot limits.")
        if not group_coverage.get("complete", False):
            gaps.append("Native code grouping is bounded; see coverage.native_grouping for omissions and limits.")
        return dict(schema_version=1, action="land", cursor=request["cursor"], session_id=session,
            result_key=request["result_key"], as_of=plan["as_of"], commit=product["commit"], tree=product["tree"],
            query=request["query"], center=group or product, nodes=nodes,
            edges=[] if group else [dict(source=product["id"], target=node["id"], relation="committed_native_group") for node in groups],
            breadcrumbs=breadcrumbs, selected_place=group or product, product=product,
            group_id=request["group_id"], allowed_paths=allowed, files=files,
            snapshot={key: snapshot[key] for key in ("id", "source_id", "kind", "repository", "commit", "tree", "authored_at",
                "committed_at", "snapshot_path", "source_cache", "coverage", "include", "cache_hit") if key in snapshot},
            evidence=evidence, identity_policy=IDENTITY, conversation_policy=CONVERSATIONS,
            cli_command=_command(request, request["group_id"]),
            coverage=dict(complete=bool(receipt.get("coverage", {}).get("complete") and group_coverage.get("complete")),
                files=len(files), native_groups=len(groups), snapshot=receipt.get("coverage", {}), native_grouping=group_coverage,
                source= "Saved pinned plan and completed native result only", harvest_invocations=0,
                current_catalog_read=False, current_repository_read=False, elapsed_seconds=round(time.monotonic()-started, 4),
                parent_metadata_complete=parent_id is None, gaps=gaps))
    finally:
        os.close(fd)


SCRIPT = """import json,sys
sys.path.insert(0,sys.argv[1])
import navcom_historical_landing as service
try: result={'ok':True,'value':service._execute(json.load(sys.stdin))}
except Exception as exc: result={'ok':False,'error':str(exc)[:1500]}
print(json.dumps(result))
"""


def landing(cursor, place_id, *, result_key, group_id=None, query="", cache_path, limit=20, seconds=15):
    """Open a saved dated product/group with bounded native optional search."""
    if not isinstance(cursor, str) or not CURSOR.fullmatch(cursor):
        raise history.HistoryError("Supply an exact saved historical cursor")
    if not isinstance(result_key, str) or not KEY.fullmatch(result_key):
        raise history.HistoryError("Supply the result_key from the saved dated view")
    if not isinstance(place_id, str) or not place_id or len(place_id) > 200 or (group_id is not None and (not isinstance(group_id, str) or len(group_id) > 200)):
        raise history.HistoryError("Supply the exact saved product and optional group identity")
    if not isinstance(query, str) or len(query) > 500 or type(limit) is not int or not 1 <= limit <= 200:
        raise history.HistoryError("Historical search needs at most 500 characters and limit 1–200")
    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or not 0 < seconds <= 30:
        raise history.HistoryError("Historical landing needs a time bound greater than zero up to 30 seconds")
    request = dict(cursor=cursor, place_id=place_id, result_key=result_key, group_id=group_id,
                   query=query, cache_path=str(Path(cache_path).expanduser().resolve()), limit=limit, seconds=seconds)
    with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
        process = subprocess.Popen([sys.executable, "-I", "-B", "-c", SCRIPT, str(Path(__file__).parent)],
            stdin=subprocess.PIPE, stdout=output, stderr=errors, start_new_session=True)
        deadline = time.monotonic() + seconds
        try:
            process.stdin.write(json.dumps(request).encode()); process.stdin.close()
            while process.poll() is None:
                if time.monotonic() > deadline:
                    raise history.HistoryError("Historical landing reached its time budget; the saved view is unchanged")
                if os.fstat(output.fileno()).st_size > MAX_OUTPUT or os.fstat(errors.fileno()).st_size > 65536:
                    raise history.HistoryError("Historical landing exceeded its output budget")
                try: process.wait(timeout=.05)
                except subprocess.TimeoutExpired: pass
            if process.returncode or os.fstat(output.fileno()).st_size > MAX_OUTPUT or os.fstat(errors.fileno()).st_size > 65536:
                raise history.HistoryError("Historical landing worker unavailable or exceeded its output budget")
            output.seek(0); result = json.load(output)
            if not result.get("ok"):
                raise history.HistoryError(result.get("error", "Saved historical landing unavailable"))
            return result["value"]
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
