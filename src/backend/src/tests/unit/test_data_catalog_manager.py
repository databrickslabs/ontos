"""Unit tests for DataCatalogManager.

Covers the parts of PR #337 that the reviewer flagged as untested:

- ``_merge_columns`` dedup precedence between contract + asset sources
- ``_matches_search`` field coverage
- Pagination math on ``get_all_columns`` / ``search_columns``
- Composed filter behaviour on ``get_all_columns``

These tests stub the two heavy extraction helpers (``_get_columns_from_contracts``,
``_get_columns_from_assets``) so we exercise the pure merge/filter/search/page
logic without spinning up a DB.
"""
from __future__ import annotations

from typing import List
from unittest.mock import MagicMock

import pytest

from src.controller.data_catalog_manager import DataCatalogManager
from src.models.data_catalog import ColumnDictionaryEntry


def _entry(
    *,
    column_name: str,
    table_full_name: str,
    table_name: str = "tbl",
    schema_name: str = "schema",
    catalog_name: str = "catalog",
    table_type: str = "TABLE",
    source: str = "asset",
    description: str | None = None,
    column_label: str | None = None,
    system_name: str | None = None,
    contract_name: str | None = None,
    business_terms: list[dict] | None = None,
    classification: str | None = None,
) -> ColumnDictionaryEntry:
    """Build a minimal ColumnDictionaryEntry with sensible defaults."""
    return ColumnDictionaryEntry(
        column_name=column_name,
        column_label=column_label,
        column_type="STRING",
        description=description,
        nullable=True,
        position=0,
        table_name=table_name,
        table_full_name=table_full_name,
        schema_name=schema_name,
        catalog_name=catalog_name,
        table_type=table_type,
        source=source,
        system_name=system_name,
        contract_name=contract_name,
        business_terms=business_terms or [],
        classification=classification,
    )


@pytest.fixture
def manager() -> DataCatalogManager:
    """Build a DataCatalogManager whose dependencies are all mocked."""
    return DataCatalogManager(
        obo_client=MagicMock(),
        db_session=MagicMock(),
        contracts_manager=MagicMock(),
        settings=MagicMock(),
    )


class TestMergeColumns:
    """_merge_columns: asset base + contract enrichment, dedup, business term union."""

    def test_disjoint_sources_are_concatenated(self, manager):
        contract_only = _entry(
            column_name="business_id",
            table_full_name="contracts_demo.orders",
            source="contract",
        )
        asset_only = _entry(
            column_name="customer_id",
            table_full_name="main.sales.customers",
            source="asset",
        )

        merged = manager._merge_columns([contract_only], [asset_only])

        assert len(merged) == 2
        sources = {col.column_name: col.source for col in merged}
        assert sources == {"business_id": "contract", "customer_id": "asset"}

    def test_same_key_in_both_sources_marks_source_both(self, manager):
        contract = _entry(
            column_name="order_id",
            table_full_name="main.sales.orders",
            source="contract",
            column_label="Order Identifier",
            contract_name="orders-v1",
            classification="PII",
            business_terms=[{"iri": "urn:bt:OrderId", "label": "OrderId"}],
        )
        asset = _entry(
            column_name="order_id",
            table_full_name="main.sales.orders",
            source="asset",
            description="physical column comment",
        )

        merged = manager._merge_columns([contract], [asset])

        assert len(merged) == 1
        col = merged[0]
        assert col.source == "both"
        # asset metadata stays the base (description from physical layer)
        assert col.description == "physical column comment"
        # contract context enriches it
        assert col.column_label == "Order Identifier"
        assert col.classification == "PII"
        assert col.contract_name == "orders-v1"
        assert any(t["iri"] == "urn:bt:OrderId" for t in col.business_terms)

    def test_dedup_is_case_insensitive(self, manager):
        contract = _entry(
            column_name="ORDER_ID",
            table_full_name="MAIN.SALES.ORDERS",
            source="contract",
        )
        asset = _entry(
            column_name="order_id",
            table_full_name="main.sales.orders",
            source="asset",
        )

        merged = manager._merge_columns([contract], [asset])

        assert len(merged) == 1
        assert merged[0].source == "both"

    def test_business_terms_are_unioned_by_iri(self, manager):
        contract = _entry(
            column_name="order_id",
            table_full_name="main.sales.orders",
            source="contract",
            business_terms=[
                {"iri": "urn:bt:OrderId", "label": "OrderId"},
                {"iri": "urn:bt:Pii", "label": "PII"},
            ],
        )
        asset = _entry(
            column_name="order_id",
            table_full_name="main.sales.orders",
            source="asset",
            business_terms=[{"iri": "urn:bt:OrderId", "label": "OrderId"}],
        )

        merged = manager._merge_columns([contract], [asset])

        iris = {t["iri"] for t in merged[0].business_terms}
        assert iris == {"urn:bt:OrderId", "urn:bt:Pii"}


