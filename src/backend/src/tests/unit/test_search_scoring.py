"""
Unit tests for the shared, tokenized search scorer (src.controller.search_scoring).

These are pure (no DB, no auth) and cover the behaviours that fix the MCP
agent's failure mode: multi-word plain-language queries returning results,
bounded/paginated list mode instead of an unbounded ``*`` dump, filters, and
facets.
"""
import pytest

from src.common.search_interfaces import SearchIndexItem
from src.controller import search_scoring
from src.models.search_config import SearchConfig


@pytest.fixture
def config():
    # Defaults only (title=prefix, description=substring, tags=prefix) is enough
    # for the scorer contract; per-type extra fields are exercised via extra_data.
    return SearchConfig()


@pytest.fixture
def items():
    return [
        SearchIndexItem(
            id="product::1", type="data-product", feature_id="data-products",
            title="Customer Churn", description="Predicts customer churn risk",
            link="/data-products/1", tags=["ml", "customer"],
            extra_data={"status": "active", "domain": "Customer", "owner": "Alice",
                        "version": "1.2.0", "domains": ["Customer", "Sales"]},
        ),
        SearchIndexItem(
            id="product::2", type="data-product", feature_id="data-products",
            title="Sales Transactions", description="Daily sales facts",
            link="/data-products/2", tags=["finance"],
            extra_data={"status": "draft", "domain": "Sales", "owner": "Bob",
                        "domains": ["Sales"]},
        ),
        SearchIndexItem(
            id="contract::3", type="data-contract", feature_id="data-contracts",
            title="Orders Contract", description="Contract for order events",
            link="/data-contracts/3", tags=["orders"],
            extra_data={"status": "active", "domain": "Sales"},
        ),
    ]


def test_tokenize():
    assert search_scoring.tokenize("Customer Churn, data-product") == ["customer", "churn", "data", "product"]
    assert search_scoring.tokenize("") == []
    assert search_scoring.tokenize("   ") == []


def test_multiword_query_matches_via_tokens(config, items):
    # The whole phrase is never a substring of one field, but the tokens are.
    out = search_scoring.search_index(items, "customer churn data product", config)
    assert out["total_count"] >= 1
    assert out["results"][0]["title"] == "Customer Churn"


def test_partial_terms_still_match_and_rank(config, items):
    # 'sales' matches the product via its title (default config indexes title).
    sales = search_scoring.search_index(items, "sales", config)
    assert [r["title"] for r in sales["results"]] == ["Sales Transactions"]
    # 'orders' matches the contract via its title and tags.
    orders = search_scoring.search_index(items, "orders", config)
    assert "Orders Contract" in [r["title"] for r in orders["results"]]


def test_no_match_returns_empty_not_everything(config, items):
    out = search_scoring.search_index(items, "zznomatch", config)
    assert out["total_count"] == 0
    assert out["results"] == []


def test_list_mode_is_bounded_and_paginated(config, items):
    out = search_scoring.search_index(items, "*", config, limit=2, offset=0)
    assert out["total_count"] == 3
    assert out["returned"] == 2
    assert out["has_more"] is True
    page2 = search_scoring.search_index(items, "", config, limit=2, offset=2)
    assert page2["returned"] == 1
    assert page2["has_more"] is False


def test_type_filter(config, items):
    out = search_scoring.search_index(items, "*", config, type_filter="data-contract")
    assert out["total_count"] == 1
    assert out["results"][0]["type"] == "data-contract"


def test_filters_are_exact_case_insensitive(config, items):
    active = search_scoring.search_index(items, "*", config, filters={"status": "active"})
    assert active["total_count"] == 2  # product::1 and contract::3 are active
    # Exact: 'Sale' must NOT match 'Sales'.
    assert search_scoring.search_index(items, "*", config, filters={"domain": "Sale"})["total_count"] == 0


def test_domains_filter_matches_any_assigned_domain(config, items):
    # product::1 has assigned domains [Customer, Sales]; filtering by Sales must include it.
    out = search_scoring.search_index(items, "*", config, filters={"domains": "sales"})
    ids = sorted(r["id"] for r in out["results"])
    assert ids == ["1", "2"]  # both products carry an assigned 'Sales' domain


def test_version_surfaced_when_present(config, items):
    out = search_scoring.search_index(items, "churn", config)
    assert out["results"][0]["version"] == "1.2.0"


def test_facets_present(config, items):
    out = search_scoring.search_index(items, "*", config)
    assert out["facets"]["type"]["data-product"] == 2
    assert out["facets"]["status"]["active"] == 2
    assert "Sales" in out["facets"]["domain"]


def test_entity_id_stripped_of_prefix(config, items):
    out = search_scoring.search_index(items, "churn", config)
    assert out["results"][0]["id"] == "1"  # 'product::1' -> '1'


def test_limit_clamped(config, items):
    out = search_scoring.search_index(items, "*", config, limit=9999)
    assert out["limit"] == 100
