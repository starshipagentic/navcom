"""A dated chart of current navigation addresses, reconstructed from Git objects.

The immutable session pins the current address set and HEADs. Git committer dates
select recorded trees; they are not deployment dates or proof a product existed.
"""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import tempfile
import time

import navcom_history as history
import navcom_space as space


POLICY = "Pinned HEAD first-parent ancestry: select the first commit at or before the UTC cutoff by recorded committer date. Author dates, filesystem mtimes and dirty files do not select state. Non-monotonic or truncated ancestry is unknown; timestamps do not establish deployment or historical existence."
DEFAULT_BUDGETS = dict(max_files=2000, max_bytes=16 * 1024 * 1024, max_file_bytes=2 * 1024 * 1024)
RECOVERY_BUDGETS = dict(max_files=10000, max_bytes=64 * 1024 * 1024)
BUDGET_ERROR = "Historical snapshot exceeds its file/byte budget at "


def _utc(value):
    try:
        date = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError):
        raise history.HistoryError("Supply an ISO date or timestamp with a UTC offset")
    if date.tzinfo is None:
        if len(value) != 10:
            raise history.HistoryError("Historical timestamps need an explicit UTC offset")
        date = date.replace(tzinfo=timezone.utc)
    return date.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def _command(plan, cursor, *, cache, space_cache, source_cache, query, limit, seconds, search_limit):
    """Replay a pinned page with shell-safe literal arguments, never a fresh HEAD."""
    argv=["navcom","history","system",plan["selected"]["id"],"--at",plan["as_of"],"--cursor",cursor,
          "--cache",str(cache),"--limit",str(limit),"--seconds",str(seconds),"--max-commits",str(plan["max_commits"])]
    for flag,value in (("--space-cache",space_cache),("--source-cache",source_cache)):
        if value is not None:
            argv.extend([flag,str(Path(value).expanduser().resolve())])
    if query:
        argv.append("--query="+query)
    if search_limit != 20:
        argv.extend(["--search-limit",str(search_limit)])
    defaults=dict(max_files=2000,max_bytes=16*1024*1024,max_file_bytes=2*1024*1024)
    for key,value in plan["budgets"].items():
        if value != defaults[key]:
            argv.extend(["--"+key.replace("_","-"),str(value)])
    return shlex.join(argv)


def _worker(request):
    if request["action"] == "validate_snapshot":
        snapshot = request["snapshot"]
        root = Path(snapshot["snapshot_path"]).parent
        if root != Path(request["history_cache"]) / "revisions" / snapshot["id"]:
            raise history.HistoryError("Saved historical snapshot is outside this history cache")
        history._validate_artifact(root, snapshot)
        return True
    if request["action"] == "pin":
        selected = history.resolve_place(request["place"], space_cache=request["space_cache"], source_cache=request.get("source_cache"))
        return dict(selected, tip=history._revision(selected["repository"], "HEAD"))
    repo, tip = request["repository"], request["tip"]
    raw = history._git(repo, "log", "--first-parent", "--format=%H%x09%T%x09%aI%x09%cI%x09%s",
                       f"--max-count={request['max_commits']+1}", tip).decode("utf-8", "replace")
    commits = [history._commit(line) for line in raw.splitlines() if line]
    observed_dates = sorted({_utc(c["committed_at"]) for c in commits[:request["max_commits"]]})
    shallow=history._git(repo,"rev-parse","--is-shallow-repository").decode().strip()=="true"
    date_coverage = dict(available_dates=observed_dates,tip=tip,first_parent=True,shallow=shallow,truncated=len(commits)>request["max_commits"])
    if len(commits) > request["max_commits"]:
        raise history.HistoryError("Commit selection exceeded its ancestry budget; no partial history was guessed",date_coverage)
    dates = [datetime.fromisoformat(c["committed_at"]) for c in commits]
    if any(newer < older for newer, older in zip(dates, dates[1:])):
        raise history.HistoryError("Non-monotonic first-parent committer dates; an as-of selection is unknown",date_coverage)
    cutoff = datetime.fromisoformat(request["as_of"].replace("Z", "+00:00"))
    selected = next((c for c, date in zip(commits, dates) if date <= cutoff), None)
    if selected is None:
        raise history.HistoryError("No recorded first-parent commit at or before the cutoff",date_coverage)
    # A merge may carry an ancestor with a future committer date. Do not silently
    # treat that metadata contradiction as a valid earlier world.
    ancestry = history._git(repo, "log", "--format=%cI", f"--max-count={request['max_commits']+1}", selected["commit"]).decode().splitlines()
    if len(ancestry) > request["max_commits"] or any(datetime.fromisoformat(d) > cutoff for d in ancestry):
        raise history.HistoryError("Selected tree has bounded or future-dated ancestry; historical state is unknown",date_coverage)
    try:
        result = history.view(repo=repo, revision=selected["commit"], action="explore", include=request["include"],
                              cache_path=request["history_cache"], query=request["query"], limit=request["search_limit"], **request["budgets"])
    except history.HistoryError as exc:
        raise history.HistoryError(str(exc),dict(exc.coverage,**date_coverage)) from exc
    result["pinned_tip"] = tip
    result["available_dates"] = observed_dates
    result["date_coverage"] = date_coverage
    return result


