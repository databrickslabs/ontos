"""Unit tests for MCP tool efficiency changes.

Covers four changes from the agent's own feedback on the live tool set:
  1. list_data_products / list_data_contracts are now thin wrappers over the
     corresponding search_* tool — one implementation, no TypeError bug, same
     shape as search.
  2. Server-side tag dedupe in the index builders — the result's tags[:5]
     slice no longer wastes slots on repeat strings.
  3. _to_result drops feature_id (duplicates type for MCP consumers).
  4. search_* tools expose include_facets (opt-out) and fields (projection)
     so cheap list calls and "then fetch details" flows don't pay for the
     full row + facet block every time.
"""
import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.common.search_interfaces import SearchIndexItem
from src.controller import search_scoring
from src.models.search_config import SearchConfig
from src.tools.base import ToolContext
from src.tools.data_products import (
    ListDataProductsTool,
    SearchDataProductsTool,
)
from src.tools.data_contracts import (
    ListDataContractsTool,
    SearchDataContractsTool,
)


def _run(coro):
    return asyncio.run(coro)


# =====================================================================
# _to_result shape + fields projection + include_facets opt-out
# =====================================================================

@pytest.fixture
def config():
    return SearchConfig()


@pytest.fixture
def items():
    return [
        SearchIndexItem(
            id="product::1", type="data-product", feature_id="data-products",
            title="Customer Churn", description="Predicts customer churn risk",
            link="/data-products/1", tags=["ml", "customer"],
            extra_data={"status": "active", "domain": "Customer", "owner": "Alice",
                        "version": "1.2.0", "domains": ["Customer"]},
        ),
        SearchIndexItem(
            id="product::2", type="data-product", feature_id="data-products",
            title="Sales Daily", description="Daily sales facts",
            link="/data-products/2", tags=["finance"],
            extra_data={"status": "draft", "domain": "Sales", "owner": "Bob",
                        "domains": ["Sales"]},
        ),
    ]


class TestToResult:
    def test_result_omits_feature_id(self, config, items):
        """feature_id duplicates type for MCP consumers — must not appear."""
        res = search_scoring.search_index(items, "customer", config)
        assert res["results"], "sanity"
        for row in res["results"]:
            assert "feature_id" not in row, f"feature_id leaked into {row}"
            assert "type" in row and "link" in row  # these stay

    def test_fields_projection_narrows_rows(self, config, items):
        """fields=['title','status'] keeps only those keys + id."""
        res = search_scoring.search_index(items, "*", config, fields=["title", "status"])
        assert res["results"]
        for row in res["results"]:
            assert set(row.keys()) <= {"id", "title", "status"}
            assert "id" in row  # id always kept

    def test_fields_empty_list_returns_full_row(self, config, items):
        """fields=None / [] must leave the row untouched (back-compat)."""
        full = search_scoring.search_index(items, "*", config)["results"][0]
        narrow_none = search_scoring.search_index(items, "*", config, fields=None)["results"][0]
        narrow_empty = search_scoring.search_index(items, "*", config, fields=[])["results"][0]
        assert set(full.keys()) == set(narrow_none.keys()) == set(narrow_empty.keys())

    def test_include_facets_false_returns_empty_facets(self, config, items):
        """include_facets=False skips the facet-computation pass."""
        with_facets = search_scoring.search_index(items, "*", config, include_facets=True)
        without = search_scoring.search_index(items, "*", config, include_facets=False)
        assert with_facets["facets"]  # non-empty on this fixture
        assert without["facets"] == {}
        assert without["results"] == with_facets["results"]  # records unchanged


# =====================================================================
# Server-side tag dedupe in index builders
# =====================================================================

