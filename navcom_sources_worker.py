#!/usr/bin/env python3
"""Private Starforge worker: immutable local harvest snapshots and native search adapters."""

import contextlib, fcntl, hashlib, json, os, shutil, sys, tempfile, time
from pathlib import Path

sys.dont_write_bytecode = True
import starforge

SF = Path(starforge.__file__).resolve().parent.parent
from starforge.catalog import Catalog
from starforge.analyzer import ProjectAnalyzer
from starforge.gem_finder import GemFinder
from starforge.harvester import Harvester
from starforge.concept_search import concept_search, _extract_keywords
from starforge.utils import SKIP_DIRS

DEFAULT = Path.home() / ".cache/navcom/sources"
EXT = {
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".sh",
    ".lua",
    ".rb",
    ".go",
    ".rs",
    ".md",
    ".toml",
    ".php",
    ".java",
    ".kt",
    ".swift",
    ".c",
    ".cpp",
    ".h",
    ".hpp",
    ".cs",
    ".bash",
    ".zsh",
    ".yaml",
    ".yml",
    ".json",
}
SKIP = set(SKIP_DIRS)
SOURCE_FILENAMES = {"package.json", "requirements.txt", "Makefile", "Dockerfile"}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read(path):
    return json.loads(path.read_text())


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".publish-")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def progress(message):
    print("navcom sources ▸ " + message, file=sys.stderr, flush=True)


def source_bytes(source):
    root = Path(source["root"])
    if not root.is_dir():
        raise ValueError("Source unavailable: " + str(root))
    paths = set()
    excluded = []
    for item in source["include"]:
        rel = Path(item)
        if rel.is_absolute() or ".." in rel.parts:
            raise ValueError("Scope must stay inside its source")
        if any(part.startswith(".") or part in SKIP for part in rel.parts):
            excluded.append(str(rel))
            continue
        target = root / rel
        if not target.exists():
            raise ValueError("Selected scope missing: " + str(target))
        if target.is_symlink() or not target.resolve().is_relative_to(root.resolve()):
            raise ValueError("Scope escapes source")
        if target.is_file():
            paths.add(target)
        else:
            for folder, dirs, names in os.walk(target, followlinks=False):
                parent = Path(folder)
                for d in dirs:
                    if d in SKIP or d.startswith(".") or (parent / d).is_symlink():
                        excluded.append(str((parent / d).relative_to(root)))
                dirs[:] = sorted(
                    d
                    for d in dirs
                    if d not in SKIP
                    and not d.startswith(".")
                    and not (parent / d).is_symlink()
                )
                paths.update(parent / name for name in names)
    payload = {}
    total = 0
    for path in sorted(paths):
        rel = str(path.relative_to(root))
        if path.is_symlink():
            excluded.append(rel)
            continue
        if path.name.startswith(".") or (
            path.suffix.lower() not in EXT
            and path.name not in SOURCE_FILENAMES
        ):
            excluded.append(rel)
            continue
        if path.stat().st_size > source.get("max_file_bytes", 2 * 1024 * 1024):
            raise ValueError("Oversize selected file: " + rel)
        data = path.read_bytes()
        total += len(data)
        if len(payload) >= source.get("max_files", 10000) or total > source.get(
            "max_bytes", 64 * 1024 * 1024
        ):
            raise ValueError(
                "Source scan budget exceeded; narrow --include or raise --max-files / --max-bytes"
            )
        payload[rel] = data
    if not payload:
        raise ValueError("No supported files in selected scope")
    signature = digest(
        json.dumps([(p, digest(b)) for p, b in payload.items()]).encode()
    )
    return (
        payload,
        signature,
        dict(
            files=len(payload),
            bytes=total,
            include=source["include"],
            excluded=sorted(excluded),
            supported_extensions=sorted(EXT),
            full_repository=False,
        ),
    )


def _worker_component(source, roots):
    """Hash the executable definitions reachable from a worker entry point.

    Deriving dependencies avoids a hand-maintained list of harvest helpers.
    Imports are indexed by binding so a search-only import does not change a
    harvest key. AST serialization deliberately ignores formatting/comments.
    """
    import ast
    definitions = {}
    for node in ast.parse(source).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            definitions[node.name] = node
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                binding = alias.asname or (alias.name.split(".")[0] if isinstance(node, ast.Import) else alias.name)
                definitions[binding] = (ast.Import(names=[alias]) if isinstance(node, ast.Import)
                                        else ast.ImportFrom(module=node.module, names=[alias], level=node.level))
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    definitions[target.id] = node
    selected, pending = {}, list(roots)
    while pending:
        name = pending.pop()
        if name in selected or name not in definitions:
            continue
        node = definitions[name]
        selected[name] = ast.dump(node, include_attributes=False)
        pending.extend(child.id for child in ast.walk(node)
                       if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load))
    if not all(name in selected for name in roots):
        raise RuntimeError("Missing worker fingerprint entry point")
    return selected