SCRIPT = """import json,sys
sys.path.insert(0,sys.argv[1])
import navcom_system_history as service
try:
 result={'ok':True,'value':service._worker(json.load(sys.stdin))}
except Exception as exc:
 result={'ok':False,'error':str(exc)[:1500],'coverage':getattr(exc,'coverage',{})}
print(json.dumps(result))
"""


def _run(request, seconds):
    """Bound a complete native operation, including any harvest child process."""
    with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
        process = subprocess.Popen([sys.executable, "-I", "-B", "-c", SCRIPT, str(Path(__file__).parent)],
                                   stdin=subprocess.PIPE, stdout=output, stderr=errors, start_new_session=True)
        deadline = time.monotonic() + seconds
        try:
            process.stdin.write(json.dumps(request).encode()); process.stdin.close()
            while process.poll() is None:
                if time.monotonic() > deadline:
                    raise history.HistoryError("System history time budget reached; this scope remains unknown")
                if os.fstat(output.fileno()).st_size > 32 * 1024 * 1024 or os.fstat(errors.fileno()).st_size > 65536:
                    raise history.HistoryError("System history output budget reached")
                try:
                    process.wait(timeout=.05)
                except subprocess.TimeoutExpired:
                    continue
            if process.returncode or os.fstat(output.fileno()).st_size > 32 * 1024 * 1024 or os.fstat(errors.fileno()).st_size > 65536:
                raise history.HistoryError("Historical worker unavailable or exceeded its output budget")
            output.seek(0); result = json.load(output)
            if not result.get("ok"):
                raise history.HistoryError(result.get("error", "Historical worker unavailable"), result.get("coverage"))
            return result["value"]
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()


def _chart(plan, completed):
    nodes = [dict(n, historical_state="navigation_anchor", evidence_basis="Current navigation address, not historical ownership") for n in plan["parents"]]
    for anchor in plan["anchors"]:
        row = dict(anchor, label="Historical content unknown", historical_state="unknown", description="", clues=[], evidence=[])
        pin = plan["pins"].get(anchor["id"], {})
        row["historical_gap"] = pin.get("error", "Repository page not visited in this pinned session")
        for result in completed.values():
            if anchor["id"] not in result["scope_ids"]:
                continue
            if result.get("error"):
                row["historical_gap"] = result["error"]; continue
            data = result["data"]; scopes = pin["include"]
            files = [f["path"] for f in data["snapshot"]["files"] if any(p == "." or f["path"] == p or f["path"].startswith(p + "/") for p in scopes)]
            if not files:
                row["historical_gap"] = "Selected current address has no supported files at this commit; renamed paths are not followed"; continue
            manifests = [m for m in data["manifests"] if str(Path(m["path"]).parent) in scopes]
            clues = [c for c in data["product_clues"] if c.get("relative_root") in scopes]
            # An analyzer's summary may use the isolated snapshot directory as
            # its project name. Only committed authored identity can name a
            # dated place; keep analysis clues as evidence, not product names.
            label, label_source = "Committed source", dict(basis="unknown", reason="No authored historical name in this scope")
            for manifest in manifests:
                name = manifest["metadata"].get("name")
                cleaned = space._clean_clue(None, name, 100) if isinstance(name, str) else ""
                if cleaned:
                    label, label_source = cleaned, dict(basis="committed_manifest", path=manifest["path"], field="name")
                    break
            else:
                for clue in clues:
                    if clue.get("basis") != "harvested_readme":
                        continue
                    cleaned = space._clean_clue(None, clue.get("text"), 100)
                    if cleaned:
                        label, label_source = cleaned, dict(basis="harvested_readme", path=clue.get("path"), meaning="Committed README excerpt; not a declared product name")
                        break
            label_source.update(repository=data["repository"], commit=data["commit"])
            description = next((m["metadata"].get("description") for m in manifests if isinstance(m["metadata"].get("description"), str)), "")
            row.update(label=label, label_source=label_source,
                       description=space._clean_clue(None, description, 320), clues=clues, manifests=manifests,
                       historical_state="committed", historical_gap=None, files=files,
                       evidence=[dict(type="committed_tree", repository=data["repository"], commit=data["commit"], tree=data["tree"],
                                      authored_at=data["authored_at"], committed_at=data["committed_at"], include=scopes)],
                       commit=data["commit"],tree=data["tree"],committed_at=data["committed_at"],authored_at=data["authored_at"],
                       structure=dict(data["structure"],token_groups=[g for g in data["structure"].get("token_groups",[]) if all(any(p=="." or f==p or f.startswith(p+"/") for p in scopes) for f in g.get("paths",[]))]), snapshot_path=data["snapshot"]["snapshot_path"])
        nodes.append(row)
    shown={n["id"] for n in nodes}
    return dict(nodes=nodes, entities=nodes, edges=[dict(source=n["parent_id"], target=n["id"], relation="current_navigation_address") for n in nodes if n.get("parent_id") in shown])


