"""
Domains tools for LLM.

Tools for searching, creating, updating, and deleting data domains.
"""

from typing import Any, Dict, List, Optional
from uuid import UUID

from src.common.logging import get_logger
from src.controller import search_scoring
from src.tools.base import BaseTool, ToolContext, ToolResult

logger = get_logger(__name__)


class SearchDomainsTool(BaseTool):
    """Search for data domains via the shared, tokenized search index."""

    name = "search_domains"
    category = "organization"
    description = (
        "Search data domains by name or description. Use FEW BROAD terms, not full "
        "sentences — each term is matched independently and results are ranked by "
        "relevance. Leave 'query' empty (or '*') to list domains; the response is always "
        "paginated and includes 'total_count' and 'has_more'. Page with 'offset' instead "
        "of broadening the query."
    )
    parameters = {
        "query": {
            "type": "string",
            "description": "Search terms (e.g., 'customer', 'finance'). Empty or '*' lists all domains."
        },
        "limit": {
            "type": "integer",
            "description": "Max results to return (default: 25, max: 100)."
        },
        "offset": {
            "type": "integer",
            "description": "Number of results to skip for pagination (default: 0)."
        }
    }
    required_params = ["query"]
    required_scope = "domains:read"

    async def execute(
        self,
        ctx: ToolContext,
        query: str = "",
        limit: int = 25,
        offset: int = 0,
    ) -> ToolResult:
        """Search data domains over the shared in-memory index."""
        logger.info(f"[search_domains] Starting - query='{query}', limit={limit}, offset={offset}")

        if not ctx.search_manager:
            logger.warning("[search_domains] FAILED: search_manager is None")
            return ToolResult(success=False, error="Search not available", data={"domains": []})

        try:
            data = search_scoring.search_index(
                ctx.search_manager.index,
                query,
                ctx.search_manager.config,
                type_filter="data-domain",
                limit=limit,
                offset=offset,
            )
            logger.info(
                f"[search_domains] SUCCESS: returned {data['returned']} of "
                f"{data['total_count']} matching domains"
            )
            return ToolResult(
                success=True,
                data={
                    "domains": data["results"],
                    "total_found": data["total_count"],
                    "returned": data["returned"],
                    "offset": data["offset"],
                    "limit": data["limit"],
                    "has_more": data["has_more"],
                    "query": query,
                },
            )

        except Exception as e:
            logger.error(f"[search_domains] FAILED: {e.__class__.__name__}: {e}", exc_info=True)
            return ToolResult(success=False, error=f"{e.__class__.__name__}: {str(e)}", data={"domains": []})


class GetDomainTool(BaseTool):
    """Get a single data domain by ID."""
    
    name = "get_domain"
    category = "organization"
    description = "Get detailed information about a specific data domain by its ID."
    parameters = {
        "domain_id": {
            "type": "string",
            "description": "The ID of the data domain to retrieve"
        }
    }
    required_params = ["domain_id"]
    required_scope = "domains:read"
    
    async def execute(
        self,
        ctx: ToolContext,
        domain_id: str
    ) -> ToolResult:
        """Get a data domain by ID."""
        logger.info(f"[get_domain] Starting - domain_id={domain_id}")
        
        try:
            from src.db_models.data_domains import DataDomain
            
            domain = ctx.db.query(DataDomain).filter(DataDomain.id == domain_id).first()
            
            if not domain:
                return ToolResult(
                    success=False,
                    error=f"Data domain '{domain_id}' not found"
                )
            
            # Get parent name if exists
            parent_name = None
            if domain.parent:
                parent_name = domain.parent.name
            
            # Get children count
            children_count = len(domain.children) if domain.children else 0
            
            logger.info(f"[get_domain] SUCCESS: Found domain {domain_id}")
            return ToolResult(
                success=True,
                data={
                    "id": str(domain.id),
                    "name": domain.name,
                    "description": domain.description,
                    "parent_id": str(domain.parent_id) if domain.parent_id else None,
                    "parent_name": parent_name,
                    "children_count": children_count,
                    "created_at": domain.created_at.isoformat() if domain.created_at else None,
                    "updated_at": domain.updated_at.isoformat() if domain.updated_at else None
                }
            )
            
        except Exception as e:
            logger.error(f"[get_domain] FAILED: {type(e).__name__}: {e}", exc_info=True)
            return ToolResult(success=False, error=f"{type(e).__name__}: {str(e)}")


