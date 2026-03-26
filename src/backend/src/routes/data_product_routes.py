import os
from pathlib import Path
from typing import List, Dict, Any, Optional

import yaml
from fastapi import APIRouter, HTTPException, UploadFile, File, Body, Depends, Request, BackgroundTasks, Query
from fastapi.responses import JSONResponse
from pydantic import ValidationError
import json
import uuid
from sqlalchemy.orm import Session

from src.controller.data_products_manager import DataProductsManager
from src.models.data_products import (
    DataProduct,
    GenieSpaceRequest,
    NewVersionRequest,
    SubscriptionCreate,
    SubscriptionResponse,
    SubscribersListResponse,
    ChangeStatusPayload,
    RequestStatusChangePayload,
    HandleStatusChangePayload,
    CommitDraftRequest,
    CommitDraftResponse,
    DiffFromParentResponse
)
from src.models.users import UserInfo
from databricks.sdk.errors import PermissionDenied

from src.common.authorization import PermissionChecker, ApprovalChecker
from src.common.features import FeatureAccessLevel
from src.common.file_security import sanitize_filename

from src.common.dependencies import (
    CurrentUserDep,
    DBSessionDep,
    AuditManagerDep,
    AuditCurrentUserDep,
    ChangeLogManagerDep,
)
from src.common.workflow_triggers import get_trigger_registry
from src.models.process_workflows import EntityType
from src.models.notifications import NotificationType
from src.common.dependencies import NotificationsManagerDep, CurrentUserDep, DBSessionDep

from src.common.logging import get_logger
logger = get_logger(__name__)

router = APIRouter(prefix="/api", tags=["Data Products"])

DATA_PRODUCTS_FEATURE_ID = "data-products"

def get_data_products_manager(
    request: Request # Inject Request
) -> DataProductsManager:
    manager = getattr(request.app.state, 'data_products_manager', None)
    if manager is None:
         logger.critical("DataProductsManager instance not found in app.state!")
         raise HTTPException(status_code=500, detail="Data Products service is not available.")
    if not isinstance(manager, DataProductsManager):
        logger.critical(f"Object found at app.state.data_products_manager is not a DataProductsManager instance (Type: {type(manager)})!")
        raise HTTPException(status_code=500, detail="Data Products service configuration error.")
    return manager


# --- Lifecycle transitions (minimal) ---

