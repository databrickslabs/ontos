from typing import List
from fastapi import APIRouter, Depends, HTTPException, Body, Request

from src.common.authorization import PermissionChecker
from src.common.dependencies import DBSessionDep, AuditCurrentUserDep, AuditManagerDep
from src.common.features import FeatureAccessLevel
from src.common.logging import get_logger
from src.controller.semantic_links_manager import SemanticLinksManager
from src.controller.semantic_models_manager import SemanticModelsManager
from src.models.semantic_links import EntitySemanticLink, EntitySemanticLinkCreate

logger = get_logger(__name__)

router = APIRouter(prefix="/api", tags=["Semantic Links"])


def get_manager(request: Request, db: DBSessionDep) -> SemanticLinksManager:
    semantic_models_manager = getattr(request.app.state, 'semantic_models_manager', None)
    return SemanticLinksManager(db, semantic_models_manager=semantic_models_manager)


@router.get("/semantic-links/entity/{entity_type}/{entity_id}", response_model=List[EntitySemanticLink])
async def list_links(entity_type: str, entity_id: str, manager: SemanticLinksManager = Depends(get_manager)):
    try:
        return manager.list_for_entity(entity_id=entity_id, entity_type=entity_type)
    except Exception as e:
        logger.error("Failed listing semantic links for %s/%s", entity_type, entity_id, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to list semantic links")


@router.get("/semantic-links/iri/{iri:path}", response_model=List[EntitySemanticLink])
async def list_links_by_iri(iri: str, manager: SemanticLinksManager = Depends(get_manager)):
    try:
        return manager.list_for_iri(iri=iri)
    except Exception as e:
        logger.error("Failed listing semantic links for IRI %s", iri, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to list semantic links for IRI")


@router.post("/semantic-links/", response_model=EntitySemanticLink)
async def add_link(
    payload: EntitySemanticLinkCreate,
    request: Request,
    current_user: AuditCurrentUserDep,
    audit_manager: AuditManagerDep,
    db: DBSessionDep = None,
    manager: SemanticLinksManager = Depends(get_manager),
    _: bool = Depends(PermissionChecker('semantic-models', FeatureAccessLevel.READ_WRITE))
):
    success = False
    details = {
        "params": {
            "entity_type": payload.entity_type,
            "entity_id": payload.entity_id,
            "iri": payload.iri,
            "label": payload.label
        }
    }
    created_link_id = None

    try:
        created = manager.add(payload, created_by=(current_user.username if current_user else None))
        if db is not None:
            db.commit()
        success = True
        created_link_id = created.id
        return created
    except HTTPException as e:
        details["exception"] = {"type": "HTTPException", "status_code": e.status_code, "detail": e.detail}
        raise
    except Exception as e:
        logger.error("Failed adding semantic link", exc_info=True)
        details["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise HTTPException(status_code=400, detail="Failed to add semantic link")
    finally:
        if created_link_id:
            details["created_resource_id"] = created_link_id
        if db is not None:
            audit_manager.log_action(
                db=db,
                username=current_user.username if current_user else "anonymous",
                ip_address=request.client.host if request.client else None,
                feature="semantic-links",
                action="CREATE",
                success=success,
                details=details
            )


@router.delete("/semantic-links/{link_id}")
async def delete_link(
    link_id: str,
    request: Request,
    current_user: AuditCurrentUserDep,
    audit_manager: AuditManagerDep,
    db: DBSessionDep = None,
    manager: SemanticLinksManager = Depends(get_manager),
    _: bool = Depends(PermissionChecker('semantic-models', FeatureAccessLevel.READ_WRITE))
):
    success = False
    details = {
        "params": {
            "link_id": link_id
        }
    }

    try:
        # Validate link_id is a valid UUID before querying the database
        try:
            import uuid as _uuid
            _uuid.UUID(link_id)
        except (ValueError, AttributeError):
            raise HTTPException(status_code=404, detail="Link not found")

        ok = manager.remove(link_id, removed_by=(current_user.username if current_user else None))
        if not ok:
            raise HTTPException(status_code=404, detail="Link not found")
        if db is not None:
            db.commit()
        success = True
        return {"deleted": True}
    except HTTPException as e:
        details["exception"] = {"type": "HTTPException", "status_code": e.status_code, "detail": e.detail}
        raise
    except Exception as e:
        logger.error("Failed deleting semantic link %s", link_id, exc_info=True)
        details["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise HTTPException(status_code=500, detail="Failed to delete semantic link")
    finally:
        if db is not None:
            audit_manager.log_action(
                db=db,
                username=current_user.username if current_user else "anonymous",
                ip_address=request.client.host if request.client else None,
                feature="semantic-links",
                action="DELETE",
                success=success,
                details=details
            )


def register_routes(app):
    app.include_router(router)

