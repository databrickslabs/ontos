"""Parity: the Postgres search backend ranks exactly like the in-memory scorer.

Same items, same ``SearchConfig``, same queries → identical result ids, order,
total counts and relevance scores, across the shipped Settings and variants
(boost, disabled types, ranking order, match types). Auto-skips without
``SEARCH_TEST_PG_URL`` (see test_search_repository_pg.py for how to run).
"""
import copy
import os
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.common.search_config_loader import SearchConfigLoader
from src.common.search_interfaces import SearchIndexItem
from src.controller import search_scoring
from src.db_models.search_documents import SearchDocumentDb
from src.models.search_config import MatchType, SortField
from src.repositories import search_repository as repo

_PG_URL = os.environ.get("SEARCH_TEST_PG_URL")
_YAML = Path(__file__).resolve().parents[2] / "data" / "search_config.yaml"


@pytest.fixture()
def pg_session():
    if not _PG_URL:
        pytest.skip("SEARCH_TEST_PG_URL not set — Postgres parity test skipped")
    schema = f"search_par_{uuid.uuid4().hex[:8]}"
    admin = create_engine(_PG_URL, future=True)
    try:
        with admin.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    except Exception as e:  # pragma: no cover - environment dependent
        pytest.skip(f"Postgres not reachable at SEARCH_TEST_PG_URL: {e}")
    engine = create_engine(_PG_URL, future=True, connect_args={"options": f"-csearch_path={schema}"})
    SearchDocumentDb.__table__.create(bind=engine)
    db = sessionmaker(bind=engine, future=True)()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()
        with admin.begin() as conn:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin.dispose()


def _item(id_, type_, feature_id, title, description="", tags=None, extra=None):
    return SearchIndexItem(
        id=id_, type=type_, feature_id=feature_id, title=title, description=description,
        link=f"/{type_}/{id_}", tags=tags or [], extra_data=extra or {},
    )


ITEMS = [
    _item("product::1", "data-product", "data-products", "Customer Churn",
          "Predicts customer churn risk for retention", tags=["ml", "customer/retention"],
          extra={"status": "active", "domain": "Customer", "domains": ["Customer", "Sales"],
                 "owner": "Retention Analytics", "version": "1.2.0", "product_team": "Growth Squad"}),
    _item("product::2", "data-product", "data-products", "Sales Transactions",
          "Daily sales facts by store", tags=["finance", "sales"],
          extra={"status": "draft", "domain": "Sales", "domains": ["Sales"], "owner": "Finance Ops"}),
    _item("product::3", "data-product", "data-products", "Customer 360",
          "Unified customer profile", tags=["customer"],
          extra={"status": "active", "domain": "Customer", "owner": "CRM Team"}),
    _item("contract::4", "data-contract", "data-contracts", "Orders Contract",
          "Contract for order events from the customer portal", tags=["orders"],
          extra={"status": "active", "domain": "Sales", "owner": "Order Platform"}),
    _item("contract::5", "data-contract", "data-contracts", "Churn Features Contract",
          "Feature table backing churn models", tags=["ml"],
          extra={"status": "proposed", "domain": "Customer"}),
    _item("glossary::6", "glossary-term", "semantic-models", "Customer Lifetime Value",
          "Predicted net revenue from a customer", tags=["metric"], extra={"domain": "Finance"}),
    _item("domain::7", "data-domain", "data-domains", "Customer Domain",
          "All things customer", extra={}),
    _item("asset::8", "asset-table", "assets", "sales_orders_daily",
          "Daily orders aggregated", tags=["sales"], extra={"status": "active"}),
    _item("team::9", "team", "teams", "Retention Squad", "Owns churn initiatives", extra={}),
    _item("other::10", "unconfigured-type", "misc", "Customer Notes", "Free text notes", tags=["notes"]),
]

QUERIES = [
    "customer", "customer churn", "churn data product", "sales", "Sales Orders",
    "cust", "retention", "finance ops", "growth", "ml", "orders contract",
    "custmer", "1.2.0", "!!!", "zzz-no-match", "customer/retention",
]


def _base_config():
    return SearchConfigLoader(config_path=_YAML).load(force_reload=True)