class TestTagDedupe:
    def test_product_builder_dedupes_tags(self):
        """Products accumulate tags from unified tags + assigned domains +
        ontosOriginalDomain + concept labels. The same string must not appear
        twice (would waste the result's tags[:5] slice)."""
        from src.controller.data_products_manager import DataProductsManager

        mgr = DataProductsManager.__new__(DataProductsManager)
        mgr._db = None  # the branches that use it are wrapped in try/except

        product = SimpleNamespace(
            id="p1", name="P", description=None, status="active", version="1.0.0",
            domain="Sales",
            tags=[  # unified-tag shape returned by get_unified_tags
                SimpleNamespace(fully_qualified_name="Sales", tag_name="Sales"),
                SimpleNamespace(fully_qualified_name="Sales", tag_name="Sales"),
                SimpleNamespace(fully_qualified_name="Finance", tag_name="Finance"),
            ],
            customProperties=[
                SimpleNamespace(property="ontosOriginalDomain", value="Sales"),
            ],
            team=None, outputPorts=[], owner_team_id=None, owner_team_name=None,
        )
        item = mgr._build_search_index_item(product)
        assert item is not None
        assert item.tags.count("Sales") == 1, f"Sales appears {item.tags.count('Sales')}× in {item.tags}"
        assert "Finance" in item.tags

    def test_contract_builder_dedupes_tags(self):
        """Contracts same rationale — assigned domains + tag names shouldn't duplicate."""
        from src.controller.data_contracts_manager import DataContractsManager
        from src.db_models.data_contracts import DataContractDb

        mgr = DataContractsManager.__new__(DataContractsManager)

        contract_db = SimpleNamespace(
            id="c1", name="C", description_usage=None, description_purpose=None,
            status="active", version="1.0.0", owner_team_id=None, owner="",
        )
        # Both preloaded_tags and preloaded_domains carry "Sales" — must collapse.
        preloaded_tags = [
            SimpleNamespace(fully_qualified_name="Sales", name="Sales"),
            SimpleNamespace(fully_qualified_name="Sales", name="Sales"),
        ]
        preloaded_domains = [
            SimpleNamespace(domain_name="Sales", is_primary=True),
            SimpleNamespace(domain_name="Finance", is_primary=False),
        ]
        item = mgr._build_search_index_item(
            contract_db, db=None,
            preloaded_tags=preloaded_tags,
            preloaded_domains=preloaded_domains,
        )
        assert item is not None
        assert item.tags.count("Sales") == 1
        assert "Finance" in item.tags


# =====================================================================
# list_data_* are thin wrappers over search_data_*
# =====================================================================

class _StubSearchManager:
    """Captures the kwargs passed to query_index and returns a canned shape."""
    def __init__(self):
        self.calls = []

    def query_index(self, query, **kw):
        self.calls.append({"query": query, **kw})
        # `type` + `link` arrive from the scorer because the UI global search
        # (mixed types) needs them. The per-type MCP tools must strip both.
        t = kw.get("type_filter") or "data-product"
        return {
            "results": [{"id": "x", "type": t, "title": "X", "link": f"/{t}s/x"}],
            "total_count": 1, "returned": 1, "offset": 0, "limit": 25, "has_more": False,
            "facets": {"status": {"active": 1}}, "query": query,
        }


def _ctx(search_manager=None):
    return ToolContext(db=MagicMock(), settings=MagicMock(),
                       data_products_manager=MagicMock(),
                       data_contracts_manager=MagicMock(),
                       search_manager=search_manager)


class TestListTools:
    def test_list_data_products_delegates_to_search_with_wildcard(self):
        """list_data_products must call search_data_products with query='*' —
        this is what fixes the TypeError (list_products didn't accept domain/
        status kwargs) and unifies the three overlapping entry points."""
        sm = _StubSearchManager()
        res = _run(ListDataProductsTool().execute(_ctx(sm), domain="Sales", status="active", limit=50))
        assert res.success
        # Exactly one query_index call, with the search wildcard, filters, limit.
        assert len(sm.calls) == 1
        call = sm.calls[0]
        assert call["query"] == "*"
        assert call["type_filter"] == "data-product"
        assert call["filters"] == {"domains": "Sales", "status": "active"}
        assert call["limit"] == 50
        # Response shape mirrors search_data_products.
        assert "products" in res.data and "total_found" in res.data
        assert "has_more" in res.data and "facets" in res.data

    def test_list_data_contracts_delegates_to_search_with_wildcard(self):
        sm = _StubSearchManager()
        res = _run(ListDataContractsTool().execute(_ctx(sm), domain="Sales", status="active", limit=50))
        assert res.success
        assert len(sm.calls) == 1
        call = sm.calls[0]
        assert call["query"] == "*"
        assert call["type_filter"] == "data-contract"
        assert call["filters"] == {"domain": "Sales", "status": "active"}
        assert "contracts" in res.data and "total_found" in res.data
        assert "has_more" in res.data and "facets" in res.data


# =====================================================================
# search_* passes include_facets and fields through to query_index
# =====================================================================

class TestSearchParamPassthrough:
    def test_search_data_products_passes_include_facets_and_fields(self):
        sm = _StubSearchManager()
        _run(SearchDataProductsTool().execute(
            _ctx(sm), query="customer", include_facets=False, fields=["title", "status"]
        ))
        call = sm.calls[0]
        assert call["include_facets"] is False
        assert call["fields"] == ["title", "status"]

    def test_search_data_contracts_passes_include_facets_and_fields(self):
        sm = _StubSearchManager()
        _run(SearchDataContractsTool().execute(
            _ctx(sm), query="orders", include_facets=False, fields=["title"]
        ))
        call = sm.calls[0]
        assert call["include_facets"] is False
        assert call["fields"] == ["title"]

    def test_search_defaults_include_facets_true_fields_none(self):
        """Back-compat: when the caller omits the new params, behaviour is unchanged."""
        sm = _StubSearchManager()
        _run(SearchDataProductsTool().execute(_ctx(sm), query="customer"))
        call = sm.calls[0]
        assert call["include_facets"] is True
        assert call["fields"] is None


