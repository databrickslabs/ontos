"""Semantic search: embedding columns, ANN index, background embedding, vector ranking (#1060).

- ``SEARCH_TEST_PG_URL`` with pgvector (the CI ``pgvector/pgvector:pg17`` service;
  skipped where ``vector`` isn't available): HNSW path with a deterministic
  concept-based fake embedder, so "a zero-lexical-overlap query finds the right
  item" is testable without a model.
- ``SEARCH_TEST_LAKEBASE_URL``: the same on Lakebase Search (``lakebase_ann``).
- ``SEARCH_TEST_EMBEDDING_PROFILE`` (+ optional ``SEARCH_TEST_EMBEDDING_ENDPOINT``,
  default ``databricks-gte-large-en``): the real Databricks embedding endpoint.
"""
import math
import os
import re

import pytest
from sqlalchemy import text

from src.common.search_config_loader import SearchConfigLoader
from src.common.search_embeddings import EmbeddingInputRejected, EmbeddingStats, QueryEmbeddingCache
from src.common.search_interfaces import SearchIndexItem
from src.controller.search_backend import PostgresBackend
from src.controller.search_embedding_worker import EmbeddingWorker
from src.repositories import search_repository as repo
from src.repositories.search_engine import EMBEDDING_INDEXES, prepare_engine
from src.tests.integration.test_search_engine_pg import _schema_env
from src.tests.integration.test_search_settings_parity_pg import _YAML, ITEMS

_PG_URL = os.environ.get("SEARCH_TEST_PG_URL")
_LAKEBASE_URL = os.environ.get("SEARCH_TEST_LAKEBASE_URL")
_EMBED_PROFILE = os.environ.get("SEARCH_TEST_EMBEDDING_PROFILE")

# Concept axes: synonyms share an axis, so related wording lands close together
# without any shared token ("client attrition" ~ "Customer Churn").
_CONCEPTS = {
    "customer": 0, "customers": 0, "client": 0, "clients": 0, "consumer": 0,
    "churn": 1, "attrition": 1, "retention": 1, "leaving": 1,
    "sales": 2, "revenue": 2, "transactions": 2, "income": 2,
    "order": 3, "orders": 3, "purchase": 3, "purchases": 3,
    "contract": 4, "agreement": 4,
    "team": 5, "squad": 5, "crew": 5,
    "value": 6, "lifetime": 6, "worth": 6,
    "profile": 7, "360": 7, "unified": 7,
}
DIM = len(set(_CONCEPTS.values()))


class ConceptEmbedder:
    dim = DIM

    def __init__(self, fail_after_calls=None, endpoint="concepts-v1", reject=None, on_embed=None):
        self.stats = EmbeddingStats()
        self.fail_after_calls = fail_after_calls
        self.endpoint = endpoint
        self.reject = reject          # texts containing this word get a 400
        self.on_embed = on_embed      # side effect while the "endpoint call" runs

    def embed(self, texts):
        if self.fail_after_calls is not None and self.stats.calls >= self.fail_after_calls:
            self.stats.add(calls=1, errors=1)
            raise RuntimeError("endpoint unavailable")
        if self.reject and any(self.reject in t for t in texts):
            self.stats.add(calls=1, errors=1)
            raise EmbeddingInputRejected("input too long")
        if self.on_embed:
            self.on_embed()
        out = []
        for t in texts:
            v = [0.0] * DIM
            for w in re.findall(r"\w+", t.lower()):
                if w in _CONCEPTS:
                    v[_CONCEPTS[w]] += 1.0
            norm = math.sqrt(sum(x * x for x in v)) or 1.0
            out.append([x / norm if any(v) else 1.0 / math.sqrt(DIM) for x in v])
        self.stats.add(calls=1, texts=len(texts), tokens=sum(len(t.split()) for t in texts))
        return out


def _config():
    return SearchConfigLoader(config_path=_YAML).load(force_reload=True)


def _vector_env(url, requested="pg"):
    factory, teardown = _schema_env(url)
    with factory() as db:
        has_vector = db.execute(text("SELECT 1 FROM pg_available_extensions WHERE name = 'vector'")).scalar()
    if not has_vector:
        teardown()
        pytest.skip("pgvector not available on this Postgres")
    engine = prepare_engine(factory, requested, embedding_dim=DIM)
    with factory() as db:
        repo.upsert_documents(db, ITEMS)
    return factory, engine, teardown


@pytest.fixture()
def pgv():
    if not _PG_URL:
        pytest.skip("SEARCH_TEST_PG_URL not set")
    factory, engine, teardown = _vector_env(_PG_URL)
    try:
        yield factory, engine
    finally:
        teardown()


