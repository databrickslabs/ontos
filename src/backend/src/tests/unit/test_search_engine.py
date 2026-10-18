"""Unit tests for search engine selection (no database needed)."""
import pytest

from src.repositories.search_engine import SearchEngineUnavailable, choose_engine

LAKEBASE = {"lakebase_text", "lakebase_vector"}


@pytest.mark.parametrize("installed, expected", [
    (set(), "pg"),
    ({"pg_trgm"}, "pg"),
    ({"pg_trgm", "vector"}, "pg"),
    ({"lakebase_text"}, "pg"),            # half of Lakebase Search isn't enough
    (LAKEBASE, "lakebase"),
    (LAKEBASE | {"pg_trgm", "vector"}, "lakebase"),
])
def test_auto_picks_lakebase_only_with_both_extensions(installed, expected):
    assert choose_engine("auto", installed).name == expected


def test_explicit_pg_ignores_lakebase_extensions():
    assert choose_engine("pg", LAKEBASE).name == "pg"


def test_explicit_lakebase_without_extensions_fails_with_missing_list():
    with pytest.raises(SearchEngineUnavailable, match="lakebase_vector"):
        choose_engine("lakebase", {"lakebase_text"})


def test_explicit_lakebase_with_extensions():
    assert choose_engine("LakeBase", LAKEBASE).name == "lakebase"


def test_unknown_engine_name_is_rejected():
    with pytest.raises(SearchEngineUnavailable, match="not one of"):
        choose_engine("elastic", set())


def test_trgm_objects_are_schema_qualified_and_quoted():
    """The app pins search_path to its own schema, so pg_trgm living in another
    schema must be referenced explicitly; the schema name comes from the
    catalog and is quoted as an identifier."""
    e = choose_engine("auto", {"pg_trgm"}, {"pg_trgm": 'we"ird'})
    assert e.has_trgm
    assert e.trgm("word_similarity") == '"we""ird".word_similarity'
    assert e.trgm_op("<%") == 'OPERATOR("we""ird".<%)'


def test_unqualified_when_schema_unknown():
    e = choose_engine("auto", {"pg_trgm"})
    assert e.trgm("gin_trgm_ops") == "gin_trgm_ops"
    assert e.trgm_op("<%") == "<%"


# --- BM25 (lakebase_text, #1059) ---------------------------------------------

def test_bm25_only_on_the_lakebase_engine():
    assert choose_engine("auto", LAKEBASE).has_bm25
    assert not choose_engine("pg", LAKEBASE).has_bm25          # pinned pg ignores BM25
    assert not choose_engine("auto", {"pg_trgm"}).has_bm25


def test_bm25_objects_are_schema_qualified():
    eng = choose_engine("auto", LAKEBASE, {"lakebase_text": "public"})
    assert eng.bm25("to_bm25query") == '"public".to_bm25query'
    assert eng.bm25_op() == 'OPERATOR("public".<@>)'
    bare = choose_engine("auto", LAKEBASE)
    assert bare.bm25("to_bm25query") == "to_bm25query" and bare.bm25_op() == "<@>"


@pytest.mark.parametrize("requested, creates_lakebase", [("auto", True), ("lakebase", True), ("pg", False)])
def test_prepare_creates_lakebase_extensions_only_when_they_may_be_used(monkeypatch, requested, creates_lakebase):
    from src.repositories import search_engine as se

    available = {"pg_trgm", "lakebase_text", "lakebase_vector"}
    installed = {}
    ddl = []

    def fake_ddl(_factory, sql, _what):
        ddl.append(sql)
        installed[sql.split()[5]] = "public"

    monkeypatch.setattr(se, "_available", lambda db: available)
    monkeypatch.setattr(se, "_installed", lambda db: dict(installed))
    monkeypatch.setattr(se, "_try_ddl", fake_ddl)
    monkeypatch.setattr(se, "ensure_search_indexes", lambda f, e: None)

    class _Ctx:
        def __enter__(self):
            return None

        def __exit__(self, *a):
            return False

    se.prepare_engine(lambda: _Ctx(), requested)
    assert all(s.endswith(" CASCADE") for s in ddl)
    created = {s.split()[5] for s in ddl}
    assert "pg_trgm" in created
    assert ({"lakebase_text", "lakebase_vector"} <= created) == creates_lakebase
