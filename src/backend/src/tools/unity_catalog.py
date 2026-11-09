"""
Unity Catalog browsing tools for LLM.

Tools for listing and exploring Unity Catalog hierarchy:
catalogs, schemas, and their metadata.
"""

from typing import Any, Dict, List, Optional

from src.common.logging import get_logger
from src.tools.base import BaseTool, ToolContext, ToolResult, tool_failure

logger = get_logger(__name__)


class GetCurrentUserTool(BaseTool):
    """Get information about the current authenticated user."""
    
    name = "get_current_user"
    category = "discovery"
    description = (
        "Get the current user's email, username, and ID. "
        "Use this to find assets owned by or assigned to the current user, "
        "such as 'my catalogs', 'my data products', or 'tables I own'."
    )
    parameters = {}
    required_params = []
    required_scope = "user:read"
    
    async def execute(self, ctx: ToolContext) -> ToolResult:
        """Get the current user's information from the workspace client."""
        logger.info("[get_current_user] Starting")
        
        if not ctx.workspace_client:
            logger.error("[get_current_user] FAILED: Workspace client not available")
            return ToolResult(success=False, error="Workspace client not available")
        
        try:
            user = ctx.workspace_client.current_user.me()
            
            user_info = {
                "email": user.user_name,
                "display_name": getattr(user, 'display_name', None),
                "user_id": getattr(user, 'id', None),
            }
            
            logger.info(f"[get_current_user] SUCCESS: {user_info['email']}")
            return ToolResult(
                success=True,
                data={
                    "user": user_info,
                    "message": f"Current user: {user_info['email']}"
                }
            )
            
        except Exception as e:
            return ToolResult(
                success=False,
                **tool_failure("get_current_user", e)
            )


class ListCatalogsTool(BaseTool):
    """List all Unity Catalog catalogs accessible to the user."""
    
    name = "list_catalogs"
    category = "unity_catalog"
    description = (
        "List all Unity Catalog catalogs accessible to the user, with owner and metadata. "
        "Use this to answer questions like 'Which catalogs do I own?' or 'Show me all catalogs'."
    )
    parameters = {
        "owner_filter": {
            "type": "string",
            "description": "Optional: filter catalogs by owner email/username to find catalogs owned by a specific user"
        },
        "limit": {
            "type": "integer",
            "description": "Maximum number of catalogs to return (default: 50, max: 100)"
        }
    }
    required_params = []
    required_scope = "analytics:read"
    
    async def execute(
        self,
        ctx: ToolContext,
        owner_filter: Optional[str] = None,
        limit: int = 50
    ) -> ToolResult:
        """List all catalogs the user has access to."""
        limit = min(max(1, limit), 100)  # Clamp to 1-100
        logger.info(f"[list_catalogs] Starting (owner_filter={owner_filter}, limit={limit})")
        
        if not ctx.workspace_client:
            logger.error("[list_catalogs] FAILED: Workspace client not available")
            return ToolResult(success=False, error="Workspace client not available")
        
        try:
            # List all catalogs
            catalogs_list = list(ctx.workspace_client.catalogs.list())
            
            catalogs = []
            for catalog in catalogs_list:
                owner = getattr(catalog, 'owner', None)
                
                # Apply owner filter if specified
                if owner_filter:
                    if not owner or owner_filter.lower() not in owner.lower():
                        continue
                
                catalogs.append({
                    "name": catalog.name,
                    "owner": owner,
                    "comment": getattr(catalog, 'comment', None),
                    "created_at": str(getattr(catalog, 'created_at', None)) if getattr(catalog, 'created_at', None) else None,
                    "updated_at": str(getattr(catalog, 'updated_at', None)) if getattr(catalog, 'updated_at', None) else None,
                })
            
            total_count = len(catalogs)
            truncated = total_count > limit
            catalogs = catalogs[:limit]
            
            message = f"Found {total_count} catalog(s)"
            if owner_filter:
                message += f" matching owner filter '{owner_filter}'"
            if truncated:
                message += f" (showing first {limit})"
            
            logger.info(f"[list_catalogs] SUCCESS: {message}")
            return ToolResult(
                success=True,
                data={
                    "catalogs": catalogs,
                    "count": len(catalogs),
                    "total_count": total_count,
                    "truncated": truncated,
                    "message": message
                }
            )
            
        except Exception as e:
            return ToolResult(
                success=False,
                **tool_failure("list_catalogs", e)
            )