def _component_signature(roots):
    # Conservatively include all installed native modules: Starforge dispatches
    # through several plugin/CLI registries as well as direct imports.
    native = [(str(path.relative_to(SF)), digest(path.read_bytes()))
              for path in sorted((SF / "starforge").glob("*.py"))]
    worker = _worker_component(Path(__file__).read_text(), roots)
    return digest(json.dumps(["component-v1", native, worker], sort_keys=True).encode())


def extractor_signature():
    """Harvest identity, independent of query/ranking/returned-hit changes.

    This intentionally replaces the legacy whole-worker fingerprint once, when
    each selected source next refreshes. Existing artifacts remain readable.
    """
    return _component_signature(("refresh",))


def query_signature():
    """Retrieval and source-reference identity; never a harvest cache key."""
    return _component_signature(("combined_search", "batch_search"))


@contextlib.contextmanager
def writer(cache):
    cache.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (cache / "writer.lock").open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError(
                "Another source harvest is running; cached search remains available"
            )
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


@contextlib.contextmanager
def staged_catalog(path):
    """Buffer native TinyDB writes while building an unpublished catalog.

    Starforge's Catalog does not expose a storage constructor argument. Attach
    TinyDB's own middleware to this private staging database; all native
    Catalog and Harvester methods retain their normal semantics. Closing the
    database flushes every pending write before callers read or publish it.
    """
    from tinydb import TinyDB
    from tinydb.middlewares import CachingMiddleware
    from tinydb.storages import JSONStorage
    catalog = Catalog(path)
    # Native Table instances capture their storage during construction. Rebind
    # the two empty tables through TinyDB's public storage constructor as well.
    catalog._db.close()
    catalog._db = TinyDB(str(path), storage=CachingMiddleware(JSONStorage), indent=2)
    catalog.projects = catalog._db.table("projects")
    catalog.gems = catalog._db.table("gems")
    try:
        yield catalog
    finally:
        catalog._db.close()


class CheckedGemFinder(GemFinder):
    """Observe native scan completion because Harvester catches scan failures."""
    def __init__(self):
        super().__init__()
        self.completed = False
        self.gems = []

    def scan(self, *args, **kwargs):
        self.completed = False
        self.gems = super().scan(*args, **kwargs)
        self.completed = True
        return self.gems


def verify_gem_harvest(finder, result, catalog, source_id):
    """Verify the one native scan was stored completely, without scanning twice."""
    expected = {(str(gem["file_path"]), source_id) for gem in finder.gems}
    stored = catalog.list_gems(source_repo=source_id, limit=len(expected) + 1)
    actual = {(str(gem["file_path"]), gem["source_repo"]) for gem in stored}
    if (not finder.completed or result["gems_found"] != len(finder.gems)
            or len(stored) != len(finder.gems) or actual != expected):
        raise RuntimeError("Incomplete gem harvest")