@router.post('/data-products/{product_id}/move-to-sandbox')
async def move_product_to_sandbox(
    product_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager: DataProductsManager = Depends(get_data_products_manager),
    _: bool = Depends(PermissionChecker(DATA_PRODUCTS_FEATURE_ID, FeatureAccessLevel.READ_WRITE))
):
    """Move a draft product to sandbox for testing (draft → sandbox)."""
    try:
        updated_product = manager.move_to_sandbox(product_id, current_user.username if current_user else None)
        
        audit_manager.log_action(
            db=db,
            username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=DATA_PRODUCTS_FEATURE_ID,
            action='MOVE_TO_SANDBOX',
            success=True,
            details={'product_id': product_id, 'status': updated_product.status}
        )
        
        return {'status': updated_product.status}
    except ValueError as e:
        logger.error("Validation error moving product %s to sandbox: %s", product_id, e)
        raise HTTPException(status_code=409, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Move to sandbox failed for product_id=%s", product_id)
        raise HTTPException(status_code=500, detail="Failed to move product to sandbox")


@router.post('/data-products/{product_id}/submit-review')
@router.post('/data-products/{product_id}/submit-certification')
async def submit_product_for_review(
    product_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager: DataProductsManager = Depends(get_data_products_manager),
    _: bool = Depends(PermissionChecker(DATA_PRODUCTS_FEATURE_ID, FeatureAccessLevel.READ_WRITE))
):
    """Submit a draft/sandbox product for review (draft/sandbox → proposed)."""
    try:
        updated_product = manager.submit_for_review(product_id, current_user.username if current_user else None)
        
        audit_manager.log_action(
            db=db,
            username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=DATA_PRODUCTS_FEATURE_ID,
            action='SUBMIT_CERTIFICATION',
            success=True,
            details={'product_id': product_id, 'status': updated_product.status}
        )
        
        return {'status': updated_product.status}
    except ValueError as e:
        logger.error("Validation error submitting product %s: %s", product_id, e)
        raise HTTPException(status_code=409, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Submit product certification failed for product_id=%s", product_id)
        raise HTTPException(status_code=500, detail="Failed to submit product certification")


@router.post('/data-products/{product_id}/approve')
async def approve_product(
    product_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager: DataProductsManager = Depends(get_data_products_manager),
    _: bool = Depends(ApprovalChecker('PRODUCTS'))
):
    """Approve a product under review (under_review → approved)."""
    try:
        updated_product = manager.approve_product(product_id, current_user.username if current_user else None)
        
        audit_manager.log_action(
            db=db,
            username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=DATA_PRODUCTS_FEATURE_ID,
            action='APPROVE',
            success=True,
            details={'product_id': product_id, 'status': updated_product.status}
        )
        
        return {'status': updated_product.status}
    except ValueError as e:
        logger.error("Validation error approving product %s: %s", product_id, e)
        raise HTTPException(status_code=409, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Approve product failed for product_id=%s", product_id)
        raise HTTPException(status_code=500, detail="Failed to approve product")


@router.post('/data-products/{product_id}/reject')
async def reject_product(
    product_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager: DataProductsManager = Depends(get_data_products_manager),
    _: bool = Depends(ApprovalChecker('PRODUCTS'))
):
    """Reject a product review, returning to draft (under_review → draft)."""
    try:
        updated_product = manager.reject_product(product_id, current_user.username if current_user else None)
        
        audit_manager.log_action(
            db=db,
            username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=DATA_PRODUCTS_FEATURE_ID,
            action='REJECT',
            success=True,
            details={'product_id': product_id, 'status': updated_product.status}
        )
        
        return {'status': updated_product.status}
    except ValueError as e:
        logger.error("Validation error rejecting product %s: %s", product_id, e)
        raise HTTPException(status_code=409, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Reject product failed for product_id=%s", product_id)
        raise HTTPException(status_code=500, detail="Failed to reject product")


@router.post('/data-products/{product_id}/publish')
async def publish_product(
    product_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager: DataProductsManager = Depends(get_data_products_manager),
    _: bool = Depends(PermissionChecker(DATA_PRODUCTS_FEATURE_ID, FeatureAccessLevel.READ_WRITE))
):
    """
    Publish an approved product to make it active and available in the marketplace.

    Validates that all output ports have dataContractId set before allowing publication.
    ODPS lifecycle (aligned with ODCS): approved → active
    """
    try:
        updated_product = manager.publish_product(product_id, current_user.username if current_user else None)
        
        audit_manager.log_action(
            db=db,
            username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=DATA_PRODUCTS_FEATURE_ID,
            action='PUBLISH',
            success=True,
            details={'product_id': product_id, 'status': updated_product.status}
        )
        
        return {'status': updated_product.status}
    except ValueError as e:
        logger.error("Validation error publishing product %s: %s", product_id, e)
        error_status = 409 if "Invalid transition" in str(e) else 400
        raise HTTPException(status_code=error_status, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Publish product failed for product_id=%s", product_id)
        raise HTTPException(status_code=500, detail="Failed to publish product")


@router.post('/data-products/{product_id}/set-publication-scope')
async def set_publication_scope(
    product_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    body: dict = Body(...),
    manager: DataProductsManager = Depends(get_data_products_manager),
    _: bool = Depends(PermissionChecker(DATA_PRODUCTS_FEATURE_ID, FeatureAccessLevel.READ_WRITE))
):
    """
    Set publication scope for a data product.
    Body: { "scope": "none" | "domain" | "organization" | "external" }
    Product must be active to publish.
    """
    from datetime import datetime, timezone
    scope = body.get("scope", "none")
    valid_scopes = ["none", "domain", "organization", "external"]
    if scope not in valid_scopes:
        raise HTTPException(status_code=422, detail=f"Invalid scope. Must be one of: {valid_scopes}")

    try:
        product_db = manager._repo.get(db=db, id=product_id)
        if not product_db:
            raise HTTPException(status_code=404, detail="Data product not found")

        if scope != "none" and product_db.status != "active":
            raise HTTPException(
                status_code=409,
                detail=f"Product must be active to publish. Current status: {product_db.status}"
            )

        product_db.publication_scope = scope
        if scope != "none":
            product_db.published_at = datetime.now(timezone.utc)
            product_db.published_by = current_user.username if current_user else None
        else:
            product_db.published_at = None
            product_db.published_by = None
        db.add(product_db)
        db.commit()
        db.refresh(product_db)

        audit_manager.log_action(
            db=db,
            username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=DATA_PRODUCTS_FEATURE_ID,
            action='SET_PUBLICATION_SCOPE',
            success=True,
            details={'product_id': product_id, 'scope': scope}
        )

        return {
            'publication_scope': product_db.publication_scope,
            'published_at': str(product_db.published_at) if product_db.published_at else None,
            'published_by': product_db.published_by,
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Set publication scope failed for product_id=%s", product_id)
        raise HTTPException(status_code=500, detail="Failed to set publication scope")


@router.post('/data-products/{product_id}/unpublish')
async def unpublish_product(
    product_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager: DataProductsManager = Depends(get_data_products_manager),
    _: bool = Depends(PermissionChecker(DATA_PRODUCTS_FEATURE_ID, FeatureAccessLevel.READ_WRITE))
):
    """Remove a data product from the marketplace (set publication_scope to none)."""
    try:
        product_db = manager._repo.get(db=db, id=product_id)
        if not product_db:
            raise HTTPException(status_code=404, detail="Data product not found")

        product_db.publication_scope = "none"
        product_db.published_at = None
        product_db.published_by = None
        db.add(product_db)
        db.commit()

        get_trigger_registry(db).on_unpublish(
            EntityType.DATA_PRODUCT,
            product_id,
            entity_name=product_db.name,
            user_email=current_user.username,
        )

        audit_manager.log_action(
            db=db,
            username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=DATA_PRODUCTS_FEATURE_ID,
            action='UNPUBLISH',
            success=True,
            details={'product_id': product_id}
        )

        return {'publication_scope': 'none'}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Unpublish product failed for product_id=%s", product_id)
        raise HTTPException(status_code=500, detail="Failed to unpublish product")


@router.post('/data-products/{product_id}/request-certify')
async def request_certify_product(
    product_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    change_log_manager: ChangeLogManagerDep,
    current_user: AuditCurrentUserDep,
    body: dict = Body(...),
    manager: DataProductsManager = Depends(get_data_products_manager),
    _: bool = Depends(PermissionChecker(DATA_PRODUCTS_FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    """Request certification for a data product (workflow); approvers use handle-certify."""
    certification_level = body.get("certification_level")
    if certification_level is None:
        raise HTTPException(status_code=422, detail="certification_level is required")
    message = body.get("message")

    try:
        product_db = manager._repo.get(db=db, id=product_id)
        if not product_db:
            raise HTTPException(status_code=404, detail="Data product not found")

        username = current_user.username if current_user else None
        change_log_manager.log_change_with_details(
            db,
            entity_type="data_product",
            entity_id=product_id,
            action="certification_requested",
            username=username,
            details={"certification_level": certification_level, "message": message},
        )

        get_trigger_registry(db).on_request_certify(
            EntityType.DATA_PRODUCT,
            product_id,
            entity_name=product_db.name,
            entity_data={
                "requested_certification_level": certification_level,
                "message": message,
                "requester": username,
            },
            user_email=username,
            blocking=True,
        )

        audit_manager.log_action(
            db=db,
            username=username,
            ip_address=request.client.host if request.client else None,
            feature=DATA_PRODUCTS_FEATURE_ID,
            action="REQUEST_CERTIFY",
            success=True,
            details={"product_id": product_id, "certification_level": certification_level},
        )

        return JSONResponse(
            status_code=202,
            content={"status": "requested", "message": "Certification request submitted"},
        )
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Request certify failed for product_id=%s", product_id)
        raise HTTPException(status_code=500, detail="Failed to submit certification request")


@router.post('/data-products/{product_id}/handle-certify')
async def handle_certify_product(
    product_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    change_log_manager: ChangeLogManagerDep,
    current_user: AuditCurrentUserDep,
    body: dict = Body(...),
    manager: DataProductsManager = Depends(get_data_products_manager),
    _: bool = Depends(ApprovalChecker('PRODUCTS')),
):
    """Approve or deny a certification request for a data product."""
    from datetime import datetime, timezone

    if body.get("approved") is None:
        raise HTTPException(status_code=422, detail="approved is required")

    approved = bool(body.get("approved"))
    notes = body.get("notes")
    username = current_user.username if current_user else None

    try:
        product_db = manager._repo.get(db=db, id=product_id)
        if not product_db:
            raise HTTPException(status_code=404, detail="Data product not found")

        if not approved:
            change_log_manager.log_change_with_details(
                db,
                entity_type="data_product",
                entity_id=product_id,
                action="certification_denied",
                username=username,
                details={"notes": notes},
            )
            audit_manager.log_action(
                db=db,
                username=username,
                ip_address=request.client.host if request.client else None,
                feature=DATA_PRODUCTS_FEATURE_ID,
                action="HANDLE_CERTIFY",
                success=True,
                details={"product_id": product_id, "approved": False},
            )
            return {"status": "denied"}

        certification_level = body.get("certification_level")
        if certification_level is None:
            raise HTTPException(status_code=422, detail="certification_level is required when approved is true")

        if product_db.status not in ("active",):
            raise HTTPException(
                status_code=409,
                detail=f"Product must be active to certify. Current status: {product_db.status}",
            )

        from src.repositories.certification_levels_repository import certification_levels_repo

        level = certification_levels_repo.get_by_order(db, certification_level)
        if not level:
            raise HTTPException(status_code=404, detail=f"Certification level {certification_level} not found")

        product_db.certification_level = certification_level
        product_db.certified_at = datetime.now(timezone.utc)
        product_db.certified_by = username
        product_db.certification_notes = notes
        db.add(product_db)
        db.commit()
        db.refresh(product_db)

        audit_manager.log_action(
            db=db,
            username=username,
            ip_address=request.client.host if request.client else None,
            feature=DATA_PRODUCTS_FEATURE_ID,
            action='CERTIFY',
            success=True,
            details={'product_id': product_id, 'certification_level': certification_level},
        )

        from src.controller.certification_propagator import propagate_certification

        propagate_certification(db, "DataProduct", product_id)
        db.commit()

        try:
            get_trigger_registry(db).on_certify(
                EntityType.DATA_PRODUCT,
                product_id,
                entity_name=product_db.name,
                entity_data={
                    "certification_level": certification_level,
                    "notes": notes,
                    "certified_by": username,
                },
                user_email=username,
                blocking=False,
            )
        except Exception as trigger_err:
            logger.warning("on_certify trigger error (non-fatal): %s", trigger_err)

        return {
            'certification_level': product_db.certification_level,
            'certified_at': str(product_db.certified_at),
            'certified_by': product_db.certified_by,
            'certification_notes': product_db.certification_notes,
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Handle certify failed for product_id=%s", product_id)
        raise HTTPException(status_code=500, detail="Failed to handle certification request")


@router.post('/data-products/{product_id}/handle-publish')
async def handle_publish_product(
    product_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    change_log_manager: ChangeLogManagerDep,
    current_user: AuditCurrentUserDep,
    body: dict = Body(...),
    manager: DataProductsManager = Depends(get_data_products_manager),
    _: bool = Depends(ApprovalChecker('PRODUCTS')),
):
    """Approve or deny a publication request for a data product."""
    from datetime import datetime, timezone

    if body.get("approved") is None:
        raise HTTPException(status_code=422, detail="approved is required")

    approved = bool(body.get("approved"))
    username = current_user.username if current_user else None

    try:
        product_db = manager._repo.get(db=db, id=product_id)
        if not product_db:
            raise HTTPException(status_code=404, detail="Data product not found")

        if not approved:
            change_log_manager.log_change_with_details(
                db,
                entity_type="data_product",
                entity_id=product_id,
                action="publication_denied",
                username=username,
                details={"notes": body.get("notes")},
            )
            audit_manager.log_action(
                db=db,
                username=username,
                ip_address=request.client.host if request.client else None,
                feature=DATA_PRODUCTS_FEATURE_ID,
                action="HANDLE_PUBLISH",
                success=True,
                details={"product_id": product_id, "approved": False},
            )
            return {"status": "denied"}

        scope = body.get("scope")
        if scope is None:
            raise HTTPException(status_code=422, detail="scope is required when approved is true")

        valid_scopes = ["none", "domain", "organization", "external"]
        if scope not in valid_scopes:
            raise HTTPException(status_code=422, detail=f"Invalid scope. Must be one of: {valid_scopes}")

        if scope != "none" and product_db.status != "active":
            raise HTTPException(
                status_code=409,
                detail=f"Product must be active to publish. Current status: {product_db.status}",
            )

        product_db.publication_scope = scope
        if scope != "none":
            product_db.published_at = datetime.now(timezone.utc)
            product_db.published_by = username
        else:
            product_db.published_at = None
            product_db.published_by = None

        db.add(product_db)
        db.commit()
        db.refresh(product_db)

        audit_manager.log_action(
            db=db,
            username=username,
            ip_address=request.client.host if request.client else None,
            feature=DATA_PRODUCTS_FEATURE_ID,
            action='SET_PUBLICATION_SCOPE',
            success=True,
            details={'product_id': product_id, 'scope': scope},
        )

        try:
            if scope != "none":
                get_trigger_registry(db).on_publish(
                    EntityType.DATA_PRODUCT,
                    product_id,
                    entity_name=product_db.name,
                    entity_data={
                        "publication_scope": scope,
                        "published_by": username,
                        "name": product_db.name,
                    },
                    user_email=username,
                    blocking=False,
                )
        except Exception as trigger_err:
            logger.warning("on_publish trigger error (non-fatal): %s", trigger_err)

        return {
            'publication_scope': product_db.publication_scope,
            'published_at': str(product_db.published_at) if product_db.published_at else None,
            'published_by': product_db.published_by,
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Handle publish failed for product_id=%s", product_id)
        raise HTTPException(status_code=500, detail="Failed to handle publication request")


@router.post('/data-products/{product_id}/request-publish')
async def request_publish_product(
    product_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    change_log_manager: ChangeLogManagerDep,
    current_user: AuditCurrentUserDep,
    body: dict = Body(...),
    manager: DataProductsManager = Depends(get_data_products_manager),
    _: bool = Depends(PermissionChecker(DATA_PRODUCTS_FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    """Request publication for a data product (workflow); approvers use handle-publish."""
    scope = body.get("scope")
    if scope is None:
        raise HTTPException(status_code=422, detail="scope is required")

    valid_scopes = ["none", "domain", "organization", "external"]
    if scope not in valid_scopes:
        raise HTTPException(status_code=422, detail=f"Invalid scope. Must be one of: {valid_scopes}")

    justification = body.get("justification")
    username = current_user.username if current_user else None

    try:
        product_db = manager._repo.get(db=db, id=product_id)
        if not product_db:
            raise HTTPException(status_code=404, detail="Data product not found")

        change_log_manager.log_change_with_details(
            db,
            entity_type="data_product",
            entity_id=product_id,
            action="publication_requested",
            username=username,
            details={"scope": scope, "justification": justification},
        )

        get_trigger_registry(db).on_request_publish(
            EntityType.DATA_PRODUCT,
            product_id,
            entity_name=product_db.name,
            entity_data={
                "requested_scope": scope,
                "justification": justification,
                "requester": username,
            },
            user_email=username,
            blocking=True,
        )

        audit_manager.log_action(
            db=db,
            username=username,
            ip_address=request.client.host if request.client else None,
            feature=DATA_PRODUCTS_FEATURE_ID,
            action="REQUEST_PUBLISH",
            success=True,
            details={"product_id": product_id, "scope": scope},
        )

        return JSONResponse(
            status_code=202,
            content={"status": "requested", "message": "Publication request submitted"},
        )
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Request publish failed for product_id=%s", product_id)
        raise HTTPException(status_code=500, detail="Failed to submit publication request")


@router.post('/data-products/{product_id}/certify')
async def certify_product(
    product_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    body: dict = Body(...),
    manager: DataProductsManager = Depends(get_data_products_manager),
    _: bool = Depends(ApprovalChecker('PRODUCTS'))
):
    """
    Certify a data product at a specific certification level.
    Requires active status. Certification is now a separate dimension from status.
    Body: { "certification_level": int, "notes": str? }
    """
    from datetime import datetime, timezone
    certification_level = body.get("certification_level")
    if certification_level is None:
        raise HTTPException(status_code=422, detail="certification_level is required")

    try:
        product_db = manager._repo.get(db=db, id=product_id)
        if not product_db:
            raise HTTPException(status_code=404, detail="Data product not found")

        if product_db.status not in ("active",):
            raise HTTPException(
                status_code=409,
                detail=f"Product must be active to certify. Current status: {product_db.status}"
            )

        from src.repositories.certification_levels_repository import certification_levels_repo
        level = certification_levels_repo.get_by_order(db, certification_level)
        if not level:
            raise HTTPException(status_code=404, detail=f"Certification level {certification_level} not found")

        product_db.certification_level = certification_level
        product_db.certified_at = datetime.now(timezone.utc)
        product_db.certified_by = current_user.username if current_user else None
        product_db.certification_notes = body.get("notes")
        db.add(product_db)
        db.commit()
        db.refresh(product_db)

        audit_manager.log_action(
            db=db,
            username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=DATA_PRODUCTS_FEATURE_ID,
            action='CERTIFY',
            success=True,
            details={'product_id': product_id, 'certification_level': certification_level}
        )

        # Propagate certification to downstream entities
        from src.controller.certification_propagator import propagate_certification
        propagate_certification(db, "DataProduct", product_id)
        db.commit()

        get_trigger_registry(db).on_certify(
            EntityType.DATA_PRODUCT,
            product_id,
            entity_name=product_db.name,
            entity_data={"certification_level": product_db.certification_level},
            user_email=current_user.username,
        )

        return {
            'certification_level': product_db.certification_level,
            'certified_at': str(product_db.certified_at),
            'certified_by': product_db.certified_by,
            'certification_notes': product_db.certification_notes,
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Certify product failed for product_id=%s", product_id)
        raise HTTPException(status_code=500, detail="Failed to certify product")


@router.post('/data-products/{product_id}/decertify')
async def decertify_product(
    product_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager: DataProductsManager = Depends(get_data_products_manager),
    _: bool = Depends(ApprovalChecker('PRODUCTS'))
):
    """Remove certification from a data product."""
    try:
        product_db = manager._repo.get(db=db, id=product_id)
        if not product_db:
            raise HTTPException(status_code=404, detail="Data product not found")

        old_level = product_db.certification_level
        product_db.certification_level = None
        product_db.certified_at = None
        product_db.certified_by = None
        product_db.certification_expires_at = None
        product_db.certification_notes = None
        db.add(product_db)
        db.commit()

        get_trigger_registry(db).on_decertify(
            EntityType.DATA_PRODUCT,
            product_id,
            entity_name=product_db.name,
            user_email=current_user.username,
        )

        audit_manager.log_action(
            db=db,
            username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=DATA_PRODUCTS_FEATURE_ID,
            action='DECERTIFY',
            success=True,
            details={'product_id': product_id, 'previous_level': old_level}
        )

        return {'certification_level': None}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Decertify product failed for product_id=%s", product_id)
        raise HTTPException(status_code=500, detail="Failed to decertify product")


@router.post('/data-products/{product_id}/deprecate')
async def deprecate_product(
    product_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager: DataProductsManager = Depends(get_data_products_manager),
    _: bool = Depends(PermissionChecker(DATA_PRODUCTS_FEATURE_ID, FeatureAccessLevel.READ_WRITE))
):
    """
    Deprecate an active or certified product to signal it will be retired soon.
    ODPS lifecycle: active/certified → deprecated
    """
    try:
        updated_product = manager.deprecate_product(product_id, current_user.username if current_user else None)
        
        audit_manager.log_action(
            db=db,
            username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=DATA_PRODUCTS_FEATURE_ID,
            action='DEPRECATE',
            success=True,
            details={'product_id': product_id, 'status': updated_product.status}
        )
        
        return {'status': updated_product.status}
    except ValueError as e:
        logger.error("Validation error deprecating product %s: %s", product_id, e)
        raise HTTPException(status_code=409, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Deprecate product failed for product_id=%s", product_id)
        raise HTTPException(status_code=500, detail="Failed to deprecate product")


@router.post('/data-products/{product_id}/request-review')
async def request_product_review(
    product_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager: DataProductsManager = Depends(get_data_products_manager),
    _: bool = Depends(PermissionChecker(DATA_PRODUCTS_FEATURE_ID, FeatureAccessLevel.READ_WRITE))
):
    """
    Request a data steward review for a product.
    Transitions draft/sandbox → proposed → under_review with notifications.
    """
    from pydantic import BaseModel
    
    class ReviewRequest(BaseModel):
        reviewer_email: str
        message: Optional[str] = None
    
    try:
        body = await request.json()
        review_request = ReviewRequest(**body)
        
        result = manager.request_review(
            product_id=product_id,
            reviewer_email=review_request.reviewer_email,
            requester_email=current_user.username if current_user else "unknown",
            message=review_request.message,
            current_user=current_user.username if current_user else None
        )
        
        audit_manager.log_action(
            db=db,
            username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=DATA_PRODUCTS_FEATURE_ID,
            action='REQUEST_REVIEW',
            success=True,
            details={'product_id': product_id, 'reviewer': review_request.reviewer_email}
        )
        
        return result
    except ValueError as e:
        logger.error("Validation error requesting review for product %s: %s", product_id, e)
        raise HTTPException(status_code=409, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Request review failed for product_id=%s", product_id)
        raise HTTPException(status_code=500, detail="Failed to request product review")

# --- Contract-Product Integration Endpoints ---

@router.post('/data-products/from-contract', response_model=DataProduct, status_code=201)
async def create_product_from_contract(
    contract_id: str = Body(..., embed=True),
    product_name: str = Body(..., embed=True),
    product_type: str = Body(..., embed=True),
    version: str = Body(..., embed=True),
    output_port_name: Optional[str] = Body(None, embed=True),
    request: Request = None,
    db: DBSessionDep = None,
    audit_manager: AuditManagerDep = None,
    current_user: AuditCurrentUserDep = None,
    manager: DataProductsManager = Depends(get_data_products_manager),
    _: bool = Depends(PermissionChecker(DATA_PRODUCTS_FEATURE_ID, FeatureAccessLevel.READ_WRITE))
):
    """
    Create a new Data Product from an existing Data Contract.

    The contract governs one output port of the product. Inherits domain_id,
    owner_team_id, and project_id from the contract.
    """
    try:
        from src.models.data_products import DataProductType

        # Convert product_type string to enum
        try:
            product_type_enum = DataProductType(product_type)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid product_type: {product_type}. Must be one of: {[t.value for t in DataProductType]}"
            )

        # Create product via manager
        created_product = manager.create_from_contract(
            contract_id=contract_id,
            product_name=product_name,
            product_type=product_type_enum,
            version=version,
            output_port_name=output_port_name
        )

        # Log audit event
        audit_manager.log_action(
            db=db,
            username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=DATA_PRODUCTS_FEATURE_ID,
            action='CREATE_FROM_CONTRACT',
            success=True,
            details={
                'product_id': created_product.id,
                'contract_id': contract_id,
                'product_name': product_name,
                'product_type': product_type
            }
        )

        logger.info(f"Created Data Product {created_product.id} from contract {contract_id}")
        return created_product

    except ValueError as e:
        logger.error("Validation error creating product from contract %s: %s", contract_id, e)
        raise HTTPException(status_code=400, detail="Invalid contract data for product creation")
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error creating product from contract {contract_id}")
        raise HTTPException(status_code=500, detail=f"Failed to create product from contract: {str(e)}")


@router.get('/data-products/by-contract/{contract_id}', response_model=List[DataProduct])
async def get_products_by_contract(
    contract_id: str,
    manager: DataProductsManager = Depends(get_data_products_manager),
    _: bool = Depends(PermissionChecker(DATA_PRODUCTS_FEATURE_ID, FeatureAccessLevel.READ_ONLY))
):
    """
    Get all Data Products that use a specific Data Contract.

    Returns products that have output ports linked to the specified contract.
    """
    try:
        products = manager.get_products_by_contract(contract_id)
        logger.info(f"Found {len(products)} products for contract {contract_id}")
        return products
    except Exception as e:
        logger.exception(f"Error getting products for contract {contract_id}")
        raise HTTPException(status_code=500, detail=f"Failed to get products for contract: {str(e)}")


@router.get('/data-products/{product_id}/contracts', response_model=List[str])
async def get_contracts_for_product(
    product_id: str,
    manager: DataProductsManager = Depends(get_data_products_manager),
    _: bool = Depends(PermissionChecker(DATA_PRODUCTS_FEATURE_ID, FeatureAccessLevel.READ_ONLY))
):
    """
    Get all Data Contract IDs associated with a Data Product's output ports.

    Returns a list of contract IDs (may be empty if no contracts are linked).
    """
    try:
        contract_ids = manager.get_contracts_for_product(product_id)
        logger.info(f"Found {len(contract_ids)} contracts for product {product_id}")
        return contract_ids
    except ValueError as e:
        logger.error("Product not found %s: %s", product_id, e)
        raise HTTPException(status_code=404, detail="Product not found")
    except Exception as e:
        logger.exception(f"Error getting contracts for product {product_id}")
        raise HTTPException(status_code=500, detail=f"Failed to get contracts for product: {str(e)}")

# --- Dataset Hierarchy Endpoints (Phase 5) ---

@router.get('/data-products/{product_id}/datasets')
async def get_product_datasets(
    product_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    background_tasks: BackgroundTasks,
    manager: DataProductsManager = Depends(get_data_products_manager),
    _: bool = Depends(PermissionChecker(DATA_PRODUCTS_FEATURE_ID, FeatureAccessLevel.READ_ONLY))
):
    """Get all Dataset assets linked to this Data Product via hasDataset relationships."""
    success = False
    details = {"product_id": product_id, "action": "get_product_datasets"}
    try:
        datasets = manager.get_product_datasets(product_id, db=db)
        success = True
        details["count"] = len(datasets)
        return datasets
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception(f"Error getting datasets for product {product_id}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        background_tasks.add_task(
            audit_manager.log_action_background,
            username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=DATA_PRODUCTS_FEATURE_ID,
            action="GET_PRODUCT_DATASETS",
            success=success,
            details=details,
        )


@router.get('/data-products/{product_id}/hierarchy')
async def get_product_hierarchy(
    product_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    background_tasks: BackgroundTasks,
    manager: DataProductsManager = Depends(get_data_products_manager),
    _: bool = Depends(PermissionChecker(DATA_PRODUCTS_FEATURE_ID, FeatureAccessLevel.READ_ONLY))
):
    """Get the full DP > Dataset > Table/View > Column hierarchy for a Data Product."""
    success = False
    details = {"product_id": product_id, "action": "get_product_hierarchy"}
    try:
        hierarchy = manager.get_product_hierarchy(product_id, db=db)
        success = True
        details["dataset_count"] = len(hierarchy.get("datasets", []))
        return hierarchy
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception(f"Error getting hierarchy for product {product_id}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        background_tasks.add_task(
            audit_manager.log_action_background,
            username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=DATA_PRODUCTS_FEATURE_ID,
            action="GET_PRODUCT_HIERARCHY",
            success=success,
            details=details,
        )


@router.get('/data-products/{product_id}/odps/export')
async def export_odps(
    product_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    background_tasks: BackgroundTasks,
    manager: DataProductsManager = Depends(get_data_products_manager),
    _: bool = Depends(PermissionChecker(DATA_PRODUCTS_FEATURE_ID, FeatureAccessLevel.READ_ONLY)),
):
    """Export a Data Product as ODPS v1.0.0 YAML, including entity relationship-based datasets."""
    from fastapi.responses import Response
    success = False
    details = {"product_id": product_id, "action": "export_odps"}
    try:
        odps = manager.build_odps_export(product_id, db=db)
        yaml_content = yaml.dump(odps, default_flow_style=False, allow_unicode=True, sort_keys=False)

        raw_name = (odps.get("name") or "product").lower().replace(" ", "_")
        safe_filename = f"{raw_name}-odps.yaml"
        success = True
        return Response(
            content=yaml_content,
            media_type="application/x-yaml",
            headers={
                "Content-Disposition": f'attachment; filename="{safe_filename}"',
                "Content-Type": "application/x-yaml; charset=utf-8",
            },
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception(f"Failed to export ODPS for product {product_id}")
        raise HTTPException(status_code=500, detail="Failed to export ODPS")
    finally:
        background_tasks.add_task(
            audit_manager.log_action_background,
            username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=DATA_PRODUCTS_FEATURE_ID,
            action="EXPORT_ODPS",
            success=success,
            details=details,
        )


@router.post('/data-products/{product_id}/datasets')
async def link_dataset_to_product(
    product_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    background_tasks: BackgroundTasks,
    body: Dict[str, str] = Body(...),
    manager: DataProductsManager = Depends(get_data_products_manager),
    _: bool = Depends(PermissionChecker(DATA_PRODUCTS_FEATURE_ID, FeatureAccessLevel.READ_WRITE))
):
    """Link a Dataset asset to this Data Product via hasDataset relationship.
    
    Body: { "dataset_id": "<uuid>" }
    """
    success = False
    dataset_id = body.get("dataset_id", "")
    details = {"product_id": product_id, "dataset_id": dataset_id, "action": "link_dataset"}
    try:
        if not dataset_id:
            raise HTTPException(status_code=422, detail="dataset_id is required")
        result = manager.link_dataset(product_id, dataset_id, current_user.username, db=db)
        success = True
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception(f"Error linking dataset {dataset_id} to product {product_id}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        background_tasks.add_task(
            audit_manager.log_action_background,
            username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=DATA_PRODUCTS_FEATURE_ID,
            action="LINK_DATASET",
            success=success,
            details=details,
        )


@router.delete('/data-products/{product_id}/datasets/{dataset_id}')
async def unlink_dataset_from_product(
    product_id: str,
    dataset_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    background_tasks: BackgroundTasks,
    manager: DataProductsManager = Depends(get_data_products_manager),
    _: bool = Depends(PermissionChecker(DATA_PRODUCTS_FEATURE_ID, FeatureAccessLevel.READ_WRITE))
):
    """Remove the hasDataset relationship between a Data Product and a Dataset."""
    success = False
    details = {"product_id": product_id, "dataset_id": dataset_id, "action": "unlink_dataset"}
    try:
        removed = manager.unlink_dataset(product_id, dataset_id, db=db)
        if not removed:
            raise HTTPException(status_code=404, detail="Relationship not found")
        success = True
        return {"status": "removed"}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error unlinking dataset {dataset_id} from product {product_id}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        background_tasks.add_task(
            audit_manager.log_action_background,
            username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=DATA_PRODUCTS_FEATURE_ID,
            action="UNLINK_DATASET",
            success=success,
            details=details,
        )


# --- Utility Endpoints ---

@router.get('/data-products/statuses', response_model=List[str])
async def get_data_product_statuses(
    manager: DataProductsManager = Depends(get_data_products_manager),
    _: bool = Depends(PermissionChecker(DATA_PRODUCTS_FEATURE_ID, FeatureAccessLevel.READ_ONLY))
):
    try:
        statuses = manager.get_distinct_statuses()
        logger.info(f"Retrieved {len(statuses)} distinct data product statuses")
        return statuses
    except Exception as e:
        error_msg = f"Error retrieving data product statuses: {e!s}"
        logger.error(error_msg)
        raise HTTPException(status_code=500, detail=error_msg)

@router.get('/data-products/types', response_model=List[str])
async def get_data_product_types(
    manager: DataProductsManager = Depends(get_data_products_manager),
    _: bool = Depends(PermissionChecker(DATA_PRODUCTS_FEATURE_ID, FeatureAccessLevel.READ_ONLY))
):
    try:
        types = manager.get_distinct_product_types()
        logger.info(f"Retrieved {len(types)} distinct data product types")
        return types
    except Exception as e:
        error_msg = f"Error retrieving data product types: {e!s}"
        logger.error(error_msg)
        raise HTTPException(status_code=500, detail=error_msg)

@router.get('/data-products/owners', response_model=List[str])
async def get_data_product_owners(
    manager: DataProductsManager = Depends(get_data_products_manager),
    _: bool = Depends(PermissionChecker(DATA_PRODUCTS_FEATURE_ID, FeatureAccessLevel.READ_ONLY))
):
    try:
        owners = manager.get_distinct_owners()
        logger.info(f"Retrieved {len(owners)} distinct data product owners")
        return owners
    except Exception as e:
        error_msg = f"Error retrieving data product owners: {e!s}"
        logger.error(error_msg)
        raise HTTPException(status_code=500, detail=error_msg)

@router.get('/data-products/published', response_model=List[DataProduct])
async def get_published_products(
    scope: Optional[str] = Query(
        None,
        description="Filter by publication scope: domain, organization, external",
    ),
    manager: DataProductsManager = Depends(get_data_products_manager),
    _: bool = Depends(PermissionChecker(DATA_PRODUCTS_FEATURE_ID, FeatureAccessLevel.READ_ONLY))
):
    """
    Get data products published to the marketplace (publication_scope other than none).

    Optional ``scope`` narrows results to a single publication scope (case-insensitive).
    """
    try:
        published_products = manager.get_published_products(limit=10000, scope=scope)
        logger.info(
            f"Retrieved {len(published_products)} published data products (scope={scope or 'all'})"
        )
        return published_products
    except Exception as e:
        error_msg = f"Error retrieving published data products: {e!s}"
        logger.error(error_msg)
        raise HTTPException(status_code=500, detail=error_msg)


# NOTE: Static routes must be defined BEFORE dynamic {product_id} routes
@router.get('/data-products/my-subscriptions', response_model=List[DataProduct])
async def get_my_subscriptions(
    db: DBSessionDep,
    current_user: CurrentUserDep,
    manager: DataProductsManager = Depends(get_data_products_manager),
    skip: int = 0,
    limit: int = 100
):
    """Get all data products the current user is subscribed to."""
    if not current_user or not current_user.username:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    return manager.get_user_subscriptions(
        subscriber_email=current_user.username,
        skip=skip,
        limit=limit,
        db=db
    )


@router.post("/data-products/upload", response_model=List[DataProduct], status_code=201)
async def upload_data_products(
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    file: UploadFile = File(...),
    manager: DataProductsManager = Depends(get_data_products_manager),
    _: bool = Depends(PermissionChecker(DATA_PRODUCTS_FEATURE_ID, FeatureAccessLevel.READ_WRITE))
):
    # SECURITY: Sanitize filename for safe logging and validation
    raw_filename = file.filename or "upload.bin"
    safe_filename = sanitize_filename(raw_filename, default="upload.bin")
    
    # Validate file extension using sanitized filename
    if not (safe_filename.lower().endswith('.yaml') or safe_filename.lower().endswith('.json')):
        audit_manager.log_action(
            db=db,
            username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=DATA_PRODUCTS_FEATURE_ID,
            action="UPLOAD_BATCH",
            success=False,
            details={
                "filename": safe_filename,
                "error": "Invalid file type",
                "params": { "filename_in_request": safe_filename },
                "response_status_code": 400
            }
        )
        raise HTTPException(status_code=400, detail="Invalid file type. Please upload a YAML or JSON file.")

    # Tracking for audit
    success = False
    response_status_code = 500
    created_products_for_response: List[DataProduct] = []
    processing_errors_for_audit: List[Dict[str, Any]] = []
    created_ids_for_audit: List[str] = []

    details_for_audit = {
        "filename": safe_filename,
        "params": { "filename_in_request": safe_filename },
    }

    try:
        # Read file content
        # Read file content
        content = await file.read()
        if safe_filename.lower().endswith('.yaml'):
            data = yaml.safe_load(content)
        else:
            import json
            data = json.loads(content)
            
        data_list: List[Dict[str, Any]]
        if isinstance(data, dict):
            data_list = [data]
        elif isinstance(data, list):
            data_list = data
        else:
            response_status_code = 400
            exc = HTTPException(status_code=response_status_code, detail="File must contain a JSON object/array or a YAML mapping/list of data product objects.")
            details_for_audit["exception"] = {"type": "HTTPException", "status_code": exc.status_code, "detail": exc.detail}
            raise exc

        # Delegate to manager
        created_products, errors_list = manager.upload_products_batch(content, file.filename)

        # Extract created IDs for audit
        created_ids = [p.id for p in created_products if p and hasattr(p, 'id')]

        # Determine response status
        if errors_list:
            if created_products:
                # Partial success
                success = True
                response_status_code = 422
                logger.warning(
                    f"Partial success: {len(created_products)} created, "
                    f"{len(errors_list)} errors from file {file.filename}"
                )
                raise HTTPException(
                    status_code=response_status_code,
                    detail={
                        "message": "Validation or creation errors occurred during upload.",
                        "errors": errors_list,
                        "created_count": len(created_products)
                    }
                )
            else:
                # Total failure
                success = False
                response_status_code = 422
                raise HTTPException(
                    status_code=response_status_code,
                    detail={
                        "message": "All items failed validation or creation.",
                        "errors": errors_list
                    }
                )

        # Complete success
        success = True
        response_status_code = 201
        logger.info(f"Successfully created {len(created_products)} data products from uploaded file {safe_filename}")
        return created_products

    except ValueError as e:
        # File parsing or format errors
        success = False
        response_status_code = 400
        details_for_audit["exception"] = {"type": "ValueError", "message": str(e)}
        logger.error(f"File processing error for {file.filename}: {e}")
        raise HTTPException(status_code=response_status_code, detail=str(e))
    except HTTPException:
        # Re-raise HTTP exceptions (from partial success handling above)
        raise
    except Exception as e:
        # Unexpected errors
        success = False
        response_status_code = 500
        error_msg = f"Unexpected error processing uploaded file: {e!s}"
        details_for_audit["exception"] = {"type": type(e).__name__, "message": str(e)}
        logger.exception(error_msg)
        raise HTTPException(status_code=response_status_code, detail=error_msg)
    finally:
        # Audit logging
        details_for_audit["response_status_code"] = response_status_code
        if created_ids:
            details_for_audit["created_resource_ids"] = created_ids
        if errors_list:
            details_for_audit["item_processing_errors"] = errors_list

        audit_manager.log_action(
            db=db,
            username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=DATA_PRODUCTS_FEATURE_ID,
            action="UPLOAD_BATCH",
            success=success,
            details=details_for_audit,
        )

@router.get('/data-products', response_model=Any)
async def get_data_products(
    project_id: Optional[str] = None,
    current_user: CurrentUserDep = None,
    manager: DataProductsManager = Depends(get_data_products_manager),
    _: bool = Depends(PermissionChecker(DATA_PRODUCTS_FEATURE_ID, FeatureAccessLevel.READ_ONLY))
):
    try:
        logger.info(f"Retrieving data products via get_data_products route (project_id: {project_id})...")

        # Check if user is admin
        from src.common.authorization import is_user_admin
        from src.common.config import get_settings
        settings = get_settings()
        user_groups = current_user.groups if current_user else []
        is_admin = is_user_admin(user_groups, settings)

        logger.info(f"User {current_user.email if current_user else 'unknown'} is_admin: {is_admin}")

        products = manager.list_products(project_id=project_id, is_admin=is_admin)
        logger.info(f"Retrieved {len(products)} data products")
        return [p.model_dump() for p in products]
    except Exception as e:
        error_msg = f"Error retrieving data products: {e!s}"
        logger.exception(error_msg)
        raise HTTPException(status_code=500, detail=error_msg)

@router.post('/data-products', response_model=DataProduct, status_code=201)
async def create_data_product(
    request: Request,
    background_tasks: BackgroundTasks,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    payload: Dict[str, Any] = Body(...),
    manager: DataProductsManager = Depends(get_data_products_manager),
    _: bool = Depends(PermissionChecker(DATA_PRODUCTS_FEATURE_ID, FeatureAccessLevel.READ_WRITE))
):
    success = False
    details_for_audit = {
        "params": {"product_id_in_payload": payload.get('id', 'N/A_PreCreate')},
    }
    created_product_response = None

    try:
        logger.info(f"Received raw payload for creation: {payload}")

        # create_product() always generates a UUID for the ID and preserves
        # any non-UUID original id as a sourceId custom property.
        # Pre-validate with a placeholder UUID so we return 422 early for bad payloads.
        try:
            validation_payload = {**payload, 'id': str(uuid.uuid4())}
            validated_model = DataProduct(**validation_payload)
        except ValidationError as e:
            logger.error(f"Validation failed for payload (ID: {payload.get('id', 'N/A_Validation')}): {e}")
            error_details = e.errors() if hasattr(e, 'errors') else str(e)
            details_for_audit["validation_error"] = error_details
            raise HTTPException(status_code=422, detail=error_details)

        # Validate project access if project_id is provided
        project_id = payload.get('project_id')
        if project_id:
            from src.controller.projects_manager import projects_manager
            from src.common.config import get_settings
            user_groups = current_user.groups or []
            settings = get_settings()
            is_member = projects_manager.is_user_project_member(
                db=db,
                user_identifier=current_user.email,
                user_groups=user_groups,
                project_id=project_id,
                settings=settings
            )
            if not is_member:
                raise HTTPException(
                    status_code=403, 
                    detail="You must be a member of the project to create a product in it"
                )

        created_product_response = manager.create_product(payload, db=db, user=current_user.username if current_user else None)
        success = True

        if created_product_response and hasattr(created_product_response, 'id'):
            details_for_audit["created_resource_id"] = str(created_product_response.id)

        logger.info(f"Successfully created data product with ID: {created_product_response.id if created_product_response else payload.get('id')}")
        return created_product_response

    except HTTPException as http_exc:
        details_for_audit["exception"] = {"type": "HTTPException", "status_code": http_exc.status_code, "detail": http_exc.detail}
        raise
    except Exception as e:
        error_msg = f"Unexpected error creating data product (ID: {payload.get('id', 'N/A_Exception')}): {e!s}"
        logger.exception(error_msg)
        details_for_audit["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise HTTPException(status_code=500, detail=error_msg)
    finally:
        background_tasks.add_task(
            audit_manager.log_action_background,
            username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=DATA_PRODUCTS_FEATURE_ID,
            action="CREATE",
            success=success,
            details=details_for_audit.copy()
        )

@router.post("/data-products/{product_id}/versions", response_model=DataProduct, status_code=201)
async def create_data_product_version(
    product_id: str, # This is the original product ID
    request: Request, 
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    version_request: NewVersionRequest = Body(...), # Ensure Body is used if it was intended
    manager: DataProductsManager = Depends(get_data_products_manager),
    _: bool = Depends(PermissionChecker(DATA_PRODUCTS_FEATURE_ID, FeatureAccessLevel.READ_WRITE))
):
    success = False
    response_status_code = 500
    details_for_audit = {
        "params": {"original_product_id": product_id, "requested_new_version": version_request.new_version},
    }
    new_product_response = None

    try:
        logger.info(f"Received request to create version '{version_request.new_version}' from product ID: {product_id}")
        # The manager method handles its own DB interactions
        new_product_response = manager.create_new_version(product_id, version_request)
        
        # request.state.audit_created_resource_id is no longer needed here as we capture it below
        
        success = True
        response_status_code = 201
        logger.info(f"Successfully created new version ID: {new_product_response.id} from original product ID: {product_id}")
        return new_product_response

    except ValueError as ve:
        success = False
        # Determine status code based on error message content, or default to 400/404
        response_status_code = 404 if "not found" in str(ve).lower() else 400
        details_for_audit["exception"] = {"type": "ValueError", "status_code": response_status_code, "message": str(ve)}
        logger.error(f"Value error creating version for {product_id}: {ve!s}")
        raise HTTPException(status_code=response_status_code, detail=str(ve))
    except HTTPException as http_exc: # Should come after more specific exceptions if they might raise HTTPExceptions
        success = False
        response_status_code = http_exc.status_code
        details_for_audit["exception"] = {"type": "HTTPException", "status_code": http_exc.status_code, "detail": http_exc.detail}
        raise
    except Exception as e:
        success = False
        response_status_code = 500
        error_msg = f"Unexpected error creating version for data product {product_id}: {e!s}"
        details_for_audit["exception"] = {"type": type(e).__name__, "message": str(e)}
        logger.exception(error_msg)
        raise HTTPException(status_code=response_status_code, detail=error_msg)
    finally:
        if "exception" not in details_for_audit:
             details_for_audit["response_status_code"] = response_status_code
        
        if success and new_product_response and hasattr(new_product_response, 'id'):
            details_for_audit["created_version_id"] = str(new_product_response.id)
        
        audit_manager.log_action(
            db=db,
            username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=DATA_PRODUCTS_FEATURE_ID,
            action="CREATE_VERSION", # Specific action type
            success=success,
            details=details_for_audit,
        )

@router.post('/data-products/compare', response_model=dict)
async def compare_product_versions(
    body: dict = Body(...),
    manager: DataProductsManager = Depends(get_data_products_manager),
    _: bool = Depends(PermissionChecker(DATA_PRODUCTS_FEATURE_ID, FeatureAccessLevel.READ_ONLY))
):
    """Analyze changes between two product versions and recommend version bump."""
    old_product = body.get('old_product')
    new_product = body.get('new_product')

    if not old_product or not new_product:
        raise HTTPException(status_code=400, detail="Both old_product and new_product are required")

    try:
        # Business logic now in manager
        return manager.compare_products(
            old_product=old_product,
            new_product=new_product
        )
    except ValueError as e:
        logger.error("Validation error comparing products: %s", e)
        raise HTTPException(status_code=400, detail="Invalid product data")
    except Exception as e:
        logger.error("Error comparing products", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to compare products")

@router.put('/data-products/{product_id}', response_model=DataProduct)
async def update_data_product(
    product_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    background_tasks: BackgroundTasks,
    manager: DataProductsManager = Depends(get_data_products_manager),
    _: bool = Depends(PermissionChecker(DATA_PRODUCTS_FEATURE_ID, FeatureAccessLevel.READ_WRITE))
):
    """
    Update a data product with project membership authorization.

    Validates that users can only update products belonging to projects
    they are members of (if the product has a project_id).
    """
    # Parse and validate JSON body
    """
    Update a data product with project membership authorization.

    Validates that users can only update products belonging to projects
    they are members of (if the product has a project_id).
    """
    # Parse and validate JSON body
    try:
        body_dict = await request.json()
        logger.info(f"Received raw payload for update (ID: {product_id}): {body_dict}")
        product_update = DataProduct(**body_dict)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON body.")
    except ValidationError as e:
        logger.error(f"Validation failed for PUT request body (ID: {product_id}): {e}")
        raise HTTPException(status_code=422, detail=e.errors())

    # Validate path ID matches body ID
    if product_id != product_update.id:
        audit_manager.log_action(
            db=db,
            username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=DATA_PRODUCTS_FEATURE_ID,
            action="UPDATE",
            success=False,
            details={"error": "ID mismatch", "product_id": product_id}
        )
        raise HTTPException(status_code=400, detail="Product ID in path does not match ID in request body.")

    # Tracking for audit
    success = False
    response_status_code = 500
    details_for_audit = {"params": {"product_id": product_id}}
    updated_product_response = None

    try:
        logger.info(f"Updating data product ID: {product_id}")

        # Check if versioning is required for non-draft products
        current_product_db = manager.get_product(product_id)
        if current_product_db and current_product_db.status and current_product_db.status.lower() != 'draft':
            # Check if caller explicitly forced the update
            force_update = request.headers.get('X-Force-Update') == 'true'
            
            if not force_update:
                # Analyze the impact of proposed changes
                product_dict = product_update.model_dump(by_alias=True)
                impact_analysis = manager.analyze_update_impact(
                    product_id=product_id,
                    proposed_changes=product_dict,
                    db=db
                )
                
                # Check if user is admin
                from src.common.authorization import is_user_admin
                from src.common.config import get_settings
                settings = get_settings()
                user_is_admin = is_user_admin(current_user.groups, settings)
                
                if impact_analysis['requires_versioning']:
                    # If breaking changes and not admin, force new version
                    if not user_is_admin:
                        raise HTTPException(
                            status_code=409,
                            detail={
                                "message": "Breaking changes detected - new version required",
                                "requires_versioning": True,
                                "change_analysis": impact_analysis['change_analysis'],
                                "user_can_override": False,
                                "recommended_action": "clone"
                            }
                        )
                    else:
                        # Admin can choose - return recommendation
                        raise HTTPException(
                            status_code=409,
                            detail={
                                "message": "Breaking changes detected - recommend new version",
                                "requires_versioning": True,
                                "change_analysis": impact_analysis['change_analysis'],
                                "user_can_override": True,
                                "recommended_action": "clone"
                            }
                        )

        # Delegate to manager (includes auth check)
        user_groups = current_user.groups or []
        product_dict = product_update.model_dump()

        updated_product_response = manager.update_product_with_auth(
            product_id=product_id,
            product_data_dict=product_dict,
            user_email=current_user.email,
            user_groups=user_groups,
            db=db,
            background_tasks=background_tasks,
        )

        if not updated_product_response:
            response_status_code = 404
            raise HTTPException(status_code=404, detail="Data product not found")

        success = True
        response_status_code = 200
        logger.info(f"Successfully updated data product with ID: {product_id}")
        
        # Delivery is now handled in the manager via DeliveryMixin
        
        return updated_product_response

    except PermissionError as e:
        # Project membership check failed
        success = False
        response_status_code = 403
        details_for_audit["exception"] = {"type": "PermissionError", "message": str(e)}
        logger.warning(f"Permission denied updating product {product_id}: {e}")
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        # Validation errors from manager
        success = False
        response_status_code = 400
        details_for_audit["exception"] = {"type": "ValueError", "message": str(e)}
        logger.error(f"Validation error updating product {product_id}: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        # Unexpected errors
        success = False
        response_status_code = 500
        error_msg = f"Unexpected error updating data product {product_id}: {e!s}"
        details_for_audit["exception"] = {"type": type(e).__name__, "message": str(e)}
        logger.exception(error_msg)
        raise HTTPException(status_code=500, detail=error_msg)
    finally:
        # Audit logging
        details_for_audit["response_status_code"] = response_status_code
        if success and updated_product_response and hasattr(updated_product_response, 'id'):
            details_for_audit["updated_resource_id"] = str(updated_product_response.id)

        background_tasks.add_task(
            audit_manager.log_action_background,
            username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=DATA_PRODUCTS_FEATURE_ID,
            action="UPDATE",
            success=success,
            details=details_for_audit.copy()
        )

@router.delete('/data-products/{product_id}', status_code=204) 
async def delete_data_product(
    product_id: str,
    request: Request, 
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager: DataProductsManager = Depends(get_data_products_manager),
    _: bool = Depends(PermissionChecker(DATA_PRODUCTS_FEATURE_ID, FeatureAccessLevel.ADMIN))
):
    success = False
    response_status_code = 500 # Default for audit in case of unexpected server error
    details_for_audit = {
        "params": {"product_id": product_id},
        # For delete, body_preview is not applicable from route args
    }

    try:
        logger.info(f"Received request to delete data product ID: {product_id}")
        deleted = manager.delete_product(product_id, user=current_user.username if current_user else None)
        if not deleted:
            response_status_code = 404
            exc = HTTPException(status_code=response_status_code, detail="Data product not found")
            details_for_audit["exception"] = {"type": "HTTPException", "status_code": exc.status_code, "detail": exc.detail}
            logger.warning(f"Deletion failed: Data product not found with ID: {product_id}")
            raise exc

        success = True
        response_status_code = 204 # Standard for successful DELETE
        logger.info(f"Successfully deleted data product with ID: {product_id}")
        # No response body for 204, so no updated_product_response or response_preview
        return None 

    except HTTPException as http_exc:
        success = False
        response_status_code = http_exc.status_code
        details_for_audit["exception"] = {"type": "HTTPException", "status_code": http_exc.status_code, "detail": http_exc.detail}
        raise
    except Exception as e:
        success = False
        response_status_code = 500 
        error_msg = f"Unexpected error deleting data product {product_id}: {e!s}"
        details_for_audit["exception"] = {"type": type(e).__name__, "message": str(e)}
        logger.exception(error_msg)
        raise HTTPException(status_code=response_status_code, detail=error_msg)
    finally:
        if "exception" not in details_for_audit:
             details_for_audit["response_status_code"] = response_status_code
        
        # For delete, we can confirm the ID of the resource that was targeted for deletion.
        details_for_audit["deleted_resource_id_attempted"] = product_id

        audit_manager.log_action(
            db=db,
            username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=DATA_PRODUCTS_FEATURE_ID,
            action="DELETE",
            success=success,
            details=details_for_audit,
        )

@router.get('/data-products/{product_id}', response_model=Any)
async def get_data_product(
    product_id: str,
    manager: DataProductsManager = Depends(get_data_products_manager),
    _: bool = Depends(PermissionChecker(DATA_PRODUCTS_FEATURE_ID, FeatureAccessLevel.READ_ONLY))
) -> Any: # Return Any to allow returning a dict
    try:
        product = manager.get_product(product_id)
        if not product:
            raise HTTPException(status_code=404, detail="Data product not found")
        return product.model_dump(by_alias=False, exclude={'created_at', 'updated_at'}, exclude_none=True, exclude_unset=True)
    except ValueError as e:
        logger.error("Validation error fetching product %s: %s", product_id, e)
        raise HTTPException(status_code=404, detail="Data product not found")
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Unexpected error fetching product {product_id}")
        raise HTTPException(status_code=500, detail="Internal server error")

@router.post("/data-products/genie-space", status_code=202)
async def create_genie_space_from_products(
    request_body: GenieSpaceRequest,
    current_user: CurrentUserDep, # Moved up, no default value
    db: DBSessionDep, # Inject the database session
    manager: DataProductsManager = Depends(get_data_products_manager), # Has default
    _: bool = Depends(PermissionChecker(DATA_PRODUCTS_FEATURE_ID, FeatureAccessLevel.READ_WRITE)) # Has default
):
    if not request_body.product_ids:
        raise HTTPException(status_code=400, detail="No product IDs provided.")

    try:
        await manager.initiate_genie_space_creation(request_body, current_user, db=db)
        return {"message": "Genie Space creation process initiated. You will be notified upon completion."}
    except RuntimeError as e:
        logger.error("Runtime error initiating Genie Space creation", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to initiate Genie Space creation")
    except Exception as e:
        logger.error(f"Unexpected error initiating Genie Space creation: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to initiate Genie Space creation.")

@router.get('/data-products/{product_id}/import-team-members', response_model=list)
async def get_team_members_for_import(
    product_id: str,
    team_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager: DataProductsManager = Depends(get_data_products_manager),
    _: bool = Depends(PermissionChecker(DATA_PRODUCTS_FEATURE_ID, FeatureAccessLevel.READ_WRITE))
):
    """Get team members formatted for import into product ODPS team array.
    
    Route handler: parses parameters, audits request, delegates to manager, returns response.
    All business logic is in the manager.
    """
    success = False
    members = []
    try:
        # Delegate business logic to manager
        members = manager.get_team_members_for_import(
            product_id=product_id,
            team_id=team_id,
            current_user=current_user.username if current_user else None
        )
        
        success = True
        return members
        
    except ValueError as e:
        logger.error("Validation error fetching team members for product %s: %s", product_id, e)
        raise HTTPException(status_code=404, detail="Product or team not found")
    except Exception as e:
        logger.error("Error fetching team members for import for product %s", product_id, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch team members for import")
    finally:
        # Audit the action
        audit_manager.log_action(
            db=db,
            username=current_user.username if current_user else 'anonymous',
            ip_address=request.client.host if request.client else None,
            feature=DATA_PRODUCTS_FEATURE_ID,
            action='GET_TEAM_MEMBERS_FOR_IMPORT',
            success=success,
            details={"product_id": product_id, "team_id": team_id, "member_count": len(members)}
        )

# ==================== Subscription Endpoints ====================

@router.post('/data-products/{product_id}/subscribe', response_model=SubscriptionResponse)
async def subscribe_to_product(
    product_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    subscription_data: Optional[SubscriptionCreate] = Body(default=None),
    manager: DataProductsManager = Depends(get_data_products_manager)
):
    """Subscribe the current user to a data product.
    
    Users can subscribe to active or certified products to receive notifications
    about status changes, compliance violations, and new versions.
    """
    success = False
    try:
        if not current_user or not current_user.username:
            raise HTTPException(status_code=401, detail="Authentication required")
        
        reason = subscription_data.reason if subscription_data else None
        result = manager.subscribe(
            product_id=product_id,
            subscriber_email=current_user.username,
            reason=reason,
            db=db
        )
        
        success = True
        return result
        
    except ValueError as e:
        logger.error("Validation error subscribing to product %s: %s", product_id, e)
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("Error subscribing to product %s: %s", product_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to subscribe to product")
    finally:
        audit_manager.log_action(
            db=db,
            username=current_user.username if current_user else 'anonymous',
            ip_address=request.client.host if request.client else None,
            feature=DATA_PRODUCTS_FEATURE_ID,
            action='SUBSCRIBE',
            success=success,
            details={"product_id": product_id}
        )


@router.delete('/data-products/{product_id}/subscribe', response_model=SubscriptionResponse)
async def unsubscribe_from_product(
    product_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager: DataProductsManager = Depends(get_data_products_manager)
):
    """Unsubscribe the current user from a data product."""
    success = False
    try:
        if not current_user or not current_user.username:
            raise HTTPException(status_code=401, detail="Authentication required")
        
        result = manager.unsubscribe(
            product_id=product_id,
            subscriber_email=current_user.username,
            db=db
        )
        
        success = True
        return result
        
    except Exception as e:
        logger.error("Error unsubscribing from product %s: %s", product_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to unsubscribe from product")
    finally:
        audit_manager.log_action(
            db=db,
            username=current_user.username if current_user else 'anonymous',
            ip_address=request.client.host if request.client else None,
            feature=DATA_PRODUCTS_FEATURE_ID,
            action='UNSUBSCRIBE',
            success=success,
            details={"product_id": product_id}
        )


@router.get('/data-products/{product_id}/subscription', response_model=SubscriptionResponse)
async def get_subscription_status(
    product_id: str,
    db: DBSessionDep,
    current_user: CurrentUserDep,
    manager: DataProductsManager = Depends(get_data_products_manager)
):
    """Check if the current user is subscribed to a data product."""
    if not current_user or not current_user.username:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    return manager.get_subscription_status(
        product_id=product_id,
        subscriber_email=current_user.username,
        db=db
    )


@router.get('/data-products/{product_id}/subscribers', response_model=SubscribersListResponse)
async def get_product_subscribers(
    product_id: str,
    db: DBSessionDep,
    current_user: CurrentUserDep,
    manager: DataProductsManager = Depends(get_data_products_manager),
    skip: int = 0,
    limit: int = 100,
    _: bool = Depends(PermissionChecker(DATA_PRODUCTS_FEATURE_ID, FeatureAccessLevel.READ_WRITE))
):
    """Get all subscribers for a data product.
    
    Only product owners and administrators can view the full subscriber list.
    """
    return manager.get_subscribers(
        product_id=product_id,
        skip=skip,
        limit=limit,
        db=db
    )


@router.get('/data-products/{product_id}/subscriber-count')
async def get_subscriber_count(
    product_id: str,
    db: DBSessionDep,
    manager: DataProductsManager = Depends(get_data_products_manager)
):
    """Get the number of subscribers for a data product."""
    count = manager.get_subscriber_count(product_id=product_id, db=db)
    return {"product_id": product_id, "subscriber_count": count}


# ==================== Versioned Editing Endpoints ====================

@router.post('/data-products/{product_id}/clone-for-editing', response_model=DataProduct)
async def clone_product_for_editing(
    product_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager: DataProductsManager = Depends(get_data_products_manager),
    _: bool = Depends(PermissionChecker(DATA_PRODUCTS_FEATURE_ID, FeatureAccessLevel.READ_WRITE))
):
    """Clone a product to create a personal draft for editing.
    
    Creates a copy of the product as a personal draft visible only to the owner.
    Use this when editing a product that is active or above status.
    """
    try:
        new_product = manager.clone_product_for_editing(
            db=db,
            product_id=product_id,
            current_user=current_user.username
        )
        
        audit_manager.log_action(
            db=db,
            username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=DATA_PRODUCTS_FEATURE_ID,
            action='CLONE_FOR_EDITING',
            success=True,
            details={'product_id': product_id, 'new_product_id': new_product.id}
        )
        return new_product
        
    except ValueError as e:
        logger.error(f"Error cloning product {product_id} for editing: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error cloning product {product_id} for editing: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to clone product for editing")


@router.get('/data-products/{product_id}/diff-from-parent', response_model=DiffFromParentResponse)
async def get_diff_from_parent(
    product_id: str,
    db: DBSessionDep,
    current_user: CurrentUserDep,
    manager: DataProductsManager = Depends(get_data_products_manager),
    _: bool = Depends(PermissionChecker(DATA_PRODUCTS_FEATURE_ID, FeatureAccessLevel.READ_ONLY))
):
    """Compare a draft product to its parent and suggest a version bump.
    
    Returns diff analysis with suggested semantic version bump.
    """
    try:
        diff_data = manager.get_diff_from_parent(db=db, product_id=product_id)
        return diff_data
        
    except ValueError as e:
        logger.error(f"Error getting diff for product {product_id}: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error getting diff for product {product_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get diff from parent")


@router.post('/data-products/{product_id}/commit', response_model=CommitDraftResponse)
async def commit_personal_draft(
    product_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    payload: CommitDraftRequest = Body(...),
    manager: DataProductsManager = Depends(get_data_products_manager),
    _: bool = Depends(PermissionChecker(DATA_PRODUCTS_FEATURE_ID, FeatureAccessLevel.READ_WRITE))
):
    """Commit a personal draft as a new team-visible version.
    
    Promotes the personal draft from tier 1 (only owner) to tier 2 (team/project).
    The product is NOT published to the marketplace - that's a separate action.
    """
    try:
        committed_product = manager.commit_personal_draft(
            db=db,
            draft_id=product_id,
            new_version=payload.new_version,
            change_summary=payload.change_summary,
            current_user=current_user.username
        )
        
        audit_manager.log_action(
            db=db,
            username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=DATA_PRODUCTS_FEATURE_ID,
            action='COMMIT_DRAFT',
            success=True,
            details={'product_id': product_id, 'new_version': payload.new_version}
        )
        return CommitDraftResponse(
            id=committed_product.id,
            name=committed_product.name,
            version=committed_product.version,
            status=committed_product.status,
            draft_owner_id=committed_product.draft_owner_id
        )
        
    except ValueError as e:
        logger.error(f"Error committing draft {product_id}: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except PermissionError as e:
        logger.error(f"Permission error committing draft {product_id}: {e}")
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        logger.error(f"Error committing draft {product_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to commit draft")


@router.delete('/data-products/{product_id}/discard')
async def discard_personal_draft(
    product_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager: DataProductsManager = Depends(get_data_products_manager),
    _: bool = Depends(PermissionChecker(DATA_PRODUCTS_FEATURE_ID, FeatureAccessLevel.READ_WRITE))
):
    """Discard (delete) a personal draft.
    
    Only the owner of the draft can discard it.
    """
    try:
        manager.discard_personal_draft(
            db=db,
            draft_id=product_id,
            current_user=current_user.username
        )
        
        audit_manager.log_action(
            db=db,
            username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=DATA_PRODUCTS_FEATURE_ID,
            action='DISCARD_DRAFT',
            success=True,
            details={'product_id': product_id}
        )
        return {"message": "Draft discarded successfully"}
        
    except ValueError as e:
        logger.error(f"Error discarding draft {product_id}: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        logger.error(f"Permission error discarding draft {product_id}: {e}")
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        logger.error(f"Error discarding draft {product_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to discard draft")


# ==================== Status Change Endpoints ====================

@router.post('/data-products/{product_id}/change-status')
async def change_product_status(
    product_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    payload: ChangeStatusPayload = Body(...),
    manager: DataProductsManager = Depends(get_data_products_manager),
    _: bool = Depends(PermissionChecker(DATA_PRODUCTS_FEATURE_ID, FeatureAccessLevel.READ_WRITE))
):
    """Directly change product status (for admin/owner).
    
    Use this for direct status changes without approval workflow.
    """
    try:
        updated_product = manager.transition_status(
            product_id=product_id,
            new_status=payload.new_status,
            current_user=current_user.username
        )
        
        audit_manager.log_action(
            db=db,
            username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=DATA_PRODUCTS_FEATURE_ID,
            action='CHANGE_STATUS',
            success=True,
            details={'product_id': product_id, 'new_status': payload.new_status}
        )
        return {"message": f"Status changed to {payload.new_status}", "product": updated_product}
        
    except ValueError as e:
        logger.error(f"Error changing status for product {product_id}: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error changing status for product {product_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to change status")


@router.post('/data-products/{product_id}/request-status-change')
async def request_status_change(
    product_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    notifications: NotificationsManagerDep,
    payload: RequestStatusChangePayload = Body(...),
    manager: DataProductsManager = Depends(get_data_products_manager),
    _: bool = Depends(PermissionChecker(DATA_PRODUCTS_FEATURE_ID, FeatureAccessLevel.READ_ONLY))
):
    """Request a status change for a product (requires approval).
    
    Creates a request that admins can approve/deny.
    """
    try:
        result = manager.request_status_change(
            db=db,
            notifications_manager=notifications,
            product_id=product_id,
            target_status=payload.target_status,
            justification=payload.justification,
            requester_email=current_user.username,
            current_user=current_user.username
        )
        
        audit_manager.log_action(
            db=db,
            username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=DATA_PRODUCTS_FEATURE_ID,
            action='REQUEST_STATUS_CHANGE',
            success=True,
            details={'product_id': product_id, 'target_status': payload.target_status}
        )
        return result
        
    except ValueError as e:
        logger.error(f"Request status change validation error for product {product_id}: {e}")
        error_status = 404 if "not found" in str(e).lower() else 400
        raise HTTPException(status_code=error_status, detail=str(e))
    except Exception as e:
        logger.error(f"Request status change failed for product {product_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to request status change")


@router.post('/data-products/{product_id}/handle-status-change')
async def handle_status_change_response(
    product_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    notifications: NotificationsManagerDep,
    payload: HandleStatusChangePayload = Body(...),
    manager: DataProductsManager = Depends(get_data_products_manager),
    _: bool = Depends(PermissionChecker(DATA_PRODUCTS_FEATURE_ID, FeatureAccessLevel.READ_WRITE))
):
    """Handle a status change request decision (approve/deny/clarify).
    
    Only admins/owners can approve or deny status change requests.
    """
    try:
        result = manager.handle_status_change_response(
            db=db,
            notifications_manager=notifications,
            product_id=product_id,
            approver_email=current_user.username,
            decision=payload.decision,
            target_status=payload.target_status,
            message=payload.message,
            current_user=current_user.username
        )
        
        audit_manager.log_action(
            db=db,
            username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=DATA_PRODUCTS_FEATURE_ID,
            action=f'STATUS_CHANGE_{payload.decision.upper()}',
            success=True,
            details={'product_id': product_id, 'decision': payload.decision, 'target_status': payload.target_status}
        )
        return result
        
    except ValueError as e:
        logger.error(f"Handle status change validation error for product {product_id}: {e}")
        error_status = 404 if "not found" in str(e).lower() else 400
        raise HTTPException(status_code=error_status, detail=str(e))
    except Exception as e:
        logger.error(f"Handle status change failed for product {product_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to handle status change")


def register_routes(app):
    app.include_router(router)
    logger.info("Data product routes registered")
