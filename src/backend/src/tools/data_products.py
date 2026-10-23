"""
Data Products tools for LLM.

Tools for searching, creating, updating, and deleting data products.
"""

import json
import uuid
from typing import Any, Dict, List, Optional

from src.common.logging import get_logger
from src.controller import search_scoring
from src.tools.base import BaseTool, ToolContext, ToolResult, tool_failure
# search_scoring is no longer imported here — search tools delegate to
# SearchManager.query_index() so the active backend (memory or postgres) is used.


def _iso_or_none(dt) -> Optional[str]:
    """ISO-serialize a datetime/date; None stays None."""
    return dt.isoformat() if dt is not None else None


def _original_id_from_props(custom_properties) -> Optional[str]:
    """Return the preserved YAML id (``ontosOriginalId``) from a product's
    customProperties, if present. Lets an agent reconcile the Ontos UUID with
    an upstream reference without a second call."""
    if not custom_properties:
        return None
    for prop in custom_properties:
        name = getattr(prop, 'property', None) if not isinstance(prop, dict) else prop.get('property')
        if name == 'ontosOriginalId':
            value = getattr(prop, 'value', None) if not isinstance(prop, dict) else prop.get('value')
            return value if value is not None else None
    return None


def _serialize_product(product) -> Dict[str, Any]:
    """Full-detail dict for a single data product.

    Shared by get_data_product and the bulk get_data_products so both return the
    identical shape (including output ports with physical table locations).
    """
    # Extract description purpose (handles Description model, dict, or str)
    desc_purpose = None
    if product.description:
        if hasattr(product.description, 'purpose'):
            desc_purpose = product.description.purpose
        elif isinstance(product.description, dict):
            desc_purpose = product.description.get('purpose')
        elif isinstance(product.description, str):
            try:
                desc_dict = json.loads(product.description)
                if isinstance(desc_dict, dict):
                    desc_purpose = desc_dict.get('purpose')
            except Exception:
                desc_purpose = product.description

    # Surface output ports so agents can find the physical tables
    output_ports = []
    for port in (product.outputPorts or []):
        server = getattr(port, 'server', None)
        location = getattr(port, 'assetIdentifier', None)
        if not location and server is not None:
            host = getattr(server, 'host', '') or ''
            schema = getattr(server, 'schema_name', '') or ''
            location = f"{host}.{schema}" if host and schema else (host or None)
        output_ports.append({
            "name": port.name,
            "description": getattr(port, 'description', None),
            "contract_id": getattr(port, 'contractId', None),
            "contract_name": getattr(port, 'contractName', None),
            "location": location,
        })

    # Imported ODPS team: name + members with their role, so an agent can answer
    # "who is the owner / data steward" questions. dateIn/dateOut/replacedByUsername
    # omitted — not useful for ownership answers and inflates the payload.
    team = None
    product_team = getattr(product, 'team', None)
    if product_team is not None:
        members = []
        for member in (getattr(product_team, 'members', None) or []):
            if member is None:
                continue
            members.append({
                "username": getattr(member, 'username', None),
                "name": getattr(member, 'name', None),
                "role": getattr(member, 'role', None),
            })
        team = {
            "name": getattr(product_team, 'name', None),
            "description": getattr(product_team, 'description', None),
            "members": members,
        }

    return {
        "id": product.id,
        "name": product.name,
        "domain": product.domain,
        "description": desc_purpose,
        "status": product.status,
        "version": product.version,
        "owner_team_id": getattr(product, 'owner_team_id', None),
        "owner_team_name": getattr(product, 'owner_team_name', None),
        "team": team,
        "output_ports": output_ports,
        "tenant": getattr(product, 'tenant', None),
        # Preserved original id when adopt_ids=false (or the YAML id was invalid /
        # colliding) — enables upstream-reference reconciliation.
        "original_id": _original_id_from_props(getattr(product, 'customProperties', None)),
        # Lifecycle timestamps — agents frequently want "when was this registered /
        # last updated / published" alongside the ownership info.
        "created_at": _iso_or_none(getattr(product, 'created_at', None)),
        "updated_at": _iso_or_none(getattr(product, 'updated_at', None)),
        "published_at": _iso_or_none(getattr(product, 'published_at', None)),
        "product_created_ts": _iso_or_none(getattr(product, 'productCreatedTs', None)),
        "url": f"/data-products/{product.id}",
    }

