"""
Data Contracts tools for LLM.

Tools for searching, creating, updating, and deleting data contracts.
"""

import json
from typing import Any, Dict, List, Optional

from src.common.logging import get_logger
from src.tools.base import BaseTool, ToolContext, ToolResult

logger = get_logger(__name__)


def _original_id_from_props(custom_properties) -> Optional[str]:
    """Return the preserved YAML id (``ontosOriginalId``) from a contract's
    customProperties. Contracts expose customProperties as a dict (not a list
    of CustomProperty like products), so this is a direct lookup."""
    if not custom_properties:
        return None
    if isinstance(custom_properties, dict):
        value = custom_properties.get('ontosOriginalId')
        return value if value else None
    # Defensive: fall back to the list-of-objects shape used elsewhere.
    for prop in custom_properties:
        name = getattr(prop, 'property', None) if not isinstance(prop, dict) else prop.get('property')
        if name == 'ontosOriginalId':
            value = getattr(prop, 'value', None) if not isinstance(prop, dict) else prop.get('value')
            return value if value else None
    return None


def _serialize_contract(contract) -> Dict[str, Any]:
    """Full-detail dict for a single data contract.

    Shared by get_data_contract and the bulk get_data_contracts so both return
    the identical shape.
    """
    desc = getattr(contract, 'description', None)
    desc_purpose = getattr(desc, 'purpose', None) if desc is not None else None

    # ODCS team: a flat List[TeamMember] on DataContractRead (not wrapped in a
    # Team object like products). Project username/name/role so an agent can
    # answer ownership questions. dateIn/dateOut/replacedByUsername omitted.
    team = []
    for member in (getattr(contract, 'team', None) or []):
        if member is None:
            continue
        team.append({
            "username": getattr(member, 'username', None),
            "name": getattr(member, 'name', None),
            "role": getattr(member, 'role', None),
        })

    return {
        "id": contract.id,
        "name": contract.name,
        "domain": getattr(contract, 'domain', None),
        "description": desc_purpose,
        "status": contract.status,
        "version": contract.version,
        "owner_team_name": getattr(contract, 'owner_team_name', None),
        "team": team,
        "data_product": getattr(contract, 'dataProduct', None),
        # Preserved original id when adopt_ids=false (or the YAML id was invalid /
        # colliding) — enables upstream-reference reconciliation.
        "original_id": _original_id_from_props(getattr(contract, 'customProperties', None)),
        # Lifecycle timestamps — DataContractRead stores these as pre-serialized
        # ISO strings (unlike products which hold datetime objects).
        "created_at": getattr(contract, 'created', None),
        "updated_at": getattr(contract, 'updated', None),
        "published_at": getattr(contract, 'published_at', None),
        "url": f"/data-contracts/{contract.id}",
    }


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
        "'has_more' and (by default) 'facets' so you can refine rather than fetch "
        "everything. Set include_facets=false to skip the facet block on cheap list "
        "calls, or fields=['title','status'] to narrow each row."
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
        },
        "include_facets": {
            "type": "boolean",
            "description": "Include the global facets block (domain/status/owner/tags counts). "
                           "Default true. Set false on cheap list calls to save tokens.",
        },
        "fields": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Optional allowlist of result-row keys to keep (e.g. ['title','status']). "
                           "'id' is always included. Shrinks payload for 'then fetch details' flows.",
        },
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
        include_facets: bool = True,
        fields: Optional[List[str]] = None,
    ) -> ToolResult:
        """Search data contracts over the shared in-memory index."""
        logger.info(
            f"[search_data_contracts] Starting - query='{query}', domain={domain}, "
            f"status={status}, limit={limit}, offset={offset}, "
            f"include_facets={include_facets}, fields={fields}"
        )

        if not ctx.search_manager:
            logger.warning("[search_data_contracts] FAILED: search_manager is None")
            return ToolResult(success=False, error="Search not available", data={"contracts": []})

        # Reject unknown `fields` names loudly instead of silently dropping them
        # (otherwise `fields=['name']` returns just `{id}` without hint — #954
        # reviewer note). The row key is `title`, not `name`.
        from src.controller.search_scoring import KNOWN_RESULT_FIELDS
        if fields:
            unknown = [f for f in fields if f not in KNOWN_RESULT_FIELDS]
            if unknown:
                return ToolResult(
                    success=False,
                    error=(
                        f"unknown fields: {sorted(unknown)}. "
                        f"known: {sorted(KNOWN_RESULT_FIELDS)}"
                    ),
                    data={"contracts": []},
                )

        try:
            data = ctx.search_manager.query_index(
                query,
                type_filter="data-contract",
                filters={"domain": domain, "status": status},
                limit=limit,
                offset=offset,
                include_facets=include_facets,
                fields=fields,
            )
            # Tool name already carries the type; `link` is a UI-only route path.
            # Neither helps an MCP agent, so drop them from every record.
            for r in data["results"]:
                r.pop("type", None)
                r.pop("link", None)
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
    description = (
        "Get detailed information about a specific data contract by its ID. "
        "Includes the ODCS team members with their roles so you can answer "
        "ownership / data-steward questions, lifecycle timestamps (created / "
        "updated / published), and the preserved original id from the source "
        "YAML when adoption was off."
    )
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

            logger.info(f"[get_data_contract] SUCCESS: Found contract {contract.name}")
            return ToolResult(success=True, data=_serialize_contract(contract))

        except Exception as e:
            logger.error(f"[get_data_contract] FAILED: {type(e).__name__}: {e}", exc_info=True)
            return ToolResult(success=False, error=f"{type(e).__name__}: {str(e)}")


