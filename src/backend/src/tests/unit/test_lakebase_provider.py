"""Unit tests for LakebaseProvider.

Uses an in-memory SQLite engine so the tests exercise real SQLAlchemy
text() bindings (escaping, parameterisation) rather than a mocked
connection. SQLite's ``LIKE`` is case-insensitive by default for ASCII,
which matches the case-insensitive semantics we want from Postgres
``ILIKE`` for the search assertions here.
"""

import pytest
from sqlalchemy import create_engine, text

from src.controller.directory_providers import (
    DirectoryError,
    DirectoryProviderConfig,
    DirectoryProviderContext,
    LakebaseProvider,
)
from src.controller.directory_providers.lakebase_provider import _validate_fqn
from src.models.directory import PrincipalType


@pytest.fixture
def engine_with_principals():
    """Build an in-memory engine with a populated principals table."""

    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(
            text(
                'CREATE TABLE principals ('
                '"type" TEXT NOT NULL,'
                '"id" TEXT NOT NULL,'
                '"display_name" TEXT NOT NULL,'
                '"sub_label" TEXT'
                ')'
            )
        )
        conn.execute(
            text(
                'INSERT INTO principals (type, id, display_name, sub_label) '
                "VALUES "
                "('user', 'alice@example.com', 'Alice Liddell', 'alice@example.com'),"
                "('user', 'bob@example.com',   'Bob Builder',   'bob@example.com'),"
                "('user', 'amelia@example.com','Amelia Earhart','amelia@example.com'),"
                "('group', 'Producers', 'Data Producers', 'producers-guid'),"
                "('group', 'Stewards',  'Data Stewards',  'stewards-guid')"
            )
        )
    return engine


def _make_provider(engine, table: str = "principals") -> LakebaseProvider:
    return LakebaseProvider(
        DirectoryProviderContext(db_engine=engine),
        DirectoryProviderConfig(lakebase_table=table),
    )


class TestFqnValidation:
    def test_accepts_single_part(self):
        assert _validate_fqn("principals") == '"principals"'

    def test_accepts_three_parts(self):
        assert _validate_fqn("main.directory.principals") == \
            '"main"."directory"."principals"'

    def test_rejects_empty(self):
        with pytest.raises(DirectoryError):
            _validate_fqn("")

    def test_rejects_too_many_parts(self):
        with pytest.raises(DirectoryError):
            _validate_fqn("a.b.c.d")

    def test_rejects_sql_injection_attempt(self):
        # Hyphens, quotes, semicolons, spaces all rejected at the
        # identifier-segment level.
        for bad in (
            "principals; DROP TABLE principals",
            'evil"',
            "with-dash",
            "with space",
            "1starts_with_digit",
        ):
            with pytest.raises(DirectoryError):
                _validate_fqn(bad)


class TestSearch:
    def test_prefix_match_against_display_name(self, engine_with_principals):
        provider = _make_provider(engine_with_principals)
        results = provider.search_users("ali", top=20)
        ids = sorted(p.id for p in results)
        assert ids == ["alice@example.com"]

    def test_prefix_match_against_id(self, engine_with_principals):
        # ``bo`` matches Bob's id (bob@…) but not Amelia's display_name.
        provider = _make_provider(engine_with_principals)
        results = provider.search_users("bo", top=20)
        assert [p.id for p in results] == ["bob@example.com"]

    def test_returns_principal_with_full_shape(self, engine_with_principals):
        provider = _make_provider(engine_with_principals)
        p = provider.search_users("alice", top=20)[0]
        assert p.type == PrincipalType.USER
        assert p.id == "alice@example.com"
        assert p.display_name == "Alice Liddell"
        assert p.sub_label == "alice@example.com"

    def test_search_groups_filters_by_type(self, engine_with_principals):
        provider = _make_provider(engine_with_principals)
        groups = provider.search_groups("data", top=20)
        ids = sorted(p.id for p in groups)
        assert ids == ["Producers", "Stewards"]
        # All returned principals must be groups.
        assert {p.type for p in groups} == {PrincipalType.GROUP}

    def test_top_caps_results(self, engine_with_principals):
        provider = _make_provider(engine_with_principals)
        # All three users start with 'a' or 'b'; 'a' alone matches alice + amelia.
        results = provider.search_users("a", top=1)
        assert len(results) == 1

    def test_empty_query_short_circuits(self, engine_with_principals):
        provider = _make_provider(engine_with_principals)
        assert provider.search_users("", top=20) == []

    def test_wildcard_in_input_is_escaped(self, engine_with_principals):
        # Without escaping, '%' would expand to "match anything" and
        # this query would return rows. With escaping, the literal '%'
        # is sought and nothing matches.
        provider = _make_provider(engine_with_principals)
        assert provider.search_users("%", top=20) == []
        assert provider.search_users("_", top=20) == []


class TestGet:
    def test_get_user_returns_principal(self, engine_with_principals):
        provider = _make_provider(engine_with_principals)
        p = provider.get_user("alice@example.com")
        assert p.display_name == "Alice Liddell"

    def test_get_user_raises_when_missing(self, engine_with_principals):
        provider = _make_provider(engine_with_principals)
        with pytest.raises(DirectoryError, match="not found"):
            provider.get_user("nobody@example.com")

    def test_get_user_empty_id_raises(self, engine_with_principals):
        provider = _make_provider(engine_with_principals)
        with pytest.raises(DirectoryError):
            provider.get_user("")


class TestProbe:
    def test_test_succeeds_when_table_exists(self, engine_with_principals):
        provider = _make_provider(engine_with_principals)
        provider.test()  # no exception

    def test_test_fails_when_table_absent(self):
        engine = create_engine("sqlite:///:memory:")
        provider = _make_provider(engine, table="missing_table")
        with pytest.raises(DirectoryError, match="failed"):
            provider.test()


class TestConstruction:
    def test_requires_db_engine(self):
        with pytest.raises(DirectoryError, match="engine"):
            LakebaseProvider(
                DirectoryProviderContext(),
                DirectoryProviderConfig(lakebase_table="principals"),
            )

    def test_requires_table_name(self, engine_with_principals):
        with pytest.raises(DirectoryError, match="required"):
            LakebaseProvider(
                DirectoryProviderContext(db_engine=engine_with_principals),
                DirectoryProviderConfig(lakebase_table=""),
            )