def refresh(sources, cache=DEFAULT, merge=False):
    start = time.perf_counter()
    progress("starting — checking selected sources")
    with writer(cache):
        old = (read(cache / "current.json") if (cache / "current.json").exists() else {"sources": []})
        if sources is None:
            sources = old["sources"]
        sources = [
            {
                k: v
                for k, v in s.items()
                if k not in ("artifact", "signature", "extractor", "coverage")
            }
            for s in sources
        ]
        if not sources:
            raise ValueError("No sources registered; run navcom sources harvest ROOT")
        if len({s["id"] for s in sources}) != len(sources):
            raise ValueError("Duplicate source identity")
        extractor = extractor_signature()
        receipts = []
        changed = 0
        for i, s in enumerate(sources, 1):
            progress(f"[{i}/{len(sources)}] checking {s['label']}")
            if cache.resolve().is_relative_to(Path(s["root"]).resolve()):
                raise ValueError("Keep --cache outside the harvested source root")
            payload, signature, coverage = source_bytes(s)
            key = digest(json.dumps([s, signature, extractor], sort_keys=True).encode())
            artifact = cache / "artifacts" / key
            if not (artifact / "receipt.json").exists():
                progress(
                    f"[{i}/{len(sources)}] analyzing {s['label']} — {len(payload)} files"
                )
                stage = Path(tempfile.mkdtemp(prefix=".work-", dir=cache))
                try:
                    snapshot = stage / "source"
                    snapshot.mkdir()
                    for rel, data in payload.items():
                        p = snapshot / rel
                        p.parent.mkdir(parents=True, exist_ok=True)
                        p.write_bytes(data)
                    with staged_catalog(stage / "catalog.json") as catalog:
                        finder = CheckedGemFinder()
                        h = Harvester(
                            catalog,
                            None,
                            ProjectAnalyzer(dispatcher=False),
                            finder,
                            llm_delay=0,
                        )
                        result = h._analyze_and_store(snapshot, s["id"], "navcom-local")
                        verify_gem_harvest(finder, result, catalog, s["id"])
                    write(stage / "structure.json", source_structure(
                        snapshot, s.get("discovery_coverage", {}).get("application_roots")))
                    data = read(stage / "catalog.json")
                    # Snapshot moves once at publication; retain valid immutable artifact paths.
                    raw = json.dumps(data).replace(str(stage), str(artifact))
                    (stage / "catalog.json").write_text(raw)
                    if source_bytes(s)[1] != signature:
                        raise RuntimeError("Source changed during harvest; retry")
                    write(
                        stage / "receipt.json",
                        dict(
                            source=s,
                            signature=signature,
                            extractor=extractor,
                            coverage=coverage,
                            gems=result["gems_found"],
                        ),
                    )
                    artifact.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(stage, artifact)
                    changed += 1
                finally:
                    if stage.exists():
                        shutil.rmtree(stage)
            else:
                progress(f"[{i}/{len(sources)}] cached {s['label']}")
            receipts.append(
                dict(
                    s,
                    artifact=str(artifact),
                    signature=signature,
                    extractor=extractor,
                    coverage=coverage,
                )
            )
        retained = 0
        if merge:
            # A bounded intake page checks only its selected live sources.
            # Other published immutable receipts remain searchable even when
            # their original drive is offline; explicit refresh(None) checks all.
            updates = {receipt["id"]: receipt for receipt in receipts}
            retained = sum(source["id"] not in updates for source in old["sources"])
            receipts = [updates.pop(source["id"], source) for source in old["sources"]] + list(updates.values())
        identical = old["sources"] == receipts
        if not identical:
            gen = Path(tempfile.mkdtemp(prefix="generation-", dir=cache))
            with staged_catalog(gen / "catalog.json") as catalog:
                for s in receipts:
                    raw = read(Path(s["artifact"]) / "catalog.json")
                    for p in raw.get("projects", {}).values():
                        catalog.add_project(
                            p["name"],
                            p["path"],
                            summary=p["summary"],
                            tech_stack=p["tech_stack"],
                            tags=p["tags"],
                            galaxy=p.get("galaxy", ""),
                        )
                    for g in raw.get("gems", {}).values():
                        rel = str(
                            Path(g["file_path"]).relative_to(Path(s["artifact"]) / "source")
                        )
                        # The search implementation keys by gem name; make it unique across sources/files.
                        name = s["label"] + ":" + s["id"] + ":" + rel
                        catalog.add_gem(
                            name,
                            g["file_path"],
                            s["id"],
                            description=g["description"],
                            importance_score=g["importance_score"],
                            signals=g["signals"],
                            language=g["language"],
                            mtime=g.get("mtime", 0),
                        )
            write(
                cache / "current.json",
                dict(
                    sources=receipts,
                    catalog=str(gen / "catalog.json"),
                    published=time.time(),
                ),
            )
        result = dict(
            analyzed_sources=changed,
            cached_sources=len(sources) - changed,
            retained_sources=retained,
            published=not identical,
            seconds=round(time.perf_counter() - start, 3),
            sources=len(receipts),
        )
        progress("complete — " + str(changed) + " sources analyzed")
        return result


