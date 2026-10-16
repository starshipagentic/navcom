"""Optional, cached dossiers using the installed Starship metadata observer.

Only an explicitly local ship location is observed. A remote path is never
interpreted as a local mount. Historical receipts, current metadata observation,
receiving checks and captain takeover remain separate claims. No project-carried
code, restoration, integrity check, receiving command or captain command runs.
"""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import socket
import subprocess
import sys
import tempfile
import time


VERSION = 2
RECEIPT_LIMIT = 1024 * 1024
TOOLS = ("fleet.py", "descriptor.py", "service_control.py")
FORBIDDEN = {"secrets", ".aws", ".ssh", ".gnupg", "credentials", ".config"}
RECEIPT_NAMES = {"receipt.json", "RESULT.json", "receiving.json"}


def _text(value, limit=800):
    if not isinstance(value, str):
        return ""
    value = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", value).strip()[:limit]
    value = re.sub(r"(?i)\b(api[_-]?key|password|secret|access[_-]?token)\s*[:=]\s*\S+", r"\1=[redacted]", value)
    return re.sub(r"(https?://)[^/\s@]+@", r"\1[redacted]@", value)


def _strings(value):
    return [_text(v) for v in value[:40] if _text(v)] if isinstance(value, list) else []


def _absolute(value):
    if not isinstance(value, str) or "\x00" in value:
        return None
    path = PurePosixPath(value)
    return str(path) if path.is_absolute() and ".." not in path.parts else None


def _contains(root, value):
    try:
        PurePosixPath(value).relative_to(PurePosixPath(root))
        return True
    except ValueError:
        return False


def _stat(path):
    try:
        item = path.lstat()
        return dict(size=item.st_size, mtime_ns=item.st_mtime_ns, ctime_ns=item.st_ctime_ns, inode=item.st_ino,
                    symlink=path.is_symlink())
    except OSError:
        return None


def _safe_path(path):
    """Metadata must not escape through links or traverse private credential stores."""
    if any(part.casefold() in FORBIDDEN for part in path.parts):
        return False
    # Check ancestors first so probing a descendant never traverses a linked
    # metadata directory before we reject the link.
    return not any(p.is_symlink() for p in (*reversed(path.parents), path))


def _tool_identity(tool_root):
    root = Path(tool_root).expanduser()
    if not root.is_absolute() or ".starship" in root.parts or not _safe_path(root):
        raise ValueError("Use the installed ship-commission tools, never project-carried .starship code.")
    hashes = {}
    for name in TOOLS:
        path = root / name
        stat = _stat(path)
        if not stat or stat["symlink"] or stat["size"] > 512 * 1024 or not path.is_file():
            raise ValueError("Installed ship-commission observer is unavailable.")
        hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return dict(root=str(root), files=hashes)


def _observe(root, tool_root):
    # Isolated Python avoids project imports and PYTHONPATH. No live-config is
    # passed: upstream's application/service observer is deliberately inactive.
    script = """import json,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import fleet
assert Path(fleet.__file__).resolve() == (Path(sys.argv[1])/'fleet.py').resolve()
print(json.dumps(fleet.inspect_ship(Path(sys.argv[2]))))
"""
    completed = subprocess.run([sys.executable, "-I", "-B", "-c", script, str(tool_root), str(root)],
                               capture_output=True, text=True, timeout=15)
    if completed.returncode or len(completed.stdout) > 128 * 1024:
        raise ValueError("Installed Starship metadata observer failed; no readiness claim was made.")
    data = json.loads(completed.stdout)
    if not isinstance(data, dict) or data.get("path") != str(root):
        raise ValueError("Starship observation did not match the selected location.")
    return {k: data[k] for k in ("state", "repositories", "capture_evidence", "descriptor_binding",
                                "integrity", "application_journey", "captain", "handover") if k in data}


