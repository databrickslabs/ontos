from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status, Query, Body, Request
from sqlalchemy.orm import Session

from src.common.logging import get_logger
from src.common.dependencies import DBSessionDep, CurrentUserDep, get_tags_manager, AuditManagerDep, AuditCurrentUserDep
from src.common.authorization import PermissionChecker
from src.common.features import FeatureAccessLevel
from src.controller.tags_manager import TagsManager
from src.models.users import UserInfo # For CurrentUserDep
from src.models.tags import (
    Tag, TagCreate, TagUpdate, TagStatus,
    TagNamespace, TagNamespaceCreate, TagNamespaceUpdate,
    TagNamespacePermission, TagNamespacePermissionCreate, TagNamespacePermissionUpdate,
    AssignedTagCreate, AssignedTag
)

logger = get_logger(__name__)

# Define router with /api prefix, and then /tags group
router = APIRouter(prefix="/api", tags=["Tags"])

# --- Tag Namespace Routes ---
@router.post("/tags/namespaces", response_model=TagNamespace, status_code=status.HTTP_201_CREATED)
async def create_tag_namespace(
    namespace_in: TagNamespaceCreate,
    request: Request,
    db: DBSessionDep,
    background_tasks: BackgroundTasks,
    current_user: CurrentUserDep,
    audit_manager: AuditManagerDep,
    audit_user: AuditCurrentUserDep,
    manager: TagsManager = Depends(get_tags_manager)
):
    success = False
    details = {
        "params": {
            "namespace_name": namespace_in.name,
            "description": namespace_in.description
        }
    }

    try:
        logger.info(f"User '{current_user.email}' creating tag namespace: {namespace_in.name}")
        # Delivery handled via DeliveryMixin in manager
        result = manager.create_namespace(
            db,
            namespace_in=namespace_in,
            user_email=current_user.email,
            background_tasks=background_tasks,
        )
        success = True
        details["namespace_id"] = str(result.id)
        
        return result
    except HTTPException as e:
        details["exception"] = {"type": "HTTPException", "status_code": e.status_code, "detail": e.detail}
        raise
    except Exception as e:
        details["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise
    finally:
        audit_manager.log_action(
            db=db,
            username=audit_user.username,
            ip_address=request.client.host if request.client else None,
            feature="tags",
            action="CREATE",
            success=success,
            details=details
        )

@router.get("/tags/namespaces", response_model=List[TagNamespace])
async def list_tag_namespaces(
    db: DBSessionDep,
    manager: TagsManager = Depends(get_tags_manager),
    skip: int = 0,
    limit: int = Query(default=100, le=1000)
):
    return manager.list_namespaces(db, skip=skip, limit=limit)

@router.get("/tags/namespaces/{namespace_id}", response_model=TagNamespace)
async def get_tag_namespace(
    namespace_id: UUID,
    db: DBSessionDep,
    manager: TagsManager = Depends(get_tags_manager)
):
    namespace = manager.get_namespace(db, namespace_id=namespace_id)
    if not namespace:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tag namespace not found")
    return namespace

@router.put("/tags/namespaces/{namespace_id}", response_model=TagNamespace)
async def update_tag_namespace(
    namespace_id: UUID,
    namespace_in: TagNamespaceUpdate,
    request: Request,
    db: DBSessionDep,
    background_tasks: BackgroundTasks,
    current_user: CurrentUserDep,
    audit_manager: AuditManagerDep,
    audit_user: AuditCurrentUserDep,
    manager: TagsManager = Depends(get_tags_manager)
):
    success = False
    details = {
        "params": {
            "namespace_id": str(namespace_id),
            "updates": namespace_in.dict(exclude_unset=True)
        }
    }

    try:
        logger.info(f"User '{current_user.email}' updating tag namespace ID: {namespace_id}")
        # Delivery handled via DeliveryMixin in manager
        updated_namespace = manager.update_namespace(
            db,
            namespace_id=namespace_id,
            namespace_in=namespace_in,
            user_email=current_user.email,
            background_tasks=background_tasks,
        )
        if not updated_namespace:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tag namespace not found")
        success = True
        
        return updated_namespace
    except HTTPException as e:
        details["exception"] = {"type": "HTTPException", "status_code": e.status_code, "detail": e.detail}
        raise
    except Exception as e:
        details["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise
    finally:
        audit_manager.log_action(
            db=db,
            username=audit_user.username,
            ip_address=request.client.host if request.client else None,
            feature="tags",
            action="UPDATE",
            success=success,
            details=details
        )

@router.delete("/tags/namespaces/{namespace_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tag_namespace(
    namespace_id: UUID,
    request: Request,
    db: DBSessionDep,
    current_user: CurrentUserDep,
    audit_manager: AuditManagerDep,
    audit_user: AuditCurrentUserDep,
    manager: TagsManager = Depends(get_tags_manager)
):
    success = False
    details = {
        "params": {
            "namespace_id": str(namespace_id)
        }
    }

    try:
        logger.info(f"User '{current_user.email}' deleting tag namespace ID: {namespace_id}")
        if not manager.delete_namespace(db, namespace_id=namespace_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tag namespace not found or could not be deleted")
        success = True
        return
    except HTTPException as e:
        details["exception"] = {"type": "HTTPException", "status_code": e.status_code, "detail": e.detail}
        raise
    except Exception as e:
        details["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise
    finally:
        audit_manager.log_action(
            db=db,
            username=audit_user.username,
            ip_address=request.client.host if request.client else None,
            feature="tags",
            action="DELETE",
            success=success,
            details=details
        )

# --- Tag Routes ---
@router.post("/tags", response_model=Tag, status_code=status.HTTP_201_CREATED)
async def create_tag(
    tag_in: TagCreate,
    request: Request,
    db: DBSessionDep,
    current_user: CurrentUserDep,
    audit_manager: AuditManagerDep,
    audit_user: AuditCurrentUserDep,
    manager: TagsManager = Depends(get_tags_manager),
    _: None = Depends(PermissionChecker('tags', FeatureAccessLevel.READ_WRITE))
):
    success = False
    details = {
        "params": {
            "tag_name": tag_in.name,
            "namespace": tag_in.namespace_name or str(tag_in.namespace_id) if tag_in.namespace_id else "default",
            "parent_id": str(tag_in.parent_id) if tag_in.parent_id else None
        }
    }

    try:
        logger.info(f"User '{current_user.email}' creating tag: {tag_in.name} in namespace {tag_in.namespace_name or tag_in.namespace_id or 'default'}")
        result = manager.create_tag(db, tag_in=tag_in, user_email=current_user.email)
        success = True
        details["tag_id"] = str(result.id)
        return result
    except HTTPException as e:
        details["exception"] = {"type": "HTTPException", "status_code": e.status_code, "detail": e.detail}
        raise
    except Exception as e:
        details["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise
    finally:
        audit_manager.log_action(
            db=db,
            username=audit_user.username,
            ip_address=request.client.host if request.client else None,
            feature="tags",
            action="CREATE",
            success=success,
            details=details
        )

@router.get("/tags", response_model=List[Tag])
async def list_tags(
    db: DBSessionDep,
    manager: TagsManager = Depends(get_tags_manager),
    skip: int = 0,
    limit: int = Query(default=100, le=1000),
    namespace_id: Optional[UUID] = Query(None, description="Filter by namespace ID"),
    namespace_name: Optional[str] = Query(None, description="Filter by namespace name"),
    name_contains: Optional[str] = Query(None, description="Filter by tag name containing string (case-insensitive)"),
    status: Optional[TagStatus] = Query(None, description="Filter by tag status"),
    parent_id: Optional[UUID] = Query(None, description="Filter by parent tag ID"),
    is_root: Optional[bool] = Query(None, description="Filter for root tags (parent_id is null) or non-root tags")
):
    return manager.list_tags(db, skip=skip, limit=limit, namespace_id=namespace_id, namespace_name=namespace_name,
                             name_contains=name_contains, status=status, parent_id=parent_id, is_root=is_root)

@router.get("/tags/{tag_id}", response_model=Tag)
async def get_tag(
    tag_id: UUID,
    db: DBSessionDep,
    manager: TagsManager = Depends(get_tags_manager)
):
    tag = manager.get_tag(db, tag_id=tag_id)
    if not tag:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tag not found")
    return tag


@router.get("/tags/{tag_id}/entities", response_model=List[dict])
async def get_entities_for_tag(
    tag_id: UUID,
    db: DBSessionDep,
    entity_type: Optional[str] = Query(None, description="Filter by entity type (e.g., data_product, data_contract, dataset)"),
    manager: TagsManager = Depends(get_tags_manager)
):
    """Get all entities that have this tag assigned."""
    # Verify tag exists
    tag = manager.get_tag(db, tag_id=tag_id)
    if not tag:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tag not found")
    return manager.get_entities_for_tag(db, tag_id=tag_id, entity_type=entity_type)


@router.get("/tags/fqn/{fully_qualified_name:path}", response_model=Tag, name="get_tag_by_fqn")
async def get_tag_by_fully_qualified_name_route(
    fully_qualified_name: str,
    db: DBSessionDep,
    manager: TagsManager = Depends(get_tags_manager)
):
    # Example: /api/tags/fqn/default/my-tag or /api/tags/fqn/custom_ns/another-tag
    tag = manager.get_tag_by_fqn(db, fqn=fully_qualified_name)
    if not tag:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Tag with FQN '{fully_qualified_name}' not found")
    return tag

@router.put("/tags/{tag_id}", response_model=Tag)
async def update_tag(
    tag_id: UUID,
    tag_in: TagUpdate,
    request: Request,
    db: DBSessionDep,
    current_user: CurrentUserDep,
    audit_manager: AuditManagerDep,
    audit_user: AuditCurrentUserDep,
    manager: TagsManager = Depends(get_tags_manager)
):
    success = False
    details = {
        "params": {
            "tag_id": str(tag_id),
            "updates": tag_in.dict(exclude_unset=True)
        }
    }

    try:
        logger.info(f"User '{current_user.email}' updating tag ID: {tag_id}")
        updated_tag = manager.update_tag(db, tag_id=tag_id, tag_in=tag_in, user_email=current_user.email)
        if not updated_tag:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tag not found")
        success = True
        return updated_tag
    except HTTPException as e:
        details["exception"] = {"type": "HTTPException", "status_code": e.status_code, "detail": e.detail}
        raise
    except Exception as e:
        details["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise
    finally:
        audit_manager.log_action(
            db=db,
            username=audit_user.username,
            ip_address=request.client.host if request.client else None,
            feature="tags",
            action="UPDATE",
            success=success,
            details=details
        )

@router.delete("/tags/{tag_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tag(
    tag_id: UUID,
    request: Request,
    db: DBSessionDep,
    current_user: CurrentUserDep,
    audit_manager: AuditManagerDep,
    audit_user: AuditCurrentUserDep,
    manager: TagsManager = Depends(get_tags_manager)
):
    success = False
    details = {
        "params": {
            "tag_id": str(tag_id)
        }
    }

    try:
        logger.info(f"User '{current_user.email}' deleting tag ID: {tag_id}")
        if not manager.delete_tag(db, tag_id=tag_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tag not found or could not be deleted")
        success = True
        return
    except HTTPException as e:
        details["exception"] = {"type": "HTTPException", "status_code": e.status_code, "detail": e.detail}
        raise
    except Exception as e:
        details["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise
    finally:
        audit_manager.log_action(
            db=db,
            username=audit_user.username,
            ip_address=request.client.host if request.client else None,
            feature="tags",
            action="DELETE",
            success=success,
            details=details
        )

# --- Tag Namespace Permission Routes ---
@router.post("/tags/namespaces/{namespace_id}/permissions", response_model=TagNamespacePermission, status_code=status.HTTP_201_CREATED)
async def add_namespace_permission(
    namespace_id: UUID,
    permission_in: TagNamespacePermissionCreate,
    request: Request,
    db: DBSessionDep,
    current_user: CurrentUserDep,
    audit_manager: AuditManagerDep,
    audit_user: AuditCurrentUserDep,
    manager: TagsManager = Depends(get_tags_manager)
):
    success = False
    details = {
        "params": {
            "namespace_id": str(namespace_id),
            "group_id": permission_in.group_id,
            "permission_level": permission_in.access_level
        }
    }

    try:
        logger.info(f"User '{current_user.email}' adding permission to namespace {namespace_id} for group {permission_in.group_id}")
        result = manager.add_permission_to_namespace(db, namespace_id=namespace_id, perm_in=permission_in, user_email=current_user.email)
        success = True
        details["permission_id"] = str(result.id)
        return result
    except HTTPException as e:
        details["exception"] = {"type": "HTTPException", "status_code": e.status_code, "detail": e.detail}
        raise
    except Exception as e:
        details["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise
    finally:
        audit_manager.log_action(
            db=db,
            username=audit_user.username,
            ip_address=request.client.host if request.client else None,
            feature="tags",
            action="CREATE",
            success=success,
            details=details
        )

@router.get("/tags/namespaces/{namespace_id}/permissions", response_model=List[TagNamespacePermission])
async def list_namespace_permissions(
    namespace_id: UUID,
    db: DBSessionDep,
    manager: TagsManager = Depends(get_tags_manager),
    skip: int = 0,
    limit: int = Query(default=100, le=1000)
):
    # Check if namespace exists first (optional, manager method might do it)
    ns = manager.get_namespace(db, namespace_id=namespace_id)
    if not ns:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tag namespace not found")
    return manager.list_permissions_for_namespace(db, namespace_id=namespace_id, skip=skip, limit=limit)

@router.get("/tags/namespaces/{namespace_id}/permissions/{permission_id}", response_model=TagNamespacePermission)
async def get_namespace_permission_detail(
    namespace_id: UUID, # Keep for path consistency, though perm_id is unique
    permission_id: UUID,
    db: DBSessionDep,
    manager: TagsManager = Depends(get_tags_manager)
):
    permission = manager.get_namespace_permission(db, perm_id=permission_id)
    if not permission or permission.namespace_id != namespace_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Permission not found for this namespace")
    return permission

@router.put("/tags/namespaces/{namespace_id}/permissions/{permission_id}", response_model=TagNamespacePermission)
async def update_namespace_permission(
    namespace_id: UUID,
    permission_id: UUID,
    permission_in: TagNamespacePermissionUpdate,
    request: Request,
    db: DBSessionDep,
    current_user: CurrentUserDep,
    audit_manager: AuditManagerDep,
    audit_user: AuditCurrentUserDep,
    manager: TagsManager = Depends(get_tags_manager)
):
    success = False
    details = {
        "params": {
            "namespace_id": str(namespace_id),
            "permission_id": str(permission_id),
            "updates": permission_in.dict(exclude_unset=True)
        }
    }

    try:
        logger.info(f"User '{current_user.email}' updating permission ID {permission_id} for namespace {namespace_id}")
        # First, check if the permission belongs to the given namespace_id to ensure path integrity
        existing_perm_check = manager.get_namespace_permission(db, perm_id=permission_id)
        if not existing_perm_check or existing_perm_check.namespace_id != namespace_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Permission not found or does not belong to the specified namespace.")

        updated_permission = manager.update_namespace_permission(db, perm_id=permission_id, perm_in=permission_in, user_email=current_user.email)
        if not updated_permission:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Permission not found for update")
        success = True
        return updated_permission
    except HTTPException as e:
        details["exception"] = {"type": "HTTPException", "status_code": e.status_code, "detail": e.detail}
        raise
    except Exception as e:
        details["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise
    finally:
        audit_manager.log_action(
            db=db,
            username=audit_user.username,
            ip_address=request.client.host if request.client else None,
            feature="tags",
            action="UPDATE",
            success=success,
            details=details
        )

@router.delete("/tags/namespaces/{namespace_id}/permissions/{permission_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_namespace_permission(
    namespace_id: UUID,
    permission_id: UUID,
    request: Request,
    db: DBSessionDep,
    current_user: CurrentUserDep,
    audit_manager: AuditManagerDep,
    audit_user: AuditCurrentUserDep,
    manager: TagsManager = Depends(get_tags_manager)
):
    success = False
    details = {
        "params": {
            "namespace_id": str(namespace_id),
            "permission_id": str(permission_id)
        }
    }

    try:
        logger.info(f"User '{current_user.email}' deleting permission ID {permission_id} from namespace {namespace_id}")
        # Optional: Check if permission belongs to namespace before deleting
        perm_to_delete = manager.get_namespace_permission(db, perm_id=permission_id)
        if not perm_to_delete or perm_to_delete.namespace_id != namespace_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Permission not found or does not belong to specified namespace.")

        if not manager.remove_permission_from_namespace(db, perm_id=permission_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Permission not found or could not be deleted")
        success = True
        return
    except HTTPException as e:
        details["exception"] = {"type": "HTTPException", "status_code": e.status_code, "detail": e.detail}
        raise
    except Exception as e:
        details["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise
    finally:
        audit_manager.log_action(
            db=db,
            username=audit_user.username,
            ip_address=request.client.host if request.client else None,
            feature="tags",
            action="DELETE",
            success=success,
            details=details
        )

# --- Generic Entity Tagging Routes ---
@router.get("/entities/{entity_type}/{entity_id}/tags", response_model=List[AssignedTag])
async def list_entity_tags(
    entity_type: str,
    entity_id: str,
    db: DBSessionDep,
    manager: TagsManager = Depends(get_tags_manager)
):
    return manager.list_assigned_tags(db, entity_id=entity_id, entity_type=entity_type)

@router.post("/entities/{entity_type}/{entity_id}/tags:set", response_model=List[AssignedTag])
async def set_entity_tags(
    entity_type: str,
    entity_id: str,
    tags: List[AssignedTagCreate],
    request: Request,
    db: DBSessionDep,
    current_user: CurrentUserDep,
    audit_manager: AuditManagerDep,
    audit_user: AuditCurrentUserDep,
    manager: TagsManager = Depends(get_tags_manager)
):
    success = False
    details = {
        "params": {
            "entity_type": entity_type,
            "entity_id": entity_id,
            "tags_count": len(tags)
        }
    }

    try:
        result = manager.set_tags_for_entity(db, entity_id=entity_id, entity_type=entity_type, tags=tags, user_email=current_user.email)
        success = True
        details["assigned_tags"] = [str(t.tag_id) for t in result]
        return result
    except HTTPException as e:
        details["exception"] = {"type": "HTTPException", "status_code": e.status_code, "detail": e.detail}
        raise
    except Exception as e:
        details["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise
    finally:
        audit_manager.log_action(
            db=db,
            username=audit_user.username,
            ip_address=request.client.host if request.client else None,
            feature="tags",
            action="UPDATE",
            success=success,
            details=details
        )

@router.post("/entities/{entity_type}/{entity_id}/tags:add", response_model=AssignedTag)
async def add_tag_to_entity_route(
    entity_type: str,
    entity_id: str,
    tag_id: UUID,
    request: Request,
    db: DBSessionDep,
    current_user: CurrentUserDep,
    audit_manager: AuditManagerDep,
    audit_user: AuditCurrentUserDep,
    assigned_value: Optional[str] = None,
    manager: TagsManager = Depends(get_tags_manager)
):
    success = False
    details = {
        "params": {
            "entity_type": entity_type,
            "entity_id": entity_id,
            "tag_id": str(tag_id),
            "assigned_value": assigned_value
        }
    }

    try:
        result = manager.add_tag_to_entity(db, entity_id=entity_id, entity_type=entity_type, tag_id=tag_id, assigned_value=assigned_value, user_email=current_user.email)
        success = True
        return result
    except HTTPException as e:
        details["exception"] = {"type": "HTTPException", "status_code": e.status_code, "detail": e.detail}
        raise
    except Exception as e:
        details["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise
    finally:
        audit_manager.log_action(
            db=db,
            username=audit_user.username,
            ip_address=request.client.host if request.client else None,
            feature="tags",
            action="CREATE",
            success=success,
            details=details
        )

@router.delete("/entities/{entity_type}/{entity_id}/tags:remove", status_code=status.HTTP_204_NO_CONTENT)
async def remove_tag_from_entity_route(
    entity_type: str,
    entity_id: str,
    tag_id: UUID,
    request: Request,
    db: DBSessionDep,
    current_user: CurrentUserDep,
    audit_manager: AuditManagerDep,
    audit_user: AuditCurrentUserDep,
    manager: TagsManager = Depends(get_tags_manager)
):
    success = False
    details = {
        "params": {
            "entity_type": entity_type,
            "entity_id": entity_id,
            "tag_id": str(tag_id)
        }
    }

    try:
        ok = manager.remove_tag_from_entity(db, entity_id=entity_id, entity_type=entity_type, tag_id=tag_id, user_email=current_user.email if current_user else None)
        if not ok:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tag association not found")
        success = True
        return
    except HTTPException as e:
        details["exception"] = {"type": "HTTPException", "status_code": e.status_code, "detail": e.detail}
        raise
    except Exception as e:
        details["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise
    finally:
        audit_manager.log_action(
            db=db,
            username=audit_user.username,
            ip_address=request.client.host if request.client else None,
            feature="tags",
            action="DELETE",
            success=success,
            details=details
        )


def register_routes(app):
    app.include_router(router)
    logger.info("Tag routes registered with prefix /api/tags") 