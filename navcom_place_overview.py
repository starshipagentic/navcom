"""Small, factual previews of the places already present in a published chart.

This is shared summary data for the CLI and the view (factual counts and exact
child IDs), not another analyzer or ownership classifier.
Only direct children are summarized; searching never changes these previews.
"""
from collections import defaultdict

PREVIEW_PLACES = 4  # Named direct children per category.


def _category(node):
    if node.get("form") == "archive":
        return "archives"
    if node.get("kind") == "district" and node.get("form") == "application":
        return "applications"
    return {"system": "systems", "planet": "products", "moon": "experiments",
            "district": "areas", "star": "experts", "starbase": "starbases",
            "ship": "ships"}.get(node.get("kind"), "places")


def previews(entities, identities):
    """Return bounded direct-child clues for selected IDs from one publication."""
    wanted = set(identities)
    groups = {identity: defaultdict(list) for identity in wanted}
    descriptions = {}
    for node in entities:
        identity = node.get("id")
        if identity in wanted:
            description = node.get("description")
            for clue in node.get("clues", []):
                if description and clue.get("text") == description:
                    descriptions[identity] = {key: clue[key] for key in ("basis", "path", "artifact") if key in clue}
                    break
        parent = node.get("parent_id")
        if parent in wanted:
            groups[parent][_category(node)].append(node)
    output = {}
    order = ("systems", "products", "applications", "areas", "experiments",
             "experts", "starbases", "ships", "archives", "places")
    for identity in wanted:
        sections = []
        for category in order:
            members = groups[identity].get(category, [])
            if not members:
                continue
            members.sort(key=lambda node: (str(node.get("label", "")).casefold(), node["id"]))
            samples = []
            for node in members[:PREVIEW_PLACES]:
                item = {key: node[key] for key in ("id", "label", "kind", "form") if key in node}
                # Native groups retain their exact member paths. Their count is
                # useful context without pretending that it measures importance.
                paths = {path for evidence in node.get("evidence", [])
                         if evidence.get("type") == "starforge_token_group"
                         for path in evidence.get("paths", []) if isinstance(path, str)}
                if paths:
                    item["files"] = len(paths)
                samples.append(item)
            sections.append(dict(category=category, count=len(members), places=samples,
                                 more=len(members) > len(samples)))
        output[identity] = dict(basis="published_direct_children", groups=sections,
                                total=sum(section["count"] for section in sections))
        if identity in descriptions:
            output[identity]["description_source"] = descriptions[identity]
    return output
