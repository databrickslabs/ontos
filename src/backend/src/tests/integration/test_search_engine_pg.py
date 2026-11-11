"""Engine detection, engine indexes and the pg_trgm typo fallback on real Postgres.

Runs against ``SEARCH_TEST_PG_URL`` (local Postgres or the CI pgvector service);
auto-skips without it. The Lakebase test additionally needs
``SEARCH_TEST_LAKEBASE_URL`` pointing at a Lakebase branch with Lakebase Search
enabled (manual / nightly).

Each connection pins ``search_path`` to a throwaway schema, like the app does,
so a pg_trgm installed in ``public`` is only reachable through the
schema-qualified names the engine generates.
"""
import os
import uuid
from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.common.search_config_loader import SearchConfigLoader
from src.common.search_interfaces import SearchIndexItem
from src.db_models.search_documents import SearchDocumentDb
from src.repositories import search_repository as repo
from src.repositories.search_engine import (
    TITLE_TRGM_INDEX,
    SearchEngineUnavailable,
    prepare_engine,
)
from src.tests.integration.test_search_settings_parity_pg import _YAML

_PG_URL = os.environ.get("SEARCH_TEST_PG_URL")
_LAKEBASE_URL = os.environ.get("SEARCH_TEST_LAKEBASE_URL")


def _schema_env(url):
    schema = f"search_eng_{uuid.uuid4().hex[:8]}"
    admin = create_engine(url, future=True)
    try:
        with admin.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    except Exception as e:  # pragma: no cover - environment dependent
        pytest.skip(f"Postgres not reachable: {e}")
    engine = create_engine(url, future=True, connect_args={"options": f"-csearch_path={schema}"})
    SearchDocumentDb.__table__.create(bind=engine)
    Session = sessionmaker(bind=engine, future=True)

    @contextmanager
    def factory():
        s = Session()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    def teardown():
        engine.dispose()
        with admin.begin() as conn:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin.dispose()

    return factory, teardown


@pytest.fixture()
def pg():
    if not _PG_URL:
        pytest.skip("SEARCH_TEST_PG_URL not set")
    factory, teardown = _schema_env(_PG_URL)
    try:
        yield factory
    finally:
        teardown()


def _item(id_, type_, feature_id, title, description="", extra=None):
    return SearchIndexItem(id=id_, type=type_, feature_id=feature_id, title=title,
                           description=description, link=f"/{id_}", tags=[], extra_data=extra or {})


ITEMS = [
    _item("product::1", "data-product", "data-products", "Customer Churn", extra={"status": "active"}),
    _item("product::2", "data-product", "data-products", "Customer 360", extra={"status": "draft"}),
    _item("contract::3", "data-contract", "data-contracts", "Orders Contract", extra={"status": "active"}),
    _item("team::4", "team", "teams", "Retention Squad"),
]


@pytest.fixture()
def seeded(pg):
    with pg() as db:
        repo.upsert_documents(db, ITEMS)
    return pg


@pytest.fixture()
def config():
    return SearchConfigLoader(config_path=_YAML).load(force_reload=True)


def test_auto_detects_pg_with_trigram_and_creates_index(pg):
    engine = prepare_engine(pg, "auto")
    assert engine.name == "pg"
    assert engine.has_trgm
    with pg() as db:
        idx = db.execute(text("SELECT indexdef FROM pg_indexes WHERE indexname = :n"),
                         {"n": TITLE_TRGM_INDEX}).scalar()
    assert idx and "gin_trgm_ops" in idx


def test_prepare_is_idempotent(pg):
    first = prepare_engine(pg, "auto")
    second = prepare_engine(pg, "auto")
    assert first == second


def test_explicit_lakebase_fails_fast_on_plain_postgres(pg):
    with pytest.raises(SearchEngineUnavailable, match="lakebase"):
        prepare_engine(pg, "lakebase")


def test_typo_falls_back_to_trigram(seeded, config):
    engine = prepare_engine(seeded, "auto")
    with seeded() as db:
        assert repo.search(db, "custmer", config=config)["total_count"] == 0  # no fallback without engine
        res = repo.search(db, "custmer", config=config, engine=engine)
    ids = [r["id"] for r in res["results"]]
    assert set(ids) == {"1", "2"} and res["total_count"] == 2
    assert all(0 < r["relevance_score"] <= 1 for r in res["results"])
    assert res["facets"]["type"] == {"data-product": 2}


def test_fallback_only_when_nothing_matches(seeded, config):
    """A query with lexical matches keeps the Settings-driven (parity) ranking."""
    engine = prepare_engine(seeded, "auto")
    with seeded() as db:
        with_engine = repo.search(db, "customer", config=config, engine=engine)
        without = repo.search(db, "customer", config=config)
    assert with_engine == without


def test_fallback_respects_filters_permissions_and_disabled_types(seeded, config):
    engine = prepare_engine(seeded, "auto")
    with seeded() as db:
        res = repo.search(db, "custmer", config=config, engine=engine, filters={"status": "active"})
        assert [r["id"] for r in res["results"]] == ["1"]
        res = repo.search(db, "orders contrct", config=config, engine=engine,
                          allowed_features=["data-products"])
        assert res["total_count"] == 0
        config.asset_types["data-contract"].enabled = False
        res = repo.search(db, "orders contrct", config=config, engine=engine)
        assert res["total_count"] == 0


def test_fallback_threshold_is_tunable(seeded, config):
    engine = prepare_engine(seeded, "auto")
    with seeded() as db:
        strict = repo.search(db, "custmer", config=config, engine=engine, trgm_threshold=0.9)
        loose = repo.search(db, "custmer", config=config, engine=engine, trgm_threshold=0.45)
    assert strict["total_count"] == 0 and loose["total_count"] == 2


def test_rest_path_uses_fallback(seeded, config):
    engine = prepare_engine(seeded, "auto")
    with seeded() as db:
        items = repo.search_index_items(db, "retenton", config=config, engine=engine)
    assert [i.id for i in items] == ["team::4"]


@pytest.mark.skipif(not _LAKEBASE_URL, reason="SEARCH_TEST_LAKEBASE_URL not set (Lakebase Search branch)")
def test_auto_detects_lakebase_on_lakebase_search_branch():
    factory, teardown = _schema_env(_LAKEBASE_URL)
    try:
        engine = prepare_engine(factory, "auto")
        assert engine.name == "lakebase"
        assert engine.has_trgm
    finally:
        teardown()
