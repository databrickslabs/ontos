"""
Databricks / Unity Catalog Connector

This module implements the AssetConnector interface for Databricks Unity Catalog,
providing asset discovery, metadata retrieval, and validation for UC objects
including tables, views, functions, models, volumes, and metrics.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from databricks.sdk import WorkspaceClient
from databricks.sdk.errors import NotFound, PermissionDenied, DatabricksError
from databricks.sdk.service.catalog import TableType, FunctionInfo, VolumeType
from databricks.sdk.service.workspace import ObjectType

from src.connectors.base import (
    AssetConnector,
    ConnectorCapabilities,
    ConnectorConfig,
    ConnectorConnectionError,
    ConnectorPermissionError,
    ListAssetsOptions,
)
from src.models.assets import (
    AssetInfo,
    AssetMetadata,
    AssetOwnership,
    AssetStatistics,
    AssetValidationResult,
    ColumnInfo,
    SampleData,
    SchemaInfo,
    UnifiedAssetType,
)
from src.common.logging import get_logger

logger = get_logger(__name__)


# ============================================================================
# Databricks Connector Configuration
# ============================================================================

class DatabricksConnectorConfig(ConnectorConfig):
    """Configuration specific to the Databricks connector."""
    
    # Workspace client is typically injected, not configured
    workspace_client: Optional[Any] = None
    
    # Statement execution warehouse ID for SQL queries
    warehouse_id: Optional[str] = None
    
    # Default catalog to use
    default_catalog: Optional[str] = None
    
    # Whether to include system schemas in listings
    include_system_schemas: bool = False
    
    model_config = {"from_attributes": True, "arbitrary_types_allowed": True}


# ============================================================================
# Table Type Mapping
# ============================================================================

TABLE_TYPE_MAPPING = {
    TableType.MANAGED: UnifiedAssetType.UC_TABLE,
    TableType.EXTERNAL: UnifiedAssetType.UC_TABLE,
    TableType.VIEW: UnifiedAssetType.UC_VIEW,
    TableType.MATERIALIZED_VIEW: UnifiedAssetType.UC_MATERIALIZED_VIEW,
    TableType.STREAMING_TABLE: UnifiedAssetType.UC_STREAMING_TABLE,
}


# ============================================================================
# Databricks Connector
# ============================================================================

class DatabricksConnector(AssetConnector):
    """
    Asset connector for Databricks Unity Catalog.
    
    This connector provides access to Unity Catalog objects including:
    - Tables (managed, external, streaming)
    - Views (regular, materialized)
    - Functions (UDFs)
    - Models (registered ML models)
    - Volumes
    - Metrics (AI/BI metrics)
    - Notebooks
    - Jobs
    """
    
    connector_type = "databricks"
    display_name = "Databricks Unity Catalog"
    description = "Connector for Databricks Unity Catalog assets"
    
    def __init__(
        self,
        config: Optional[DatabricksConnectorConfig] = None,
        workspace_client: Optional[WorkspaceClient] = None
    ):
        """
        Initialize the Databricks connector.
        
        Args:
            config: Optional configuration
            workspace_client: Optional pre-configured WorkspaceClient
        """
        super().__init__(config or DatabricksConnectorConfig())
        
        # Use provided client or try to get from config
        if workspace_client:
            self._ws_client = workspace_client
        elif isinstance(self._config, DatabricksConnectorConfig) and self._config.workspace_client:
            self._ws_client = self._config.workspace_client
        else:
            self._ws_client = None
        
        if not self._ws_client:
            logger.warning("DatabricksConnector initialized without WorkspaceClient - operations will fail")
    
    def set_workspace_client(self, client: WorkspaceClient) -> None:
        """
        Set the workspace client after initialization.
        
        Args:
            client: The WorkspaceClient to use
        """
        self._ws_client = client
        logger.info("WorkspaceClient set on DatabricksConnector")
    
    @property
    def is_available(self) -> bool:
        """Check if the connector is available."""
        return self._config.enabled and self._ws_client is not None
    
    def _get_capabilities(self) -> ConnectorCapabilities:
        """Return the capabilities of this connector."""
        return ConnectorCapabilities(
            can_list_assets=True,
            can_get_metadata=True,
            can_validate_exists=True,
            can_get_schema=True,
            can_get_sample_data=True,
            can_get_statistics=True,
            can_get_lineage=False,  # Would need separate lineage API
            can_get_permissions=True,
            can_create_assets=False,
            can_update_assets=False,
            can_delete_assets=False,
            supported_asset_types=[
                UnifiedAssetType.UC_TABLE,
                UnifiedAssetType.UC_VIEW,
                UnifiedAssetType.UC_MATERIALIZED_VIEW,
                UnifiedAssetType.UC_STREAMING_TABLE,
                UnifiedAssetType.UC_FUNCTION,
                UnifiedAssetType.UC_MODEL,
                UnifiedAssetType.UC_VOLUME,
                UnifiedAssetType.UC_NOTEBOOK,
                UnifiedAssetType.UC_JOB,
                UnifiedAssetType.UC_METRIC,
            ]
        )
    
    def _ensure_client(self) -> WorkspaceClient:
        """Ensure workspace client is available."""
        if not self._ws_client:
            raise ConnectorConnectionError(
                "WorkspaceClient not configured",
                connector_type=self.connector_type
            )
        return self._ws_client
    
    # -------------------------------------------------------------------------
    # List Assets
    # -------------------------------------------------------------------------
    
    def list_assets(
        self,
        options: Optional[ListAssetsOptions] = None
    ) -> List[AssetInfo]:
        """
        List Unity Catalog assets.

        The path format determines what is listed:
        - None or "": List all catalogs
        - "catalog": List schemas in catalog
        - "catalog.schema": List tables/views/functions/models/volumes in schema
        - "catalog.schema.object" (or deeper): empty — leaf FQN. Columns come
          from get_asset_metadata().schema_info, not from listing.
        """
        ws = self._ensure_client()
        options = options or ListAssetsOptions()
        results: List[AssetInfo] = []
        limit = options.limit
        
        try:
            path = options.path or ""
            parts = path.split(".") if path else []
            
            # Determine what to list based on path depth
            if len(parts) == 0 or path == "":
                # List catalogs
                results.extend(self._list_catalogs(ws, options, limit))
            elif len(parts) == 1:
                # List schemas in catalog
                results.extend(self._list_schemas(ws, parts[0], options, limit))
            elif len(parts) >= 3:
                # Leaf FQN (catalog.schema.object[.column...]) — no children to list.
                # Columns are sourced from get_asset_metadata().schema_info, not from listing.
                # Mirrors the BigQuery connector's documented contract.
                return []
            elif len(parts) == 2:
                # List objects in schema
                catalog = parts[0]
                schema = parts[1]
                
                # Filter by asset types if specified
                asset_types = options.asset_types
                
                # List tables/views
                if not asset_types or any(t in asset_types for t in [
                    UnifiedAssetType.UC_TABLE,
                    UnifiedAssetType.UC_VIEW,
                    UnifiedAssetType.UC_MATERIALIZED_VIEW,
                    UnifiedAssetType.UC_STREAMING_TABLE,
                ]):
                    results.extend(self._list_tables(ws, catalog, schema, options, limit - len(results)))
                
                # List functions
                if not asset_types or UnifiedAssetType.UC_FUNCTION in asset_types:
                    if len(results) < limit:
                        results.extend(self._list_functions(ws, catalog, schema, options, limit - len(results)))
                
                # List models
                if not asset_types or UnifiedAssetType.UC_MODEL in asset_types:
                    if len(results) < limit:
                        results.extend(self._list_models(ws, catalog, schema, options, limit - len(results)))
                
                # List volumes
                if not asset_types or UnifiedAssetType.UC_VOLUME in asset_types:
                    if len(results) < limit:
                        results.extend(self._list_volumes(ws, catalog, schema, options, limit - len(results)))
                
                # List metrics
                if not asset_types or UnifiedAssetType.UC_METRIC in asset_types:
                    if len(results) < limit:
                        results.extend(self._list_metrics(ws, catalog, schema, options, limit - len(results)))
            
            return results[:limit]
            
        except PermissionDenied as e:
            logger.warning(f"Permission denied listing assets: {e}")
            raise ConnectorPermissionError(str(e), self.connector_type)
        except DatabricksError as e:
            logger.error(f"Databricks error listing assets: {e}")
            raise ConnectorConnectionError(str(e), self.connector_type)
    
    def _list_catalogs(
        self,
        ws: WorkspaceClient,
        options: ListAssetsOptions,
        limit: int
    ) -> List[AssetInfo]:
        """List available catalogs."""
        results = []
        search_term = (options.search_term or "").lower()
        
        for catalog in ws.catalogs.list():
            if len(results) >= limit:
                break
            
            if search_term and search_term not in (catalog.name or "").lower():
                continue
            
            results.append(AssetInfo(
                identifier=catalog.name,
                name=catalog.name,
                asset_type=UnifiedAssetType.UC_CATALOG,
                connector_type=self.connector_type,
                description=catalog.comment,
                path=catalog.name,
                catalog=catalog.name,
            ))
        
        return results
    
    def _list_schemas(
        self,
        ws: WorkspaceClient,
        catalog: str,
        options: ListAssetsOptions,
        limit: int
    ) -> List[AssetInfo]:
        """List schemas in a catalog."""
        results = []
        search_term = (options.search_term or "").lower()
        
        try:
            for schema in ws.schemas.list(catalog_name=catalog):
                if len(results) >= limit:
                    break
                
                # Skip system schemas unless requested
                if not options.include_hidden and schema.name in ("information_schema", "__internal"):
                    continue
                
                if search_term and search_term not in (schema.name or "").lower():
                    continue
                
                results.append(AssetInfo(
                    identifier=f"{catalog}.{schema.name}",
                    name=schema.name,
                    asset_type=UnifiedAssetType.UC_SCHEMA,
                    connector_type=self.connector_type,
                    description=schema.comment,
                    path=f"{catalog}.{schema.name}",
                    catalog=catalog,
                    schema_name=schema.name,
                ))
        except (NotFound, PermissionDenied) as e:
            logger.debug(f"Cannot list schemas in catalog {catalog}: {e}")
        
        return results
    
    def _list_tables(
        self,
        ws: WorkspaceClient,
        catalog: str,
        schema: str,
        options: ListAssetsOptions,
        limit: int
    ) -> List[AssetInfo]:
        """List tables and views in a schema."""
        results = []
        search_term = (options.search_term or "").lower()
        
        try:
            for table in ws.tables.list(catalog_name=catalog, schema_name=schema):
                if len(results) >= limit:
                    break
                
                if search_term and search_term not in (table.name or "").lower():
                    continue
                
                # Map table type
                asset_type = TABLE_TYPE_MAPPING.get(
                    table.table_type,
                    UnifiedAssetType.UC_TABLE
                )
                
                # Filter by asset type if specified
                if options.asset_types and asset_type not in options.asset_types:
                    continue
                
                full_name = table.full_name or f"{catalog}.{schema}.{table.name}"
                
                results.append(AssetInfo(
                    identifier=full_name,
                    name=table.name,
                    asset_type=asset_type,
                    connector_type=self.connector_type,
                    description=table.comment,
                    path=full_name,
                    catalog=catalog,
                    schema_name=schema,
                ))
        except (NotFound, PermissionDenied) as e:
            logger.debug(f"Cannot list tables in {catalog}.{schema}: {e}")
        
        return results
    
    def _list_functions(
        self,
        ws: WorkspaceClient,
        catalog: str,
        schema: str,
        options: ListAssetsOptions,
        limit: int
    ) -> List[AssetInfo]:
        """List functions in a schema."""
        results = []
        search_term = (options.search_term or "").lower()
        
        try:
            for func in ws.functions.list(catalog_name=catalog, schema_name=schema):
                if len(results) >= limit:
                    break
                
                if search_term and search_term not in (func.name or "").lower():
                    continue
                
                full_name = func.full_name or f"{catalog}.{schema}.{func.name}"
                
                results.append(AssetInfo(
                    identifier=full_name,
                    name=func.name,
                    asset_type=UnifiedAssetType.UC_FUNCTION,
                    connector_type=self.connector_type,
                    description=func.comment,
                    path=full_name,
                    catalog=catalog,
                    schema_name=schema,
                ))
        except (NotFound, PermissionDenied) as e:
            logger.debug(f"Cannot list functions in {catalog}.{schema}: {e}")
        except Exception as e:
            # Functions API may not be available in all workspaces
            logger.debug(f"Error listing functions in {catalog}.{schema}: {e}")
        
        return results
    
    def _list_models(
        self,
        ws: WorkspaceClient,
        catalog: str,
        schema: str,
        options: ListAssetsOptions,
        limit: int
    ) -> List[AssetInfo]:
        """List registered models in a schema."""
        results = []
        search_term = (options.search_term or "").lower()
        
        try:
            # List models using the registered models API
            for model in ws.registered_models.list(catalog_name=catalog, schema_name=schema):
                if len(results) >= limit:
                    break
                
                if search_term and search_term not in (model.name or "").lower():
                    continue
                
                full_name = model.full_name or f"{catalog}.{schema}.{model.name}"
                
                results.append(AssetInfo(
                    identifier=full_name,
                    name=model.name,
                    asset_type=UnifiedAssetType.UC_MODEL,
                    connector_type=self.connector_type,
                    description=model.comment,
                    path=full_name,
                    catalog=catalog,
                    schema_name=schema,
                ))
        except (NotFound, PermissionDenied) as e:
            logger.debug(f"Cannot list models in {catalog}.{schema}: {e}")
        except Exception as e:
            logger.debug(f"Error listing models in {catalog}.{schema}: {e}")
        
        return results
    
    def _list_volumes(
        self,
        ws: WorkspaceClient,
        catalog: str,
        schema: str,
        options: ListAssetsOptions,
        limit: int
    ) -> List[AssetInfo]:
        """List volumes in a schema."""
        results = []
        search_term = (options.search_term or "").lower()
        
        try:
            for volume in ws.volumes.list(catalog_name=catalog, schema_name=schema):
                if len(results) >= limit:
                    break
                
                if search_term and search_term not in (volume.name or "").lower():
                    continue
                
                full_name = volume.full_name or f"{catalog}.{schema}.{volume.name}"
                
                results.append(AssetInfo(
                    identifier=full_name,
                    name=volume.name,
                    asset_type=UnifiedAssetType.UC_VOLUME,
                    connector_type=self.connector_type,
                    description=volume.comment,
                    path=full_name,
                    catalog=catalog,
                    schema_name=schema,
                ))
        except (NotFound, PermissionDenied) as e:
            logger.debug(f"Cannot list volumes in {catalog}.{schema}: {e}")
        except Exception as e:
            logger.debug(f"Error listing volumes in {catalog}.{schema}: {e}")
        
        return results
    
    def _list_metrics(
        self,
        ws: WorkspaceClient,
        catalog: str,
        schema: str,
        options: ListAssetsOptions,
        limit: int
    ) -> List[AssetInfo]:
        """
        List UC metrics in a schema.
        
        Note: UC Metrics API may not be available in all workspaces.
        This implementation uses the Lakeview/AI-BI metrics if available.
        """
        results = []
        
        # UC Metrics are a newer feature - try to list them if API is available
        try:
            # The metrics API is accessed through the Lakeview API in newer SDKs
            # For now, we'll query the SYSTEM.INFORMATION_SCHEMA if available
            # or use the REST API directly
            
            # This is a placeholder - actual implementation depends on
            # which SDK version and features are available
            logger.debug(f"Metrics listing for {catalog}.{schema} - feature may not be available")
            
        except Exception as e:
            logger.debug(f"Error listing metrics in {catalog}.{schema}: {e}")
        
        return results
    
    # -------------------------------------------------------------------------
    # Get Asset Metadata
    # -------------------------------------------------------------------------
    
    def get_asset_metadata(self, identifier: str) -> Optional[AssetMetadata]:
        """
        Get detailed metadata for an asset.
        
        The identifier should be a fully qualified name (catalog.schema.name).
        Single-part identifiers are treated as catalogs, two-part as schemas.
        """
        ws = self._ensure_client()
        
        parts = identifier.split(".") if identifier else []

        if len(parts) == 0:
            return None

        try:
            # Single part -> catalog
            if len(parts) == 1:
                return self._get_catalog_metadata(ws, identifier)

            # Two parts -> schema
            if len(parts) == 2:
                return self._get_schema_metadata(ws, parts[0], parts[1])

            # Three+ parts -> leaf asset
            metadata = self._get_table_metadata(ws, identifier)
            if metadata:
                return metadata
            
            metadata = self._get_function_metadata(ws, identifier)
            if metadata:
                return metadata
            
            metadata = self._get_model_metadata(ws, identifier)
            if metadata:
                return metadata
            
            metadata = self._get_volume_metadata(ws, identifier)
            if metadata:
                return metadata
            
            logger.debug(f"Asset not found: {identifier}")
            return None
            
        except PermissionDenied as e:
            logger.warning(f"Permission denied getting metadata for {identifier}: {e}")
            raise ConnectorPermissionError(str(e), self.connector_type)
        except DatabricksError as e:
            logger.error(f"Databricks error getting metadata for {identifier}: {e}")
            return None

    def _get_catalog_metadata(
        self, ws: WorkspaceClient, catalog_name: str
    ) -> Optional[AssetMetadata]:
        """Get metadata for a UC catalog."""
        try:
            catalog = ws.catalogs.get(name=catalog_name)
            return AssetMetadata(
                identifier=catalog.name,
                name=catalog.name,
                asset_type=UnifiedAssetType.UC_CATALOG,
                connector_type=self.connector_type,
                description=catalog.comment,
                path=catalog.name,
                catalog=catalog.name,
                ownership=AssetOwnership(owner=catalog.owner),
                properties=catalog.properties or {},
                created_at=catalog.created_at if hasattr(catalog, "created_at") else None,
                updated_at=catalog.updated_at if hasattr(catalog, "updated_at") else None,
                exists=True,
            )
        except NotFound:
            return None
        except Exception as e:
            logger.debug(f"Error getting catalog metadata for {catalog_name}: {e}")
            return None

    def _get_schema_metadata(
        self, ws: WorkspaceClient, catalog_name: str, schema_name: str
    ) -> Optional[AssetMetadata]:
        """Get metadata for a UC schema."""
        try:
            schema = ws.schemas.get(full_name=f"{catalog_name}.{schema_name}")
            path = f"{catalog_name}.{schema_name}"
            return AssetMetadata(
                identifier=path,
                name=schema.name,
                asset_type=UnifiedAssetType.UC_SCHEMA,
                connector_type=self.connector_type,
                description=schema.comment,
                path=path,
                catalog=catalog_name,
                schema_name=schema.name,
                ownership=AssetOwnership(owner=schema.owner if hasattr(schema, "owner") else None),
                properties=schema.properties or {},
                created_at=schema.created_at if hasattr(schema, "created_at") else None,
                updated_at=schema.updated_at if hasattr(schema, "updated_at") else None,
                exists=True,
            )
        except NotFound:
            return None
        except Exception as e:
            logger.debug(f"Error getting schema metadata for {catalog_name}.{schema_name}: {e}")
            return None
    
    def _get_table_metadata(
        self,
        ws: WorkspaceClient,
        identifier: str
    ) -> Optional[AssetMetadata]:
        """Get metadata for a table or view."""
        try:
            table = ws.tables.get(full_name=identifier)
            
            # Map table type
            asset_type = TABLE_TYPE_MAPPING.get(
                table.table_type,
                UnifiedAssetType.UC_TABLE
            )
            
            # Build schema info
            schema_info = None
            if table.columns:
                columns = []
                for col in table.columns:
                    type_name_value = col.type_name.value if col.type_name else None
                    columns.append(ColumnInfo(
                        name=col.name,
                        data_type=col.type_text or type_name_value or "unknown",
                        logical_type=type_name_value,
                        nullable=col.nullable if col.nullable is not None else True,
                        description=col.comment,
                        is_partition_key=col.partition_index is not None,
                    ))
                
                schema_info = SchemaInfo(
                    columns=columns,
                    partition_columns=[c.name for c in table.columns if c.partition_index is not None] if table.columns else None,
                )
            
            # Build statistics
            statistics = None
            if table.table_constraints or hasattr(table, 'row_count'):
                statistics = AssetStatistics(
                    row_count=getattr(table, 'row_count', None),
                    updated_at=table.updated_at if hasattr(table, 'updated_at') else None,
                )
            
            # Build ownership
            ownership = AssetOwnership(
                owner=table.owner,
            )
            
            # Build tags dict from properties
            tags = {}
            if table.properties:
                tags = {k: v for k, v in table.properties.items() if k.startswith("tag_")}
            
            return AssetMetadata(
                identifier=table.full_name or identifier,
                name=table.name,
                asset_type=asset_type,
                connector_type=self.connector_type,
                description=table.comment,
                comment=table.comment,
                path=table.full_name,
                location=table.storage_location,
                catalog=table.catalog_name,
                schema_name=table.schema_name,
                schema_info=schema_info,
                ownership=ownership,
                statistics=statistics,
                tags=tags,
                properties=table.properties or {},
                created_at=table.created_at if hasattr(table, 'created_at') else None,
                updated_at=table.updated_at if hasattr(table, 'updated_at') else None,
                created_by=table.created_by if hasattr(table, 'created_by') else None,
                exists=True,
            )
            
        except NotFound:
            return None
        except Exception as e:
            logger.debug(f"Error getting table metadata for {identifier}: {e}")
            return None
    
    def _get_function_metadata(
        self,
        ws: WorkspaceClient,
        identifier: str
    ) -> Optional[AssetMetadata]:
        """Get metadata for a function."""
        try:
            func = ws.functions.get(name=identifier)
            
            # Functions don't have traditional schemas, but have input parameters
            schema_info = None
            if func.input_params and func.input_params.parameters:
                columns = []
                for param in func.input_params.parameters:
                    columns.append(ColumnInfo(
                        name=param.name,
                        data_type=param.type_text or "unknown",
                        logical_type=param.type_name.value if param.type_name else None,
                        description=param.comment,
                    ))
                schema_info = SchemaInfo(columns=columns)
            
            properties = {}
            if func.return_params:
                properties["return_type"] = func.return_params.parameters[0].type_text if func.return_params.parameters else None
            if func.routine_body:
                properties["routine_body"] = func.routine_body.value if hasattr(func.routine_body, 'value') else str(func.routine_body)
            
            return AssetMetadata(
                identifier=func.full_name or identifier,
                name=func.name,
                asset_type=UnifiedAssetType.UC_FUNCTION,
                connector_type=self.connector_type,
                description=func.comment,
                path=func.full_name,
                catalog=func.catalog_name,
                schema_name=func.schema_name,
                schema_info=schema_info,
                ownership=AssetOwnership(owner=func.owner),
                properties=properties,
                created_at=func.created_at if hasattr(func, 'created_at') else None,
                updated_at=func.updated_at if hasattr(func, 'updated_at') else None,
                exists=True,
            )
            
        except NotFound:
            return None
        except Exception as e:
            logger.debug(f"Error getting function metadata for {identifier}: {e}")
            return None
    
    def _get_model_metadata(
        self,
        ws: WorkspaceClient,
        identifier: str
    ) -> Optional[AssetMetadata]:
        """Get metadata for a registered model."""
        try:
            model = ws.registered_models.get(full_name=identifier)
            
            return AssetMetadata(
                identifier=model.full_name or identifier,
                name=model.name,
                asset_type=UnifiedAssetType.UC_MODEL,
                connector_type=self.connector_type,
                description=model.comment,
                path=model.full_name,
                catalog=model.catalog_name,
                schema_name=model.schema_name,
                ownership=AssetOwnership(owner=model.owner),
                created_at=model.created_at if hasattr(model, 'created_at') else None,
                updated_at=model.updated_at if hasattr(model, 'updated_at') else None,
                exists=True,
            )
            
        except NotFound:
            return None
        except Exception as e:
            logger.debug(f"Error getting model metadata for {identifier}: {e}")
            return None
    
    def _get_volume_metadata(
        self,
        ws: WorkspaceClient,
        identifier: str
    ) -> Optional[AssetMetadata]:
        """Get metadata for a volume."""
        try:
            volume = ws.volumes.read(name=identifier)
            
            return AssetMetadata(
                identifier=volume.full_name or identifier,
                name=volume.name,
                asset_type=UnifiedAssetType.UC_VOLUME,
                connector_type=self.connector_type,
                description=volume.comment,
                path=volume.full_name,
                location=volume.storage_location,
                catalog=volume.catalog_name,
                schema_name=volume.schema_name,
                ownership=AssetOwnership(owner=volume.owner),
                properties={
                    "volume_type": volume.volume_type.value if volume.volume_type else None,
                },
                created_at=volume.created_at if hasattr(volume, 'created_at') else None,
                updated_at=volume.updated_at if hasattr(volume, 'updated_at') else None,
                exists=True,
            )
            
        except NotFound:
            return None
        except Exception as e:
            logger.debug(f"Error getting volume metadata for {identifier}: {e}")
            return None
    
    # -------------------------------------------------------------------------
    # Validate Asset Exists
    # -------------------------------------------------------------------------
    
    def validate_asset_exists(self, identifier: str) -> AssetValidationResult:
        """Validate that an asset exists in Unity Catalog."""
        ws = self._ensure_client()
        
        try:
            # Try to get table info (most common case)
            try:
                table = ws.tables.get(full_name=identifier)
                return AssetValidationResult(
                    identifier=identifier,
                    exists=True,
                    validated=True,
                    asset_type=TABLE_TYPE_MAPPING.get(table.table_type, UnifiedAssetType.UC_TABLE),
                    message="Asset found",
                    details={
                        "name": table.name,
                        "catalog": table.catalog_name,
                        "schema": table.schema_name,
                        "table_type": table.table_type.value if table.table_type else None,
                    }
                )
            except NotFound:
                pass
            
            # Try function
            try:
                ws.functions.get(name=identifier)
                return AssetValidationResult(
                    identifier=identifier,
                    exists=True,
                    validated=True,
                    asset_type=UnifiedAssetType.UC_FUNCTION,
                    message="Function found",
                )
            except NotFound:
                pass
            except Exception:
                pass
            
            # Try model
            try:
                ws.registered_models.get(full_name=identifier)
                return AssetValidationResult(
                    identifier=identifier,
                    exists=True,
                    validated=True,
                    asset_type=UnifiedAssetType.UC_MODEL,
                    message="Model found",
                )
            except NotFound:
                pass
            except Exception:
                pass
            
            # Try volume
            try:
                ws.volumes.read(name=identifier)
                return AssetValidationResult(
                    identifier=identifier,
                    exists=True,
                    validated=True,
                    asset_type=UnifiedAssetType.UC_VOLUME,
                    message="Volume found",
                )
            except NotFound:
                pass
            except Exception:
                pass
            
            # Not found anywhere
            return AssetValidationResult(
                identifier=identifier,
                exists=False,
                validated=True,
                message="Asset not found in Unity Catalog",
            )
            
        except PermissionDenied as e:
            return AssetValidationResult(
                identifier=identifier,
                exists=False,
                validated=False,
                message=f"Permission denied: {e}",
            )
        except Exception as e:
            return AssetValidationResult(
                identifier=identifier,
                exists=False,
                validated=False,
                message=f"Validation error: {e}",
            )
    
    # -------------------------------------------------------------------------
    # Sample Data
    # -------------------------------------------------------------------------
    
    def get_sample_data(
        self,
        identifier: str,
        limit: int = 100
    ) -> Optional[SampleData]:
        """
        Get sample data from a table.
        
        Uses the Statement Execution API if a warehouse is configured,
        otherwise returns None.
        """
        ws = self._ensure_client()
        
        # Validate it's a table-like asset first
        validation = self.validate_asset_exists(identifier)
        if not validation.exists:
            return None
        
        if validation.asset_type not in [
            UnifiedAssetType.UC_TABLE,
            UnifiedAssetType.UC_VIEW,
            UnifiedAssetType.UC_MATERIALIZED_VIEW,
        ]:
            logger.debug(f"Asset {identifier} does not support sample data")
            return None
        
        try:
            # Get warehouse ID from config
            warehouse_id = None
            if isinstance(self._config, DatabricksConnectorConfig):
                warehouse_id = self._config.warehouse_id
            
            if not warehouse_id:
                logger.debug("No warehouse configured for sample data queries")
                return None
            
            # Execute query
            query = f"SELECT * FROM {identifier} LIMIT {limit}"
            
            statement = ws.statement_execution.execute_statement(
                warehouse_id=warehouse_id,
                statement=query,
                wait_timeout="30s",
            )
            
            if statement.result and statement.result.data_array:
                columns = [col.name for col in statement.manifest.schema.columns] if statement.manifest and statement.manifest.schema else []
                
                return SampleData(
                    columns=columns,
                    rows=statement.result.data_array,
                    sample_size=len(statement.result.data_array),
                    truncated=len(statement.result.data_array) >= limit,
                )
            
            return SampleData(columns=[], rows=[], sample_size=0)
            
        except Exception as e:
            logger.warning(f"Error getting sample data for {identifier}: {e}")
            return None
    
    # -------------------------------------------------------------------------
    # Container Listing (Catalogs, Schemas)
    # -------------------------------------------------------------------------
    
    def list_containers(
        self,
        parent_path: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        List catalogs and schemas for navigation.
        
        Args:
            parent_path: None for catalogs, catalog name for schemas
            
        Returns:
            List of container info dicts
        """
        ws = self._ensure_client()
        containers = []
        
        try:
            if parent_path is None:
                # List catalogs
                for catalog in ws.catalogs.list():
                    containers.append({
                        "name": catalog.name,
                        "type": "catalog",
                        "path": catalog.name,
                        "comment": catalog.comment,
                        "has_children": True,
                    })
            else:
                parts = parent_path.split(".")
                if len(parts) >= 2:
                    # Schema-level or deeper — no structural containers;
                    # leaf assets are listed by list_assets() instead.
                    return []
                # List schemas in catalog
                catalog_name = parts[0]
                for schema in ws.schemas.list(catalog_name=catalog_name):
                    if schema.name in ("information_schema", "__internal"):
                        continue
                    containers.append({
                        "name": schema.name,
                        "type": "schema",
                        "path": f"{catalog_name}.{schema.name}",
                        "comment": schema.comment,
                        "has_children": True,
                    })
        except Exception as e:
            logger.warning(f"Error listing containers for {parent_path}: {e}")
            raise ConnectorConnectionError(f"Failed to list resources: {e}", connector_type=self.connector_type) from e
        
        return containers
    
    # -------------------------------------------------------------------------
    # Health Check
    # -------------------------------------------------------------------------
    
    def health_check(self) -> Dict[str, Any]:
        """Perform a health check."""
        result = {
            "connector_type": self.connector_type,
            "available": self.is_available,
            "enabled": self._config.enabled,
            "has_workspace_client": self._ws_client is not None,
        }
        
        if self._ws_client:
            try:
                # Try to list catalogs as a health check
                catalogs = list(self._ws_client.catalogs.list())
                result["catalog_count"] = len(catalogs)
                result["healthy"] = True
            except Exception as e:
                result["healthy"] = False
                result["error"] = str(e)
        else:
            result["healthy"] = False
            result["error"] = "No workspace client configured"
        
        return result