logger = get_logger(__name__)


class SearchDataProductsTool(BaseTool):
    """Search for data products via the shared, tokenized search index."""

    name = "search_data_products"
    category = "data_products"
    description = (
        "Search data products by name, domain, description, tags or linked ontology "
        "concepts. Use FEW BROAD terms, not full sentences — each term is matched "
        "independently and results are ranked by relevance. Narrow with the 'domain'/"
        "'status' filters and page with 'offset' instead of broadening the query. Leave "
        "'query' empty (or '*') to list products; the response is always paginated and "
        "includes 'total_count', 'has_more' and (by default) 'facets' so you can refine "
        "rather than fetch everything. Set include_facets=false to skip the facet block "
        "on cheap list calls, or fields=['title','status'] to narrow each row. Call "
        "get_data_product for full details (output tables, ports)."
    )
    parameters = {
        "query": {
            "type": "string",
            "description": "Search terms (e.g., 'customer', 'sales'). Empty or '*' lists all products."
        },
        "domain": {
            "type": "string",
            "description": "Optional filter by domain (e.g., 'Customer', 'Sales', 'Finance')."
        },
        "status": {
            "type": "string",
            "enum": ["active", "draft", "deprecated", "retired"],
            "description": "Optional filter by product status."
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
    required_scope = "data-products:read"

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
        """Search data products over the shared in-memory index."""
        logger.info(
            f"[search_data_products] Starting - query='{query}', domain={domain}, "
            f"status={status}, limit={limit}, offset={offset}, "
            f"include_facets={include_facets}, fields={fields}"
        )

        if not ctx.search_manager:
            logger.warning("[search_data_products] FAILED: search_manager is None")
            return ToolResult(success=False, error="Search not available", data={"products": []})

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
                    data={"products": []},
                )

        try:
            data = ctx.search_manager.query_index(
                query,
                type_filter="data-product",
                # 'domains' = full assigned-domain set, so the filter matches ANY
                # assigned domain exactly (not just the primary).
                filters={"domains": domain, "status": status},
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
            # Present under the historical 'products'/'total_found' keys for compatibility.
            logger.info(
                f"[search_data_products] SUCCESS: returned {data['returned']} of "
                f"{data['total_count']} matching products"
            )
            return ToolResult(
                success=True,
                data={
                    "products": data["results"],
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
            return ToolResult(
                success=False,
                **tool_failure("search_data_products", e),
                data={"products": []},
            )


class CreateDraftDataProductTool(BaseTool):
    """Create a new draft data product."""
    
    name = "create_draft_data_product"
    category = "data_products"
    description = "Create a new draft data product. The product will be created in 'draft' status for user review. Optionally link to an existing data contract."
    parameters = {
        "name": {
            "type": "string",
            "description": "Name for the data product (e.g., 'Customer Analytics Product')"
        },
        "description": {
            "type": "string",
            "description": "Business description and purpose of the data product"
        },
        "domain": {
            "type": "string",
            "description": "Business domain (e.g., 'Customer', 'Sales', 'Finance')"
        },
        "contract_id": {
            "type": "string",
            "description": "Optional: ID of an existing data contract to link to this product"
        },
        "output_tables": {
            "type": "array",
            "description": "List of output table FQNs this product provides",
            "items": {"type": "string"}
        }
    }
    required_params = ["name", "description", "domain"]
    required_scope = "data-products:write"
    
    async def execute(
        self,
        ctx: ToolContext,
        name: str,
        description: str,
        domain: str,
        contract_id: Optional[str] = None,
        output_tables: Optional[List[str]] = None
    ) -> ToolResult:
        """Create a draft data product."""
        logger.info(f"[create_draft_data_product] Starting - name='{name}', domain={domain}, contract_id={contract_id}")
        
        if not ctx.data_products_manager:
            logger.error(f"[create_draft_data_product] FAILED: Data products manager not available")
            return ToolResult(success=False, error="Data products manager not available")
        
        try:
            logger.info(f"Creating draft data product: {name}")
            
            # Build output ports from tables
            output_ports = []
            if output_tables:
                for i, table_fqn in enumerate(output_tables):
                    output_ports.append({
                        "name": f"output_{i + 1}",
                        "server": table_fqn,
                        "description": f"Output table: {table_fqn}"
                    })
            
            # If contract_id provided, link it
            if contract_id and output_ports:
                output_ports[0]["dataContractId"] = contract_id
            
            # Build product data in ODPS format
            product_data = {
                "apiVersion": "v1.0.0",
                "kind": "DataProduct",
                "id": str(uuid.uuid4()),
                "name": name,
                "version": "0.1.0",
                "status": "draft",
                "domain": domain,
                "description": {
                    "purpose": description
                },
                "outputPorts": output_ports
            }
            
            # Create the product
            created = ctx.data_products_manager.create_product(
                product_data=product_data,
                db=ctx.db
            )
            
            logger.info(f"[create_draft_data_product] SUCCESS: Created product id={created.id}, name={created.name}")
            return ToolResult(
                success=True,
                data={
                    "success": True,
                    "product_id": created.id,
                    "name": created.name,
                    "version": created.version,
                    "status": created.status,
                    "message": f"Draft product '{name}' created successfully. Review and publish it in the Data Products UI.",
                    "url": f"/data-products/{created.id}"
                }
            )
            
        except Exception as e:
            return ToolResult(success=False, **tool_failure("create_draft_data_product", e))


class UpdateDataProductTool(BaseTool):
    """Update an existing data product's properties."""
    
    name = "update_data_product"
    category = "data_products"
    description = "Update an existing data product's properties like domain, description, or status."
    parameters = {
        "product_id": {
            "type": "string",
            "description": "ID of the data product to update"
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
            "description": (
                "New status (draft, active, deprecated). Applied as a lifecycle transition: "
                "only an allowed transition, and status change workflows can block it."
            ),
            "enum": ["draft", "active", "deprecated"]
        }
    }
    required_params = ["product_id"]
    required_scope = "data-products:write"
    
    async def execute(
        self,
        ctx: ToolContext,
        product_id: str,
        domain: Optional[str] = None,
        description: Optional[str] = None,
        status: Optional[str] = None
    ) -> ToolResult:
        """Update an existing data product."""
        logger.info(f"[update_data_product] Starting - product_id={product_id}, domain={domain}, status={status}")
        
        if not ctx.data_products_manager:
            logger.error(f"[update_data_product] FAILED: Data products manager not available")
            return ToolResult(success=False, error="Data products manager not available")
        
        try:
            # Build update data
            update_data: Dict[str, Any] = {}
            if domain is not None:
                update_data["domain"] = domain
            if description is not None:
                update_data["description"] = {"purpose": description}
            
            if not update_data and status is None:
                return ToolResult(
                    success=False,
                    error="No fields to update. Provide at least one of: domain, description, status"
                )

            # A status change goes through the lifecycle transition (allowed
            # transitions, before_status_change gates), like the change-status
            # route; an update can't change it.
            if status is not None:
                current = ctx.data_products_manager.get_product(product_id)
                if not current:
                    return ToolResult(
                        success=False,
                        error=f"Data product '{product_id}' not found"
                    )
                current_status = getattr(current.status, 'value', current.status) or 'draft'
                if str(current_status).lower() != status.lower():
                    ctx.data_products_manager.transition_status(product_id, status)

            # Update the product
            if update_data:
                updated = ctx.data_products_manager.update_product(
                    product_id=product_id,
                    product_data_dict=update_data,
                    db=ctx.db
                )
            else:
                updated = ctx.data_products_manager.get_product(product_id)
            
            if not updated:
                return ToolResult(
                    success=False,
                    error=f"Data product '{product_id}' not found"
                )
            
            logger.info(f"[update_data_product] SUCCESS: Updated product id={updated.id}")
            return ToolResult(
                success=True,
                data={
                    "success": True,
                    "product_id": updated.id,
                    "name": updated.name,
                    "domain": updated.domain,
                    "status": updated.status,
                    "message": f"Product '{updated.name}' updated successfully.",
                    "url": f"/data-products/{updated.id}"
                }
            )
            
        except Exception as e:
            return ToolResult(success=False, **tool_failure("update_data_product", e))


class GetDataProductTool(BaseTool):
    """Get a data product by ID."""
    
    name = "get_data_product"
    category = "data_products"
    description = (
        "Get detailed information about a specific data product by its ID. "
        "Includes the imported ODPS team metadata (members with roles) so you "
        "can answer ownership questions, lifecycle timestamps (created / "
        "updated / published / product_created_ts), and the preserved original "
        "id from the source YAML when adoption was off."
    )
    parameters = {
        "product_id": {
            "type": "string",
            "description": "ID of the data product to retrieve"
        }
    }
    required_params = ["product_id"]
    required_scope = "data-products:read"
    
    async def execute(self, ctx: ToolContext, product_id: str) -> ToolResult:
        """Get a data product by ID."""
        logger.info(f"[get_data_product] Starting - product_id={product_id}")
        
        if not ctx.data_products_manager:
            logger.error(f"[get_data_product] FAILED: Data products manager not available")
            return ToolResult(success=False, error="Data products manager not available")
        
        try:
            product = ctx.data_products_manager.get_product(product_id)

            if not product:
                return ToolResult(
                    success=False,
                    error=f"Data product '{product_id}' not found"
                )

            logger.info(f"[get_data_product] SUCCESS: Found product {product.name}")
            return ToolResult(success=True, data=_serialize_product(product))

        except Exception as e:
            return ToolResult(success=False, **tool_failure("get_data_product", e))


class GetDataProductsBulkTool(BaseTool):
    """Fetch full details for several data products by ID in one call."""

    name = "get_data_products"
    category = "data_products"
    description = (
        "Fetch full details for MULTIPLE data products by ID in a single call "
        "(including output ports / physical table locations, imported ODPS team "
        "members with roles, lifecycle timestamps, and the preserved original "
        "id from the source YAML). Prefer this over repeated get_data_product "
        "when you already hold a set of ids. Returns up to 20 by default; raise "
        "'limit' up to 100. Ids beyond the limit are not fetched and reported "
        "via 'truncated'/'requested' so you can page."
    )
    parameters = {
        "product_ids": {
            "type": "array",
            "items": {"type": "string"},
            "description": "IDs of the data products to retrieve.",
        },
        "limit": {
            "type": "integer",
            "description": "Max products to return (default: 20, server max: 100).",
        },
    }
    required_params = ["product_ids"]
    required_scope = "data-products:read"

    DEFAULT_LIMIT = 20
    MAX_LIMIT = 100

    async def execute(
        self,
        ctx: ToolContext,
        product_ids: List[str],
        limit: int = DEFAULT_LIMIT,
    ) -> ToolResult:
        """Bulk-get data products by id, capped by a server-enforced maximum."""
        if not ctx.data_products_manager:
            return ToolResult(success=False, error="Data products manager not available")

        # Server safeguard: clamp the batch size regardless of what the caller asks.
        effective_limit = max(1, min(int(limit or self.DEFAULT_LIMIT), self.MAX_LIMIT))
        # De-duplicate while preserving order.
        unique_ids = list(dict.fromkeys(product_ids or []))
        requested = len(unique_ids)
        ids = unique_ids[:effective_limit]
        logger.info(
            f"[get_data_products] Starting - requested={requested}, "
            f"limit={effective_limit}, fetching={len(ids)}"
        )

        products: List[Dict[str, Any]] = []
        not_found: List[str] = []
        try:
            for pid in ids:
                product = ctx.data_products_manager.get_product(pid)
                if product:
                    products.append(_serialize_product(product))
                else:
                    not_found.append(pid)

            logger.info(
                f"[get_data_products] SUCCESS: {len(products)} found, "
                f"{len(not_found)} not found"
            )
            return ToolResult(
                success=True,
                data={
                    "products": products,
                    "not_found": not_found,
                    "returned": len(products),
                    "requested": requested,
                    "limit": effective_limit,
                    "truncated": requested > effective_limit,
                },
            )
        except Exception as e:
            return ToolResult(success=False, **tool_failure("get_data_products", e))


class ListDataProductsTool(BaseTool):
    """List all data products — thin wrapper over search_data_products."""

    name = "list_data_products"
    category = "data_products"
    description = (
        "List all data products, optionally filtered by domain or status. This is a "
        "thin wrapper over search_data_products with query='*'; prefer search_data_products "
        "directly when you need relevance ranking, pagination offsets, facets, or a free-text "
        "query. The response shape matches search_data_products (products / total_found / "
        "has_more / offset / limit / facets)."
    )
    parameters = {
        "domain": {
            "type": "string",
            "description": "Optional filter by domain",
        },
        "status": {
            "type": "string",
            "enum": ["active", "draft", "deprecated", "retired"],
            "description": "Optional filter by status",
        },
        "limit": {
            "type": "integer",
            "description": "Maximum number of products to return (default: 50, max: 100)",
        },
    }
    required_params = []
    required_scope = "data-products:read"

    async def execute(
        self,
        ctx: ToolContext,
        domain: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> ToolResult:
        """Delegate to search_data_products with query='*' so the three overlapping
        entry points (search / list / get) collapse to a single implementation.
        Previously this called `data_products_manager.list_products(domain=..., status=...)`
        with kwargs the manager didn't accept — every call raised TypeError and
        returned a generic error. Now it inherits search_data_products' response
        shape (paginated, faceted, consistent)."""
        return await SearchDataProductsTool().execute(
            ctx,
            query="*",
            domain=domain,
            status=status,
            limit=limit,
            offset=0,
        )


class DeleteDataProductTool(BaseTool):
    """Delete a data product by ID."""
    
    name = "delete_data_product"
    category = "data_products"
    description = "Delete a data product by its ID. This action cannot be undone."
    parameters = {
        "product_id": {
            "type": "string",
            "description": "ID of the data product to delete"
        }
    }
    required_params = ["product_id"]
    required_scope = "data-products:write"
    
    async def execute(self, ctx: ToolContext, product_id: str) -> ToolResult:
        """Delete a data product."""
        logger.info(f"[delete_data_product] Starting - product_id={product_id}")
        
        if not ctx.data_products_manager:
            logger.error(f"[delete_data_product] FAILED: Data products manager not available")
            return ToolResult(success=False, error="Data products manager not available")
        
        try:
            # Get product name first for the response
            product = ctx.data_products_manager.get_product(product_id)
            if not product:
                return ToolResult(
                    success=False,
                    error=f"Data product '{product_id}' not found"
                )
            
            product_name = product.name
            
            # Delete the product
            success = ctx.data_products_manager.delete_product(product_id)
            
            if not success:
                return ToolResult(
                    success=False,
                    error=f"Failed to delete data product '{product_id}'"
                )
            
            logger.info(f"[delete_data_product] SUCCESS: Deleted product {product_name}")
            return ToolResult(
                success=True,
                data={
                    "success": True,
                    "product_id": product_id,
                    "name": product_name,
                    "message": f"Data product '{product_name}' deleted successfully."
                }
            )
            
        except Exception as e:
            return ToolResult(success=False, **tool_failure("delete_data_product", e))