class TestMatchesSearch:
    """_matches_search: every field branch is reachable."""

    @pytest.fixture
    def col(self) -> ColumnDictionaryEntry:
        return _entry(
            column_name="customer_id",
            table_full_name="main.sales.customers",
            table_name="customers",
            schema_name="sales",
            catalog_name="main",
            source="both",
            description="The customer identifier",
            column_label="Customer ID",
            system_name="warehouse",
            contract_name="customers-v1",
            business_terms=[{"iri": "urn:bt:CustomerId", "label": "CustomerIdentifier"}],
        )

    @pytest.mark.parametrize(
        "query",
        [
            "customer_id",        # column_name
            "identifier",          # description
            "customer id",         # column_label
            "customers",           # table_name
            "customers-v1",        # contract_name
            "warehouse",           # system_name
            "main",                # catalog_name
            "sales",               # schema_name
            "customeridentifier",  # business term label
            "urn:bt:customerid",   # business term IRI (prefix match)
        ],
    )
    def test_each_field_branch_matches(self, manager, col, query):
        assert manager._matches_search(col, query.lower()) is True

    def test_miss_returns_false(self, manager, col):
        assert manager._matches_search(col, "nonexistent_token") is False


def _seed_columns() -> tuple[List[ColumnDictionaryEntry], List[ColumnDictionaryEntry]]:
    """Build a small fixture set spanning two systems / two catalogs."""
    contract = [
        _entry(
            column_name=f"c_{i}",
            table_full_name=f"contracts.orders_{i}",
            schema_name="orders",
            catalog_name="contracts",
            table_type="CONTRACT",
            source="contract",
        )
        for i in range(7)
    ]
    asset = [
        _entry(
            column_name=f"a_{i}",
            table_full_name=f"main.sales.tbl_{i}",
            schema_name="sales",
            catalog_name="main",
            table_type="TABLE",
            source="asset",
            system_name="warehouse",
        )
        for i in range(8)
    ]
    # One overlap that should collapse to a single 'both' row
    contract.append(_entry(
        column_name="shared_col",
        table_full_name="main.sales.tbl_0",
        schema_name="sales",
        catalog_name="main",
        source="contract",
    ))
    asset.append(_entry(
        column_name="shared_col",
        table_full_name="main.sales.tbl_0",
        schema_name="sales",
        catalog_name="main",
        source="asset",
        system_name="warehouse",
    ))
    return contract, asset


class TestPaginationAndFilters:
    """get_all_columns: pagination math and filter composition."""

    def _patch_extractors(self, manager, monkeypatch):
        contract, asset = _seed_columns()
        monkeypatch.setattr(manager, "_get_columns_from_contracts", lambda: contract)
        monkeypatch.setattr(manager, "_get_columns_from_assets", lambda: asset)
        # total unique columns after merge: 7 contract-only + 8 asset-only + 1 'both' = 16
        return 16

    def test_page_one_returns_first_slice(self, manager, monkeypatch):
        total = self._patch_extractors(manager, monkeypatch)

        resp = manager.get_all_columns(offset=0, limit=5)

        assert resp.column_count == total
        assert len(resp.columns) == 5
        assert resp.has_more is True
        assert resp.offset == 0
        assert resp.limit == 5

    def test_offset_skips_correct_number(self, manager, monkeypatch):
        total = self._patch_extractors(manager, monkeypatch)

        first_page = manager.get_all_columns(offset=0, limit=5).columns
        second_page = manager.get_all_columns(offset=5, limit=5).columns

        # No overlap between consecutive pages
        first_keys = {(c.table_full_name, c.column_name) for c in first_page}
        second_keys = {(c.table_full_name, c.column_name) for c in second_page}
        assert first_keys.isdisjoint(second_keys)
        # Combined coverage equals what a flat slice would produce
        assert len(first_keys | second_keys) == 10
        assert total == 16  # sanity

    def test_has_more_false_at_boundary(self, manager, monkeypatch):
        total = self._patch_extractors(manager, monkeypatch)

        resp = manager.get_all_columns(offset=total - 3, limit=5)

        assert len(resp.columns) == 3
        assert resp.has_more is False

    def test_catalog_filter_narrows_to_one_catalog(self, manager, monkeypatch):
        self._patch_extractors(manager, monkeypatch)

        resp = manager.get_all_columns(catalog_filter="contracts", offset=0, limit=100)

        assert resp.column_count == 7  # contract-only entries
        assert all(c.catalog_name == "contracts" for c in resp.columns)

    def test_combined_filters_compose(self, manager, monkeypatch):
        self._patch_extractors(manager, monkeypatch)

        resp = manager.get_all_columns(
            catalog_filter="main",
            schema_filter="sales",
            asset_type_filter="TABLE",
            system_filter="warehouse",
            offset=0,
            limit=100,
        )

        # 8 asset-only + 1 'both' that lives under main.sales -> 9 columns
        assert resp.column_count == 9
        assert all(c.catalog_name == "main" for c in resp.columns)
        assert all(c.schema_name == "sales" for c in resp.columns)
        assert all(c.system_name == "warehouse" for c in resp.columns)

    def test_search_pagination_total_count_is_full_match_set(self, manager, monkeypatch):
        self._patch_extractors(manager, monkeypatch)

        # All asset rows + the 'both' row carry system_name='warehouse' (contract-only
        # rows don't), so the search hits exactly that 9-row subset.
        resp = manager.search_columns(query="warehouse", offset=0, limit=3)

        assert resp.total_count == 9
        assert len(resp.columns) == 3
        assert resp.has_more is True
