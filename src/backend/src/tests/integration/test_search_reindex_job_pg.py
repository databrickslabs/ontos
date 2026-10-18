"""The search_index_reindex workflow (#1059) against real Postgres / Lakebase.

``run_reindex`` is the job's whole logic (``main`` only adds the Lakebase OAuth
connection), so the tests drive it with an engine on a throwaway schema.
``SEARCH_TEST_PG_URL`` covers the pg engine (CI); ``SEARCH_TEST_LAKEBASE_URL``
covers BM25 rebuilds on a Lakebase Search branch (manual / nightly).
"""
import importlib.util
import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from src.common.search_config_loader import SearchConfigLoader
from src.common.search_interfaces import SearchIndexItem
from src.repositories import search_repository as repo
from src.repositories.search_engine import BM25_INDEXES, prepare_engine
from src.tests.integration.test_search_engine_pg import _schema_env
from src.tests.integration.test_search_settings_parity_pg import _YAML, ITEMS

_PG_URL = os.environ.get("SEARCH_TEST_PG_URL")
_LAKEBASE_URL = os.environ.get("SEARCH_TEST_LAKEBASE_URL")

_JOB = Path(__file__).resolve().parents[2] / "workflows" / "search_index_reindex" / "search_index_reindex.py"
_spec = importlib.util.spec_from_file_location("search_index_reindex", _JOB)
job = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(job)


def _env(url):
    factory, teardown = _schema_env(url)
    with factory() as db:
        schema = db.execute(text("SELECT current_schema()")).scalar()
    engine = create_engine(url, future=True, connect_args={"options": f"-csearch_path={schema}"})
    return factory, schema, engine, teardown


@pytest.fixture()
def pg():
    if not _PG_URL:
        pytest.skip("SEARCH_TEST_PG_URL not set")
    factory, schema, engine, teardown = _env(_PG_URL)
    try:
        prepare_engine(factory, "pg")  # trigram index
        with factory() as db:
            repo.upsert_documents(db, ITEMS)
        yield schema, engine
    finally:
        engine.dispose()
        teardown()


def test_pg_engine_has_nothing_stale_by_default(pg):
    schema, engine = pg
    summary = job.run_reindex(engine, schema)
    assert summary["engine"] == "pg" and summary["rows"] == len(ITEMS)
    assert summary["reindexed"] == {} and summary["failed"] == []
    assert summary["analyze_seconds"] >= 0 and summary["total_seconds"] >= summary["analyze_seconds"]


def test_reindex_all_rebuilds_every_search_index_except_the_primary_key(pg):
    schema, engine = pg
    summary = job.run_reindex(engine, schema, reindex_all=True)
    assert summary["failed"] == []
    assert "ix_search_documents_title_trgm" in summary["reindexed"]
    assert "ix_search_documents_type" in summary["reindexed"]
    assert not any(n.endswith("_pkey") for n in summary["reindexed"])
    assert all(t is not None for t in summary["reindexed"].values())


def test_missing_table_is_a_clear_error():
    if not _PG_URL:
        pytest.skip("SEARCH_TEST_PG_URL not set")
    engine = create_engine(_PG_URL, future=True)
    try:
        with pytest.raises(RuntimeError, match="SEARCH_BACKEND=postgres"):
            job.run_reindex(engine, "no_such_schema_for_search")
    finally:
        engine.dispose()


@pytest.mark.skipif(not _LAKEBASE_URL, reason="SEARCH_TEST_LAKEBASE_URL not set (Lakebase Search branch)")
def test_lakebase_job_rebuilds_bm25_and_fixes_stale_scores():
    factory, schema, engine, teardown = _env(_LAKEBASE_URL)
    try:
        search_engine = prepare_engine(factory, "auto")
        config = SearchConfigLoader(config_path=_YAML).load(force_reload=True)
        with factory() as db:
            repo.upsert_documents(db, ITEMS)
        job.run_reindex(engine, schema)  # indexes were built on the empty table

        def score():
            with factory() as db:
                return dict(repo.bm25_rank(db, "churn", config=config, engine=search_engine, limit=1000))["product::1"]

        before = score()
        with factory() as db:
            repo.upsert_documents(db, [
                SearchIndexItem(id=f"product::bulk{n}", type="data-product", feature_id="data-products",
                                title=f"Churn report {n}", description="churn", link="/", tags=[], extra_data={})
                for n in range(300)
            ])
        stale = score()
        summary = job.run_reindex(engine, schema)
        fresh = score()

        assert summary["engine"] == "lakebase" and summary["rows"] == len(ITEMS) + 300
        assert set(summary["reindexed"]) == set(BM25_INDEXES.values()) and summary["failed"] == []
        assert stale == pytest.approx(before, rel=1e-6) and fresh < before
    finally:
        engine.dispose()
        teardown()
