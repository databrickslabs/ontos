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