class CreateDomainTool(BaseTool):
    """Create a new data domain."""
    
    name = "create_domain"
    category = "organization"
    description = "Create a new data domain. Domains can be organized hierarchically with parent-child relationships."
    parameters = {
        "name": {
            "type": "string",
            "description": "Name for the domain (e.g., 'Customer', 'Finance', 'Operations')"
        },
        "description": {
            "type": "string",
            "description": "Description of what this domain covers"
        },
        "parent_id": {
            "type": "string",
            "description": "Optional: ID of the parent domain for hierarchical organization"
        }
    }
    required_params = ["name"]
    required_scope = "domains:write"
    
    async def execute(
        self,
        ctx: ToolContext,
        name: str,
        description: Optional[str] = None,
        parent_id: Optional[str] = None
    ) -> ToolResult:
        """Create a data domain."""
        logger.info(f"[create_domain] Starting - name='{name}', parent_id={parent_id}")
        
        try:
            from src.repositories.data_domain_repository import data_domain_repo
            from src.models.data_domains import DataDomainCreate
            from src.controller.data_domains_manager import DataDomainManager
            
            manager = DataDomainManager(repository=data_domain_repo)
            
            domain_create = DataDomainCreate(
                name=name,
                description=description or "",
                parent_id=UUID(parent_id) if parent_id else None
            )
            
            created = manager.create_domain(
                db=ctx.db,
                domain_in=domain_create,
                current_user_id="llm-assistant"
            )
            
            ctx.db.commit()
            
            logger.info(f"[create_domain] SUCCESS: Created domain id={created.id}, name={created.name}")
            return ToolResult(
                success=True,
                data={
                    "success": True,
                    "domain_id": str(created.id),
                    "name": created.name,
                    "description": created.description,
                    "message": f"Domain '{name}' created successfully.",
                    "url": f"/data-domains/{created.id}"
                }
            )
            
        except Exception as e:
            logger.error(f"[create_domain] FAILED: {type(e).__name__}: {e}", exc_info=True)
            return ToolResult(success=False, error=f"{type(e).__name__}: {str(e)}")


class UpdateDomainTool(BaseTool):
    """Update an existing data domain."""
    
    name = "update_domain"
    category = "organization"
    description = "Update an existing data domain's name, description, or parent."
    parameters = {
        "domain_id": {
            "type": "string",
            "description": "ID of the domain to update"
        },
        "name": {
            "type": "string",
            "description": "New name for the domain"
        },
        "description": {
            "type": "string",
            "description": "New description"
        },
        "parent_id": {
            "type": "string",
            "description": "New parent domain ID (or null to make it a root domain)"
        }
    }
    required_params = ["domain_id"]
    required_scope = "domains:write"
    
    async def execute(
        self,
        ctx: ToolContext,
        domain_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        parent_id: Optional[str] = None
    ) -> ToolResult:
        """Update a data domain."""
        logger.info(f"[update_domain] Starting - domain_id={domain_id}")
        
        try:
            from src.repositories.data_domain_repository import data_domain_repo
            from src.models.data_domains import DataDomainUpdate
            from src.controller.data_domains_manager import DataDomainManager
            
            manager = DataDomainManager(repository=data_domain_repo)
            
            update_data: Dict[str, Any] = {}
            if name is not None:
                update_data["name"] = name
            if description is not None:
                update_data["description"] = description
            if parent_id is not None:
                update_data["parent_id"] = UUID(parent_id) if parent_id else None
            
            if not update_data:
                return ToolResult(
                    success=False,
                    error="No fields to update. Provide at least one of: name, description, parent_id"
                )
            
            domain_update = DataDomainUpdate(**update_data)
            
            updated = manager.update_domain(
                db=ctx.db,
                domain_id=UUID(domain_id),
                domain_in=domain_update,
                current_user_id="llm-assistant"
            )
            
            if not updated:
                return ToolResult(
                    success=False,
                    error=f"Domain '{domain_id}' not found"
                )
            
            ctx.db.commit()
            
            logger.info(f"[update_domain] SUCCESS: Updated domain id={updated.id}")
            return ToolResult(
                success=True,
                data={
                    "success": True,
                    "domain_id": str(updated.id),
                    "name": updated.name,
                    "message": f"Domain '{updated.name}' updated successfully.",
                    "url": f"/data-domains/{updated.id}"
                }
            )
            
        except Exception as e:
            logger.error(f"[update_domain] FAILED: {type(e).__name__}: {e}", exc_info=True)
            return ToolResult(success=False, error=f"{type(e).__name__}: {str(e)}")


class DeleteDomainTool(BaseTool):
    """Delete a data domain."""
    
    name = "delete_domain"
    category = "organization"
    description = "Delete a data domain by its ID. Note: Domains with children may be affected by cascade rules."
    parameters = {
        "domain_id": {
            "type": "string",
            "description": "The ID of the domain to delete"
        }
    }
    required_params = ["domain_id"]
    required_scope = "domains:write"
    
    async def execute(
        self,
        ctx: ToolContext,
        domain_id: str
    ) -> ToolResult:
        """Delete a data domain."""
        logger.info(f"[delete_domain] Starting - domain_id={domain_id}")
        
        try:
            from src.repositories.data_domain_repository import data_domain_repo
            from src.controller.data_domains_manager import DataDomainManager
            
            manager = DataDomainManager(repository=data_domain_repo)
            
            deleted = manager.delete_domain(
                db=ctx.db,
                domain_id=UUID(domain_id),
                current_user_id="llm-assistant"
            )
            
            if not deleted:
                return ToolResult(
                    success=False,
                    error=f"Domain '{domain_id}' not found or could not be deleted"
                )
            
            ctx.db.commit()
            
            logger.info(f"[delete_domain] SUCCESS: Deleted domain {domain_id}")
            return ToolResult(
                success=True,
                data={
                    "success": True,
                    "message": f"Domain '{deleted.name}' deleted successfully",
                    "domain_id": domain_id
                }
            )
            
        except Exception as e:
            logger.error(f"[delete_domain] FAILED: {type(e).__name__}: {e}", exc_info=True)
            return ToolResult(success=False, error=f"{type(e).__name__}: {str(e)}")
