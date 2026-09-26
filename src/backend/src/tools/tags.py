"""
Tags tools for LLM.

Tools for managing tags and assigning them to app objects.
"""

from typing import Any, Dict, List, Optional
from uuid import UUID

from src.common.logging import get_logger
from src.controller import search_scoring
from src.tools.base import BaseTool, ToolContext, ToolResult

logger = get_logger(__name__)


class SearchTagsTool(BaseTool):
    """Search for tags via the shared, tokenized search index."""

    name = "search_tags"
    category = "tags"
    description = (
        "Search tags by name, namespace or description (tags categorize any app object). "
        "Use FEW BROAD terms, not full sentences — each term is matched independently. "
        "Narrow with the 'namespace' filter and page with 'offset'. Leave 'query' empty "
        "(or '*') to list tags; the response is always paginated and includes "
        "'total_count', 'has_more' and 'facets'."
    )
    parameters = {
        "query": {
            "type": "string",
            "description": "Search terms (e.g., 'pii', 'customer'). Empty or '*' lists all tags."
        },
        "namespace": {
            "type": "string",
            "description": "Optional filter by namespace name."
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
    required_scope = "tags:read"

    async def execute(
        self,
        ctx: ToolContext,
        query: str = "",
        namespace: Optional[str] = None,
        limit: int = 25,
        offset: int = 0,
    ) -> ToolResult:
        """Search tags over the shared in-memory index."""
        logger.info(f"[search_tags] Starting - query='{query}', namespace={namespace}, limit={limit}, offset={offset}")

        if not ctx.search_manager:
            logger.warning("[search_tags] FAILED: search_manager is None")
            return ToolResult(success=False, error="Search not available", data={"tags": []})

        try:
            # Tag index items store the namespace under extra_data['category'].
            data = search_scoring.search_index(
                ctx.search_manager.index,
                query,
                ctx.search_manager.config,
                type_filter="tag",
                filters={"category": namespace},
                limit=limit,
                offset=offset,
            )
            logger.info(
                f"[search_tags] SUCCESS: returned {data['returned']} of {data['total_count']} matching tags"
            )
            return ToolResult(
                success=True,
                data={
                    "tags": data["results"],
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
            logger.error(f"[search_tags] FAILED: {e.__class__.__name__}: {e}", exc_info=True)
            return ToolResult(success=False, error=f"{e.__class__.__name__}: {str(e)}", data={"tags": []})


class GetTagTool(BaseTool):
    """Get a single tag by ID or fully qualified name."""
    
    name = "get_tag"
    category = "tags"
    description = "Get detailed information about a specific tag by its ID or fully qualified name (namespace::tag_name)."
    parameters = {
        "tag_id": {
            "type": "string",
            "description": "The ID of the tag to retrieve"
        },
        "fqn": {
            "type": "string",
            "description": "Fully qualified name (namespace::tag_name) - alternative to tag_id"
        }
    }
    required_params = []
    required_scope = "tags:read"
    
    async def execute(
        self,
        ctx: ToolContext,
        tag_id: Optional[str] = None,
        fqn: Optional[str] = None
    ) -> ToolResult:
        """Get a tag by ID or FQN."""
        logger.info(f"[get_tag] Starting - tag_id={tag_id}, fqn={fqn}")
        
        if not tag_id and not fqn:
            return ToolResult(
                success=False,
                error="Either tag_id or fqn must be provided"
            )
        
        try:
            from src.controller.tags_manager import TagsManager
            
            tags_manager = TagsManager()
            
            tag = None
            if tag_id:
                tag = tags_manager.get_tag(ctx.db, tag_id=UUID(tag_id))
            elif fqn:
                tag = tags_manager.get_tag_by_fqn(ctx.db, fqn=fqn)
            
            if not tag:
                return ToolResult(
                    success=False,
                    error=f"Tag not found"
                )
            
            logger.info(f"[get_tag] SUCCESS: Found tag {tag.id}")
            return ToolResult(
                success=True,
                data={
                    "id": str(tag.id),
                    "name": tag.name,
                    "fully_qualified_name": tag.fully_qualified_name,
                    "namespace_id": str(tag.namespace_id) if tag.namespace_id else None,
                    "namespace_name": tag.namespace_name,
                    "description": tag.description,
                    "status": tag.status.value if tag.status else None,
                    "parent_id": str(tag.parent_id) if tag.parent_id else None,
                    "created_at": tag.created_at.isoformat() if tag.created_at else None
                }
            )
            
        except Exception as e:
            logger.error(f"[get_tag] FAILED: {type(e).__name__}: {e}", exc_info=True)
            return ToolResult(success=False, error=f"{type(e).__name__}: {str(e)}")


class CreateTagTool(BaseTool):
    """Create a new tag."""
    
    name = "create_tag"
    category = "tags"
    description = (
        "Create a new tag. Tags are organized in namespaces using the format 'namespace/tag_name'. "
        "For example, 'import/healthcare' creates tag 'healthcare' in namespace 'import'. "
        "If no slash is present in the name (e.g., just 'pii'), the tag is created in the 'default' namespace. "
        "The namespace is automatically created if it doesn't exist."
    )
    parameters = {
        "name": {
            "type": "string",
            "description": (
                "Tag name, optionally with namespace prefix using slash separator. "
                "Examples: 'import/healthcare' (namespace='import', tag='healthcare'), "
                "'pii' (uses default namespace), 'compliance/gdpr' (namespace='compliance', tag='gdpr')"
            )
        },
        "description": {
            "type": "string",
            "description": "Description of what this tag represents"
        },
        "namespace_name": {
            "type": "string",
            "description": "Explicit namespace for the tag (overrides namespace parsed from name). Defaults to 'default' if not specified and name has no slash."
        },
        "parent_id": {
            "type": "string",
            "description": "Optional: ID of parent tag for hierarchical organization"
        }
    }
    required_params = ["name"]
    required_scope = "tags:write"
    
    async def execute(
        self,
        ctx: ToolContext,
        name: str,
        description: Optional[str] = None,
        namespace_name: Optional[str] = None,
        parent_id: Optional[str] = None
    ) -> ToolResult:
        """Create a tag."""
        logger.info(f"[create_tag] Starting - name='{name}', namespace={namespace_name}")
        
        try:
            from src.controller.tags_manager import TagsManager
            from src.models.tags import TagCreate, TagNamespaceCreate, TAG_NAMESPACE_SEPARATOR
            
            tags_manager = TagsManager()
            
            # Parse FQN format: if name contains '/' and no explicit namespace_name provided,
            # extract namespace from the name (e.g., 'import/healthcare' -> namespace='import', name='healthcare')
            parsed_namespace = namespace_name
            parsed_name = name
            
            if TAG_NAMESPACE_SEPARATOR in name and not namespace_name:
                parts = name.split(TAG_NAMESPACE_SEPARATOR, 1)  # Split on first slash only
                parsed_namespace = parts[0].strip()
                parsed_name = parts[1].strip()
                logger.info(f"[create_tag] Parsed FQN: namespace='{parsed_namespace}', name='{parsed_name}'")
            
            # Use 'default' namespace if still not set
            final_namespace = parsed_namespace or "default"
            
            # Auto-create namespace if it doesn't exist
            existing_ns = tags_manager.get_namespace_by_name(ctx.db, name=final_namespace)
            if not existing_ns and final_namespace != "default":
                logger.info(f"[create_tag] Auto-creating namespace '{final_namespace}'")
                ns_create = TagNamespaceCreate(name=final_namespace, description=f"Auto-created namespace for {final_namespace} tags")
                tags_manager.create_namespace(ctx.db, namespace_in=ns_create, user_email="llm-assistant")
            
            tag_create = TagCreate(
                name=parsed_name,
                description=description or "",
                namespace_name=final_namespace,
                parent_id=UUID(parent_id) if parent_id else None
            )
            
            created = tags_manager.create_tag(
                ctx.db,
                tag_in=tag_create,
                user_email="llm-assistant"
            )
            
            logger.info(f"[create_tag] SUCCESS: Created tag id={created.id}, name={created.name}, fqn={created.fully_qualified_name}")
            return ToolResult(
                success=True,
                data={
                    "success": True,
                    "tag_id": str(created.id),
                    "name": created.name,
                    "namespace_name": final_namespace,
                    "fully_qualified_name": created.fully_qualified_name,
                    "message": f"Tag '{created.fully_qualified_name}' created successfully."
                }
            )
            
        except Exception as e:
            logger.error(f"[create_tag] FAILED: {type(e).__name__}: {e}", exc_info=True)
            return ToolResult(success=False, error=f"{type(e).__name__}: {str(e)}")


class UpdateTagTool(BaseTool):
    """Update an existing tag."""
    
    name = "update_tag"
    category = "tags"
    description = "Update an existing tag's name, description, or status."
    parameters = {
        "tag_id": {
            "type": "string",
            "description": "ID of the tag to update"
        },
        "name": {
            "type": "string",
            "description": "New name for the tag"
        },
        "description": {
            "type": "string",
            "description": "New description"
        },
        "status": {
            "type": "string",
            "enum": ["active", "deprecated", "archived"],
            "description": "New status for the tag"
        }
    }
    required_params = ["tag_id"]
    required_scope = "tags:write"
    
    async def execute(
        self,
        ctx: ToolContext,
        tag_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        status: Optional[str] = None
    ) -> ToolResult:
        """Update a tag."""
        logger.info(f"[update_tag] Starting - tag_id={tag_id}")
        
        try:
            from src.controller.tags_manager import TagsManager
            from src.models.tags import TagUpdate, TagStatus
            
            tags_manager = TagsManager()
            
            update_data: Dict[str, Any] = {}
            if name is not None:
                update_data["name"] = name
            if description is not None:
                update_data["description"] = description
            if status is not None:
                update_data["status"] = TagStatus(status)
            
            if not update_data:
                return ToolResult(
                    success=False,
                    error="No fields to update. Provide at least one of: name, description, status"
                )
            
            tag_update = TagUpdate(**update_data)
            
            updated = tags_manager.update_tag(
                ctx.db,
                tag_id=UUID(tag_id),
                tag_in=tag_update,
                user_email="llm-assistant"
            )
            
            if not updated:
                return ToolResult(
                    success=False,
                    error=f"Tag '{tag_id}' not found"
                )
            
            logger.info(f"[update_tag] SUCCESS: Updated tag id={updated.id}")
            return ToolResult(
                success=True,
                data={
                    "success": True,
                    "tag_id": str(updated.id),
                    "name": updated.name,
                    "fully_qualified_name": updated.fully_qualified_name,
                    "message": f"Tag '{updated.fully_qualified_name}' updated successfully."
                }
            )
            
        except Exception as e:
            logger.error(f"[update_tag] FAILED: {type(e).__name__}: {e}", exc_info=True)
            return ToolResult(success=False, error=f"{type(e).__name__}: {str(e)}")


class DeleteTagTool(BaseTool):
    """Delete a tag."""
    
    name = "delete_tag"
    category = "tags"
    description = "Delete a tag by its ID. Tags that are parents to other tags cannot be deleted until children are removed."
    parameters = {
        "tag_id": {
            "type": "string",
            "description": "The ID of the tag to delete"
        }
    }
    required_params = ["tag_id"]
    required_scope = "tags:write"
    
    async def execute(
        self,
        ctx: ToolContext,
        tag_id: str
    ) -> ToolResult:
        """Delete a tag."""
        logger.info(f"[delete_tag] Starting - tag_id={tag_id}")
        
        try:
            from src.controller.tags_manager import TagsManager
            
            tags_manager = TagsManager()
            
            # Get tag details before deletion for the response
            tag = tags_manager.get_tag(ctx.db, tag_id=UUID(tag_id))
            tag_name = tag.fully_qualified_name if tag else tag_id
            
            success = tags_manager.delete_tag(ctx.db, tag_id=UUID(tag_id))
            
            if not success:
                return ToolResult(
                    success=False,
                    error=f"Tag '{tag_id}' not found or could not be deleted"
                )
            
            logger.info(f"[delete_tag] SUCCESS: Deleted tag {tag_id}")
            return ToolResult(
                success=True,
                data={
                    "success": True,
                    "message": f"Tag '{tag_name}' deleted successfully",
                    "tag_id": tag_id
                }
            )
            
        except Exception as e:
            logger.error(f"[delete_tag] FAILED: {type(e).__name__}: {e}", exc_info=True)
            return ToolResult(success=False, error=f"{type(e).__name__}: {str(e)}")


class ListEntityTagsTool(BaseTool):
    """List tags assigned to an entity."""
    
    name = "list_entity_tags"
    category = "tags"
    description = "List all tags assigned to a specific entity (data_product, data_contract, data_domain, team, project, etc.)."
    parameters = {
        "entity_type": {
            "type": "string",
            "enum": ["data_product", "data_contract", "data_domain", "team", "project"],
            "description": "Type of entity"
        },
        "entity_id": {
            "type": "string",
            "description": "ID of the entity"
        }
    }
    required_params = ["entity_type", "entity_id"]
    required_scope = "tags:read"
    
    async def execute(
        self,
        ctx: ToolContext,
        entity_type: str,
        entity_id: str
    ) -> ToolResult:
        """List tags for an entity."""
        logger.info(f"[list_entity_tags] Starting - entity_type={entity_type}, entity_id={entity_id}")
        
        try:
            from src.controller.tags_manager import TagsManager
            
            tags_manager = TagsManager()
            
            assigned_tags = tags_manager.list_assigned_tags(
                ctx.db,
                entity_id=entity_id,
                entity_type=entity_type
            )
            
            result_tags = []
            for tag in assigned_tags:
                result_tags.append({
                    "tag_id": str(tag.tag_id),
                    "tag_name": tag.tag_name,
                    "fully_qualified_name": tag.fully_qualified_name,
                    "namespace_name": tag.namespace_name,
                    "assigned_value": tag.assigned_value,
                    "assigned_by": tag.assigned_by,
                    "assigned_at": tag.assigned_at.isoformat() if tag.assigned_at else None
                })
            
            logger.info(f"[list_entity_tags] SUCCESS: Found {len(result_tags)} tags for {entity_type}:{entity_id}")
            return ToolResult(
                success=True,
                data={
                    "entity_type": entity_type,
                    "entity_id": entity_id,
                    "tags": result_tags,
                    "total_count": len(result_tags)
                }
            )
            
        except Exception as e:
            logger.error(f"[list_entity_tags] FAILED: {type(e).__name__}: {e}", exc_info=True)
            return ToolResult(success=False, error=f"{type(e).__name__}: {str(e)}", data={"tags": []})


class AssignTagToEntityTool(BaseTool):
    """Assign a tag to an entity."""
    
    name = "assign_tag_to_entity"
    category = "tags"
    description = "Assign a tag to any entity (data_product, data_contract, data_domain, team, project). Can optionally include an assigned value."
    parameters = {
        "entity_type": {
            "type": "string",
            "enum": ["data_product", "data_contract", "data_domain", "team", "project"],
            "description": "Type of entity to tag"
        },
        "entity_id": {
            "type": "string",
            "description": "ID of the entity to tag"
        },
        "tag_id": {
            "type": "string",
            "description": "ID of the tag to assign"
        },
        "assigned_value": {
            "type": "string",
            "description": "Optional value for the tag assignment (e.g., for key-value tags)"
        }
    }
    required_params = ["entity_type", "entity_id", "tag_id"]
    required_scope = "tags:write"
    
    async def execute(
        self,
        ctx: ToolContext,
        entity_type: str,
        entity_id: str,
        tag_id: str,
        assigned_value: Optional[str] = None
    ) -> ToolResult:
        """Assign a tag to an entity."""
        logger.info(f"[assign_tag_to_entity] Starting - entity_type={entity_type}, entity_id={entity_id}, tag_id={tag_id}")
        
        try:
            from src.controller.tags_manager import TagsManager
            
            tags_manager = TagsManager()
            
            assigned = tags_manager.add_tag_to_entity(
                ctx.db,
                entity_id=entity_id,
                entity_type=entity_type,
                tag_id=UUID(tag_id),
                assigned_value=assigned_value,
                user_email="llm-assistant"
            )
            
            logger.info(f"[assign_tag_to_entity] SUCCESS: Assigned tag {tag_id} to {entity_type}:{entity_id}")
            return ToolResult(
                success=True,
                data={
                    "success": True,
                    "entity_type": entity_type,
                    "entity_id": entity_id,
                    "tag_id": str(assigned.tag_id),
                    "tag_name": assigned.tag_name,
                    "fully_qualified_name": assigned.fully_qualified_name,
                    "message": f"Tag '{assigned.fully_qualified_name}' assigned to {entity_type} successfully."
                }
            )
            
        except Exception as e:
            logger.error(f"[assign_tag_to_entity] FAILED: {type(e).__name__}: {e}", exc_info=True)
            return ToolResult(success=False, error=f"{type(e).__name__}: {str(e)}")


class RemoveTagFromEntityTool(BaseTool):
    """Remove a tag from an entity."""
    
    name = "remove_tag_from_entity"
    category = "tags"
    description = "Remove a tag assignment from an entity."
    parameters = {
        "entity_type": {
            "type": "string",
            "enum": ["data_product", "data_contract", "data_domain", "team", "project"],
            "description": "Type of entity"
        },
        "entity_id": {
            "type": "string",
            "description": "ID of the entity"
        },
        "tag_id": {
            "type": "string",
            "description": "ID of the tag to remove"
        }
    }
    required_params = ["entity_type", "entity_id", "tag_id"]
    required_scope = "tags:write"
    
    async def execute(
        self,
        ctx: ToolContext,
        entity_type: str,
        entity_id: str,
        tag_id: str
    ) -> ToolResult:
        """Remove a tag from an entity."""
        logger.info(f"[remove_tag_from_entity] Starting - entity_type={entity_type}, entity_id={entity_id}, tag_id={tag_id}")
        
        try:
            from src.controller.tags_manager import TagsManager
            
            tags_manager = TagsManager()
            
            success = tags_manager.remove_tag_from_entity(
                ctx.db,
                entity_id=entity_id,
                entity_type=entity_type,
                tag_id=UUID(tag_id),
                user_email=ctx.user_email if hasattr(ctx, 'user_email') else None
            )
            
            if not success:
                return ToolResult(
                    success=False,
                    error=f"Tag '{tag_id}' was not assigned to {entity_type}:{entity_id}"
                )
            
            logger.info(f"[remove_tag_from_entity] SUCCESS: Removed tag {tag_id} from {entity_type}:{entity_id}")
            return ToolResult(
                success=True,
                data={
                    "success": True,
                    "entity_type": entity_type,
                    "entity_id": entity_id,
                    "tag_id": tag_id,
                    "message": f"Tag removed from {entity_type} successfully."
                }
            )
            
        except Exception as e:
            logger.error(f"[remove_tag_from_entity] FAILED: {type(e).__name__}: {e}", exc_info=True)
            return ToolResult(success=False, error=f"{type(e).__name__}: {str(e)}")

