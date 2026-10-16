"""The same procedural contract serves typing, voice, CLI and web callers."""

import pytest

from navcom_navigation_intent import interpret, retrieval_style


@pytest.mark.parametrize("text", ["back", "go back", " Back ", "GO BACK"])
def test_exact_back_commands(text):
    result = interpret(text, "planet:quartz")
    assert result["action"] == "back"
    assert result["query"] == ""
    assert result["within"] == "planet:quartz"
    assert result["engine"] == "procedural"
    assert "history" in result["steps"][0]


def test_home_and_global_scope():
    assert interpret("home", "district:auth")["within"] == ""
    assert interpret("home", "district:auth")["action"] == "home"
    result = interpret("find matrix", "moon:exp32", local=False)
    assert result["within"] == ""
    assert result["query"] == "matrix"
    assert result["steps"][0] == "Search across the galaxy."


@pytest.mark.parametrize("text,query", [
    ("take me to Cedar", "Cedar"),
    ("fly to v34 matrix", "v34 matrix"),
    ("OPEN EXP32", "EXP32"),
    ("open login & RBAC", "login & RBAC"),
])
def test_destination_is_unresolved_and_content_is_preserved(text, query):
    result = interpret(text, "system:cedar")
    assert result["action"] == "navigate"
    assert result["query"] == query
    assert result["within"] == "system:cedar"
    assert "Look for a destination" in result["steps"][0]
    assert "harvested code and documents" in result["steps"][1]
    assert "indexed conversations" in result["steps"][2]


@pytest.mark.parametrize("text,query", [
    ("find EXP32 Matrix", "EXP32 Matrix"),
    ("search for login  +  RBAC", "login  +  RBAC"),
    ("now search matrix", "matrix"),
    ("now search for v34", "v34"),
    ("search API/key", "API/key"),
])
def test_only_literal_search_prefix_is_removed(text, query):
    result = interpret(text, "moon:exp32")
    assert result["action"] == "search"
    assert result["query"] == query
    assert result["within"] == "moon:exp32"


@pytest.mark.parametrize("text", [
    "back propagation", "go back in time", "home automation", "reopen matrix",
    "how do I open a file", "find", "search for", "open", "take me to",
    "somewhere back in the experiment", "$(touch /tmp/nope)",
])
def test_ambiguous_words_remain_literal_searches(text):
    result = interpret(text, None)
    assert result["action"] == "search"
    assert result["query"] == text
    assert result["within"] == ""


def test_back_word_inside_search_does_not_become_navigation():
    result = interpret("find the word back", "planet:quartz")
    assert result["action"] == "search" and result["query"] == "the word back"


@pytest.mark.parametrize("text", ["", "   ", None, 42, "x" * 501])
def test_input_limits(text):
    with pytest.raises(ValueError):
        interpret(text, "")
    assert interpret("x" * 500, "")["query"] == "x" * 500


@pytest.mark.parametrize('text', ['Which products use Cognito for login?', 'Where were protocol goals discussed?', 'Compare authentication in Aurora and Radar', 'How does the marmot workflow operate?'])
def test_questions_opt_into_upstream_term_retrieval_without_rewriting_input(text):
    result=interpret(text,'system:coast')
    assert result['retrieval_style']=='question' and result['query']==text
    assert result['within']=='system:coast'


@pytest.mark.parametrize('text', ['login protocol', '"login protocol"', "Where is 'login protocol' documented?", 'where ./apps/login.py', 'where src/auth.ts', 'where config.yaml?', 'What does https://example.com do?', 'What is `AUTH_MODE`?'])
def test_literals_and_paths_never_become_term_alternatives(text):
    assert retrieval_style(text)=='literal'
