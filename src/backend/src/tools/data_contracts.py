"""
Data Contracts tools for LLM.

Tools for searching, creating, updating, and deleting data contracts.
"""

import json
from typing import Any, Dict, List, Optional

from src.common.logging import get_logger
from src.tools.base import BaseTool, ToolContext, ToolResult

logger = get_logger(__name__)


class CreateDraftDataContractTool(BaseTool):
    """Create a new draft data contract based on schema information."""
    
    name = "create_draft_data_contract"
    category = "data_contracts"
    description = "Create a new draft data contract based on schema information. The contract will be created in 'draft' status for user review. Use after exploring a catalog schema to formalize a data asset."
    parameters = {
        "name": {
            "type": "string",
            "description": "Name for the contract (e.g., 'Customer Master Data Contract')"
        },
        "description": {
            "type": "string",
            "description": "Business description of what this contract governs"
        },
        "domain": {
            "type": "string",
            "description": "Business domain (e.g., 'Customer', 'Sales', 'Finance')"
        },
        "tables": {
            "type": "array",
            "description": "List of tables to include in the contract schema",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Table name"},
                    "full_name": {"type": "string", "description": "Fully qualified table name (catalog.schema.table)"},
                    "description": {"type": "string", "description": "Table description"},
                    "columns": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "type": {"type": "string"},
                                "description": {"type": "string"}
                            }
                        }
                    }
                }
            }
        }
    }
    required_params = ["name", "description", "domain"]
    required_scope = "contracts:write"
    
    async def execute(
        self,
        ctx: ToolContext,
        name: str,
        description: str,
        domain: str,
        tables: Optional[List[Dict[str, Any]]] = None
    ) -> ToolResult:
        """Create a draft data contract from schema information."""
        logger.info(f"[create_draft_data_contract] Starting - name='{name}', domain={domain}, tables={len(tables) if tables else 0}")
        
        if not ctx.data_contracts_manager:
            logger.error(f"[create_draft_data_contract] FAILED: Data contracts manager not available")
            return ToolResult(success=False, error="Data contracts manager not available")
        
        try:
            logger.debug(f"[create_draft_data_contract] Building contract data for '{name}'")
            
            # Build schema objects from tables
            schema_objects = []
            if tables:
                for table in tables:
                    properties = []
                    for col in table.get("columns", []):
                        properties.append({
                            "property": col.get("name"),
                            "logicalType": col.get("type", "string"),
                            "physicalType": col.get("type", "STRING"),
                            "businessName": col.get("name"),
                            "description": col.get("description", "")
                        })
                    
                    schema_objects.append({
                        "name": table.get("name"),
                        "physicalName": table.get("full_name") or table.get("name"),
                        "description": table.get("description", ""),
                        "properties": properties
                    })
            
            # Build contract data in ODCS format
            contract_data = {
                "apiVersion": "v3.1.0",
                "kind": "DataContract",
                "name": name,
                "version": "0.1.0",
                "status": "draft",
                "domain": domain,
                "description": {
                    "purpose": description
                },
                "schema": schema_objects
            }
            
            # Create the contract
            created = ctx.data_contracts_manager.create_contract_with_relations(
                db=ctx.db,
                contract_data=contract_data,
                current_user=None  # Will use system default
            )
            
            logger.info(f"[create_draft_data_contract] SUCCESS: Created contract id={created.id}, name={created.name}")
            return ToolResult(
                success=True,
                data={
                    "success": True,
                    "contract_id": created.id,
                    "name": created.name,
                    "version": created.version,
                    "status": created.status,
                    "message": f"Draft contract '{name}' created successfully. Review and publish it in the Data Contracts UI.",
                    "url": f"/data-contracts/{created.id}"
                }
            )
            
        except Exception as e:
            logger.error(f"[create_draft_data_contract] FAILED: {type(e).__name__}: {e}", exc_info=True)
            return ToolResult(success=False, error=f"{type(e).__name__}: {str(e)}")


