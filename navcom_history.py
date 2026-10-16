"""Read committed Git trees into isolated, bounded Starforge source caches.

Commit timestamps are recorded Git metadata, not deployment or existence proof.
No operation checks out a revision or reads fallback contents from the worktree.
"""
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import select
import shutil
import shlex
import subprocess
import tempfile
import time


class HistoryError(ValueError):
    def __init__(self, message, coverage=None):
        super().__init__(message)
        self.coverage = coverage or {}


class _GitBlobs:
    """One native Git batch reader; each response has bounded, verified framing."""
    def __init__(self, repo):
        env = dict(os.environ, GIT_OPTIONAL_LOCKS="0", GIT_NO_REPLACE_OBJECTS="1",
                   GIT_NO_LAZY_FETCH="1", GIT_TERMINAL_PROMPT="0")
        self.errors = tempfile.TemporaryFile()
        self.buffer = bytearray()
        try:
            self.process = subprocess.Popen(["git", "-C", str(repo), "cat-file", "--batch"],
                                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.errors,
                                            env=env, bufsize=0)
        except Exception:
            self.errors.close()
            raise

    def _fill(self, deadline):
        if os.fstat(self.errors.fileno()).st_size > 65536:
            raise HistoryError("Git batch diagnostics exceed the history inspection budget")
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not select.select([self.process.stdout], [], [], remaining)[0]:
            raise HistoryError("Git batch object read timed out")
        chunk = os.read(self.process.stdout.fileno(), 65536)
        if not chunk:
            raise HistoryError("Git batch ended before the requested object was complete")
        self.buffer.extend(chunk)

    def _line(self, deadline):
        while True:
            end = self.buffer.find(b"\n")
            if end >= 0:
                if end > 200:
                    raise HistoryError("Git batch header exceeds its framing budget")
                line = bytes(self.buffer[:end]); del self.buffer[:end + 1]
                return line
            if len(self.buffer) > 200:
                raise HistoryError("Git batch header exceeds its framing budget")
            self._fill(deadline)

    def _exact(self, count, deadline):
        result = bytearray()
        while len(result) < count:
            if not self.buffer:
                self._fill(deadline)
            take = min(count - len(result), len(self.buffer))
            result.extend(self.buffer[:take]); del self.buffer[:take]
        return bytes(result)

    def read(self, oid, expected_size, max_bytes, timeout=20):
        if len(oid) not in (40, 64) or any(c not in "0123456789abcdef" for c in oid):
            raise HistoryError("Git tree contains an invalid object ID")
        if not 0 <= expected_size <= max_bytes:
            raise HistoryError("Git batch object exceeds its byte budget")
        deadline = time.monotonic() + timeout
        try:
            self.process.stdin.write((oid + "\n").encode("ascii"))
        except (OSError, BrokenPipeError) as exc:
            raise HistoryError("Git batch reader is unavailable") from exc
        try:
            returned, kind, size_text = self._line(deadline).decode("ascii").split()
            size = int(size_text)
        except (UnicodeDecodeError, ValueError) as exc:
            raise HistoryError("Git batch returned a missing object or invalid header") from exc
        if returned != oid or kind != "blob" or size != expected_size or not 0 <= size <= max_bytes:
            raise HistoryError("Git batch object does not match the selected tree")
        contents = self._exact(size, deadline)
        if self._exact(1, deadline) != b"\n":
            raise HistoryError("Git batch object has invalid framing")
        if os.fstat(self.errors.fileno()).st_size > 65536:
            raise HistoryError("Git batch diagnostics exceed the history inspection budget")
        digest = hashlib.new("sha1" if len(oid) == 40 else "sha256")
        digest.update(b"blob " + str(size).encode("ascii") + b"\0")
        digest.update(contents)
        if digest.hexdigest() != oid:
            raise HistoryError("Git batch object content does not match its object ID")
        return contents

    def close(self):
        self.process.stdin.close()
        try:
            self.process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            self.process.kill(); self.process.wait()
        finally:
            self.process.stdout.close()
            self.errors.close()