def _discover_receipts(root, record_id):
    """Bounded metadata lookup using the existing Starship commission layout."""
    if not isinstance(record_id,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,99}',record_id):
        return [], dict(directories=0,truncated=False)
    start=root/'.starship'/'commission'/record_id
    stack=[(start,0)]; candidates=[]; visited=0; entries=0; truncated=False
    while stack and visited<128 and entries<4096:
        directory,depth=stack.pop()
        if not _safe_path(directory) or not directory.is_dir():continue
        visited+=1
        try:
            # islice bounds even a malformed metadata directory with huge fanout.
            import itertools
            children=list(itertools.islice(directory.iterdir(),4097-entries))
        except OSError:continue
        entries+=len(children)
        if entries>4096:truncated=True;break
        for child in sorted(children,reverse=True):
            if child.is_symlink() or child.name.casefold() in FORBIDDEN:continue
            if child.name in RECEIPT_NAMES and child.is_file():candidates.append(child)
            elif child.is_dir() and not child.name.startswith('.') and child.name not in ('archive','working','active','logs','node_modules'):
                if depth<4:stack.append((child,depth+1))
                else:truncated=True
    return candidates,dict(directories=visited,entries=entries,truncated=truncated or bool(stack),
        basis='Bounded Starship commission metadata; receipts must match the exact physical root.')


def _receipt_candidate(entity, explicit, local, physical_path):
    """Use a caller-selected receipt or a receipt referenced by the existing snapshot.

    Snapshot references are restricted to metadata below that snapshot's project
    root. Commands, private routes and arbitrary JSON references are not followed.
    """
    discovery=dict(directories=0,truncated=False)
    if explicit is not None:
        candidates = [Path(explicit).expanduser()]
    else:
        provenance = entity.get("provenance", {})
        snapshot = _absolute(provenance.get("snapshot")) if isinstance(provenance, dict) else None
        metadata_root = Path(snapshot).parent.parent if snapshot and Path(snapshot).parent.name=='bridge' else None
        if metadata_root and not local and physical_path and (
                _contains(physical_path,str(metadata_root)) or _contains(str(metadata_root),physical_path)):
            metadata_root=None
        candidates = []
        if metadata_root:
            for item in entity.get("evidence", []):
                reference = _absolute(item.get("path")) if isinstance(item, dict) else None
                if reference and (_contains(str(metadata_root / ".starship" / "commission"), reference) or
                                  _contains(str(metadata_root / "LABS"), reference)):
                    candidates.append(Path(reference))
            discovered,discovery=_discover_receipts(metadata_root,entity.get('record_id') or provenance.get('record_id'))
            candidates+=discovered
        if local and physical_path:
            candidates += [Path(physical_path) / ".starship" / "runtime" / "receiving.json",
                           Path(physical_path) / ".starship" / "runtime" / "receipt.json"]
    matches=[]; inspected_bytes=0; inspected_receipts=0
    for path in dict.fromkeys(candidates):
        if not path.is_absolute() or ".." in path.parts or path.name not in RECEIPT_NAMES:
            continue
        if not local and physical_path and _contains(physical_path, str(path)):
            # Even an explicit receipt inside a remote location is not local.
            continue
        if _safe_path(path):
            stat = _stat(path)
            if stat and not stat["symlink"] and path.is_file():
                if explicit is not None:return path, stat, discovery
                if inspected_receipts>=64 or inspected_bytes+stat['size']>16*1024*1024:
                    discovery['truncated']=True
                    continue
                inspected_receipts+=1;inspected_bytes+=stat['size']
                try:
                    metadata,recorded=_receipt(path,physical_path)
                    if not metadata['identity_match']:continue
                    from datetime import datetime
                    try:stamp=datetime.fromisoformat(recorded['recorded_at'].replace('Z','+00:00')).timestamp()
                    except (ValueError,TypeError):stamp=0
                    matches.append((stamp,str(path),path,stat))
                except (OSError,ValueError):continue
    discovery.update(inspected_receipts=inspected_receipts,inspected_bytes=inspected_bytes)
    if matches:
        discovery['matching_receipts']=[dict(path=str(path),stat=stat) for _,_,path,stat in sorted(matches,reverse=True)]
        _,_,path,stat=max(matches)
        return path,stat,discovery
    return None, None, discovery


