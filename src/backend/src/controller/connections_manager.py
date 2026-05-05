"""
Manager for external data platform connections.

Handles CRUD operations on the connections table, instantiates connectors
on demand, and ensures a system Databricks connection exists at startup.
"""

import json as _json
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from src.common.logging import get_logger
from src.connectors.base import AssetConnector, ConnectorConfig
from src.connectors.registry import get_registry
from src.db_models.connections import ConnectionDb
from src.models.connections import ConnectionCreate, ConnectionUpdate, ConnectionResponse
from src.repositories.connections_repository import connections_repo

logger = get_logger(__name__)

SYSTEM_CREATED_BY = "system"

# Maps connector_type -> typed ConnectorConfig subclass
_CONFIG_CLASSES: Optional[Dict[str, Any]] = None


def _get_config_classes() -> Dict[str, Any]:
    global _CONFIG_CLASSES
    if _CONFIG_CLASSES is None:
        from src.connectors.bigquery import BigQueryConnectorConfig
        from src.connectors.snowflake import SnowflakeConnectorConfig
        from src.connectors.kafka import KafkaConnectorConfig
        from src.connectors.powerbi import PowerBIConnectorConfig
        _CONFIG_CLASSES = {
            "bigquery": BigQueryConnectorConfig,
            "snowflake": SnowflakeConnectorConfig,
            "kafka": KafkaConnectorConfig,
            "powerbi": PowerBIConnectorConfig,
        }
    return _CONFIG_CLASSES


# Fields that must not be persisted or returned to clients
_INTERNAL_FIELDS = {"workspace_client", "credentials"}


