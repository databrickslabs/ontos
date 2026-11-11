"""API routes for cross-tier entity relationships.

Provides CRUD and query endpoints for relationships between any
application entities, validated against the ontology.
"""

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from src.models.entity_relationships import (
    EntityRelationshipCreate,
    EntityRelationshipRead,
    EntityRelationshipSummary,
    InstanceHierarchyNode,
    HierarchyRootGroup,
)
from src.controller.entity_relationships_manager import EntityRelationshipsManager
from src.common.authorization import PermissionChecker
from src.common.features import FeatureAccessLevel
from src.common.dependencies import (
    DBSessionDep,
    AuditManagerDep,
    AuditCurrentUserDep,
)
from src.common.errors import ConflictError, NotFoundError
from src.common.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/entity-relationships", tags=["Entity Relationships"])
entity_router = APIRouter(prefix="/api/entities", tags=["Entity Relationships"])
hierarchy_router = APIRouter(prefix="/api/entity-hierarchy", tags=["Entity Hierarchy"])
FEATURE_ID = "entity_relationships"


def get_entity_relationships_manager(request: Request) -> EntityRelationshipsManager:
    mgr = getattr(request.app.state, "entity_relationships_manager", None)
    if not mgr:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Entity Relationships manager not configured.",
        )
    return mgr


# ===================== Create =====================


def _concept_label_lookup(request: Request):
    """``iri -> label`` from the semantic models, or None when they aren't loaded."""
    semantic_models = getattr(request.app.state, "semantic_models_manager", None)
    if semantic_models is None:
        return None

    def lookup(iri: str):
        concept = semantic_models.get_concept_details(iri)
        return getattr(concept, "label", None) if concept else None

    return lookup


@router.post(
    "",
    response_model=EntityRelationshipRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE))],
)
def create_relationship(
    request: Request,
    rel_in: EntityRelationshipCreate,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager: EntityRelationshipsManager = Depends(get_entity_relationships_manager),
):
    """Create a relationship between two entities, validated against the ontology."""
    success = False
    details = {
        "params": {
            "source": f"{rel_in.source_type}:{rel_in.source_id}",
            "target": f"{rel_in.target_type}:{rel_in.target_id}",
            "relationship_type": rel_in.relationship_type,
        }
    }
    created_id = None
    try:
        result = manager.create_relationship(
            db=db, rel_in=rel_in, current_user_id=current_user.email,
            concept_label=_concept_label_lookup(request),
        )
        success = True
        created_id = str(result.id)
        return result
    except ValueError as e:
        details["exception"] = {"type": "ValidationError", "message": str(e)}
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    except ConflictError as e:
        details["exception"] = {"type": "ConflictError", "message": str(e)}
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
    except Exception as e:
        logger.exception("Failed to create entity relationship")
        details["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create relationship")
    finally:
        if created_id:
            details["created_resource_id"] = created_id
        audit_manager.log_action(
            db=db, username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=FEATURE_ID, action="CREATE_ENTITY_RELATIONSHIP", success=success, details=details,
        )


# ===================== Delete =====================


@router.delete(
    "/{rel_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE))],
)
def delete_relationship(
    request: Request,
    rel_id: UUID,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager: EntityRelationshipsManager = Depends(get_entity_relationships_manager),
):
    """Delete an entity relationship by ID."""
    success = False
    details = {"params": {"rel_id": str(rel_id)}}
    try:
        manager.delete_relationship(db=db, rel_id=rel_id)
        success = True
        details["deleted_resource_id"] = str(rel_id)
    except NotFoundError as e:
        details["exception"] = {"type": "NotFoundError", "message": str(e)}
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        logger.exception("Failed to delete entity relationship %s", rel_id)
        details["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to delete relationship")
    finally:
        audit_manager.log_action(
            db=db, username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=FEATURE_ID, action="DELETE_ENTITY_RELATIONSHIP", success=success, details=details,
        )


# ===================== Get by ID =====================


@router.get(
    "/{rel_id}",
    response_model=EntityRelationshipRead,
)
def get_relationship(
    request: Request,
    rel_id: UUID,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager: EntityRelationshipsManager = Depends(get_entity_relationships_manager),
):
    """Get a single entity relationship by ID."""
    success = False
    details = {"params": {"rel_id": str(rel_id)}}
    try:
        result = manager.get_relationship(db=db, rel_id=rel_id)
        success = True
        return result
    except NotFoundError as e:
        details["exception"] = {"type": "NotFoundError", "message": str(e)}
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except Exception as e:
        logger.exception("Failed to get entity relationship %s", rel_id)
        details["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to get relationship")
    finally:
        audit_manager.log_action(
            db=db, username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=FEATURE_ID, action="GET_ENTITY_RELATIONSHIP", success=success, details=details,
        )


# ===================== Query =====================


