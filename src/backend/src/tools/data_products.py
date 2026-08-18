"""
Data Products tools for LLM.

Tools for searching, creating, updating, and deleting data products.
"""

import json
import uuid
from typing import Any, Dict, List, Optional

from src.common.logging import get_logger
from src.tools.base import BaseTool, ToolContext, ToolResult

logger = get_logger(__name__)


class GetDataProductTool(BaseTool):
    """Get a single data product by ID."""
    
    name = "get_data_product"
    category = "data_products"
    description = "Get detailed information about a specific data product by its ID."
    parameters = {
        "product_id": {
            "type": "string",
            "description": "The ID of the data product to retrieve"
        }
    }
    required_params = ["product_id"]
    required_scope = "data-products:read"
    
    async def execute(
        self,
        ctx: ToolContext,
        product_id: str
    ) -> ToolResult:
        """Get a data product by ID."""
        logger.info(f"[get_data_product] Starting - product_id={product_id}")
        
        try:
            from src.db_models.data_products import DataProductDb
            from src.repositories.entity_domain_association_repository import entity_domain_repo

            product = ctx.db.query(DataProductDb).filter(DataProductDb.id == product_id).first()

            if not product:
                return ToolResult(
                    success=False,
                    error=f"Data product '{product_id}' not found"
                )

            # Domain now lives in the entity_domain_associations junction; use the primary.
            assigned = entity_domain_repo.get_domains_for_entity(
                ctx.db, entity_type="data_product", entity_id=str(product.id)
            )
            primary_domain = next((a.domain_name for a in assigned if a.is_primary), None)

            # Extract description purpose from JSON
            desc_purpose = None
            if product.description:
                try:
                    desc_dict = json.loads(product.description) if isinstance(product.description, str) else product.description
                    if isinstance(desc_dict, dict):
                        desc_purpose = desc_dict.get('purpose')
                except Exception:
                    pass
            
            # Extract output tables from output_ports JSON
            output_tables = []
            if product.output_ports:
                try:
                    ports = json.loads(product.output_ports) if isinstance(product.output_ports, str) else product.output_ports
                    if isinstance(ports, list):
                        for port in ports:
                            if isinstance(port, dict):
                                output_tables.append(port.get('name', 'Unknown'))
                except Exception:
                    pass
            
            logger.info(f"[get_data_product] SUCCESS: Found product {product_id}")
            return ToolResult(
                success=True,
                data={
                    "id": str(product.id),
                    "name": product.name,
                    "domain": primary_domain,
                    "description": desc_purpose,
                    "status": product.status,
                    "version": product.version,
                    "output_tables": output_tables,
                    "created_at": product.created_at.isoformat() if product.created_at else None,
                    "updated_at": product.updated_at.isoformat() if product.updated_at else None
                }
            )
            
        except Exception as e:
            logger.error(f"[get_data_product] FAILED: {type(e).__name__}: {e}", exc_info=True)
            return ToolResult(success=False, error=f"{type(e).__name__}: {str(e)}")


class DeleteDataProductTool(BaseTool):
    """Delete a data product."""
    
    name = "delete_data_product"
    category = "data_products"
    description = "Delete a data product by its ID. This action cannot be undone."
    parameters = {
        "product_id": {
            "type": "string",
            "description": "The ID of the data product to delete"
        }
    }
    required_params = ["product_id"]
    required_scope = "data-products:write"
    
    async def execute(
        self,
        ctx: ToolContext,
        product_id: str
    ) -> ToolResult:
        """Delete a data product."""
        logger.info(f"[delete_data_product] Starting - product_id={product_id}")
        
        if not ctx.data_products_manager:
            logger.error(f"[delete_data_product] FAILED: Data products manager not available")
            return ToolResult(success=False, error="Data products manager not available")
        
        try:
            success = ctx.data_products_manager.delete_product(product_id)
            
            if not success:
                return ToolResult(
                    success=False,
                    error=f"Data product '{product_id}' not found or could not be deleted"
                )
            
            ctx.db.commit()
            
            logger.info(f"[delete_data_product] SUCCESS: Deleted product {product_id}")
            return ToolResult(
                success=True,
                data={
                    "success": True,
                    "message": f"Data product '{product_id}' deleted successfully",
                    "product_id": product_id
                }
            )
            
        except Exception as e:
            logger.error(f"[delete_data_product] FAILED: {type(e).__name__}: {e}", exc_info=True)
            return ToolResult(success=False, error=f"{type(e).__name__}: {str(e)}")