class UpdateDataContractTool(BaseTool):
    """Update an existing data contract's properties."""
    
    name = "update_data_contract"
    category = "data_contracts"
    description = "Update an existing data contract's properties like domain, description, or status."
    parameters = {
        "contract_id": {
            "type": "string",
            "description": "ID of the data contract to update"
        },
        "domain": {
            "type": "string",
            "description": "New business domain"
        },
        "description": {
            "type": "string",
            "description": "New business description/purpose"
        },
        "status": {
            "type": "string",
            "description": "New status (draft, active, deprecated)",
            "enum": ["draft", "active", "deprecated"]
        }
    }
    required_params = ["contract_id"]
    required_scope = "contracts:write"
    
    async def execute(
        self,
        ctx: ToolContext,
        contract_id: str,
        domain: Optional[str] = None,
        description: Optional[str] = None,
        status: Optional[str] = None
    ) -> ToolResult:
        """Update an existing data contract."""
        logger.info(f"[update_data_contract] Starting - contract_id={contract_id}, domain={domain}, status={status}")
        
        if not ctx.data_contracts_manager:
            logger.error(f"[update_data_contract] FAILED: Data contracts manager not available")
            return ToolResult(success=False, error="Data contracts manager not available")
        
        try:
            # Build update data
            update_data: Dict[str, Any] = {}
            if domain is not None:
                update_data["domain"] = domain
            if description is not None:
                update_data["description"] = {"purpose": description}
            if status is not None:
                update_data["status"] = status
            
            if not update_data:
                return ToolResult(
                    success=False,
                    error="No fields to update. Provide at least one of: domain, description, status"
                )
            
            # Update the contract
            updated = ctx.data_contracts_manager.update_contract_with_relations(
                db=ctx.db,
                contract_id=contract_id,
                contract_data=update_data,
                current_user=None
            )
            
            if not updated:
                return ToolResult(
                    success=False,
                    error=f"Data contract '{contract_id}' not found"
                )
            
            logger.info(f"[update_data_contract] SUCCESS: Updated contract id={updated.id}")
            return ToolResult(
                success=True,
                data={
                    "success": True,
                    "contract_id": updated.id,
                    "name": updated.name,
                    "domain": updated.domain,
                    "status": updated.status,
                    "message": f"Contract '{updated.name}' updated successfully.",
                    "url": f"/data-contracts/{updated.id}"
                }
            )
            
        except Exception as e:
            logger.error(f"[update_data_contract] FAILED: {type(e).__name__}: {e}", exc_info=True)
            return ToolResult(success=False, error=f"{type(e).__name__}: {str(e)}")