def source_applications(snapshot, files, application_roots=None):
    """Run native entry/build detection on bounded immutable manifest views.

    A manifest is an inspection address, not a product declaration. Only native
    runnable entry evidence qualifies a candidate; build/test helpers stay out.
    Views omit sibling apps and executable code, and no command is executed.
    """
    from starforge.entry_points import detect_entry_points
    from starforge.build_systems import detect_build_systems
    from starforge.dep_conflicts import extract_versioned_deps
    names = {"package.json", "pyproject.toml", "Cargo.toml", "composer.json"}
    manifests = sorted(path for path in files if path.name in names)
    roots = sorted({path.parent for path in manifests})
    candidates, inspected, omitted, dependencies = [], [], [], {}
    declared_roots = {str(Path(value)) for value in application_roots or []}
    for root in roots[:64]:
        relative = str(root.relative_to(snapshot))
        metadata = [path for path in manifests if path.parent == root]
        if any(path.stat().st_size > 1024 * 1024 for path in metadata):
            omitted.append(dict(root=relative, reason="manifest byte limit"))
            continue
        with tempfile.TemporaryDirectory(prefix="navcom-native-app-") as temporary:
            view = Path(temporary)
            for path in metadata:
                (view / path.name).write_bytes(path.read_bytes())
            entries = detect_entry_points(view)
            builds = detect_build_systems(view)
            try:
                dependencies[root] = [row for row in extract_versioned_deps(view)
                                      if row.get("source_file") == "package.json"]
            except (AttributeError, TypeError, ValueError):
                dependencies[root] = []
                omitted.append(dict(root=relative, reason="invalid native dependency metadata"))
        runnable = [entry for entry in entries if entry.get("type") in {"npm-bin", "console-script"}
                    or (entry.get("type") == "npm-script" and entry.get("name") in
                        {"npm run start", "npm run dev", "npm run serve"})]
        inspected.append(dict(root=relative, manifests=[path.name for path in metadata],
                              runnable=bool(runnable)))
        if not runnable:
            continue
        # Metadata identity is read directly because native detection describes
        # entry points rather than package names. Never use command detail text.
        identity = {}
        try:
            if (root / "package.json") in metadata:
                identity = read(root / "package.json")
            elif (root / "pyproject.toml") in metadata:
                import tomllib
                document = tomllib.loads((root / "pyproject.toml").read_text())
                identity = document.get("project") or document.get("tool", {}).get("poetry", {})
        except (OSError, ValueError, ImportError, AttributeError):
            pass
        if not isinstance(identity, dict):
            identity = {}
        def scalar(value, fallback, limit):
            return value[:limit] if isinstance(value, str) and value.strip() else fallback
        native_entries = [{key: str(entry.get(key, ""))[:256] for key in ("name", "type", "file")}
                          for entry in runnable[:32]]
        candidates.append(dict(root=relative, manifest=str(root.relative_to(snapshot) / runnable[0]["file"]),
                               name=scalar(identity.get("name"), root.name, 160),
                               description=scalar(identity.get("description"), "", 640),
                               entry_points=native_entries, build_systems=builds[:32], status="candidate",
                               package_name=identity.get("name") if isinstance(identity.get("name"), str) else "",
                               local_declaration=("workspace_member" if relative in declared_roots and relative != "."
                                                  else "private_package" if identity.get("private") is True else "")))
    for candidate in candidates:
        candidate["dependency_evidence"] = []
        package_name = candidate.pop("package_name")
        if Path(candidate["manifest"]).name != "package.json" or not package_name:
            continue
        root = snapshot / candidate["root"]
        ancestors = sorted((parent for parent in dependencies if parent != root and root.is_relative_to(parent)),
                           key=lambda parent: len(parent.parts), reverse=True)
        for parent in ancestors:
            rows = [row for row in dependencies[parent] if row.get("package") == package_name.lower()]
            if not rows:
                continue
            # Native extraction owns package identity. Local dependency protocols
            # are explicit declarations, not a guess from directory names. Never
            # publish raw specs: URL credentials can occur in dependency values.
            specs = [row.get("version_spec") for row in rows]
            if (all(isinstance(spec, str) and spec.strip() for spec in specs)
                    and not any(spec.strip().lower().startswith(("file:", "link:", "workspace:", "portal:", ".", "/", "~/"))
                                for spec in specs)):
                candidate["dependency_evidence"] = [dict(
                    type="declared_dependency", engine="starforge.dep_conflicts.extract_versioned_deps",
                    package=package_name[:160], declaring_manifest=str(parent.relative_to(snapshot) / "package.json"),
                    candidate_manifest=candidate["manifest"], relationship="nonlocal_package_dependency",
                    meaning="An ancestor manifest declares this package as a dependency; this alone does not establish a separate product.")]
            break  # The nearest declaring manifest supplies the relationship.
    omitted.extend(dict(root=str(root.relative_to(snapshot)), reason="manifest-root limit") for root in roots[64:])
    return candidates, dict(engine="starforge.entry_points.detect_entry_points + starforge.build_systems.detect_build_systems",
                            inspected=inspected, omitted=omitted, max_roots=64,
                            max_manifest_bytes=1024 * 1024, complete=not omitted,
                            dependency_engine="starforge.dep_conflicts.extract_versioned_deps",
                            meaning="Manifest-only native entry and dependency evidence; runtime health and product ownership are unverified.")


