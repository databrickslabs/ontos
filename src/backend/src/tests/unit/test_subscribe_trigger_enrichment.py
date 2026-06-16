"""Tests for on_subscribe trigger entity_data enrichment.

``DataProductsManager.subscribe`` fires the ``on_subscribe`` trigger
after a subscription row is persisted. The entity_data passed to the
trigger must mirror the access-grant enrichment so webhook templates
can reference ``${entity.catalogs}`` / ``${entity.output_ports}`` on
subscription events too.
"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


def _make_port(name: str, asset_identifier: str | None) -> SimpleNamespace:
    return SimpleNamespace(name=name, asset_identifier=asset_identifier)


def _make_dp_db(ports: list[SimpleNamespace], **kwargs) -> SimpleNamespace:
    defaults = {"id": "prd-123", "name": "customer_360"}
    defaults.update(kwargs)
    return SimpleNamespace(output_ports=ports, **defaults)


class TestSubscribeTriggerEnrichment:
    """Pin the ``on_subscribe`` enrichment shape."""

    @pytest.fixture
    def mock_dp_manager(self, db_session):
        """Build a DataProductsManager with all collaborators mocked."""
        from src.controller.data_products_manager import DataProductsManager

        ws_client = MagicMock()
        notifications_manager = MagicMock()
        tags_manager = MagicMock()

        mgr = DataProductsManager(
            db=db_session,
            ws_client=ws_client,
            notifications_manager=notifications_manager,
            tags_manager=tags_manager,
        )
        return mgr

    def test_subscribe_to_dp_fires_trigger_with_enriched_entity_data(
        self, mock_dp_manager
    ):
        """End-to-end: subscribing fires on_subscribe with output_ports + catalogs."""
        from src.controller import data_products_manager as dpm_module

        # Resolved API model for ``get_product`` — only ``status`` and
        # ``name`` are read by the subscribe flow.
        api_product = SimpleNamespace(
            id="prd-123",
            name="customer_360",
            status="active",
        )

        # Resolved DB model — what the enrichment helper introspects.
        dp_db = _make_dp_db(
            ports=[
                _make_port("orders", "prod.sales.orders"),
                _make_port("customers", "main.marts.customers"),
            ]
        )

        # Capture the on_subscribe call.
        captured = {}

        class FakeTriggerRegistry:
            def on_subscribe(self, **kwargs):
                captured.update(kwargs)
                return []

        # Stub the SQLAlchemy query chain on the manager's own session
        # so we don't need a real ``data_products`` row.
        fake_query = MagicMock()
        fake_query.filter.return_value.first.return_value = dp_db
        mock_dp_manager._db.query = MagicMock(return_value=fake_query)

        with patch.object(
            mock_dp_manager, "get_product", return_value=api_product
        ), patch.object(dpm_module, "subscription_repo") as fake_sub_repo, patch.object(
            mock_dp_manager,
            "_log_subscription_change",
        ), patch(
            "src.common.workflow_triggers.get_trigger_registry",
            return_value=FakeTriggerRegistry(),
        ):
            fake_sub_repo.get_by_product_and_user.return_value = None
            fake_sub_repo.create.return_value = SimpleNamespace(
                id="sub-1",
                product_id="prd-123",
                subscriber_email="alice@example.com",
                subscribed_at=datetime.now(timezone.utc),
                subscription_reason=None,
            )

            mock_dp_manager.subscribe(
                product_id="prd-123",
                subscriber_email="alice@example.com",
                reason="Onboarding analytics dashboard.",
            )

        entity_data = captured["entity_data"]
        assert entity_data["product_id"] == "prd-123"
        assert entity_data["subscriber_email"] == "alice@example.com"
        assert entity_data["reason"] == "Onboarding analytics dashboard."
        assert entity_data["data_product_name"] == "customer_360"
        assert entity_data["catalogs"] == ["main", "prod"]
        assert len(entity_data["output_ports"]) == 2
        assert {p["fqn"] for p in entity_data["output_ports"]} == {
            "prod.sales.orders",
            "main.marts.customers",
        }

    def test_subscribe_to_dp_without_ports_emits_empty_lists(
        self, mock_dp_manager
    ):
        """A DP with no usable ports still fires the trigger with
        well-formed keys (empty lists, not missing keys)."""
        from src.controller import data_products_manager as dpm_module

        api_product = SimpleNamespace(
            id="prd-456",
            name="empty_dp",
            status="active",
        )
        dp_db = _make_dp_db(
            ports=[_make_port("not_uc", "/path/to/notebook")],
            id="prd-456",
            name="empty_dp",
        )

        captured = {}

        class FakeTriggerRegistry:
            def on_subscribe(self, **kwargs):
                captured.update(kwargs)
                return []

        fake_query = MagicMock()
        fake_query.filter.return_value.first.return_value = dp_db
        mock_dp_manager._db.query = MagicMock(return_value=fake_query)

        with patch.object(
            mock_dp_manager, "get_product", return_value=api_product
        ), patch.object(dpm_module, "subscription_repo") as fake_sub_repo, patch.object(
            mock_dp_manager,
            "_log_subscription_change",
        ), patch(
            "src.common.workflow_triggers.get_trigger_registry",
            return_value=FakeTriggerRegistry(),
        ):
            fake_sub_repo.get_by_product_and_user.return_value = None
            fake_sub_repo.create.return_value = SimpleNamespace(
                id="sub-2",
                product_id="prd-456",
                subscriber_email="bob@example.com",
                subscribed_at=datetime.now(timezone.utc),
                subscription_reason=None,
            )

            mock_dp_manager.subscribe(
                product_id="prd-456",
                subscriber_email="bob@example.com",
                reason=None,
            )

        entity_data = captured["entity_data"]
        assert entity_data["output_ports"] == []
        assert entity_data["catalogs"] == []
