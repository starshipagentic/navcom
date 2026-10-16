"""Cached, evidence-backed places for the Atlas CLI and browser.

Refresh inspects bounded repository metadata, indexed working directories and
published Starforge artifacts. Navigation reads one immutable JSON publication;
it never scans source, runs Git, calls a model, or infers product ownership from
words in conversations. Suggested places are deliberately distinguishable from
owner declarations. Physical copies and provider ancestry are separate concepts.
"""

from collections import defaultdict
from contextlib import contextmanager
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
from urllib.parse import urlsplit


SCHEMA_VERSION = 1
GALAXY = "galaxy:owner"
INDEPENDENT = "system:independent"
KINDS = {"galaxies": "galaxy", "systems": "system", "solar-systems": "system",
         "planets": "planet", "products": "planet", "moons": "moon",
         "experiments": "moon", "districts": "district", "cities": "district",
         "stars": "star", "bases": "starbase", "starbases": "starbase", "ships": "ship"}
EXPERIMENT = re.compile(r"^(?:exp\d+(?:[-_].*)?|experiment(?:[-_].+)?)$", re.I)
LAB_DIRS = {"lab", "labs", "experiments"}
MAX_JSON = 32 * 1024 * 1024
STAR_BATCH_ROOTS = 10
STAR_DISCOVERY_SECONDS = 30


