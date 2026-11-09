"""Regression tests for ConnectionsManager.list_connector_types().

Covers the bug (cat-conn-issue) where the "Add Connection" dropdown hid the
fully implemented BigQuery connector.

Root cause: the dropdown was gated on the connector's runtime ``is_available``
property. For BigQuery, ``is_available`` performs a live client check that
fails when no project/credentials are configured yet — which is always true at
startup — so BigQuery was filtered out even though it is a real, selectable
connector. The fix gates the dropdown on the static ``is_selectable`` class
flag instead; only stub/mockup connectors set that False.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.controller.connections_manager import ConnectionsManager


class _FakeConnector:
    """Minimal stand-in exposing the attributes list_connector_types reads."""

    def __init__(self, ctype, *, is_selectable, is_available):
        self.connector_type = ctype
        self.display_name = ctype.title()
        self.description = f"{ctype} connector"
        self.is_selectable = is_selectable
        self.is_available = is_available
        self.capabilities = SimpleNamespace(
            can_list_assets=True,
            can_get_metadata=True,
            can_get_sample_data=False,
        )


@pytest.fixture
def fake_registry():
    """A registry whose connectors mirror the real availability/selectability mix.

    - databricks: default, selectable, but not "available" (no ws client)
    - bigquery:   selectable, NOT available (no project/creds) -> must appear
    - snowflake:  stub, not selectable -> must be hidden
    """
    connectors = {
        "databricks": _FakeConnector("databricks", is_selectable=True, is_available=False),
        "bigquery": _FakeConnector("bigquery", is_selectable=True, is_available=False),
        "snowflake": _FakeConnector("snowflake", is_selectable=False, is_available=False),
    }

    registry = MagicMock()
    registry._default_connector_type = "databricks"
    registry.list_registered.return_value = list(connectors.keys())
    registry.get_connector.side_effect = lambda ct: connectors[ct]
    return registry


def _list_types(fake_registry):
    manager = ConnectionsManager(db=MagicMock())
    with patch(
        "src.controller.connections_manager.get_registry",
        return_value=fake_registry,
    ), patch(
        "src.controller.connections_manager._get_config_classes",
        return_value={},
    ):
        return manager.list_connector_types()


def test_bigquery_listed_despite_unavailable(fake_registry):
    """BigQuery is selectable, so it appears even though is_available is False."""
    types = {t["connector_type"] for t in _list_types(fake_registry)}
    assert "bigquery" in types


def test_default_databricks_always_listed(fake_registry):
    types = {t["connector_type"] for t in _list_types(fake_registry)}
    assert "databricks" in types


def test_stub_connectors_hidden(fake_registry):
    """Non-selectable stubs (snowflake here) are filtered out of the dropdown."""
    types = {t["connector_type"] for t in _list_types(fake_registry)}
    assert "snowflake" not in types


def test_metadata_populated_from_connector(fake_registry):
    bq = next(t for t in _list_types(fake_registry) if t["connector_type"] == "bigquery")
    assert bq["display_name"] == "Bigquery"
    assert bq["description"] == "bigquery connector"
    assert bq["capabilities"]["can_list_assets"] is True
    assert bq["capabilities"]["can_get_sample_data"] is False