def _worker(factory, engine, embedder=None, batch_size=4):
    return EmbeddingWorker(factory, engine, embedder or ConceptEmbedder(), batch_size=batch_size)


def _ids(ranked):
    return [i for i, _ in ranked]


def _rank(factory, engine, embedder, query, **kw):
    with factory() as db:
        return repo.vector_rank(db, embedder.embed([query])[0], config=_config(), engine=engine, **kw)


# ------------------------------------------------------------------ pgvector

def test_embedding_columns_and_hnsw_index(pgv):
    factory, engine = pgv
    assert engine.embedding_dim == DIM and engine.vector_index_method == "hnsw"
    with factory() as db:
        idx = db.execute(text("SELECT indexdef FROM pg_indexes WHERE indexname = :n"),
                         {"n": EMBEDDING_INDEXES["hnsw"]}).scalar()
        pending = repo.count_pending_embeddings(db)
    assert idx and "hnsw" in idx and "vector_cosine_ops" in idx
    assert pending == len(ITEMS)  # nothing embedded yet


def test_zero_lexical_overlap_query_finds_the_item_semantically(pgv):
    factory, engine = pgv
    embedder = ConceptEmbedder()
    _worker(factory, engine, embedder).run_until_idle()
    with factory() as db:
        assert repo.search(db, "client attrition", config=_config())["total_count"] == 0  # no lexical match
    ranked = _rank(factory, engine, embedder, "client attrition")
    assert ranked[0][0] == "product::1"            # Customer Churn
    assert 0 < ranked[0][1] <= 1.0001


def test_unchanged_documents_are_not_re_embedded(pgv):
    factory, engine = pgv
    embedder = ConceptEmbedder()
    worker = _worker(factory, engine, embedder)
    worker.run_until_idle()
    texts_after_backfill = embedder.stats.texts
    assert texts_after_backfill == len(ITEMS)

    with factory() as db:  # a reconcile re-sends every row; unchanged ones aren't rewritten...
        repo.upsert_documents(db, ITEMS)
        assert repo.count_pending_embeddings(db) == 0
        # ...and a row whose updated_at moved without a text change (e.g. only
        # extra_data changed) matches its hash: no endpoint call.
        db.execute(text("UPDATE search_documents SET updated_at = clock_timestamp()"))
    stats = worker.run_until_idle()
    assert embedder.stats.texts == texts_after_backfill
    assert stats["unchanged"] == len(ITEMS)

    changed = ITEMS[1].model_copy(update={"description": "Revenue and income by store"})
    with factory() as db:
        repo.upsert_documents(db, [changed])
    worker.run_until_idle()
    assert embedder.stats.texts == texts_after_backfill + 1  # only the edited document
    with factory() as db:
        assert repo.count_pending_embeddings(db) == 0


def test_backfill_is_resumable_after_an_endpoint_failure(pgv):
    factory, engine = pgv
    flaky = ConceptEmbedder(fail_after_calls=1)        # first batch works, then the endpoint fails
    with pytest.raises(RuntimeError, match="unavailable"):
        _worker(factory, engine, flaky, batch_size=4).run_until_idle()
    with factory() as db:
        assert repo.count_pending_embeddings(db) == len(ITEMS) - 4   # first batch kept
    resumed = ConceptEmbedder()
    _worker(factory, engine, resumed, batch_size=4).run_until_idle()
    assert resumed.stats.texts == len(ITEMS) - 4                     # only the remainder
    with factory() as db:
        assert repo.count_pending_embeddings(db) == 0


def test_vector_rank_applies_filters_permissions_and_disabled_types(pgv):
    factory, engine = pgv
    embedder = ConceptEmbedder()
    _worker(factory, engine, embedder).run_until_idle()
    contracts = _rank(factory, engine, embedder, "client agreement", type_filter="data-contract")
    assert contracts and all(i.startswith("contract::") for i in _ids(contracts))
    allowed = _rank(factory, engine, embedder, "client attrition", allowed_features=["teams"])
    assert _ids(allowed) == ["team::9"]
    config = _config()
    config.asset_types["data-product"].enabled = False
    with factory() as db:
        no_products = repo.vector_rank(db, embedder.embed(["client attrition"])[0], config=config, engine=engine)
    assert not any(i.startswith("product::") for i in _ids(no_products))


