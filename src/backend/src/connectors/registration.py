"""Registers the built-in asset connectors in the global registry.

Called at app startup and by the connector_sync job: the job runs in its own
process, where nothing else registers them, and a Tableau sync would fail with
"No connector class registered".
"""

from typing import Any

from src.connectors.bigquery import BigQueryConnector
from src.connectors.databricks import DatabricksConnector
from src.connectors.kafka import KafkaConnector
from src.connectors.powerbi import PowerBIConnector
from src.connectors.registry import ConnectorRegistry, get_registry
from src.connectors.snowflake import SnowflakeConnector
from src.connectors.tableau import TableauConnector


def register_asset_connectors(workspace_client: Any) -> ConnectorRegistry:
    """Register the Databricks connector (default) and the other connectors by class."""
    registry = get_registry()

    # Register Databricks/UC connector (primary connector)
    databricks_connector = DatabricksConnector(workspace_client=workspace_client)
    registry.register_instance("databricks", databricks_connector, set_as_default=True)

    # Register additional connectors (lazily instantiated when first accessed)
    registry.register_class("bigquery", BigQueryConnector)
    registry.register_class("snowflake", SnowflakeConnector)
    registry.register_class("kafka", KafkaConnector)
    registry.register_class("powerbi", PowerBIConnector)
    registry.register_class("tableau", TableauConnector)
    return registry
