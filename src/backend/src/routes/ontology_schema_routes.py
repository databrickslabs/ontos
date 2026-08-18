"""API routes for the ontology-driven schema manager.

Exposes entity type definitions, field schemas, relationship rules,
and hierarchy information derived from the ontos-ontology.ttl RDF graph.
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from src.models.ontology_schema import (
    AssetTypeSyncResult,
    EntityHierarchyNode,
    EntityRelationships,
    EntityTypeDefinition,
    EntityTypeSchema,
    RelationshipDefinition,
    RelationshipDefinitionCreate,
    RelationshipDefinitionUpdate,
)
from src.controller.ontology_schema_manager import OntologySchemaManager
from src.common.authorization import PermissionChecker
from src.common.features import FeatureAccessLevel
from src.common.dependencies import (
    DBSessionDep,
    AuditManagerDep,
    AuditCurrentUserDep,
)
from src.common.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/ontology", tags=["Ontology Schema"])
FEATURE_ID = "ontology"


def get_ontology_schema_manager(request: Request) -> OntologySchemaManager:
    mgr = getattr(request.app.state, "ontology_schema_manager", None)
    if not mgr:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Ontology Schema manager not configured.",
        )
    return mgr


# ===================== Entity Types =====================


@router.get(
    "/entity-types",
    response_model=List[EntityTypeDefinition],
    summary="List all entity types defined in the ontology",
)
def list_entity_types(
    request: Request,
    tier: Optional[str] = Query(None, description="Filter by model tier: 'dedicated' or 'asset'"),
    category: Optional[str] = Query(None, description="Filter by UI category: data, governance, analytics, integration, system"),
    persona: Optional[str] = Query(None, description="Filter by persona visibility: admin, steward, producer, consumer"),
    lang: Optional[str] = Query(None, description="Preferred language for labels (e.g. 'en', 'de')"),
    db: DBSessionDep = None,
    audit_manager: AuditManagerDep = None,
    current_user: AuditCurrentUserDep = None,
    manager: OntologySchemaManager = Depends(get_ontology_schema_manager),
):
    """Return all entity types that have an ontos:modelTier annotation."""
    success = False
    details = {"params": {"tier": tier, "category": category, "persona": persona, "lang": lang}}
    try:
        result = manager.get_entity_types(tier=tier, category=category, persona=persona, lang=lang)
        success = True
        details["count"] = len(result)
        return result
    except Exception as e:
        logger.exception("Failed to list entity types")
        details["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to list entity types")
    finally:
        audit_manager.log_action(
            db=db, username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=FEATURE_ID, action="LIST_ENTITY_TYPES", success=success, details=details,
        )


# ---------- Query-parameter variants (proxy-safe) ----------
# Reverse proxies (e.g. Databricks Apps) can mangle IRIs embedded in
# URL paths by collapsing "//".  These endpoints accept the IRI as a
# query parameter instead, which is never subject to path normalisation.


@router.get(
    "/entity-types/schema",
    response_model=EntityTypeSchema,
    summary="Get field schema for an entity type (query-param variant)",
)
def get_entity_type_schema_q(
    request: Request,
    type_iri: str = Query(..., description="Full IRI of the entity type"),
    lang: Optional[str] = Query(None, description="Preferred language for labels (e.g. 'en', 'de')"),
    db: DBSessionDep = None,
    audit_manager: AuditManagerDep = None,
    current_user: AuditCurrentUserDep = None,
    manager: OntologySchemaManager = Depends(get_ontology_schema_manager),
):
    return _handle_schema(request, type_iri, db, audit_manager, current_user, manager, lang=lang)


@router.get(
    "/entity-types/relationships",
    response_model=EntityRelationships,
    summary="Get relationships for an entity type (query-param variant)",
)
def get_entity_type_relationships_q(
    request: Request,
    type_iri: str = Query(..., description="Full IRI of the entity type"),
    lang: Optional[str] = Query(None, description="Preferred language for labels (e.g. 'en', 'de')"),
    db: DBSessionDep = None,
    audit_manager: AuditManagerDep = None,
    current_user: AuditCurrentUserDep = None,
    manager: OntologySchemaManager = Depends(get_ontology_schema_manager),
):
    return _handle_relationships(request, type_iri, db, audit_manager, current_user, manager, lang=lang)


@router.get(
    "/entity-types/hierarchy-for",
    response_model=List[EntityHierarchyNode],
    summary="Get class hierarchy for an entity type (query-param variant)",
)
def get_entity_type_hierarchy_q(
    request: Request,
    type_iri: str = Query(..., description="Full IRI of the entity type"),
    lang: Optional[str] = Query(None, description="Preferred language for labels (e.g. 'en', 'de')"),
    db: DBSessionDep = None,
    audit_manager: AuditManagerDep = None,
    current_user: AuditCurrentUserDep = None,
    manager: OntologySchemaManager = Depends(get_ontology_schema_manager),
):
    return _handle_hierarchy(request, type_iri, db, audit_manager, current_user, manager, lang=lang)


# ---------- Path-parameter variants (legacy, with IRI normalisation) ----------


@router.get(
    "/entity-types/{type_iri:path}/schema",
    response_model=EntityTypeSchema,
    summary="Get field schema for an entity type",
)
def get_entity_type_schema(
    request: Request,
    type_iri: str,
    lang: Optional[str] = Query(None, description="Preferred language for labels (e.g. 'en', 'de')"),
    db: DBSessionDep = None,
    audit_manager: AuditManagerDep = None,
    current_user: AuditCurrentUserDep = None,
    manager: OntologySchemaManager = Depends(get_ontology_schema_manager),
):
    return _handle_schema(request, type_iri, db, audit_manager, current_user, manager, lang=lang)


@router.get(
    "/entity-types/{type_iri:path}/relationships",
    response_model=EntityRelationships,
    summary="Get relationships for an entity type",
)
def get_entity_type_relationships(
    request: Request,
    type_iri: str,
    lang: Optional[str] = Query(None, description="Preferred language for labels (e.g. 'en', 'de')"),
    db: DBSessionDep = None,
    audit_manager: AuditManagerDep = None,
    current_user: AuditCurrentUserDep = None,
    manager: OntologySchemaManager = Depends(get_ontology_schema_manager),
):
    return _handle_relationships(request, type_iri, db, audit_manager, current_user, manager, lang=lang)


@router.get(
    "/entity-types/{type_iri:path}/hierarchy",
    response_model=List[EntityHierarchyNode],
    summary="Get class hierarchy for an entity type",
)
def get_entity_type_hierarchy(
    request: Request,
    type_iri: str,
    lang: Optional[str] = Query(None, description="Preferred language for labels (e.g. 'en', 'de')"),
    db: DBSessionDep = None,
    audit_manager: AuditManagerDep = None,
    current_user: AuditCurrentUserDep = None,
    manager: OntologySchemaManager = Depends(get_ontology_schema_manager),
):
    return _handle_hierarchy(request, type_iri, db, audit_manager, current_user, manager, lang=lang)


# ---------- Shared handler implementations ----------


def _handle_schema(request, type_iri, db, audit_manager, current_user, manager, lang=None):
    """Return the field schema (data properties) for a specific entity type."""
    success = False
    details = {"params": {"type_iri": type_iri, "lang": lang}}
    try:
        schema = manager.get_entity_type_schema(type_iri, lang=lang)
        if not schema:
            details["exception"] = {"type": "NotFound", "message": f"Entity type not found: {type_iri}"}
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Entity type not found: {type_iri}",
            )
        success = True
        details["field_count"] = len(schema.fields)
        return schema
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to get entity type schema for '%s'", type_iri)
        details["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to get entity type schema")
    finally:
        audit_manager.log_action(
            db=db, username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=FEATURE_ID, action="GET_ENTITY_TYPE_SCHEMA", success=success, details=details,
        )


def _handle_relationships(request, type_iri, db, audit_manager, current_user, manager, lang=None):
    """Return all outgoing and incoming relationships for an entity type."""
    success = False
    details = {"params": {"type_iri": type_iri, "lang": lang}}
    try:
        result = manager.get_relationships(type_iri, lang=lang)
        success = True
        details["outgoing_count"] = len(result.outgoing)
        details["incoming_count"] = len(result.incoming)
        return result
    except Exception as e:
        logger.exception("Failed to get relationships for '%s'", type_iri)
        details["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to get relationships")
    finally:
        audit_manager.log_action(
            db=db, username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=FEATURE_ID, action="GET_ENTITY_TYPE_RELATIONSHIPS", success=success, details=details,
        )


def _handle_hierarchy(request, type_iri, db, audit_manager, current_user, manager, lang=None):
    """Return the class hierarchy subtree rooted at the given entity type."""
    success = False
    details = {"params": {"type_iri": type_iri, "lang": lang}}
    try:
        result = manager.get_hierarchy(root_iri=type_iri, lang=lang)
        success = True
        return result
    except Exception as e:
        logger.exception("Failed to get hierarchy for '%s'", type_iri)
        details["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to get hierarchy")
    finally:
        audit_manager.log_action(
            db=db, username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=FEATURE_ID, action="GET_ENTITY_TYPE_HIERARCHY", success=success, details=details,
        )


# ===================== Full Hierarchy =====================


@router.get(
    "/hierarchy",
    response_model=List[EntityHierarchyNode],
    summary="Get full entity class hierarchy",
)
def get_full_hierarchy(
    request: Request,
    lang: Optional[str] = Query(None, description="Preferred language for labels (e.g. 'en', 'de')"),
    db: DBSessionDep = None,
    audit_manager: AuditManagerDep = None,
    current_user: AuditCurrentUserDep = None,
    manager: OntologySchemaManager = Depends(get_ontology_schema_manager),
):
    """Return the complete class hierarchy from ontos:Entity downward."""
    success = False
    details = {"params": {"lang": lang}}
    try:
        result = manager.get_hierarchy(lang=lang)
        success = True
        return result
    except Exception as e:
        logger.exception("Failed to get full hierarchy")
        details["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to get hierarchy")
    finally:
        audit_manager.log_action(
            db=db, username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=FEATURE_ID, action="GET_FULL_HIERARCHY", success=success, details=details,
        )


# ===================== Asset Type Sync =====================


@router.post(
    "/sync-asset-types",
    response_model=AssetTypeSyncResult,
    summary="Sync ontology asset types to the database",
    dependencies=[Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE))],
)
def sync_asset_types(
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager: OntologySchemaManager = Depends(get_ontology_schema_manager),
):
    """Force a sync of ontology-defined asset types to AssetTypeDb.

    Normally runs automatically on startup. This endpoint allows manual re-sync.
    """
    success = False
    details = {}
    try:
        result = manager.sync_asset_types(db)
        success = True
        details["created"] = result.created
        details["updated"] = result.updated
        details["errors"] = result.errors
        return result
    except Exception as e:
        logger.exception("Failed to sync asset types")
        details["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to sync asset types")
    finally:
        audit_manager.log_action(
            db=db, username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=FEATURE_ID, action="SYNC_ASSET_TYPES", success=success, details=details,
        )


# ===================== User-defined relationship CRUD =====================


@router.get(
    "/relationships/custom",
    response_model=List[RelationshipDefinition],
    summary="List user-defined (custom) relationships",
    dependencies=[Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY))],
)
def list_custom_relationships(
    request: Request,
    lang: Optional[str] = Query(None, description="Preferred language for labels"),
    manager: OntologySchemaManager = Depends(get_ontology_schema_manager),
):
    """Return all relationships created via the API (Ontos-RDF ones are read-only)."""
    try:
        return manager.list_custom_relationships(lang=lang)
    except Exception:
        logger.exception("Failed to list custom relationships")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to list custom relationships")


@router.post(
    "/relationships/custom",
    response_model=RelationshipDefinition,
    status_code=status.HTTP_201_CREATED,
    summary="Create a user-defined relationship",
    dependencies=[Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE))],
)
def create_custom_relationship(
    request: Request,
    payload: RelationshipDefinitionCreate,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager: OntologySchemaManager = Depends(get_ontology_schema_manager),
):
    """Create a relationship (object property) between two ontology classes."""
    success = False
    details = {"source": payload.source_type_iri, "target": payload.target_type_iri, "label": payload.label}
    try:
        result = manager.create_relationship(payload, created_by=current_user.username)
        success = True
        details["property_iri"] = result.property_iri
        return result
    except ValueError as e:
        details["error"] = str(e)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.exception("Failed to create custom relationship")
        details["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create custom relationship")
    finally:
        audit_manager.log_action(
            db=db, username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=FEATURE_ID, action="CREATE_RELATIONSHIP", success=success, details=details,
        )


@router.put(
    "/relationships/custom",
    response_model=RelationshipDefinition,
    summary="Update a user-defined relationship",
    dependencies=[Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE))],
)
def update_custom_relationship(
    request: Request,
    payload: RelationshipDefinitionUpdate,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    property_iri: str = Query(..., description="IRI of the user-defined relationship to update"),
    manager: OntologySchemaManager = Depends(get_ontology_schema_manager),
):
    """Update editable attributes of a user-defined relationship (domain/range immutable)."""
    success = False
    details = {"property_iri": property_iri}
    try:
        result = manager.update_relationship(property_iri, payload)
        success = True
        return result
    except ValueError as e:
        details["error"] = str(e)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.exception("Failed to update custom relationship")
        details["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to update custom relationship")
    finally:
        audit_manager.log_action(
            db=db, username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=FEATURE_ID, action="UPDATE_RELATIONSHIP", success=success, details=details,
        )


@router.delete(
    "/relationships/custom",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a user-defined relationship",
    dependencies=[Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE))],
)
def delete_custom_relationship(
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    property_iri: str = Query(..., description="IRI of the user-defined relationship to delete"),
    manager: OntologySchemaManager = Depends(get_ontology_schema_manager),
):
    """Delete a user-defined relationship. Ontos-RDF relationships cannot be deleted."""
    success = False
    details = {"property_iri": property_iri}
    try:
        manager.delete_relationship(property_iri)
        success = True
    except ValueError as e:
        details["error"] = str(e)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.exception("Failed to delete custom relationship")
        details["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to delete custom relationship")
    finally:
        audit_manager.log_action(
            db=db, username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=FEATURE_ID, action="DELETE_RELATIONSHIP", success=success, details=details,
        )


# ===================== Registration =====================


def register_routes(app):
    app.include_router(router)
    logger.info("Ontology schema routes registered with prefix /api/ontology")