class ConnectionsManager:
    """Manages external connection records and connector instantiation."""

    def __init__(self, db: Session, workspace_client: Optional[Any] = None):
        self._db = db
        self._ws_client = workspace_client

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def list_connections(
        self, connector_type: Optional[str] = None
    ) -> List[ConnectionResponse]:
        if connector_type:
            rows = connections_repo.get_by_connector_type(self._db, connector_type)
        else:
            rows = connections_repo.get_all(self._db)
        return [ConnectionResponse.model_validate(r) for r in rows]

    def get_connection(self, connection_id: UUID) -> Optional[ConnectionResponse]:
        row = connections_repo.get(self._db, connection_id)
        if row is None:
            return None
        return ConnectionResponse.model_validate(row)

    def create_connection(
        self, data: ConnectionCreate, created_by: Optional[str] = None
    ) -> ConnectionResponse:
        if data.is_default:
            connections_repo.clear_default_for_type(self._db, data.connector_type)

        # Strip internal fields from config before persisting
        clean_config = {k: v for k, v in data.config.items() if k not in _INTERNAL_FIELDS}
        db_obj = ConnectionDb(
            name=data.name,
            connector_type=data.connector_type,
            description=data.description,
            config=clean_config,
            enabled=data.enabled,
            is_default=data.is_default,
            system_asset_id=data.system_asset_id,
            created_by=created_by or "",
        )
        self._db.add(db_obj)
        self._db.commit()
        self._db.refresh(db_obj)
        logger.info(f"Created connection '{data.name}' (type={data.connector_type})")
        return ConnectionResponse.model_validate(db_obj)

    def update_connection(
        self, connection_id: UUID, data: ConnectionUpdate
    ) -> Optional[ConnectionResponse]:
        db_obj = connections_repo.get(self._db, connection_id)
        if db_obj is None:
            return None

        update_data = data.model_dump(exclude_unset=True)

        if update_data.get("is_default"):
            connections_repo.clear_default_for_type(self._db, db_obj.connector_type)

        if "config" in update_data and update_data["config"] is not None:
            update_data["config"] = {
                k: v for k, v in update_data["config"].items() if k not in _INTERNAL_FIELDS
            }

        for field, value in update_data.items():
            setattr(db_obj, field, value)

        self._db.commit()
        self._db.refresh(db_obj)
        logger.info(f"Updated connection '{db_obj.name}' (id={connection_id})")
        return ConnectionResponse.model_validate(db_obj)

    def delete_connection(self, connection_id: UUID) -> bool:
        db_obj = connections_repo.get(self._db, connection_id)
        if db_obj is None:
            return False
        if db_obj.created_by == SYSTEM_CREATED_BY:
            raise ValueError("System connections cannot be deleted")
        self._db.delete(db_obj)
        self._db.commit()
        logger.info(f"Deleted connection '{db_obj.name}' (id={connection_id})")
        return True

    # ------------------------------------------------------------------
    # Connector instantiation
    # ------------------------------------------------------------------

    def get_connector_for_connection(self, connection_id: UUID) -> Optional[AssetConnector]:
        """Create a connector instance from a connection record."""
        db_obj = connections_repo.get(self._db, connection_id)
        if db_obj is None:
            return None
        return self._build_connector(db_obj)

    def _build_connector(self, db_obj: ConnectionDb) -> AssetConnector:
        registry = get_registry()
        connector_type = db_obj.connector_type
        config_dict = dict(db_obj.config or {})

        # Pre-registered singleton instances (e.g. Databricks) — return directly.
        # Only match explicitly registered instances, not class-created cached ones.
        if connector_type in registry._connector_instances and \
           connector_type not in registry._connector_classes:
            if self._ws_client and connector_type == "databricks":
                from src.connectors.databricks import DatabricksConnector
                return DatabricksConnector(workspace_client=self._ws_client)
            return registry._connector_instances[connector_type]

        # Inject workspace client for connectors that need it
        if connector_type == "bigquery" and self._ws_client:
            config_dict["workspace_client"] = self._ws_client

        config_classes = _get_config_classes()
        config_cls = config_classes.get(connector_type, ConnectorConfig)
        typed_config = config_cls(**config_dict)

        if connector_type in registry._connector_classes:
            connector_class = registry._connector_classes[connector_type]
            return connector_class(typed_config)

        raise ValueError(f"No connector class registered for type '{connector_type}'")

    # ------------------------------------------------------------------
    # Test connection
    # ------------------------------------------------------------------

    def test_connection(self, connection_id: UUID) -> Dict[str, Any]:
        db_obj = connections_repo.get(self._db, connection_id)
        if db_obj is None:
            return {"healthy": False, "error": "Connection not found"}

        try:
            connector = self._build_connector(db_obj)
            result = connector.health_check()
            result["connection_name"] = db_obj.name
            return result
        except Exception as exc:
            logger.error(f"Error testing connection '{db_obj.name}': {exc}", exc_info=True)
            return {
                "connector_type": db_obj.connector_type,
                "connection_name": db_obj.name,
                "healthy": False,
                "error": str(exc),
            }

    # ------------------------------------------------------------------
    # Connector types metadata
    # ------------------------------------------------------------------

    def list_connector_types(self) -> List[Dict[str, Any]]:
        """Return metadata about all registered connector types."""
        registry = get_registry()
        result = []
        for ctype in registry.list_registered():
            info: Dict[str, Any] = {
                "connector_type": ctype,
                "display_name": ctype.title(),
                "description": "",
                "capabilities": {},
                "config_fields": [],
            }
            try:
                connector = registry.get_connector(ctype)
                info["display_name"] = connector.display_name
                info["description"] = connector.description
                info["capabilities"] = {
                    "can_list_assets": connector.capabilities.can_list_assets,
                    "can_get_metadata": connector.capabilities.can_get_metadata,
                    "can_get_sample_data": connector.capabilities.can_get_sample_data,
                }
            except Exception:
                pass

            # Config field hints for the UI
            config_cls = _get_config_classes().get(ctype)
            if config_cls:
                for fname, finfo in config_cls.model_fields.items():
                    if fname in _INTERNAL_FIELDS:
                        continue
                    info["config_fields"].append({
                        "name": fname,
                        "required": finfo.is_required(),
                        "description": finfo.description or "",
                    })

            result.append(info)
        return result

    # ------------------------------------------------------------------
    # System connections (startup helpers)
    # ------------------------------------------------------------------

    def ensure_system_databricks_connection(self) -> None:
        """Create the built-in Databricks UC connection if it doesn't exist."""
        existing = connections_repo.get_by_name(self._db, "Databricks UC")
        if existing:
            logger.debug("System Databricks UC connection already exists")
            return

        db_obj = ConnectionDb(
            name="Databricks UC",
            connector_type="databricks",
            description="Default Unity Catalog connection (auto-configured from environment)",
            config={},
            enabled=True,
            is_default=True,
            created_by=SYSTEM_CREATED_BY,
        )
        self._db.add(db_obj)
        self._db.commit()
        logger.info("Created system Databricks UC connection")

    def migrate_from_app_settings(self) -> int:
        """Migrate legacy CONNECTOR_CONFIG_* entries from app_settings to connections table.

        Returns the number of connections migrated.
        """
        from src.repositories.app_settings_repository import app_settings_repo

        prefix = "CONNECTOR_CONFIG_"
        all_settings = app_settings_repo.get_all(self._db)
        migrated = 0

        for key, value in all_settings.items():
            if not key.startswith(prefix) or not value:
                continue
            connector_type = key[len(prefix):]

            # Skip if a connection for this type already exists
            existing = connections_repo.get_by_connector_type(self._db, connector_type)
            if existing:
                logger.debug(f"Connection for '{connector_type}' already exists, skipping migration")
                continue

            try:
                config_dict = _json.loads(value)
                # Strip internal fields
                config_dict = {k: v for k, v in config_dict.items() if k not in _INTERNAL_FIELDS}

                db_obj = ConnectionDb(
                    name=f"{connector_type.title()}",
                    connector_type=connector_type,
                    description="",
                    config=config_dict,
                    enabled=True,
                    is_default=False,
                    created_by="",
                )
                self._db.add(db_obj)
                self._db.commit()
                migrated += 1

                # Remove the old key
                app_settings_repo.delete(self._db, key)
                logger.info(f"Migrated connector config '{connector_type}' to connections table")
            except Exception as exc:
                logger.warning(f"Failed to migrate connector config '{connector_type}': {exc}")

        return migrated
