"""Unit tests for AssetsManager.resolve_accessible_asset_ids (#583)."""

import uuid
from unittest.mock import MagicMock

import pytest

from src.controller.assets_manager import AssetsManager


class TestResolveAccessibleAssetIds:

    @pytest.fixture
    def manager(self):
        return AssetsManager(ontology_schema_manager=None)

    def _make_product(self, product_id: str, status: str):
        p = MagicMock()
        p.id = product_id
        p.status = status
        return p

    def test_filters_to_consumer_visible_statuses(self, manager):
        """Only asset IDs for active/deprecated DPs are returned; draft excluded."""
        db = MagicMock()

        active_id = str(uuid.uuid4())
        deprecated_id = str(uuid.uuid4())
        draft_id = str(uuid.uuid4())

        active_assets = [uuid.uuid4(), uuid.uuid4()]
        deprecated_assets = [uuid.uuid4()]
        draft_assets = [uuid.uuid4()]

        products = [
            self._make_product(active_id, "active"),
            self._make_product(deprecated_id, "deprecated"),
            self._make_product(draft_id, "draft"),
        ]

        def fake_list_linked(db, *, product_ids, port_ids=None):
            result = set()
            for pid in product_ids:
                if pid == active_id:
                    result.update(active_assets)
                elif pid == deprecated_id:
                    result.update(deprecated_assets)
                elif pid == draft_id:
                    result.update(draft_assets)
            return result

        mock_dpm = MagicMock()
        mock_dpm.list_products.return_value = products
        mock_dpm.list_linked_asset_ids_for_products.side_effect = fake_list_linked

        result = manager.resolve_accessible_asset_ids(
            db, data_products_manager=mock_dpm, is_admin=False,
        )

        expected = set(active_assets) | set(deprecated_assets)
        assert set(result) == expected
        for aid in draft_assets:
            assert aid not in result
        mock_dpm.list_products.assert_called_once_with(skip=0, limit=10_000, is_admin=True)

    def test_admin_returns_none(self, manager):
        """Admin callers get None (no filter); list_products is never called."""
        db = MagicMock()
        mock_dpm = MagicMock()

        result = manager.resolve_accessible_asset_ids(
            db, data_products_manager=mock_dpm, is_admin=True,
        )

        assert result is None
        mock_dpm.list_products.assert_not_called()

    def test_no_visible_products_returns_empty(self, manager):
        """Returns empty when all DPs are in non-consumer-visible statuses."""
        db = MagicMock()
        mock_dpm = MagicMock()
        mock_dpm.list_products.return_value = [
            self._make_product(str(uuid.uuid4()), "draft"),
            self._make_product(str(uuid.uuid4()), "proposed"),
        ]

        result = manager.resolve_accessible_asset_ids(
            db, data_products_manager=mock_dpm, is_admin=False,
        )

        assert list(result) == []
        mock_dpm.list_linked_asset_ids_for_products.assert_not_called()

    def test_list_products_exception_returns_empty(self, manager):
        """Returns empty (no exception) when list_products raises."""
        db = MagicMock()
        mock_dpm = MagicMock()
        mock_dpm.list_products.side_effect = RuntimeError("DB down")

        result = manager.resolve_accessible_asset_ids(
            db, data_products_manager=mock_dpm, is_admin=False,
        )

        assert list(result) == []