class SearchDataProductsTool(BaseTool):
    """Search for data products by name, domain, description, or keywords."""
    
    name = "search_data_products"
    category = "data_products"
    description = "Search for data products by name, domain, description, or keywords. Returns matching data products with their metadata."
    parameters = {
        "query": {
            "type": "string",
            "description": "Search query for data products (e.g., 'customer', 'sales transactions')"
        },
        "domain": {
            "type": "string",
            "description": "Optional filter by domain (e.g., 'Customer', 'Sales', 'Finance')"
        },
        "status": {
            "type": "string",
            "enum": ["active", "draft", "deprecated", "retired"],
            "description": "Optional filter by product status"
        }
    }
    required_params = ["query"]
    required_scope = "data-products:read"
    
    async def execute(
        self,
        ctx: ToolContext,
        query: str,
        domain: Optional[str] = None,
        status: Optional[str] = None
    ) -> ToolResult:
        """Search for data products."""
        logger.info(f"[search_data_products] Starting - query='{query}', domain={domain}, status={status}")
        
        try:
            # Query database directly using the session
            from src.db_models.data_products import DataProductDb
            from src.db_models.semantic_links import EntitySemanticLinkDb
            from src.repositories.entity_domain_association_repository import entity_domain_repo

            products_db = ctx.db.query(DataProductDb).limit(500).all()
            logger.debug(f"[search_data_products] Found {len(products_db)} total products in database")

            if not products_db:
                logger.info(f"[search_data_products] No products found in database")
                return ToolResult(
                    success=True,
                    data={"products": [], "total_found": 0, "message": "No data products found"}
                )

            # Batch-load domain assignments (domain moved to the junction table).
            # {product_id: [domain names]} with the primary name tracked separately.
            domains_map = entity_domain_repo.get_domains_for_entities(
                ctx.db, entity_type="data_product", entity_ids=[str(p.id) for p in products_db]
            )
            product_domain_names: Dict[str, List[str]] = {
                pid: [a.domain_name for a in assigned if a.domain_name]
                for pid, assigned in domains_map.items()
            }
            product_primary_domain: Dict[str, Optional[str]] = {
                pid: next((a.domain_name for a in assigned if a.is_primary), None)
                for pid, assigned in domains_map.items()
            }
            
            # Filter by query (name, description, domain)
            query_lower = query.lower() if query and query != '*' else ''
            filtered = []
            
            # Build set of product IDs that match via semantic links
            semantic_product_ids: set = set()
            if query_lower:
                try:
                    sem_links = ctx.db.query(EntitySemanticLinkDb).filter(
                        EntitySemanticLinkDb.entity_type == 'data_product'
                    ).all()
                    for sl in sem_links:
                        iri_tail = (sl.iri.split('#')[-1].split('/')[-1]).lower()
                        label_lower = (sl.label or '').lower()
                        if query_lower in iri_tail or query_lower in label_lower:
                            semantic_product_ids.add(sl.entity_id)
                    if semantic_product_ids:
                        logger.debug(f"[search_data_products] {len(semantic_product_ids)} products matched via semantic links")
                except Exception as e:
                    logger.warning(f"[search_data_products] Semantic link lookup failed: {e}")
            
            for p in products_db:
                p_domain_names = product_domain_names.get(str(p.id), [])
                # If query is empty or '*', include all products
                if not query_lower:
                    include = True
                else:
                    # Match on name
                    name_match = query_lower in (p.name or "").lower()

                    # Match on description (stored as JSON)
                    desc_match = False
                    if p.description:
                        try:
                            desc_dict = json.loads(p.description) if isinstance(p.description, str) else p.description
                            if isinstance(desc_dict, dict):
                                desc_text = desc_dict.get('purpose', '')
                                desc_match = query_lower in desc_text.lower()
                        except Exception:
                            pass

                    # Match on domain (any assigned domain — primary or additional)
                    domain_match = any(query_lower in (n or "").lower() for n in p_domain_names)

                    # Match via semantic links (ontology concepts)
                    semantic_match = str(p.id) in semantic_product_ids

                    include = name_match or desc_match or domain_match or semantic_match

                if include:
                    # Apply filters (any-of over assigned domains)
                    if domain and not any(n.lower() == domain.lower() for n in p_domain_names):
                        continue
                    if status and p.status != status:
                        continue
                    
                    # Extract output tables from output_ports JSON
                    output_tables = []
                    if p.output_ports:
                        try:
                            ports = json.loads(p.output_ports) if isinstance(p.output_ports, str) else p.output_ports
                            if isinstance(ports, list):
                                for port in ports:
                                    if isinstance(port, dict):
                                        output_tables.append(port.get('name', 'Unknown'))
                        except Exception:
                            pass
                    
                    # Extract description purpose from JSON
                    desc_purpose = None
                    if p.description:
                        try:
                            desc_dict = json.loads(p.description) if isinstance(p.description, str) else p.description
                            if isinstance(desc_dict, dict):
                                desc_purpose = desc_dict.get('purpose')
                        except Exception:
                            pass
                    
                    filtered.append({
                        "id": str(p.id),
                        "name": p.name,
                        "domain": product_primary_domain.get(str(p.id)),
                        "description": desc_purpose,
                        "status": p.status,
                        "output_tables": output_tables[:5],  # Limit for response size
                        "version": p.version
                    })
            
            logger.info(f"[search_data_products] SUCCESS: Found {len(filtered)} matching products")
            return ToolResult(
                success=True,
                data={
                    "products": filtered[:20],  # Limit results
                    "total_found": len(filtered)
                }
            )
            
        except Exception as e:
            logger.error(f"[search_data_products] FAILED: {type(e).__name__}: {e}", exc_info=True)
            return ToolResult(
                success=False,
                error=f"{type(e).__name__}: {str(e)}",
                data={"products": []}
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
            
            logger.info(f"[get_data_product] SUCCESS: Found product {product.name}")
            return ToolResult(
                success=True,
                data={
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
                    "url": f"/data-products/{product.id}"
                }
            )
            
        except Exception as e:
            logger.error(f"[get_data_product] FAILED: {type(e).__name__}: {e}", exc_info=True)
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

