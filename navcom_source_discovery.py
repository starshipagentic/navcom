"""Bounded source intake from NavCom's existing conversation project inventory.

This module selects bounded code and metadata for Starforge's harvest worker. It does not
classify products, implement search, copy files, or change the source projects.
"""

import contextlib
import fnmatch
import hashlib
import json
import os
from pathlib import Path
import select
import sqlite3
import subprocess
import tempfile
import time
from collections import Counter, deque

from navcom_discovery import Discovery


MAX_METADATA_FILES = 160
MAX_METADATA_BYTES = 8 * 1024 * 1024
MAX_METADATA_FILE_BYTES = 1024 * 1024
MAX_CODE_FILES = 400
MAX_CODE_BYTES = 8 * 1024 * 1024
MAX_CODE_FILE_BYTES = 2 * 1024 * 1024  # Broad search intake; grouping has its own smaller limit.
MAX_IGNORE_BATCH_BYTES = 512 * 1024
MAX_IGNORE_SECONDS = 5
MAX_IGNORE_OWNERS = 64
MAX_IGNORE_RESTARTS = 2
MAX_DIRECTORIES = 512
MAX_ENTRIES = 20000
MAX_DEPTH = 6
MAX_PROJECTS = 2000
PROJECT_MANIFESTS = {"package.json", "pyproject.toml", "Cargo.toml", "composer.json",
                     "pnpm-workspace.yaml", ".navcom-space.json"}
METADATA_NAMES = {"package.json", "pyproject.toml", "Cargo.toml", "composer.json",
                  "pnpm-workspace.yaml", "∑ship.md", "∆captainslog.md"}
NESTED_MANIFESTS = {"package.json", "pyproject.toml", "Cargo.toml", "composer.json"}
EXCLUDED_DIRS = {"node_modules", "vendor", "dist", "build", "__pycache__", "venv",
                 "env", "target", "coverage", "htmlcov", "site-packages", "bower_components",
                 "generated", "__generated__", "third_party", "third-party", "secrets", "credentials"}
CODE_SUFFIXES = {".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".rb", ".php",
                 ".java", ".kt", ".swift", ".c", ".cpp", ".h", ".hpp", ".cs", ".lua",
                 ".sh", ".bash", ".zsh"}


def _expertise_document(path):
    """Existing README policy plus a provider's authored charter, not config."""
    name = path.name.casefold()
    return name == "soul.md" or (name.startswith("readme") and path.suffix.casefold() == ".md")


def _git_root(path, *, with_status=False):
    try:
        result = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=2,
            env=dict(os.environ, GIT_OPTIONAL_LOCKS="0"),
        )
        if result.returncode == 0 and result.stdout.strip():
            root = Path(result.stdout.strip()).resolve()
            return (root, True) if with_status else root
    except (OSError, subprocess.TimeoutExpired):
        pass
    return (path, False) if with_status else path


def _project_nodes(projects, maximum):
    if not isinstance(projects, list) or len(projects) > maximum:
        raise ValueError("A pinned project page must contain at most " + str(maximum) + " inventory nodes")
    nodes = []
    for node in projects:
        if not isinstance(node, dict) or not isinstance(node.get("label"), str) or len(node["label"]) > 4096:
            raise ValueError("Pinned project nodes need a bounded project label")
        collection = node.get("collection")
        if collection is not None and (not isinstance(collection, str) or len(collection) > 4096):
            raise ValueError("Pinned project collection identity is invalid")
        nodes.append(dict(label=node["label"], collection=collection))
    return nodes


