"""
Data Products tools for LLM.

Tools for searching, creating, updating, and deleting data products.
"""

import json
import uuid
from typing import Any, Dict, List, Optional

from src.common.logging import get_logger
from src.controller import search_scoring
from src.tools.base import BaseTool, ToolContext, ToolResult
# search_scoring is no longer imported here — search tools delegate to
# SearchManager.query_index() so the active backend (memory or postgres) is used.


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

    return {
        "id": product.id,
        "name": product.name,
        "domain": product.domain,
        "description": desc_purpose,
        "status": product.status,
        "version": product.version,
        "owner_team_id": getattr(product, 'owner_team_id', None),
        "owner_team_name": getattr(product, 'owner_team_name', None),
        "output_ports": output_ports,
        "tenant": getattr(product, 'tenant', None),
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
        "includes 'total_count', 'has_more' and 'facets' so you can refine rather than "
        "fetch everything. Call get_data_product for full details (output tables, ports)."
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
        }
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
    ) -> ToolResult:
        """Search data products over the shared in-memory index."""
        logger.info(
            f"[search_data_products] Starting - query='{query}', domain={domain}, "
            f"status={status}, limit={limit}, offset={offset}"
        )

        if not ctx.search_manager:
            logger.warning("[search_data_products] FAILED: search_manager is None")
            return ToolResult(success=False, error="Search not available", data={"products": []})

        try:
            data = ctx.search_manager.query_index(
                query,
                type_filter="data-product",
                # 'domains' = full assigned-domain set, so the filter matches ANY
                # assigned domain exactly (not just the primary).
                filters={"domains": domain, "status": status},
                limit=limit,
                offset=offset,
            )
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
            logger.error(f"[search_data_products] FAILED: {e.__class__.__name__}: {e}", exc_info=True)
            return ToolResult(
                success=False,
                error=f"{e.__class__.__name__}: {str(e)}",
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
            logger.error(f"[create_draft_data_product] FAILED: {type(e).__name__}: {e}", exc_info=True)
            return ToolResult(success=False, error=f"{type(e).__name__}: {str(e)}")


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
            "description": "New status (draft, active, deprecated)",
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
            if status is not None:
                update_data["status"] = status
            
            if not update_data:
                return ToolResult(
                    success=False,
                    error="No fields to update. Provide at least one of: domain, description, status"
                )
            
            # Update the product
            updated = ctx.data_products_manager.update_product(
                product_id=product_id,
                product_data_dict=update_data,
                db=ctx.db
            )
            
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
            logger.error(f"[update_data_product] FAILED: {type(e).__name__}: {e}", exc_info=True)
            return ToolResult(success=False, error=f"{type(e).__name__}: {str(e)}")


class GetDataProductTool(BaseTool):
    """Get a data product by ID."""
    
    name = "get_data_product"
    category = "data_products"
    description = "Get detailed information about a specific data product by its ID."
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
            logger.error(f"[get_data_product] FAILED: {type(e).__name__}: {e}", exc_info=True)
            return ToolResult(success=False, error=f"{type(e).__name__}: {str(e)}")


class GetDataProductsBulkTool(BaseTool):
    """Fetch full details for several data products by ID in one call."""

    name = "get_data_products"
    category = "data_products"
    description = (
        "Fetch full details for MULTIPLE data products by ID in a single call "
        "(including output ports / physical table locations). Prefer this over "
        "repeated get_data_product when you already hold a set of ids. Returns up "
        "to 20 by default; raise 'limit' up to 100. Ids beyond the limit are not "
        "fetched and reported via 'truncated'/'requested' so you can page."
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
            logger.error(f"[get_data_products] FAILED: {type(e).__name__}: {e}", exc_info=True)
            return ToolResult(success=False, error=f"{type(e).__name__}: {str(e)}")


class ListDataProductsTool(BaseTool):
    """List all data products with optional filters."""
    
    name = "list_data_products"
    category = "data_products"
    description = "List all data products with optional filtering by domain, status, or limit."
    parameters = {
        "domain": {
            "type": "string",
            "description": "Optional filter by domain"
        },
        "status": {
            "type": "string",
            "enum": ["active", "draft", "deprecated", "retired"],
            "description": "Optional filter by status"
        },
        "limit": {
            "type": "integer",
            "description": "Maximum number of products to return (default: 50)"
        }
    }
    required_params = []
    required_scope = "data-products:read"
    
    async def execute(
        self,
        ctx: ToolContext,
        domain: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50
    ) -> ToolResult:
        """List all data products."""
        logger.info(f"[list_data_products] Starting - domain={domain}, status={status}, limit={limit}")
        
        if not ctx.data_products_manager:
            logger.error(f"[list_data_products] FAILED: Data products manager not available")
            return ToolResult(success=False, error="Data products manager not available")
        
        try:
            # Use list_products method with filters
            products = ctx.data_products_manager.list_products(
                skip=0,
                limit=limit,
                domain=domain,
                status=status
            )
            
            result_list = []
            for p in products:
                desc_purpose = None
                if p.description:
                    if isinstance(p.description, dict):
                        desc_purpose = p.description.get('purpose')
                    elif isinstance(p.description, str):
                        try:
                            desc_dict = json.loads(p.description)
                            if isinstance(desc_dict, dict):
                                desc_purpose = desc_dict.get('purpose')
                        except Exception:
                            pass
                
                result_list.append({
                    "id": p.id,
                    "name": p.name,
                    "domain": p.domain,
                    "description": desc_purpose,
                    "status": p.status,
                    "version": p.version
                })
            
            logger.info(f"[list_data_products] SUCCESS: Found {len(result_list)} products")
            return ToolResult(
                success=True,
                data={
                    "products": result_list,
                    "total_found": len(result_list)
                }
            )
            
        except Exception as e:
            logger.error(f"[list_data_products] FAILED: {type(e).__name__}: {e}", exc_info=True)
            return ToolResult(success=False, error=f"{type(e).__name__}: {str(e)}")


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
            logger.error(f"[delete_data_product] FAILED: {type(e).__name__}: {e}", exc_info=True)
            return ToolResult(success=False, error=f"{type(e).__name__}: {str(e)}")