def test_backend_embeds_in_the_background_and_degrades_when_the_endpoint_fails(pgv):
    factory, engine = pgv
    embedder = ConceptEmbedder()
    backend = PostgresBackend(factory, config_provider=_config, embedder=embedder)
    backend.engine = engine
    backend.start_embeddings()
    try:
        backend.embedding_worker._debounce = 0
        new = SearchIndexItem(id="product::77", type="data-product", feature_id="data-products",
                              title="Consumer Attrition Signals", description="", link="/", tags=[], extra_data={})
        backend.upsert([new])  # wakes the worker
        import time
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            with factory() as db:
                if not repo.count_pending_embeddings(db):
                    break
            time.sleep(0.2)
        assert "product::77" in _ids(backend.vector_rank("client churn"))[:2]

        embedder.fail_after_calls = 0                     # endpoint goes down
        backend._query_vectors = QueryEmbeddingCache(embedder)  # no cached query vector
        assert backend.vector_rank("client attrition") == []   # degrades, never raises
    finally:
        backend.embedding_worker.stop(timeout=5)


def _pending(factory):
    with factory() as db:
        return repo.count_pending_embeddings(db)


def test_writes_dont_wait_on_the_endpoint_and_edits_made_meanwhile_are_re_embedded(pgv):
    factory, engine = pgv
    edited = ITEMS[0].model_copy(update={"description": "Revenue by store"})

    def user_saves_during_the_call():
        with factory() as db:  # another session; would block if the worker held row locks
            db.execute(text("SET LOCAL lock_timeout = '2s'"))
            repo.upsert_documents(db, [edited])

    embedder = ConceptEmbedder(on_embed=user_saves_during_the_call)
    worker = _worker(factory, engine, embedder, batch_size=len(ITEMS))
    worker.run_batch()
    assert _pending(factory) == 1          # the stale vector for the edited row wasn't stored
    embedder.on_embed = None
    worker.run_until_idle()
    assert _pending(factory) == 0


def test_a_document_the_endpoint_rejects_doesnt_stall_the_rest(pgv):
    factory, engine = pgv
    with factory() as db:
        repo.upsert_documents(db, [ITEMS[0].model_copy(update={"description": "POISON " * 50})])
    stats = _worker(factory, engine, ConceptEmbedder(reject="POISON"), batch_size=len(ITEMS)).run_until_idle()
    assert stats["rejected"] == 1 and stats["embedded"] == len(ITEMS) - 1
    assert _pending(factory) == 0          # the rejected text isn't retried until it changes
    with factory() as db:
        repo.upsert_documents(db, [ITEMS[0]])  # fixed
    assert _pending(factory) == 1


def test_an_outage_still_backs_off_instead_of_rejecting_documents(pgv):
    factory, engine = pgv
    with pytest.raises(RuntimeError):
        _worker(factory, engine, ConceptEmbedder(fail_after_calls=0)).run_batch()
    assert _pending(factory) == len(ITEMS)  # claims released, nothing marked


def test_a_re_created_embedding_column_is_re_embedded(pgv):
    factory, engine = pgv
    _worker(factory, engine).run_until_idle()
    with factory() as db:
        db.execute(text("UPDATE search_documents SET embedding = NULL"))  # as after DROP + re-add
    assert _pending(factory) == len(ITEMS)
    stats = _worker(factory, engine).run_until_idle()
    assert stats["embedded"] == len(ITEMS) and stats["unchanged"] == 0


def test_switching_the_model_re_embeds_everything(pgv):
    factory, engine = pgv
    _worker(factory, engine, ConceptEmbedder(endpoint="model-a")).run_until_idle()
    with factory() as db:  # e.g. a later edit pass; the hash no longer matches the new model
        db.execute(text("UPDATE search_documents SET updated_at = clock_timestamp()"))
    stats = _worker(factory, engine, ConceptEmbedder(endpoint="model-b")).run_until_idle()
    assert stats["embedded"] == len(ITEMS) and stats["unchanged"] == 0


def test_filtered_semantic_query_isnt_starved_by_the_ann_candidate_limit(pgv):
    """HNSW returns ~ef_search (40) candidates before WHERE filters apply."""
    factory, engine = pgv
    with factory() as db:
        repo.upsert_documents(db, [
            SearchIndexItem(id=f"product::churn{n}", type="data-product", feature_id="data-products",
                            title=f"Customer Churn {n}", description="client attrition", link="/", tags=[],
                            extra_data={})
            for n in range(300)
        ])
    embedder = ConceptEmbedder()
    _worker(factory, engine, embedder, batch_size=100).run_until_idle()
    teams = _rank(factory, engine, embedder, "client attrition", type_filter="team")
    assert "team::9" in _ids(teams)


