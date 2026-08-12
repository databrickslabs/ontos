"""
Asset Connector Base Classes

This module defines the abstract base class for asset connectors and
supporting models. All platform-specific connectors must inherit from
AssetConnector and implement its abstract methods.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Type

from pydantic import BaseModel, Field

from src.models.assets import (
    AssetInfo,
    AssetMetadata,
    AssetValidationResult,
    SampleData,
    UnifiedAssetType,
)
from src.common.logging import get_logger

logger = get_logger(__name__)


# ============================================================================
# Connector Configuration
# ============================================================================

class ConnectorConfig(BaseModel):
    """
    Configuration for a connector instance.
    
    Each connector type may extend this with platform-specific configuration.
    """
    enabled: bool = Field(True, description="Whether this connector is enabled")
    timeout_seconds: int = Field(30, description="Default timeout for operations")
    max_results: int = Field(1000, description="Maximum results to return from list operations")
    cache_ttl_seconds: int = Field(300, description="Cache TTL for metadata")
    
    # Connection settings (platform-specific connectors may use these)
    host: Optional[str] = Field(None, description="Host/endpoint")
    port: Optional[int] = Field(None, description="Port")
    database: Optional[str] = Field(None, description="Default database/catalog")
    schema_name: Optional[str] = Field(None, alias="schema", description="Default schema")
    
    # Authentication (platform-specific)
    auth_type: Optional[str] = Field(None, description="Authentication type")
    credentials: Dict[str, Any] = Field(default_factory=dict, description="Credentials (encrypted)")
    
    # Additional properties
    properties: Dict[str, Any] = Field(default_factory=dict, description="Additional properties")
    
    model_config = {"from_attributes": True, "populate_by_name": True}


# ============================================================================
# Connector Capabilities
# ============================================================================

@dataclass
class ConnectorCapabilities:
    """
    Declares what operations a connector supports.
    
    This allows the system to gracefully handle connectors that don't
    support certain operations (e.g., sample data, statistics).
    """
    # Core capabilities
    can_list_assets: bool = True
    can_get_metadata: bool = True
    can_validate_exists: bool = True
    
    # Extended capabilities
    can_get_schema: bool = True
    can_get_sample_data: bool = False
    can_get_statistics: bool = False
    can_get_lineage: bool = False
    can_get_permissions: bool = False
    
    # Write capabilities (for future use)
    can_create_assets: bool = False
    can_update_assets: bool = False
    can_delete_assets: bool = False
    
    # Supported asset types
    supported_asset_types: List[UnifiedAssetType] = field(default_factory=list)
    
    def supports(self, capability: str) -> bool:
        """Check if a capability is supported."""
        return getattr(self, capability, False)


# ============================================================================
# List Options
# ============================================================================

class ListAssetsOptions(BaseModel):
    """Options for listing assets."""
    path: Optional[str] = Field(None, description="Path/prefix to filter by")
    asset_types: Optional[List[UnifiedAssetType]] = Field(None, description="Filter by asset types")
    search_term: Optional[str] = Field(None, description="Search term for filtering")
    limit: int = Field(100, ge=1, le=10000, description="Maximum results to return")
    offset: int = Field(0, ge=0, description="Offset for pagination")
    include_hidden: bool = Field(False, description="Include hidden/system assets")
    
    model_config = {"from_attributes": True}


# ============================================================================
# Abstract Base Connector
# ============================================================================

class AssetConnector(ABC):
    """
    Abstract base class for asset connectors.
    
    Each platform-specific connector (Databricks, Snowflake, Kafka, etc.)
    must inherit from this class and implement its abstract methods.
    
    Example:
        class DatabricksConnector(AssetConnector):
            connector_type = "databricks"
            
            def list_assets(self, options):
                # Implementation
                pass
    """
    
    # -------------------------------------------------------------------------
    # Class-level attributes (must be set by subclasses)
    # -------------------------------------------------------------------------
    
    # Connector type identifier (must match ODCS server types)
    connector_type: str = "unknown"
    
    # Human-readable display name
    display_name: str = "Unknown Connector"
    
    # Description
    description: str = "Base connector class"

    # Whether this connector type is offered in the "Add Connection" UI.
    # This is a static, implementation-status flag — distinct from the runtime
    # ``is_available`` check (which reflects whether a *configured* connection
    # can currently reach its backend). Stub/mockup connectors set this False.
    is_selectable: bool = True

    # -------------------------------------------------------------------------
    # Instance attributes
    # -------------------------------------------------------------------------
    
    def __init__(self, config: Optional[ConnectorConfig] = None):
        """
        Initialize the connector.
        
        Args:
            config: Optional configuration for the connector
        """
        self._config = config or ConnectorConfig()
        self._capabilities: Optional[ConnectorCapabilities] = None
        logger.info(f"Initialized {self.connector_type} connector")
    
    @property
    def config(self) -> ConnectorConfig:
        """Get the connector configuration."""
        return self._config
    
    @property
    def capabilities(self) -> ConnectorCapabilities:
        """
        Get the capabilities of this connector.
        
        Subclasses should override _get_capabilities() to return
        their specific capabilities.
        """
        if self._capabilities is None:
            self._capabilities = self._get_capabilities()
        return self._capabilities
    
    def _get_capabilities(self) -> ConnectorCapabilities:
        """
        Return the capabilities of this connector.
        
        Subclasses should override this to declare their capabilities.
        """
        return ConnectorCapabilities()
    
    @property
    def is_available(self) -> bool:
        """
        Check if the connector is available and properly configured.
        
        Subclasses should override this to check connection health.
        """
        return self._config.enabled
    
    # -------------------------------------------------------------------------
    # Abstract Methods - Must be implemented by subclasses
    # -------------------------------------------------------------------------
    
    @abstractmethod
    def list_assets(
        self,
        options: Optional[ListAssetsOptions] = None
    ) -> List[AssetInfo]:
        """
        List assets available through this connector.
        
        Args:
            options: Optional filtering and pagination options
            
        Returns:
            List of AssetInfo objects
            
        Raises:
            ConnectionError: If the connector cannot connect
            PermissionError: If access is denied
        """
        pass
    
    @abstractmethod
    def get_asset_metadata(self, identifier: str) -> Optional[AssetMetadata]:
        """
        Get detailed metadata for a specific asset.
        
        Args:
            identifier: Asset identifier (FQN, path, or ID)
            
        Returns:
            AssetMetadata if found, None otherwise
            
        Raises:
            ConnectionError: If the connector cannot connect
            PermissionError: If access is denied
        """
        pass
    
    @abstractmethod
    def validate_asset_exists(self, identifier: str) -> AssetValidationResult:
        """
        Validate that an asset exists.
        
        This is a lightweight check compared to get_asset_metadata.
        
        Args:
            identifier: Asset identifier to validate
            
        Returns:
            AssetValidationResult with exists status and details
        """
        pass
    
    # -------------------------------------------------------------------------
    # Optional Methods - Subclasses may override these
    # -------------------------------------------------------------------------
    
    def get_sample_data(
        self,
        identifier: str,
        limit: int = 100
    ) -> Optional[SampleData]:
        """
        Get sample data from an asset.
        
        Args:
            identifier: Asset identifier
            limit: Maximum number of rows to return
            
        Returns:
            SampleData if available, None otherwise
        """
        if not self.capabilities.can_get_sample_data:
            logger.debug(f"{self.connector_type} connector does not support sample data")
            return None
        return None
    
    def list_containers(
        self,
        parent_path: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        List containers (catalogs, databases, schemas, etc.).
        
        This is useful for hierarchical navigation.
        
        Args:
            parent_path: Parent container path (None for top-level)
            
        Returns:
            List of container info dicts
        """
        return []
    
    def search_assets(
        self,
        query: str,
        asset_types: Optional[List[UnifiedAssetType]] = None,
        limit: int = 50
    ) -> List[AssetInfo]:
        """
        Search for assets by query string.
        
        Default implementation filters list_assets results.
        Subclasses may override for more efficient search.
        
        Args:
            query: Search query
            asset_types: Optional filter by asset types
            limit: Maximum results
            
        Returns:
            List of matching AssetInfo objects
        """
        options = ListAssetsOptions(
            search_term=query,
            asset_types=asset_types,
            limit=limit
        )
        return self.list_assets(options)
    
    def get_asset_by_type(
        self,
        asset_type: UnifiedAssetType,
        identifier: str
    ) -> Optional[AssetMetadata]:
        """
        Get asset metadata when the type is known.
        
        This can be more efficient than get_asset_metadata when the
        asset type is already known.
        
        Args:
            asset_type: The known asset type
            identifier: Asset identifier
            
        Returns:
            AssetMetadata if found, None otherwise
        """
        # Default implementation delegates to get_asset_metadata
        return self.get_asset_metadata(identifier)
    
    def health_check(self) -> Dict[str, Any]:
        """
        Perform a health check on the connector.
        
        Returns:
            Dict with health status and details
        """
        return {
            "connector_type": self.connector_type,
            "available": self.is_available,
            "enabled": self._config.enabled,
        }
    
    # -------------------------------------------------------------------------
    # Utility Methods
    # -------------------------------------------------------------------------
    
    def _parse_identifier(self, identifier: str) -> Dict[str, Optional[str]]:
        """
        Parse an identifier into its components.
        
        Default implementation handles dot-separated identifiers
        (e.g., "catalog.schema.table").
        
        Subclasses may override for different identifier formats.
        
        Args:
            identifier: The identifier to parse
            
        Returns:
            Dict with 'catalog', 'schema', 'name' keys
        """
        parts = identifier.split(".")
        result = {
            "catalog": None,
            "schema": None,
            "name": None,
        }
        
        if len(parts) >= 3:
            result["catalog"] = parts[0]
            result["schema"] = parts[1]
            result["name"] = ".".join(parts[2:])  # Handle names with dots
        elif len(parts) == 2:
            result["schema"] = parts[0]
            result["name"] = parts[1]
        elif len(parts) == 1:
            result["name"] = parts[0]
        
        return result
    
    def _build_identifier(
        self,
        name: str,
        schema: Optional[str] = None,
        catalog: Optional[str] = None
    ) -> str:
        """
        Build an identifier from components.
        
        Args:
            name: Asset name
            schema: Schema name
            catalog: Catalog name
            
        Returns:
            Fully qualified identifier
        """
        parts = []
        if catalog:
            parts.append(catalog)
        if schema:
            parts.append(schema)
        parts.append(name)
        return ".".join(parts)
    
    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}(type={self.connector_type}, enabled={self._config.enabled})>"


# ============================================================================
# Connector Error Types
# ============================================================================

class ConnectorError(Exception):
    """Base exception for connector errors."""
    
    def __init__(self, message: str, connector_type: str = "unknown"):
        self.connector_type = connector_type
        super().__init__(f"[{connector_type}] {message}")


class ConnectorNotFoundError(ConnectorError):
    """Raised when a connector type is not registered."""
    pass


class ConnectorConnectionError(ConnectorError):
    """Raised when a connector cannot establish a connection."""
    pass


class ConnectorAuthenticationError(ConnectorError):
    """Raised when authentication fails."""
    pass


class ConnectorPermissionError(ConnectorError):
    """Raised when the connector lacks permission for an operation."""
    pass


class ConnectorNotImplementedError(ConnectorError):
    """Raised when an operation is not implemented by a connector."""
    pass