def source_structure(snapshot, application_roots=None):
    """Cache upstream token groups; these are evidence, not product boundaries."""
    from starforge.similarity import find_token_groups
    code_ext={'.py','.js','.ts','.tsx','.jsx','.go','.rs','.rb','.php','.java','.cs','.swift','.kt'}
    snapshot_files=sorted(p for p in snapshot.rglob('*') if p.is_file())
    applications, application_coverage = source_applications(snapshot, snapshot_files, application_roots)
    files=[p for p in snapshot_files if p.suffix in code_ext]
    roots={Path('.')}
    for value in application_roots or []:
        root=Path(value)
        if not root.is_absolute() and '..' not in root.parts and (snapshot/root).is_dir():
            roots.add(root)
    roots.update(Path(candidate['root']) for candidate in applications)
    partitions={str(root):[] for root in sorted(roots)}
    for path in files:
        relative=path.relative_to(snapshot)
        owner=max((root for root in roots if relative.is_relative_to(root)),key=lambda root:len(root.parts))
        partitions[str(owner)].append(path)
    # Keep explicit/large scopes fair as well as automatically selected ones.
    from collections import deque
    streams=deque(iter(paths) for paths in partitions.values())
    bounded=[]
    while streams and len(bounded)<1500:
        stream=streams.popleft()
        path=next(stream,None)
        if path is not None:
            if path.stat().st_size<=250000:bounded.append(path)
            streams.append(stream)
    selected=set(bounded)
    oversized=[path for path in files if path.stat().st_size>250000]
    oversized_set=set(oversized)
    omitted_by_count=[path for path in files if path not in selected and path not in oversized_set]
    groups=[];scopes=[]
    for root,paths in partitions.items():
        members=[path for path in paths if path in selected]
        native=find_token_groups(members) if len(members)>1 else []
        for group in native:
            group['paths']=[str(Path(path).relative_to(snapshot)) for path in group['paths']]
            group['application_root']=root
        groups.extend(native)
        scopes.append(dict(root=root,eligible=len(paths),analyzed=len(members),groups=len(native)))
    return dict(schema_version=1,engine='starforge.similarity.find_token_groups',
                application_candidates=applications, application_coverage=application_coverage,
                token_groups=groups,coverage=dict(eligible=len(files),analyzed=len(bounded),
                limit=1500,max_file_bytes=250000,
                oversized_files=len(oversized),
                oversized_paths=[str(path.relative_to(snapshot)) for path in oversized[:100]],
                oversized_paths_truncated=len(oversized)>100,
                file_limit_omissions=len(omitted_by_count),
                complete=len(files)==len(bounded),application_scopes=scopes),
                meaning='Shared code tokens suggest conceptual districts; they do not establish ownership.')


def selected_paths(source, paths):
    snapshot=Path(source['artifact'])/'source'
    for value in paths:
        path=Path(value)
        if path.is_absolute() or '..' in path.parts:
            raise ValueError('--path must stay within the harvested source')
    return {str(p.relative_to(snapshot)) for p in snapshot.rglob('*') if p.is_file()
            and (not paths or any(p.relative_to(snapshot)==Path(value) or
                                 p.relative_to(snapshot).is_relative_to(Path(value)) for value in paths))}


def source_view(view, source, paths):
    link=view/'harvest-cache'/'local'/source['id']
    link.parent.mkdir(parents=True,exist_ok=True)
    snapshot=Path(source['artifact'])/'source'
    if not paths:
        link.symlink_to(snapshot,target_is_directory=True)
    else:
        link.mkdir()
        for rel in sorted(selected_paths(source,paths)):
            dest=link/rel;dest.parent.mkdir(parents=True,exist_ok=True)
            dest.symlink_to(snapshot/rel)