class GetCatalogDetailsTool(BaseTool):
    """Get detailed information about a specific Unity Catalog catalog."""
    
    name = "get_catalog_details"
    category = "unity_catalog"
    description = (
        "Get detailed information about a specific Unity Catalog catalog, "
        "including owner, comment, properties, and schema count. "
        "Use this to answer questions like 'Tell me about the sales catalog' or 'Who owns demo_cat?'."
    )
    parameters = {
        "catalog_name": {
            "type": "string",
            "description": "The name of the catalog to get details for"
        }
    }
    required_params = ["catalog_name"]
    required_scope = "analytics:read"
    
    async def execute(
        self,
        ctx: ToolContext,
        catalog_name: str
    ) -> ToolResult:
        """Get detailed info about a specific catalog."""
        logger.info(f"[get_catalog_details] Starting for catalog: {catalog_name}")
        
        if not ctx.workspace_client:
            logger.error("[get_catalog_details] FAILED: Workspace client not available")
            return ToolResult(success=False, error="Workspace client not available")
        
        try:
            # Get catalog details
            catalog = ctx.workspace_client.catalogs.get(catalog_name)
            
            # Count schemas in the catalog
            schema_count = 0
            try:
                schemas = list(ctx.workspace_client.schemas.list(catalog_name=catalog_name))
                schema_count = len(schemas)
            except Exception as schema_err:
                logger.warning(f"Could not count schemas for {catalog_name}: {schema_err}")
            
            catalog_info = {
                "name": catalog.name,
                "owner": getattr(catalog, 'owner', None),
                "comment": getattr(catalog, 'comment', None),
                "created_at": str(getattr(catalog, 'created_at', None)) if getattr(catalog, 'created_at', None) else None,
                "updated_at": str(getattr(catalog, 'updated_at', None)) if getattr(catalog, 'updated_at', None) else None,
                "properties": dict(getattr(catalog, 'properties', {}) or {}),
                "schema_count": schema_count,
                "isolation_mode": str(getattr(catalog, 'isolation_mode', None)) if getattr(catalog, 'isolation_mode', None) else None,
                "securable_type": str(getattr(catalog, 'securable_type', None)) if getattr(catalog, 'securable_type', None) else None,
            }
            
            logger.info(f"[get_catalog_details] SUCCESS: Retrieved details for {catalog_name}")
            return ToolResult(
                success=True,
                data={
                    "catalog": catalog_info,
                    "message": f"Retrieved details for catalog '{catalog_name}'"
                }
            )
            
        except Exception as e:
                        return ToolResult(
                success=False,
                **tool_failure(f"get_catalog_details {catalog_name}", e),
                data={"catalog_name": catalog_name}
            )


class ListSchemasTool(BaseTool):
    """List all schemas in a Unity Catalog catalog."""
    
    name = "list_schemas"
    category = "unity_catalog"
    description = (
        "List all schemas (databases) in a Unity Catalog catalog, with owner and metadata. "
        "Use this to answer questions like 'What schemas are in main catalog?' or "
        "'Show my schemas in demo_cat'."
    )
    parameters = {
        "catalog_name": {
            "type": "string",
            "description": "The name of the catalog to list schemas from"
        },
        "owner_filter": {
            "type": "string",
            "description": "Optional: filter schemas by owner email/username"
        },
        "include_table_count": {
            "type": "boolean",
            "description": "If true, include the count of tables in each schema (slower). Default: false"
        },
        "limit": {
            "type": "integer",
            "description": "Maximum number of schemas to return (default: 50, max: 100)"
        }
    }
    required_params = ["catalog_name"]
    required_scope = "analytics:read"
    
    async def execute(
        self,
        ctx: ToolContext,
        catalog_name: str,
        owner_filter: Optional[str] = None,
        include_table_count: bool = False,
        limit: int = 50
    ) -> ToolResult:
        """List all schemas in a catalog."""
        limit = min(max(1, limit), 100)  # Clamp to 1-100
        logger.info(f"[list_schemas] Starting for catalog: {catalog_name} (owner_filter={owner_filter}, include_table_count={include_table_count}, limit={limit})")
        
        if not ctx.workspace_client:
            logger.error("[list_schemas] FAILED: Workspace client not available")
            return ToolResult(success=False, error="Workspace client not available")
        
        try:
            # List schemas in the catalog
            schemas_list = list(ctx.workspace_client.schemas.list(catalog_name=catalog_name))
            
            schemas = []
            for schema in schemas_list:
                owner = getattr(schema, 'owner', None)
                
                # Apply owner filter if specified
                if owner_filter:
                    if not owner or owner_filter.lower() not in owner.lower():
                        continue
                
                schema_info: Dict[str, Any] = {
                    "name": schema.name,
                    "full_name": getattr(schema, 'full_name', None) or f"{catalog_name}.{schema.name}",
                    "owner": owner,
                    "comment": getattr(schema, 'comment', None),
                    "created_at": str(getattr(schema, 'created_at', None)) if getattr(schema, 'created_at', None) else None,
                    "updated_at": str(getattr(schema, 'updated_at', None)) if getattr(schema, 'updated_at', None) else None,
                }
                
                # Optionally get table count
                if include_table_count:
                    try:
                        tables = list(ctx.workspace_client.tables.list(
                            catalog_name=catalog_name,
                            schema_name=schema.name
                        ))
                        schema_info["table_count"] = len(tables)
                    except Exception as table_err:
                        logger.warning(f"Could not count tables for {catalog_name}.{schema.name}: {table_err}")
                        schema_info["table_count"] = None
                
                schemas.append(schema_info)
            
            total_count = len(schemas)
            truncated = total_count > limit
            schemas = schemas[:limit]
            
            message = f"Found {total_count} schema(s) in catalog '{catalog_name}'"
            if owner_filter:
                message += f" matching owner filter '{owner_filter}'"
            if truncated:
                message += f" (showing first {limit})"
            
            logger.info(f"[list_schemas] SUCCESS: {message}")
            return ToolResult(
                success=True,
                data={
                    "catalog_name": catalog_name,
                    "schemas": schemas,
                    "count": len(schemas),
                    "total_count": total_count,
                    "truncated": truncated,
                    "message": message
                }
            )
            
        except Exception as e:
                        return ToolResult(
                success=False,
                **tool_failure(f"list_schemas {catalog_name}", e),
                data={"catalog_name": catalog_name}
            )

