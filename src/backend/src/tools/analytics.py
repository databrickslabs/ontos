"""
Analytics tools for LLM.

Tools for querying table schemas, executing analytics queries,
and exploring Unity Catalog schemas.
"""

from typing import Any, Dict, Optional

from src.common.logging import get_logger
from src.common.sql_validator import SQLValidator, validate_and_prepare_query
from src.tools.base import BaseTool, ToolContext, ToolResult, tool_failure

logger = get_logger(__name__)


class GetTableSchemaTool(BaseTool):
    """Get the schema (columns and data types) of a table from a data product."""
    
    name = "get_table_schema"
    category = "unity_catalog"
    description = "Get the schema (columns and data types) of a table from a data product."
    parameters = {
        "table_fqn": {
            "type": "string",
            "description": "Fully qualified table name (catalog.schema.table)"
        }
    }
    required_params = ["table_fqn"]
    required_scope = "analytics:read"
    
    def __init__(self):
        self._sql_validator = SQLValidator(max_row_limit=1000)
    
    async def execute(
        self,
        ctx: ToolContext,
        table_fqn: str
    ) -> ToolResult:
        """Get schema for a table. Uses OBO workspace client for access control."""
        logger.info(f"[get_table_schema] Starting for table: {table_fqn}")
        
        if not ctx.workspace_client:
            logger.error(f"[get_table_schema] FAILED: Workspace client not available")
            return ToolResult(success=False, error="Workspace client not available")
        
        try:
            # Validate table name
            self._sql_validator.sanitize_identifier(table_fqn)
            logger.debug(f"[get_table_schema] Table name validated: {table_fqn}")
            
            # Get table info from Unity Catalog
            logger.debug(f"[get_table_schema] Calling ws_client.tables.get for {table_fqn}")
            table_info = ctx.workspace_client.tables.get(full_name=table_fqn)
            
            columns = []
            if table_info.columns:
                for col in table_info.columns:
                    columns.append({
                        "name": col.name,
                        "type": col.type_text,
                        "nullable": col.nullable,
                        "comment": col.comment
                    })
            
            logger.info(f"[get_table_schema] SUCCESS: Found {len(columns)} columns for {table_fqn}")
            return ToolResult(
                success=True,
                data={
                    "table_fqn": table_fqn,
                    "columns": columns,
                    "table_type": str(table_info.table_type) if table_info.table_type else None,
                    "comment": table_info.comment
                }
            )
            
        except Exception as e:
                        return ToolResult(
                success=False,
                **tool_failure(f"get_table_schema {table_fqn}", e),
                data={"table_fqn": table_fqn}
            )


class ExecuteAnalyticsQueryTool(BaseTool):
    """Execute a read-only SQL SELECT query against Databricks tables."""
    
    name = "execute_analytics_query"
    category = "analytics"
    description = "Execute a read-only SQL SELECT query against Databricks tables. Use for aggregations, joins, filtering."
    parameters = {
        "sql": {
            "type": "string",
            "description": "The SQL SELECT query to execute"
        },
        "explanation": {
            "type": "string",
            "description": "Brief explanation of what this query does and why"
        }
    }
    required_params = ["sql", "explanation"]
    required_scope = "analytics:read"
    
    async def execute(
        self,
        ctx: ToolContext,
        sql: str,
        explanation: str
    ) -> ToolResult:
        """Execute an analytics query. Uses OBO workspace client for access control."""
        logger.info(f"[execute_analytics_query] Starting - explanation: {explanation}")
        logger.debug(f"[execute_analytics_query] SQL: {sql[:500]}...")
        
        if not ctx.workspace_client:
            logger.error(f"[execute_analytics_query] FAILED: Workspace client not available")
            return ToolResult(success=False, error="Workspace client not available")
        
        try:
            # Validate and prepare query
            is_valid, prepared_sql, error = validate_and_prepare_query(
                sql,
                allowed_tables=None,  # TODO: Check user permissions
                max_rows=1000
            )
            
            if not is_valid:
                logger.warning(f"[execute_analytics_query] Query validation failed: {error}")
                return ToolResult(success=False, error=f"Query validation failed: {error}")
            
            logger.info(f"[execute_analytics_query] Executing validated query: {prepared_sql[:200]}...")
            
            # Execute query
            # Note: This uses statement execution API
            warehouse_id = ctx.settings.DATABRICKS_WAREHOUSE_ID
            
            result = ctx.workspace_client.statement_execution.execute_statement(
                statement=prepared_sql,
                warehouse_id=warehouse_id,
                wait_timeout="30s"
            )
            
            # Check status
            if result.status and result.status.state:
                state = str(result.status.state)
                if "FAILED" in state or "CANCELED" in state:
                    error_msg = result.status.error.message if result.status.error else "Query failed"
                    return ToolResult(
                        success=False,
                        error=error_msg,
                        data={"state": state}
                    )
            
            # Extract results
            columns = []
            if result.manifest and result.manifest.schema and result.manifest.schema.columns:
                columns = [col.name for col in result.manifest.schema.columns]
            
            rows = []
            if result.result and result.result.data_array:
                rows = result.result.data_array
            
            truncated = len(rows) >= 1000
            
            logger.info(f"[execute_analytics_query] SUCCESS: {len(rows)} rows returned, {len(columns)} columns")
            return ToolResult(
                success=True,
                data={
                    "columns": columns,
                    "rows": rows[:100],  # Limit for response size
                    "row_count": len(rows),
                    "explanation": explanation,
                    "truncated": truncated,
                    "full_result_available": len(rows) > 100
                }
            )
            
        except Exception as e:
            return ToolResult(success=False, **tool_failure("execute_analytics_query", e))


