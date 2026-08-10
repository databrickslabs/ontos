"""
Data Contracts tools for LLM.

Tools for searching, creating, updating, and deleting data contracts.
"""

import json
from typing import Any, Dict, List, Optional

from src.common.logging import get_logger
from src.tools.base import BaseTool, ToolContext, ToolResult

logger = get_logger(__name__)


class SearchDataContractsTool(BaseTool):
    """Search for data contracts by name, domain, or status."""
    
    name = "search_data_contracts"
    category = "data_contracts"
    description = "Search for data contracts by name, domain, description, or keywords. Returns matching contracts with their metadata."
    parameters = {
        "query": {
            "type": "string",
            "description": "Search query for data contracts (e.g., 'customer', 'sales data')"
        },
        "domain": {
            "type": "string",
            "description": "Optional filter by domain (e.g., 'Customer', 'Sales', 'Finance')"
        },
        "status": {
            "type": "string",
            "enum": ["active", "draft", "deprecated", "retired"],
            "description": "Optional filter by contract status"
        }
    }
    required_params = ["query"]
    required_scope = "contracts:read"
    
    async def execute(
        self,
        ctx: ToolContext,
        query: str,
        domain: Optional[str] = None,
        status: Optional[str] = None
    ) -> ToolResult:
        """Search for data contracts."""
        logger.info(f"[search_data_contracts] Starting - query='{query}', domain={domain}, status={status}")
        
        try:
            from src.db_models.data_contracts import DataContractDb
            from src.repositories.entity_domain_association_repository import entity_domain_repo

            contracts_db = ctx.db.query(DataContractDb).limit(500).all()
            logger.debug(f"[search_data_contracts] Found {len(contracts_db)} total contracts in database")

            if not contracts_db:
                return ToolResult(
                    success=True,
                    data={"contracts": [], "total_found": 0, "message": "No data contracts found"}
                )

            # Batch-load domain assignments (domain moved to the junction table).
            domains_map = entity_domain_repo.get_domains_for_entities(
                ctx.db, entity_type="data_contract", entity_ids=[str(c.id) for c in contracts_db]
            )
            contract_domain_names: Dict[str, List[str]] = {
                cid: [a.domain_name for a in assigned if a.domain_name]
                for cid, assigned in domains_map.items()
            }
            contract_primary_domain: Dict[str, Optional[str]] = {
                cid: next((a.domain_name for a in assigned if a.is_primary), None)
                for cid, assigned in domains_map.items()
            }

            query_lower = query.lower() if query and query != '*' else ''
            filtered = []

            for c in contracts_db:
                c_domain_names = contract_domain_names.get(str(c.id), [])
                if not query_lower:
                    include = True
                else:
                    name_match = query_lower in (c.name or "").lower()

                    desc_match = False
                    if c.description:
                        try:
                            desc_dict = json.loads(c.description) if isinstance(c.description, str) else c.description
                            if isinstance(desc_dict, dict):
                                desc_text = desc_dict.get('purpose', '')
                                desc_match = query_lower in desc_text.lower()
                            elif isinstance(desc_dict, str):
                                desc_match = query_lower in desc_dict.lower()
                        except Exception:
                            pass

                    domain_match = any(query_lower in (n or "").lower() for n in c_domain_names)
                    include = name_match or desc_match or domain_match

                if include:
                    if domain and not any(n.lower() == domain.lower() for n in c_domain_names):
                        continue
                    if status and c.status != status:
                        continue

                    desc_purpose = None
                    if c.description:
                        try:
                            desc_dict = json.loads(c.description) if isinstance(c.description, str) else c.description
                            if isinstance(desc_dict, dict):
                                desc_purpose = desc_dict.get('purpose')
                        except Exception:
                            pass

                    filtered.append({
                        "id": str(c.id),
                        "name": c.name,
                        "domain": contract_primary_domain.get(str(c.id)),
                        "description": desc_purpose,
                        "status": c.status,
                        "version": c.version
                    })
            
            logger.info(f"[search_data_contracts] SUCCESS: Found {len(filtered)} matching contracts")
            return ToolResult(
                success=True,
                data={
                    "contracts": filtered[:20],
                    "total_found": len(filtered)
                }
            )
            
        except Exception as e:
            logger.error(f"[search_data_contracts] FAILED: {type(e).__name__}: {e}", exc_info=True)
            return ToolResult(success=False, error=f"{type(e).__name__}: {str(e)}", data={"contracts": []})