class SearchDataContractsTool(BaseTool):
    """Search for data contracts via the shared, tokenized search index."""

    name = "search_data_contracts"
    category = "data_contracts"
    description = (
        "Search data contracts by name, domain, description or tags. Use FEW BROAD "
        "terms, not full sentences — each term is matched independently and results are "
        "ranked by relevance. Narrow with the 'domain'/'status' filters and page with "
        "'offset' instead of broadening the query. Leave 'query' empty (or '*') to list "
        "contracts; the response is always paginated and includes 'total_count', "
        "'has_more' and 'facets' so you can refine rather than fetch everything."
    )
    parameters = {
        "query": {
            "type": "string",
            "description": "Search terms (e.g., 'orders', 'customer'). Empty or '*' lists all contracts."
        },
        "domain": {
            "type": "string",
            "description": "Optional filter by domain."
        },
        "status": {
            "type": "string",
            "enum": ["draft", "active", "deprecated"],
            "description": "Optional filter by status."
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
    required_scope = "contracts:read"

    async def execute(
        self,
        ctx: ToolContext,
        query: str = "",
        domain: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 25,
        offset: int = 0,
    ) -> ToolResult:
        """Search data contracts over the shared in-memory index."""
        logger.info(
            f"[search_data_contracts] Starting - query='{query}', domain={domain}, "
            f"status={status}, limit={limit}, offset={offset}"
        )

        if not ctx.search_manager:
            logger.warning("[search_data_contracts] FAILED: search_manager is None")
            return ToolResult(success=False, error="Search not available", data={"contracts": []})

        try:
            data = ctx.search_manager.query_index(
                query,
                type_filter="data-contract",
                filters={"domain": domain, "status": status},
                limit=limit,
                offset=offset,
            )
            logger.info(
                f"[search_data_contracts] SUCCESS: returned {data['returned']} of "
                f"{data['total_count']} matching contracts"
            )
            return ToolResult(
                success=True,
                data={
                    "contracts": data["results"],
                    "total_found": data["total_count"],
                    "returned": data["returned"],
                    "offset": data["offset"],
                    "limit": data["limit"],
                    "has_more": data["has_more"],
                    "facets": data["facets"],
                    "query": query,
                },
            )

        except Exception as e:
            logger.error(f"[search_data_contracts] FAILED: {e.__class__.__name__}: {e}", exc_info=True)
            return ToolResult(success=False, error=f"{e.__class__.__name__}: {str(e)}", data={"contracts": []})


class GetDataContractTool(BaseTool):
    """Get a data contract by ID."""
    
    name = "get_data_contract"
    category = "data_contracts"
    description = "Get detailed information about a specific data contract by its ID."
    parameters = {
        "contract_id": {
            "type": "string",
            "description": "ID of the data contract to retrieve"
        }
    }
    required_params = ["contract_id"]
    required_scope = "contracts:read"
    
    async def execute(self, ctx: ToolContext, contract_id: str) -> ToolResult:
        """Get a data contract by ID."""
        logger.info(f"[get_data_contract] Starting - contract_id={contract_id}")
        
        if not ctx.data_contracts_manager:
            logger.error(f"[get_data_contract] FAILED: Data contracts manager not available")
            return ToolResult(success=False, error="Data contracts manager not available")
        
        try:
            # DB-backed read: the legacy in-memory manager.get_contract() is empty in a
            # deployed app, so go through the repo + API builder used by the REST path (#918).
            from src.repositories.data_contracts_repository import data_contract_repo

            db_obj = data_contract_repo.get_with_all(ctx.db, id=contract_id)
            if not db_obj:
                return ToolResult(
                    success=False,
                    error=f"Data contract '{contract_id}' not found"
                )

            contract = ctx.data_contracts_manager._build_contract_api_model(ctx.db, db_obj)
            desc = getattr(contract, 'description', None)
            desc_purpose = getattr(desc, 'purpose', None) if desc is not None else None

            logger.info(f"[get_data_contract] SUCCESS: Found contract {contract.name}")
            return ToolResult(
                success=True,
                data={
                    "id": contract.id,
                    "name": contract.name,
                    "domain": getattr(contract, 'domain', None),
                    "description": desc_purpose,
                    "status": contract.status,
                    "version": contract.version,
                    "owner_team_name": getattr(contract, 'owner_team_name', None),
                    "data_product": getattr(contract, 'dataProduct', None),
                    "url": f"/data-contracts/{contract.id}"
                }
            )

        except Exception as e:
            logger.error(f"[get_data_contract] FAILED: {type(e).__name__}: {e}", exc_info=True)
            return ToolResult(success=False, error=f"{type(e).__name__}: {str(e)}")


class ListDataContractsTool(BaseTool):
    """List all data contracts."""
    
    name = "list_data_contracts"
    category = "data_contracts"
    description = "List all data contracts with optional filtering."
    parameters = {
        "domain": {
            "type": "string",
            "description": "Optional filter by domain"
        },
        "status": {
            "type": "string",
            "enum": ["draft", "active", "deprecated"],
            "description": "Optional filter by status"
        },
        "limit": {
            "type": "integer",
            "description": "Maximum number of contracts to return (default: 50)"
        }
    }
    required_params = []
    required_scope = "contracts:read"
    
    async def execute(
        self,
        ctx: ToolContext,
        domain: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50
    ) -> ToolResult:
        """List all data contracts."""
        logger.info(f"[list_data_contracts] Starting - domain={domain}, status={status}, limit={limit}")
        
        if not ctx.data_contracts_manager:
            logger.error(f"[list_data_contracts] FAILED: Data contracts manager not available")
            return ToolResult(success=False, error="Data contracts manager not available")
        
        try:
            # DB-backed list: the legacy in-memory manager.list_contracts() is empty in a
            # deployed app; use the summary query used by the REST list endpoint (#918).
            summaries = ctx.data_contracts_manager.list_contracts_from_db(
                ctx.db, status=status, is_admin=True,
            )

            filtered = []
            for c in summaries:
                # Domain is filtered here by name (the DB query filters by domain_id).
                if domain and (getattr(c, 'domain', None) or '').lower() != domain.lower():
                    continue
                filtered.append({
                    "id": c.id,
                    "name": c.name,
                    "domain": getattr(c, 'domain', None),
                    "status": c.status,
                    "version": c.version,
                    "owner_team_name": getattr(c, 'owner_team_name', None),
                })
                if len(filtered) >= limit:
                    break

            logger.info(f"[list_data_contracts] SUCCESS: Found {len(filtered)} contracts")
            return ToolResult(
                success=True,
                data={
                    "contracts": filtered,
                    "total_found": len(filtered)
                }
            )

        except Exception as e:
            logger.error(f"[list_data_contracts] FAILED: {type(e).__name__}: {e}", exc_info=True)
            return ToolResult(success=False, error=f"{type(e).__name__}: {str(e)}")


class DeleteDataContractTool(BaseTool):
    """Delete a data contract by ID."""
    
    name = "delete_data_contract"
    category = "data_contracts"
    description = "Delete a data contract by its ID. This action cannot be undone."
    parameters = {
        "contract_id": {
            "type": "string",
            "description": "ID of the data contract to delete"
        }
    }
    required_params = ["contract_id"]
    required_scope = "contracts:write"
    
    async def execute(self, ctx: ToolContext, contract_id: str) -> ToolResult:
        """Delete a data contract."""
        logger.info(f"[delete_data_contract] Starting - contract_id={contract_id}")
        
        if not ctx.data_contracts_manager:
            logger.error(f"[delete_data_contract] FAILED: Data contracts manager not available")
            return ToolResult(success=False, error="Data contracts manager not available")
        
        try:
            # DB-backed delete: the legacy in-memory manager.delete_contract() never touches
            # Postgres, so use the repo + manager delete-with-logging the REST path uses (#918).
            from src.repositories.data_contracts_repository import data_contract_repo

            db_obj = data_contract_repo.get_with_all(ctx.db, id=contract_id)
            if not db_obj:
                return ToolResult(
                    success=False,
                    error=f"Data contract '{contract_id}' not found"
                )
            contract_name = db_obj.name

            ctx.data_contracts_manager.delete_contract_from_db(
                db=ctx.db,
                contract_id=contract_id,
                current_user=None,
            )
            ctx.db.commit()

            logger.info(f"[delete_data_contract] SUCCESS: Deleted contract {contract_name}")
            return ToolResult(
                success=True,
                data={
                    "success": True,
                    "contract_id": contract_id,
                    "name": contract_name,
                    "message": f"Data contract '{contract_name}' deleted successfully."
                }
            )
            
        except Exception as e:
            logger.error(f"[delete_data_contract] FAILED: {type(e).__name__}: {e}", exc_info=True)
            return ToolResult(success=False, error=f"{type(e).__name__}: {str(e)}")

