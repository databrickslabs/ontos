"""Unit tests for ConnectionsManager.list_connector_types() availability filtering.

Verifies that connector types whose connector reports ``is_available is False``
(e.g. the Snowflake/PowerBI/Kafka mockup stubs) are excluded from the list
surfaced to the Add Connection dropdown, while available connectors and the
default connector type are retained.
"""

from types import SimpleNamespace

import src.controller.connections_manager as cm
from src.controller.connections_manager import ConnectionsManager


class _FakeCapabilities:
    can_list_assets = True
    can_get_metadata = True
    can_get_sample_data = False


class _FakeConnector:
    def __init__(self, ctype: str, is_available: bool):
        self.connector_type = ctype
        self.display_name = ctype.title()
        self.description = f"{ctype} connector"
        self._is_available = is_available
        self.capabilities = _FakeCapabilities()

    @property
    def is_available(self) -> bool:
        return self._is_available


class _FakeRegistry:
    def __init__(self, connectors, default_type=None):
        self._connectors = connectors
        self._default_connector_type = default_type

    def list_registered(self):
        return sorted(self._connectors.keys())

    def get_connector(self, ctype):
        return self._connectors[ctype]


def _make_manager(monkeypatch, registry):
    monkeypatch.setattr(cm, "get_registry", lambda: registry)
    # Avoid pulling in connector config classes / pydantic models in this test.
    monkeypatch.setattr(cm, "_get_config_classes", lambda: {})
    return ConnectionsManager(db=None)


def test_unavailable_stub_connectors_are_excluded(monkeypatch):
    registry = _FakeRegistry(
        connectors={
            "databricks": _FakeConnector("databricks", is_available=True),
            "bigquery": _FakeConnector("bigquery", is_available=True),
            "snowflake": _FakeConnector("snowflake", is_available=False),
            "powerbi": _FakeConnector("powerbi", is_available=False),
            "kafka": _FakeConnector("kafka", is_available=False),
        },
        default_type="databricks",
    )
    manager = _make_manager(monkeypatch, registry)

    types = {info["connector_type"] for info in manager.list_connector_types()}

    assert "databricks" in types
    assert "bigquery" in types
    assert "snowflake" not in types
    assert "powerbi" not in types
    assert "kafka" not in types


def test_default_connector_is_kept_even_when_unavailable(monkeypatch):
    # The default connector path must never be hidden, even if is_available is
    # momentarily False (e.g. workspace client not yet attached).
    registry = _FakeRegistry(
        connectors={
            "databricks": _FakeConnector("databricks", is_available=False),
            "snowflake": _FakeConnector("snowflake", is_available=False),
        },
        default_type="databricks",
    )
    manager = _make_manager(monkeypatch, registry)

    types = {info["connector_type"] for info in manager.list_connector_types()}

    assert types == {"databricks"}
