"""Read Starship's existing fleet snapshot without probing or changing its ships.

Physical hosting is separate from conceptual geography. A historical receiving
test is evidence to inspect, never proof that a ship can be boarded now.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath


def _text(value):
    return value.strip() if isinstance(value, str) else ""


def _strings(value):
    return list(dict.fromkeys(_text(x) for x in value if _text(x))) if isinstance(value, list) else []


def _key(kind, *parts):
    digest = hashlib.sha256("\0".join(parts).encode()).hexdigest()[:20]
    return f"fleet:{kind}:{digest}"


def _read(path, problems, role):
    if path is None:
        return {}
    try:
        if path.stat().st_size > 16 * 1024 * 1024:
            raise ValueError("record exceeds 16 MiB")
        data = json.loads(path.read_text())
        if not isinstance(data, dict):
            raise ValueError("expected a JSON object")
        return data
    except (OSError, ValueError) as exc:
        problems.append({"source": role, "path": str(path), "reason": type(exc).__name__})
        return {}


def _path(value, base=""):
    """Normalize a declared POSIX location without resolving a remote path."""
    value = _text(value)
    if not value or value.lower() in {"not recorded", "unknown", "unassigned"}:
        return None
    p = PurePosixPath(value)
    if ".." in p.parts or "\x00" in value:
        return None
    if not p.is_absolute():
        if not base or not PurePosixPath(base).is_absolute():
            return None
        p = PurePosixPath(base) / p
    return str(p)


def read_fleet(snapshot_path=None, config_path=None, *, archive_cache=None, archive_limit=128, archive_seconds=5):
    """Return ``{schema_version, entities, coverage}`` from optional local records.

    Paths may be supplied explicitly, through NAVCOM_FLEET_SNAPSHOT and
    NAVCOM_FLEET_CONFIG, or from NAVCOM_STARSHIP_ROOT (default ~/dev/starship).
    Exact commission evidence also permits bounded installed-native archive
    metadata inspection, cached in archive_cache (or NAVCOM_FLEET_CACHE).
    No network, private configuration, readiness or captain actions are used.
    Missing/malformed inputs produce coverage gaps, not startup failures.
    """
    root = Path(os.environ.get("NAVCOM_STARSHIP_ROOT", "~/dev/starship")).expanduser()
    explicit_snapshot = snapshot_path or os.environ.get("NAVCOM_FLEET_SNAPSHOT")
    snapshot = Path(explicit_snapshot).expanduser() if explicit_snapshot else root / "bridge/data.json"
    explicit_config = config_path or os.environ.get("NAVCOM_FLEET_CONFIG")
    if explicit_config:
        config = Path(explicit_config).expanduser()
    elif not explicit_snapshot:
        config = root / "LABS/101-captain-fleet/fleet.json"
    elif snapshot.parent.name == "bridge":
        config = snapshot.parent.parent / "LABS/101-captain-fleet/fleet.json"
    else:
        config = None
    problems = []
    data = _read(snapshot, problems, "snapshot")
    settings = _read(config, problems, "config")
    host = _text(settings.get("ssh_host")) or None
    base = _path(settings.get("remote_root")) or _path(data.get("base"))
    volume = _text(settings.get("volume_uuid")) or None
    as_of = _text(data.get("generated")) or None
    source_home = _path(settings.get("home"))
    entities = []
    base_id = _key("starbase", host or "unknown-host", volume or base or str(snapshot)) if base else None
    provenance = {"snapshot": str(snapshot), "config": str(config) if config else None,
                  "as_of": as_of, "basis": "Starship metadata snapshot"}
    readiness = {"status": "unknown", "basis": "historical-record", "as_of": as_of,
                 "message": "Current availability and boarding have not been checked."}
    if base_id:
        entities.append({"id": base_id, "kind": "starbase", "label": _text(data.get("destination")) or f"Starbase at {base}",
                         "parent_id": None, "source_roots": [], "art_role": "starbase",
                         "physical": {"host": host, "path": base, "volume_uuid": volume, "availability": "unobserved"},
                         "readiness": dict(readiness), "provenance": dict(provenance),
                         "gaps": ["Storage availability has not been observed."], "evidence": []})
    rows = data.get("ships", [])
    if not isinstance(rows, list):
        problems.append({"source": "snapshot", "path": str(snapshot), "reason": "ships must be a list"})
        rows = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            problems.append({"source": "snapshot", "reason": "ignored invalid ship entry"})
            continue
        name = _text(row.get("name")) or _text(row.get("id"))
        record_id = _text(row.get("id")) or name
        if not record_id:
            problems.append({"source": "snapshot", "reason": "ignored unnamed ship entry"})
            continue
        ship_id = _key("ship", base_id or str(snapshot), record_id)
        if ship_id in seen:
            problems.append({"source": "snapshot", "reason": "ignored duplicate ship entry", "record_id": record_id})
            continue
        seen.add(ship_id)
        roots = []
        unresolved_roots = []
        for source in _strings(row.get("sources")):
            if source.startswith("~/") and source_home:
                source = str(PurePosixPath(source_home) / source[2:])
            resolved = _path(source)
            (roots if resolved else unresolved_roots).append(resolved or source)
        location = _path(row.get("destination"), base or "")
        gaps = _strings(row.get("gaps"))
        if not location:
            gaps.append("A usable destination path is not recorded.")
        if not host:
            gaps.append("The destination host is not recorded.")
        if unresolved_roots:
            gaps.append("Some source references are not absolute paths.")
        evidence = _text(row.get("evidence"))
        evidence_path = _path(evidence, str(snapshot.parent.parent)) if snapshot.parent.name == "bridge" else _path(evidence)
        entities.append({"id": ship_id, "kind": "ship", "label": name,
                         "record_id": record_id, "parent_id": base_id, "source_roots": roots,
                         "unresolved_source_references": unresolved_roots, "art_role": "ship",
                         "physical": {"host": host, "path": location, "volume_uuid": volume, "availability": "unobserved"},
                         "readiness": dict(readiness, recorded_state=_text(row.get("state")) or "not recorded"),
                         "description": _text(row.get("detail")),
                         "provenance": dict(provenance, record_id=record_id, basis=_text(row.get("basis")) or "Starship metadata snapshot"),
                         "gaps": list(dict.fromkeys(gaps)),
                         "evidence": [{"reference": evidence, "path": evidence_path}] if evidence else []})
    coverage = {"available": bool(data or settings), "status": "historical" if data else "partial" if settings else "unavailable",
                "as_of": as_of, "snapshot": str(snapshot), "config": str(config) if config else None,
                "ships": sum(e["kind"] == "ship" for e in entities), "starbases": int(bool(base_id)),
                "live_checks": False, "problems": problems,
                "notes": ["Fleet metadata is historical evidence, not current readiness.",
                          "Conceptual product locations are separate from physical hosting."]}
    from navcom_commission_archives import discover
    archives = discover(entities, snapshot, cache_path=archive_cache,
                        limit=archive_limit, seconds=archive_seconds)
    entities.extend(archives['entities'])
    coverage['archives'] = archives['coverage']
    coverage['recorded_ships'] = coverage['ships']
    coverage['ships'] += len(archives['entities'])
    return {"schema_version": 1, "entities": entities, "coverage": coverage}


load = read_fleet
