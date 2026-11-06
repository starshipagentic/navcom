"""Explainable fleet berths derived only from one supplied cached chart.

Berths are layout metadata, not new destinations, ownership or physical moves.
The caller derives them before filtering/paging and retains original ship IDs,
parents and coordinates. No native inspection, source read or model is invoked.
"""

from collections import defaultdict
import hashlib
import json
from pathlib import PurePosixPath

def _key(namespace, *parts):
    value = json.dumps(parts, ensure_ascii=False, separators=(",", ":"))
    return namespace + ":" + hashlib.sha256(value.encode()).hexdigest()[:20]


def _path(value):
    if not isinstance(value, str) or not value.startswith("/") or "\x00" in value:
        return None
    path = PurePosixPath(value)
    return None if ".." in path.parts else path


def _system(node, nodes):
    seen = set()
    while node and node["id"] not in seen:
        seen.add(node["id"])
        if node.get("kind") == "system":
            return node
        node = nodes.get(node.get("parent_id"))
    return None


def _independent(system):
    return system["id"] == "system:independent" or any(
        e.get("type") == "unassigned" for e in system.get("evidence", [])
        if isinstance(e, dict)
    )


def _families(members, contexts):
    """Connected sets of exact recorded references, never name resemblance."""
    parent = {identity: identity for identity in members}
    def find(identity):
        while parent[identity] != identity:
            parent[identity] = parent[parent[identity]]
            identity = parent[identity]
        return identity
    owners = {}
    for identity in sorted(members):
        for context in sorted(contexts[identity]):
            if context in owners:
                a, b = sorted((find(identity), find(owners[context])))
                parent[b] = a
            else:
                owners[context] = identity
    families = defaultdict(list)
    for identity in members:
        families[find(identity)].append(identity)
    return list(families.values())


