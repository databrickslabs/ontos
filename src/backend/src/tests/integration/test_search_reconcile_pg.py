"""DB-backed search as the deployed default (#1058) on real Postgres.

Covers the background reconcile (first-boot backfill, stale-row sweep, partial
runs, one-replica-at-a-time lock), several replicas sharing one index, bulk
type replacement (glossary), and memory-vs-Postgres equality through the
SearchManager entry points (MCP ``query_index`` and REST ``search``).

Runs against ``SEARCH_TEST_PG_URL``; auto-skips without it.
"""
import os
import uuid
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.common.search_config_loader import SearchConfigLoader
from src.common.search_interfaces import SearchableAsset, SearchIndexItem
from src.controller import search_manager as search_manager_module
from src.controller.search_backend import InMemoryBackend, PostgresBackend
from src.controller.search_manager import SearchManager
from src.db_models.search_documents import SearchDocumentDb
from src.models.users import UserInfo
from src.repositories import search_repository as repo
from src.tests.integration.test_search_settings_parity_pg import _YAML, ITEMS

_PG_URL = os.environ.get("SEARCH_TEST_PG_URL")


@pytest.fixture()
def pg():
    """A session factory on a throwaway schema (pinned search_path, like the app)."""
    if not _PG_URL:
        pytest.skip("SEARCH_TEST_PG_URL not set")
    schema = f"search_rec_{uuid.uuid4().hex[:8]}"
    admin = create_engine(_PG_URL, future=True)
    try:
        with admin.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    except Exception as e:  # pragma: no cover - environment dependent
        pytest.skip(f"Postgres not reachable: {e}")
    engines = []

    def make_factory():
        engine = create_engine(_PG_URL, future=True, connect_args={"options": f"-csearch_path={schema}"})
        engines.append(engine)
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
        return factory

    first = make_factory()
    SearchDocumentDb.__table__.create(bind=engines[0])
    first.make_factory = make_factory  # a second "replica" connects with its own engine
    try:
        yield first
    finally:
        for e in engines:
            e.dispose()
        with admin.begin() as conn:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin.dispose()


class _Source(SearchableAsset):
    def __init__(self, items, fail=False):
        self.items = list(items)
        self.fail = fail

    def get_search_index_items(self):
        if self.fail:
            raise RuntimeError("manager down")
        return list(self.items)


def _ids(factory):
    with factory() as db:
        return {r[0] for r in db.execute(text("SELECT id FROM search_documents"))}


def _backend(factory):
    config = SearchConfigLoader(config_path=_YAML).load(force_reload=True)
    return PostgresBackend(factory, config_provider=lambda: config)


def _indexable(item):
    return bool(item.feature_id)


PRODUCTS, OTHERS = ITEMS[:3], ITEMS[3:]


# --------------------------------------------------------------- reconcile

def test_reconcile_backfills_empty_table_in_batches(pg):
    backend = _backend(pg)
    stats = backend.reconcile(
        [("Products", lambda: PRODUCTS), ("Others", lambda: OTHERS)],
        is_indexable=_indexable, batch_size=2,
    )
    assert stats["status"] == "done"
    assert stats["upserted"] == len(ITEMS) and stats["removed"] == 0
    assert _ids(pg) == {i.id for i in ITEMS}


def test_reconcile_sweeps_rows_of_deleted_entities(pg):
    backend = _backend(pg)
    with pg() as db:
        repo.upsert_documents(db, ITEMS)
    survivors = [i for i in ITEMS if i.id != "product::2"]
    stats = backend.reconcile([("All", lambda: survivors)], is_indexable=_indexable)
    assert stats["removed"] == 1
    assert "product::2" not in _ids(pg)


def test_failed_source_skips_the_sweep(pg):
    backend = _backend(pg)
    with pg() as db:
        repo.upsert_documents(db, ITEMS)

    def broken():
        raise RuntimeError("down")

    stats = backend.reconcile(
        [("Products", lambda: PRODUCTS), ("Broken", broken)], is_indexable=_indexable,
    )
    assert stats["status"] == "partial" and stats["failed_sources"] == ["Broken"]
    assert stats["removed"] == 0
    assert _ids(pg) == {i.id for i in ITEMS}  # nothing wiped because of the broken source


def test_only_one_replica_reconciles_at_a_time(pg):
    with pg() as holder:
        assert repo.try_reconcile_lock(holder)
        try:
            stats = _backend(pg).reconcile([("All", lambda: ITEMS)], is_indexable=_indexable)
            assert stats["status"] == "skipped"
            assert _ids(pg) == set()
        finally:
            repo.release_reconcile_lock(holder)
    assert _backend(pg).reconcile([("All", lambda: ITEMS)], is_indexable=_indexable)["status"] == "done"


def test_replace_type_swaps_only_that_type(pg):
    backend = _backend(pg)
    with pg() as db:
        repo.upsert_documents(db, ITEMS)
    term = SearchIndexItem(id="glossary-term::new", type="glossary-term", feature_id="semantic-models",
                           title="Net Revenue", description="", link="/c", tags=[], extra_data={})
    backend.replace_type("glossary-term", [term])
    ids = _ids(pg)
    assert "glossary::6" not in ids and "glossary-term::new" in ids
    assert {i.id for i in ITEMS if i.type != "glossary-term"} <= ids


# ---------------------------------------------------------- multi-replica

