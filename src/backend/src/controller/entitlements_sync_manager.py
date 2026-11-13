from datetime import datetime, timezone
from typing import List, Optional

import yaml

from src.common.workspace_client import get_workspace_client
from src.models.entitlements_sync import EntitlementSyncConfig

from src.common.logging import get_logger
logger = get_logger(__name__)


class EntitlementsSyncManager:
    def __init__(self):
        self.configs: List[EntitlementSyncConfig] = []
        # Set a shorter timeout for API calls to prevent blocking
        self.workspace_client = get_workspace_client(timeout=10)

    def load_from_yaml(self, yaml_path: str) -> None:
        """Load sync configurations from a YAML file"""
        try:
            with open(yaml_path) as f:
                data = yaml.safe_load(f)
                self.configs = [EntitlementSyncConfig(**config) for config in data.get('configs', [])]
                logger.info(f"Loaded {len(self.configs)} sync configurations from {yaml_path}")
        except Exception as e:
            logger.exception(f"Error loading sync configurations from {yaml_path}: {e}")
            self.configs = []

    def get_configs(self) -> List[EntitlementSyncConfig]:
        """Get all sync configurations"""
        return self.configs

    def get_config(self, config_id: str) -> Optional[EntitlementSyncConfig]:
        """Get a specific sync configuration by ID"""
        return next((config for config in self.configs if config.id == config_id), None)

    def create_config(self, config: EntitlementSyncConfig) -> EntitlementSyncConfig:
        """Create a new sync configuration"""
        config.created_at = datetime.now(timezone.utc)
        config.updated_at = datetime.now(timezone.utc)
        self.configs.append(config)
        return config

    def update_config(self, config_id: str, config: EntitlementSyncConfig) -> Optional[EntitlementSyncConfig]:
        """Update an existing sync configuration"""
        for i, existing_config in enumerate(self.configs):
            if existing_config.id == config_id:
                config.updated_at = datetime.now(timezone.utc)
                self.configs[i] = config
                return config
        return None

    def delete_config(self, config_id: str) -> bool:
        """Delete a sync configuration"""
        initial_length = len(self.configs)
        self.configs = [config for config in self.configs if config.id != config_id]
        return len(self.configs) < initial_length

    def get_connections(self) -> List[dict]:
        """Get available Unity Catalog connections"""
        try:
            # Use the cached connections property
            connections = self.workspace_client.connections.list()
            return [
                {
                    "id": conn.name,
                    "name": conn.name,
                    "type": conn.connection_type,
                    "provider": conn.options.get("provider", "") if conn.options else ""
                }
                for conn in connections
            ]
        except Exception as e:
            logger.exception(f"Error fetching connections: {e}")
            return []

    def get_catalogs(self) -> List[str]:
        """Get available Unity Catalog catalogs"""
        try:
            # Use the cached catalogs property
            catalogs = self.workspace_client.catalogs.list()
            return [catalog.name for catalog in catalogs]
        except Exception as e:
            logger.exception(f"Error fetching catalogs: {e}")
            return []
