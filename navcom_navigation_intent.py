"""Shared, deterministic interpretation of typed and transcribed navigation.

Returned steps describe a plan. This module does not search, resolve an entity,
invoke a model, execute commands, or claim that navigation has occurred.
"""

import re


MAX_INPUT = 500
_DESTINATION = re.compile(r"^(?:take me to|fly to|open)\s+(.+)$", re.IGNORECASE | re.DOTALL)
_SEARCH = re.compile(r"^(?:find|search for|search|now search for|now search)\s+(.+)$", re.IGNORECASE | re.DOTALL)
_QUESTION = re.compile(r"^(?:how|what|where|which|why|who|when|compare)\b", re.IGNORECASE)
_PATH = re.compile(r"(?:^|\s)(?:[a-zA-Z][\w+.-]*://[^\s]+|(?:~?/|\.{1,2}/|[\w.-]+/)[^\s]+|[\w.-]+\.[\w]{1,12}(?=\s|$|[?]))")
_SCOPED_SEARCH = re.compile(r"^(?:find|search for|search|now search for|now search)\s+(.+?)\s+(?:in|within)\s+(.+)$", re.IGNORECASE | re.DOTALL)
_TRAVEL_SEARCH = re.compile(r"^(?:take me to|fly to|open)\s+(.+?)(?:\s*,\s*|\s+)(?:then|and)\s+(?:find|search for|search)\s+(.+)$", re.IGNORECASE | re.DOTALL)


def _command_tail(phrase):
    """Accept one sentence terminator on plain command words, not literal syntax.

    Quotes, paths, dotted/underscored names, operators and ellipses do not match.
    Only callers that already recognized a command may use this normalization.
    """
    phrase=phrase.strip()
    if phrase.endswith(('.', '!', '?')):
        words=phrase[:-1].rstrip()
        if re.fullmatch(r'[^\W_]+(?:[\s-]+[^\W_]+)*',words):
            return words
    return phrase


def retrieval_style(query):
    """Only explicit question grammar opts into upstream term decomposition.

    Quoted text, paths and ordinary keyword searches keep their literal contract.
    This classifies syntax, not domains, clients, products or guessed intent.
    """
    if any(mark in query for mark in ('"', "'", "`")) or _PATH.search(query):
        return "literal"
    return "question" if _QUESTION.match(query) else "literal"


def interpret(text, within, local=True):
    """Return a navigation/search plan without changing query vocabulary.

    ``within`` is an existing opaque place identifier. ``local=False`` clears it
    so the caller can search globally. Only complete back/home commands navigate
    directly; destination phrases remain unresolved queries for the shared API.
    """
    if not isinstance(text, str):
        raise ValueError("Navigation input must be text")
    if len(text) > MAX_INPUT:
        raise ValueError("Navigation input must be 500 characters or fewer")
    command = text.strip()
    if not command:
        raise ValueError("Enter a destination or something to search for")
    scope = (within or "") if local else ""
    normalized = command.casefold()
    result = {"action": "search", "query": command, "within": scope,
              "steps": [], "engine": "procedural"}
    control=_command_tail(command).casefold()
    if control in ("back", "go back"):
        result.update(action="back", query="", steps=["Return to the previous view using navigation history."])
        return result
    if control == "home":
        result.update(action="home", query="", within="", steps=["Return to the galaxy overview."])
        return result
    # These are command clauses, not a product classifier. Resolve the named
    # place against the actual catalog before searching; quoted/path input keeps
    # its existing literal behavior rather than being split at an embedded word.
    clause_safe = not any(mark in command for mark in ('"', "'", "`")) and not _PATH.search(command)
    travel_search = _TRAVEL_SEARCH.fullmatch(command) if clause_safe else None
    scoped_search = _SCOPED_SEARCH.fullmatch(command) if clause_safe else None
    if travel_search or scoped_search:
        match = travel_search or scoped_search
        place, query = (match.group(1), match.group(2)) if travel_search else (match.group(2), match.group(1))
        # Only the final clause carries sentence-ending punctuation. Interior
        # punctuation remains part of its destination/query text.
        place,query=place.strip(),query.strip()
        if travel_search:query=_command_tail(query)
        else:place=_command_tail(place)
        result.update(query=query.strip(), scope_query=place.strip(), navigate_first=bool(travel_search),
                      retrieval_style=retrieval_style(query.strip()), steps=[
                          f'Resolve the named place "{place.strip()}" inside the allowed chart scope.',
                          'Search its saved code, documents and conversations after the place is resolved.',
                      ])
        return result
    destination = _DESTINATION.fullmatch(command)
    if destination:
        query = _command_tail(destination.group(1))
        result.update(action="navigate", query=query)
        first = f'Look for a destination named "{query}" in the cached galactic map.'
    else:
        search = None if normalized in ("search for", "now search for") else _SEARCH.fullmatch(command)
        if search:
            result["query"] = _command_tail(search.group(1))
        first = (f'Search within the current place "{scope}".' if scope
                 else "Search across the galaxy.")
    query = result["query"]
    result["retrieval_style"] = retrieval_style(query) if result["action"] == "search" else "literal"
    result["steps"] = [
        first,
        f'Look for "{query}" in harvested code and documents' + (" within this place." if scope else "."),
        f'Look for "{query}" in indexed conversations' + (" within this place." if scope else "."),
    ]
    return result