def _saved_results(cache, session, plan, query_key):
    folder = cache / "systems" / session / "results" / query_key
    return {job["id"]: history._json_file(path) for job in plan["jobs"]
            if (path := folder / (job["id"] + ".json")).is_file()}


def _larger_retry(plan, completed):
    budgets = dict(plan["budgets"])
    for key, bound in RECOVERY_BUDGETS.items():
        budgets[key] = max(budgets[key], bound)
    increased = {key for key in budgets if budgets[key] > plan["budgets"][key]}
    eligible = []
    if increased:
        for job in plan["jobs"]:
            outcome = completed.get(job["id"], {})
            if not str(outcome.get("error") or "").startswith(BUDGET_ERROR):
                continue
            failure = outcome.get("coverage", {}).get("snapshot_budget_failure", {})
            dimensions = failure.get("dimensions")
            if dimensions and not set(dimensions).issubset(increased):
                continue  # The unchanged per-file/other bound would still fail.
            eligible.append(dict(job_id=job["id"], scope_ids=job["scope_ids"],
                                 dimensions=dimensions or [], exact_failure=bool(dimensions)))
    return budgets, eligible


def _compatible_success(outcome, job):
    data = outcome.get("data") or {}
    snapshot = data.get("snapshot") or {}
    return (not outcome.get("error") and outcome.get("scope_ids") == job["scope_ids"]
            and data.get("repository") == job["repository"] and data.get("pinned_tip") == job["tip"]
            and data.get("include") == job["include"] and snapshot.get("include") == job["include"]
            and snapshot.get("repository") == job["repository"]
            and snapshot.get("commit") == data.get("commit") and snapshot.get("tree") == data.get("tree"))


