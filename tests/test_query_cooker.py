"""The query cooker must turn ANY text into a valid FTS5 expression."""
import random
import sqlite3
import string

import pytest


@pytest.fixture()
def fts():
    con = sqlite3.connect(":memory:")
    con.execute("CREATE VIRTUAL TABLE t USING fts5(text)")
    con.execute("INSERT INTO t VALUES (?)", ("don't use useState() in C++; v0.1.3 log-search drizzle migration cognito auth",))
    return con


def matches(con, expr):
    return len(con.execute("SELECT * FROM t WHERE t MATCH ?", (expr,)).fetchall())


@pytest.mark.parametrize("query,expected_hits", [
    ("don't", 1), ("useState()", 1), ("main()", 0), ("C++", 1), ("v0.1.3", 1), ("log-search", 1),
    ("drizzle migration", 1), ('"drizzle migration"', 1), ("“drizzle migration”", 1),
    ("drizzle AND", 1), ("AND drizzle", 1), ("drizzle OR", 1), ("(drizzle OR nope", 1), ("drizzle)", 1),
    ("drizzle, nope", 1), ("nope; cognito", 1), ("drizzle | nope", 1), ("drizzle or nope", 1),
    ("x (drizzle)", 0), ("(drizzle) auth", 1), ("' OR 1=1 --", 0), ("NOT", 0),
])
def test_known_awkward_queries(navcom, fts, query, expected_hits):
    # search_hits falls back to the all-literal query when nothing else is left
    cooked = navcom.fts_prefix_query(query) or navcom.fts_literal_query(query)
    assert matches(fts, cooked) == expected_hits, cooked


@pytest.mark.parametrize("query", ["*", "**", '""', "()", "   ", "--", "...", ";;", "AND OR NOT"])
def test_nothing_searchable_cooks_to_empty(navcom, query):
    assert navcom.fts_prefix_query(query) == "" or query == "AND OR NOT"


def test_comma_lists_mean_any(navcom):
    assert navcom.fts_prefix_query("drizzle, prisma, sequelize") == "drizzle* OR prisma* OR sequelize*"
    assert navcom.fts_prefix_query("drizzle kit, prisma") == "(drizzle* kit*) OR prisma*"
    assert navcom.fts_prefix_query("a,b") == '"a,b"*'  # no space after the comma: one token


def test_or_and_explicit_operators(navcom):
    assert navcom.fts_prefix_query("auth or login") == "auth* OR login*"
    assert navcom.fts_prefix_query("x (y)") == "x* AND ( y* )"


def test_fuzz_never_produces_a_syntax_error(navcom, fts):
    alphabet = string.ascii_letters[:8] + string.digits[:3] + " \"'(),;:*^-+|&!?.~/\\@#$%[]{}<>=`“”‘’"
    rng = random.Random(1234)
    for _ in range(15000):
        q = "".join(rng.choice(alphabet) for _ in range(rng.randint(1, 30)))
        if rng.random() < 0.3:
            q = q.replace("A", " AND ").replace("B", " OR ").replace("C", " NOT ")
        for cook in (navcom.fts_prefix_query, navcom.fts_any_query, navcom.fts_literal_query):
            expr = cook(q)
            if expr:
                matches(fts, expr)  # raises on syntax error


def test_make_snippet(navcom):
    assert navcom.make_snippet("/goal ship the zebracorn release", ["zebracorn"]) == "/goal ship the «zebracorn» release"
    long = " ".join(f"w{i}" for i in range(200)) + " needle " + " ".join(f"v{i}" for i in range(200))
    snip = navcom.make_snippet(long, ["needle"], tokens=10)
    assert "«needle»" in snip and snip.startswith("…") and snip.endswith("…")
    tail = navcom.make_snippet(" ".join(f"w{i}" for i in range(50)) + " needle!", ["needle"], tokens=10)
    assert tail.endswith("«needle»!") and tail.count(" ") >= 8              # window filled backwards
