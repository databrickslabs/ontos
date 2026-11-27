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


@pytest.mark.parametrize("value", [0, -0.1, 1.01, 2])
def test_trgm_threshold_must_be_in_zero_to_one(value):
    from pydantic import ValidationError
    from src.common.config import Settings
    with pytest.raises(ValidationError, match="SEARCH_TRGM_THRESHOLD"):
        Settings(_env_file=None, SEARCH_TRGM_THRESHOLD=value)


@pytest.mark.parametrize("value", [0.01, 0.45, 1.0])
def test_trgm_threshold_accepts_the_useful_range(value):
    from src.common.config import Settings
    assert Settings(_env_file=None, SEARCH_TRGM_THRESHOLD=value).SEARCH_TRGM_THRESHOLD == value


def test_refused_create_extension_leaves_fallback_off():
    """pg_trgm is listed as available but CREATE EXTENSION is refused: prepare_engine
    logs and continues, the engine runs without the typo fallback, and no trigram
    index DDL is attempted."""
    from src.repositories.search_engine import prepare_engine

    statements = []

    class _Db:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, stmt, *args, **kwargs):
            sql = str(stmt)
            statements.append(sql)
            if sql.startswith("CREATE EXTENSION"):
                raise PermissionError("permission denied to create extension \"pg_trgm\"")
            if "pg_available_extensions" in sql:
                return iter([("pg_trgm",)])
            return iter([])

        def commit(self):
            pass

    engine = prepare_engine(lambda: _Db(), "auto")

    assert engine.name == "pg"
    assert not engine.has_trgm
    assert any(s.startswith("CREATE EXTENSION") for s in statements)
    assert not any("gin_trgm_ops" in s for s in statements)