def view(place="", as_of="", *, space_cache, source_cache=None, cache_path, query="", limit=4,
         cursor=None, seconds=30, max_commits=10000, max_files=None, max_bytes=None,
         max_file_bytes=None, search_limit=20, progress=None, retry_larger=False):
    """Return every current anchor plus a paged, immutable dated reconstruction.

    Continue with next_cursor, never a freshly resolved HEAD. Unknown inventory
    pins remain unknown in that session; start a new session to attempt them.
    """
    if not isinstance(limit,int) or not 1 <= limit <= 50 or not 0 < seconds <= 120:
        raise history.HistoryError("System history needs limit 1–50 and seconds greater than zero up to 120")
    if not isinstance(max_commits,int) or not 1 <= max_commits <= 100000 or not 1 <= search_limit <= 200:
        raise history.HistoryError("Commit and search limits exceed the supported bounds")
    if not isinstance(query,str) or len(query) > 500:
        raise history.HistoryError("Historical query must contain at most 500 characters")
    if not isinstance(retry_larger, bool) or (retry_larger and not cursor):
        raise history.HistoryError("A larger historical retry requires an existing pinned cursor")
    started = time.monotonic(); deadline = started + seconds
    cache = Path(cache_path).expanduser().resolve()
    requested_budgets = dict(max_files=max_files,max_bytes=max_bytes,max_file_bytes=max_file_bytes)
    if any(value is not None and (not isinstance(value, int) or isinstance(value, bool) or value < 1)
           for value in requested_budgets.values()):
        raise history.HistoryError("History budgets must be positive integers")
    query_key = _hash([query, search_limit])
    if cursor:
        session, _, number = cursor.partition(":")
        if len(session) != 64 or any(c not in "0123456789abcdef" for c in session) or not number.isdigit():
            raise history.HistoryError("Invalid system history cursor")
        offset = int(number); plan = history._json_file(cache / "systems" / session / "plan.json")
        if offset > len(plan["jobs"]):
            raise history.HistoryError("Cursor offset exceeds this pinned repository set")
        if (place and place not in {plan["selected"]["id"],plan["selected"]["label"]}) or (as_of and _utc(as_of) != plan["as_of"]):
            raise history.HistoryError("Cursor belongs to a different place or UTC cutoff")
        if any(value is not None and value != plan["budgets"][key] for key, value in requested_budgets.items()) or max_commits != plan["max_commits"]:
            raise history.HistoryError("Continue a pinned session with the same snapshot and ancestry budgets")
        budgets = dict(plan["budgets"])
    else:
        budgets = {key: value if value is not None else DEFAULT_BUDGETS[key] for key, value in requested_budgets.items()}
        cutoff = _utc(as_of)
        center = space.view(space_cache, action="show", within=place)["center"]
        if center["kind"] not in {"system", "galaxy"}:
            raise history.HistoryError("System history requires a system or galaxy; use history explore for one repository")
        catalog = history._json_file(space_cache)
        mapping = {n["id"]:n for n in catalog["entities"]}
        def inside(node):
            seen=set()
            while node and node["id"] not in seen:
                if node["id"] == center["id"]:return True
                seen.add(node["id"]);node=mapping.get(node.get("parent_id"))
            return False
        selected = [n for n in mapping.values() if inside(n)]
        eligible = sorted([n for n in selected if n["kind"] in {"planet","moon"}],key=lambda n:n["id"])
        anchors = [dict({k:n.get(k) for k in ("id","kind","parent_id","position")},current_label=n.get("label")) for n in eligible]
        parents = [{k:n.get(k) for k in ("id","kind","label","parent_id","position")} for n in selected if n["kind"] in {"system","galaxy"}]
        for n in eligible:
            for location in n.get("locations",[]):
                if location.get("path") and cache.is_relative_to(Path(location["path"]).expanduser().resolve()):
                    raise history.HistoryError("Keep the system history cache outside selected source locations")
        pins = {}; jobs = {}
        # Copy address metadata once so a concurrent catalog refresh cannot alter
        # what a later pin resolves. No current prose enters the dated chart.
        with tempfile.TemporaryDirectory(prefix="navcom-system-pins-") as tmp:
            address_file=Path(tmp)/"space.json";address_file.write_text(json.dumps(catalog))
            source_copy=None
            if source_cache and (Path(source_cache)/"current.json").is_file():
                source_copy=Path(tmp)/"sources";source_copy.mkdir()
                (source_copy/"current.json").write_text(json.dumps(history._json_file(Path(source_cache)/"current.json")))
            pin_deadline = started + seconds * .4
            for index,node in enumerate(eligible):
                if progress:progress(dict(stage="pin",completed=index,total=len(eligible),scope_id=node["id"]))
                if time.monotonic() >= pin_deadline:
                    pins[node["id"]]=dict(error="Repository HEAD was not pinned within the inventory time budget; start a new session to retry")
                    continue
                try:
                    pin=_run(dict(action="pin",place=node["id"],space_cache=str(address_file),source_cache=str(source_copy) if source_copy else None),min(10,pin_deadline-time.monotonic()))
                    if cache.is_relative_to(Path(pin["repository"])):
                        raise history.HistoryError("Keep the history cache outside the resolved repository")
                    pins[node["id"]]=pin
                    job=jobs.setdefault(pin["repository"],dict(repository=pin["repository"],tip=pin["tip"],include=[],scope_ids=[]))
                    if job["tip"] != pin["tip"]:
                        raise history.HistoryError("Repository HEAD changed during pinning; start a new session")
                    job["include"].extend(pin["include"]);job["scope_ids"].append(node["id"])
                except history.HistoryError as exc:
                    if str(exc) == "Keep the history cache outside the resolved repository":
                        raise
                    pins[node["id"]]=dict(error=str(exc),coverage=exc.coverage)
        jobs=list(jobs.values())
        if any(cache.is_relative_to(Path(job["repository"])) for job in jobs):
            raise history.HistoryError("Keep the system history cache outside resolved source repositories")
        for job in jobs:
            job["include"]=space._minimal_paths(job["include"])
            job["id"]=_hash([job["repository"],job["tip"],job["include"]])
        jobs.sort(key=lambda job:job["repository"])
        plan=dict(selected={k:center[k] for k in ("id","kind","label")},as_of=cutoff,anchors=anchors,parents=parents,pins=pins,jobs=jobs,
                  budgets=budgets,max_commits=max_commits,policy=POLICY,
                  catalog_fingerprint=_hash(catalog),adapter=_hash(Path(__file__).read_text()),history_adapter=_hash(Path(history.__file__).read_text()))
        session=_hash(plan);offset=0
        space._atomic(cache/"systems"/session/"plan.json",plan)
    completed = _saved_results(cache, session, plan, query_key)
    validated = set()
    if retry_larger:
        larger_budgets, eligible = _larger_retry(plan, completed)
        if not eligible:
            raise history.HistoryError("No eligible failed snapshot can use the bounded larger retry; the existing session is unchanged")
        parent_session = session
        plan = dict(plan, budgets=larger_budgets, derived_from_session_id=parent_session,
                    recovery=dict(reason="Explicit retry of failed snapshot file/total-byte limits; original heads, date and addresses retained",
                                  from_budgets=budgets, to_budgets=larger_budgets, jobs=eligible, query_key=query_key),
                    adapter=_hash(Path(__file__).read_text()), history_adapter=_hash(Path(history.__file__).read_text()))
        session = _hash(plan); offset = 0
        space._atomic(cache/"systems"/session/"plan.json",plan)
        previous = completed
        completed = _saved_results(cache, session, plan, query_key)
        retry_ids = {row["job_id"] for row in eligible}
        for job in plan["jobs"]:
            if job["id"] in completed or job["id"] in retry_ids:
                continue
            outcome = previous.get(job["id"])
            if not outcome or outcome.get("retryable") or time.monotonic() >= deadline:
                continue
            if outcome.get("data"):
                if not _compatible_success(outcome, job):
                    continue
                try:
                    _run(dict(action="validate_snapshot", snapshot=outcome["data"]["snapshot"], history_cache=str(cache)),
                         max(.01, deadline-time.monotonic()))
                except history.HistoryError:
                    continue
                validated.add(job["id"])
            completed[job["id"]] = dict(outcome, reused_from_session_id=parent_session)
            space._atomic(cache/"systems"/session/"results"/query_key/(job["id"]+".json"),completed[job["id"]])
    session_dir=cache/"systems"/session
    results_dir=session_dir/"results"/query_key
    visited=offset
    attempted=0
    for index in range(offset,len(plan["jobs"])):
        job=plan["jobs"][index]
        if time.monotonic() >= deadline:break
        saved = completed.get(job["id"])
        if plan.get("derived_from_session_id") and saved and not saved.get("retryable"):
            reusable = not saved.get("data")
            if saved.get("data") and _compatible_success(saved, job):
                try:
                    if job["id"] not in validated:
                        _run(dict(action="validate_snapshot", snapshot=saved["data"]["snapshot"], history_cache=str(cache)),
                             max(.01, deadline-time.monotonic()))
                    reusable = True
                except history.HistoryError:
                    # Do not return stale committed evidence. Reconstruct only
                    # from the same pinned Git objects if the budget permits.
                    completed.pop(job["id"], None)
            if reusable:
                visited=index+1
                continue
        if attempted >= limit:break
        attempted += 1
        if progress:progress(dict(stage="reconstruct",completed=index,total=len(plan["jobs"]),scope_ids=job["scope_ids"]))
        request=dict(action="explore",**job,as_of=plan["as_of"],max_commits=plan["max_commits"],history_cache=str(cache),query=query,search_limit=search_limit,budgets=plan["budgets"])
        try:
            data=_run(request,max(.01,deadline-time.monotonic()))
            outcome=dict(scope_ids=job["scope_ids"],data=data,error=None)
        except history.HistoryError as exc:
            retryable=any(fragment in str(exc) for fragment in ("time budget","timed out","Another historical snapshot","worker unavailable"))
            outcome=dict(scope_ids=job["scope_ids"],error=str(exc),coverage=exc.coverage,retryable=retryable)
        completed[job["id"]]=outcome
        space._atomic(results_dir/(job["id"]+".json"),outcome)
        if outcome.get("retryable"):
            visited=index
            break
        visited=index+1
    chart=_chart(plan,completed)
    done=[n["id"] for n in chart["nodes"] if n["historical_state"]=="committed"]
    unknown=[n["id"] for n in chart["nodes"] if n["historical_state"]=="unknown"]
    more=visited<len(plan["jobs"])
    dates=sorted({date for outcome in completed.values() for date in (outcome.get("data",{}).get("available_dates",[]) or outcome.get("coverage",{}).get("available_dates",[]))})
    date_records=[r.get("data",{}).get("date_coverage") or r.get("coverage",{}) for r in completed.values()]
    date_records=[r for r in date_records if "available_dates" in r]
    center=next(n for n in chart["nodes"] if n["id"]==plan["selected"]["id"])
    snapshot_coverage=[r["data"]["snapshot"]["coverage"] for r in completed.values() if r.get("data")]
    command_args=dict(cache=cache,space_cache=space_cache,source_cache=source_cache,query=query,limit=limit,seconds=seconds,search_limit=search_limit)
    next_cursor=f"{session}:{visited}" if more else None
    import navcom_historical_landing
    for node in chart["nodes"]:
        if node.get("historical_state") == "committed":
            node["land_command"] = navcom_historical_landing._command(dict(place_id=node["id"],
                cursor=f"{session}:{offset}", result_key=query_key, cache_path=str(cache),
                query=query, limit=search_limit, seconds=15))
    larger_budgets, retry_jobs = _larger_retry(plan, completed)
    retry_reason = ("Retry failed snapshots with up to 10,000 files and 64 MiB per repository, keeping pinned heads, date, paths and the per-file cap."
                    + (" Older failure records do not identify the exact exhausted limit; recovery is not guaranteed."
                       if any(not job["exact_failure"] for job in retry_jobs) else "")) if retry_jobs else None
    return dict(schema_version=1,action="system",session_id=session,selected_place=plan["selected"],as_of=plan["as_of"],selection_policy=POLICY,
                identity_policy="Current catalog supplies address IDs, containment and positions only; labels, files and groups come from the selected committed trees. This is not a historical ownership reconstruction.",
                chart=chart,**chart,completed_scope_ids=done,repositories=list(completed.values()),query=query,
                center=center,breadcrumbs=[plan["selected"]],available_dates=dates,date_coverage=dict(repositories_observed=len(date_records),pinned_repositories=len(plan["jobs"]),complete=len(date_records)==len(plan["jobs"]) and not any(r.get("truncated") or r.get("shallow") for r in date_records) and not any(p.get("error") for p in plan["pins"].values()),records=date_records),
                conversations=[],conversation_policy="No historical conversation attribution has been established; no current conversations are joined.",
                next_cursor=next_cursor,cursor=f"{session}:{offset}",result_key=query_key,offset=offset,limit=limit,
                snapshot_budgets=plan["budgets"],derived_from_session_id=plan.get("derived_from_session_id"),
                recovery=plan.get("recovery"),retry_larger_available=bool(retry_jobs),retry_larger_reason=retry_reason,
                retry_larger_command=(_command(plan,f"{session}:{offset}",**command_args)+" --retry-larger") if retry_jobs else None,
                cli_command=_command(plan,f"{session}:{offset}",**command_args),
                continue_command=_command(plan,next_cursor,**command_args) if next_cursor else None,
                coverage=dict(complete=not unknown and not more and all(c.get("complete") for c in snapshot_coverage),reconstruction_complete=not unknown and not more,eligible_scopes=len(plan["anchors"]),completed_scopes=len(done),unknown_scope_ids=unknown,
                              pinned_repositories=len(plan["jobs"]),visited_repositories=len(completed),more=more,seconds=round(time.monotonic()-started,4),
                              retry_larger_job_ids=[row["job_id"] for row in retry_jobs],
                              reused_repositories=sum(bool(row.get("reused_from_session_id")) for row in completed.values()),
                              source="Current cached product/moon addresses only; deleted or unindexed products cannot be inferred",snapshot_coverage=snapshot_coverage))