class GetDataContractsBulkTool(BaseTool):
    """Fetch full details for several data contracts by ID in one call."""

    name = "get_data_contracts"
    category = "data_contracts"
    description = (
        "Fetch full details for MULTIPLE data contracts by ID in a single call "
        "(including the ODCS team members with their roles, lifecycle timestamps, "
        "and the preserved original id from the source YAML). Prefer this over "
        "repeated get_data_contract when you already hold a set of ids. Returns "
        "up to 20 by default; raise 'limit' up to 100. Ids beyond the limit are "
        "not fetched and reported via 'truncated'/'requested' so you can page."
    )
    parameters = {
        "contract_ids": {
            "type": "array",
            "items": {"type": "string"},
            "description": "IDs of the data contracts to retrieve.",
        },
        "limit": {
            "type": "integer",
            "description": "Max contracts to return (default: 20, server max: 100).",
        },
    }
    required_params = ["contract_ids"]
    required_scope = "contracts:read"

    DEFAULT_LIMIT = 20
    MAX_LIMIT = 100

    async def execute(
        self,
        ctx: ToolContext,
        contract_ids: List[str],
        limit: int = DEFAULT_LIMIT,
    ) -> ToolResult:
        """Bulk-get data contracts by id, capped by a server-enforced maximum."""
        if not ctx.data_contracts_manager:
            return ToolResult(success=False, error="Data contracts manager not available")

        from src.repositories.data_contracts_repository import data_contract_repo

        # Server safeguard: clamp the batch size regardless of what the caller asks.
        effective_limit = max(1, min(int(limit or self.DEFAULT_LIMIT), self.MAX_LIMIT))
        # De-duplicate while preserving order.
        unique_ids = list(dict.fromkeys(contract_ids or []))
        requested = len(unique_ids)
        ids = unique_ids[:effective_limit]
        logger.info(
            f"[get_data_contracts] Starting - requested={requested}, "
            f"limit={effective_limit}, fetching={len(ids)}"
        )

        contracts: List[Dict[str, Any]] = []
        not_found: List[str] = []
        try:
            for cid in ids:
                db_obj = data_contract_repo.get_with_all(ctx.db, id=cid)
                if db_obj:
                    contract = ctx.data_contracts_manager._build_contract_api_model(ctx.db, db_obj)
                    contracts.append(_serialize_contract(contract))
                else:
                    not_found.append(cid)

            logger.info(
                f"[get_data_contracts] SUCCESS: {len(contracts)} found, "
                f"{len(not_found)} not found"
            )
            return ToolResult(
                success=True,
                data={
                    "contracts": contracts,
                    "not_found": not_found,
                    "returned": len(contracts),
                    "requested": requested,
                    "limit": effective_limit,
                    "truncated": requested > effective_limit,
                },
            )
        except Exception as e:
            logger.error(f"[get_data_contracts] FAILED: {type(e).__name__}: {e}", exc_info=True)
            return ToolResult(success=False, error=f"{type(e).__name__}: {str(e)}")


class ListDataContractsTool(BaseTool):
    """List all data contracts — thin wrapper over search_data_contracts."""

    name = "list_data_contracts"
    category = "data_contracts"
    description = (
        "List all data contracts, optionally filtered by domain or status. This is a "
        "thin wrapper over search_data_contracts with query='*'; prefer search_data_contracts "
        "directly when you need relevance ranking, pagination offsets, facets, or a free-text "
        "query. The response shape matches search_data_contracts (contracts / total_found / "
        "has_more / offset / limit / facets)."
    )
    parameters = {
        "domain": {
            "type": "string",
            "description": "Optional filter by domain",
        },
        "status": {
            "type": "string",
            "enum": ["draft", "active", "deprecated"],
            "description": "Optional filter by status",
        },
        "limit": {
            "type": "integer",
            "description": "Maximum number of contracts to return (default: 50, max: 100)",
        },
    }
    required_params = []
    required_scope = "contracts:read"

    async def execute(
        self,
        ctx: ToolContext,
        domain: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> ToolResult:
        """Delegate to search_data_contracts with query='*' so list / search / get
        collapse to a single implementation. The previous version returned a
        thin {contracts, total_found} shape with no facets or pagination
        metadata, forcing agents to switch tools to refine. Now the response
        matches search_data_contracts exactly."""
        return await SearchDataContractsTool().execute(
            ctx,
            query="*",
            domain=domain,
            status=status,
            limit=limit,
            offset=0,
        )


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