def _git(repo, *args, max_output=16 * 1024 * 1024, timeout=20):
    """Bound Git output on disk before reading it into memory."""
    env = dict(os.environ, GIT_OPTIONAL_LOCKS="0", GIT_NO_REPLACE_OBJECTS="1",
               GIT_LITERAL_PATHSPECS="1", GIT_NO_LAZY_FETCH="1", GIT_TERMINAL_PROMPT="0")
    with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(["git", "-C", str(repo), *args], stdout=output, stderr=errors, env=env)
        deadline = time.monotonic() + timeout
        try:
            while True:
                if os.fstat(output.fileno()).st_size > max_output or os.fstat(errors.fileno()).st_size > 65536:
                    raise HistoryError("Git output exceeds the history inspection budget")
                if time.monotonic() > deadline:
                    raise HistoryError("Git history inspection timed out")
                try:
                    process.wait(timeout=.05)
                    break
                except subprocess.TimeoutExpired:
                    continue
            if os.fstat(output.fileno()).st_size > max_output:
                raise HistoryError("Git output exceeds the history inspection budget")
            if process.returncode:
                errors.seek(0)
                detail = errors.read(400).decode("utf-8", "replace").strip()
                raise HistoryError("Git history unavailable: " + detail)
            output.seek(0)
            return output.read(max_output + 1)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()


def _repository(repo):
    path = Path(repo).expanduser().resolve()
    if not path.is_dir():
        raise HistoryError("Repository directory unavailable: " + str(path))
    root = Path(_git(path, "rev-parse", "--show-toplevel").decode().strip())
    shallow = _git(root, "rev-parse", "--is-shallow-repository").decode().strip() == "true"
    return root, shallow


def _revision(repo, revision):
    if not isinstance(revision, str) or not revision or any(c in revision for c in "\n\r\x00"):
        raise HistoryError("Supply a Git revision or full commit SHA")
    return _git(repo, "rev-parse", "--verify", "--end-of-options", revision + "^{commit}").decode().strip()


def _commit(line):
    sha, tree, author, committer, subject = line.split("\t", 4)
    return dict(commit=sha, tree=tree, authored_at=author, committed_at=committer, subject=subject)


def timeline(repo, limit=50, include=None):
    """List HEAD ancestry newest first; dates do not select or reconstruct state."""
    if not isinstance(limit, int) or not 1 <= limit <= 200:
        raise HistoryError("History limit must be between 1 and 200")
    root, shallow = _repository(repo)
    tip = _revision(root, "HEAD")
    scope = _scope(include)
    raw = _git(root, "log", "--date-order", f"--max-count={limit + 1}",
               "--format=%H%x09%T%x09%aI%x09%cI%x09%s", tip, "--", *scope).decode("utf-8", "replace")
    commits = [_commit(line) for line in raw.splitlines() if line]
    return dict(repository=str(root), include=scope, selected_ref="HEAD", resolved_tip=tip,
                commits=commits[:limit], shallow=shallow, truncated=len(commits) > limit,
                chronology="HEAD ancestry touching the selected paths in Git date order; recorded author/committer timestamps are not deployment times. Renamed paths are not followed.",
                selection_policy="Select a full commit SHA; no timestamp or filesystem mtime is interpreted as an as-of state")