class GetDataContractTool(BaseTool):
    """Get a single data contract by ID."""
    
    name = "get_data_contract"
    category = "data_contracts"
    description = "Get detailed information about a specific data contract by its ID."
    parameters = {
        "contract_id": {
            "type": "string",
            "description": "The ID of the data contract to retrieve"
        }
    }
    required_params = ["contract_id"]
    required_scope = "contracts:read"
    
    async def execute(
        self,
        ctx: ToolContext,
        contract_id: str
    ) -> ToolResult:
        """Get a data contract by ID."""
        logger.info(f"[get_data_contract] Starting - contract_id={contract_id}")
        
        try:
            from src.db_models.data_contracts import DataContractDb
            from src.repositories.entity_domain_association_repository import entity_domain_repo

            contract = ctx.db.query(DataContractDb).filter(DataContractDb.id == contract_id).first()

            if not contract:
                return ToolResult(
                    success=False,
                    error=f"Data contract '{contract_id}' not found"
                )

            # Domain now lives in the entity_domain_associations junction; use the primary.
            assigned = entity_domain_repo.get_domains_for_entity(
                ctx.db, entity_type="data_contract", entity_id=str(contract.id)
            )
            primary_domain = next((a.domain_name for a in assigned if a.is_primary), None)

            desc_purpose = None
            if contract.description:
                try:
                    desc_dict = json.loads(contract.description) if isinstance(contract.description, str) else contract.description
                    if isinstance(desc_dict, dict):
                        desc_purpose = desc_dict.get('purpose')
                except Exception:
                    pass

            logger.info(f"[get_data_contract] SUCCESS: Found contract {contract_id}")
            return ToolResult(
                success=True,
                data={
                    "id": str(contract.id),
                    "name": contract.name,
                    "domain": primary_domain,
                    "description": desc_purpose,
                    "status": contract.status,
                    "version": contract.version,
                    "created_at": contract.created_at.isoformat() if contract.created_at else None,
                    "updated_at": contract.updated_at.isoformat() if contract.updated_at else None
                }
            )
            
        except Exception as e:
            logger.error(f"[get_data_contract] FAILED: {type(e).__name__}: {e}", exc_info=True)
            return ToolResult(success=False, error=f"{type(e).__name__}: {str(e)}")