def _clean_clue(api, text, limit=180):
    """Display authored text, excluding transport and injected context wrappers."""
    text = str(text or "")[:6000]
    # Realtime envelopes contain a current request plus a duplicate transcript.
    request = re.search(r"<input>(.*?)</input>", text, re.S | re.I)
    if "<realtime_delegation" in text and request:
        text = request.group(1)
    cleaner = getattr(api, "_strip_conversation_artifacts", None)
    if cleaner:
        text = cleaner(text)
    tags = ("app-context", "in-app-context", "environment_context", "environment-context",
            "system-reminder", "tool_result", "tool-response", "transcript_delta", "turn_aborted")
    for tag in tags:
        text = re.sub(r"<" + tag + r"\b[^>]*>.*?(?:</" + tag + r">|$)", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"!?\[([^]\n]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"`|\*\*|__|^#+\s*", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    if re.match(r"^(?:\[(?:Tool|Read|Bash|Write|Edit):|[\[{]\s*\"(?:tool|command|function))", text, re.I):
        return ""
    one_line = getattr(api, "_one_line", None)
    return one_line(text, limit) if one_line else text[:limit]


def _conversation_clue(api, conn, key, title):
    cleaned = _clean_clue(api, title)
    if not cleaned or cleaned.lower() in {"untitled conversation", "unknown conversation"}:
        # Read a bounded indexed excerpt, never open session files or run a model.
        try:
            rows = conn.execute("SELECT substr(f.text,1,3000) FROM turn_loc l JOIN session_fts f ON f.rowid=l.rid WHERE l.file=? AND f.role='user' ORDER BY l.msg_index LIMIT 8", (key,))
            cleaned = next((text for row in rows if (text := _clean_clue(api, row[0]))), "")
        except Exception as exc:
            # Minimal/source-only indexes need not contain transcript tables.
            import sqlite3
            if not isinstance(exc, sqlite3.Error):
                raise
    if cleaned and hasattr(api, "_one_line"):
        from navcom_atlas import Atlas
        cleaned = Atlas(api).evidence_label(cleaned)
    return cleaned


def _source_clues(api, artifact, relative, root_source=False, display_name=""):
    """Use already harvested documents and native analysis; no live code scan."""
    snapshot = artifact / "source"
    folder = snapshot / relative
    clues = []
    if root_source:
        catalog = _read(artifact / "catalog.json", {}) or {}
        projects = catalog.get("projects", {})
        for record in (projects.values() if isinstance(projects, dict) else projects):
            if not isinstance(record, dict):
                continue
            summary = _clean_clue(api, record.get("summary"), 320)
            if display_name and record.get("name"):
                summary = summary.replace(str(record["name"]), display_name)
            if summary:
                clues.append(dict(text=summary, basis="starforge_project_analysis", artifact=str(artifact / "catalog.json")))
    for filename in ("README.md", "readme.md", "Readme.md"):
        path = folder / filename
        try:
            if path.is_symlink() or not path.is_file():
                continue
            with path.open(encoding="utf-8", errors="replace") as handle:
                text = handle.read(6000)
            # Keep authored prose and headings, not badges, fences or frontmatter.
            text = re.sub(r"\A---\s*\n.*?\n---\s*\n", "", text, flags=re.S)
            text = re.sub(r"```.*?(?:```|$)", "", text, flags=re.S)
            lines = [line.strip() for line in text.splitlines() if line.strip() and not line.lstrip().startswith(("![", "[![", "<!--", "|"))]
            clue = _clean_clue(api, " ".join(lines[:6]), 320)
            if clue:
                clues.append(dict(text=clue, basis="harvested_readme", path=str(path)))
            break
        except OSError:
            continue
    return clues


def _description_priority(clue):
    return {"owner_declaration": 4, "harvested_readme": 3,
            "package_manifest": 2, "workspace_application": 2, "native_application": 2,
            "starforge_project_analysis": 1}.get(clue.get("basis"), 0)


def _prefer_description(node, clue):
    """Select existing authored evidence; this does not infer product identity."""
    if not clue.get("text"):
        return
    clues = node.setdefault("clues", [])
    current = max((_description_priority(saved) for saved in clues
                   if saved.get("text") == node.get("description")), default=0)
    if not node.get("description") or _description_priority(clue) > current:
        node["description"] = clue["text"]
    if clue not in clues:
        clues.append(clue)
    # Contents previews use the first exact prose match for provenance. When
    # two sources repeat the same words, retain the preferred attribution too.
    matches = [saved for saved in clues if saved.get("text") == node.get("description")]
    if matches:
        preferred = max(matches, key=_description_priority)
        clues.remove(preferred)
        clues.insert(0, preferred)


def _district_label(words, paths):
    """Format native grouping evidence; do not regroup or infer a new subject."""
    generic = {"exist_ok", "prepare", "mkdir", "makedirs", "encoding", "utf", "utf8", "path", "paths",
               "file", "files", "read", "write", "open", "load", "save", "main", "init", "test", "tests",
               "true", "false", "none", "self", "return", "str", "dict", "list", "args", "kwargs",
               "spec", "index", "config"}

    def stem(path):
        name = Path(path).stem
        name = re.sub(r"\.(?:test|spec)$", "", name)
        return re.sub(r"^test_", "", name)

    def readable(name):
        name = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name)
        return re.sub(r"\s+", " ", re.sub(r"[_\W]+", " ", name, flags=re.U)).strip()[:60]

    names = [stem(path) for path in paths]
    filename_words = {part.casefold() for name in names for part in readable(name).split()}
    # The native tokenizer also returns import paths, punctuation fragments and
    # private helpers. Keep those as searchable evidence, not display headings.
    useful = list(dict.fromkeys(word for word in words if 2 <= len(word) <= 48
        and re.fullmatch(r"[^\W\d_][\w-]*", word, flags=re.U)
        and word.casefold() not in generic))
    # Native words present in filenames make an especially checkable clue.
    anchored = [word for word in useful if word.casefold() in filename_words]
    ordered = list(anchored)
    ordered += [word for word in useful if word not in ordered]

    if names and len(set(names)) == 1:
        parents = [Path(path).parent.parts for path in paths]
        common = []
        for pieces in zip(*(reversed(parent) for parent in parents)):
            if len(set(pieces)) != 1:
                break
            common.append(pieces[0])
        structural = {"src", "lib", "source", "test", "tests", "scripts"}
        meaningful = [part for part in reversed(common[:3]) if part.casefold() not in structural]
        if meaningful:
            # Repeated modules across versions get their actual shared terminal
            # path, not alphabetically early implementation tokens.
            suffix = [readable(part)[:30] for part in meaningful[-2:]] + [readable(names[0])]
            return " / ".join(filter(None, suffix)), "common_grouped_path", [names[0]]
        # A shared basename alone cannot distinguish unrelated folders.
        labels = list(dict.fromkeys(" / ".join(filter(None, [*[readable(part) for part in Path(path).parent.parts[-len(common)-1:]], readable(name)]))
                                   for path, name in zip(paths, names)))
        count = f" ({len(paths)} files)"
        return " · ".join(labels[:3])[:160-len(count)] + count, "grouped_file_paths", [names[0]]
    if anchored:
        label_words = [readable(word) for word in ordered[:3]]
        basis = "native_shared_tokens"
    else:
        label_words = list(dict.fromkeys(readable(name) for name in names if name.casefold() not in generic and readable(name)))[:3]
        basis = "grouped_filenames"
        if not label_words:
            label_words = list(dict.fromkeys(readable(word) for word in useful))[:3]
            basis = "native_shared_tokens" if label_words else "grouped_file_count"
    label = " · ".join(label_words) or f"{len(paths)} grouped files"
    if basis == "grouped_filenames" and len(set(names)) > 3:
        count = f" ({len(paths)} files)"
        label = label[:160-len(count)] + count
    query = ordered[:5] if anchored else [name for name in names if name.casefold() not in generic][:3]
    return label[:160], basis, list(dict.fromkeys(query))


def _id(kind, identity):
    return kind + ":" + hashlib.sha256(identity.encode()).hexdigest()[:20]


def _read(path, default=None, max_bytes=MAX_JSON):
    try:
        # Read one opened publication and enforce the bound on actual bytes,
        # even if an atomic replacement happens while the path is being read.
        with Path(path).open("rb") as stream:
            raw = stream.read(max_bytes + 1)
        if len(raw) > max_bytes:
            raise ValueError("Metadata exceeds size limit: " + str(path))
        return json.loads(raw)
    except FileNotFoundError:
        return default


def _atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, ensure_ascii=False, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


@contextmanager
def _writer(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(path.suffix + ".lock").open("a") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Another spatial refresh is running; cached navigation is available.") from None
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def sanitize_origin(value):
    """Canonical remote identity with credentials, query strings and fragments removed."""
    value = value.strip()
    if not value:
        return ""
    if "://" in value:
        parsed = urlsplit(value)
        host = (parsed.hostname or "").lower()
        path = parsed.path
        if parsed.scheme == "file":
            host = "file:"
        elif not host:
            return ""
        # Schemes/users do not change a remote's repository identity.
        origin = host + "/" + path.lstrip("/")
    elif re.match(r"^(?:[^/@:]+@)?[^/:]+:.+", value):
        host, path = value.split(":", 1)
        origin = host.rsplit("@", 1)[-1].lower() + "/" + path.lstrip("/")
    elif value.startswith(("/", ".")):
        origin = "file:" + str(Path(value).expanduser().resolve())
    else:
        return ""
    origin = origin.split("?", 1)[0].split("#", 1)[0].rstrip("/")
    return origin[:-4] if origin.endswith(".git") else origin


def _git(path, *args):
    try:
        result = subprocess.run(["git", "-C", str(path), *args], capture_output=True,
                                text=True, timeout=2,
                                env=dict(os.environ, GIT_OPTIONAL_LOCKS="0", GIT_TERMINAL_PROMPT="0"))
        return result.stdout.strip() if result.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _repository(path):
    """Only inspect metadata. No Git fetch, checkout, or recursive source traversal."""
    top = _git(path, "rev-parse", "--show-toplevel") if path.is_dir() else ""
    managed = None
    if not top and not path.exists():
        # A removed tool worktree can still be placed without turning arbitrary
        # missing subdirectories into products. This is a disclosed suggestion
        # unless Git's live worktree registry retains that exact location.
        parts = path.parts
        for i, part in enumerate(parts):
            marker = None
            if part == ".claude" and len(parts) > i + 2 and parts[i + 1] == "worktrees":
                marker = Path(*parts[:i + 3])
            elif part == ".peerlab" and len(parts) > i + 1 and parts[i + 1].startswith("peer-"):
                marker = Path(*parts[:i + 2])
            if marker is None:
                continue
            owner = Path(*parts[:i])
            owner_top = _git(owner, "rev-parse", "--show-toplevel") if owner.is_dir() else ""
            common = _git(owner, "rev-parse", "--git-common-dir") if owner_top else ""
            if not owner_top or Path(owner_top).resolve() != owner.resolve() or not common or not (owner / common).resolve().is_dir():
                continue
            registered = any(line == "worktree " + str(marker) for line in _git(owner, "worktree", "list", "--porcelain").splitlines())
            top = owner_top
            managed = dict(type="managed_worktree_location", path=str(path), repository=str(owner),
                           git_common_dir=str((owner / common).resolve()),
                           status="recorded" if registered else "suggested",
                           basis="Live Git worktree registration" if registered else "Recognized tool worktree path and enclosing live Git common directory; removed worktree identity is unverified.")
            break
    root = Path(top).resolve() if top else path
    origin = sanitize_origin(_git(root, "config", "--get", "remote.origin.url")) if top else ""
    common = _git(root, "rev-parse", "--git-common-dir") if top else ""
    if common:
        common = str((root / common).resolve())
    identity = "origin:" + origin if origin else "git:" + common if common else "path:" + str(root)
    basis = "Git origin" if origin else "Git common directory" if common else "Local path fallback"
    return dict(root=root, identity=identity, basis=basis, origin=origin, managed=managed)


def _relative(path, root):
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return None


def _safe_relative(value):
    path = Path(str(value))
    return bool(str(value)) and not path.is_absolute() and ".." not in path.parts


def _minimal_paths(paths):
    """Keep a union of directory/file scopes without redundant child entries."""
    result = []
    for value in sorted(set(paths), key=lambda p: (len(Path(p).parts), p)):
        if not any(parent == "." or value == parent or value.startswith(parent.rstrip("/") + "/") for parent in result):
            result.append(value)
    return result


def _package(path, warnings):
    try:
        data = _read(path / "package.json", {}, 512 * 1024)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError) as exc:
        warnings.append("Unreadable package metadata: " + str(path / "package.json") + " (" + str(exc) + ")")
        return {}


def _boundaries(root, warnings, max_boundaries, native_apps=()):
    """Declared runnable workspace apps, plus explicit laboratory directories.

    Shared packages do not become products merely because a package.json exists.
    This is bounded metadata discovery, not a second source analyzer.
    """
    package = _package(root, warnings)
    workspaces = package.get("workspaces", [])
    if isinstance(workspaces, dict):
        workspaces = workspaces.get("packages", [])
    patterns = workspaces if isinstance(workspaces, list) else []
    found = {}
    truncated = False
    inspected = 0
    for application in native_apps:
        if application.get("owner_root") and application["owner_root"] != str(root):
            continue
        relative = _relative(Path(application["path"]), root)
        if not relative or relative == ".":
            continue
        inspected += 1
        if inspected > max_boundaries:
            truncated = True
            break
        found[relative] = dict(relative=relative, kind="planet", label=application["label"],
                               description=application["description"], evidence=application["evidence"])
    for pattern in patterns:
        if not isinstance(pattern, str) or not _safe_relative(pattern) or "**" in pattern:
            warnings.append("Skipped unbounded/invalid workspace pattern in " + str(root / "package.json"))
            continue
        for candidate in root.glob(pattern):
            inspected += 1
            if inspected > max_boundaries:
                truncated = True
                break
            if not candidate.is_dir() or candidate.is_symlink() or candidate == root:
                continue
            data = _package(candidate, warnings)
            scripts = data.get("scripts") if isinstance(data.get("scripts"), dict) else {}
            runnable = sorted(set(scripts) & {"start", "dev", "serve"})
            if not (runnable or data.get("bin")):
                continue
            relative = candidate.relative_to(root).as_posix()
            if relative in found:
                continue
            found[relative] = dict(relative=relative, kind="planet", label=str(data.get("name") or candidate.name),
                                   description=str(data.get("description") or ""),
                                   evidence=dict(type="workspace_application", path=str(candidate / "package.json"),
                                                 pattern=pattern, runnable_scripts=runnable, has_bin=bool(data.get("bin"))))
    # Explicit labs below the repository and each runnable app; no name/topic ownership guesses.
    parents = [root] + [root / rel for rel in found]
    for parent in parents:
        # Cached addresses may now point at a substituted symlink. Their saved
        # evidence is still inspectable, but it must not trigger a live scan of
        # the redirected directory.
        relative_parent = parent.relative_to(root)
        if any((root.joinpath(*relative_parent.parts[:i])).is_symlink()
               for i in range(1, len(relative_parent.parts) + 1)):
            warnings.append("Skipped linked application metadata location: " + str(parent))
            continue
        try:
            laboratories = [p for p in parent.iterdir() if p.name.casefold() in LAB_DIRS and p.is_dir() and not p.is_symlink()]
        except OSError:
            continue
        for laboratory in laboratories:
            for candidate in laboratory.iterdir():
                inspected += 1
                if inspected > max_boundaries:
                    truncated = True
                    break
                if candidate.is_dir() and not candidate.is_symlink() and not candidate.name.startswith("."):
                    relative = candidate.relative_to(root).as_posix()
                    found[relative] = dict(relative=relative, kind="moon", label=candidate.name,
                                           description="Experiment directory; product relationship follows explicit containment.",
                                           evidence=dict(type="experiment_directory", path=str(candidate), parent=str(parent)))
    return package, list(found.values()), truncated


def _cached_applications(source, structure, warnings, previous_locations=None, dependency_components=None):
    """Exact native candidate addresses, from the published harvest only."""
    result = []
    if not isinstance(structure, dict):
        return result
    candidates = structure.get("application_candidates", [])
    if not isinstance(candidates, list):
        return result
    source_root = Path(source["root"]).expanduser().resolve()
    source_repo = _repository(source_root)
    for candidate in candidates[:64]:
        if not isinstance(candidate, dict):
            continue
        relative, manifest = candidate.get("root"), candidate.get("manifest")
        if (not isinstance(relative, str) or not _safe_relative(relative)
                or not isinstance(manifest, str) or not _safe_relative(manifest)
                or Path(manifest).parent != Path(relative)
                or Path(manifest).name not in {"package.json", "pyproject.toml", "Cargo.toml", "composer.json"}):
            warnings.append("Rejected invalid native application address in source " + source["id"])
            continue
        entries = candidate.get("entry_points", [])
        if not isinstance(entries, list):
            continue
        runnable = [entry for entry in entries if isinstance(entry, dict) and
                    (entry.get("type") in {"npm-bin", "console-script"} or
                     (entry.get("type") == "npm-script" and entry.get("name") in
                      {"npm run start", "npm run dev", "npm run serve"}))]
        if not runnable:
            continue
        root = source_root
        path = root / relative
        owner = source_repo
        candidate_repo = None
        relative_parts = Path(relative).parts
        linked = any(root.joinpath(*relative_parts[:i]).is_symlink() for i in range(1, len(relative_parts) + 1))
        if not linked:
            candidate_repo = _repository(path)
            if candidate_repo["basis"] != "Local path fallback" and (
                    source_repo["basis"] == "Local path fallback" or candidate_repo["root"] != path):
                owner = candidate_repo
        if linked or not path.is_dir():
            previous = (previous_locations or {}).get(str(path), {})
            for evidence in previous.get("evidence", []):
                saved = evidence.get("owner_root") if evidence.get("type") == "native_application" else None
                if (isinstance(saved, str) and Path(saved).is_absolute()
                        and _relative(path, Path(saved)) is not None):
                    owner = dict(root=Path(saved), basis="Previous owner; current app location unavailable")
                    break
        dependencies = [row for row in candidate.get("dependency_evidence", []) if isinstance(row, dict)
                        and row.get("type") == "declared_dependency"
                        and row.get("relationship") == "nonlocal_package_dependency"
                        and row.get("candidate_manifest") == manifest
                        and row.get("package") == candidate.get("name")
                        and isinstance(row.get("declaring_manifest"), str)
                        and _safe_relative(row["declaring_manifest"])
                        and Path(row["declaring_manifest"]).name == "package.json"
                        and Path(relative) != Path(row["declaring_manifest"]).parent
                        and Path(relative).is_relative_to(Path(row["declaring_manifest"]).parent)]
        if dependencies and candidate.get("local_declaration") not in {"workspace_member", "private_package"}:
            if candidate_repo and candidate_repo["basis"] != "Local path fallback" and candidate_repo["root"] == path:
                owner = candidate_repo  # Independent Git identity is stronger than a dependency reference.
            elif owner["root"] != path:
                if dependency_components is not None:
                    dependency_components.append(dict(source_id=source["id"], path=str(path),
                        label=str(candidate.get("name") or path.name)[:160], evidence=dependencies[:1],
                        reason="Runnable dependency evidence alone does not promote a product; workspace declarations are considered separately."))
                continue
        if path == owner["root"] and path == root:
            continue  # An exact repository root is already a destination.
        result.append(dict(path=str(path), label=str(candidate.get("name") or path.name)[:160],
                           owner_root=str(owner["root"]), source_root=str(root),
                           description=str(candidate.get("description") or "")[:640],
                           evidence=dict(type="native_application", path=str(root / manifest),
                                         owner_root=str(owner["root"]), owner_basis=owner["basis"],
                                         source_id=source["id"], artifact=str(Path(source["artifact"]) / "structure.json"),
                                         application_root=relative, entry_points=runnable[:32],
                                         build_systems=candidate.get("build_systems", [])[:32],
                                         dependency_evidence=dependencies[:1],
                                         status="candidate", meaning="Native runnable manifest evidence; product identity and runtime are unverified.")))
    return result


def _snapshot_contains(source, relative):
    """Test one exact retained subtree; never inspect the original source."""
    if not source.get("artifact") or not _safe_relative(relative):
        return False
    snapshot = Path(source["artifact"]) / "source"
    parts = Path(relative).parts
    if snapshot.is_symlink() or any(snapshot.joinpath(*parts[:i]).is_symlink() for i in range(1, len(parts) + 1)):
        return False
    return (snapshot / relative).exists()


def _declaration(root, warnings):
    path = root / ".navcom-space.json"
    try:
        value = _read(path, {}, 256 * 1024)
        if not isinstance(value, dict):
            raise ValueError("Expected an object")
        if value.get("kind", "planet") not in ("planet", "moon", "star"):
            raise ValueError("kind must be planet, moon or star")
        if "system" in value and (not isinstance(value["system"], dict) or not value["system"].get("id") or not value["system"].get("label")):
            raise ValueError("system needs explicit id and label")
        return value
    except (OSError, ValueError) as exc:
        warnings.append("Ignored declaration " + str(path) + ": " + str(exc))
        return {}


def _system(root, declaration):
    if declaration.get("system"):
        system = declaration["system"]
        return (_id("system", "declared:" + str(system["id"])), str(system["label"]), "established",
                dict(type="owner_declaration", path=str(root / ".navcom-space.json")))
    parts = root.parts
    for i, part in enumerate(parts[:-1]):
        if part.casefold() == "clients" and i + 1 < len(parts) - 1:
            client = Path(*parts[:i + 2])
            return (_id("system", "client:" + str(client)), parts[i + 1], "suggested",
                    dict(type="client_folder", path=str(client), meaning="Folder grouping; contractual ownership is not established."))
    return (INDEPENDENT, "Independent & unassigned", "unassigned",
            dict(type="unassigned", meaning="No declared suite or client-folder evidence."))


def _place_lab_applications(entities, edges, old_nodes):
    """An application inside a proven experiment is a facility at that place.

    Native entry/build detection establishes runnability, not an independent
    product. Exact experiment containment takes precedence only within the
    same Git repository. Names and token similarity never classify an app.
    Addresses keep their original opaque IDs so existing links, group owners
    and positions survive this refinement of the destination's kind.
    """
    experiments = []
    for node in entities.values():
        if node["kind"] != "moon":
            continue
        for evidence in node["evidence"]:
            if evidence.get("type") == "experiment_directory" and evidence.get("repository_root"):
                experiments.append((Path(evidence["path"]), evidence["repository_root"], node))
    placements = []
    for node in entities.values():
        if node["kind"] not in {"planet", "district"} or any(
                e.get("type") == "owner_declaration" for e in node["evidence"]):
            continue
        candidates = []
        for evidence in node["evidence"]:
            if evidence.get("type") not in {"native_application", "workspace_application"}:
                continue
            application = Path(evidence["path"]).parent
            owner = evidence.get("repository_root") or evidence.get("owner_root")
            if not owner:
                continue
            matches = [(path, repository, moon) for path, repository, moon in experiments
                       if repository == owner and application != path and _relative(application, path) is not None]
            if not matches:
                continue
            path, repository, moon = max(matches, key=lambda item: len(item[0].parts))
            relative = _relative(application, Path(repository))
            if relative is None:
                continue
            linked = any(Path(repository).joinpath(*Path(relative).parts[:i]).is_symlink()
                         for i in range(1, len(Path(relative).parts) + 1))
            available = not linked and application.is_dir()
            if available:
                actual = _repository(application)
                if actual["basis"] == "Local path fallback" or actual["root"] != Path(repository):
                    continue  # A separate nested Git product remains a product.
                observation = "current_git_owner"
            else:
                previous = old_nodes.get(node["id"], {})
                if (previous.get("form") != "application" or previous.get("parent_id") != moon["id"]
                        or not any(e.get("type") == "experiment_application" and e.get("path") == str(application)
                                   and e.get("repository_root") == repository for e in previous.get("evidence", []))):
                    continue
                observation = "previous_verified_containment"
            candidates.append((moon, dict(type="experiment_application", path=str(application),
                experiment_path=str(path), repository_root=repository, parent_id=moon["id"],
                basis=observation, available=available,
                meaning="Runnable application within this exact experiment and repository; not an independent product.")))
        targets = {moon["id"] for moon, _ in candidates}
        if len(targets) != 1:
            continue
        parent = candidates[0][0]
        cursor, seen = parent, set()
        while cursor and cursor["id"] not in seen and cursor["id"] != node["id"]:
            seen.add(cursor["id"])
            cursor = entities.get(cursor.get("parent_id"))
        if cursor is not None:
            continue
        node.update(kind="district", form="application", parent_id=parent["id"])
        for _, evidence in candidates:
            if evidence not in node["evidence"]:
                node["evidence"].append(evidence)
        edges[:] = [edge for edge in edges if not (edge["target"] == node["id"] and edge["relation"] == "contains")]
        edges.append(dict(source=parent["id"], target=node["id"], relation="contains",
                          status="suggested", evidence=candidates[0][1]))
        placements.append(dict(id=node["id"], parent_id=parent["id"], form="application"))
    return placements


def _reconcile_places(entities, edges, root_nodes, old_nodes, warnings):
    """Join exact metadata boundaries before aggregating any scope or counts.

    An independently indexed Git root can be the same destination already
    discovered through its parent's workspace manifest or LAB directory. Git
    identity does not cancel that explicit boundary. Names and similar content
    never participate in this reconciliation.
    """
    boundary_paths = defaultdict(set)
    containers = defaultdict(set)
    for node in entities.values():
        for evidence in node["evidence"]:
            if evidence.get("type") in {"experiment_directory", "workspace_application", "native_application"}:
                path = Path(evidence["path"])
                if evidence["type"] in {"workspace_application", "native_application"}:
                    path = path.parent
                boundary_paths[str(path)].add(node["id"])
            if node["kind"] == "system" and evidence.get("type") == "client_folder":
                containers[evidence["path"]].add(node["id"])

    redirects = {}
    reconciled = []
    conflicts = []

    def is_descendant(identity, ancestor):
        seen = set()
        while identity in entities and identity not in seen:
            if identity == ancestor:
                return True
            seen.add(identity)
            identity = entities[identity]["parent_id"]
        return False

    for node in list(entities.values()):
        roots = [e for e in node["evidence"] if e.get("type") == "repository_identity" and e.get("boundary") == "."]
        if not roots or node["kind"] not in {"planet", "moon"}:
            continue
        targets = {target for evidence in roots for target in boundary_paths[evidence["path"]]
                   if target != node["id"]}
        basis = "exact_declared_boundary"
        if not targets:
            # The client container is a suite address, unless its own repository,
            # package or declaration supplies independent product evidence.
            product_evidence = any(e.get("type") in {"owner_declaration", "package_manifest"}
                                   or (e.get("type") == "repository_identity" and e.get("basis") != "Local path fallback")
                                   for e in node["evidence"])
            if not product_evidence:
                targets = {target for evidence in roots for target in containers[evidence["path"]]}
                basis = "exact_client_container"
        if not targets:
            continue
        declared = any(e.get("type") == "owner_declaration" for e in node["evidence"])
        if len(targets) != 1 or declared or any(is_descendant(target, node["id"]) for target in targets):
            conflicts.append(dict(id=node["id"], candidates=sorted(targets),
                                  reason="Conflicting declaration, multiple boundaries or ancestor identity; no automatic merge."))
            continue
        target = next(iter(targets))
        redirects[node["id"]] = target
        reconciled.append(dict(from_id=node["id"], to_id=target, basis=basis,
                               paths=sorted({e["path"] for e in roots})))

    def canonical(identity):
        seen = set()
        while identity in redirects and identity not in seen:
            seen.add(identity)
            identity = redirects[identity]
        return identity

    def cycle_members(links):
        result, finished = set(), set()
        for identity in links:
            path, offsets = [], {}
            while identity in links and identity not in finished:
                if identity in offsets:
                    result.update(path[offsets[identity]:])
                    break
                offsets[identity] = len(path)
                path.append(identity)
                identity = links[identity]
            finished.update(path)
        return result

    # Individually safe merges can still make a cycle together: two products
    # may each contain a LAB clone of the other. Validate the combined proposed
    # containment, not only each original parent chain.
    while redirects:
        direct_cycles = cycle_members(redirects)
        parents = {identity: canonical(node["parent_id"]) for identity, node in entities.items()
                   if identity not in redirects}
        parent_cycles = cycle_members(parents)
        invalid = {identity for identity in redirects
                   if identity in direct_cycles or canonical(identity) in parent_cycles}
        if not invalid:
            break
        for identity in sorted(invalid):
            conflicts.append(dict(id=identity, candidates=[redirects.pop(identity)],
                                  reason="Combined boundary reconciliation would create a containment cycle; no automatic merge."))
        reconciled = [record for record in reconciled if record["from_id"] not in invalid]

    def merge(source, target):
        for field in ("evidence", "source_ids", "source_scopes", "conversation_collections",
                      "examples", "clues", "source_coverage"):
            for value in source.get(field, []):
                if value not in target.setdefault(field, []):
                    target[field].append(value)
        locations = {location["path"]: location for location in target["locations"]}
        for location in source["locations"]:
            if location["path"] not in locations:
                target["locations"].append(location)
                locations[location["path"]] = location
        target["conversation_count"] += source["conversation_count"]
        for field in ("package_name",):
            if not target.get(field) and source.get(field):
                target[field] = source[field]
        description_clues = [clue for clue in source.get("clues", [])
                             if clue.get("text") == source.get("description")]
        if description_clues:
            _prefer_description(target, max(description_clues, key=_description_priority))
        elif not target.get("description") and source.get("description"):
            target["description"] = source["description"]

    for identity in list(redirects):
        target = canonical(identity)
        merge(entities.pop(identity), entities[target])
    for node in entities.values():
        node["parent_id"] = canonical(node["parent_id"])

    # A source harvested separately at the nested Git root can have its own
    # native groups. Re-key those districts to their corrected owner, retaining
    # an already published district's position and combining exact source scopes.
    for identity, node in list(entities.items()):
        if node["kind"] != "district":
            continue
        group = next((e for e in node["evidence"] if e.get("type") == "starforge_token_group"), None)
        if not group:
            continue
        target = _id("district", node["parent_id"] + "::" + "|".join(group["shared_tokens"][:8]))
        if target == identity:
            continue
        redirects[identity] = target
        entities.pop(identity)
        if target in entities:
            merge(node, entities[target])
        else:
            node["id"] = target
            node["position"] = old_nodes.get(target, {}).get("position")
            entities[target] = node

    for root, identity in root_nodes.items():
        root_nodes[root] = canonical(identity)
    rewritten = []
    seen_edges = set()
    for edge in edges:
        edge = dict(edge, source=canonical(edge["source"]), target=canonical(edge["target"]))
        key = (edge["source"], edge["target"], edge["relation"])
        if edge["source"] == edge["target"] or key in seen_edges:
            continue
        if edge["relation"] == "contains" and entities[edge["target"]]["parent_id"] != edge["source"]:
            continue
        seen_edges.add(key)
        rewritten.append(edge)
    edges[:] = rewritten
    if conflicts:
        warnings.append(str(len(conflicts)) + " exact spatial boundary conflicts left unresolved; inspect coverage.reconciliation.conflicts.")
    return dict(merged=reconciled, conflicts=conflicts)


def _position(identity, kind, parent_position=None):
    if kind == "galaxy":
        return {"x": 0.0, "y": 0.0}
    digest = hashlib.sha256(identity.encode()).digest()
    angle = int.from_bytes(digest[:4], "big") / (2 ** 32) * math.tau
    scale = {"system": (900, 900), "planet": (160, 280), "moon": (50, 100), "district": (30, 90)}.get(kind, (200, 400))
    radius = scale[0] + int.from_bytes(digest[4:8], "big") / (2 ** 32) * scale[1]
    parent_position = parent_position or {"x": 0, "y": 0}
    return {"x": round(parent_position["x"] + math.cos(angle) * radius, 3),
            "y": round(parent_position["y"] + math.sin(angle) * radius, 3)}


def _star_inventory(inventory, source_by_root, cache_path, previous):
    """Page native metadata discovery; a bounded refresh resumes fairly next time.

    Metadata and provider inventory are the only operations here. The provider's
    callable interface templates are never executed. Chart reads never call this.
    """
    from navcom_stars import discover

    cache = cache_path.parent / (cache_path.name + ".stars")
    user_home = Path.home().resolve()
    protected = [user_home / ".hermes/hermes-agent",
                 user_home / ".codex/skills/ship-commission/scripts/borrowed", cache.resolve()]
    excluded_roots = []
    eligible = []
    for root in inventory:
        path = Path(root).resolve()
        if path == user_home or path in user_home.parents:
            excluded_roots.append(dict(path=root, reason="Home/system ancestor is a context container, not a bounded project root"))
        elif any(target.resolve().is_relative_to(path) for target in protected):
            excluded_roots.append(dict(path=root, reason="Root contains installed discovery tooling or its output cache"))
        else:
            eligible.append(root)
    ordered = sorted(eligible, key=lambda root: (root not in source_by_root, root))
    resume = previous.get("coverage", {}).get("stars", {}).get("resume_root")
    if resume in ordered:
        offset = ordered.index(resume)
        ordered = ordered[offset:] + ordered[:offset]
    home = Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes").expanduser()
    deadline = time.monotonic() + STAR_DISCOVERY_SECONDS
    coverage = dict(engine="Existing Hermes inventory and Starship/Starforge metadata detectors",
                    roots_requested=len(inventory), roots_eligible=len(ordered), roots_attempted=0, batches=[], complete=True,
                    unvisited_roots=[], deferred_roots=[], resume_root=None, gaps=[], excluded=[],
                    excluded_roots=excluded_roots, isolated_batches=0,
                    profile_home=str(home), live_checks=False,
                    bounds=dict(total_seconds=STAR_DISCOVERY_SECONDS, roots_per_batch=STAR_BATCH_ROOTS))
    records = {}
    cursor = 0
    first = True
    profile_refreshed = False
    isolate_until = 0
    while cursor < len(ordered) or first:
        remaining = deadline - time.monotonic()
        if remaining < .15:
            break
        batch = ordered[cursor:cursor + (1 if cursor < isolate_until else STAR_BATCH_ROOTS)]
        inputs = [dict(root=root, id=source_by_root[root][0]["id"]) if source_by_root.get(root)
                  else dict(root=root) for root in batch]
        walk_seconds = min(3., remaining / 3)
        native_seconds = min(5., max(.05, remaining - walk_seconds - .05))
        try:
            result = discover(inputs, cache, profile_home=home if first else None,
                              max_roots=STAR_BATCH_ROOTS, max_dirs=max(300, 300 * len(batch)),
                              seconds=walk_seconds, native_seconds=native_seconds)
        except (OSError, ValueError, RuntimeError) as exc:
            if len(batch) > 1:
                # One inaccessible mount or malformed root must not poison its
                # unrelated neighbors. Retry this bounded batch one root at a time.
                isolate_until = cursor + len(batch)
                coverage["isolated_batches"] += 1
                continue
            coverage["gaps"].append(dict(roots=batch, reason=type(exc).__name__ + ": metadata discovery unavailable"))
            coverage["deferred_roots"].extend(batch)
            coverage["complete"] = False
            cursor += len(batch)
            first = False
            if not batch:
                break
            continue
        observed = result.get("observed_at")
        batch_coverage = result.get("coverage", {})
        coverage["batches"].append(dict(roots=batch, fingerprint=result.get("fingerprint"),
                                         observed_at=observed, cache_hit=result.get("cache_hit", False),
                                         coverage=batch_coverage))
        coverage["complete"] &= bool(batch_coverage.get("complete", False))
        coverage["gaps"].extend(result.get("gaps", []))
        coverage["excluded"].extend(result.get("excluded", []))
        if result.get("gaps"):
            # A missing provider/runtime is not evidence that its resident
            # experts disappeared from the physical location.
            for gap in result["gaps"]:
                if isinstance(gap, dict) and gap.get("provider") == "hermes-profile":
                    continue
                if isinstance(gap, dict) and isinstance(gap.get("path"), str):
                    affected = [root for root in batch if _relative(Path(gap["path"]), Path(root)) is not None]
                    coverage["deferred_roots"].extend(affected or batch)
                else:
                    coverage["deferred_roots"].extend(batch)
        if first:
            profile_refreshed = not result.get("gaps") and not any(
                omitted.get("path") == str(home) for omitted in batch_coverage.get("skipped", []))
        for omitted in batch_coverage.get("skipped", []):
            if omitted.get("path") in batch and omitted.get("reason") in {
                    "directory budget", "metadata time budget", "missing or linked project root"}:
                coverage["deferred_roots"].append(omitted["path"])
            elif omitted.get("reason") == "metadata time budget" and not omitted.get("path"):
                coverage["deferred_roots"].extend(batch)
        for candidate in result.get("candidates", []):
            if not isinstance(candidate, dict) or not str(candidate.get("id", "")).startswith("star-candidate:"):
                continue
            if candidate.get("qualification") not in {"declared_candidate", "unconfirmed"}:
                coverage["excluded"].append(dict(id=candidate["id"], name=candidate.get("name", ""),
                                                   reason="Incomplete expertise evidence; not displayed as a star", candidate=candidate))
                continue
            record = dict(candidate, observed_at=observed, discovery_fingerprint=result.get("fingerprint"),
                          metadata_refresh="cached" if result.get("cache_hit") else "observed")
            if candidate["id"] in records:
                record["source_ids"] = sorted(set(record.get("source_ids", [])) | set(records[candidate["id"]].get("source_ids", [])))
            records[candidate["id"]] = record
        cursor += len(batch)
        first = False
        if not batch:
            break
    coverage["roots_attempted"] = cursor
    coverage["unvisited_roots"] = ordered[cursor:]
    coverage["deferred_roots"] = sorted(set(coverage["deferred_roots"]))
    pending = coverage["unvisited_roots"] + coverage["deferred_roots"]
    # Failed-but-attempted roots are retried by normal refresh. Only untouched
    # roots select the continuation cursor, so a permanent failure cannot hold it.
    coverage["resume_root"] = coverage["unvisited_roots"][0] if coverage["unvisited_roots"] else None
    coverage["complete"] &= not pending and not coverage["gaps"]
    coverage["profile_attempted"] = not first
    coverage["profile_metadata_refreshed"] = profile_refreshed
    # A deadline is not proof that an existing resident disappeared. Keep its
    # dated evidence explicitly stale until its exact root is inspected again.
    for old in previous.get("entities", []):
        record = old.get("star")
        if not isinstance(record, dict) or record.get("id") in records:
            continue
        binding = record.get("physical_binding", {})
        retained = binding.get("repository") in pending or (not profile_refreshed and binding.get("hermes_home") == str(home))
        if retained:
            records[record["id"]] = dict(record, metadata_refresh="not_refreshed")
    coverage["retained_unvisited_candidates"] = sum(r.get("metadata_refresh") == "not_refreshed" for r in records.values())
    return list(records.values()), coverage


def refresh(api, conn, cache_path, source_cache=None, progress=None, max_roots=1000, max_boundaries=200):
    """Publish a bounded current catalog. Never harvest implicitly or modify originals.

    ``conn`` may be None for a source-only catalog. Git/manifests are inspected
    here; code grouping comes exclusively from Starforge's published artifacts.
    A busy writer cannot invalidate the last complete reader snapshot.
    """
    if max_roots < 1 or max_boundaries < 1:
        raise ValueError("Discovery limits must be positive")
    path = Path(cache_path).expanduser()
    with _writer(path):
        old = _read(path, {}) or {}
        old_nodes = {n["id"]: n for n in old.get("entities", [])}
        old_locations = {loc["path"]: n for n in old_nodes.values() for loc in n.get("locations", [])}
        warnings = []
        indexed = defaultdict(list)
        unknown_projects = 0
        metadata_fallbacks = 0
        if conn is not None:
            # Existing NavCom inventory, preserving exact project collections.
            rows = conn.execute("SELECT s.file, m.project, m.title FROM file_state s LEFT JOIN file_meta m ON m.file=s.file").fetchall()
            for key, project, title in rows:
                # file_meta is a lazy cache: newly indexed sessions may not have
                # it yet. Reuse NavCom's existing provider metadata resolver,
                # as Atlas does, rather than silently dropping fresh projects.
                # Unlike session_meta(), this path never writes to the index.
                if not project and hasattr(api, "_project_from_key"):
                    project = api._project_from_key(key, api.detect_provider_from_path(key))
                    if project:
                        metadata_fallbacks += 1
                if not project:
                    unknown_projects += 1
                    continue
                display = api.pretty_project(project)
                root = Path(display).expanduser()
                if not root.is_absolute():
                    unknown_projects += 1
                    continue
                from navcom_atlas import identity
                indexed[str(root.resolve())].append(dict(collection="projects:" + identity(display),
                                                        title=_conversation_clue(api, conn, key, title), key=key))
        state = _read(Path(source_cache) / "current.json", {}) if source_cache else {}
        sources = state.get("sources", []) if isinstance(state, dict) else []
        source_by_root = defaultdict(list)
        structures = {}
        native_apps, dependency_components = [], []
        for source in sources:
            if isinstance(source, dict) and source.get("root") and source.get("id"):
                source_by_root[str(Path(source["root"]).expanduser().resolve())].append(source)
                structure = _read(Path(source["artifact"]) / "structure.json", None) if source.get("artifact") else None
                structures[source["id"]] = structure
                native_apps.extend(_cached_applications(source, structure, warnings, old_locations, dependency_components))
        # A source registered above a repository can still expose that exact
        # repository's apps. Add their owning roots and retain ancestor-relative
        # source scopes; unrelated ancestor cwds must not manufacture copies.
        inventory = sorted(set(indexed) | set(source_by_root) | {app["owner_root"] for app in native_apps})
        source_by_owner = defaultdict(list)
        sources_by_id = {source["id"]: source for source in sources}
        for application in native_apps:
            source = sources_by_id[application["evidence"]["source_id"]]
            owner_sources = source_by_owner[application["owner_root"]]
            if source not in owner_sources:
                owner_sources.append(source)
            # Older published snapshots predate native app DTOs. Once another
            # source establishes the address, their retained subtree still
            # supplies exact evidence; no source rescan or manual sync is needed.
            for ancestor in sources:
                relative = _relative(Path(application["path"]), Path(ancestor["root"]).expanduser().resolve())
                if relative is not None and _snapshot_contains(ancestor, relative) and ancestor not in owner_sources:
                    owner_sources.append(ancestor)
        truncated = len(inventory) > max_roots
        inventory = inventory[:max_roots]
        entities = {}
        edges = []
        edge_keys = set()
        root_nodes = {}
        boundaries_by_root = {}
        rejected_groups = 0
        missing_structure = []
        unavailable = []

        def put(identity, kind, label, parent=GALAXY, status="suggested", evidence=None, **extra):
            if identity not in entities:
                prior = old_nodes.get(identity, {})
                entities[identity] = dict(id=identity, kind=kind, label=label, parent_id=parent, status=status,
                                          evidence=[], locations=[], source_ids=[], source_scopes=[],
                                          conversation_collections=[], conversation_count=0, examples=[],
                                          position=prior.get("position"), **extra)
            node = entities[identity]
            if evidence and evidence not in node["evidence"]:
                node["evidence"].append(evidence)
            return node

        def edge(parent, child, relation="contains", status="suggested", evidence=None):
            key = (parent, child, relation)
            if key not in edge_keys:
                edge_keys.add(key)
                edges.append(dict(source=parent, target=child, relation=relation, status=status, evidence=evidence or {}))

        put(GALAXY, "galaxy", "Your galaxy", parent=None, status="established",
            evidence=dict(type="inventory_scope", meaning="Your indexed and harvested work, independent of hosting machine."))
        for ordinal, root_string in enumerate(inventory):
            root = Path(root_string)
            if progress:
                progress(ordinal + 1, len(inventory))
            present = root.is_dir()
            if not present:
                unavailable.append(root_string)
            repo = _repository(root)
            repository_root = repo["root"]
            repository_present = repository_root.is_dir()
            declaration = _declaration(repository_root, warnings) if repository_present else {}
            system_id, system_label, system_status, system_evidence = _system(repository_root, declaration)
            # A duplicate/moved Git copy reuses its already established conceptual parent.
            basis = str(declaration.get("id") or repo["identity"])
            root_kind = declaration.get("kind") or ("moon" if EXPERIMENT.fullmatch(repository_root.name) else "planet")
            root_id = _id(root_kind, basis + "::.")
            prior_location = old_locations.get(str(repository_root)) if not repository_present else None
            retained_parent = None
            if prior_location:
                root_id = prior_location["id"]
                root_kind = prior_location["kind"]
                if prior_location.get("parent_id") in old_nodes:
                    prior_system = old_nodes[prior_location["parent_id"]]
                    if prior_system["kind"] == "system":
                        system_id, system_label, system_status = prior_system["id"], prior_system["label"], prior_system["status"]
                    elif prior_system["id"] in entities and any(e.get("type") in {"experiment_directory", "workspace_application", "native_application", "previous_boundary"}
                                                               for e in prior_location.get("evidence", [])):
                        retained_parent = prior_system["id"]
            if root_id in entities:
                system_id = entities[root_id]["parent_id"]
            elif root_id in old_nodes and old_nodes[root_id].get("parent_id") in old_nodes and not declaration.get("system"):
                parent_node = old_nodes[old_nodes[root_id]["parent_id"]]
                if parent_node["kind"] == "system":
                    system_id, system_label, system_status = parent_node["id"], parent_node["label"], parent_node["status"]
            system = put(system_id, "system", system_label, status=system_status, evidence=system_evidence)
            edge(GALAXY, system_id, status=system["status"], evidence=system_evidence)
            if str(repository_root) not in boundaries_by_root:
                package, boundaries, bounded = _boundaries(repository_root, warnings, max_boundaries, native_apps)
                truncated |= bounded
                boundaries_by_root[str(repository_root)] = (package, boundaries)
            package, boundaries = boundaries_by_root[str(repository_root)]
            label = str(declaration.get("label") or repository_root.name)
            if prior_location:
                label = prior_location["label"]
            evidence = dict(type="repository_identity", basis=repo["basis"], origin=repo["origin"],
                            path=str(repository_root), boundary=".")
            parent_id = retained_parent or system_id
            node = put(root_id, root_kind, label, parent=parent_id,
                       status="established" if declaration else "suggested", evidence=evidence,
                       description=_clean_clue(api, declaration.get("description") or package.get("description") or "", 320))
            for metadata, basis_name, filename in ((package, "package_manifest", "package.json"),
                                                   (declaration, "owner_declaration", ".navcom-space.json")):
                _prefer_description(node, dict(text=_clean_clue(api, metadata.get("description"), 320),
                                               basis=basis_name, path=str(repository_root / filename)))
            if package.get("name"):
                node["package_name"] = str(package["name"])
                manifest_evidence = dict(type="package_manifest", path=str(repository_root / "package.json"), name=str(package["name"]))
                if manifest_evidence not in node["evidence"]:
                    node["evidence"].append(manifest_evidence)
            if repo.get("managed"):
                node["evidence"].append(repo["managed"])
                location = dict(path=str(root), available=False, inspected=time.time(), basis=repo["managed"]["basis"])
                if not any(loc["path"] == str(root) for loc in node["locations"]):
                    node["locations"].append(location)
            elif not repository_present and not node.get("description"):
                node["description"] = "Unavailable indexed location; current repository identity could not be checked."
            if retained_parent:
                previous_observation = next((e.get("observed_at") for e in prior_location.get("evidence", [])
                                             if e.get("type") == "previous_boundary"), old.get("published"))
                node["evidence"].append(dict(type="previous_boundary", parent_id=retained_parent,
                                              observed_at=previous_observation, path=str(repository_root),
                                              status="unavailable", meaning="Previous recorded boundary; current location is unavailable."))
            if root_kind == "moon" and parent_id == system_id:
                node["ownership"] = "Product unassigned; experiment name alone does not establish a parent product."
            if declaration:
                node["evidence"].append(dict(type="owner_declaration", path=str(repository_root / ".navcom-space.json")))
            edge(parent_id, root_id, status=node["status"], evidence=evidence)
            candidates = [(repository_root, node)]
            for boundary in sorted(boundaries, key=lambda b: (b["kind"] == "moon", len(b["relative"]))):
                rel = boundary["relative"]
                destination = repository_root / rel
                parent_id = system_id
                if boundary["kind"] == "moon":
                    ancestors = [(p, n) for p, n in candidates if _relative(destination, p) is not None and n["kind"] == "planet"]
                    parent_id = max(ancestors, key=lambda item: len(str(item[0])))[1]["id"] if ancestors else root_id
                child_id = _id(boundary["kind"], basis + "::" + rel)
                prior_boundary = old_locations.get(str(destination)) if not destination.is_dir() else None
                if prior_boundary and prior_boundary["kind"] == boundary["kind"]:
                    child_id = prior_boundary["id"]
                boundary_evidence = dict(boundary["evidence"], repository_root=str(repository_root))
                child = put(child_id, boundary["kind"], boundary["label"], parent=parent_id,
                            evidence=boundary_evidence, description=_clean_clue(api, boundary["description"], 320),
                            status="candidate" if boundary["evidence"]["type"] == "native_application" else "suggested")
                _prefer_description(child, dict(text=_clean_clue(api, boundary["description"], 320),
                                                basis=boundary["evidence"]["type"],
                                                path=boundary["evidence"].get("path", str(destination))))
                edge(parent_id, child_id, evidence=boundary["evidence"])
                if boundary["kind"] == "planet":
                    edge(root_id, child_id, relation="shares_repository", evidence=boundary["evidence"])
                candidates.append((destination, child))
            for candidate_root, candidate_node in candidates:
                relative_candidate = candidate_root.relative_to(repository_root)
                linked = any(repository_root.joinpath(*relative_candidate.parts[:i]).is_symlink()
                             for i in range(1, len(relative_candidate.parts) + 1))
                location = dict(path=str(candidate_root), available=candidate_root.is_dir() and not linked, inspected=time.time())
                if not any(loc["path"] == location["path"] for loc in candidate_node["locations"]):
                    candidate_node["locations"].append(location)
            # Indexed cwd belongs only to the most specific known boundary.
            scoped = [(p, n) for p, n in candidates if _relative(root, p) is not None]
            target = max(scoped, key=lambda item: len(str(item[0])))[1] if scoped else node
            root_nodes[root_string] = target["id"]
            for record in indexed.get(root_string, []):
                if record["collection"] not in target["conversation_collections"]:
                    target["conversation_collections"].append(record["collection"])
                target["conversation_count"] += 1
                if record["title"] and record["title"] not in target["examples"] and len(target["examples"]) < 3:
                    target["examples"].append(record["title"])
            relevant_sources = {source["id"]: source for source in source_by_root.get(root_string, [])}
            # Only the canonical repository iteration receives these sources;
            # indexed nested cwd iterations would otherwise duplicate groups.
            if root_string == str(repository_root):
                relevant_sources.update({source["id"]: source for source in source_by_owner.get(root_string, [])})
            for source in relevant_sources.values():
                artifact = Path(source.get("artifact", ""))
                source_root = Path(source["root"]).expanduser().resolve()
                borrowed = source not in source_by_root.get(root_string, [])
                for candidate_root, candidate_node in candidates:
                    relative = _relative(candidate_root, source_root)
                    if relative is None:
                        # A source harvested below a product still supplies that product.
                        if candidate_node is not target:
                            continue
                        relative = "."
                    if borrowed and not _snapshot_contains(source, relative):
                        # Native candidate DTOs prove their own recorded root,
                        # even in older fixture/partial artifacts without code.
                        native_proof = any(app["evidence"]["source_id"] == source["id"] and
                                           app["path"] == str(candidate_root) for app in native_apps)
                        if not native_proof:
                            continue
                    if source["id"] not in candidate_node["source_ids"]:
                        candidate_node["source_ids"].append(source["id"])
                    candidate_node["source_scopes"].append(dict(source_id=source["id"], paths=[relative]))
                    if source.get("artifact"):
                        clues = _source_clues(api, artifact, relative, root_source=relative == ".", display_name=candidate_node["label"])
                        saved_clues = candidate_node.setdefault("clues", [])
                        for clue in clues:
                            if clue not in saved_clues:
                                saved_clues.append(clue)
                        # A nested source can supply evidence to its containing
                        # product, but its README describes that nested scope.
                        if source_root / relative == candidate_root:
                            for clue in clues:
                                _prefer_description(candidate_node, clue)
                        candidate_node.setdefault("source_coverage", []).append(dict(
                            source_id=source["id"], snapshot=source.get("coverage", {}),
                            discovery=source.get("discovery_coverage", {})))
                structure = structures.get(source["id"])
                if not structure:
                    missing_structure.append(source["id"])
                    continue
                for group in structure.get("token_groups", []):
                    paths = sorted({p for p in group.get("paths", []) if isinstance(p, str) and _safe_relative(p)})
                    words = [str(w) for w in group.get("shared_tokens", []) if isinstance(w, (str, int))]
                    size = len(paths)
                    cohesion = group.get("cohesion", 0)
                    if not 2 <= size <= 80 or not words or not isinstance(cohesion, (float, int)) or cohesion < .05:
                        rejected_groups += 1
                        continue
                    # A group crossing app/experiment boundaries cannot establish one district.
                    owners = set()
                    outside_repository = False
                    for relative in paths:
                        physical = source_root / relative
                        native_matches = [app for app in native_apps if _relative(physical, Path(app["path"])) is not None]
                        if native_matches:
                            native_owner = max(native_matches, key=lambda app: len(Path(app["path"]).parts))["owner_root"]
                            if native_owner != str(repository_root) and _relative(Path(native_owner), repository_root) is not None:
                                outside_repository = True
                                break
                        matches = [(p, n) for p, n in candidates if _relative(physical, p) is not None]
                        if not matches:
                            outside_repository = True
                            break
                        owners.add(max(matches, key=lambda pair: len(str(pair[0])))[1]["id"])
                    if outside_repository:
                        continue  # Handled by its canonical native owner, not this ancestor.
                    if len(owners) != 1:
                        rejected_groups += 1
                        continue
                    owner = next(iter(owners))
                    district_id = _id("district", owner + "::" + "|".join(words[:8]))
                    group_evidence = dict(type="starforge_token_group", artifact=str(artifact / "structure.json"),
                                          paths=paths, shared_tokens=words, cohesion=cohesion, size=size)
                    label, label_basis, query_terms = _district_label(words, paths)
                    description = "Starforge grouped " + str(size) + " files: " + ", ".join(paths[:3])
                    if len(paths) > 3:
                        description += " and " + str(len(paths) - 3) + " more"
                    district = put(district_id, "district", label, parent=owner,
                                   evidence=group_evidence, description=description + ". Suggested area; inspect the files to confirm.")
                    district["label_basis"] = label_basis
                    district["suggested_query"] = " ".join(query_terms[:3]) if query_terms else " ".join(Path(p).stem for p in paths[:2])
                    district["source_ids"] = sorted(set(district["source_ids"] + [source["id"]]))
                    district["source_scopes"].append(dict(source_id=source["id"], paths=paths))
                    edge(owner, district_id, evidence=group_evidence)
        reconciliation = _reconcile_places(entities, edges, root_nodes, old_nodes, warnings)
        reconciliation["lab_applications"] = _place_lab_applications(entities, edges, old_nodes)
        edge_keys = {(record["source"], record["target"], record["relation"]) for record in edges}
        star_records, star_coverage = _star_inventory(inventory, source_by_root, path, old)
        for record in star_records:
            binding = record.get("physical_binding", {})
            metadata_root = (Path(binding["compose"]).parent if binding.get("compose") else
                             Path(binding["path"]) if binding.get("path") else None)
            provenance = dict(type="native_star_metadata", provider=record.get("provider"),
                              observed_at=record.get("observed_at"), fingerprint=record.get("discovery_fingerprint"),
                              metadata_refresh=record.get("metadata_refresh"))
            node = put(record["id"], "star", record.get("name") or "Expertise candidate", status="candidate",
                       evidence=provenance, description=record.get("description", ""))
            node["star"] = record
            for field in ("provider", "provider_identity", "qualification", "description_auto", "charter_refs", "steward_refs",
                          "physical_binding", "interfaces", "version_evidence", "availability", "gaps", "observed_at",
                          "discovery_fingerprint", "metadata_refresh"):
                if field in record:
                    node[field] = record[field]
            node["provenance"] = provenance
            node["ownership"] = "Cross-system expertise candidate; its implementation location does not establish product or client ownership."
            node["evidence"].extend(dict(type="provider_metadata_reference", path=reference)
                                    for reference in record.get("evidence", []) if isinstance(reference, str))
            if metadata_root is not None:
                node["locations"].append(dict(path=str(metadata_root), available=None,
                                                inspected=record.get("observed_at"), basis="Provider metadata location; runtime remains unobserved"))
                # Search only this provider's metadata subtree. Shared source IDs
                # never imply that every file in the repository belongs to it.
                for root_string, root_sources in source_by_root.items():
                    relative = _relative(metadata_root, Path(root_string))
                    if relative is None:
                        if _relative(Path(root_string), metadata_root) is None:
                            continue
                        relative = "."
                    for source in root_sources:
                        node["source_ids"].append(source["id"])
                        node["source_scopes"].append(dict(source_id=source["id"], paths=[relative]))
                node["source_ids"] = sorted(set(node["source_ids"]))
                products = [(loc["path"], product) for product in entities.values()
                            if product["kind"] in {"planet", "moon"} for loc in product["locations"]
                            if _relative(metadata_root, Path(loc["path"])) is not None]
                if products:
                    depth = max(len(Path(location).parts) for location, _ in products)
                    related = {product["id"]: product for location, product in products if len(Path(location).parts) == depth}
                    node["related_product_ids"] = sorted(related)
                    for identity in sorted(related):
                        edge(node["id"], identity, relation="relates_to", status="recorded",
                             evidence=dict(type="provider_implementation_location", path=str(metadata_root), ownership="unproven"))
            edge(GALAXY, node["id"], status="candidate", evidence=provenance)
        # Fleet records preserve their actual base/ship meanings and historical status.
        # Source associations are exact physical-copy references, not product ownership.
        from navcom_fleet import read_fleet
        fleet = read_fleet(archive_cache=path.with_name(path.name + ".fleet-archives.json"))
        for record in fleet["entities"]:
            parent = record.get("parent_id") or GALAXY
            node = put(record["id"], record["kind"], record["label"], parent=parent,
                       status="recorded", evidence=dict(type="fleet_snapshot", **record.get("provenance", {})),
                       description=record.get("description", ""))
            for field in ("physical", "readiness", "provenance", "gaps", "art_role", "source_roots", "record_id", "unresolved_source_references", "form", "related_ship_id", "integrity", "native_observation"):
                if field in record:
                    node[field] = record[field]
            node["evidence"].extend(record.get("evidence", []))
            edge(parent, node["id"], status="recorded", evidence=dict(type="fleet_snapshot"))
            if record["kind"] == "ship":
                for source_root in record.get("source_roots", []):
                    for product in list(entities.values()):
                        if product["kind"] in ("planet", "moon") and any(loc["path"] == source_root for loc in product["locations"]):
                            edge(node["id"], product["id"], relation="relates_to", status="recorded",
                                 evidence=dict(type="fleet_source_reference", path=source_root))
        for record in fleet["entities"]:
            related = record.get("related_ship_id")
            if record.get("form") == "archive" and related in entities:
                edge(record["id"], related, relation="archive_of", status="recorded",
                     evidence=dict(type="commission_archive", **record.get("provenance", {})))
        # Storage links do not imply containment, current readiness, or duplicate
        # transcript membership. They remain navigable without crowding the
        # conceptual galaxy with every retained physical copy.
        def ship_link(node, relation):
            return dict(id=node["id"], label=node["label"], kind=node["kind"],
                        form=node.get("form", "working"), physical=node.get("physical", {}), relation=relation)
        for connection in edges:
            left, right = entities[connection["source"]], entities[connection["target"]]
            if connection["relation"] == "archive_of":
                left.setdefault("ship_links", []).append(ship_link(right, "working_copy"))
                right.setdefault("ship_links", []).append(ship_link(left, "stored_copy"))
            elif connection["relation"] == "relates_to" and left["kind"] == "ship":
                right.setdefault("ship_links", []).append(ship_link(left, "source_context"))
        entities[GALAXY]["stored_copies"] = sorted(
            [ship_link(node, "stored_copy") for node in entities.values() if node.get("form") == "archive"],
            key=lambda node: (node["label"].casefold(), node["id"]))
        # Retain durable positions (including disappeared IDs) independently of result subsets.
        positions = dict(old.get("positions", {}))
        def place(node, seen=None):
            seen = seen or set()
            if node["id"] in seen:
                raise ValueError("Spatial parent cycle")
            if not node["position"]:
                parent = entities.get(node["parent_id"])
                if parent:
                    place(parent, seen | {node["id"]})
                node["position"] = positions.get(node["id"]) or _position(node["id"], node["kind"], parent["position"] if parent else None)
            positions[node["id"]] = node["position"]
        # Parent scopes are unions of exact child collections, never title similarity.
        def aggregate(node, seen=None):
            seen = seen or set()
            if node["id"] in seen:
                raise ValueError("Spatial parent cycle")
            node["direct_conversation_count"] = node["conversation_count"]
            for child in [n for n in entities.values() if n["parent_id"] == node["id"]]:
                aggregate(child, seen | {node["id"]})
                node["conversation_count"] += child["conversation_count"]
                node["conversation_collections"] = sorted(set(node["conversation_collections"] + child["conversation_collections"]))
                node["source_ids"] = sorted(set(node["source_ids"] + child["source_ids"]))
                for scope in child["source_scopes"]:
                    if scope not in node["source_scopes"]:
                        node["source_scopes"].append(scope)
        aggregate(entities[GALAXY])
        # A code group has no direct transcript membership proof. Offer related
        # product history explicitly, after aggregation so it never inflates
        # counts or propagates a false district/file relationship upward.
        for node in entities.values():
            if node["kind"] != "district" or node["conversation_collections"]:
                continue
            product = entities.get(node["parent_id"], {})
            collections = product.get("conversation_collections", [])
            if collections:
                node["conversation_collections"] = list(collections)
                node["conversation_basis"] = dict(type="project_query_context", product_id=product["id"],
                                                   collections=list(collections), query=node.get("suggested_query", ""),
                                                   file_relationship="unproven", description="Related conversations in the containing product, matched by query; not proven to discuss these files.")
        for node in entities.values():
            if node.get("kind") != "star" or not node.get("star"):
                continue
            products = [entities[identity] for identity in node.get("related_product_ids", [])]
            collections = sorted({collection for product in products for collection in product["conversation_collections"]})
            if collections:
                node["conversation_collections"] = collections
                node["conversation_basis"] = dict(type="project_query_context", product_ids=[p["id"] for p in products],
                                                   collections=collections, query="", file_relationship="unproven",
                                                   description="Related conversations in the exact implementation product, matched by query; not proven to discuss this expert.")
        for node in entities.values():
            place(node)
            source_commands = []
            by_source = defaultdict(set)
            for scope in node["source_scopes"]:
                by_source[scope["source_id"]].update(scope["paths"])
            for source_id, paths in sorted(by_source.items()):
                paths = _minimal_paths(paths)
                command = ["navcom", "sources", "search", "<query>", "--within", source_id]
                if "." not in paths:
                    for relative in sorted(paths):
                        command.extend(["--path", relative])
                source_commands.append(command)
            node["commands"] = dict(explore=["navcom", "atlas", "explore", node["id"]],
                                    source_search=source_commands,
                                    conversation_search=[["navcom", "atlas", "search", node.get("suggested_query") or "<query>", "--within", cid] for cid in node["conversation_collections"]])
            if node["kind"] == "ship":
                node["commands"]["carried_context"] = ["navcom", "atlas", "context", node["id"]]
            if node.get("stored_copies"):
                node["commands"]["stored_copies"] = ["navcom", "atlas", "list", "ships"]
        data = dict(schema_version=SCHEMA_VERSION, published=time.time(), entities=list(entities.values()), edges=edges,
                    positions=positions, coverage=dict(indexed_projects=len(indexed), indexed_conversations=sum(map(len, indexed.values())),
                    unknown_projects=unknown_projects, harvested_sources=len(sources), source_published=state.get("published") if state else None,
                    metadata_fallbacks=metadata_fallbacks,
                    inspected_roots=len(inventory), unavailable_roots=unavailable, bounded=truncated,
                    limits=dict(max_roots=max_roots, max_boundaries_per_repository=max_boundaries),
                    missing_structure_sources=sorted(set(missing_structure)), rejected_token_groups=rejected_groups,
                    native_applications=dict(candidates=len(native_apps),
                        dependency_components=dependency_components,
                        sources={source_id: structure.get("application_coverage", {"complete": False, "reason": "Snapshot predates native app detection."})
                                 for source_id, structure in structures.items() if isinstance(structure, dict)}),
                    fleet=fleet["coverage"], stars=star_coverage, reconciliation=reconciliation,
                    warnings=warnings, history="Current evidence only; no historical as-of reconstruction.",
                    inventory="Indexed working directories and registered harvested sources; not a full disk inventory.",
                    ownership="Folder, manifest and experiment candidates are suggestions unless explicitly declared.",
                    compute="Procedural refresh; ordinary navigation uses this cache without models or source scans."))
        _atomic(path, data)
        return data


def destination_matches(cache_path, reference, within="", *, catalog=None):
    """Find exact names/IDs inside a place across all result pages."""
    data = catalog if catalog is not None else (_read(Path(cache_path).expanduser()) or {})
    center = view(cache_path, action="show", within=within, catalog=data)["center"]["id"]
    nodes = {node["id"]: node for node in data["entities"]}
    candidates = []
    for node in nodes.values():
        if reference.casefold() not in (node["id"].casefold(), node["label"].casefold()):
            continue
        cursor, visited = node["id"], set()
        while cursor in nodes and cursor not in visited:
            if cursor == center:
                candidates.append(node)
                break
            visited.add(cursor)
            cursor = nodes[cursor]["parent_id"]
    return candidates


def resolve_destination(cache_path, reference, within=""):
    """Resolve only an exact unique name/ID within the selected place."""
    candidates = destination_matches(cache_path, reference, within)
    return candidates[0]["id"] if len(candidates) == 1 else None


def view(cache_path, action="list", kind="", within="", query="", limit=50, offset=0, *, catalog=None):
    """Query one published catalog; exact containment scope precedes matching."""
    if action not in ("list", "explore", "search", "show"):
        raise ValueError("Unknown spatial action")
    if not 1 <= int(limit) <= 1000 or int(offset) < 0:
        raise ValueError("limit must be 1–1000 and offset must be nonnegative")
    kind = KINDS.get(kind, kind)
    if kind and kind not in {"galaxy", "system", "planet", "moon", "district", "star", "starbase", "ship"}:
        raise ValueError("Unknown spatial kind: " + kind)
    data = catalog if catalog is not None else _read(Path(cache_path).expanduser(), None)
    if not data or data.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Spatial catalog unavailable. Run navcom atlas refresh --space first.")
    nodes = {node["id"]: node for node in data["entities"]}
    if within and within not in nodes:
        matches = [n["id"] for n in nodes.values() if n["label"].casefold() == within.casefold()]
        if len(matches) != 1:
            raise ValueError("Spatial scope " + ("is ambiguous; use its ID." if matches else "was not found: " + within))
        within = matches[0]
    within = within or GALAXY
    children = defaultdict(list)
    for node in nodes.values():
        children[node["parent_id"]].append(node["id"])
    descendants = set()
    pending = list(children[within])
    while pending:
        identity = pending.pop()
        if identity not in descendants:
            descendants.add(identity)
            pending.extend(children[identity])
    eligible = {within} if action == "show" else descendants if action == "search" or kind else set(children[within])
    # Exploration is a conceptual overview. Stored copies are exposed in its
    # explicit catalog and through linked ships; search and typed lists retain
    # them as ordinary independently addressable destinations.
    stored_copies = [nodes[identity] for identity in eligible if nodes[identity].get("form") == "archive"]
    if action == "explore" and not kind and not query:
        eligible -= {node["id"] for node in stored_copies}
    if kind:
        eligible = {identity for identity in eligible if nodes[identity]["kind"] == kind}
    terms = re.findall(r"[\w]+", query.casefold())
    scored = []
    for identity in eligible:
        node = nodes[identity]
        haystack = " ".join([node["label"], node.get("description", ""), node.get("package_name", ""), *node.get("examples", []),
                             *[loc["path"] for loc in node["locations"]],
                             *[" ".join(e.get("shared_tokens", [])) for e in node["evidence"]]]).casefold()
        if all(term in haystack for term in terms):
            score = sum(3 if term in node["label"].casefold() else 1 for term in terms)
            scored.append((score, node))
    scored.sort(key=lambda pair: (-pair[0], pair[1]["kind"], pair[1]["label"].casefold(), pair[1]["id"]))
    total = len(scored)
    output = [node for _, node in scored[int(offset):int(offset) + int(limit)]]
    from navcom_place_overview import previews
    contents = previews(nodes.values(), [within, *[node["id"] for node in output]])
    output = [{**node, "contents": contents[node["id"]]} for node in output]
    breadcrumbs = []
    cursor = within
    visited = set()
    while cursor and cursor not in visited:
        visited.add(cursor)
        breadcrumbs.append({k: nodes[cursor][k] for k in ("id", "label", "kind")})
        cursor = nodes[cursor]["parent_id"]
    shown = {n["id"] for n in output} | {within}
    edges = [edge for edge in data["edges"] if edge["source"] in shown and edge["target"] in shown]
    return dict(schema_version=SCHEMA_VERSION, published=data["published"], action=action, kind=kind, within=within,
                query=query, center={**nodes[within], "contents": contents[within]}, breadcrumbs=list(reversed(breadcrumbs)), nodes=output, entities=output,
                edges=edges, coverage=data["coverage"], total=total, more=int(offset) + len(output) < total,
                stored_copy_count=len(stored_copies) if action == "explore" and not kind and not query else 0,
                offset=int(offset), limit=int(limit), search_scope="Cached place metadata; use destination commands for source and conversation contents.")