def _scope(include):
    items = ["."] if include is None else list(include)
    if not items:
        raise HistoryError("Select at least one relative file or directory")
    result = []
    for item in items:
        if not isinstance(item, str) or not item or "\x00" in item:
            raise HistoryError("History scopes must be relative Git paths")
        path = PurePosixPath(item)
        if path.is_absolute() or ".." in path.parts:
            raise HistoryError("History scope must stay inside its repository")
        result.append(str(path))
    return sorted(set(result))


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def _source_policy():
    """Read the existing harvest worker's policy, in its installed runtime."""
    import navcom_sources
    worker_dir = str(Path(navcom_sources.__file__).parent)
    script = ("import json,sys; sys.dont_write_bytecode=True; sys.path.insert(0,sys.argv[1]); "
              "import navcom_sources_worker as worker; "
              "print(json.dumps(dict(extensions=sorted(worker.EXT),skip_dirs=sorted(worker.SKIP),"
              "filenames=sorted(worker.SOURCE_FILENAMES),extractor=worker.extractor_signature())))")
    result = subprocess.run([navcom_sources.runtime(), "-c", script, worker_dir],
                            capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise HistoryError("Historical harvest policy unavailable: " + result.stderr.strip()[-800:])
    return json.loads(result.stdout)


def _validate_artifact(artifact, receipt):
    snapshot = artifact / "snapshot"
    expected = {f["path"]: f for f in receipt["files"]}
    actual = {str(p.relative_to(snapshot)) for p in snapshot.rglob("*") if p.is_file() or p.is_symlink()}
    if actual != set(expected):
        raise HistoryError("Historical snapshot contents changed; refusing an unverified cache")
    for relative, metadata in expected.items():
        path = snapshot / relative
        if path.is_symlink() or path.stat().st_size != metadata["bytes"] or _digest(path.read_bytes()) != metadata["sha256"]:
            raise HistoryError("Historical snapshot content changed: " + relative)


def prepare(repo, revision, cache_path, include=None, *, max_files=10000,
            max_bytes=64 * 1024 * 1024, max_file_bytes=2 * 1024 * 1024):
    """Materialize only committed regular blobs, never current/uncommitted files.

    Unsupported symlinks, submodules, LFS pointers and hidden paths are reported
    and omitted. Resource-budget violations abort publication altogether.
    """
    if any(not isinstance(n, int) or n < 1 for n in (max_files, max_bytes, max_file_bytes)):
        raise HistoryError("History budgets must be positive integers")
    root, shallow = _repository(repo)
    sha = _revision(root, revision)
    scope = _scope(include)
    metadata = _commit(_git(root, "show", "-s", "--format=%H%x09%T%x09%aI%x09%cI%x09%s", sha).decode("utf-8", "replace").rstrip("\n"))
    cache = Path(cache_path).expanduser().resolve()
    if cache == root or cache.is_relative_to(root):
        raise HistoryError("Keep the historical cache outside the source repository")
    policy = _source_policy()
    signature = _digest(Path(__file__).read_bytes())
    key = _digest(json.dumps([str(root), sha, scope, max_files, max_bytes, max_file_bytes, signature, policy]).encode())
    artifact = cache / "revisions" / key
    cache.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (cache / "history.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise HistoryError("Another historical snapshot is being prepared; existing snapshots remain readable")
        try:
            receipt_path = artifact / "receipt.json"
            if receipt_path.exists():
                receipt = json.loads(receipt_path.read_text())
                _validate_artifact(artifact, receipt)
                return dict(receipt, cache_hit=True)
            raw = _git(root, "ls-tree", "-r", "-z", "--long", "--full-tree", sha, "--", *scope)
            coverage = dict(shallow=shallow, selected_paths=scope, rejected=[], files=0, bytes=0,
                            complete=not shallow, full_repository=False, whole_root_selected=scope == ["."],
                            eligibility="Existing navcom_sources_worker EXT/SKIP/SOURCE_FILENAMES; SKIP derives from Starforge SKIP_DIRS",
                            supported_extensions=policy["extensions"], supported_filenames=policy["filenames"])
            stage = Path(tempfile.mkdtemp(prefix=".history-", dir=cache))
            records = []
            encountered = set()
            batch = None
            try:
                snapshot = stage / "snapshot"
                snapshot.mkdir(mode=0o700)
                batch = _GitBlobs(root)
                for entry in raw.split(b"\0"):
                    if not entry:
                        continue
                    header, encoded_path = entry.split(b"\t", 1)
                    mode, kind, oid, size = header.decode("ascii").split()
                    relative = encoded_path.decode("utf-8", "strict")
                    encountered.add(relative)
                    path = PurePosixPath(relative)
                    reason = ("symlink" if mode == "120000" else "submodule" if mode == "160000" or kind == "commit"
                              else "unsupported object type" if kind != "blob" or mode not in ("100644", "100755")
                              else "unsafe path" if path.is_absolute() or ".." in path.parts
                              else "hidden path" if any(p.startswith(".") for p in path.parts) else None)
                    if reason:
                        coverage["rejected"].append(dict(path=relative, reason=reason))
                        continue
                    count = int(size)
                    excluded = ("Starforge skipped directory" if any(part in policy["skip_dirs"] for part in path.parts[:-1])
                                else "Not a supported code/document file in the existing harvest policy"
                                if path.suffix.lower() not in policy["extensions"] and path.name not in policy["filenames"] else None)
                    if excluded:
                        # Identify small Git LFS pointers without fetching their external payload.
                        if excluded != "Starforge skipped directory" and count <= 1024:
                            pointer = batch.read(oid, count, max_bytes=1024)
                            if pointer.splitlines()[:1] == [b"version https://git-lfs.github.com/spec/v1"]:
                                excluded = "Git LFS pointer; external object was not fetched"
                        coverage["rejected"].append(dict(path=relative, reason=excluded))
                        continue
                    if count > max_file_bytes or coverage["files"] >= max_files or coverage["bytes"] + count > max_bytes:
                        failure = dict(path=relative, file_bytes=count,
                                       dimensions=[key for key, exceeded in (
                                           ("max_file_bytes", count > max_file_bytes),
                                           ("max_files", coverage["files"] >= max_files),
                                           ("max_bytes", coverage["bytes"] + count > max_bytes)) if exceeded],
                                       limits=dict(max_files=max_files, max_bytes=max_bytes, max_file_bytes=max_file_bytes))
                        raise HistoryError("Historical snapshot exceeds its file/byte budget at " + relative,
                                           dict(coverage, snapshot_budget_failure=failure))
                    contents = batch.read(oid, count, max_bytes=max_file_bytes)
                    if len(contents) != count:
                        raise HistoryError("Historical Git blob size does not match its tree entry", coverage)
                    if contents.splitlines()[:1] == [b"version https://git-lfs.github.com/spec/v1"]:
                        coverage["rejected"].append(dict(path=relative, reason="Git LFS pointer; external object was not fetched"))
                        continue
                    destination = snapshot / relative
                    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                    destination.write_bytes(contents)
                    destination.chmod(0o600)
                    coverage["files"] += 1
                    coverage["bytes"] += count
                    records.append(dict(path=relative, object=oid, mode=mode, bytes=count, sha256=_digest(contents)))
                for requested in scope:
                    if requested != "." and not any(p == requested or p.startswith(requested + "/") for p in encountered):
                        coverage["rejected"].append(dict(path=requested, reason="missing at selected revision"))
                if not records:
                    raise HistoryError("No supported committed files in selected historical scope", coverage)
                coverage["complete"] = not shallow and not coverage["rejected"]
                coverage["full_repository"] = scope == ["."] and not coverage["rejected"]
                receipt = dict(schema_version=1, id=key, kind="git_revision", repository=str(root),
                               requested_revision=revision, **metadata, observed_at=time.time(),
                               snapshot_path=str(artifact / "snapshot"), source_cache=str(artifact / "harvest"),
                               include=scope, extractor=signature, files=records, coverage=coverage,
                               date_policy="Exact committed tree; author/committer dates are metadata, not an as-of or deployment guarantee")
                (stage / "receipt.json").write_text(json.dumps(receipt, indent=2))
                artifact.parent.mkdir(exist_ok=True, mode=0o700)
                os.replace(stage, artifact)
                return dict(receipt, cache_hit=False)
            finally:
                if batch is not None:
                    batch.close()
                if stage.exists():
                    shutil.rmtree(stage)
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def harvest_revision(repo, revision, cache_path, include=None, **budgets):
    """Prepare a revision, then invoke NavCom's unchanged Starforge worker."""
    import navcom_sources
    prepared = prepare(repo, revision, cache_path, include, **budgets)
    import navcom_space
    _, boundaries, _ = navcom_space._boundaries(Path(prepared["snapshot_path"]), [], 200)
    source = dict(id=prepared["id"], root=prepared["snapshot_path"],
                  label=Path(prepared["repository"]).name + "@" + prepared["commit"][:10], include=["."],
                  max_files=budgets.get("max_files", 10000), max_bytes=budgets.get("max_bytes", 64 * 1024 * 1024),
                  max_file_bytes=budgets.get("max_file_bytes", 2 * 1024 * 1024),
                  conversation_collection=None,
                  discovery_coverage=dict(application_roots=[b["relative"] for b in boundaries if b["kind"] == "planet"]),
                  provenance={key: prepared[key] for key in ("kind", "repository", "commit", "tree", "authored_at", "committed_at", "observed_at")})
    request = dict(action="harvest", cache=prepared["source_cache"], sources=[source])
    worker = Path(navcom_sources.__file__).with_name("navcom_sources_worker.py")
    result = subprocess.run([navcom_sources.runtime(), str(worker)], input=json.dumps(request),
                            capture_output=True, text=True, timeout=120)
    if result.returncode:
        raise HistoryError("Historical Starforge harvest failed: " + result.stderr.strip()[-800:], prepared["coverage"])
    return dict(prepared, source_id=source["id"], harvest=json.loads(result.stdout))


def _json_file(path, limit=32 * 1024 * 1024):
    path = Path(path)
    if path.stat().st_size > limit:
        raise HistoryError("Historical metadata exceeds its read budget: " + str(path))
    return json.loads(path.read_text())


def resolve_place(place="", *, repo=None, space_cache=None, source_cache=None, include=None):
    """Resolve current navigation identity to an exact Git root and literal scope.

    The current catalog supplies addresses only. Its labels, clues and groups
    are not treated as historical facts. Missing paths may still exist in Git.
    """
    selected = None
    locations = []
    anchors = {}
    rejected = []
    if place:
        import navcom_space
        if not space_cache:
            raise HistoryError("A place needs --space-cache, or choose --repo without a place")
        node = navcom_space.view(space_cache, action="show", within=place)["center"]
        selected = {key: node[key] for key in ("id", "kind", "label")}
        if node["kind"] in {"galaxy", "system", "starbase"}:
            raise HistoryError("History is pinned to one Git repository. Choose a planet, moon, district, star or ship.")
        locations = [str(loc["path"]) for loc in node.get("locations", []) if loc.get("path")]
        # Districts have file scopes rather than independent physical locations.
        if node["kind"] == "district" or not locations:
            if not source_cache or not (Path(source_cache) / "current.json").is_file():
                raise HistoryError("This place needs its saved source scopes; supply --source-cache or refresh sources")
            sources = {s["id"]: s for s in _json_file(Path(source_cache) / "current.json")["sources"]}
            locations = []
            for scope in node.get("source_scopes", []):
                source = sources.get(scope["source_id"])
                if not source:
                    raise HistoryError("Saved source scope is unavailable: " + scope["source_id"])
                if not scope.get("paths"):
                    raise HistoryError("Saved place scope has no paths; refresh geography before exploring history")
                source_root = Path(os.path.abspath(os.path.expanduser(source["root"])))
                for relative in _scope(scope["paths"]):
                    address = str(source_root / relative)
                    locations.append(address)
                    anchors[address] = source_root
            if not locations:
                raise HistoryError("This place has no recorded Git location or source file scope")
    elif repo:
        locations = [str(repo)]
    else:
        raise HistoryError("Choose a place ID/name or supply --repo ROOT")
    candidates = {}
    for location in dict.fromkeys(locations):
        # Preserve the saved literal leaf; today's symlink cannot redirect a
        # historical address to a different repository or different file.
        path = Path(os.path.abspath(os.path.expanduser(location)))
        try:
            address = anchors.get(location, path)
            existing = None
            # Walk literal ancestors from outside in. Once inside a repository,
            # stop at a symlink rather than accepting a Git marker beyond it.
            # System aliases above a repository (e.g. macOS /tmp) remain valid.
            for candidate in [*reversed(address.parents), address]:
                if candidate.is_symlink():
                    if existing is not None:
                        break
                    continue
                if (candidate / ".git").exists():
                    existing = candidate
            if existing is None:
                raise HistoryError("No Git repository at this recorded address")
            root, _ = _repository(existing)
            relative = path.relative_to(existing).as_posix()
        except (HistoryError, ValueError) as exc:
            rejected.append(dict(path=str(path), reason=str(exc)))
            continue
        candidates.setdefault(str(root), set()).add(relative)
    if not candidates:
        raise HistoryError("No available Git repository for this place", dict(rejected=rejected))
    if repo and place:
        requested, _ = _repository(repo)
        if str(requested) not in candidates:
            raise HistoryError("--repo is not a recorded Git location for this place", dict(repositories=sorted(candidates)))
        chosen = str(requested)
    elif len(candidates) != 1:
        raise HistoryError("This place has multiple Git copies; select one with --repo ROOT", dict(repositories=sorted(candidates), rejected=rejected))
    else:
        chosen = next(iter(candidates))
    import navcom_space
    scope = navcom_space._minimal_paths(candidates[chosen])
    if include is not None:
        requested = _scope(include)
        if any(not any(parent == "." or value == parent or value.startswith(parent + "/") for parent in scope) for value in requested):
            raise HistoryError("--include must stay within the selected place's repository-relative scope")
        scope = requested
    return dict(selected_place=selected, repository=chosen, include=scope,
                location_coverage=dict(rejected=rejected, repositories=sorted(candidates)),
                identity_policy="The selected place is a current navigation address; historical names and contents come only from the selected Git commit.")


def _historical_details(prepared):
    """Read committed manifests and upstream artifacts, without a second classifier."""
    import navcom_space
    state = _json_file(Path(prepared["source_cache"]) / "current.json")
    source = next(s for s in state["sources"] if s["id"] == prepared["source_id"])
    artifact = Path(source["artifact"])
    snapshot = Path(prepared["snapshot_path"])
    manifests = []
    warnings = []
    paths = [f["path"] for f in prepared["files"]]
    for relative in paths:
        name = Path(relative).name
        if name not in {"package.json", "pyproject.toml"}:
            continue
        path = snapshot / relative
        if path.stat().st_size > 512 * 1024:
            warnings.append("Manifest exceeds the 512 KiB display budget: " + relative)
            continue
        try:
            if name == "package.json":
                data = _json_file(path, 512 * 1024)
                metadata = {key: data[key] for key in ("name", "version", "description", "workspaces") if key in data}
            else:
                try:
                    import tomllib
                except ImportError:
                    warnings.append("Python 3.11+ is needed to display TOML fields; the committed file remains searchable: " + relative)
                    continue
                data = tomllib.loads(path.read_text())
                project = data.get("project") or data.get("tool", {}).get("poetry", {})
                metadata = {key: project[key] for key in ("name", "version", "description") if key in project}
            manifests.append(dict(path=relative, source_path=str(path), metadata=metadata,
                                  basis="committed_manifest", meaning="Manifest identity is a clue, not proof of a product boundary."))
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            warnings.append("Unreadable committed manifest " + relative + ": " + str(exc))
    # Reuse the same metadata boundary reader as current geography, on old bytes.
    _, boundaries, truncated = navcom_space._boundaries(snapshot, warnings, 200)
    folders = sorted({"."} | {str(Path(m["path"]).parent) for m in manifests})
    clues = [dict(clue, relative_root=folder) for folder in folders
             for clue in navcom_space._source_clues(None, artifact, folder, root_source=folder == ".")]
    return dict(manifests=manifests, product_clues=clues, boundaries=boundaries,
                boundary_coverage=dict(limit=200, truncated=truncated),
                structure=_json_file(artifact / "structure.json"),
                harvest_coverage=source.get("coverage", {}), warnings=warnings)


def view(place="", revision="", *, action="timeline", repo=None, space_cache=None,
         source_cache=None, cache_path=None, include=None, query="", limit=50, **budgets):
    """Shared CLI/API historical journey; never return current conversations."""
    if action not in {"timeline", "explore"}:
        raise HistoryError("Historical action must be timeline or explore")
    if not isinstance(limit, int) or not 1 <= limit <= 200:
        raise HistoryError("History limit must be between 1 and 200")
    if not isinstance(query, str) or len(query) > 500:
        raise HistoryError("Historical query must contain at most 500 characters")
    selected = resolve_place(place, repo=repo, space_cache=space_cache, source_cache=source_cache, include=include)
    result = dict(schema_version=1, action=action, **selected,
                  history_scope="One repository and its selected paths at an exact commit; not a reconstruction of the whole galaxy.",
                  conversations=[], conversation_policy="Conversation history is excluded: no commit-to-conversation attribution has been established.")
    command = ["navcom", "history", action]
    if selected["selected_place"]:
        command.append(selected["selected_place"]["id"])
    if action == "explore":
        command.append(revision)
    command.extend(["--repo", selected["repository"], "--limit", str(limit)])
    for relative in selected["include"]:
        command.extend(["--include", relative])
    for option, value in (("--space-cache", space_cache), ("--source-cache", source_cache)):
        if selected["selected_place"] and value:
            command.extend([option, str(Path(value).expanduser().resolve())])
    if action == "explore" and cache_path:
        command.extend(["--cache", str(Path(cache_path).expanduser().resolve())])
        if query:
            command.extend(["--query", query])
        for key, value in budgets.items():
            command.extend(["--" + key.replace("_", "-"), str(value)])
    result["cli_command"] = shlex.join(command)
    if action == "timeline":
        result.update(timeline(selected["repository"], limit=limit, include=selected["include"]))
        return result
    if not revision:
        raise HistoryError("Explore requires a Git revision from the timeline")
    if not cache_path:
        raise HistoryError("Explore requires a private historical cache directory")
    prepared = harvest_revision(selected["repository"], revision, cache_path, selected["include"], **budgets)
    # Copying a result must replay its exact commit even if HEAD moves later.
    command[3 + bool(selected["selected_place"])]=prepared["commit"]
    result["cli_command"] = shlex.join(command)
    result.update(snapshot=prepared, **{key: prepared[key] for key in ("commit", "tree", "authored_at", "committed_at", "subject", "date_policy")})
    result.update(_historical_details(prepared))
    result["evidence"] = None
    if query.strip():
        import navcom_sources
        request = dict(action="search", cache=prepared["source_cache"], query=query, mode="both", limit=limit)
        worker = Path(navcom_sources.__file__).with_name("navcom_sources_worker.py")
        process = subprocess.run([navcom_sources.runtime(), str(worker)], input=json.dumps(request),
                                 capture_output=True, text=True, timeout=60)
        if process.returncode:
            raise HistoryError("Historical Starforge search failed: " + process.stderr.strip()[-800:], prepared["coverage"])
        result["evidence"] = json.loads(process.stdout)
        result["evidence"]["freshness"] = "Exact committed tree " + prepared["commit"] + "; current files are never searched."
        result["evidence"]["commit"] = prepared["commit"]
    return result
