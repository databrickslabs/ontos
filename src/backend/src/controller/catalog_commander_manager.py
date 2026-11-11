from typing import Any, Dict, List, Optional, Tuple

from databricks.sdk import WorkspaceClient
from urllib.parse import quote

from ..common.logging import get_logger
from ..common.unity_catalog_utils import sanitize_uc_identifier
from ..common.config import Settings

logger = get_logger(__name__)

# Unity Catalog table_type -> object type shown in the catalog tree
_TREE_TYPES = {
    'VIEW': 'view',
    'MATERIALIZED_VIEW': 'materialized_view',
    'STREAMING_TABLE': 'streaming_table',
    'METRIC_VIEW': 'metric',
}


def _tree_type(table: Any) -> str:
    """Catalog tree type of a Unity Catalog table; 'table' for managed, external and others.

    ``table_type`` is a ``TableType`` enum from the SDK (``str()`` of it is
    ``'TableType.VIEW'``), or a plain string in tests.
    """
    table_type = getattr(table, 'table_type', None)
    raw = getattr(table_type, 'value', table_type)
    return _TREE_TYPES.get(str(raw).upper(), 'table') if raw else 'table'

# Constants for pagination
DEFAULT_LIMIT = 100
MAX_LIMIT = 1000

class CatalogCommanderManager:
    """Manages catalog operations and queries."""

    def __init__(
        self,
        sp_client: WorkspaceClient,
        obo_client: WorkspaceClient,
        settings: Optional[Settings] = None
    ):
        """Initialize the catalog commander manager.
        
        Args:
            sp_client: Service principal workspace client for administrative operations
            obo_client: OBO workspace client for user-specific catalog browsing operations
            settings: Application settings for warehouse configuration
        """
        logger.debug("Initializing CatalogCommanderManager...")
        self.sp_client = sp_client  # For administrative operations, jobs, etc.
        self.obo_client = obo_client  # For browsing catalogs with user permissions
        # Keep 'client' alias pointing to obo_client for backward compatibility
        self.client = obo_client
        self.settings = settings
        logger.debug("CatalogCommanderManager initialized successfully with SP and OBO clients")

    def _validate_and_parse_dataset_path(self, dataset_path: str) -> Tuple[str, str, str]:
        """Validate and parse a dataset path into its components.
        
        This method provides SQL injection protection by sanitizing each
        identifier component using Unity Catalog identifier validation rules.
        
        Args:
            dataset_path: Full path to the dataset (catalog.schema.table)
            
        Returns:
            Tuple of (catalog_name, schema_name, table_name) - all sanitized
            
        Raises:
            ValueError: If the path format is invalid or contains invalid identifiers
        """
        if not dataset_path or not isinstance(dataset_path, str):
            raise ValueError("dataset_path must be a non-empty string")
        
        parts = dataset_path.strip().split('.')
        if len(parts) != 3:
            raise ValueError(
                f"dataset_path must be in the form catalog.schema.table, got: {dataset_path}"
            )
        
        catalog_name, schema_name, table_name = parts
        
        # Sanitize each component to prevent SQL injection
        try:
            catalog_name = sanitize_uc_identifier(catalog_name)
            schema_name = sanitize_uc_identifier(schema_name)
            table_name = sanitize_uc_identifier(table_name)
        except ValueError as e:
            raise ValueError(f"Invalid dataset path component: {e}")
        
        return catalog_name, schema_name, table_name

    def list_catalogs(self) -> List[Dict[str, Any]]:
        """List all catalogs in the Databricks workspace.
        
        Uses the OBO client to ensure only catalogs the user has permission to see are returned.
        
        Returns:
            List of catalog information dictionaries
        """
        try:
            logger.debug("Fetching all catalogs from Databricks workspace using OBO client")
            # Use OBO client (self.client) to respect user permissions
            catalogs = list(self.client.catalogs.list())  # Convert generator to list
            logger.debug(f"Retrieved {len(catalogs)} catalogs from Databricks")

            result = [{
                'id': catalog.name,
                'name': catalog.name,
                'type': 'catalog',
                'children': [],  # Empty array means children not fetched yet
                'hasChildren': True  # Catalogs can always have schemas
            } for catalog in catalogs]

            logger.debug(f"Successfully formatted {len(result)} catalogs")
            return result
        except Exception as e:
            logger.error(f"Error in list_catalogs: {e!s}", exc_info=True)
            raise

    def list_schemas(self, catalog_name: str) -> List[Dict[str, Any]]:
        """List all schemas in a catalog.
        
        Args:
            catalog_name: Name of the catalog
            
        Returns:
            List of schema information dictionaries
        """
        logger.debug(f"Fetching schemas for catalog: {catalog_name}")
        schemas = list(self.client.schemas.list(catalog_name=catalog_name))  # Convert generator to list

        result = [{
            'id': f"{catalog_name}.{schema.name}",
            'name': schema.name,
            'type': 'schema',
            'children': [],  # Empty array means children not fetched yet
            'hasChildren': True  # Schemas can always have tables
        } for schema in schemas]

        logger.debug(f"Successfully retrieved {len(result)} schemas for catalog {catalog_name}")
        return result

    def list_tables(self, catalog_name: str, schema_name: str) -> List[Dict[str, Any]]:
        """List all tables and views in a schema.
        
        Args:
            catalog_name: Name of the catalog
            schema_name: Name of the schema
            
        Returns:
            List of table/view information dictionaries
        """
        logger.debug(f"Fetching tables for schema: {catalog_name}.{schema_name}")
        tables = list(self.client.tables.list(catalog_name=catalog_name, schema_name=schema_name))  # Convert generator to list

        result = [{
            'id': f"{catalog_name}.{schema_name}.{table.name}",
            'name': table.name,
            # This listing only tells tables, views and metric views apart
            'type': tree_type if (tree_type := _tree_type(table)) in ('view', 'metric') else 'table',
            'children': [],  # Empty array for consistency
            'hasChildren': False  # Tables/views are leaf nodes
        } for table in tables]

        logger.debug(f"Successfully retrieved {len(result)} tables for schema {catalog_name}.{schema_name}")
        return result

    def list_views(self, catalog_name: str, schema_name: str) -> List[Dict[str, Any]]:
        """List all views in a schema.

        Args:
            catalog_name: Name of the catalog
            schema_name: Name of the schema

        Returns:
            List of view information dictionaries
        """
        logger.debug(f"Fetching views for schema: {catalog_name}.{schema_name}")
        try:
            # Use tables.list and filter for views
            all_tables = list(self.client.tables.list(catalog_name=catalog_name, schema_name=schema_name))
            views = [tbl for tbl in all_tables if _tree_type(tbl) == 'view']

            result = [{
                'id': f"{catalog_name}.{schema_name}.{view.name}",
                'name': view.name,
                'type': 'view',
                'children': [],
                'hasChildren': False
            } for view in views]

            logger.debug(f"Successfully retrieved {len(result)} views for schema {catalog_name}.{schema_name}")
            return result
        except Exception as e:
            logger.error(f"Error listing views for {catalog_name}.{schema_name}: {e!s}", exc_info=True)
            raise

    def list_functions(self, catalog_name: str, schema_name: str) -> List[Dict[str, Any]]:
        """List all functions in a schema.

        Args:
            catalog_name: Name of the catalog
            schema_name: Name of the schema

        Returns:
            List of function information dictionaries
        """
        logger.info(f"Fetching functions for schema: {catalog_name}.{schema_name}")
        try:
            functions = list(self.client.functions.list(catalog_name=catalog_name, schema_name=schema_name))

            result = [{
                'id': function.full_name, # Functions usually have full_name
                'name': function.name,
                'type': 'function',
                'children': [],
                'hasChildren': False
            } for function in functions]

            logger.info(f"Successfully retrieved {len(result)} functions for schema {catalog_name}.{schema_name}")
            return result
        except Exception as e:
            logger.error(f"Error listing functions for {catalog_name}.{schema_name}: {e!s}", exc_info=True)
            raise

    def list_models(self, catalog_name: str, schema_name: str) -> List[Dict[str, Any]]:
        """List all registered ML models in a schema.

        Args:
            catalog_name: Name of the catalog
            schema_name: Name of the schema

        Returns:
            List of model information dictionaries
        """
        logger.debug(f"Fetching models for schema: {catalog_name}.{schema_name}")
        try:
            models = list(self.client.registered_models.list(catalog_name=catalog_name, schema_name=schema_name))

            result = [{
                'id': model.full_name or f"{catalog_name}.{schema_name}.{model.name}",
                'name': model.name,
                'type': 'model',
                'children': [],
                'hasChildren': False,
                'description': getattr(model, 'comment', None)
            } for model in models]

            logger.debug(f"Successfully retrieved {len(result)} models for schema {catalog_name}.{schema_name}")
            return result
        except Exception as e:
            logger.debug(f"Error listing models for {catalog_name}.{schema_name}: {e!s}")
            # Models API may not be available in all workspaces
            return []

    def list_volumes(self, catalog_name: str, schema_name: str) -> List[Dict[str, Any]]:
        """List all volumes in a schema.

        Args:
            catalog_name: Name of the catalog
            schema_name: Name of the schema

        Returns:
            List of volume information dictionaries
        """
        logger.debug(f"Fetching volumes for schema: {catalog_name}.{schema_name}")
        try:
            volumes = list(self.client.volumes.list(catalog_name=catalog_name, schema_name=schema_name))

            result = [{
                'id': volume.full_name or f"{catalog_name}.{schema_name}.{volume.name}",
                'name': volume.name,
                'type': 'volume',
                'children': [],
                'hasChildren': False,
                'description': getattr(volume, 'comment', None)
            } for volume in volumes]

            logger.debug(f"Successfully retrieved {len(result)} volumes for schema {catalog_name}.{schema_name}")
            return result
        except Exception as e:
            logger.debug(f"Error listing volumes for {catalog_name}.{schema_name}: {e!s}")
            # Volumes API may not be available in all workspaces
            return []

    def list_objects(
        self,
        catalog_name: str,
        schema_name: str,
        asset_types: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """List all objects in a schema, optionally filtered by asset type.

        This unified method combines tables, views, functions, models, and volumes
        into a single response. Asset types can be filtered using the asset_types parameter.

        Args:
            catalog_name: Name of the catalog
            schema_name: Name of the schema
            asset_types: Optional list of asset types to include. 
                        Valid values: table, view, materialized_view, streaming_table, 
                        function, model, volume, metric.
                        If None, returns all types.

        Returns:
            List of object information dictionaries with 'type' field indicating asset type
        """
        logger.info(f"Fetching objects for schema: {catalog_name}.{schema_name} (types={asset_types})")
        
        # Normalize asset types to lowercase if provided
        type_filter = set(t.lower() for t in asset_types) if asset_types else None
        
        # Define which types to fetch based on filter
        all_types = {'table', 'view', 'materialized_view', 'streaming_table', 'function', 'model', 'volume', 'metric'}
        types_to_fetch = type_filter if type_filter else all_types
        
        results: List[Dict[str, Any]] = []
        
        try:
            # Fetch tables/views (these come from the same API)
            # Metric views come from the Tables API too (table_type METRIC_VIEW)
            if types_to_fetch & {'table', 'view', 'materialized_view', 'streaming_table', 'metric'}:
                try:
                    tables = list(self.client.tables.list(catalog_name=catalog_name, schema_name=schema_name))
                    for table in tables:
                        obj_type = _tree_type(table)
                        
                        # Check if this type is in the filter
                        if type_filter and obj_type not in type_filter:
                            continue
                        
                        results.append({
                            'id': f"{catalog_name}.{schema_name}.{table.name}",
                            'name': table.name,
                            'type': obj_type,
                            'children': [],
                            'hasChildren': False,
                            'description': getattr(table, 'comment', None)
                        })
                except Exception as e:
                    logger.warning(f"Error listing tables for {catalog_name}.{schema_name}: {e!s}")
            
            # Fetch functions
            if 'function' in types_to_fetch:
                try:
                    functions = list(self.client.functions.list(catalog_name=catalog_name, schema_name=schema_name))
                    for func in functions:
                        results.append({
                            'id': func.full_name or f"{catalog_name}.{schema_name}.{func.name}",
                            'name': func.name,
                            'type': 'function',
                            'children': [],
                            'hasChildren': False,
                            'description': getattr(func, 'comment', None)
                        })
                except Exception as e:
                    logger.debug(f"Error listing functions for {catalog_name}.{schema_name}: {e!s}")
            
            # Fetch models
            if 'model' in types_to_fetch:
                try:
                    models = list(self.client.registered_models.list(catalog_name=catalog_name, schema_name=schema_name))
                    for model in models:
                        results.append({
                            'id': model.full_name or f"{catalog_name}.{schema_name}.{model.name}",
                            'name': model.name,
                            'type': 'model',
                            'children': [],
                            'hasChildren': False,
                            'description': getattr(model, 'comment', None)
                        })
                except Exception as e:
                    logger.debug(f"Error listing models for {catalog_name}.{schema_name}: {e!s}")
            
            # Fetch volumes
            if 'volume' in types_to_fetch:
                try:
                    volumes = list(self.client.volumes.list(catalog_name=catalog_name, schema_name=schema_name))
                    for volume in volumes:
                        results.append({
                            'id': volume.full_name or f"{catalog_name}.{schema_name}.{volume.name}",
                            'name': volume.name,
                            'type': 'volume',
                            'children': [],
                            'hasChildren': False,
                            'description': getattr(volume, 'comment', None)
                        })
                except Exception as e:
                    logger.debug(f"Error listing volumes for {catalog_name}.{schema_name}: {e!s}")
            
            # Sort by name for consistent ordering
            results.sort(key=lambda x: x['name'].lower())
            
            logger.info(f"Successfully retrieved {len(results)} objects for schema {catalog_name}.{schema_name}")
            return results
            
        except Exception as e:
            logger.error(f"Error listing objects for {catalog_name}.{schema_name}: {e!s}", exc_info=True)
            raise

    def get_dataset(
        self,
        dataset_path: str,
        limit: int = DEFAULT_LIMIT,
        offset: int = 0
    ) -> Dict[str, Any]:
        """Get dataset schema, metadata, and paginated data rows.

        Uses Unity Catalog Tables API for metadata and Statement Execution API
        for fetching actual data rows with pagination support.

        Args:
            dataset_path: Full path to the dataset (catalog.schema.table)
            limit: Maximum number of rows to return (default: 100, max: 1000)
            offset: Number of rows to skip for pagination (default: 0)

        Returns:
            Dictionary containing table info, schema, paginated data, and row counts
        """
        logger.info(f"Fetching dataset for: {dataset_path} (limit={limit}, offset={offset})")
        
        # Validate and sanitize the dataset path
        catalog_name, schema_name, table_name = self._validate_and_parse_dataset_path(dataset_path)
        safe_path = f"{catalog_name}.{schema_name}.{table_name}"
        
        # Clamp limit to valid range
        limit = max(1, min(limit, MAX_LIMIT))
        offset = max(0, offset)
        
        try:
            # Use Unity Catalog Tables API to get table details
            tbl = None
            try:
                get_method = getattr(self.client.tables, 'get', None)
                if callable(get_method):
                    tbl = get_method(catalog_name=catalog_name, schema_name=schema_name, name=table_name)
                else:
                    raise AttributeError('tables.get not available')
            except Exception:
                # Fallback to direct REST call via api_client
                path = f"/api/2.1/unity-catalog/tables/{quote(safe_path, safe='')}"
                tbl = self.client.api_client.do('GET', path)

            # Extract table-level metadata
            table_info = self._extract_table_info(tbl, catalog_name, schema_name, table_name)

            # Build enhanced schema with full UC metadata
            schema = self._extract_schema(tbl)

            # Fetch actual data rows using Statement Execution API
            data = []
            total_rows = 0
            
            if self.settings and self.settings.DATABRICKS_WAREHOUSE_ID:
                warehouse_id = self.settings.DATABRICKS_WAREHOUSE_ID
                logger.debug(f"Fetching data using warehouse: {warehouse_id}")
                
                try:
                    # Execute paginated SELECT query
                    # Use backticks to safely quote the table name
                    select_sql = f"SELECT * FROM `{catalog_name}`.`{schema_name}`.`{table_name}` LIMIT {limit} OFFSET {offset}"
                    logger.debug(f"Executing SQL: {select_sql}")
                    
                    result = self.client.statement_execution.execute_statement(
                        statement=select_sql,
                        warehouse_id=warehouse_id,
                        wait_timeout="30s"
                    )
                    
                    # Check status
                    if result.status and result.status.state:
                        state = str(result.status.state)
                        if "FAILED" in state or "CANCELED" in state:
                            error_msg = result.status.error.message if result.status.error else "Query failed"
                            logger.warning(f"Query failed: {error_msg}")
                        else:
                            # Extract column names from manifest
                            column_names = []
                            if result.manifest and result.manifest.schema and result.manifest.schema.columns:
                                column_names = [col.name for col in result.manifest.schema.columns]
                            
                            # Extract data rows and convert to dictionaries
                            if result.result and result.result.data_array:
                                for row in result.result.data_array:
                                    if column_names:
                                        row_dict = dict(zip(column_names, row))
                                    else:
                                        row_dict = {f"col_{i}": v for i, v in enumerate(row)}
                                    data.append(row_dict)
                            
                            logger.info(f"Retrieved {len(data)} rows from {safe_path}")
                    
                    # Get total row count (use a separate COUNT query)
                    count_sql = f"SELECT COUNT(*) as cnt FROM `{catalog_name}`.`{schema_name}`.`{table_name}`"
                    count_result = self.client.statement_execution.execute_statement(
                        statement=count_sql,
                        warehouse_id=warehouse_id,
                        wait_timeout="30s"
                    )
                    
                    if (count_result.status and "SUCCEEDED" in str(count_result.status.state) and
                        count_result.result and count_result.result.data_array):
                        total_rows = int(count_result.result.data_array[0][0] or 0)
                        logger.debug(f"Total row count: {total_rows}")
                        
                except Exception as e:
                    logger.warning(f"Failed to fetch data via Statement Execution API: {e}")
                    # Continue without data - metadata is still useful
            else:
                logger.warning("No warehouse configured - returning metadata only without data rows")

            result: Dict[str, Any] = {
                'schema': schema,
                'table_info': table_info,
                'data': data,
                'total_rows': total_rows,
                'limit': limit,
                'offset': offset,
            }

            logger.info(f"Successfully retrieved dataset with {len(schema)} columns and {len(data)} rows for {safe_path}")
            return result
        except ValueError as e:
            # Re-raise validation errors as-is
            raise
        except Exception as e:
            logger.error(f"Error fetching dataset for {dataset_path}: {e!s}", exc_info=True)
            raise

    def _extract_table_info(
        self,
        tbl: Any,
        catalog_name: str,
        schema_name: str,
        table_name: str
    ) -> Dict[str, Any]:
        """Extract table-level metadata from a table object or dict."""
        if isinstance(tbl, dict):
            return {
                'name': tbl.get('name', table_name),
                'catalog_name': tbl.get('catalog_name', catalog_name),
                'schema_name': tbl.get('schema_name', schema_name),
                'table_type': tbl.get('table_type', 'MANAGED'),
                'data_source_format': tbl.get('data_source_format', 'DELTA'),
                'storage_location': tbl.get('storage_location'),
                'owner': tbl.get('owner'),
                'comment': tbl.get('comment'),
                'created_at': tbl.get('created_at'),
                'updated_at': tbl.get('updated_at'),
                'properties': tbl.get('properties', {}),
            }
        else:
            return {
                'name': getattr(tbl, 'name', table_name),
                'catalog_name': getattr(tbl, 'catalog_name', catalog_name),
                'schema_name': getattr(tbl, 'schema_name', schema_name),
                'table_type': getattr(tbl, 'table_type', 'MANAGED'),
                'data_source_format': getattr(tbl, 'data_source_format', 'DELTA'),
                'storage_location': getattr(tbl, 'storage_location', None),
                'owner': getattr(tbl, 'owner', None),
                'comment': getattr(tbl, 'comment', None),
                'created_at': getattr(tbl, 'created_at', None),
                'updated_at': getattr(tbl, 'updated_at', None),
                'properties': getattr(tbl, 'properties', {}),
            }

    def list_columns(self, catalog_name: str, schema_name: str, object_name: str) -> List[Dict[str, Any]]:
        """List columns for a table or view in Unity Catalog.

        Args:
            catalog_name: Name of the catalog
            schema_name: Name of the schema
            object_name: Name of the table or view

        Returns:
            List of column info dicts with name, type, comment (optional)
        """
        try:
            tbl = None
            try:
                get_method = getattr(self.client.tables, 'get', None)
                if callable(get_method):
                    tbl = get_method(catalog_name=catalog_name, schema_name=schema_name, name=object_name)
                else:
                    raise AttributeError('tables.get not available')
            except Exception:
                path = f"/api/2.1/unity-catalog/tables/{quote(f'{catalog_name}.{schema_name}.{object_name}', safe='')}"
                tbl = self.client.api_client.do('GET', path)

            schema = self._extract_schema(tbl)
            # Return a simple list for the columns API: id = catalog.schema.table.columnName
            result = []
            for col in schema:
                col_name = col.get('name')
                if col_name:
                    result.append({
                        'id': f"{catalog_name}.{schema_name}.{object_name}.{col_name}",
                        'name': col_name,
                        'type': col.get('type') or col.get('physicalType') or 'string',
                        'comment': col.get('comment'),
                    })
            logger.debug(f"Retrieved {len(result)} columns for {catalog_name}.{schema_name}.{object_name}")
            return result
        except Exception as e:
            logger.error(f"Error listing columns for {catalog_name}.{schema_name}.{object_name}: {e!s}", exc_info=True)
            raise

    def _extract_schema(self, tbl: Any) -> List[Dict[str, Any]]:
        """Extract column schema information from a table object or dict."""
        schema: List[Dict[str, Any]] = []
        columns_iter = None
        
        if hasattr(tbl, 'columns'):
            columns_iter = tbl.columns
        elif isinstance(tbl, dict) and 'columns' in tbl:
            columns_iter = tbl['columns']

        if columns_iter:
            for col in columns_iter:
                if isinstance(col, dict):
                    col_name = col.get('name') or col.get('column_name')
                    col_type = col.get('type_text') or col.get('type_name') or col.get('data_type')
                    nullable = col.get('nullable')
                    comment = col.get('comment')
                    partition_index = col.get('partition_index')
                    type_name = col.get('type_name')
                else:
                    col_name = getattr(col, 'name', None) or getattr(col, 'column_name', None)
                    col_type = getattr(col, 'type_text', None) or getattr(col, 'type_name', None) or getattr(col, 'data_type', None)
                    nullable = getattr(col, 'nullable', None)
                    comment = getattr(col, 'comment', None)
                    partition_index = getattr(col, 'partition_index', None)
                    type_name = getattr(col, 'type_name', None)

                logical_type = self._map_to_odcs_logical_type(col_type)

                column_meta = {
                    'name': col_name,
                    'type': col_type,
                    'physicalType': type_name or col_type,
                    'logicalType': logical_type,
                    'nullable': nullable,
                    'comment': comment,
                    'partitioned': partition_index is not None,
                    'partitionKeyPosition': partition_index,
                }
                schema.append(column_meta)
        
        return schema

    def _map_to_odcs_logical_type(self, databricks_type: str) -> str:
        """Map Databricks data types to ODCS logical types.

        Args:
            databricks_type: The Databricks data type (e.g., 'int', 'bigint', 'varchar(255)')

        Returns:
            ODCS-compliant logical type
        """
        if not databricks_type:
            return 'string'

        # Normalize type string
        db_type = databricks_type.lower().strip()

        # Check complex types first (most specific)

        # Array types (check for array< or array() patterns)
        if 'array' in db_type and ('<' in db_type or '(' in db_type):
            return 'array'

        # Object/struct types
        if any(t in db_type for t in ['struct', 'map', 'object']):
            return 'object'

        # Boolean type
        if 'boolean' in db_type or 'bool' in db_type:
            return 'boolean'

        # Date/time types
        if any(t in db_type for t in ['date', 'timestamp', 'time']):
            return 'date'

        # Number types
        if any(t in db_type for t in ['double', 'float', 'decimal', 'numeric']):
            return 'number'

        # Integer types
        if any(t in db_type for t in ['int', 'bigint', 'smallint', 'tinyint']):
            return 'integer'

        # String types (least specific, check last)
        if any(t in db_type for t in ['string', 'varchar', 'char', 'text']):
            return 'string'

        # Default fallback
        return 'string'

    def health_check(self) -> Dict[str, str]:
        """Check if the catalog API is healthy.
        
        Returns:
            Dictionary containing health status
        """
        try:
            # Try to list catalogs as a health check
            self.client.catalogs.list()
            logger.info("Health check successful")
            return {"status": "healthy"}
        except Exception as e:
            error_msg = f"Health check failed: {e!s}"
            logger.error(error_msg)
            raise