class DeleteDataContractTool(BaseTool):
    """Delete a data contract."""
    
    name = "delete_data_contract"
    category = "data_contracts"
    description = "Delete a data contract by its ID. This action cannot be undone."
    parameters = {
        "contract_id": {
            "type": "string",
            "description": "The ID of the data contract to delete"
        }
    }
    required_params = ["contract_id"]
    required_scope = "contracts:write"
    
    async def execute(
        self,
        ctx: ToolContext,
        contract_id: str
    ) -> ToolResult:
        """Delete a data contract."""
        logger.info(f"[delete_data_contract] Starting - contract_id={contract_id}")
        
        if not ctx.data_contracts_manager:
            logger.error(f"[delete_data_contract] FAILED: Data contracts manager not available")
            return ToolResult(success=False, error="Data contracts manager not available")
        
        try:
            success = ctx.data_contracts_manager.delete_contract(contract_id)
            
            if not success:
                return ToolResult(
                    success=False,
                    error=f"Data contract '{contract_id}' not found or could not be deleted"
                )
            
            ctx.db.commit()
            
            logger.info(f"[delete_data_contract] SUCCESS: Deleted contract {contract_id}")
            return ToolResult(
                success=True,
                data={
                    "success": True,
                    "message": f"Data contract '{contract_id}' deleted successfully",
                    "contract_id": contract_id
                }
            )
            
        except Exception as e:
            logger.error(f"[delete_data_contract] FAILED: {type(e).__name__}: {e}", exc_info=True)
            return ToolResult(success=False, error=f"{type(e).__name__}: {str(e)}")


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
    """Search for data contracts by name, domain, or keywords."""
    
    name = "search_data_contracts"
    category = "data_contracts"
    description = "Search for data contracts by name, domain, description, or keywords."
    parameters = {
        "query": {
            "type": "string",
            "description": "Search query for data contracts"
        },
        "domain": {
            "type": "string",
            "description": "Optional filter by domain"
        },
        "status": {
            "type": "string",
            "enum": ["draft", "active", "deprecated"],
            "description": "Optional filter by status"
        }
    }
    required_params = ["query"]
    
    async def execute(
        self,
        ctx: ToolContext,
        query: str,
        domain: Optional[str] = None,
        status: Optional[str] = None
    ) -> ToolResult:
        """Search for data contracts."""
        logger.info(f"[search_data_contracts] Starting - query='{query}', domain={domain}, status={status}")
        
        if not ctx.data_contracts_manager:
            logger.error(f"[search_data_contracts] FAILED: Data contracts manager not available")
            return ToolResult(success=False, error="Data contracts manager not available")
        
        try:
            contracts = ctx.data_contracts_manager.list_contracts()
            
            query_lower = query.lower() if query and query != '*' else ''
            filtered = []
            
            for c in contracts:
                # Filter by query
                if query_lower:
                    name_match = query_lower in (c.name or "").lower()
                    domain_match = query_lower in (getattr(c, 'domain', '') or "").lower()
                    desc_match = query_lower in (c.description or "").lower() if c.description else False
                    include = name_match or domain_match or desc_match
                else:
                    include = True
                
                if not include:
                    continue
                
                # Apply filters
                if domain and getattr(c, 'domain', None) and getattr(c, 'domain', '').lower() != domain.lower():
                    continue
                if status and c.status != status:
                    continue
                
                filtered.append({
                    "id": c.id,
                    "name": c.name,
                    "domain": getattr(c, 'domain', None),
                    "status": c.status,
                    "version": c.version,
                    "format": c.format
                })
            
            logger.info(f"[search_data_contracts] SUCCESS: Found {len(filtered)} matching contracts")
            return ToolResult(
                success=True,
                data={
                    "contracts": filtered[:20],
                    "total_found": len(filtered)
                }
            )
            
        except Exception as e:
            logger.error(f"[search_data_contracts] FAILED: {type(e).__name__}: {e}", exc_info=True)
            return ToolResult(success=False, error=f"{type(e).__name__}: {str(e)}")


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
    
    async def execute(self, ctx: ToolContext, contract_id: str) -> ToolResult:
        """Get a data contract by ID."""
        logger.info(f"[get_data_contract] Starting - contract_id={contract_id}")
        
        if not ctx.data_contracts_manager:
            logger.error(f"[get_data_contract] FAILED: Data contracts manager not available")
            return ToolResult(success=False, error="Data contracts manager not available")
        
        try:
            contract = ctx.data_contracts_manager.get_contract(contract_id)
            
            if not contract:
                return ToolResult(
                    success=False,
                    error=f"Data contract '{contract_id}' not found"
                )
            
            logger.info(f"[get_data_contract] SUCCESS: Found contract {contract.name}")
            return ToolResult(
                success=True,
                data={
                    "id": contract.id,
                    "name": contract.name,
                    "domain": getattr(contract, 'domain', None),
                    "description": contract.description,
                    "status": contract.status,
                    "version": contract.version,
                    "format": contract.format,
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
            contracts = ctx.data_contracts_manager.list_contracts()
            
            filtered = []
            for c in contracts:
                if domain and getattr(c, 'domain', None) and getattr(c, 'domain', '').lower() != domain.lower():
                    continue
                if status and c.status != status:
                    continue
                
                filtered.append({
                    "id": c.id,
                    "name": c.name,
                    "domain": getattr(c, 'domain', None),
                    "status": c.status,
                    "version": c.version,
                    "format": c.format
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
    
    async def execute(self, ctx: ToolContext, contract_id: str) -> ToolResult:
        """Delete a data contract."""
        logger.info(f"[delete_data_contract] Starting - contract_id={contract_id}")
        
        if not ctx.data_contracts_manager:
            logger.error(f"[delete_data_contract] FAILED: Data contracts manager not available")
            return ToolResult(success=False, error="Data contracts manager not available")
        
        try:
            # Get contract name first
            contract = ctx.data_contracts_manager.get_contract(contract_id)
            if not contract:
                return ToolResult(
                    success=False,
                    error=f"Data contract '{contract_id}' not found"
                )
            
            contract_name = contract.name
            
            success = ctx.data_contracts_manager.delete_contract(contract_id)
            
            if not success:
                return ToolResult(
                    success=False,
                    error=f"Failed to delete data contract '{contract_id}'"
                )
            
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