def group_projects(projects):
    """Pin inventory jobs by native Git root without inventing project ownership.

    Missing/non-local rows remain queued so discovery can report their omission.
    A large single repository is split explicitly at the existing 200-row page
    limit; all associations survive, and no arbitrary prefix is dropped.
    """
    nodes = _project_nodes(projects, MAX_PROJECTS)
    groups = {}
    roots_by_path = {}
    for node in nodes:
        path = Path(node["label"]).expanduser()
        if path.is_absolute() and path.is_dir() and not path.is_symlink():
            canonical = path.resolve()
            if canonical not in roots_by_path:
                roots_by_path[canonical] = str(_git_root(canonical))
            root = roots_by_path[canonical]
        else:
            root = node["label"]
        group = groups.setdefault(root, [])
        if node not in group:
            group.append(node)
    jobs = []
    split = []
    for root, rows in groups.items():
        if len(rows) > 200:
            split.append(dict(root=root, projects=len(rows), jobs=(len(rows) + 199) // 200))
        for offset in range(0, len(rows), 200):
            jobs.append(dict(root=root, projects=rows[offset:offset + 200]))
    return dict(jobs=jobs, coverage=dict(inventory_rows=len(nodes), root_groups=len(groups),
                jobs=len(jobs), split_groups=split, grouping="native Git working-tree root; unresolved rows retained",
                max_inventory_rows=MAX_PROJECTS, max_projects_per_job=200))


def _has_project_manifest(root):
    for name in PROJECT_MANIFESTS:
        path = root / name
        try:
            if not path.is_symlink() and path.is_file() and path.stat().st_size <= MAX_METADATA_FILE_BYTES:
                return True
        except OSError:
            pass
    return False


class _GitIgnore:
    """One native, streaming Git policy process for a bounded source selection.

    --non-matching emits one four-field record for every requested path, so the
    client can read a complete batch without closing stdin or starting Git again.
    Native Git decides patterns, global rules and the tracked-file exemption.
    """
    def __init__(self, root):
        self.root = root
        self.process = None
        self.errors = None
        self.starts = 0

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        if self.process:
            if self.process.stdin and not self.process.stdin.closed:
                self.process.stdin.close()
            if self.process.poll() is None:
                try:
                    self.process.wait(timeout=.2)
                except subprocess.TimeoutExpired:
                    self.process.kill(); self.process.wait()
            self.process.stdout.close()
        if self.errors:
            self.errors.close()

    def _not_repository(self):
        self.errors.seek(0)
        return b"not a git repository" in self.errors.read(4096).lower()

    def check(self, payload, timeout):
        if len(payload) > MAX_IGNORE_BATCH_BYTES:
            raise ValueError("native Git request exceeds its byte budget")
        expected = payload.split(b"\0")[:-1]
        if not expected or not payload.endswith(b"\0"):
            raise ValueError("native Git request is not a complete path batch")
        deadline = time.monotonic() + timeout
        if self.process is None:
            self.errors = tempfile.TemporaryFile()
            self.process = subprocess.Popen(
                ["git", "-C", str(self.root), "check-ignore", "--stdin", "-z", "--verbose", "--non-matching"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.errors,
                env=dict(os.environ, GIT_OPTIONAL_LOCKS="0", GIT_FLUSH="1", LC_ALL="C"),
            )
            self.starts += 1
            os.set_blocking(self.process.stdin.fileno(), False)
            os.set_blocking(self.process.stdout.fileno(), False)
        sent = 0
        output = bytearray()
        # stdout can be larger than stdin because Git includes the winning
        # rule. Concurrent read/write avoids a pipe-buffer deadlock.
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired("git check-ignore", timeout)
            if os.fstat(self.errors.fileno()).st_size > 65536:
                raise ValueError("native Git errors exceed their output budget")
            readers, writers, _ = select.select([self.process.stdout],
                [self.process.stdin] if sent < len(payload) else [], [], min(.05, remaining))
            if writers:
                try:
                    sent += os.write(self.process.stdin.fileno(), payload[sent:sent + 65536])
                except BrokenPipeError:
                    if self._not_repository():
                        return None
                    raise ValueError("native Git closed its input before the batch completed") from None
                except BlockingIOError:
                    pass
            if readers:
                chunk = os.read(self.process.stdout.fileno(), 65536)
                if not chunk:
                    if self._not_repository():
                        return None
                    raise ValueError("native Git closed its output before the batch completed")
                output.extend(chunk)
                if len(output) > MAX_IGNORE_BATCH_BYTES * 4:
                    raise ValueError("native Git response exceeds its output budget")
                fields = output.split(b"\0")
                if len(fields) == 4 * len(expected) + 1 and fields[-1] == b"":
                    actual = [bytes(fields[i]) for i in range(3, len(fields) - 1, 4)]
                    if sent != len(payload) or actual != expected:
                        raise ValueError("native Git returned unexpected path records")
                    # Git's verbose protocol includes explicit negation matches;
                    # these mean the path is not ignored, like unmatched records.
                    return {path for index, path in enumerate(actual)
                            if fields[index * 4 + 2] and not fields[index * 4 + 2].startswith(b"!")}
                if len(fields) > 4 * len(expected) + 1:
                    raise ValueError("native Git returned extra path records")


class _GitIgnoreTree:
    """Route the existing bounded walk to native Git owners, never through gitlinks.

    A directory is checked by its parent before its contents are routed to a
    child repository. All processes and ownership checks share one time budget.
    Failed batches stay unknown; later batches can restart only that owner.
    """
    def __init__(self, root):
        self.root = root
        self.owners = {root: self._record(root)}
        self.registered = set()
        self.declared = set()
        self.seconds = 0
        self.metadata_commands = 0
        self.processes = []
        self.decisions = {}
        self.reasons = {}

    @staticmethod
    def _record(root):
        return dict(root=root, checker=None, status="not-checked", checked_paths=0,
                    ignored_paths=0, unknown_paths=0, failures=0, restarts=0)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        for checker in self.processes:
            checker.close()

    def _remaining(self):
        remaining = MAX_IGNORE_SECONDS - self.seconds
        if remaining <= 0:
            raise subprocess.TimeoutExpired("native Git ignore policy", MAX_IGNORE_SECONDS)
        return min(2, remaining)

    def _native(self, argv):
        # Native metadata output is file-backed and bounded, including stderr.
        started = time.monotonic()
        try:
            timeout = self._remaining()
            with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
                self.metadata_commands += 1
                result = subprocess.run(argv, stdout=output, stderr=errors, timeout=timeout,
                    env=dict(os.environ, GIT_OPTIONAL_LOCKS="0", LC_ALL="C"))
                if output.tell() > 65536 or errors.tell() > 65536:
                    raise ValueError("native Git ownership metadata exceeds its byte budget")
                output.seek(0)
                return result.returncode, output.read(65537)
        finally:
            self.seconds += time.monotonic() - started

    def _owner(self, path):
        return max((folder for folder in self.owners if folder == path or folder in path.parents),
                   key=lambda folder: len(folder.parts))

    def register(self, folder):
        """Called only for directories reached by the existing safe bounded walk."""
        if folder in self.registered:
            return
        self.registered.add(folder)
        marker = folder / ".git"
        boundary = marker.exists() or marker.is_symlink() or folder in self.declared
        if folder != self.root and not boundary:
            return
        record = self.owners.get(folder)
        if record is None:
            record = self._record(folder)
            self.owners[folder] = record
            try:
                if len(self.owners) > MAX_IGNORE_OWNERS:
                    raise ValueError("native Git owner budget exceeded")
                if marker.is_symlink() or not marker.exists():
                    raise ValueError("declared Git boundary has no usable working-tree marker")
                code, output = self._native(["git", "-C", str(folder), "rev-parse", "--show-toplevel"])
                if code or Path(os.fsdecode(output).strip()).resolve() != folder.resolve():
                    raise ValueError("native Git did not verify the selected working-tree root")
            except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
                record.update(status="unavailable", blocked=True, reason=type(exc).__name__)
                return
        record["expected_repository"] = boundary
        modules = folder / ".gitmodules"
        if not marker.exists() or not modules.exists():
            return
        try:
            if modules.is_symlink() or not modules.is_file() or modules.stat().st_size > MAX_METADATA_FILE_BYTES:
                raise ValueError("submodule declarations exceed their bounded regular-file policy")
            code, output = self._native(["git", "config", "--no-includes", "--null", "--file", str(modules),
                                         "--get-regexp", r"^submodule\..*\.path$"])
            if code not in (0, 1):
                raise ValueError("native Git could not read submodule paths")
            records = output.split(b"\0")[:-1]
            if output and not output.endswith(b"\0") or len(records) > MAX_IGNORE_OWNERS:
                raise ValueError("submodule declaration output exceeds its record budget")
            for value in records:
                _, separator, value = value.partition(b"\n")
                relative = Path(os.fsdecode(value))
                if not separator or not relative.parts or relative.is_absolute() or ".." in relative.parts:
                    raise ValueError("native Git returned an unsafe submodule address")
                self.declared.add(folder / relative)
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            # Check-ignore remains authoritative. A malformed declaration cannot
            # poison its stream permanently; a failed batch is explicitly unknown.
            record["declaration_error"] = type(exc).__name__

    def _unknown(self, record, paths, reason="Git ignore policy unavailable"):
        for path in paths:
            self.decisions[path] = True
            self.reasons[path] = reason
        record["unknown_paths"] += len(paths)

    def check(self, paths):
        grouped = {}
        for path in paths:
            if path not in self.decisions:
                grouped.setdefault(self._owner(path.parent), []).append(path)
        for owner, paths in grouped.items():
            record = self.owners[owner]
            if record.get("blocked"):
                self._unknown(record, paths)
                continue
            if record["status"] == "not-a-repository":
                self.decisions.update((path, False) for path in paths)
                continue
            pending = deque(paths)
            while pending:
                batch, payload = [], bytearray()
                while pending:
                    path = pending[0]
                    entry = os.fsencode(str(path.relative_to(owner))) + b"\0"
                    if payload and len(payload) + len(entry) > MAX_IGNORE_BATCH_BYTES:
                        break
                    pending.popleft()
                    if len(entry) > MAX_IGNORE_BATCH_BYTES:
                        self._unknown(record, [path], "path exceeds Git ignore request budget")
                        continue
                    batch.append(path)
                    payload.extend(entry)
                if not batch:
                    continue
                started = time.monotonic()
                try:
                    timeout = self._remaining()
                    if record["checker"] is None:
                        if record["failures"] > MAX_IGNORE_RESTARTS:
                            raise ValueError("native Git restart budget exhausted")
                        record["restarts"] = record["failures"]
                        record["checker"] = _GitIgnore(owner)
                        self.processes.append(record["checker"])
                    omitted = record["checker"].check(bytes(payload), timeout)
                    if omitted is None:
                        # A verified child cannot become an ordinary directory
                        # when its Git metadata disappears during this selection.
                        if record.get("expected_repository") or owner != self.root:
                            raise ValueError("verified Git owner became unavailable")
                        record["status"] = "not-a-repository"
                        self.decisions.update((path, False) for path in batch + list(pending))
                        break
                    if not omitted <= set(bytes(payload).split(b"\0")):
                        raise ValueError("native Git returned an unexpected ignore path")
                    for path in batch:
                        self.decisions[path] = os.fsencode(str(path.relative_to(owner))) in omitted
                        if self.decisions[path]:
                            self.reasons[path] = "Git ignored automatic input"
                    record["status"] = "available"
                    record["checked_paths"] += len(batch)
                    record["ignored_paths"] += len(omitted)
                except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
                    record.update(status="unavailable", reason=type(exc).__name__)
                    record["failures"] += 1
                    self._unknown(record, batch)
                    if record["checker"]:
                        record["checker"].close()
                        record["checker"] = None
                    # The next batch starts a fresh native process under the
                    # same shared deadline; unrelated owners are unaffected.
                finally:
                    self.seconds += time.monotonic() - started

    def coverage(self):
        records = []
        for root, record in sorted(self.owners.items()):
            row = {key: value for key, value in record.items()
                   if key not in {"root", "checker", "blocked", "expected_repository"}}
            row["path"] = str(root.relative_to(self.root))
            if row["unknown_paths"] and row["checked_paths"]:
                row["status"] = "partial"
            records.append(row)
        statuses = {row["status"] for row in records}
        status = next(iter(statuses)) if len(statuses) == 1 else "partial"
        result = dict(status=status, engine="git check-ignore --stdin -z --verbose --non-matching",
                      commands=sum(checker.starts for checker in self.processes),
                      ownership_commands=self.metadata_commands, owners=records)
        for key in ("checked_paths", "ignored_paths", "unknown_paths"):
            result[key] = sum(row[key] for row in records)
        if result["unknown_paths"] or any("declaration_error" in row for row in records):
            result["fallback"] = "Unchecked automatic paths omitted; explicit registered scopes retained."
        return result


def _metadata(root, max_files=10000, max_bytes=64 * 1024 * 1024, max_file_bytes=2 * 1024 * 1024,
              *, project_boundaries=(), container=False, family_cache=None):
    with _GitIgnoreTree(root) as ignore:
        return _select_metadata(root, ignore, max_files, max_bytes, max_file_bytes,
                                project_boundaries, container, family_cache)


def _select_metadata(root, ignore, max_files, max_bytes, max_file_bytes, project_boundaries, container, family_cache):
    """Select metadata first, then code fairly across declared workspace roots.

    The historical private name is retained for callers. Only metadata is read
    here; code bytes, native grouping and search belong to the harvest worker.
    Budgets describe observed omissions, never a claim about unvisited folders.
    """
    selected = set()
    selected_kinds = Counter()
    selected_bytes = Counter()
    attempted = set()
    excluded = []
    excluded_counts = Counter()
    limited = []
    total_bytes = 0
    inspected_dirs = 0
    inspected_entries = 0
    directory_cache = {}

    def reject(path, reason):
        item = {"path": str(path.relative_to(root)), "reason": reason}
        # A directory can be reached through metadata and code traversal.
        key = (item["path"], reason)
        if key in rejected:
            return
        rejected.add(key)
        excluded_counts[reason] += 1
        if len(excluded) < 500:
            excluded.append(item)

    rejected = set()

    def needs_ignore_policy(path):
        """Do not ask Git about bytes this intake can never select or traverse."""
        relative = path.relative_to(root)
        if any(part.startswith(".") or part.casefold() in EXCLUDED_DIRS for part in relative.parts) or path.is_symlink():
            return False
        return (path.is_dir() or path.name in METADATA_NAMES or _expertise_document(path)
                or path.suffix.lower() in CODE_SUFFIXES | {".md"})

    def children(folder):
        nonlocal inspected_dirs, inspected_entries
        if folder in directory_cache:
            return directory_cache[folder]
        inspected_dirs += 1
        if inspected_dirs > MAX_DIRECTORIES:
            limited.append("directory budget exceeded")
            reject(folder, "directory budget; subtree unvisited")
            directory_cache[folder] = []
            return []
        try:
            entries = []
            with os.scandir(folder) as items:
                for item in items:
                    inspected_entries += 1
                    if inspected_entries > MAX_ENTRIES:
                        limited.append("directory entry budget exceeded")
                        # Do not choose an arbitrary OS-order prefix. Omit this
                        # folder altogether when it cannot be enumerated safely.
                        entries = []
                        reject(folder, "directory entry budget; folder unvisited")
                        break
                    entries.append(folder / item.name)
            entries.sort(key=lambda p: p.name)
            ignore.register(folder)
            ignore.check([path for path in entries if needs_ignore_policy(path)])
            directory_cache[folder] = entries
        except OSError as exc:
            reject(folder, type(exc).__name__)
            directory_cache[folder] = []
        return directory_cache[folder]

    def safe(path):
        relative = path.relative_to(root)
        if any(part.startswith(".") or part.casefold() in EXCLUDED_DIRS for part in relative.parts):
            reject(path, "hidden, secret or generated path")
            return False
        if any((root.joinpath(*relative.parts[:i])).is_symlink()
               for i in range(1, len(relative.parts) + 1)):
            reject(path, "symlink")
            return False
        if container:
            if any(path == boundary or boundary in path.parents for boundary in project_boundaries):
                reject(path, "indexed child project delegated to its own source")
                return False
            if path.is_dir() and (path / ".git").exists():
                reject(path, "nested Git repository omitted from container scope")
                return False
            if path.is_dir() and _has_project_manifest(path):
                reject(path, "nested product manifest omitted from container scope")
                return False
        # Unsupported assets are rejected by the existing selection rules;
        # their Git policy cannot turn them into automatic source inputs.
        if not needs_ignore_policy(path):
            return True
        ignore.check([path])
        if ignore.decisions.get(path):
            reject(path, ignore.reasons.get(path, "Git ignore policy unavailable"))
            return False
        return True

    def add(path, kind="metadata"):
        nonlocal total_bytes
        if path in attempted or not safe(path) or not path.is_file():
            return
        attempted.add(path)
        try:
            size = path.stat().st_size
        except OSError as exc:
            reject(path, type(exc).__name__)
            return
        file_limit = min(max_file_bytes, MAX_METADATA_FILE_BYTES if kind == "metadata" else MAX_CODE_FILE_BYTES)
        count_limit = MAX_METADATA_FILES if kind == "metadata" else MAX_CODE_FILES
        byte_limit = MAX_METADATA_BYTES if kind == "metadata" else MAX_CODE_BYTES
        if size > file_limit:
            reject(path, kind + " file size limit")
            return
        if selected_kinds[kind] >= count_limit or selected_bytes[kind] + size > byte_limit:
            limited.append(kind + " file/byte budget exceeded")
            reject(path, kind + " file/byte budget")
            return
        if len(selected) >= max_files or total_bytes + size > max_bytes:
            limited.append("registered source file/byte budget exceeded")
            reject(path, "registered source file/byte budget")
            return
        selected.add(path)
        selected_kinds[kind] += 1
        selected_bytes[kind] += size
        total_bytes += size

    def patterns(folder):
        found = []
        package = folder / "package.json"
        if package in selected:
            try:
                data = json.loads(package.read_text())
                workspace = data.get("workspaces", [])
                if isinstance(workspace, dict):
                    workspace = workspace.get("packages", [])
                if isinstance(workspace, list):
                    found.extend(p for p in workspace if isinstance(p, str))
            except (OSError, ValueError, AttributeError):
                reject(package, "invalid package manifest")
        for filename, parent in (("pyproject.toml", "tool"), ("Cargo.toml", "workspace")):
            manifest = folder / filename
            if manifest not in selected:
                continue
            try:
                import tomllib
                data = tomllib.loads(manifest.read_text())
                workspace = (data.get("tool", {}).get("uv", {}).get("workspace", {})
                             if parent == "tool" else data.get("workspace", {}))
                members = workspace.get("members", [])
                if isinstance(members, list):
                    found.extend(p for p in members if isinstance(p, str))
            except ImportError:
                reject(manifest, "workspace TOML requires Python 3.11 or newer")
            except (OSError, ValueError, AttributeError):
                reject(manifest, "invalid workspace manifest")
        # pnpm's YAML is retained for Starforge, but not partially parsed here.
        if folder / "pnpm-workspace.yaml" in selected and not found:
            limited.append("pnpm workspace retained; YAML membership was not parsed")
        return found

    def expand(folder, pattern):
        parts = Path(pattern).parts
        if not parts or Path(pattern).is_absolute() or ".." in parts or pattern.startswith("!"):
            limited.append("unsupported workspace pattern: " + pattern)
            return []
        candidates = [folder]
        for component in parts:
            if component == ".":
                continue
            if component == "**":
                limited.append("recursive workspace glob omitted: " + pattern)
                return []
            next_candidates = []
            for current in candidates:
                for child in children(current):
                    if fnmatch.fnmatchcase(child.name, component) and safe(child) and child.is_dir():
                        if len(child.relative_to(root).parts) > MAX_DEPTH:
                            limited.append("workspace depth budget exceeded")
                        else:
                            next_candidates.append(child)
            candidates = next_candidates
        return candidates

    pending = [root]
    application_roots = set()
    while pending:
        folder = pending.pop(0)
        if folder in application_roots:
            continue
        application_roots.add(folder)
        for path in children(folder):
            if path.name in METADATA_NAMES or _expertise_document(path):
                add(path)
        for pattern in patterns(folder):
            pending.extend(expand(folder, pattern))
        docs = folder / "docs"
        if docs.is_dir() and safe(docs):
            doc_folders = [(docs, 0)]
            while doc_folders:
                current, depth = doc_folders.pop(0)
                for path in children(current):
                    if not safe(path):
                        continue
                    if path.is_file() and path.suffix.lower() == ".md":
                        add(path)
                    elif path.is_dir() and depth < 1:
                        doc_folders.append((path, depth + 1))
                    elif path.is_dir():
                        limited.append("docs beyond two directory levels omitted")
                        reject(path, "docs depth budget; subtree unvisited")
    # This same bounded walk finds nested manifests and expertise documents.
    # Collect code paths (not bytes) until boundaries are known, then sample each
    # manifest root fairly. A repository without workspaces must not exhaust its
    # code budget before an independently runnable nested app gets a turn.
    def code_files(app_root):
        folders = deque([(app_root, 0)])
        while folders:
            folder, depth = folders.popleft()
            for path in children(folder):
                if not safe(path):
                    continue
                if path.is_dir():
                    if path in application_roots and path != app_root:
                        continue
                    if depth >= MAX_DEPTH:
                        limited.append("code depth budget exceeded")
                        reject(path, "code depth budget; subtree unvisited")
                    else:
                        folders.append((path, depth + 1))
                elif path.is_file() and path not in attempted:
                    if path.name in NESTED_MANIFESTS or _expertise_document(path):
                        yield path, "metadata"
                    elif path.suffix.lower() not in CODE_SUFFIXES:
                        reject(path, "not an automatic code or metadata input")
                    elif any(marker in path.name.lower() for marker in (".min.", ".generated.", ".gen.", "_pb2.")):
                        reject(path, "generated code file")
                    else:
                        yield path, "code"

    streams = deque(iter(code_files(app)) for app in sorted(application_roots))
    code_candidates = []
    while streams:
        stream = streams.popleft()
        item = next(stream, None)
        if item is not None:
            if item[1] == "metadata":
                add(*item)
            else:
                code_candidates.append(item[0])
            streams.append(stream)
    manifest_roots = {path.parent for path in selected if path.name in NESTED_MANIFESTS}
    # Reuse the same native family adapter as the relationship view. Its inputs
    # are already accepted paths from this bounded walk, never an extra scan.
    directories = {parent.relative_to(root) for file in code_candidates for parent in file.parents
                   if parent != root and root in parent.parents}
    from navcom_native_families import analyze
    family_analysis = analyze(directories, root.name, family_cache) if len(directories) > 1 else dict(
        status="not-needed", families=[], omitted=[])
    # Runtime cache hits are telemetry, not source metadata: toggling them must
    # not invalidate an otherwise unchanged harvest receipt.
    family_analysis.pop("cached", None)
    limited.extend(family_analysis.get("omitted", []))
    version_roots = {root / member["path"] for family in family_analysis["families"] for member in family["members"]}
    sampling_roots = application_roots | manifest_roots | version_roots
    by_root = {folder: deque() for folder in sorted(sampling_roots)}
    for candidate in code_candidates:
        owner = max((folder for folder in sampling_roots if folder == candidate.parent or folder in candidate.parents),
                    key=lambda folder: len(folder.parts))
        by_root[owner].append(candidate)
    pending_code = deque(files for files in by_root.values() if files)
    while pending_code:
        files = pending_code.popleft()
        add(files.popleft(), "code")
        if files:
            pending_code.append(files)
    ignore_policy = ignore.coverage()
    if ignore_policy["unknown_paths"]:
        limited.append("Git ignore policy unavailable; unchecked automatic paths omitted")
    if any("declaration_error" in owner for owner in ignore_policy["owners"]):
        limited.append("Git submodule declaration metadata unavailable; native path decisions remain authoritative")
    return sorted(str(p.relative_to(root)) for p in selected), {
        "metadata_files": selected_kinds["metadata"], "metadata_bytes": selected_bytes["metadata"],
        "code_files": selected_kinds["code"], "code_bytes": selected_bytes["code"],
        "selected_files": len(selected), "selected_bytes": total_bytes,
        "inspected_directories": min(inspected_dirs, MAX_DIRECTORIES),
        "inspected_entries": min(inspected_entries, MAX_ENTRIES),
        "application_roots": sorted(str(p.relative_to(root)) for p in application_roots),
        "manifest_roots": sorted(str(p.relative_to(root)) for p in manifest_roots),
        "version_sampling": family_analysis,
        "version_roots": sorted(str(p.relative_to(root)) for p in version_roots),
        "code_sampling": "Round-robin across declared workspaces, retained manifest roots and native version-family members; sampling buckets do not establish products or ancestry.",
        "excluded": sorted(excluded, key=lambda e: (e["path"], e["reason"])),
        "excluded_counts": dict(sorted(excluded_counts.items())),
        "excluded_details_truncated": len(rejected) > len(excluded),
        "git_ignore": ignore_policy,
        "limits": sorted(set(limited)),
        "budgets": dict(metadata_files=MAX_METADATA_FILES, metadata_bytes=MAX_METADATA_BYTES,
                        code_files=MAX_CODE_FILES, code_bytes=MAX_CODE_BYTES, code_file_bytes=MAX_CODE_FILE_BYTES,
                        git_ignore_seconds=MAX_IGNORE_SECONDS, git_ignore_batch_bytes=MAX_IGNORE_BATCH_BYTES,
                        git_ignore_owners=MAX_IGNORE_OWNERS, git_ignore_restarts_per_owner=MAX_IGNORE_RESTARTS,
                        native_family_seconds=3,
                        directories=MAX_DIRECTORIES, entries=MAX_ENTRIES, code_depth=MAX_DEPTH),
        "omissions_meaning": "Counts cover observed files or directory roots; unvisited descendants are not counted.",
        "full_repository": False,
        "container_policy": dict(enabled=container,
                                 basis="No native Git root or bounded project manifest" if container else
                                       "Normal automatic source scope",
                                 indexed_boundaries=[str(path.relative_to(root)) for path in project_boundaries] if container else []),
    }


def discover(api, index_path, cache_path, limit=200, offset=0, within=None, progress=None, *, projects=None,
             project_boundaries=None):
    """Discover one inventory page and preserve registered source scopes.

    ``projects`` is an internal page of already pinned Discovery nodes, not a
    classification configuration. Its caller owns pagination/completion state.
    Supplying it avoids re-querying a changing conversation inventory mid-run.
    """
    if not 1 <= limit <= 200 or offset < 0:
        raise ValueError("limit must be 1–200 and offset must be nonnegative")
    cache_path = Path(cache_path).expanduser()
    pointer = cache_path / "current.json"
    existing = json.loads(pointer.read_text()).get("sources", []) if pointer.exists() else []
    registered = {str(Path(s["root"]).resolve()): s for s in existing}
    params = {"action": ["list"], "grouping": ["projects"],
              "limit": [str(limit)], "offset": [str(offset)]}
    if within:
        params["within"] = [within]
    if projects is None:
        index_path = Path(index_path).expanduser()
        if not index_path.is_file():
            raise ValueError("Conversation index unavailable; index conversations first")
        with contextlib.closing(sqlite3.connect(index_path.resolve().as_uri() + "?mode=ro", uri=True, timeout=.3)) as conn:
            inventory = Discovery(api).view(conn, params)
    else:
        nodes = _project_nodes(projects, min(limit, 200))
        inventory = dict(nodes=nodes, more=False, freshness=None)
    boundary_nodes = _project_nodes(project_boundaries, MAX_PROJECTS) if project_boundaries is not None else inventory["nodes"]
    boundaries = set()
    for node in boundary_nodes:
        candidate = Path(node.get("label", "")).expanduser()
        if candidate.is_absolute() and not candidate.is_symlink():
            boundaries.add(candidate.resolve())
    grouped = {}
    native_roots = set()
    skipped = []
    for node in inventory["nodes"]:
        label = node.get("label", "")
        path = Path(label).expanduser()
        if not path.is_absolute():
            skipped.append({"path": label, "reason": "not a local absolute project path"})
            continue
        if not path.is_dir() or path.is_symlink():
            skipped.append({"path": label, "reason": "missing directory or symlink"})
            continue
        path = path.resolve()
        root, native = _git_root(path, with_status=True)
        if native:
            native_roots.add(root)
        grouped.setdefault(root, []).append({"path": str(path), "collection": node.get("collection")})
    sources, scopes = [], []
    for ordinal, (root, associations) in enumerate(sorted(grouped.items()), 1):
        if progress:
            progress(ordinal, len(grouped), str(root))
        old = registered.get(str(root), {})
        container = root not in native_roots and not _has_project_manifest(root)
        nested_boundaries = sorted(path for path in boundaries if path != root and root in path.parents)
        metadata, scope = _metadata(root, max_files=old.get("max_files", 10000),
                                    max_bytes=old.get("max_bytes", 64 * 1024 * 1024),
                                    max_file_bytes=old.get("max_file_bytes", 2 * 1024 * 1024),
                                    project_boundaries=nested_boundaries, container=container,
                                    family_cache=cache_path / "discovery-families" if not cache_path.resolve().is_relative_to(root) else None)
        scopes.append(dict(root=str(root), **scope))
        prior_auto = set(old.get("discovery_include", []))
        explicit = [p for p in old.get("include", []) if p not in prior_auto]
        if not metadata and not explicit:
            skipped.append({"path": str(root), "reason": "no supported bounded code or metadata inputs"})
            continue
        source = {k: v for k, v in old.items() if k not in ("artifact", "signature", "extractor", "coverage")}
        source.update(
            id=hashlib.sha256(str(root).encode()).hexdigest()[:16], root=str(root),
            label=old.get("label", root.name),
            include=list(dict.fromkeys(explicit + metadata)),
            discovery_include=metadata, discovery_coverage=scope,
            max_files=old.get("max_files", 10000),
            max_bytes=old.get("max_bytes", 64 * 1024 * 1024),
            max_file_bytes=old.get("max_file_bytes", 2 * 1024 * 1024),
            conversation_collection=next((a["collection"] for a in associations if a["path"] == str(root)), old.get("conversation_collection")),
        )
        all_associations = {a["path"]: a for a in old.get("conversation_projects", [])}
        all_associations.update({a["path"]: a for a in associations})
        source["conversation_projects"] = [all_associations[k] for k in sorted(all_associations)]
        source["conversation_collections"] = sorted({a["collection"] for a in all_associations.values() if a["collection"]})
        sources.append(source)
    return {"sources": sources, "coverage": {
        "offset": offset, "limit": limit, "inventory_rows": len(inventory["nodes"]),
        "more": bool(inventory.get("more")),
        "next_offset": offset + limit if inventory.get("more") else None,
        "within": within, "freshness": inventory.get("freshness"),
        "sources": len(sources), "skipped": skipped, "scopes": scopes,
        "selection": "bounded code and metadata; declared workspaces sampled fairly; existing registered scopes retained",
        "full_inventory": projects is None and not offset and not inventory.get("more"),
        "selection_input": "pinned_project_page" if projects is not None else "live_discovery_page",
    }}