class ScopedCatalog:
    def __init__(self, catalog, allowed, allowed_files=None):
        self.catalog = catalog
        self.allowed = allowed
        self.allowed_files = allowed_files

    def list_gems(self, limit=50000):
        return [
            g
            for g in self.catalog.list_gems(limit=50000)
            if g["source_repo"] in self.allowed and (self.allowed_files is None or g["file_path"] in self.allowed_files)
        ][:limit]

    def list_projects(self, limit=50000):
        return [
            p
            for p in self.catalog.list_projects(limit=50000)
            if p["name"] in self.allowed
        ][:limit]

    def search_gems(self, q, limit=30):
        return [
            g
            for g in self.catalog.search_gems(q, limit=50000)
            if g["source_repo"] in self.allowed and (self.allowed_files is None or g["file_path"] in self.allowed_files)
        ][:limit]

    def search_projects(self, q, limit=20):
        return [
            p
            for p in self.catalog.search_projects(q, limit=50000)
            if p["name"] in self.allowed
        ][:limit]


def search(query, cache=DEFAULT, within=None, limit=8, paths=None, *, state=None):
    paths=paths or []
    start = time.perf_counter()
    state = state if state is not None else read(cache / "current.json")
    sources = {s["id"]: s for s in state["sources"]}
    if within:
        matches = [
            s for s in sources.values() if within in (s["id"], s["label"], s["root"])
        ]
        if len(matches) != 1:
            raise ValueError("Scope must identify exactly one source")
        allowed = {matches[0]["id"]}
    else:
        allowed = set(sources)
    allowed_files={str(Path(sources[sid]["artifact"])/"source"/rel) for sid in allowed for rel in selected_paths(sources[sid],paths)} if paths else None
    catalog = ScopedCatalog(Catalog(Path(state["catalog"])), allowed, allowed_files)
    with tempfile.TemporaryDirectory(prefix=".concept-", dir=cache) as tmp:
        view = Path(tmp)
        for source_id in sorted(allowed):
            source_view(view,sources[source_id],paths)
        hits = concept_search(query, catalog, view, limit=limit)
    for hit in hits:
        s = sources[hit["repo"]]
        rel = Path(hit["file_path"]).relative_to(Path(s["artifact"]) / "source")
        hit.update(
            source_path=str(Path(s["root"]) / rel),
            relative_path=str(rel),
            source=s["label"],
            source_id=s["id"],
            conversation_collection=s.get("conversation_collection"),
            conversation_command=[
                "navcom",
                "atlas",
                "search",
                query,
                "--within",
                s["conversation_collection"],
            ]
            if s.get("conversation_collection")
            else None,
        )
    return dict(
        query=query,
        within=within,
        hits=hits,
        seconds=round(time.perf_counter() - start, 3),
        published=state["published"],
        freshness="last complete explicit harvest; search does not rescan sources",
        harvest_invocations=0,
    )


def _pin_source_refs(result, state):
    """Attach reader addresses from the exact registry used for this search.

    Do this on cached returns too; a query memo cannot nominate a different
    source or artifact. No live file reads or fresh registry reads are needed.
    """
    sources = {source["id"]: source for source in state["sources"]}
    if len(sources) != len(state["sources"]):
        raise ValueError("Duplicate published source identity")
    for field in ("concept_hits", "text_hits"):
        for hit in result.get(field, []):
            source = sources.get(hit.get("source_id"))
            if source is None:
                raise ValueError("Search hit has no exact published source identity")
            relative = hit.get("relative_path")
            if (not isinstance(relative, str) or not relative or "\\" in relative
                    or "\x00" in relative or Path(relative).is_absolute()
                    or ".." in Path(relative).parts or str(Path(relative)) == "."):
                raise ValueError("Search hit path is outside its source snapshot")
            relative = str(Path(relative))
            artifact = Path(source["artifact"])
            key = artifact.name
            if len(key) != 64 or any(char not in "0123456789abcdef" for char in key):
                raise ValueError("Search hit has an invalid published artifact key")
            if hit.get("repo", source["id"]) != source["id"]:
                raise ValueError("Search hit source identity does not match its native result")
            expected = artifact / "source" / relative
            if hit.get("file_path") and Path(hit["file_path"]) != expected:
                raise ValueError("Search hit path does not match its native artifact")
            if hit.get("source_path") and Path(hit["source_path"]) != Path(source["root"]) / relative:
                raise ValueError("Search hit path does not match its published source")
            line = hit.get("line", 1)
            if type(line) is not int or line < 1:
                raise ValueError("Search hit has an invalid source line")
            reference = dict(source_id=source["id"], relative_path=relative,
                             line=line, snapshot=key, published=state["published"])
            if hit.get("source_ref") is not None and hit["source_ref"] != reference:
                raise ValueError("Search hit reference does not match its published snapshot")
            hit["source_ref"] = reference
    return result


