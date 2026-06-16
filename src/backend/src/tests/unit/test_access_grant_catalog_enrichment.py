"""Tests for access-grant request entity_data enrichment.

When an access-grant request targets a data product, the
``AccessGrantsManager.create_request`` flow enriches the trigger's
``entity_data`` with fields parsed from the DP's output ports so
webhook ``body_template``s can reference ``${entity.output_ports}`` and
``${entity.catalogs}`` directly.

These tests pin the enrichment shape and the "caller wins" override
discipline.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.common.workflow_triggers import enrich_entity_data_with_data_product
from src.db_models.access_grants import AccessGrantRequestStatus


def _make_port(name: str, asset_identifier: str | None) -> SimpleNamespace:
    """Build a minimal stand-in for ``OutputPortDb`` for the helper."""
    return SimpleNamespace(name=name, asset_identifier=asset_identifier)


def _make_dp(ports: list[SimpleNamespace], **kwargs) -> SimpleNamespace:
    """Build a minimal stand-in for ``DataProductDb`` for the helper."""
    defaults = {"id": "prd-123", "name": "customer_360"}
    defaults.update(kwargs)
    return SimpleNamespace(output_ports=ports, **defaults)


class TestEnrichEntityDataWithDataProduct:
    """Pin the helper's shape contract.

    The helper is invoked from both ``AccessGrantsManager.create_request``
    and ``DataProductsManager.subscribe`` — tested here once.
    """

    def test_multi_catalog_dp_emits_dedup_sorted_catalogs(self):
        dp = _make_dp(
            ports=[
                _make_port("orders", "prod.sales.orders"),
                _make_port("customers", "main.marts.customers"),
                _make_port("returns", "prod.sales.returns"),
            ]
        )
        entity_data = {}

        enrich_entity_data_with_data_product(entity_data, dp)

        # Catalogs: dedup + sorted alphabetically.
        assert entity_data["catalogs"] == ["main", "prod"]

        # Output ports: one per usable identifier, in source order.
        assert len(entity_data["output_ports"]) == 3
        assert entity_data["output_ports"][0] == {
            "name": "orders",
            "catalog": "prod",
            "schema": "sales",
            "table": "orders",
            "fqn": "prod.sales.orders",
        }
        assert entity_data["output_ports"][1]["catalog"] == "main"
        assert entity_data["output_ports"][2]["table"] == "returns"

    def test_skips_ports_without_usable_asset_identifier(self):
        """Ports without a parseable identifier are silently dropped.

        A workflow author would rather see only the usable rows than
        half-formed records with empty ``catalog`` fields.
        """
        dp = _make_dp(
            ports=[
                _make_port("usable", "main.marts.customers"),
                _make_port("missing", None),
                _make_port("not_uc", "/path/to/notebook"),
                _make_port("too_many_parts", "a.b.c.d"),
                _make_port("empty", ""),
            ]
        )
        entity_data = {}

        enrich_entity_data_with_data_product(entity_data, dp)

        # Only the parseable port survives.
        assert len(entity_data["output_ports"]) == 1
        assert entity_data["output_ports"][0]["fqn"] == "main.marts.customers"
        assert entity_data["catalogs"] == ["main"]

    def test_caller_supplied_keys_are_preserved(self):
        """If the caller pre-populates ``output_ports`` (e.g. from a
        wizard override), the helper must not clobber the value.
        Same goes for ``catalogs``.
        """
        dp = _make_dp(ports=[_make_port("orders", "prod.sales.orders")])
        custom_ports = [{"name": "custom", "catalog": "x", "schema": "y", "table": "z", "fqn": "x.y.z"}]
        entity_data = {
            "output_ports": custom_ports,
            "catalogs": ["override"],
        }

        enrich_entity_data_with_data_product(entity_data, dp)

        assert entity_data["output_ports"] is custom_ports
        assert entity_data["catalogs"] == ["override"]

    def test_empty_dp_yields_empty_lists(self):
        """A DP with no output ports still produces well-formed keys."""
        dp = _make_dp(ports=[])
        entity_data = {}

        enrich_entity_data_with_data_product(entity_data, dp)

        assert entity_data["output_ports"] == []
        assert entity_data["catalogs"] == []

    def test_none_data_product_is_noop(self):
        """Passing ``None`` (DP not found) must not raise."""
        entity_data = {"existing": "value"}

        enrich_entity_data_with_data_product(entity_data, None)

        assert entity_data == {"existing": "value"}


class TestAccessGrantRequestEnrichment:
    """Integration: the create_request flow wires the helper in correctly."""

    def test_create_request_for_dp_enriches_entity_data(self, db_session, monkeypatch):
        """End-to-end: a DP-targeted request results in a trigger
        firing with ``output_ports`` + ``catalogs`` in entity_data.
        """
        from src.controller.access_grants_manager import AccessGrantsManager
        from src.models.access_grants import (
            AccessGrantRequestCreate,
            PermissionLevel,
        )

        # Stub the DP repo so we don't depend on DB schema for ports.
        fake_dp = _make_dp(
            ports=[
                _make_port("orders", "prod.sales.orders"),
                _make_port("customers", "main.marts.customers"),
            ],
            id="prd-123",
            name="customer_360",
        )

        # Capture the entity_data passed to the trigger.
        captured = {}

        class FakeTriggerRegistry:
            def on_request_access(self, **kwargs):
                captured.update(kwargs)
                return []

        # Stub the access-grant request repo so we don't need its
        # actual DB schema either — we only care that the trigger
        # fires with the right entity_data. Fields here must satisfy
        # ``AccessGrantRequestResponse.model_validate`` at the end of
        # ``create_request``.
        fake_request = SimpleNamespace(
            id=uuid.uuid4(),
            requester_email="alice@example.com",
            entity_type="data_product",
            entity_id="prd-123",
            entity_name="customer_360",
            requested_duration_days=30,
            permission_level="READ",
            reason="Need to validate Q3 churn metrics.",
            status=AccessGrantRequestStatus.PENDING.value,
            created_at=datetime.now(timezone.utc),
            handled_at=None,
            handled_by=None,
            admin_message=None,
        )

        with patch(
            "src.controller.access_grants_manager.access_grant_request_repo"
        ) as fake_request_repo, patch(
            "src.repositories.data_products_repository.data_product_repo"
        ) as fake_dp_repo, patch(
            "src.common.workflow_triggers.get_trigger_registry",
            return_value=FakeTriggerRegistry(),
        ):
            fake_request_repo.check_existing_pending.return_value = None
            fake_request_repo.create.return_value = fake_request
            fake_dp_repo.get.return_value = fake_dp

            mgr = AccessGrantsManager()
            mgr._request_repo = fake_request_repo

            # Also stub grant_repo + config_repo (read-side).
            mgr._grant_repo = MagicMock()
            mgr._grant_repo.check_active_grant.return_value = None
            mgr._config_repo = MagicMock()
            mgr._config_repo.get_by_entity_type.return_value = None

            payload = AccessGrantRequestCreate(
                entity_type="data_product",
                entity_id="prd-123",
                entity_name="customer_360",
                requested_duration_days=30,
                permission_level=PermissionLevel.READ,
                reason="Need to validate Q3 churn metrics.",
            )

            mgr.create_request(db_session, "alice@example.com", payload)

        # The trigger fired with enrichment baked in.
        entity_data = captured["entity_data"]
        assert entity_data["data_product_name"] == "customer_360"
        assert entity_data["catalogs"] == ["main", "prod"]
        assert len(entity_data["output_ports"]) == 2
        fqns = [p["fqn"] for p in entity_data["output_ports"]]
        assert "prod.sales.orders" in fqns
        assert "main.marts.customers" in fqns