@router.get(
    "",
    response_model=List[EntityRelationshipRead],
    summary="Query entity relationships with filters",
)
def query_relationships(
    request: Request,
    source_type: Optional[str] = Query(None),
    source_id: Optional[str] = Query(None),
    target_type: Optional[str] = Query(None),
    target_id: Optional[str] = Query(None),
    relationship_type: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: DBSessionDep = None,
    audit_manager: AuditManagerDep = None,
    current_user: AuditCurrentUserDep = None,
    manager: EntityRelationshipsManager = Depends(get_entity_relationships_manager),
):
    """Query relationships with optional filters on source, target, and type."""
    success = False
    details = {
        "params": {
            "source_type": source_type, "source_id": source_id,
            "target_type": target_type, "target_id": target_id,
            "relationship_type": relationship_type,
        }
    }
    try:
        result = manager.query_relationships(
            db=db,
            source_type=source_type, source_id=source_id,
            target_type=target_type, target_id=target_id,
            relationship_type=relationship_type,
            skip=skip, limit=limit,
        )
        success = True
        details["count"] = len(result)
        return result
    except Exception as e:
        logger.exception("Failed to query entity relationships")
        details["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to query relationships")
    finally:
        audit_manager.log_action(
            db=db, username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=FEATURE_ID, action="QUERY_ENTITY_RELATIONSHIPS", success=success, details=details,
        )


# ===================== Entity-centric endpoint =====================


@entity_router.get(
    "/{entity_type}/{entity_id}/relationships",
    response_model=EntityRelationshipSummary,
    summary="Get all relationships for a specific entity",
)
def get_entity_relationships(
    request: Request,
    entity_type: str,
    entity_id: str,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager: EntityRelationshipsManager = Depends(get_entity_relationships_manager),
):
    """Return all outgoing and incoming relationships for a specific entity."""
    success = False
    details = {"params": {"entity_type": entity_type, "entity_id": entity_id}}
    try:
        result = manager.get_all_for_entity(db=db, entity_type=entity_type, entity_id=entity_id)
        success = True
        details["total"] = result.total
        return result
    except Exception as e:
        logger.exception("Failed to get relationships for %s:%s", entity_type, entity_id)
        details["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to get entity relationships")
    finally:
        audit_manager.log_action(
            db=db, username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=FEATURE_ID, action="GET_ALL_ENTITY_RELATIONSHIPS", success=success, details=details,
        )


# ===================== Instance Hierarchy =====================


@hierarchy_router.get(
    "/roots",
    response_model=List[HierarchyRootGroup],
    summary="Get root entities for the hierarchy browser",
)
def get_hierarchy_roots(
    request: Request,
    types: Optional[str] = Query(None, description="Comma-separated root types (default: System,DataDomain)"),
    db: DBSessionDep = None,
    manager: EntityRelationshipsManager = Depends(get_entity_relationships_manager),
):
    """Return top-level entities grouped by type for the hierarchy browser sidebar."""
    try:
        root_types = [t.strip() for t in types.split(",")] if types else None
        return manager.get_hierarchy_roots(db=db, root_types=root_types)
    except Exception as e:
        logger.exception("Failed to get hierarchy roots")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get hierarchy roots",
        )


@hierarchy_router.get(
    "/{entity_type}/{entity_id}",
    response_model=InstanceHierarchyNode,
    summary="Get the hierarchy tree for a specific entity",
)
def get_entity_hierarchy(
    request: Request,
    entity_type: str,
    entity_id: str,
    max_depth: int = Query(5, ge=1, le=10, description="Maximum tree depth to expand"),
    db: DBSessionDep = None,
    manager: EntityRelationshipsManager = Depends(get_entity_relationships_manager),
):
    """Build and return the recursive hierarchy tree for a specific entity instance."""
    try:
        result = manager.get_entity_hierarchy(
            db=db, entity_type=entity_type, entity_id=entity_id, max_depth=max_depth,
        )
        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Entity {entity_type}:{entity_id} not found",
            )
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to get entity hierarchy for %s:%s", entity_type, entity_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get entity hierarchy",
        )


@hierarchy_router.get(
    "/paths",
    summary="Get all hierarchy relationship paths from the ontology",
)
def get_hierarchy_paths(
    request: Request,
    manager: EntityRelationshipsManager = Depends(get_entity_relationships_manager),
):
    """Return all ontology-defined hierarchy paths (which types connect to which via which relationship)."""
    try:
        return manager._osm.get_all_hierarchy_paths()
    except Exception as e:
        logger.exception("Failed to get hierarchy paths")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get hierarchy paths",
        )


# ===================== Registration =====================


def register_routes(app):
    app.include_router(router)
    app.include_router(entity_router)
    app.include_router(hierarchy_router)
    logger.info("Entity relationship routes registered with prefix /api/entity-relationships, /api/entities, /api/entity-hierarchy")