def _receipt(path, physical_path):
    if path.stat().st_size > RECEIPT_LIMIT:
        raise ValueError("Historical receipt exceeds the 1 MiB metadata limit.")
    raw = path.read_bytes()
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("Historical receipt must be a JSON object.")
    native = data.get("native") if isinstance(data.get("native"), dict) else {}
    roots = [_absolute(data.get(k)) for k in ("root", "working_root", "native_cwd")]
    roots.append(_absolute(native.get("cwd")))
    matched = bool(physical_path and physical_path in roots)
    metadata = dict(path=str(path), sha256=hashlib.sha256(raw).hexdigest(), identity_match=matched)
    if not matched:
        return metadata, {}
    history = data.get("history_coverage") if isinstance(data.get("history_coverage"), dict) else {}
    summary = {}
    for field in ("sessions", "messages"):
        if type(history.get(field)) is int and history[field] >= 0:
            summary[field] = history[field]
    for field in ("providers", "scope", "omitted"):
        if isinstance(history.get(field), list):
            summary[field] = _strings(history[field])
    dates = _strings(history.get("captured_at"))
    if dates:
        summary["captured_from"], summary["captured_to"] = min(dates), max(dates)
    if type(history.get("catalog_hashes_match")) is bool:
        summary["recorded_catalog_hashes_match"] = history["catalog_hashes_match"]
    thread = _text(data.get("native_thread") or native.get("thread_id") or data.get("thread_id"), 200)
    route_recorded = any(isinstance(v, str) and v for v in (data.get("resume_command"), native.get("resume_route"), native.get("actual_app_server_resume_route")))
    return metadata, dict(mission=_text(data.get("task") or data.get("scope")),
                          outcome=_text(data.get("outcome") or data.get("status") or data.get("state")),
                          recorded_at=_text(data.get("recorded_at") or data.get("finished_at") or data.get("completed"), 100),
                          viewpoint=dict(cwd=_text(data.get("native_cwd") or native.get("cwd") or data.get("working_root") or data.get("root"), 2000),
                                         thread=thread, harness=_text(data.get("harness"), 100), model=_text(data.get("model"), 200)),
                          route_recorded=route_recorded, context=summary,
                          gaps=_strings(data.get("remaining_gaps")) + _strings(data.get("unproved_scopes")) + _strings(data.get("limits")) + _strings(data.get("gaps")))