def test_filtered_semantic_queries_widen_the_hnsw_scan(pgv):
    # Small test tables are planned without the HNSW index, so check the
    # settings the query runs with (pgvector >= 0.8 for iterative_scan).
    factory, _ = pgv
    with factory() as db:
        repo._hnsw_filtered_scan(db, 200)
        assert db.execute(text("SELECT current_setting('hnsw.ef_search')")).scalar() == "200"
        version = db.execute(text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")).scalar()
        if tuple(int(x) for x in version.split(".")[:2]) >= (0, 8):
            assert db.execute(text("SELECT current_setting('hnsw.iterative_scan')")).scalar() == "relaxed_order"
    with factory() as db:  # transaction-local
        assert db.execute(text("SELECT current_setting('hnsw.ef_search', true)")).scalar() in (None, "", "40")


def test_full_rebuild_keeps_embeddings(pgv):
    factory, engine = pgv
    _worker(factory, engine).run_until_idle()
    with factory() as db:
        repo.replace_all(db, ITEMS[1:])
        assert repo.count_pending_embeddings(db) == 0
        assert db.execute(text("SELECT count(*) FROM search_documents WHERE embedding IS NOT NULL")).scalar() \
            == len(ITEMS) - 1


def test_a_changed_embedding_size_turns_semantic_search_off(pgv):
    factory, _ = pgv
    assert prepare_engine(factory, "pg", embedding_dim=DIM * 2).embedding_dim == 0


# ------------------------------------------------------------- lakebase_ann

@pytest.mark.skipif(not _LAKEBASE_URL, reason="SEARCH_TEST_LAKEBASE_URL not set (Lakebase Search branch)")
def test_lakebase_ann_index_and_semantic_query():
    factory, engine, teardown = _vector_env(_LAKEBASE_URL, requested="auto")
    try:
        assert engine.name == "lakebase" and engine.vector_index_method == "lakebase_ann"
        with factory() as db:
            idx = db.execute(text("SELECT indexdef FROM pg_indexes WHERE indexname = :n"),
                             {"n": EMBEDDING_INDEXES["lakebase_ann"]}).scalar()
        assert idx and "lakebase_ann" in idx
        embedder = ConceptEmbedder()
        _worker(factory, engine, embedder).run_until_idle()
        assert _ids(_rank(factory, engine, embedder, "client attrition"))[0] == "product::1"
        with factory() as db:  # filtered query behind many closer neighbours
            repo.upsert_documents(db, [
                SearchIndexItem(id=f"product::churn{n}", type="data-product", feature_id="data-products",
                                title=f"Customer Churn {n}", description="client attrition", link="/",
                                tags=[], extra_data={})
                for n in range(300)
            ])
        _worker(factory, engine, embedder, batch_size=100).run_until_idle()
        assert "team::9" in _ids(_rank(factory, engine, embedder, "client attrition", type_filter="team"))
    finally:
        teardown()


# ---------------------------------------------------- real embedding endpoint

@pytest.mark.skipif(not (_EMBED_PROFILE and _PG_URL),
                    reason="SEARCH_TEST_EMBEDDING_PROFILE / SEARCH_TEST_PG_URL not set")
def test_databricks_embedding_endpoint_finds_paraphrases(monkeypatch):
    from types import SimpleNamespace

    from databricks.sdk.core import Config

    from src.common.search_embeddings import DatabricksEmbedder

    # conftest points DATABRICKS_HOST at a placeholder host, which would override
    # the profile's (and the SDK would retry its metadata lookup for minutes).
    monkeypatch.delenv("DATABRICKS_HOST", raising=False)
    monkeypatch.delenv("DATABRICKS_TOKEN", raising=False)
    cfg = Config(profile=_EMBED_PROFILE)
    settings = SimpleNamespace(
        DATABRICKS_TOKEN=None, DATABRICKS_CONFIG_PROFILE=_EMBED_PROFILE, DATABRICKS_HOST=cfg.host,
        LLM_BASE_URL=None,
    )
    endpoint = os.environ.get("SEARCH_TEST_EMBEDDING_ENDPOINT", "databricks-gte-large-en")
    embedder = DatabricksEmbedder(settings, endpoint, 1024)
    factory, teardown = _schema_env(_LAKEBASE_URL or _PG_URL)
    try:
        engine = prepare_engine(factory, "auto", embedding_dim=1024)
        if not engine.embedding_dim:
            pytest.skip("pgvector not available on this Postgres")
        with factory() as db:
            repo.upsert_documents(db, ITEMS)
        stats = EmbeddingWorker(factory, engine, embedder, batch_size=16).run_until_idle()
        assert stats["embedded"] == len(ITEMS) and stats["endpoint"]["tokens"] > 0
        with factory() as db:
            ranked = repo.vector_rank(db, embedder.embed(["which clients are likely to leave us"])[0],
                                      config=_config(), engine=engine, limit=3)
        assert "product::1" in _ids(ranked)
    finally:
        teardown()
