"""ConnectionsManager injects the workspace client into connector configs that declare it."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src.connectors.kafka import KafkaConnector
from src.connectors.tableau import TableauConnector
from src.controller.connections_manager import ConnectionsManager


def _registry():
    return SimpleNamespace(
        _connector_instances={},
        _connector_classes={"tableau": TableauConnector, "kafka": KafkaConnector},
    )


def test_workspace_client_is_injected_for_configs_with_the_field():
    ws = MagicMock()
    row = SimpleNamespace(connector_type="tableau", config={"server_url": "https://t", "secret_scope": "s", "secret_key": "k"})
    with patch("src.controller.connections_manager.get_registry", _registry):
        connector = ConnectionsManager(db=MagicMock(), workspace_client=ws)._build_connector(row)
    assert connector._config.workspace_client is ws


def test_configs_without_the_field_get_no_workspace_client():
    row = SimpleNamespace(connector_type="kafka", config={})
    with patch("src.controller.connections_manager.get_registry", _registry):
        connector = ConnectionsManager(db=MagicMock(), workspace_client=MagicMock())._build_connector(row)
    assert "workspace_client" not in type(connector._config).model_fields
