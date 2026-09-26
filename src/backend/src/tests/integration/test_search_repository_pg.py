"""Local-Postgres integration test for the DB-backed search repository.

The main unit suite runs on in-memory SQLite, which cannot execute Postgres
full-text search (`to_tsvector`, `websearch_to_tsquery`, `ts_rank_cd`, GIN,
generated columns). This module exercises the real SQL against a Postgres
database and **auto-skips** when none is reachable, so it is safe in CI.

To run it, point it at a throwaway Postgres (e.g. a Lakebase branch or a local
container) via ``SEARCH_TEST_PG_URL``::

    SEARCH_TEST_PG_URL=postgresql+psycopg2://user:pw@localhost:5432/postgres \
        hatch -e dev run pytest src/tests/integration/test_search_repository_pg.py
"""
import os
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.common.search_interfaces import SearchIndexItem
from src.db_models.search_documents import SearchDocumentDb
from src.repositories import search_repository as repo

_PG_URL = os.environ.get("SEARCH_TEST_PG_URL")


def _engine_or_skip():
    if not _PG_URL:
        pytest.skip("SEARCH_TEST_PG_URL not set — Postgres FTS integration test skipped")
    try:
        eng = create_engine(_PG_URL, future=True)
        with eng.connect() as c:
            c.execute(text("SELECT 1"))
        return eng
    except Exception as e:  # pragma: no cover - environment dependent
        pytest.skip(f"Postgres not reachable at SEARCH_TEST_PG_URL: {e}")


@pytest.fixture()
def pg_session():
    """A session against a freshly created search_documents table in a temp schema."""
    engine = _engine_or_skip()
    schema = f"search_it_{uuid.uuid4().hex[:8]}"
    with engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        conn.execute(text(f'SET search_path TO "{schema}"'))
    # Create the table (+ tsvector/GIN via the model's after_create DDL) in the schema.
    creator = create_engine(_PG_URL, future=True, execution_options={"schema_translate_map": {None: schema}})
    SearchDocumentDb.__table__.create(bind=creator)
    Session = sessionmaker(bind=creator, future=True)
    db = Session()
    db.execute(text(f'SET search_path TO "{schema}"'))
    try:
        yield db
    finally:
        db.close()
        with engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))


def _item(id_, type_, feature_id, title, description="", tags=None, extra=None):
    return SearchIndexItem(
        id=id_, type=type_, feature_id=feature_id, title=title,
        description=description, link=f"/{type_}/{id_}", tags=tags or [], extra_data=extra or {},
    )


@pytest.fixture()
def seeded(pg_session):
    repo.upsert_documents(pg_session, [
        _item("product::1", "data-product", "data-products", "Customer Churn",
              "Predicts customer churn risk", tags=["ml"],
              extra={"status": "active", "domain": "Customer", "domains": ["Customer", "Sales"], "version": "1.2.0"}),
        _item("product::2", "data-product", "data-products", "Sales Transactions",
              "Daily sales facts", tags=["finance"], extra={"status": "draft", "domain": "Sales", "domains": ["Sales"]}),
        _item("contract::3", "data-contract", "data-contracts", "Orders Contract",
              "Contract for order events", tags=["orders"], extra={"status": "active", "domain": "Sales"}),
    ])
    pg_session.flush()
    return pg_session


def test_fulltext_multiword_query(seeded):
    out = repo.search(seeded, "customer churn")
    assert out["total_count"] >= 1
    assert out["results"][0]["title"] == "Customer Churn"
    assert out["results"][0]["version"] == "1.2.0"  # surfaced from extra_data


def test_type_filter_and_pagination(seeded):
    out = repo.search(seeded, "*", type_filter="data-product", limit=1, offset=0)
    assert out["total_count"] == 2
    assert out["returned"] == 1
    assert out["has_more"] is True
    assert all(r["type"] == "data-product" for r in out["results"])


def test_domains_filter_matches_any_assigned(seeded):
    out = repo.search(seeded, "*", filters={"domains": "sales"})
    ids = sorted(r["id"] for r in out["results"])
    assert ids == ["1", "2"]  # both products carry an assigned 'Sales' domain


def test_status_filter_exact(seeded):
    out = repo.search(seeded, "*", filters={"status": "active"})
    assert out["total_count"] == 2  # product::1 + contract::3


def test_permission_filter_by_feature(seeded):
    out = repo.search(seeded, "*", allowed_features=["data-products"])
    assert out["total_count"] == 2
    assert all(r["feature_id"] == "data-products" for r in out["results"])


def test_facets(seeded):
    out = repo.search(seeded, "*")
    assert out["facets"]["type"]["data-product"] == 2
    assert out["facets"]["status"]["active"] == 2