# =====================================================================
# Per-record `type` + `link` strip on per-type MCP tools
# =====================================================================

class TestPerRecordTypeAndLinkStrip:
    """`type` is redundant with the tool name; `link` is a UI route path.
    Both are useful on the shared scorer output (UI global search mixes types),
    but the per-type MCP list/search tools must drop them from every record."""

    def test_search_data_products_records_omit_type_and_link(self):
        sm = _StubSearchManager()
        res = _run(SearchDataProductsTool().execute(_ctx(sm), query="customer"))
        assert res.success and res.data["products"]
        for row in res.data["products"]:
            assert "type" not in row, f"type leaked into {row}"
            assert "link" not in row, f"link leaked into {row}"

    def test_search_data_contracts_records_omit_type_and_link(self):
        sm = _StubSearchManager()
        res = _run(SearchDataContractsTool().execute(_ctx(sm), query="orders"))
        assert res.success and res.data["contracts"]
        for row in res.data["contracts"]:
            assert "type" not in row
            assert "link" not in row

    def test_list_data_products_inherits_strip(self):
        """ListDataProductsTool delegates to SearchDataProductsTool, so the
        strip applies through the wrapper too."""
        sm = _StubSearchManager()
        res = _run(ListDataProductsTool().execute(_ctx(sm)))
        assert res.success and res.data["products"]
        for row in res.data["products"]:
            assert "type" not in row
            assert "link" not in row

    def test_list_data_contracts_inherits_strip(self):
        sm = _StubSearchManager()
        res = _run(ListDataContractsTool().execute(_ctx(sm)))
        assert res.success and res.data["contracts"]
        for row in res.data["contracts"]:
            assert "type" not in row
            assert "link" not in row


# =====================================================================
# Contract search index stores raw description (no version/status prefix)
# =====================================================================

class TestFieldsValidation:
    """`fields=['name']` on contracts used to return just `{id}` with no hint —
    the row key is `title`, not `name`. Validate names up front and return a
    helpful error so callers (and the pre-#954 row shape) learn fast (#954
    reviewer note 3)."""

    def test_search_data_products_rejects_unknown_field(self):
        sm = _StubSearchManager()
        res = _run(SearchDataProductsTool().execute(
            _ctx(sm), query="customer", fields=["name", "status"],
        ))
        assert res.success is False
        assert "unknown fields" in (res.error or "").lower()
        assert "'name'" in (res.error or "") or "name" in (res.error or "")
        # The search manager was never called — validation is pre-flight.
        assert sm.calls == []

    def test_search_data_contracts_rejects_unknown_field(self):
        sm = _StubSearchManager()
        res = _run(SearchDataContractsTool().execute(
            _ctx(sm), query="orders", fields=["owner_team_name"],
        ))
        assert res.success is False
        assert "unknown fields" in (res.error or "").lower()
        assert sm.calls == []

    def test_search_data_products_accepts_known_fields(self):
        sm = _StubSearchManager()
        res = _run(SearchDataProductsTool().execute(
            _ctx(sm), query="customer", fields=["title", "status"],
        ))
        assert res.success is True
        assert sm.calls[0]["fields"] == ["title", "status"]

    def test_search_data_contracts_accepts_known_fields(self):
        sm = _StubSearchManager()
        res = _run(SearchDataContractsTool().execute(
            _ctx(sm), query="orders", fields=["id", "title", "domain"],
        ))
        assert res.success is True
        assert sm.calls[0]["fields"] == ["id", "title", "domain"]


class TestContractDescriptionIsRaw:
    """The contract index used to compose `"{version} • {status} • {usage}"` as
    the description, duplicating structured fields and making the string harder
    for an MCP agent to parse. Index now stores just the raw usage text —
    version and status are already in `extra_data` and surface as separate
    result-row keys."""

    def test_contract_description_omits_version_status_prefix(self):
        from src.controller.data_contracts_manager import DataContractsManager

        mgr = DataContractsManager.__new__(DataContractsManager)
        contract_db = SimpleNamespace(
            id="c1", name="C", description_usage="Customer master attributes",
            description_purpose=None, status="active", version="1.0.0",
            owner_team_id=None, owner="",
        )
        item = mgr._build_search_index_item(contract_db, db=None,
                                             preloaded_tags=[], preloaded_domains=[])
        assert item is not None
        assert item.description == "Customer master attributes"
        # version + status remain available via extra_data (and surface in
        # result rows through _RESULT_FIELDS).
        assert item.extra_data["version"] == "1.0.0"
        assert item.extra_data["status"] == "active"