def test_replicas_share_one_index(pg):
    """Writes through one app instance are visible to another immediately."""
    replica_a, replica_b = _backend(pg), _backend(pg.make_factory())
    item = SearchIndexItem(id="product::77", type="data-product", feature_id="data-products",
                           title="Replica Shared Product", description="", link="/p", tags=[],
                           extra_data={"status": "draft"})
    replica_a.upsert([item])
    assert [r["id"] for r in replica_b.search("replica shared")["results"]] == ["77"]
    replica_a.upsert([item.model_copy(update={"extra_data": {"status": "active"}})])
    assert replica_b.search("replica shared")["results"][0]["status"] == "active"
    replica_a.remove(item.id)
    assert replica_b.search("replica shared")["total_count"] == 0


# ------------------------------------------- SearchManager on the DB backend

@pytest.fixture()
def pg_manager_factory(pg, monkeypatch):
    """Build SearchManagers whose backend is chosen like in the app."""
    config_loader = SearchConfigLoader(config_path=_YAML)

    def build(backend_name, sources, wait_seconds=30.0):
        settings = SimpleNamespace(
            SEARCH_BACKEND=backend_name, SEARCH_ENGINE="pg", SEARCH_TRGM_THRESHOLD=0.45,
            SEARCH_BACKFILL_WAIT_SECONDS=wait_seconds, SEARCH_BACKFILL_BATCH_SIZE=3,
        )
        monkeypatch.setattr("src.common.config.get_settings", lambda: settings)

        def create_backend(manager, name, engine_name="auto", trgm_threshold=0.45):
            if name == "postgres":
                return PostgresBackend(pg, config_provider=lambda: manager.config,
                                       engine_name=engine_name, trgm_threshold=trgm_threshold)
            return InMemoryBackend(manager)

        monkeypatch.setattr(search_manager_module, "create_backend", create_backend)
        return SearchManager(searchable_managers=sources, config_loader=config_loader)
    return build


def test_postgres_manager_backfills_without_an_in_memory_index(pg, pg_manager_factory):
    mgr = pg_manager_factory("postgres", [_Source(PRODUCTS), _Source(OTHERS)])
    # Empty table on first boot: startup waited for the backfill.
    assert mgr.wait_for_reconcile(timeout=30)
    assert mgr.index == []
    assert mgr.last_reconcile["status"] == "done"
    assert _ids(pg) == {i.id for i in ITEMS}


def test_rebuild_reconciles_in_the_background_and_rollback_to_memory_works(pg, pg_manager_factory):
    source = _Source(ITEMS)
    mgr = pg_manager_factory("postgres", [source])
    mgr.wait_for_reconcile(timeout=30)
    source.items = [i for i in ITEMS if i.id != "contract::4"]
    mgr.build_index()  # e.g. POST /api/search/rebuild-index
    mgr.wait_for_reconcile(timeout=30)
    assert "contract::4" not in _ids(pg)

    # Rollback switch: the memory backend rebuilds its index from the managers.
    mem = pg_manager_factory("memory", [source])
    assert {i.id for i in mem.index} == {i.id for i in source.items}


def test_incremental_lifecycle_without_restart(pg, pg_manager_factory):
    mgr = pg_manager_factory("postgres", [_Source([])])
    mgr.wait_for_reconcile(timeout=30)
    item = SearchIndexItem(id="product::90", type="data-product", feature_id="data-products",
                           title="Lifecycle Product", description="first", link="/p", tags=[],
                           extra_data={"status": "draft"})
    mgr.upsert_item(item)                                               # create
    assert mgr.query_index("lifecycle")["results"][0]["status"] == "draft"
    mgr.upsert_item(item.model_copy(update={"description": "second"}))  # update
    assert mgr.query_index("lifecycle")["results"][0]["description"] == "second"
    mgr.upsert_item(item.model_copy(update={"extra_data": {"status": "active"}}))  # status transition
    assert mgr.query_index("lifecycle")["results"][0]["status"] == "active"
    mgr.remove_item(item.id)                                            # delete
    assert mgr.query_index("lifecycle")["total_count"] == 0


class _AllowAll:
    def get_user_effective_permissions(self, groups, override=None):
        return {}

    def has_permission(self, perms, feature_id, level):
        return True


_USER = UserInfo(email="a@x", username="a", user="a", ip="127.0.0.1", groups=["users"])


@pytest.mark.parametrize("query", ["customer", "sales orders", "churn", "*", "zzz-no-match"])
def test_memory_and_postgres_return_the_same_shapes(pg, pg_manager_factory, query):
    """Contract test: MCP (query_index) and REST (search) answer identically on both backends."""
    mem = pg_manager_factory("memory", [_Source(ITEMS)])
    db = pg_manager_factory("postgres", [_Source(ITEMS)])
    db.wait_for_reconcile(timeout=30)

    assert db.query_index(query, limit=100) == mem.query_index(query, limit=100)
    assert db.query_index(query, limit=2, offset=1, include_facets=False, fields=["title"]) == \
        mem.query_index(query, limit=2, offset=1, include_facets=False, fields=["title"])
    rest_mem = mem.search(query, _AllowAll(), _USER)
    rest_db = db.search(query, _AllowAll(), _USER)
    assert [i.model_dump() for i in rest_db] == [i.model_dump() for i in rest_mem]
