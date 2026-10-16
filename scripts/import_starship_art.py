#!/usr/bin/env python3
"""Import selected original Starship PNGs through its catalog, preserving provenance."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct


ROLES = {
    "starbase": "08-starbase/starbase-core",
    "dock": "08-starbase/arrival-dock",
    "archive": "08-starbase/archive-vault",
    "lab": "08-starbase/science-lab",
    "navcom": "08-starbase/navcom-relay",
    "observatory": "08-starbase/observatory",
    "city": "09-human-cities/city",
    "ship": "03-verdant-fleet/scout",
}


def import_art(source, destination):
    source, destination = Path(source).expanduser(), Path(destination)
    atlas = (source / "art/atlas").resolve()
    catalog_path = atlas / "catalog.json"
    catalog_bytes = catalog_path.read_bytes()
    catalog = json.loads(catalog_bytes)
    by_id = {a["id"]: a for a in catalog}
    staged = []
    for role, asset_id in ROLES.items():
        item = by_id[asset_id]
        original = (atlas / item["image"]).resolve()
        if not original.is_relative_to(atlas):
            raise ValueError(f"Asset escapes catalog root: {asset_id}")
        content = original.read_bytes()
        if not content.startswith(b"\x89PNG\r\n\x1a\n") or len(content) < 24:
            raise ValueError(f"Not a PNG: {asset_id}")
        width, height = struct.unpack(">II", content[16:24])
        staged.append((role, content, {"role": role, "id": asset_id,
            "file": f"{role}.png", "sha256": hashlib.sha256(content).hexdigest(),
            "bytes": len(content), "width": width, "height": height,
            "suggested_display_width": item.get("suggestedDisplayWidth"),
            "source_image": "art/atlas/" + item["image"],
            "source_sheet": "art/atlas/" + item.get("sheet", ""),
            "crop": item.get("crop"), "provenance": item.get("provenance", "not recorded"),
            "culture": item.get("culture"), "kind": item.get("kind"),
            "title": item.get("title")}))
    destination.mkdir(parents=True, exist_ok=True)
    copied = 0
    for role, content, _ in staged:
        target = destination / f"{role}.png"
        if not target.exists() or target.read_bytes() != content:
            target.write_bytes(content)
            copied += 1
    manifest = {"schema_version": 1, "source_project": "Starship", "source_catalog": "art/atlas/catalog.json",
                "source_catalog_sha256": hashlib.sha256(catalog_bytes).hexdigest(),
                "method": "Catalog-selected original PNG bytes; no image modification or regeneration.",
                "license_note": "Owner's existing generated art library. Source documentation states image_gen provenance; no separate art license declaration was found.",
                "assets": [entry for _, _, entry in staged]}
    target = destination / "manifest.json"
    content = json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    if not target.exists() or target.read_text() != content:
        target.write_text(content)
    return {"assets": len(staged), "copied": copied, "unchanged": len(staged) - copied, "manifest": str(target)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path.home() / "dev/starship")
    parser.add_argument("--destination", type=Path, default=Path(__file__).resolve().parents[1] / "assets/starship")
    args = parser.parse_args(argv)
    try:
        result = import_art(args.source, args.destination)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(1, f"Starship art import failed: {exc}\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