def _query_source_identity(sources):
    """Keep native retrieval tied to its selected immutable inputs, not the sweep.

    The aggregate catalog is rebuilt when any source publishes. Its selected
    rows still come from these immutable source catalogs; unrelated rows never
    enter ScopedCatalog. Display paths and collection routing are inputs too.
    """
    result = []
    for source in sorted(sources, key=lambda item: item["id"]):
        artifact = Path(source["artifact"])
        if not (artifact / "source").is_dir() or not (artifact / "catalog.json").is_file():
            raise ValueError("Published source artifact is unavailable: " + source["id"])
        result.append({key: source.get(key) for key in (
            "id", "root", "label", "artifact", "signature", "extractor",
            "include", "conversation_collection")})
    return result


def _cached_query_result(result, state):
    """Validate the original memo address before rebasing its publication.

    Only publication time may differ. Identity, literal path, line, artifact and
    original publication must agree first, including on an unchanged snapshot.
    """
    _pin_source_refs(result, dict(state, published=result["published"]))
    for field in ("concept_hits", "text_hits"):
        for hit in result.get(field, []):
            hit["source_ref"]["published"] = state["published"]
    result["published"] = state["published"]
    result["query_cache_hit"] = True
    return _pin_source_refs(result, state)


def combined_search(request, cache, *, state=None, extractor=None):
    import re
    from rich.table import Table
    import typer
    from starforge.cli_reporting import register

    state = state if state is not None else read(cache / "current.json")
    sources = state["sources"]
    within = request.get("within")
    if within:
        sources = [s for s in sources if within in (s["id"], s["label"], s["root"])]
        if len(sources) != 1:
            raise ValueError(
                "Scope must identify exactly one source ID, label, or absolute root"
            )
    paths=request.get("paths") or []
    if paths and not within:raise ValueError("--path requires --within")
    for source in sources:selected_paths(source,paths) if paths else None
    query = request["query"]
    mode = request.get("mode", "both")
    limit = request.get("limit", 20)
    text_mode = request.get("text_mode", "literal")
    if text_mode not in ("literal", "question_terms"):
        raise ValueError("Unknown native text retrieval mode")
    if text_mode == "question_terms" and request.get("regex"):
        raise ValueError("Question terms cannot be combined with an explicit regex")
    # Reuse Starforge's own concept-query decomposition. Punctuation normalization
    # is syntax handling only; no client vocabulary, synonyms or model are added.
    all_terms = list(dict.fromkeys(_extract_keywords(" ".join(re.findall(r"\w+(?:[-_]\w+)*", query))))) if text_mode == "question_terms" else []
    text_terms = all_terms[:16]
    # Native question keywords are words, not arbitrary substrings: ``work``
    # must not consume the result budget with ``workers`` or ``network``.
    # code-search already supports regex; literal/explicit-regex queries keep
    # their existing contracts and native result ordering remains unchanged.
    pattern = (r"\b(?:" + "|".join(re.escape(term) for term in text_terms) + r")\b"
               if text_terms else query if request.get("regex") else re.escape(query))
    if mode != "concept":
        re.compile(pattern, re.IGNORECASE)
    identity = _query_source_identity(sources)
    selected_state = dict(state, sources=sources)
    key = digest(
        # An optional caller namespace cannot bypass retrieval/DTO invalidation.
        json.dumps(["selected-source-query-v1", identity, request, query_signature(), extractor],
                   sort_keys=True).encode()
    )
    memo = cache / "queries" / (key + ".json")
    if memo.exists():
        return _cached_query_result(read(memo), selected_state)
    result = dict(
        schema_version=1,
        query=query,
        mode=mode,
        text_mode=text_mode,
        text_terms=text_terms,
        text_terms_truncated=len(all_terms)>len(text_terms),
        paths=paths,
        published=state["published"],
        freshness="Last complete harvest; run navcom sources refresh to check source edits.",
        concept_hits=[],
        text_hits=[],
        harvest_invocations=0,
        query_cache_hit=False,
        limit_per_path=limit,
        potentially_truncated=False,
    )
    if mode != "text":
        result["concept_hits"] = search(query, cache, within, limit, paths, state=state)["hits"]
    if mode != "concept":

        class Capture:
            def __init__(self):
                self.rows = []

            def print(self, obj, *args, **kwargs):
                if isinstance(obj, Table):
                    self.rows.extend(
                        list(row) for row in zip(*(c._cells for c in obj.columns))
                    )

        capture = Capture()
        app = typer.Typer()
        register(app, capture)
        native_search = next(
            c.callback for c in app.registered_commands if c.name == "code-search"
        )
        # A private view prevents substring repo filters and cwd precedence from leaking scope.
        with tempfile.TemporaryDirectory(prefix=".search-", dir=cache) as tmp:
            view = Path(tmp)
            for source in sources:
                source_view(view,source,paths)
            previous = Path.cwd()
            try:
                os.chdir(view)
                native_search(
                    pattern=pattern,
                    repo="",
                    ext=request.get("ext") or "",
                    limit=limit,
                    context=0,
                )
            finally:
                os.chdir(previous)
        by_id = {s["id"]: s for s in sources}
        for repo, filename, line, match in capture.rows:
            source = by_id[repo]
            relative = Path(filename).relative_to(Path("local") / repo)
            result["text_hits"].append(
                dict(
                    source_id=repo,
                    source=source["label"],
                    source_path=str(Path(source["root"]) / relative),
                    relative_path=str(relative),
                    line=int(line),
                    match=match,
                    conversation_command=[
                        "navcom",
                        "atlas",
                        "search",
                        query,
                        "--within",
                        source["conversation_collection"],
                    ]
                    if source.get("conversation_collection")
                    else None,
                )
            )
    result["potentially_truncated"] = result["text_terms_truncated"] or any(
        len(result[k]) >= limit for k in ("concept_hits", "text_hits")
    )
    result = _pin_source_refs(result, selected_state)
    write(memo, result)
    return result