@contextmanager
def _writer(path):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with path.with_suffix(".lock").open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("Another inspection is running for this ship; cached browsing remains available.") from None
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _write(path, data):
    fd, name = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(data, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def inspect_ship(entity, cache_path, *, refresh=False, tool_root=None, receipt_path=None):
    """Inspect one exact catalog ship into a cache directory.

    ``tool_root`` and ``receipt_path`` are trusted caller configuration; neither
    is accepted from arbitrary entity fields. The default tool is the installed
    skill under ~/.codex/skills. Unsupported/remote states remain useful dossiers.
    """
    if not isinstance(entity, dict) or entity.get("kind") != "ship" or not entity.get("id"):
        raise ValueError("Select an exact catalog ship for inspection.")
    physical = entity.get("physical") if isinstance(entity.get("physical"), dict) else {}
    host = _text(physical.get("host"), 255)
    root = _absolute(physical.get("path"))
    local = host.casefold().rstrip(".") in {"localhost", "127.0.0.1", "::1", socket.gethostname().casefold().rstrip(".")}
    gaps = []
    selected_tool = Path(tool_root or Path.home() / ".codex" / "skills" / "ship-commission" / "scripts").expanduser()
    tool = None
    # Do not load or execute an observer for a remote or unlocated ship.
    if local and root:
        try:
            tool = _tool_identity(selected_tool)
        except (OSError, ValueError) as exc:
            gaps.append(str(exc))
    receipt, receipt_stat, receipt_discovery = _receipt_candidate(entity, receipt_path, local, root)
    location_stats = None
    if local and root and _safe_path(Path(root)) and _safe_path(Path(root) / ".starship"):
        location_stats = {relative: _stat(Path(root) / relative) for relative in
                          (".", ".starship", ".starship/manifest.json", ".starship/descriptor.json", ".starship/seal.json", ".starship/HANDOVER.md")}
    signature = dict(version=VERSION, ship=entity["id"], label=_text(entity.get("label"), 200), host=host, root=root, tool=tool,
                     tool_path=str(selected_tool), receipt=str(receipt) if receipt else None,
                     receipt_stat=receipt_stat, receipt_discovery=receipt_discovery, location_stats=location_stats)
    cache = Path(cache_path).expanduser() / (hashlib.sha256(str(entity["id"]).encode()).hexdigest() + ".json")
    try:
        saved = json.loads(cache.read_text())
        if not refresh and saved.get("signature") == signature:
            return dict(saved["result"], cached=True)
    except (OSError, ValueError, KeyError):
        pass
    with _writer(cache):
        now = time.time()
        result = dict(schema_version=VERSION, ship_id=entity["id"], label=_text(entity.get("label"), 200),
                      observed_at=now, cached=False,
                      physical=dict(host=host or None, path=root, availability="unobserved", locality="local" if local else "remote-or-unspecified"),
                      integrity=dict(status="not checked", capture_evidence="unknown", descriptor_binding="unknown"),
                      receiving=dict(status="not checked", current_ready=None),
                      captain=dict(status="not checked", route_validated=False, takeover_verified=False),
                      context={}, provenance=dict(tool=tool, receipt=None,receipt_discovery=receipt_discovery), gaps=gaps,
                      next_actions=[dict(id="refresh-inspection", label="Refresh metadata observation", effect="read-only", supported=True)])
        if receipt:
            try:
                provenance, recorded = _receipt(receipt, root)
                result["provenance"]["receipt"] = provenance
                if not recorded:
                    gaps.append("Receipt location does not match this ship; its receiving claims were not applied.")
                else:
                    result["receiving"].update(recorded_outcome=recorded["outcome"], recorded_at=recorded["recorded_at"], mission=recorded["mission"])
                    result["captain"].update(viewpoint=recorded["viewpoint"], route_recorded=recorded["route_recorded"])
                    result["context"] = recorded["context"]
                    if result['context']:
                        result['context'].update(recorded_at=recorded['recorded_at'],receipt_path=str(receipt))
                    gaps.extend(recorded["gaps"])
                    result["next_actions"].append(dict(id="read-receipt", label="Inspect historical receipt", effect="read-only", supported=True, path=str(receipt)))
            except (OSError, ValueError) as exc:
                gaps.append("Historical receipt unavailable: " + str(exc))
        if not result['context']:
            # A later supplemental check can omit carried-history coverage. Keep
            # the newest coverage-bearing receipt independently attributed.
            for item in receipt_discovery.get('matching_receipts',[]):
                try:
                    provenance,recorded=_receipt(Path(item['path']),root)
                    if recorded.get('context'):
                        result['context']=dict(recorded['context'],recorded_at=recorded['recorded_at'],receipt_path=item['path'])
                        result['provenance']['context_receipt']=provenance
                        break
                except (OSError,ValueError):continue
        if receipt_discovery['truncated']:
            gaps.append('Commission metadata lookup reached its bound; other historical receipts may exist.')
        if not local:
            gaps.append("Physical host is remote or unspecified; its path was not inspected on this machine.")
        elif not root:
            gaps.append("An absolute physical location is not recorded.")
        elif not location_stats:
            result["physical"]["availability"] = "unsafe-path"
            gaps.append("Linked or private credential paths are not inspected.")
        elif location_stats["."] is None:
            result["physical"]["availability"] = "missing"
        elif not Path(root).is_dir():
            result["physical"]["availability"] = "not-directory"
            gaps.append("The recorded ship location is not a directory.")
        else:
            result["physical"]["availability"] = "present"
            result["physical"]["observed_at"] = now
            if tool:
                try:
                    observed = _observe(Path(root), selected_tool)
                    result["physical"]["metadata_state"] = observed.get("state", "unknown")
                    result["physical"]["repositories"] = observed.get("repositories")
                    result["integrity"].update(capture_evidence=observed.get("capture_evidence", "unknown"), descriptor_binding=observed.get("descriptor_binding", "unknown"))
                    if observed.get("handover") and _contains(root, observed["handover"]):
                        result["next_actions"].append(dict(id="read-handover", label="Inspect receiving handover", effect="read-only", supported=True, path=observed["handover"]))
                except (OSError, ValueError, subprocess.SubprocessError) as exc:
                    gaps.append(str(exc))
        result["gaps"] = list(dict.fromkeys(gaps + ["Seal/descriptor presence does not prove archive integrity, application readiness or captain takeover."]))
        _write(cache, dict(signature=signature, result=result))
        return result