def derive(catalog, base_id):
    """Return stable grouping for *all* direct ship children of one starbase.

Exact fleet-source links and cached client-folder containment establish context
    first. Otherwise shared exact product/source references provide small context
    berths. Singletons remain unassigned. Names, topic guesses and receiving
    reports never establish a relationship or physical berth.

Families use shared exact context only *within* a berth. Their keys can change
when evidence connects/disconnects contexts; unrelated paging, order, filters,
labels and readiness changes do not change them or the stable berth IDs.
"""
    nodes = {n["id"]: n for n in catalog.get("entities", [])
             if isinstance(n, dict) and isinstance(n.get("id"), str)}
    base = nodes.get(base_id)
    if not base or base.get("kind") != "starbase":
        raise ValueError("Fleet layout requires an exact cached starbase ID")
    ships = {identity: node for identity, node in nodes.items()
             if node.get("kind") == "ship" and node.get("parent_id") == base_id}
    products = defaultdict(set)
    for edge in catalog.get("edges", []):
        if not isinstance(edge, dict) or edge.get("relation") != "relates_to":
            continue
        evidence = edge.get("evidence", {})
        target = nodes.get(edge.get("target"), {})
        if (edge.get("source") in ships and target.get("kind") in {"planet", "moon"}
                and isinstance(evidence, dict) and evidence.get("type") == "fleet_source_reference"):
            products[edge["source"]].add(target["id"])
    folders = []
    for node in nodes.values():
        if node.get("kind") != "system" or _independent(node):
            continue
        for evidence in node.get("evidence", []):
            if isinstance(evidence, dict) and evidence.get("type") == "client_folder":
                path = _path(evidence.get("path"))
                if path:
                    folders.append((path, node["id"]))
    folders = sorted(set(folders), key=lambda item: (str(item[0]), item[1]))
    assignments, groups, contexts = {}, {}, {}
    for identity, ship in sorted(ships.items()):
        roots = sorted({str(path) for value in ship.get("source_roots", [])
                        if (path := _path(value)) is not None})
        evidence, systems = [], set()
        for product_id in sorted(products[identity]):
            product = nodes[product_id]
            system = _system(product, nodes)
            evidence.append(dict(type="fleet_source_reference", product_id=product_id,
                                 system_id=system["id"] if system else None))
            if system and not _independent(system):
                systems.add(system["id"])
        for root in roots:
            matching = [(path, system) for path, system in folders
                        if PurePosixPath(root).is_relative_to(path)]
            # A more specific recorded client folder beats its outer container.
            # Ties remain multiple context associations, never a guessed winner.
            depth = max((len(path.parts) for path, _ in matching), default=0)
            for path, system in matching:
                if len(path.parts) == depth:
                    systems.add(system)
                    evidence.append(dict(type="client_folder", source_root=root,
                                         path=str(path), system_id=system,
                                         meaning="Cached folder context; ownership is not established."))
        if systems:
            related = sorted(systems)
            label = nodes[related[0]]["label"] if len(related) == 1 else "Cross-system context"
            basis = "cached_system_context" if len(related) == 1 else "multiple_system_context"
            status = "recorded" if len(related) == 1 and nodes[related[0]].get("status") == "established" else "suggested"
            group_id = _key("fleet-berth", base_id, "systems", related)
            evidence.extend(dict(type="system_context", system_id=sid, label=nodes[sid]["label"],
                                 status=nodes[sid].get("status", "unknown")) for sid in related)
        else:
            label, basis, status = "Unassigned context", "no_grouped_context", "unassigned"
            group_id = _key("fleet-berth", base_id, "unassigned")
            evidence.extend(dict(type="recorded_source", path=root) for root in roots)
        assignments[identity] = dict(id=group_id, label=label, basis=basis, status=status,
                                     evidence=evidence, family_key="")
        group = groups.setdefault(group_id, dict(id=group_id, label=label, basis=basis,
                                                status=status, count=0, members=[]))
        group["members"].append(identity)
        # Different apparent business ownership never joins the same family.
        contexts[identity] = {"product:" + pid for pid in products[identity]} | {"source:" + root for root in roots}

    unassigned_id = _key("fleet-berth", base_id, "unassigned")
    if unassigned_id in groups:
        unassigned = groups[unassigned_id]
        for members in _families(unassigned["members"], contexts):
            if len(members) < 2:
                continue
            anchors = sorted(set().union(*(contexts[identity] for identity in members)))
            common = set.intersection(*(contexts[identity] for identity in members))
            product_ids = sorted(value[len("product:"):] for value in common if value.startswith("product:"))
            sources = sorted(value[len("source:"):] for value in common if value.startswith("source:"))
            label = (nodes[product_ids[0]]["label"] if product_ids else
                     PurePosixPath(sources[0]).name if sources else "Shared source context") or "Shared source context"
            group_id = _key("fleet-berth", base_id, "shared_context", anchors)
            groups[group_id] = dict(id=group_id, label=label, basis="shared_exact_context",
                                    status="recorded", count=0, members=members)
            for identity in members:
                assignments[identity].update(id=group_id, label=label, basis="shared_exact_context", status="recorded")
                assignments[identity]["evidence"].append(dict(type="shared_exact_context", references=anchors,
                    meaning="Shared recorded source/product references; not ownership or readiness."))
        unassigned["members"] = [identity for identity in unassigned["members"] if assignments[identity]["id"] == unassigned_id]
        if not unassigned["members"]:
            del groups[unassigned_id]

    for group in groups.values():
        for members in _families(group["members"], contexts):
            anchors = sorted(set().union(*(contexts[identity] for identity in members)))
            family = _key("fleet-family", base_id, group["id"], anchors or ["ship:" + members[0]])
            for identity in members:
                assignments[identity]["family_key"] = family
        group["members"].sort(key=lambda identity: (assignments[identity]["family_key"], str(ships[identity].get("label", "")).casefold(), identity))
        group["count"] = len(group["members"])
    ordered = sorted(groups.values(), key=lambda group: (group["status"] == "unassigned", group["label"].casefold(), group["id"]))
    return dict(version=1, base_id=base_id, groups=ordered, assignments=assignments)