def batch_search(request, cache):
    """Search each eligible saved scope once in one runtime and one generation.

    Each scope delegates to the same cached Starforge search used by the source
    CLI. The time budget is checked between scopes; a single native call may
    finish after it. The caller also bounds the worker process itself.
    """
    state = read(cache / "current.json")
    extractor = query_signature()
    scopes = request.get("scopes", [])
    if not isinstance(scopes, list):
        raise ValueError("Search scopes must be a list")
    identities = [scope["source_id"] for scope in scopes]
    if len(identities) != len(set(identities)):
        raise ValueError("Duplicate search scope")
    seconds = min(30.0, max(0.01, float(request.get("time_budget_seconds", 20))))
    started = time.monotonic()
    results, errors, attempted = [], [], []
    for scope in scopes:
        if time.monotonic() - started >= seconds:
            break
        sid = scope["source_id"]
        attempted.append(sid)
        individual = dict(action="search", cache=str(cache), query=request["query"],
                          within=sid, paths=scope.get("paths") or [],
                          mode=request.get("mode", "both"), limit=request.get("limit", 12))
        if request.get("text_mode"):individual["text_mode"]=request["text_mode"]
        try:
            data = combined_search(individual, cache, state=state, extractor=extractor)
            results.append(dict(source_id=sid, **data))
        except (OSError, ValueError, RuntimeError) as exc:
            errors.append({"source_id": sid, "error": str(exc)})
    unsearched = identities[len(attempted):]
    return dict(sources=results, errors=errors, coverage=dict(
        source_scopes=len(scopes), attempted_source_scopes=len(attempted),
        searched_source_scopes=len(results), unsearched_source_ids=unsearched,
        query_cache_hits=sum(bool(r.get("query_cache_hit")) for r in results),
        published=state["published"], time_budget_seconds=seconds,
        elapsed_seconds=round(time.monotonic() - started, 3),
        complete=not errors and not unsearched and not any(r.get("potentially_truncated") for r in results),
    ))


def main():
    # Stdout is a strict JSON protocol. Third-party console output belongs on stderr.
    request = json.load(sys.stdin)
    cache = Path(request["cache"]).expanduser().resolve()
    os.umask(0o077)
    try:
        with contextlib.redirect_stdout(sys.stderr):
            if request["action"] == "harvest":
                result = refresh(request["sources"], cache, merge=True)
            elif request["action"] == "refresh":
                result = refresh(None, cache)
            else:
                if not (cache / "current.json").exists():
                    raise ValueError(
                        "No harvested sources; run navcom sources harvest ROOT first"
                    )
                result = batch_search(request, cache) if request["action"] == "batch-search" else combined_search(request, cache)
        print(
            json.dumps(
                dict(
                    schema_version=1,
                    **{k: v for k, v in result.items() if k != "schema_version"},
                )
            )
        )
    except Exception as exc:
        print("navcom sources: " + str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