class ExploreCatalogSchemaTool(BaseTool):
    """List all tables and views in a Unity Catalog schema."""
    
    name = "explore_catalog_schema"
    category = "unity_catalog"
    description = "List all tables and views in a Unity Catalog schema, including their columns and types. Use this to understand what data assets exist in a database/schema and suggest semantic models or data products."
    parameters = {
        "catalog": {
            "type": "string",
            "description": "Catalog name (e.g., 'demo_cat', 'main')"
        },
        "schema": {
            "type": "string",
            "description": "Schema/database name (e.g., 'demo_db', 'default')"
        },
        "include_columns": {
            "type": "boolean",
            "description": "If true, include column details for each table (default: true)"
        }
    }
    required_params = ["catalog", "schema"]
    required_scope = "analytics:read"
    
    async def execute(
        self,
        ctx: ToolContext,
        catalog: str,
        schema: str,
        include_columns: bool = True
    ) -> ToolResult:
        """Explore all tables and views in a Unity Catalog schema. Uses OBO workspace client for access control."""
        logger.info(f"[explore_catalog_schema] Starting for {catalog}.{schema} (include_columns={include_columns})")
        
        if not ctx.workspace_client:
            logger.error(f"[explore_catalog_schema] FAILED: Workspace client not available")
            return ToolResult(success=False, error="Workspace client not available")
        
        try:
            logger.debug(f"[explore_catalog_schema] Calling ws_client.tables.list for {catalog}.{schema}")
            
            # List tables in the schema
            tables_iterator = ctx.workspace_client.tables.list(
                catalog_name=catalog,
                schema_name=schema
            )
            tables_list = list(tables_iterator)
            
            if not tables_list:
                return ToolResult(
                    success=True,
                    data={
                        "catalog": catalog,
                        "schema": schema,
                        "table_count": 0,
                        "tables": [],
                        "message": f"No tables found in {catalog}.{schema}"
                    }
                )
            
            tables = []
            for table in tables_list:
                table_info: Dict[str, Any] = {
                    "name": table.name,
                    "full_name": table.full_name,
                    "table_type": str(table.table_type).replace("TableType.", "") if table.table_type else None,
                    "comment": table.comment,
                }
                
                # Get detailed column info if requested
                if include_columns:
                    try:
                        # Get full table details including columns
                        table_details = ctx.workspace_client.tables.get(full_name=table.full_name)
                        if table_details.columns:
                            table_info["columns"] = [
                                {
                                    "name": col.name,
                                    "type": col.type_text,
                                    "comment": col.comment,
                                    "nullable": col.nullable
                                }
                                for col in table_details.columns
                            ]
                            table_info["column_count"] = len(table_details.columns)
                    except Exception as col_err:
                        logger.warning(f"Could not get columns for {table.full_name}: {col_err}")
                        table_info["columns"] = []
                        table_info["column_error"] = str(col_err)
                
                tables.append(table_info)
            
            logger.info(f"[explore_catalog_schema] SUCCESS: Found {len(tables)} tables/views in {catalog}.{schema}")
            return ToolResult(
                success=True,
                data={
                    "catalog": catalog,
                    "schema": schema,
                    "table_count": len(tables),
                    "tables": tables,
                    "message": f"Found {len(tables)} tables/views in {catalog}.{schema}"
                }
            )
            
        except Exception as e:
                        return ToolResult(
                success=False,
                **tool_failure(f"explore_catalog_schema {catalog}.{schema}", e),
                data={"catalog": catalog, "schema": schema}
            )