def _variants():
    base = _base_config()
    out = {"shipped": base}

    boosted = copy.deepcopy(base)
    boosted.defaults.fields.description.boost = 5.0
    boosted.defaults.fields.title.boost = 0.5
    for at in boosted.asset_types.values():
        if "description" in at.fields:
            at.fields["description"].boost = 5.0
    out["description_boosted"] = boosted

    disabled = copy.deepcopy(base)
    disabled.asset_types["data-contract"].enabled = False
    disabled.asset_types["asset"].enabled = False
    out["contracts_and_assets_disabled"] = disabled

    by_score = copy.deepcopy(base)
    by_score.ranking.primary_sort = SortField.BOOST_SCORE
    by_score.ranking.secondary_sort = SortField.TITLE_ASC
    by_score.ranking.tertiary_sort = SortField.MATCH_PRIORITY
    out["rank_by_score"] = by_score

    match_types = copy.deepcopy(base)
    match_types.defaults.fields.title.match_type = MatchType.FUZZY
    match_types.defaults.fields.description.match_type = MatchType.EXACT
    for at in match_types.asset_types.values():
        for fc in list(at.fields.values()) + list(at.extra_fields.values()):
            fc.match_type = MatchType.FUZZY
    out["fuzzy_and_exact"] = match_types
    return out


VARIANTS = _variants()


def _memory_items(config):
    """What SearchManager.build_index keeps for the in-memory backend."""
    def enabled(item):
        a = config.asset_types.get(item.type)
        if not a and item.type.startswith("asset-"):
            a = config.asset_types.get("asset")
        return not (a and not a.enabled)
    return [i for i in ITEMS if enabled(i)]


@pytest.fixture()
def seeded(pg_session):
    repo.upsert_documents(pg_session, ITEMS)  # disabled types are stored too
    pg_session.flush()
    return pg_session


def _shape(res):
    return [(r["id"], r.get("relevance_score")) for r in res["results"]], res["total_count"]


@pytest.mark.parametrize("variant", list(VARIANTS))
@pytest.mark.parametrize("query", QUERIES)
def test_mcp_search_parity(seeded, variant, query):
    config = VARIANTS[variant]
    mem = search_scoring.search_index(_memory_items(config), query, config, limit=100)
    pg = repo.search(seeded, query, config=config, limit=100)
    assert _shape(pg) == _shape(mem), f"{variant} / {query!r}"


@pytest.mark.parametrize("variant", list(VARIANTS))
@pytest.mark.parametrize("query", ["customer", "sales orders", "churn"])
def test_pagination_parity(seeded, variant, query):
    config = VARIANTS[variant]
    for offset in (0, 2, 4):
        mem = search_scoring.search_index(_memory_items(config), query, config, limit=2, offset=offset)
        pg = repo.search(seeded, query, config=config, limit=2, offset=offset)
        assert _shape(pg) == _shape(mem)
        assert pg["has_more"] == mem["has_more"]


@pytest.mark.parametrize("variant", list(VARIANTS))
@pytest.mark.parametrize("query", QUERIES)
def test_rest_ranking_parity(seeded, variant, query):
    config = VARIANTS[variant]
    mem = [s.item.id for s in search_scoring.score_and_rank(_memory_items(config), query, config)]
    pg = [i.id for i in repo.search_index_items(seeded, query, config=config)]
    assert pg == mem


@pytest.mark.parametrize("variant", list(VARIANTS))
def test_list_mode_parity(seeded, variant):
    config = VARIANTS[variant]
    mem = search_scoring.search_index(_memory_items(config), "*", config, limit=100)
    pg = repo.search(seeded, "*", config=config, limit=100)
    assert [r["id"] for r in pg["results"]] == [r["id"] for r in mem["results"]]
    assert pg["total_count"] == mem["total_count"]


def test_filters_apply_with_settings(seeded):
    config = VARIANTS["shipped"]
    mem = search_scoring.search_index(_memory_items(config), "customer", config,
                                      type_filter="data-product", filters={"status": "active"}, limit=100)
    pg = repo.search(seeded, "customer", config=config, type_filter="data-product",
                     filters={"status": "active"}, limit=100)
    assert _shape(pg) == _shape(mem)


def test_disabling_a_type_applies_live_and_reenabling_restores(seeded):
    base = VARIANTS["shipped"]

    def ids(cfg):
        return {r["id"] for r in repo.search(seeded, "contract", config=cfg, limit=100)["results"]}

    assert "4" in ids(base)
    assert "4" not in ids(VARIANTS["contracts_and_assets_disabled"])
    assert "4" in ids(base)  # same stored rows, no rebuild


def test_facets_include_owner_and_count_matches(seeded):
    res = repo.search(seeded, "customer", config=VARIANTS["shipped"], limit=100)
    assert res["facets"]["owner"]
    assert sum(res["facets"]["type"].values()) == res["total_count"]
