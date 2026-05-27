import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List
from uuid import uuid4

from fastapi import APIRouter, File, HTTPException, UploadFile, Depends, Request, Body, Query, BackgroundTasks
from fastapi.responses import JSONResponse

from src.controller.data_contracts_manager import DataContractsManager
from src.common.dependencies import (
    DBSessionDep,
    AuditManagerDep,
    CurrentUserDep,
    AuditCurrentUserDep,
    NotificationsManagerDep,
)
from src.repositories.data_contracts_repository import data_contract_repo
from src.db_models.data_contracts import (
    DataContractDb,
    DataContractCommentDb,
    DataContractTagDb,
    DataContractRoleDb,
    SchemaObjectDb,
    SchemaPropertyDb,
    DataContractTeamDb,
    DataContractSupportDb,
    DataContractCustomPropertyDb,
    DataContractSlaPropertyDb,
    DataQualityCheckDb,
    DataContractServerDb,
    DataContractServerPropertyDb,
    DataContractAuthoritativeDefinitionDb,
    SchemaObjectAuthoritativeDefinitionDb,
    SchemaObjectCustomPropertyDb,
    DataContractPricingDb,
    DataContractRolePropertyDb,
    DataProfilingRunDb,
    SuggestedQualityCheckDb,
    SchemaObjectRelationshipDb,
    SchemaPropertyRelationshipDb,
    DataContractTeamMetadataDb,
)
from src.models.data_contracts_api import (
    DataContractCreate,
    DataContractUpdate,
    DataContractRead,
    DataContractSummary,
    DataContractCommentCreate,
    DataContractCommentRead,
)
from src.common.odcs_validation import validate_odcs_contract, ODCSValidationError
from src.common.authorization import PermissionChecker, ApprovalChecker
from src.common.features import FeatureAccessLevel
from src.common.file_security import sanitize_filename, sanitize_filename_for_header
from src.models.notifications import NotificationType, Notification
from src.models.data_asset_reviews import AssetType, ReviewedAssetStatus
from src.common.deployment_dependencies import get_deployment_policy_manager
from src.controller.deployment_policy_manager import DeploymentPolicyManager
from pydantic import BaseModel, Field
import uuid
import yaml

# Configure logging
from src.common.logging import get_logger
logger = get_logger(__name__)

router = APIRouter(prefix="/api", tags=["Data Contracts"])

def get_data_contracts_manager(request: Request) -> DataContractsManager:
    """Retrieves the DataContractsManager singleton from app.state."""
    manager = getattr(request.app.state, 'data_contracts_manager', None)
    if manager is None:
        logger.critical("DataContractsManager instance not found in app.state!")
        raise HTTPException(status_code=500, detail="Data Contracts service is not available.")
    if not isinstance(manager, DataContractsManager):
        logger.critical(f"Object found at app.state.data_contracts_manager is not a DataContractsManager instance (Type: {type(manager)})!")
        raise HTTPException(status_code=500, detail="Data Contracts service configuration error.")
    return manager

def get_jobs_manager(request: Request):
    """Retrieves the JobsManager instance from app.state."""
    return getattr(request.app.state, 'jobs_manager', None)

 

@router.get('/data-contracts', response_model=list[DataContractSummary])
async def get_contracts(
    db: DBSessionDep,
    domain_id: Optional[str] = None,
    project_id: Optional[str] = None,
    include_history: bool = False,
    current_user: CurrentUserDep = None,
    manager: DataContractsManager = Depends(get_data_contracts_manager),
    _: bool = Depends(PermissionChecker('data-contracts', FeatureAccessLevel.READ_ONLY))
):
    """Get all data contracts with basic ODCS structure and optional project filtering.

    ``include_history`` (PRD #442): reserved for the family-collapse rollout.
    Until the frontend opts into the collapse, the param is accepted but the
    response shape is unchanged (every version row returned). When the
    frontend is ready, the manager will switch on this flag to return one
    row per ``version_family_id`` by default and the full set when ``True``.
    """
    try:
        # Check if user is admin
        from src.common.authorization import is_user_admin
        from src.common.config import get_settings
        settings = get_settings()
        user_groups = current_user.groups if current_user else []
        is_admin = is_user_admin(user_groups, settings)

        logger.info(
            f"User {current_user.email if current_user else 'unknown'} fetching contracts "
            f"(project_id: {project_id}, domain_id: {domain_id}, is_admin: {is_admin}, "
            f"include_history: {include_history})"
        )

        result = manager.list_contracts_from_db(
            db,
            domain_id=domain_id,
            project_id=project_id,
            is_admin=is_admin
        )
        return result
    except Exception as e:
        error_msg = f"Error retrieving data contracts: {e!s}"
        logger.error(error_msg)
        raise HTTPException(status_code=500, detail=error_msg)

@router.get('/data-contracts/count')
async def get_contracts_count(
    db: DBSessionDep,
    _: bool = Depends(PermissionChecker('data-contracts', FeatureAccessLevel.READ_ONLY))
):
    """Get total count of data contracts without loading any relationships."""
    count = db.query(DataContractDb).count()
    return {"count": count}


@router.get('/data-contracts/{contract_id}', response_model=DataContractRead)
async def get_contract(
    contract_id: str,
    db: DBSessionDep,
    manager: DataContractsManager = Depends(get_data_contracts_manager),
    _: bool = Depends(PermissionChecker('data-contracts', FeatureAccessLevel.READ_ONLY))
):
    """Get a specific data contract with full ODCS structure"""
    contract = data_contract_repo.get_with_all(db, id=contract_id)
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")

    return manager._build_contract_api_model(db, contract)


# --- Lifecycle Transition Endpoints (minimal) ---

@router.post('/data-contracts/{contract_id}/approve')
async def approve_contract(
    contract_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager: DataContractsManager = Depends(get_data_contracts_manager),
    _: bool = Depends(ApprovalChecker('CONTRACTS')),
):
    """Approve a contract (PROPOSED/UNDER_REVIEW → APPROVED)."""
    try:
        # Check valid source status
        contract = data_contract_repo.get(db, id=contract_id)
        if not contract:
            raise HTTPException(status_code=404, detail="Contract not found")
        from_status = (contract.status or '').lower()
        if from_status not in ('proposed', 'under_review'):
            raise HTTPException(status_code=409, detail=f"Invalid transition from {contract.status} to APPROVED")
        
        # Business logic now in manager
        updated = manager.transition_status(
            db=db,
            contract_id=contract_id,
            new_status='approved',
            current_user=current_user.username if current_user else None
        )
        
        # Audit
        audit_manager.log_action(
            db=db,
            username=current_user.username if current_user else 'anonymous',
            ip_address=request.client.host if request.client else None,
            feature='data-contracts',
            action='APPROVE',
            success=True,
            details={'contract_id': contract_id, 'from': from_status, 'to': updated.status}
        )
        return {'status': updated.status}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Approve contract failed for contract_id=%s", contract_id)
        raise HTTPException(status_code=500, detail="Failed to approve contract")


@router.post('/data-contracts/{contract_id}/reject')
async def reject_contract(
    contract_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager: DataContractsManager = Depends(get_data_contracts_manager),
    _: bool = Depends(ApprovalChecker('CONTRACTS')),
):
    """Reject a contract (PROPOSED/UNDER_REVIEW → DRAFT for revisions)."""
    try:
        # Check valid source status
        contract = data_contract_repo.get(db, id=contract_id)
        if not contract:
            raise HTTPException(status_code=404, detail="Contract not found")
        from_status = (contract.status or '').lower()
        if from_status not in ('proposed', 'under_review'):
            raise HTTPException(status_code=409, detail=f"Invalid transition from {contract.status} to DRAFT")
        
        # Business logic now in manager (ODCS: rejected contracts return to draft)
        updated = manager.transition_status(
            db=db,
            contract_id=contract_id,
            new_status='draft',
            current_user=current_user.username if current_user else None
        )
        
        # Audit
        audit_manager.log_action(
            db=db,
            username=current_user.username if current_user else 'anonymous',
            ip_address=request.client.host if request.client else None,
            feature='data-contracts',
            action='REJECT',
            success=True,
            details={'contract_id': contract_id, 'from': from_status, 'to': updated.status}
        )
        return {'status': updated.status}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Reject contract failed for contract_id=%s", contract_id)
        raise HTTPException(status_code=500, detail="Failed to reject contract")


class ChangeStatusPayload(BaseModel):
    new_status: str


@router.post('/data-contracts/{contract_id}/change-status')
async def change_contract_status(
    contract_id: str,
    payload: ChangeStatusPayload,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager: DataContractsManager = Depends(get_data_contracts_manager),
    _: bool = Depends(PermissionChecker('data-contracts', FeatureAccessLevel.READ_WRITE)),
):
    """
    Change contract status. Validates transition is allowed per ODCS lifecycle.
    
    Valid transitions:
    - draft → proposed, deprecated
    - proposed → draft, under_review, deprecated
    - under_review → draft, approved, deprecated
    - approved → active, draft, deprecated
    - active → certified, deprecated
    - certified → deprecated, active
    - deprecated → retired, active
    - retired → (terminal state, no transitions)
    """
    try:
        contract = data_contract_repo.get(db, id=contract_id)
        if not contract:
            raise HTTPException(status_code=404, detail="Contract not found")
        from_status = (contract.status or 'draft').lower()
        new_status = payload.new_status.lower()
        
        # Use manager's transition_status which validates the transition
        updated = manager.transition_status(
            db=db,
            contract_id=contract_id,
            new_status=new_status,
            current_user=current_user.username if current_user else None
        )
        
        # Audit
        audit_manager.log_action(
            db=db,
            username=current_user.username if current_user else 'anonymous',
            ip_address=request.client.host if request.client else None,
            feature='data-contracts',
            action='CHANGE_STATUS',
            success=True,
            details={'contract_id': contract_id, 'from': from_status, 'to': updated.status}
        )
        return {'status': updated.status, 'from': from_status, 'to': updated.status}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Change status failed for contract_id=%s", contract_id)
        raise HTTPException(status_code=500, detail="Failed to change contract status")


# --- Request Endpoints (for review, publish, deploy) ---

class RequestReviewPayload(BaseModel):
    message: Optional[str] = None

class RequestPublishPayload(BaseModel):
    justification: Optional[str] = None
    scope: str = "organization"

class RequestDeployPayload(BaseModel):
    catalog: Optional[str] = None
    database_schema: Optional[str] = Field(None, alias="schema")
    message: Optional[str] = None
    
    class Config:
        populate_by_name = True


class RequestStatusChangePayload(BaseModel):
    target_status: str
    justification: str
    current_status: Optional[str] = None


class HandleStatusChangePayload(BaseModel):
    decision: str  # 'approve' | 'deny' | 'clarify'
    target_status: str
    requester_email: str
    message: Optional[str] = None


@router.post('/data-contracts/{contract_id}/request-review')
async def request_steward_review(
    contract_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    notifications: NotificationsManagerDep,
    payload: RequestReviewPayload = Body(default=RequestReviewPayload()),
    manager: DataContractsManager = Depends(get_data_contracts_manager),
    _: bool = Depends(PermissionChecker('data-contracts', FeatureAccessLevel.READ_WRITE)),
):
    """Request a data steward review for a contract."""
    try:
        # Business logic now in manager
        result = manager.request_steward_review(
            db=db,
            notifications_manager=notifications,
            contract_id=contract_id,
            requester_email=current_user.email,
            message=payload.message,
            current_user=current_user.username if current_user else None
        )
        
        # Audit
        audit_manager.log_action(
            db=db,
            username=current_user.username if current_user else 'anonymous',
            ip_address=request.client.host if request.client else None,
            feature='data-contracts',
            action='REQUEST_REVIEW',
            success=True,
            details={'contract_id': contract_id, 'status': result.get('status')}
        )
        
        return result
        
    except ValueError as e:
        logger.error("Request review validation error for contract_id=%s: %s", contract_id, e)
        error_status = 404 if "not found" in str(e).lower() else 409
        raise HTTPException(status_code=error_status, detail="Invalid review request")
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Request review failed for contract_id=%s", contract_id)
        raise HTTPException(status_code=500, detail="Failed to request review")


@router.post('/data-contracts/{contract_id}/request-publish')
async def request_publish_to_marketplace(
    contract_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    notifications: NotificationsManagerDep,
    payload: RequestPublishPayload = Body(default=RequestPublishPayload()),
    manager: DataContractsManager = Depends(get_data_contracts_manager),
    _: bool = Depends(PermissionChecker('data-contracts', FeatureAccessLevel.READ_WRITE)),
):
    """Request to publish an APPROVED contract to the marketplace."""
    try:
        # Business logic now in manager
        result = manager.request_publish(
            db=db,
            notifications_manager=notifications,
            contract_id=contract_id,
            requester_email=current_user.email,
            justification=payload.justification,
            current_user=current_user.username if current_user else None,
            requested_scope=payload.scope,
        )
        
        # Audit
        audit_manager.log_action(
            db=db,
            username=current_user.username if current_user else 'anonymous',
            ip_address=request.client.host if request.client else None,
            feature='data-contracts',
            action='REQUEST_PUBLISH',
            success=True,
            details={'contract_id': contract_id}
        )
        
        return result
        
    except ValueError as e:
        logger.error("Request publish validation error for contract_id=%s: %s", contract_id, e)
        error_status = 404 if "not found" in str(e).lower() else 409
        raise HTTPException(status_code=error_status, detail="Invalid publish request")
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Request publish failed for contract_id=%s", contract_id)
        raise HTTPException(status_code=500, detail="Failed to request publish")


@router.post('/data-contracts/{contract_id}/request-deploy')
async def request_deploy_to_catalog(
    contract_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    notifications: NotificationsManagerDep,
    deployment_manager: DeploymentPolicyManager = Depends(get_deployment_policy_manager),
    payload: RequestDeployPayload = Body(default=RequestDeployPayload()),
    manager: DataContractsManager = Depends(get_data_contracts_manager),
    _: bool = Depends(PermissionChecker('data-contracts', FeatureAccessLevel.READ_WRITE)),
):
    """Request approval to deploy a contract to Unity Catalog."""
    try:
        # Business logic now in manager
        result = manager.request_deploy(
            db=db,
            notifications_manager=notifications,
            deployment_manager=deployment_manager,
            current_user_obj=current_user,
            contract_id=contract_id,
            requester_email=current_user.email,
            catalog=payload.catalog,
            database_schema=payload.database_schema,
            message=payload.message,
            current_user=current_user.username if current_user else None
        )
        
        # Audit
        audit_manager.log_action(
            db=db,
            username=current_user.username if current_user else 'anonymous',
            ip_address=request.client.host if request.client else None,
            feature='data-contracts',
            action='REQUEST_DEPLOY',
            success=True,
            details={'contract_id': contract_id, 'catalog': payload.catalog, 'schema': payload.database_schema}
        )
        
        return result
        
    except ValueError as e:
        logger.error("Request deploy validation error for contract_id=%s: %s", contract_id, e)
        error_status = 404 if "not found" in str(e).lower() else (403 if "denied" in str(e).lower() or "permission" in str(e).lower() else 409)
        raise HTTPException(status_code=error_status, detail="Invalid deploy request")
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Request deploy failed for contract_id=%s", contract_id)
        raise HTTPException(status_code=500, detail="Failed to request deploy")


@router.post('/data-contracts/{contract_id}/request-status-change')
async def request_status_change(
    contract_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    notifications: NotificationsManagerDep,
    payload: RequestStatusChangePayload = Body(...),
    manager: DataContractsManager = Depends(get_data_contracts_manager),
    _: bool = Depends(PermissionChecker('data-contracts', FeatureAccessLevel.READ_ONLY)),
):
    """Request approval to change the status of a contract."""
    try:
        result = manager.request_status_change(
            db=db,
            notifications_manager=notifications,
            contract_id=contract_id,
            target_status=payload.target_status,
            justification=payload.justification,
            requester_email=current_user.email if current_user else None,
            current_user=current_user.username if current_user else None
        )
        
        # Audit
        audit_manager.log_action(
            db=db,
            username=current_user.username if current_user else 'anonymous',
            ip_address=request.client.host if request.client else None,
            feature='data-contracts',
            action='REQUEST_STATUS_CHANGE',
            success=True,
            details={
                'contract_id': contract_id,
                'target_status': payload.target_status,
                'current_status': payload.current_status
            }
        )
        
        return result
        
    except ValueError as e:
        logger.error("Request status change validation error for contract_id=%s: %s", contract_id, e)
        error_status = 404 if "not found" in str(e).lower() else (403 if "denied" in str(e).lower() or "permission" in str(e).lower() else 409)
        raise HTTPException(status_code=error_status, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Request status change failed for contract_id=%s", contract_id)
        raise HTTPException(status_code=500, detail="Failed to request status change")


# --- Handle Request Endpoints (for approvers to respond) ---

class HandleReviewPayload(BaseModel):
    decision: str  # 'approve', 'reject', 'clarify'
    message: Optional[str] = None

class HandlePublishPayload(BaseModel):
    decision: str  # 'approve', 'deny'
    message: Optional[str] = None

class HandleDeployPayload(BaseModel):
    decision: str  # 'approve', 'deny'
    message: Optional[str] = None
    execute_deployment: bool = False  # If true, actually trigger deployment


@router.post('/data-contracts/{contract_id}/handle-review')
async def handle_steward_review_response(
    contract_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    notifications: NotificationsManagerDep,
    payload: HandleReviewPayload = Body(...),
    manager: DataContractsManager = Depends(get_data_contracts_manager),
    _: bool = Depends(PermissionChecker('data-asset-reviews', FeatureAccessLevel.READ_WRITE)),
):
    """Handle a steward's review decision (approve/reject/clarify)."""
    try:
        # Business logic now in manager
        result = manager.handle_review_response(
            db=db,
            notifications_manager=notifications,
            contract_id=contract_id,
            reviewer_email=current_user.email,
            decision=payload.decision,
            message=payload.message,
            current_user=current_user.username if current_user else None
        )
        
        # Audit
        audit_manager.log_action(
            db=db,
            username=current_user.username if current_user else 'anonymous',
            ip_address=request.client.host if request.client else None,
            feature='data-contracts',
            action=f'REVIEW_{payload.decision.upper()}',
            success=True,
            details={'contract_id': contract_id, 'decision': payload.decision}
        )
        
        return result
        
    except ValueError as e:
        logger.error("Handle review validation error for contract_id=%s: %s", contract_id, e)
        error_status = 404 if "not found" in str(e).lower() else (400 if "must be" in str(e).lower() else 409)
        raise HTTPException(status_code=error_status, detail="Invalid review response")
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Handle review failed for contract_id=%s", contract_id)
        raise HTTPException(status_code=500, detail="Failed to handle review")


@router.post('/data-contracts/{contract_id}/handle-publish')
async def handle_publish_request_response(
    contract_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    notifications: NotificationsManagerDep,
    payload: HandlePublishPayload = Body(...),
    manager: DataContractsManager = Depends(get_data_contracts_manager),
    _: bool = Depends(ApprovalChecker('CONTRACTS')),
):
    """Handle a publish request decision (approve/deny)."""
    try:
        # Business logic now in manager
        result = manager.handle_publish_response(
            db=db,
            notifications_manager=notifications,
            contract_id=contract_id,
            approver_email=current_user.email,
            decision=payload.decision,
            message=payload.message,
            current_user=current_user.username if current_user else None
        )
        
        # Get contract for audit / response
        contract = data_contract_repo.get(db, id=contract_id)
        publication_scope = contract.publication_scope if contract else None

        # Audit
        audit_manager.log_action(
            db=db,
            username=current_user.username if current_user else 'anonymous',
            ip_address=request.client.host if request.client else None,
            feature='data-contracts',
            action=f'PUBLISH_{payload.decision.upper()}',
            success=True,
            details={
                'contract_id': contract_id,
                'decision': payload.decision,
                'publication_scope': publication_scope,
            }
        )

        result["publication_scope"] = publication_scope
        return result
        
    except ValueError as e:
        logger.error("Handle publish validation error for contract_id=%s: %s", contract_id, e)
        error_status = 404 if "not found" in str(e).lower() else (400 if "must be" in str(e).lower() else 409)
        raise HTTPException(status_code=error_status, detail="Invalid publish response")
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Handle publish failed for contract_id=%s", contract_id)
        raise HTTPException(status_code=500, detail="Failed to handle publish")


@router.post('/data-contracts/{contract_id}/request-certify')
async def request_contract_certification(
    contract_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    body: dict = Body(...),
    _: bool = Depends(PermissionChecker('data-contracts', FeatureAccessLevel.READ_WRITE)),
):
    """Request certification for a data contract (workflow trigger)."""
    try:
        certification_level = body.get("certification_level")
        if certification_level is None or not isinstance(certification_level, int):
            raise HTTPException(
                status_code=400,
                detail="certification_level is required and must be an integer",
            )
        message = body.get("message")
        contract_db = data_contract_repo.get(db, id=contract_id)
        if not contract_db:
            raise HTTPException(status_code=404, detail="Contract not found")

        from src.common.workflow_triggers import get_trigger_registry
        from src.models.process_workflows import EntityType

        get_trigger_registry(db).on_request_certify(
            EntityType.DATA_CONTRACT,
            contract_id,
            entity_name=contract_db.name,
            entity_data={
                "requested_certification_level": certification_level,
                "message": message,
                "requester": current_user.username if current_user else None,
            },
            user_email=current_user.username if current_user else None,
            blocking=True,
        )

        audit_manager.log_action(
            db=db,
            username=current_user.username if current_user else 'anonymous',
            ip_address=request.client.host if request.client else None,
            feature='data-contracts',
            action='REQUEST_CERTIFY',
            success=True,
            details={'contract_id': contract_id, 'certification_level': certification_level},
        )

        return JSONResponse(
            status_code=202,
            content={"status": "requested", "message": "Certification request submitted"},
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Request certify failed for contract_id=%s", contract_id)
        raise HTTPException(status_code=500, detail="Failed to request certification")


@router.post('/data-contracts/{contract_id}/handle-certify')
async def handle_contract_certification(
    contract_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    body: dict = Body(...),
    manager: DataContractsManager = Depends(get_data_contracts_manager),
    _: bool = Depends(ApprovalChecker('CONTRACTS')),
):
    """Approve or deny a data contract certification request."""
    try:
        approved = body.get("approved")
        if not isinstance(approved, bool):
            raise HTTPException(status_code=400, detail="approved must be a boolean")

        if not approved:
            audit_manager.log_action(
                db=db,
                username=current_user.username if current_user else 'anonymous',
                ip_address=request.client.host if request.client else None,
                feature='data-contracts',
                action='CERTIFY_DENIED',
                success=True,
                details={'contract_id': contract_id},
            )
            return {"status": "denied"}

        certification_level = body.get("certification_level")
        if certification_level is not None and not isinstance(certification_level, int):
            raise HTTPException(status_code=400, detail="certification_level must be an integer")
        if certification_level is None:
            raise HTTPException(
                status_code=400,
                detail="certification_level is required when approving",
            )
        notes = body.get("notes")

        contract_db = data_contract_repo.get(db, id=contract_id)
        if not contract_db:
            raise HTTPException(status_code=404, detail="Contract not found")

        now = datetime.now(timezone.utc)
        contract_db.certification_level = certification_level
        contract_db.certified_at = now
        contract_db.certified_by = current_user.email if current_user else None
        contract_db.certification_notes = notes
        db.add(contract_db)
        db.commit()
        db.refresh(contract_db)

        from src.common.workflow_triggers import fire_trigger_safe
        from src.models.process_workflows import EntityType
        fire_trigger_safe(
            db, "on_certify",
            entity_type=EntityType.DATA_CONTRACT,
            entity_id=contract_id,
            entity_name=contract_db.name,
            entity_data={
                "certification_level": certification_level,
                "certification_notes": notes,
                "certified_by": contract_db.certified_by,
            },
            user_email=current_user.email if current_user else None,
        )

        manager._update_search_index(contract_db, db)

        audit_manager.log_action(
            db=db,
            username=current_user.username if current_user else 'anonymous',
            ip_address=request.client.host if request.client else None,
            feature='data-contracts',
            action='CERTIFY_APPROVED',
            success=True,
            details={
                'contract_id': contract_id,
                'certification_level': certification_level,
            },
        )

        return {
            "status": "approved",
            "certification_level": certification_level,
            "message": "Contract certified",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Handle certify failed for contract_id=%s", contract_id)
        raise HTTPException(status_code=500, detail="Failed to handle certification")


@router.post('/data-contracts/{contract_id}/certify')
async def certify_contract_direct(
    contract_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    body: dict = Body(...),
    manager: DataContractsManager = Depends(get_data_contracts_manager),
    _: bool = Depends(ApprovalChecker('CONTRACTS')),
):
    """Certify a data contract at a specific level (direct). Contract must be active."""
    certification_level = body.get("certification_level")
    if certification_level is None:
        raise HTTPException(status_code=422, detail="certification_level is required")

    try:
        contract_db = data_contract_repo.get(db, id=contract_id)
        if not contract_db:
            raise HTTPException(status_code=404, detail="Contract not found")

        if (contract_db.status or "").lower() != "active":
            raise HTTPException(
                status_code=409,
                detail=f"Contract must be active to certify. Current status: {contract_db.status}",
            )

        from src.repositories.certification_levels_repository import certification_levels_repo

        level = certification_levels_repo.get_by_order(db, certification_level)
        if not level:
            raise HTTPException(status_code=404, detail=f"Certification level {certification_level} not found")

        now = datetime.now(timezone.utc)
        contract_db.certification_level = certification_level
        contract_db.certified_at = now
        contract_db.certified_by = current_user.username if current_user else None
        contract_db.certification_notes = body.get("notes")
        db.add(contract_db)
        db.commit()
        db.refresh(contract_db)

        audit_manager.log_action(
            db=db,
            username=current_user.username if current_user else "anonymous",
            ip_address=request.client.host if request.client else None,
            feature="data-contracts",
            action="CERTIFY",
            success=True,
            details={"contract_id": contract_id, "certification_level": certification_level},
        )

        from src.controller.certification_propagator import propagate_certification

        propagate_certification(db, "DataContract", contract_id)
        db.commit()

        from src.common.workflow_triggers import fire_trigger_safe
        from src.models.process_workflows import EntityType
        fire_trigger_safe(
            db, "on_certify",
            entity_type=EntityType.DATA_CONTRACT,
            entity_id=contract_id,
            entity_name=contract_db.name,
            entity_data={"certification_level": contract_db.certification_level},
            user_email=current_user.username if current_user else None,
        )

        manager._update_search_index(contract_db, db)

        return {
            "certification_level": contract_db.certification_level,
            "certified_at": str(contract_db.certified_at) if contract_db.certified_at else None,
            "certified_by": contract_db.certified_by,
            "certification_notes": contract_db.certification_notes,
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Certify contract failed for contract_id=%s", contract_id)
        raise HTTPException(status_code=500, detail="Failed to certify contract")


@router.post('/data-contracts/{contract_id}/decertify')
async def decertify_contract(
    contract_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager: DataContractsManager = Depends(get_data_contracts_manager),
    _: bool = Depends(ApprovalChecker('CONTRACTS')),
):
    """Remove certification from a data contract."""
    try:
        contract_db = data_contract_repo.get(db, id=contract_id)
        if not contract_db:
            raise HTTPException(status_code=404, detail="Contract not found")

        old_level = contract_db.certification_level
        contract_db.certification_level = None
        contract_db.certified_at = None
        contract_db.certified_by = None
        contract_db.certification_expires_at = None
        contract_db.certification_notes = None
        db.add(contract_db)
        db.commit()

        from src.common.workflow_triggers import fire_trigger_safe
        from src.models.process_workflows import EntityType
        fire_trigger_safe(
            db, "on_decertify",
            entity_type=EntityType.DATA_CONTRACT,
            entity_id=contract_id,
            entity_name=contract_db.name,
            user_email=current_user.username,
        )

        audit_manager.log_action(
            db=db,
            username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature="data-contracts",
            action='DECERTIFY',
            success=True,
            details={'contract_id': contract_id, 'previous_level': old_level},
        )

        manager._update_search_index(contract_db, db)

        return {'certification_level': None}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Decertify contract failed for contract_id=%s", contract_id)
        raise HTTPException(status_code=500, detail="Failed to decertify contract")


@router.post('/data-contracts/{contract_id}/set-publication-scope')
async def set_contract_publication_scope(
    contract_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    body: dict = Body(...),
    manager: DataContractsManager = Depends(get_data_contracts_manager),
    _: bool = Depends(PermissionChecker("data-contracts", FeatureAccessLevel.READ_WRITE)),
):
    """Set publication scope. Contract must be active or approved."""
    scope = body.get("scope", "none")
    valid_scopes = ["none", "domain", "organization", "external"]
    if scope not in valid_scopes:
        raise HTTPException(status_code=422, detail=f"Invalid scope. Must be one of: {valid_scopes}")

    try:
        contract_db = data_contract_repo.get(db, id=contract_id)
        if not contract_db:
            raise HTTPException(status_code=404, detail="Contract not found")

        st = (contract_db.status or "").lower()
        if scope != "none" and st not in ("active", "approved"):
            raise HTTPException(
                status_code=409,
                detail=f"Contract must be active or approved to publish. Current status: {contract_db.status}",
            )

        was_published = (contract_db.publication_scope or "none").lower() != "none"

        if scope != "none":
            contract_db.publication_scope = scope
            contract_db.published_at = datetime.now(timezone.utc)
            contract_db.published_by = current_user.username if current_user else None
        else:
            contract_db.publication_scope = "none"
            contract_db.published_at = None
            contract_db.published_by = None
        db.add(contract_db)
        db.commit()
        db.refresh(contract_db)

        # Fire on_unpublish trigger when transitioning from published to unpublished
        if scope == "none" and was_published:
            from src.common.workflow_triggers import fire_trigger_safe
            from src.models.process_workflows import EntityType
            fire_trigger_safe(
                db, "on_unpublish",
                entity_type=EntityType.DATA_CONTRACT,
                entity_id=contract_id,
                entity_name=contract_db.name,
                user_email=current_user.username if current_user else None,
            )

        audit_manager.log_action(
            db=db,
            username=current_user.username if current_user else "anonymous",
            ip_address=request.client.host if request.client else None,
            feature="data-contracts",
            action="SET_PUBLICATION_SCOPE",
            success=True,
            details={"contract_id": contract_id, "scope": scope},
        )

        manager._update_search_index(contract_db, db)

        return {
            "publication_scope": contract_db.publication_scope,
            "published_at": str(contract_db.published_at) if contract_db.published_at else None,
            "published_by": contract_db.published_by,
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Set publication scope failed for contract_id=%s", contract_id)
        raise HTTPException(status_code=500, detail="Failed to set publication scope")


@router.post('/data-contracts/{contract_id}/handle-deploy')
async def handle_deploy_request_response(
    contract_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    notifications: NotificationsManagerDep,
    payload: HandleDeployPayload = Body(...),
    manager: DataContractsManager = Depends(get_data_contracts_manager),
    _: bool = Depends(PermissionChecker('self-service', FeatureAccessLevel.READ_WRITE)),
):
    """Handle a deployment request decision (approve/deny). Optionally executes deployment."""
    try:
        # Get jobs manager for deployment execution
        jobs_manager = None
        try:
            from src.common.dependencies import get_jobs_manager
            jobs_manager = request.app.state.jobs_manager
        except Exception:
            logger.warning("Jobs manager not available")
        
        # Business logic now in manager
        result = manager.handle_deploy_response(
            db=db,
            notifications_manager=notifications,
            jobs_manager=jobs_manager,
            contract_id=contract_id,
            approver_email=current_user.email,
            decision=payload.decision,
            execute_deployment=payload.execute_deployment,
            message=payload.message,
            current_user=current_user.username if current_user else None
        )
        
        # Audit
        audit_manager.log_action(
            db=db,
            username=current_user.username if current_user else 'anonymous',
            ip_address=request.client.host if request.client else None,
            feature='data-contracts',
            action=f'DEPLOY_{payload.decision.upper()}',
            success=True,
            details={'contract_id': contract_id, 'decision': payload.decision, 'deployed': payload.execute_deployment}
        )
        
        return result
        
    except ValueError as e:
        logger.error("Handle deploy validation error for contract_id=%s: %s", contract_id, e)
        error_status = 404 if "not found" in str(e).lower() else (400 if "must be" in str(e).lower() else 409)
        raise HTTPException(status_code=error_status, detail="Invalid deploy response")
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Handle deploy failed for contract_id=%s", contract_id)
        raise HTTPException(status_code=500, detail="Failed to handle deploy")


@router.post('/data-contracts/{contract_id}/handle-status-change')
async def handle_status_change_response(
    contract_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    notifications: NotificationsManagerDep,
    payload: HandleStatusChangePayload = Body(...),
    manager: DataContractsManager = Depends(get_data_contracts_manager),
    _: bool = Depends(PermissionChecker('data-contracts', FeatureAccessLevel.READ_WRITE)),
):
    """Handle a status change request decision (approve/deny/clarify)."""
    try:
        result = manager.handle_status_change_response(
            db=db,
            notifications_manager=notifications,
            contract_id=contract_id,
            approver_email=current_user.email if current_user else None,
            decision=payload.decision,
            target_status=payload.target_status,
            requester_email=payload.requester_email,
            message=payload.message,
            current_user=current_user.username if current_user else None
        )
        
        # Audit
        audit_manager.log_action(
            db=db,
            username=current_user.username if current_user else 'anonymous',
            ip_address=request.client.host if request.client else None,
            feature='data-contracts',
            action=f'STATUS_CHANGE_{payload.decision.upper()}',
            success=True,
            details={
                'contract_id': contract_id,
                'decision': payload.decision,
                'target_status': payload.target_status
            }
        )
        
        return result
        
    except ValueError as e:
        logger.error("Handle status change validation error for contract_id=%s: %s", contract_id, e)
        error_status = 404 if "not found" in str(e).lower() else (400 if "must be" in str(e).lower() else 409)
        raise HTTPException(status_code=error_status, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Handle status change failed for contract_id=%s", contract_id)
        raise HTTPException(status_code=500, detail="Failed to handle status change")


@router.post('/data-contracts', response_model=DataContractRead)
async def create_contract(
    request: Request,
    db: DBSessionDep,
    background_tasks: BackgroundTasks,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    contract_data: DataContractCreate = Body(...),
    manager: DataContractsManager = Depends(get_data_contracts_manager),
    _: bool = Depends(PermissionChecker('data-contracts', FeatureAccessLevel.READ_WRITE)),
):
    """Create a new data contract with normalized ODCS structure"""
    success = False
    details_for_audit = {
        "params": {"contract_name": contract_data.name if contract_data.name else "N/A"},
    }
    created_contract_id = None

    try:
        # Validate project access if project_id is provided
        if contract_data.project_id:
            from src.controller.projects_manager import projects_manager
            from src.common.config import get_settings
            user_groups = current_user.groups or []
            settings = get_settings()
            is_member = projects_manager.is_user_project_member(
                db=db,
                user_identifier=current_user.email,
                user_groups=user_groups,
                project_id=contract_data.project_id,
                settings=settings
            )
            if not is_member:
                raise HTTPException(
                    status_code=403, 
                    detail="You must be a member of the project to create a contract in it"
                )
        
        # Business logic now in manager (delivery handled via DeliveryMixin)
        created = manager.create_contract_with_relations(
            db=db,
            contract_data=contract_data,
            current_user=current_user.username if current_user else None,
            background_tasks=background_tasks,
        )
        
        success = True
        created_contract_id = created.id

        # Fire on_create workflow trigger
        from src.common.workflow_triggers import fire_trigger_safe
        from src.models.process_workflows import EntityType
        fire_trigger_safe(
            db, "on_create",
            entity_type=EntityType.DATA_CONTRACT,
            entity_id=str(created.id),
            entity_name=created.name,
            entity_data={"contract_id": str(created.id), "name": created.name, "status": getattr(created, 'status', 'draft')},
            user_email=current_user.email if current_user else None,
        )

        # Load with relationships for response
        created_with_relations = data_contract_repo.get_with_all(db, id=created.id)
        return manager._build_contract_api_model(db, created_with_relations)

    except ValueError as e:
        logger.error("Validation error creating contract: %s", e)
        details_for_audit["exception"] = {"type": "ValueError", "message": str(e)}
        raise HTTPException(status_code=400, detail="Invalid contract data")
    except HTTPException as http_exc:
        details_for_audit["exception"] = {"type": "HTTPException", "status_code": http_exc.status_code, "detail": http_exc.detail}
        raise
    except Exception as e:
        logger.exception("Failed to create contract")
        details_for_audit["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise HTTPException(status_code=500, detail="Failed to create contract")
    finally:
        if created_contract_id:
            details_for_audit["created_resource_id"] = created_contract_id
        audit_manager.log_action(
            db=db,
            username=current_user.username if current_user else "anonymous",
            ip_address=request.client.host if request.client else None,
            feature="data-contracts",
            action="CREATE",
            success=success,
            details=details_for_audit
        )

@router.put('/data-contracts/{contract_id}', response_model=DataContractRead)
async def update_contract(
    contract_id: str,
    request: Request,
    db: DBSessionDep,
    background_tasks: BackgroundTasks,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    contract_data: DataContractUpdate = Body(...),
    manager: DataContractsManager = Depends(get_data_contracts_manager),
    _: bool = Depends(PermissionChecker('data-contracts', FeatureAccessLevel.READ_WRITE))
):
    """Update a data contract"""
    logger.info(f"[DEBUG UPDATE] Received update for contract {contract_id}")
    logger.info(f"[DEBUG UPDATE] contract_data.owner_team_id = {contract_data.owner_team_id}")
    logger.info(f"[DEBUG UPDATE] contract_data dict = {contract_data.model_dump(exclude_unset=True)}")
    success = False
    details_for_audit = {
        "params": {"contract_id": contract_id},
    }

    try:
        # Check project membership if contract belongs to a project
        db_obj = data_contract_repo.get(db, id=contract_id)
        if not db_obj:
            raise HTTPException(status_code=404, detail="Contract not found")
            
        if db_obj.project_id:
            from src.controller.projects_manager import projects_manager
            from src.common.config import get_settings
            user_groups = current_user.groups or []
            settings = get_settings()
            is_member = projects_manager.is_user_project_member(
                db=db,
                user_identifier=current_user.email,
                user_groups=user_groups,
                project_id=db_obj.project_id,
                settings=settings
            )
            if not is_member:
                raise HTTPException(
                    status_code=403, 
                    detail="You must be a member of the project to edit this contract"
                )

        # Check if versioning is required for non-draft contracts
        if db_obj.status and db_obj.status.lower() != 'draft':
            # Check if caller explicitly forced the update
            force_update = request.headers.get('X-Force-Update') == 'true'
            
            if not force_update:
                # Analyze the impact of proposed changes
                proposed_changes_dict = contract_data.model_dump(by_alias=True, exclude_unset=True)
                impact_analysis = manager.analyze_update_impact(
                    contract_id=contract_id,
                    proposed_changes=proposed_changes_dict,
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
                        # Admin can override - log warning but allow update
                        logger.warning(
                            f"Admin {current_user.username if current_user else 'unknown'} is updating contract "
                            f"{contract_id} with breaking changes: {impact_analysis['change_analysis'].get('summary', 'N/A')}"
                        )
                        # Continue with update - admin override in effect

        # Run before_update workflow validation
        try:
            from src.common.workflow_triggers import get_trigger_registry
            from src.models.process_workflows import EntityType
            trigger_registry = get_trigger_registry(db)
            pre_passed, pre_executions = trigger_registry.before_update(
                entity_type=EntityType.DATA_CONTRACT,
                entity_id=contract_id,
                entity_name=getattr(db_obj, 'name', None),
                entity_data=contract_data.model_dump(exclude_unset=True),
                user_email=current_user.email if current_user else None,
            )
            if not pre_passed:
                raise HTTPException(
                    status_code=400,
                    detail={
                        'message': 'Pre-update validation failed',
                        'workflows': [
                            {'workflow_name': exe.workflow_name, 'status': exe.status.value}
                            for exe in pre_executions
                        ],
                    }
                )
        except HTTPException:
            raise
        except Exception as e:
            logger.warning(f"before_update trigger failed for contract {contract_id}: {e}")

        # Business logic now in manager (delivery handled via DeliveryMixin)
        updated = manager.update_contract_with_relations(
            db=db,
            contract_id=contract_id,
            contract_data=contract_data,
            current_user=current_user.username if current_user else None,
            background_tasks=background_tasks,
        )

        success = True

        # Fire on_update workflow trigger
        from src.common.workflow_triggers import fire_trigger_safe
        from src.models.process_workflows import EntityType
        fire_trigger_safe(
            db, "on_update",
            entity_type=EntityType.DATA_CONTRACT,
            entity_id=contract_id,
            entity_name=getattr(updated, 'name', None),
            entity_data=contract_data.model_dump(exclude_unset=True),
            user_email=current_user.email if current_user else None,
        )

        # Load with relationships for full response
        updated_with_relations = data_contract_repo.get_with_all(db, id=contract_id)
        return manager._build_contract_api_model(db, updated_with_relations)

    except ValueError as e:
        logger.error("Validation error updating contract %s: %s", contract_id, e)
        details_for_audit["exception"] = {"type": "ValueError", "message": str(e)}
        raise HTTPException(status_code=400, detail="Invalid contract data")
    except HTTPException as http_exc:
        details_for_audit["exception"] = {"type": "HTTPException", "status_code": http_exc.status_code, "detail": http_exc.detail}
        raise
    except Exception as e:
        error_msg = f"Error updating data contract {contract_id}: {e!s}"
        logger.error(error_msg)
        details_for_audit["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise HTTPException(status_code=500, detail=error_msg)
    finally:
        if success:
            details_for_audit["updated_resource_id"] = contract_id
        audit_manager.log_action(
            db=db,
            username=current_user.username if current_user else "anonymous",
            ip_address=request.client.host if request.client else None,
            feature="data-contracts",
            action="UPDATE",
            success=success,
            details=details_for_audit
        )

@router.delete('/data-contracts/{contract_id}', status_code=204)
async def delete_contract(
    contract_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager: DataContractsManager = Depends(get_data_contracts_manager),
    _: bool = Depends(PermissionChecker('data-contracts', FeatureAccessLevel.READ_WRITE))
):
    """Delete a data contract"""
    success = False
    response_status_code = 500
    details_for_audit = {
        "params": {"contract_id": contract_id}
    }
    try:
        # Use manager method which handles deletion and change logging
        manager.delete_contract_from_db(
            db=db,
            contract_id=contract_id,
            current_user=current_user.username if current_user else None,
        )
        
        db.commit()
        success = True
        response_status_code = 204

        # Fire on_delete workflow trigger
        from src.common.workflow_triggers import fire_trigger_safe
        from src.models.process_workflows import EntityType
        fire_trigger_safe(
            db, "on_delete",
            entity_type=EntityType.DATA_CONTRACT,
            entity_id=contract_id,
            entity_data={"contract_id": contract_id},
            user_email=current_user.email if current_user else None,
        )

        return None
    except ValueError as e:
        response_status_code = 404
        exc = HTTPException(status_code=response_status_code, detail=str(e))
        details_for_audit["exception"] = {"type": "HTTPException", "status_code": exc.status_code, "detail": exc.detail}
        raise exc
    except HTTPException:
        raise
    except Exception as e:
        success = False
        response_status_code = 500
        error_msg = f"Error deleting data contract {contract_id}: {e!s}"
        details_for_audit["exception"] = {"type": type(e).__name__, "message": str(e)}
        logger.error(error_msg)
        raise HTTPException(status_code=500, detail=error_msg)
    finally:
        if "exception" not in details_for_audit:
            details_for_audit["response_status_code"] = response_status_code
        details_for_audit["deleted_resource_id_attempted"] = contract_id
        audit_manager.log_action(
            db=db,
            username=current_user.username if current_user else "anonymous",
            ip_address=request.client.host if request.client else None,
            feature="data-contracts",
            action="DELETE",
            success=success,
            details=details_for_audit,
        )

@router.post('/data-contracts/upload')
async def upload_contract(
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    file: UploadFile = File(...),
    manager: DataContractsManager = Depends(get_data_contracts_manager),
    _: bool = Depends(PermissionChecker('data-contracts', FeatureAccessLevel.READ_WRITE)),
):
    """Upload a contract file and parse it into normalized ODCS structure"""
    # SECURITY: Sanitize filename for safe logging and processing
    raw_filename = file.filename or "uploaded_contract"
    safe_filename = sanitize_filename(raw_filename, default="uploaded_contract")
    
    success = False
    details_for_audit = {
        "params": {"filename": safe_filename},
    }
    created_contract_id = None

    try:
        # Read file content
        contract_text = (await file.read()).decode('utf-8')
        
        # Parse file using manager (use sanitized filename)
        parsed = manager.parse_uploaded_file(
            file_content=contract_text,
            filename=safe_filename,
            content_type=file.content_type or 'application/json'
        )
        
        # Validate ODCS (optional, log warnings)
        validation_warnings = manager.validate_odcs(parsed, strict=False)
        for warning in validation_warnings[:5]:
            logger.warning(warning)
        
        # Create contract with all nested entities using manager
        created = manager.create_from_upload(
            db=db,
            parsed_odcs=parsed,
            current_user=current_user.username if current_user else None
        )
        
        success = True
        created_contract_id = created.id

        # Load with relationships for response
        created_with_relations = data_contract_repo.get_with_all(db, id=created.id)
        result = manager._build_contract_api_model(db, created_with_relations)
        return result

    except ValueError as e:
        logger.error("Validation error uploading contract: %s", e)
        details_for_audit["exception"] = {"type": "ValueError", "message": str(e)}
        raise HTTPException(status_code=400, detail={
            "message": "Invalid contract data",
            "error": str(e),
        })
    except HTTPException as http_exc:
        details_for_audit["exception"] = {"type": "HTTPException", "status_code": http_exc.status_code, "detail": http_exc.detail}
        raise
    except Exception as e:
        logger.exception("Upload failed")
        details_for_audit["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise HTTPException(status_code=500, detail={
            "message": "Upload failed",
            "error": f"{type(e).__name__}: {e}",
        })
    finally:
        if created_contract_id:
            details_for_audit["created_resource_id"] = created_contract_id
        audit_manager.log_action(
            db=db,
            username=current_user.username if current_user else "anonymous",
            ip_address=request.client.host if request.client else None,
            feature="data-contracts",
            action="UPLOAD",
            success=success,
            details=details_for_audit
        )

# Old document-based export removed - use /data-contracts/{contract_id}/odcs/export instead


@router.get('/data-contracts/schema/odcs')
async def get_odcs_schema(_perm: bool = Depends(PermissionChecker('data-contracts', FeatureAccessLevel.READ_ONLY))):
    try:
        from pathlib import Path
        schema_path = Path(__file__).parent.parent / 'schemas' / 'odcs-json-schema-v3.1.0.json'
        with open(schema_path, 'r') as f:
            data = json.load(f)
        return data
    except Exception as e:
        logger.exception("Failed to load schema file")
        raise HTTPException(status_code=500, detail="Failed to load schema file")


@router.post('/data-contracts/odcs/import')
async def import_odcs_json(
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    body: dict = Body(...),
    manager: DataContractsManager = Depends(get_data_contracts_manager),
    _: bool = Depends(PermissionChecker('data-contracts', FeatureAccessLevel.READ_WRITE)),
):
    """Import an ODCS contract from a pasted JSON object."""
    success = False
    details_for_audit: dict = {"params": {"source": "paste"}}
    created_contract_id = None

    try:
        contract_text = json.dumps(body)

        parsed = manager.parse_uploaded_file(
            file_content=contract_text,
            filename="paste.json",
            content_type="application/json",
        )

        validation_warnings = manager.validate_odcs(parsed, strict=False)
        for warning in validation_warnings[:5]:
            logger.warning(warning)

        created = manager.create_from_upload(
            db=db,
            parsed_odcs=parsed,
            current_user=current_user.username if current_user else None,
        )

        success = True
        created_contract_id = created.id

        created_with_relations = data_contract_repo.get_with_all(db, id=created.id)
        return manager._build_contract_api_model(db, created_with_relations)

    except ValueError as e:
        logger.error("Validation error importing ODCS JSON: %s", e)
        details_for_audit["exception"] = {"type": "ValueError", "message": str(e)}
        raise HTTPException(status_code=400, detail={
            "message": "Invalid contract data",
            "error": str(e),
        })
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("ODCS JSON import failed")
        details_for_audit["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise HTTPException(status_code=500, detail={
            "message": "Import failed",
            "error": f"{type(e).__name__}: {e}",
        })
    finally:
        if created_contract_id:
            details_for_audit["created_resource_id"] = created_contract_id
        audit_manager.log_action(
            db=db,
            username=current_user.username if current_user else "anonymous",
            ip_address=request.client.host if request.client else None,
            feature="data-contracts",
            action="IMPORT_ODCS_JSON",
            success=success,
            details=details_for_audit,
        )


# --- Lazy Schema / Properties Endpoints ---

@router.get('/data-contracts/{contract_id}/schemas')
async def get_contract_schemas(
    contract_id: str,
    db: DBSessionDep,
    _: bool = Depends(PermissionChecker('data-contracts', FeatureAccessLevel.READ_ONLY))
):
    """List schema objects for a contract (names + property counts, no properties loaded)."""
    from sqlalchemy import func as sa_func
    contract = data_contract_repo.get(db, id=contract_id)
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")

    rows = (
        db.query(
            SchemaObjectDb.id,
            SchemaObjectDb.name,
            SchemaObjectDb.physical_name,
            SchemaObjectDb.business_name,
            SchemaObjectDb.physical_type,
            SchemaObjectDb.description,
            sa_func.count(SchemaPropertyDb.id).label("property_count")
        )
        .outerjoin(SchemaPropertyDb, SchemaPropertyDb.object_id == SchemaObjectDb.id)
        .filter(SchemaObjectDb.contract_id == contract_id)
        .group_by(SchemaObjectDb.id)
        .order_by(SchemaObjectDb.name)
        .all()
    )
    return [
        {
            "id": r.id,
            "name": r.name,
            "physicalName": r.physical_name,
            "businessName": r.business_name,
            "physicalType": r.physical_type,
            "description": r.description,
            "propertyCount": r.property_count,
        }
        for r in rows
    ]


@router.post('/data-contracts/{contract_id}/schemas', status_code=201)
async def add_contract_schema(
    contract_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    schema_data: dict = Body(...),
    manager: DataContractsManager = Depends(get_data_contracts_manager),
    _: bool = Depends(PermissionChecker('data-contracts', FeatureAccessLevel.READ_WRITE))
):
    """Append a single schema (with properties) to a contract without touching existing schemas."""
    contract = data_contract_repo.get(db, id=contract_id)
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")

    try:
        manager._create_schema_objects(db, contract_id, [schema_data], current_user)
        db.commit()
        audit_manager.log_action(
            db=db,
            username=current_user.username if current_user else 'anonymous',
            ip_address=request.client.host if request.client else None,
            feature='data-contracts',
            action='ADD_SCHEMA',
            success=True,
            details={'contract_id': contract_id, 'schema_name': schema_data.get("name")}
        )
        return {"status": "ok", "schema_name": schema_data.get("name")}
    except Exception as e:
        db.rollback()
        logger.error("Failed to add schema to contract %s: %s", contract_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to add schema")


@router.delete('/data-contracts/{contract_id}/schemas/{schema_name}', status_code=204)
async def delete_contract_schema(
    contract_id: str,
    schema_name: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    _: bool = Depends(PermissionChecker('data-contracts', FeatureAccessLevel.READ_WRITE))
):
    """Delete a single schema by name, leaving other schemas untouched."""
    contract = data_contract_repo.get(db, id=contract_id)
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")

    schema_obj = (
        db.query(SchemaObjectDb)
        .filter(SchemaObjectDb.contract_id == contract_id, SchemaObjectDb.name == schema_name)
        .first()
    )
    if not schema_obj:
        raise HTTPException(status_code=404, detail=f"Schema '{schema_name}' not found")

    try:
        db.query(SchemaObjectDb).filter(SchemaObjectDb.id == schema_obj.id).delete()
        db.commit()
        audit_manager.log_action(
            db=db,
            username=current_user.username if current_user else 'anonymous',
            ip_address=request.client.host if request.client else None,
            feature='data-contracts',
            action='DELETE_SCHEMA',
            success=True,
            details={'contract_id': contract_id, 'schema_name': schema_name}
        )
    except Exception as e:
        db.rollback()
        logger.error("Failed to delete schema '%s' from contract %s: %s", schema_name, contract_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to delete schema")


@router.get('/data-contracts/{contract_id}/schemas/{schema_name}/properties')
async def get_schema_properties(
    contract_id: str,
    schema_name: str,
    db: DBSessionDep,
    skip: int = 0,
    limit: int = 50,
    _: bool = Depends(PermissionChecker('data-contracts', FeatureAccessLevel.READ_ONLY))
):
    """Get paginated properties for a specific schema object.

    Use limit=0 to return all properties without pagination (e.g. for the edit dialog).
    """
    from sqlalchemy import func as sa_func

    schema_obj = (
        db.query(SchemaObjectDb)
        .filter(SchemaObjectDb.contract_id == contract_id, SchemaObjectDb.name == schema_name)
        .first()
    )
    if not schema_obj:
        raise HTTPException(status_code=404, detail=f"Schema '{schema_name}' not found")

    total = db.query(sa_func.count(SchemaPropertyDb.id)).filter(SchemaPropertyDb.object_id == schema_obj.id).scalar()

    query = (
        db.query(SchemaPropertyDb)
        .filter(SchemaPropertyDb.object_id == schema_obj.id)
        .order_by(SchemaPropertyDb.name)
    )
    if limit > 0:
        query = query.offset(skip).limit(limit)
    props = query.all()

    items = []
    for p in props:
        options = {}
        if p.logical_type_options_json:
            try:
                options = json.loads(p.logical_type_options_json)
            except Exception:
                pass
        item = {
            "name": p.name,
            "logicalType": p.logical_type or "string",
            "physicalType": p.physical_type,
            "required": p.required,
            "unique": p.unique,
            "primaryKey": p.primary_key,
            "primaryKeyPosition": p.primary_key_position,
            "partitioned": p.partitioned,
            "partitionKeyPosition": p.partition_key_position,
            "classification": p.classification,
            "description": p.transform_description,
            "businessName": p.business_name,
            "criticalDataElement": p.critical_data_element,
            "examples": p.examples,
            "transformLogic": p.transform_logic,
            "transformSourceObjects": p.transform_source_objects,
            "transformDescription": p.transform_description,
            "encryptedName": p.encrypted_name,
        }
        item.update(options)
        items.append(item)

    return {"items": items, "total": total, "skip": skip, "limit": limit}


@router.get('/data-contracts/{contract_id}/odcs/export')
async def export_odcs(contract_id: str, db: DBSessionDep, manager: DataContractsManager = Depends(get_data_contracts_manager), _: bool = Depends(PermissionChecker('data-contracts', FeatureAccessLevel.READ_ONLY))):
    try:
        from fastapi.responses import Response

        db_obj = data_contract_repo.get_with_all(db, id=contract_id)
        if not db_obj:
            raise HTTPException(status_code=404, detail="Contract not found")
        odcs = manager.build_odcs_from_db(db_obj, db)

        # Convert to YAML format for ODCS compliance
        yaml_content = yaml.dump(odcs, default_flow_style=False, allow_unicode=True, sort_keys=False)
        
        # SECURITY: Sanitize filename for header to prevent injection
        raw_filename = f"{(db_obj.name or 'contract').lower().replace(' ', '_')}-odcs.yaml"
        safe_filename = sanitize_filename_for_header(raw_filename, default="contract-odcs.yaml")

        return Response(
            content=yaml_content,
            media_type='application/x-yaml',
            headers={
                'Content-Disposition': f'attachment; filename="{safe_filename}"',
                'Content-Type': 'application/x-yaml; charset=utf-8'
            }
        )
    except Exception as e:
        logger.exception("Failed to list versions for contract %s", contract_id)
        raise HTTPException(status_code=500, detail="Failed to list versions")

@router.post('/data-contracts/{contract_id}/link-assets', response_model=dict)
async def auto_link_contract_schema_to_assets(
    contract_id: str,
    db: DBSessionDep,
    current_user: AuditCurrentUserDep,
    manager: DataContractsManager = Depends(get_data_contracts_manager),
    _: bool = Depends(PermissionChecker('data-contracts', FeatureAccessLevel.READ_WRITE)),
):
    """Auto-link contract schema objects to matching Table/View assets.

    Creates implementsContract relationships from assets to this contract,
    and governedBy relationships from parent datasets.
    """
    try:
        username = current_user.username if hasattr(current_user, 'username') else str(current_user)
        result = manager.auto_link_schema_to_assets(db, contract_id, username)
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to auto-link schema to assets for contract %s", contract_id)
        raise HTTPException(status_code=500, detail="Failed to auto-link schema to assets")


@router.get('/data-contracts/{contract_id}/entity-relationships', response_model=dict)
async def get_contract_entity_relationships(
    contract_id: str,
    db: DBSessionDep,
    manager: DataContractsManager = Depends(get_data_contracts_manager),
    _: bool = Depends(PermissionChecker('data-contracts', FeatureAccessLevel.READ_ONLY)),
):
    """Get entity relationships involving this contract (incoming governedBy, etc.)."""
    try:
        db_obj = data_contract_repo.get(db, id=contract_id)
        if not db_obj:
            raise HTTPException(status_code=404, detail="Contract not found")
        return manager.get_contract_entity_relationships(db, contract_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to get entity relationships for contract %s", contract_id)
        raise HTTPException(status_code=500, detail="Failed to get entity relationships")


@router.post('/data-contracts/{contract_id}/comments', response_model=dict)
async def add_comment(
    contract_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    payload: DataContractCommentCreate = Body(...),
    _: bool = Depends(PermissionChecker('data-contracts', FeatureAccessLevel.READ_WRITE))
):
    success = False
    response_status_code = 500
    details_for_audit = {
        "params": {"contract_id": contract_id},
    }
    try:
        if not data_contract_repo.get(db, id=contract_id):
            response_status_code = 404
            exc = HTTPException(status_code=response_status_code, detail="Contract not found")
            details_for_audit["exception"] = {"type": "HTTPException", "status_code": exc.status_code, "detail": exc.detail}
            raise exc
        message = payload.message
        if not message:
            response_status_code = 400
            exc = HTTPException(status_code=response_status_code, detail="message is required")
            details_for_audit["exception"] = {"type": "HTTPException", "status_code": exc.status_code, "detail": exc.detail}
            raise exc
        db.add(DataContractCommentDb(contract_id=contract_id, author=current_user.username if current_user else 'anonymous', message=message))
        db.commit()
        success = True
        response_status_code = 200
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        success = False
        response_status_code = 500
        logger.exception("Failed to add comment to contract %s", contract_id)
        details_for_audit["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise HTTPException(status_code=500, detail="Failed to add comment")
    finally:
        if "exception" not in details_for_audit:
            details_for_audit["response_status_code"] = response_status_code
        audit_manager.log_action(
            db=db,
            username=current_user.username if current_user else "anonymous",
            ip_address=request.client.host if request.client else None,
            feature="data-contracts",
            action="COMMENT",
            success=success,
            details=details_for_audit,
        )


@router.get('/data-contracts/{contract_id}/comments', response_model=list[DataContractCommentRead])
async def list_comments(contract_id: str, db: DBSessionDep, _: bool = Depends(PermissionChecker('data-contracts', FeatureAccessLevel.READ_ONLY))):
    try:
        comments = db.query(DataContractCommentDb).filter(DataContractCommentDb.contract_id == contract_id).order_by(DataContractCommentDb.created_at.asc()).all()
        return [
            DataContractCommentRead(
                id=c.id,
                author=c.author,
                message=c.message,
                created_at=c.created_at.isoformat() if c.created_at else None,
            )
            for c in comments
        ]
    except Exception as e:
        logger.exception("Failed to list comments for contract %s", contract_id)
        raise HTTPException(status_code=500, detail="Failed to list comments")


@router.post('/data-contracts/{contract_id}/versions')
async def create_version(
    contract_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    payload: dict = Body(...),
    manager: DataContractsManager = Depends(get_data_contracts_manager),
    _: bool = Depends(PermissionChecker('data-contracts', FeatureAccessLevel.READ_WRITE))
):
    """Create a new version of a contract (lightweight, metadata only)."""
    success = False
    response_status_code = 500
    details_for_audit = {"params": {"contract_id": contract_id}}
    
    try:
        new_version = payload.get('new_version')
        if not new_version:
            response_status_code = 400
            raise HTTPException(status_code=400, detail="new_version is required")
        
        # Business logic now in manager
        clone = manager.create_new_version(
            db=db,
            contract_id=contract_id,
            new_version=new_version,
            current_user=current_user.username if current_user else None
        )
        
        success = True
        response_status_code = 201
        return {
            "id": clone.id,
            "name": clone.name,
            "version": clone.version,
            "status": clone.status,
            "owner_team_id": clone.owner_team_id
        }
    except ValueError as e:
        response_status_code = 404 if "not found" in str(e).lower() else 400
        logger.error("Validation error creating version for contract %s: %s", contract_id, e)
        details_for_audit["exception"] = {"type": "ValueError", "message": str(e)}
        raise HTTPException(status_code=response_status_code, detail="Invalid version data")
    except HTTPException:
        raise
    except Exception as e:
        response_status_code = 500
        logger.exception("Failed to create version for contract %s", contract_id)
        details_for_audit["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise HTTPException(status_code=500, detail="Failed to create version")
    finally:
        if "exception" not in details_for_audit:
            details_for_audit["response_status_code"] = response_status_code
        if success:
            details_for_audit["created_version_for_contract_id"] = contract_id
        audit_manager.log_action(
            db=db,
            username=current_user.username if current_user else "anonymous",
            ip_address=request.client.host if request.client else None,
            feature="data-contracts",
            action="VERSION",
            success=success,
            details=details_for_audit,
        )

# DQX Profiling endpoints

@router.post('/data-contracts/{contract_id}/profile')
async def start_profiling(
    contract_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    payload: dict = Body(...),
    manager: DataContractsManager = Depends(get_data_contracts_manager),
    jobs_manager = Depends(get_jobs_manager),
    _: bool = Depends(PermissionChecker('data-contracts', FeatureAccessLevel.READ_WRITE))
):
    """Start DQX profiling for selected schemas in a contract."""
    try:
        result = manager.start_profiling(
            db=db,
            contract_id=contract_id,
            schema_names=payload.get('schema_names', []),
            triggered_by=current_user.username if current_user else 'unknown',
            jobs_manager=jobs_manager
        )
        
        audit_manager.log_action(
            db=db,
            username=current_user.username if current_user else 'unknown',
            ip_address=request.client.host if request.client else None,
            feature='data-contracts',
            action='START_PROFILING',
            success=True,
            details={'contract_id': contract_id, 'schema_names': payload.get('schema_names', [])}
        )
        
        return result
    except ValueError as e:
        logger.error("Validation error starting profiling for contract %s: %s", contract_id, e)
        raise HTTPException(status_code=400, detail="Invalid profiling request")
    except Exception as e:
        logger.error("Failed to start profiling for contract %s", contract_id, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to start profiling")


@router.get('/data-contracts/{contract_id}/profile-runs')
async def get_profile_runs(
    contract_id: str,
    db: DBSessionDep,
    manager: DataContractsManager = Depends(get_data_contracts_manager),
    jobs_manager = Depends(get_jobs_manager),
    _: bool = Depends(PermissionChecker('data-contracts', FeatureAccessLevel.READ_ONLY))
):
    """Get profiling runs for a contract with suggestion counts."""
    try:
        result = manager.get_profile_runs(
            db=db,
            contract_id=contract_id,
            jobs_manager=jobs_manager
        )
        return result
    except ValueError as e:
        logger.error("Validation error getting profile runs for contract %s: %s", contract_id, e)
        raise HTTPException(status_code=404, detail="Contract not found")
    except Exception as e:
        logger.error("Failed to get profile runs for contract %s", contract_id, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get profile runs")


@router.get('/data-contracts/{contract_id}/profile-runs/{run_id}/suggestions')
async def get_suggestions(
    contract_id: str,
    run_id: str,
    db: DBSessionDep,
    manager: DataContractsManager = Depends(get_data_contracts_manager),
    _: bool = Depends(PermissionChecker('data-contracts', FeatureAccessLevel.READ_ONLY))
):
    """Get quality check suggestions for a profiling run."""
    try:
        result = manager.get_profile_suggestions(
            db=db,
            contract_id=contract_id,
            run_id=run_id
        )
        return result
    except ValueError as e:
        logger.error("Validation error getting suggestions for contract %s run %s: %s", contract_id, run_id, e)
        raise HTTPException(status_code=404, detail="Profile run not found")
    except Exception as e:
        logger.error("Failed to get suggestions for contract %s run %s", contract_id, run_id, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get suggestions")


@router.post('/data-contracts/{contract_id}/suggestions/accept')
async def accept_suggestions(
    contract_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    payload: dict = Body(...),
    manager: DataContractsManager = Depends(get_data_contracts_manager),
    _: bool = Depends(PermissionChecker('data-contracts', FeatureAccessLevel.READ_WRITE))
):
    """Accept quality check suggestions and add them to the contract."""
    try:
        result = manager.accept_suggestions(
            db=db,
            contract_id=contract_id,
            suggestion_ids=payload.get('suggestion_ids', []),
            bump_version=payload.get('bump_version'),
            current_user=current_user.username if current_user else 'anonymous',
            audit_manager=audit_manager
        )
        
        # Update audit log with IP address (manager doesn't have access to request)
        if audit_manager and request.client:
            # The audit log was already created in the manager, just noting this for future reference
            pass
        
        return result
    except ValueError as e:
        logger.error("Validation error accepting suggestions for contract %s: %s", contract_id, e)
        raise HTTPException(status_code=400, detail="Invalid suggestion request")
    except Exception as e:
        logger.error("Failed to accept suggestions for contract %s", contract_id, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to accept suggestions")


@router.put('/data-contracts/{contract_id}/suggestions/{suggestion_id}')
async def update_suggestion(
    contract_id: str,
    suggestion_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    payload: dict = Body(...),
    manager: DataContractsManager = Depends(get_data_contracts_manager),
    _: bool = Depends(PermissionChecker('data-contracts', FeatureAccessLevel.READ_WRITE))
):
    """Update a quality check suggestion (for editing before acceptance)."""
    try:
        result = manager.update_suggestion(
            db=db,
            contract_id=contract_id,
            suggestion_id=suggestion_id,
            updates=payload
        )
        
        audit_manager.log_action(
            db=db,
            username=current_user.username if current_user else 'unknown',
            ip_address=request.client.host if request.client else None,
            feature='data-contracts',
            action='UPDATE_SUGGESTION',
            success=True,
            details={'contract_id': contract_id, 'suggestion_id': suggestion_id}
        )
        
        return result
    except ValueError as e:
        logger.error("Validation error updating suggestion %s for contract %s: %s", suggestion_id, contract_id, e)
        raise HTTPException(status_code=404, detail="Suggestion not found")
    except Exception as e:
        logger.error("Failed to update suggestion %s for contract %s", suggestion_id, contract_id, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to update suggestion")


@router.post('/data-contracts/{contract_id}/suggestions/reject')
async def reject_suggestions(
    contract_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    payload: dict = Body(...),
    manager: DataContractsManager = Depends(get_data_contracts_manager),
    _: bool = Depends(PermissionChecker('data-contracts', FeatureAccessLevel.READ_WRITE))
):
    """Reject quality check suggestions."""
    try:
        result = manager.reject_suggestions(
            db=db,
            contract_id=contract_id,
            suggestion_ids=payload.get('suggestion_ids', []),
            current_user=current_user.username if current_user else 'anonymous',
            audit_manager=audit_manager
        )
        return result
    except ValueError as e:
        logger.error("Validation error rejecting suggestions for contract %s: %s", contract_id, e)
        raise HTTPException(status_code=400, detail="Invalid rejection request")
    except Exception as e:
        logger.error("Failed to reject suggestions for contract %s", contract_id, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to reject suggestions")


# ===== Custom Properties CRUD Endpoints =====

@router.get('/data-contracts/{contract_id}/custom-properties', response_model=List[dict])
async def get_custom_properties(
    contract_id: str,
    db: DBSessionDep,
    _: bool = Depends(PermissionChecker('data-contracts', FeatureAccessLevel.READ_ONLY))
):
    """Get all custom properties for a contract."""
    from src.repositories.data_contracts_repository import custom_property_repo
    from src.models.data_contracts_api import CustomPropertyRead

    contract = data_contract_repo.get(db, id=contract_id)
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")

    try:
        properties = custom_property_repo.get_by_contract(db=db, contract_id=contract_id)
        return [CustomPropertyRead.model_validate(prop).model_dump() for prop in properties]
    except Exception as e:
        logger.error("Error fetching custom properties for contract %s", contract_id, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch custom properties")


@router.post('/data-contracts/{contract_id}/custom-properties', response_model=dict, status_code=201)
async def create_custom_property(
    contract_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    prop_data: dict = Body(...),
    manager: DataContractsManager = Depends(get_data_contracts_manager),
    _: bool = Depends(PermissionChecker('data-contracts', FeatureAccessLevel.READ_WRITE))
):
    """Create a custom property."""
    from src.models.data_contracts_api import CustomPropertyCreate, CustomPropertyRead

    try:
        prop_create = CustomPropertyCreate(**prop_data)
        
        # Business logic now in manager
        new_prop = manager.create_custom_property(
            db=db,
            contract_id=contract_id,
            property_data={"property": prop_create.property, "value": prop_create.value}
        )

        audit_manager.log_action(
            db=db,
            username=current_user.username if current_user else "anonymous",
            ip_address=request.client.host if request.client else None,
            feature="data-contracts",
            action="CREATE_CUSTOM_PROPERTY",
            success=True,
            details={"contract_id": contract_id, "property": prop_create.property}
        )

        return CustomPropertyRead.model_validate(new_prop).model_dump()
    except ValueError as e:
        logger.error("Validation error creating custom property for contract %s: %s", contract_id, e)
        raise HTTPException(status_code=404, detail="Contract not found")
    except Exception as e:
        logger.error("Error creating custom property for contract %s", contract_id, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to create custom property")


@router.put('/data-contracts/{contract_id}/custom-properties/{property_id}', response_model=dict)
async def update_custom_property(
    contract_id: str,
    property_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    prop_data: dict = Body(...),
    manager: DataContractsManager = Depends(get_data_contracts_manager),
    _: bool = Depends(PermissionChecker('data-contracts', FeatureAccessLevel.READ_WRITE))
):
    """Update a custom property."""
    from src.models.data_contracts_api import CustomPropertyRead

    try:
        # Business logic now in manager
        updated_prop = manager.update_custom_property(
            db=db,
            contract_id=contract_id,
            property_id=property_id,
            property_data=prop_data
        )

        audit_manager.log_action(
            db=db,
            username=current_user.username if current_user else "anonymous",
            ip_address=request.client.host if request.client else None,
            feature="data-contracts",
            action="UPDATE_CUSTOM_PROPERTY",
            success=True,
            details={"contract_id": contract_id, "property_id": property_id}
        )

        return CustomPropertyRead.model_validate(updated_prop).model_dump()
    except ValueError as e:
        logger.error("Validation error updating custom property %s for contract %s: %s", property_id, contract_id, e)
        raise HTTPException(status_code=404, detail="Property not found")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error updating custom property %s for contract %s", property_id, contract_id, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to update custom property")


@router.delete('/data-contracts/{contract_id}/custom-properties/{property_id}', status_code=204)
async def delete_custom_property(
    contract_id: str,
    property_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager: DataContractsManager = Depends(get_data_contracts_manager),
    _: bool = Depends(PermissionChecker('data-contracts', FeatureAccessLevel.READ_WRITE))
):
    """Delete a custom property."""
    try:
        # Business logic now in manager
        manager.delete_custom_property(
            db=db,
            contract_id=contract_id,
            property_id=property_id
        )

        audit_manager.log_action(
            db=db,
            username=current_user.username if current_user else "anonymous",
            ip_address=request.client.host if request.client else None,
            feature="data-contracts",
            action="DELETE_CUSTOM_PROPERTY",
            success=True,
            details={"contract_id": contract_id, "property_id": property_id}
        )

        return None
    except ValueError as e:
        logger.error("Validation error deleting custom property %s for contract %s: %s", property_id, contract_id, e)
        raise HTTPException(status_code=404, detail="Property not found")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error deleting custom property %s for contract %s", property_id, contract_id, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to delete custom property")


# ===== Support Channels CRUD Endpoints (ODCS support[]) =====

@router.get('/data-contracts/{contract_id}/support', response_model=List[dict])
async def get_support_channels(
    contract_id: str,
    db: DBSessionDep,
    _: bool = Depends(PermissionChecker('data-contracts', FeatureAccessLevel.READ_ONLY))
):
    """Get all support channels for a contract."""
    from src.repositories.data_contracts_repository import support_channel_repo
    from src.models.data_contracts_api import SupportChannelRead

    contract = data_contract_repo.get(db, id=contract_id)
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")

    try:
        channels = support_channel_repo.get_by_contract(db=db, contract_id=contract_id)
        return [SupportChannelRead.model_validate(ch).model_dump() for ch in channels]
    except Exception as e:
        logger.error("Error fetching support channels for contract %s", contract_id, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch support channels")


@router.post('/data-contracts/{contract_id}/support', response_model=dict, status_code=201)
async def create_support_channel(
    contract_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    channel_data: dict = Body(...),
    manager: DataContractsManager = Depends(get_data_contracts_manager),
    _: bool = Depends(PermissionChecker('data-contracts', FeatureAccessLevel.READ_WRITE))
):
    """Create a new support channel for a contract."""
    from src.models.data_contracts_api import SupportChannelRead

    try:
        # Business logic now in manager
        new_channel = manager.create_support_channel(
            db=db,
            contract_id=contract_id,
            channel_data=channel_data
        )

        # Audit log
        audit_manager.log_action(
            db=db,
            username=current_user.username if current_user else 'anonymous',
            ip_address=request.client.host if request.client else None,
            feature='data-contracts',
            action='CREATE_SUPPORT_CHANNEL',
            success=True,
            details={"contract_id": contract_id, "channel_id": new_channel.id, "channel": new_channel.channel}
        )

        return SupportChannelRead.model_validate(new_channel).model_dump()
    except ValueError as e:
        logger.error("Validation error creating support channel for contract %s: %s", contract_id, e)
        raise HTTPException(status_code=404, detail="Contract not found or invalid data")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error creating support channel for contract %s", contract_id, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to create support channel")


@router.put('/data-contracts/{contract_id}/support/{channel_id}', response_model=dict)
async def update_support_channel(
    contract_id: str,
    channel_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    channel_data: dict = Body(...),
    manager: DataContractsManager = Depends(get_data_contracts_manager),
    _: bool = Depends(PermissionChecker('data-contracts', FeatureAccessLevel.READ_WRITE))
):
    """Update a support channel."""
    from src.models.data_contracts_api import SupportChannelRead

    try:
        # Business logic now in manager
        updated_channel = manager.update_support_channel(
            db=db,
            contract_id=contract_id,
            channel_id=channel_id,
            channel_data=channel_data
        )

        # Audit log
        audit_manager.log_action(
            db=db,
            username=current_user.username if current_user else 'anonymous',
            ip_address=request.client.host if request.client else None,
            feature='data-contracts',
            action='UPDATE_SUPPORT_CHANNEL',
            success=True,
            details={"contract_id": contract_id, "channel_id": channel_id}
        )

        return SupportChannelRead.model_validate(updated_channel).model_dump()
    except ValueError as e:
        logger.error("Validation error updating support channel %s for contract %s: %s", channel_id, contract_id, e)
        raise HTTPException(status_code=404, detail="Contract or channel not found")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error updating support channel %s for contract %s", channel_id, contract_id, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to update support channel")


@router.delete('/data-contracts/{contract_id}/support/{channel_id}', status_code=204)
async def delete_support_channel(
    contract_id: str,
    channel_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager: DataContractsManager = Depends(get_data_contracts_manager),
    _: bool = Depends(PermissionChecker('data-contracts', FeatureAccessLevel.READ_WRITE))
):
    """Delete a support channel."""
    try:
        # Business logic now in manager
        manager.delete_support_channel(
            db=db,
            contract_id=contract_id,
            channel_id=channel_id
        )

        # Audit log
        audit_manager.log_action(
            db=db,
            username=current_user.username if current_user else 'anonymous',
            ip_address=request.client.host if request.client else None,
            feature='data-contracts',
            action='DELETE_SUPPORT_CHANNEL',
            success=True,
            details={"contract_id": contract_id, "channel_id": channel_id}
        )

        return None
    except ValueError as e:
        logger.error("Validation error deleting support channel %s for contract %s: %s", channel_id, contract_id, e)
        raise HTTPException(status_code=404, detail="Contract or channel not found")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error deleting support channel %s for contract %s", channel_id, contract_id, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to delete support channel")


# ===== Pricing Endpoints (ODCS price) - Singleton Pattern =====

@router.get('/data-contracts/{contract_id}/pricing', response_model=dict)
async def get_pricing(
    contract_id: str,
    db: DBSessionDep,
    _: bool = Depends(PermissionChecker('data-contracts', FeatureAccessLevel.READ_ONLY))
):
    """Get pricing for a contract (returns empty object if not set)."""
    from src.repositories.data_contracts_repository import pricing_repo
    from src.models.data_contracts_api import PricingRead

    contract = data_contract_repo.get(db, id=contract_id)
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")

    try:
        pricing = pricing_repo.get_pricing(db=db, contract_id=contract_id)
        if pricing:
            return PricingRead.model_validate(pricing).model_dump()
        else:
            # Return empty pricing structure
            return {
                "id": None,
                "contract_id": contract_id,
                "price_amount": None,
                "price_currency": None,
                "price_unit": None
            }
    except Exception as e:
        logger.error("Error fetching pricing for contract %s", contract_id, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch pricing")


@router.put('/data-contracts/{contract_id}/pricing', response_model=dict)
async def update_pricing(
    contract_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    pricing_data: dict = Body(...),
    manager: DataContractsManager = Depends(get_data_contracts_manager),
    _: bool = Depends(PermissionChecker('data-contracts', FeatureAccessLevel.READ_WRITE))
):
    """Update pricing for a contract (creates if not exists - singleton pattern)."""
    from src.models.data_contracts_api import PricingRead

    try:
        # Business logic now in manager
        updated_pricing = manager.update_pricing(
            db=db,
            contract_id=contract_id,
            pricing_data=pricing_data
        )

        # Audit log
        audit_manager.log_action(
            db=db,
            username=current_user.username if current_user else 'anonymous',
            ip_address=request.client.host if request.client else None,
            feature='data-contracts',
            action='UPDATE_PRICING',
            success=True,
            details={
                "contract_id": contract_id,
                "price_amount": pricing_data.get("price_amount"),
                "price_currency": pricing_data.get("price_currency"),
                "price_unit": pricing_data.get("price_unit")
            }
        )

        return PricingRead.model_validate(updated_pricing).model_dump()
    except ValueError as e:
        logger.error("Validation error updating pricing for contract %s: %s", contract_id, e)
        raise HTTPException(status_code=404, detail="Contract not found")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error updating pricing for contract %s", contract_id, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to update pricing")


# ===== Roles CRUD Endpoints (ODCS roles[]) - With Nested Properties =====

@router.get('/data-contracts/{contract_id}/roles', response_model=List[dict])
async def get_roles(
    contract_id: str,
    db: DBSessionDep,
    _: bool = Depends(PermissionChecker('data-contracts', FeatureAccessLevel.READ_ONLY))
):
    """Get all roles for a contract (with nested properties)."""
    from src.repositories.data_contracts_repository import role_repo
    from src.models.data_contracts_api import RoleRead

    contract = data_contract_repo.get(db, id=contract_id)
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")

    try:
        roles = role_repo.get_by_contract(db=db, contract_id=contract_id)
        return [RoleRead.model_validate(r).model_dump() for r in roles]
    except Exception as e:
        logger.error("Error fetching roles for contract %s", contract_id, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch roles")


@router.post('/data-contracts/{contract_id}/roles', response_model=dict, status_code=201)
async def create_role(
    contract_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    role_data: dict = Body(...),
    _: bool = Depends(PermissionChecker('data-contracts', FeatureAccessLevel.READ_WRITE))
):
    """Create a new role for a contract (with optional nested properties)."""
    from src.repositories.data_contracts_repository import role_repo
    from src.models.data_contracts_api import RoleCreate, RoleRead

    contract = data_contract_repo.get(db, id=contract_id)
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")

    try:
        # Validate input
        role_create = RoleCreate(**role_data)

        # Convert nested properties to dict format
        custom_props = None
        if role_create.custom_properties:
            custom_props = [prop.model_dump() for prop in role_create.custom_properties]

        # Create role with nested properties
        new_role = role_repo.create_role(
            db=db,
            contract_id=contract_id,
            role=role_create.role,
            description=role_create.description,
            access=role_create.access,
            first_level_approvers=role_create.first_level_approvers,
            second_level_approvers=role_create.second_level_approvers,
            custom_properties=custom_props
        )

        db.commit()

        # Audit log
        audit_manager.log_action(
            db=db,
            username=current_user.username if current_user else 'anonymous',
            ip_address=request.client.host if request.client else None,
            feature='data-contracts',
            action='CREATE_ROLE',
            success=True,
            details={"contract_id": contract_id, "role_id": new_role.id, "role": new_role.role}
        )

        return RoleRead.model_validate(new_role).model_dump()
    except HTTPException:
        raise
    except ValueError as e:
        logger.error("Validation error creating role for contract %s: %s", contract_id, e)
        raise HTTPException(status_code=400, detail="Invalid role data")
    except Exception as e:
        db.rollback()
        logger.error("Error creating role for contract %s", contract_id, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to create role")


@router.put('/data-contracts/{contract_id}/roles/{role_id}', response_model=dict)
async def update_role(
    contract_id: str,
    role_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    role_data: dict = Body(...),
    _: bool = Depends(PermissionChecker('data-contracts', FeatureAccessLevel.READ_WRITE))
):
    """Update a role (replaces nested properties if provided)."""
    from src.repositories.data_contracts_repository import role_repo
    from src.models.data_contracts_api import RoleUpdate, RoleRead

    contract = data_contract_repo.get(db, id=contract_id)
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")

    try:
        # Validate input
        role_update = RoleUpdate(**role_data)

        # Convert nested properties to dict format
        custom_props = None
        if role_update.custom_properties is not None:
            custom_props = [prop.model_dump() for prop in role_update.custom_properties]

        # Update role
        updated_role = role_repo.update_role(
            db=db,
            role_id=role_id,
            role=role_update.role,
            description=role_update.description,
            access=role_update.access,
            first_level_approvers=role_update.first_level_approvers,
            second_level_approvers=role_update.second_level_approvers,
            custom_properties=custom_props
        )

        if not updated_role:
            raise HTTPException(status_code=404, detail="Role not found")

        db.commit()

        # Audit log
        audit_manager.log_action(
            db=db,
            username=current_user.username if current_user else 'anonymous',
            ip_address=request.client.host if request.client else None,
            feature='data-contracts',
            action='UPDATE_ROLE',
            success=True,
            details={"contract_id": contract_id, "role_id": role_id}
        )

        return RoleRead.model_validate(updated_role).model_dump()
    except HTTPException:
        raise
    except ValueError as e:
        logger.error("Validation error updating role %s for contract %s: %s", role_id, contract_id, e)
        raise HTTPException(status_code=400, detail="Invalid role data")
    except Exception as e:
        db.rollback()
        logger.error("Error updating role %s for contract %s", role_id, contract_id, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to update role")


@router.delete('/data-contracts/{contract_id}/roles/{role_id}', status_code=204)
async def delete_role(
    contract_id: str,
    role_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    _: bool = Depends(PermissionChecker('data-contracts', FeatureAccessLevel.READ_WRITE))
):
    """Delete a role (cascade deletes nested properties)."""
    from src.repositories.data_contracts_repository import role_repo

    contract = data_contract_repo.get(db, id=contract_id)
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")

    try:
        deleted = role_repo.delete_role(db=db, role_id=role_id)

        if not deleted:
            raise HTTPException(status_code=404, detail="Role not found")

        db.commit()

        # Audit log
        audit_manager.log_action(
            db=db,
            username=current_user.username if current_user else 'anonymous',
            ip_address=request.client.host if request.client else None,
            feature='data-contracts',
            action='DELETE_ROLE',
            success=True,
            details={"contract_id": contract_id, "role_id": role_id}
        )

        return None
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error("Error deleting role %s for contract %s", role_id, contract_id, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to delete role")


# ===== Contract-Level Authoritative Definitions CRUD (ODCS authoritativeDefinitions[]) =====

@router.get('/data-contracts/{contract_id}/authoritative-definitions', response_model=List[dict])
async def get_contract_authoritative_definitions(
    contract_id: str,
    db: DBSessionDep,
    _: bool = Depends(PermissionChecker('data-contracts', FeatureAccessLevel.READ_ONLY))
):
    """Get all authoritative definitions for a contract."""
    from src.repositories.data_contracts_repository import contract_authoritative_definition_repo
    from src.models.data_contracts_api import AuthoritativeDefinitionRead

    contract = data_contract_repo.get(db, id=contract_id)
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")

    try:
        definitions = contract_authoritative_definition_repo.get_by_contract(db=db, contract_id=contract_id)
        return [AuthoritativeDefinitionRead.model_validate(d).model_dump() for d in definitions]
    except Exception as e:
        logger.error("Error fetching contract authoritative definitions for %s", contract_id, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch authoritative definitions")


@router.post('/data-contracts/{contract_id}/authoritative-definitions', response_model=dict, status_code=201)
async def create_contract_authoritative_definition(
    contract_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    definition_data: dict = Body(...),
    _: bool = Depends(PermissionChecker('data-contracts', FeatureAccessLevel.READ_WRITE))
):
    """Create an authoritative definition for a contract."""
    from src.repositories.data_contracts_repository import contract_authoritative_definition_repo
    from src.models.data_contracts_api import AuthoritativeDefinitionCreate, AuthoritativeDefinitionRead

    contract = data_contract_repo.get(db, id=contract_id)
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")

    try:
        definition_create = AuthoritativeDefinitionCreate(**definition_data)
        new_definition = contract_authoritative_definition_repo.create_definition(
            db=db, contract_id=contract_id, url=definition_create.url, type=definition_create.type
        )
        db.commit()

        audit_manager.log_action(
            db=db,
            username=current_user.username if current_user else 'anonymous',
            ip_address=request.client.host if request.client else None,
            feature='data-contracts',
            action='CREATE_AUTHORITATIVE_DEFINITION',
            success=True,
            details={"contract_id": contract_id, "definition_id": new_definition.id, "url": new_definition.url}
        )

        return AuthoritativeDefinitionRead.model_validate(new_definition).model_dump()
    except HTTPException:
        raise
    except ValueError as e:
        logger.error("Validation error creating authoritative definition for contract %s: %s", contract_id, e)
        raise HTTPException(status_code=400, detail="Invalid definition data")
    except Exception as e:
        db.rollback()
        logger.error("Error creating contract authoritative definition for %s", contract_id, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to create authoritative definition")


@router.put('/data-contracts/{contract_id}/authoritative-definitions/{definition_id}', response_model=dict)
async def update_contract_authoritative_definition(
    contract_id: str,
    definition_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    definition_data: dict = Body(...),
    _: bool = Depends(PermissionChecker('data-contracts', FeatureAccessLevel.READ_WRITE))
):
    """Update an authoritative definition."""
    from src.repositories.data_contracts_repository import contract_authoritative_definition_repo
    from src.models.data_contracts_api import AuthoritativeDefinitionUpdate, AuthoritativeDefinitionRead

    contract = data_contract_repo.get(db, id=contract_id)
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")

    try:
        definition_update = AuthoritativeDefinitionUpdate(**definition_data)
        updated_definition = contract_authoritative_definition_repo.update_definition(
            db=db, definition_id=definition_id, url=definition_update.url, type=definition_update.type
        )

        if not updated_definition:
            raise HTTPException(status_code=404, detail="Authoritative definition not found")

        db.commit()

        audit_manager.log_action(
            db=db,
            username=current_user.username if current_user else 'anonymous',
            ip_address=request.client.host if request.client else None,
            feature='data-contracts',
            action='UPDATE_AUTHORITATIVE_DEFINITION',
            success=True,
            details={"contract_id": contract_id, "definition_id": definition_id}
        )

        return AuthoritativeDefinitionRead.model_validate(updated_definition).model_dump()
    except HTTPException:
        raise
    except ValueError as e:
        logger.error("Validation error updating authoritative definition %s for contract %s: %s", definition_id, contract_id, e)
        raise HTTPException(status_code=400, detail="Invalid definition data")
    except Exception as e:
        db.rollback()
        logger.error("Error updating contract authoritative definition %s for %s", definition_id, contract_id, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to update authoritative definition")


@router.delete('/data-contracts/{contract_id}/authoritative-definitions/{definition_id}', status_code=204)
async def delete_contract_authoritative_definition(
    contract_id: str,
    definition_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    _: bool = Depends(PermissionChecker('data-contracts', FeatureAccessLevel.READ_WRITE))
):
    """Delete an authoritative definition."""
    from src.repositories.data_contracts_repository import contract_authoritative_definition_repo

    contract = data_contract_repo.get(db, id=contract_id)
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")

    try:
        deleted = contract_authoritative_definition_repo.delete_definition(db=db, definition_id=definition_id)

        if not deleted:
            raise HTTPException(status_code=404, detail="Authoritative definition not found")

        db.commit()

        audit_manager.log_action(
            db=db,
            username=current_user.username if current_user else 'anonymous',
            ip_address=request.client.host if request.client else None,
            feature='data-contracts',
            action='DELETE_AUTHORITATIVE_DEFINITION',
            success=True,
            details={"contract_id": contract_id, "definition_id": definition_id}
        )

        return None
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error("Error deleting contract authoritative definition %s for %s", definition_id, contract_id, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to delete authoritative definition")


# ===== Schema-Level Authoritative Definitions CRUD =====

@router.get('/data-contracts/{contract_id}/schemas/{schema_id}/authoritative-definitions', response_model=List[dict])
async def get_schema_authoritative_definitions(
    contract_id: str,
    schema_id: str,
    db: DBSessionDep,
    _: bool = Depends(PermissionChecker('data-contracts', FeatureAccessLevel.READ_ONLY))
):
    """Get all authoritative definitions for a schema object.
    
    The schema_id can be either the schema UUID or the schema name.
    """
    from src.repositories.data_contracts_repository import schema_authoritative_definition_repo
    from src.models.data_contracts_api import AuthoritativeDefinitionRead
    from src.db_models.data_contracts import SchemaObjectDb
    import re

    contract = data_contract_repo.get(db, id=contract_id)
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")

    try:
        # Check if schema_id is a UUID or a name
        uuid_pattern = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.I)
        actual_schema_id = schema_id
        
        if not uuid_pattern.match(schema_id):
            # Treat as schema name, look up the actual ID
            schema_obj = db.query(SchemaObjectDb).filter(
                SchemaObjectDb.contract_id == contract_id,
                SchemaObjectDb.name == schema_id
            ).first()
            if not schema_obj:
                raise HTTPException(status_code=404, detail=f"Schema '{schema_id}' not found")
            actual_schema_id = schema_obj.id
        
        definitions = schema_authoritative_definition_repo.get_by_schema(db=db, schema_id=actual_schema_id)
        return [AuthoritativeDefinitionRead.model_validate(d).model_dump() for d in definitions]
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error fetching schema authoritative definitions for schema %s", schema_id, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch schema authoritative definitions")


@router.post('/data-contracts/{contract_id}/schemas/{schema_id}/authoritative-definitions', response_model=dict, status_code=201)
async def create_schema_authoritative_definition(
    contract_id: str,
    schema_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    definition_data: dict = Body(...),
    _: bool = Depends(PermissionChecker('data-contracts', FeatureAccessLevel.READ_WRITE))
):
    """Create an authoritative definition for a schema object."""
    from src.repositories.data_contracts_repository import schema_authoritative_definition_repo
    from src.models.data_contracts_api import AuthoritativeDefinitionCreate, AuthoritativeDefinitionRead

    contract = data_contract_repo.get(db, id=contract_id)
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")

    try:
        definition_create = AuthoritativeDefinitionCreate(**definition_data)
        new_definition = schema_authoritative_definition_repo.create_definition(
            db=db, schema_id=schema_id, url=definition_create.url, type=definition_create.type
        )
        db.commit()

        audit_manager.log_action(
            db=db,
            username=current_user.username if current_user else 'anonymous',
            ip_address=request.client.host if request.client else None,
            feature='data-contracts',
            action='CREATE_SCHEMA_AUTHORITATIVE_DEFINITION',
            success=True,
            details={"contract_id": contract_id, "schema_id": schema_id, "definition_id": new_definition.id}
        )

        return AuthoritativeDefinitionRead.model_validate(new_definition).model_dump()
    except HTTPException:
        raise
    except ValueError as e:
        logger.error("Validation error creating schema authoritative definition for schema %s: %s", schema_id, e)
        raise HTTPException(status_code=400, detail="Invalid definition data")
    except Exception as e:
        db.rollback()
        logger.error("Error creating schema authoritative definition for schema %s", schema_id, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to create schema authoritative definition")


@router.put('/data-contracts/{contract_id}/schemas/{schema_id}/authoritative-definitions/{definition_id}', response_model=dict)
async def update_schema_authoritative_definition(
    contract_id: str,
    schema_id: str,
    definition_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    definition_data: dict = Body(...),
    _: bool = Depends(PermissionChecker('data-contracts', FeatureAccessLevel.READ_WRITE))
):
    """Update a schema-level authoritative definition."""
    from src.repositories.data_contracts_repository import schema_authoritative_definition_repo
    from src.models.data_contracts_api import AuthoritativeDefinitionUpdate, AuthoritativeDefinitionRead

    contract = data_contract_repo.get(db, id=contract_id)
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")

    try:
        definition_update = AuthoritativeDefinitionUpdate(**definition_data)
        updated_definition = schema_authoritative_definition_repo.update_definition(
            db=db, definition_id=definition_id, url=definition_update.url, type=definition_update.type
        )

        if not updated_definition:
            raise HTTPException(status_code=404, detail="Authoritative definition not found")

        db.commit()

        audit_manager.log_action(
            db=db,
            username=current_user.username if current_user else 'anonymous',
            ip_address=request.client.host if request.client else None,
            feature='data-contracts',
            action='UPDATE_SCHEMA_AUTHORITATIVE_DEFINITION',
            success=True,
            details={"contract_id": contract_id, "schema_id": schema_id, "definition_id": definition_id}
        )

        return AuthoritativeDefinitionRead.model_validate(updated_definition).model_dump()
    except HTTPException:
        raise
    except ValueError as e:
        logger.error("Validation error updating schema authoritative definition %s for schema %s: %s", definition_id, schema_id, e)
        raise HTTPException(status_code=400, detail="Invalid definition data")
    except Exception as e:
        db.rollback()
        logger.error("Error updating schema authoritative definition %s for schema %s", definition_id, schema_id, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to update schema authoritative definition")


@router.delete('/data-contracts/{contract_id}/schemas/{schema_id}/authoritative-definitions/{definition_id}', status_code=204)
async def delete_schema_authoritative_definition(
    contract_id: str,
    schema_id: str,
    definition_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    _: bool = Depends(PermissionChecker('data-contracts', FeatureAccessLevel.READ_WRITE))
):
    """Delete a schema-level authoritative definition."""
    from src.repositories.data_contracts_repository import schema_authoritative_definition_repo

    contract = data_contract_repo.get(db, id=contract_id)
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")

    try:
        deleted = schema_authoritative_definition_repo.delete_definition(db=db, definition_id=definition_id)

        if not deleted:
            raise HTTPException(status_code=404, detail="Authoritative definition not found")

        db.commit()

        audit_manager.log_action(
            db=db,
            username=current_user.username if current_user else 'anonymous',
            ip_address=request.client.host if request.client else None,
            feature='data-contracts',
            action='DELETE_SCHEMA_AUTHORITATIVE_DEFINITION',
            success=True,
            details={"contract_id": contract_id, "schema_id": schema_id, "definition_id": definition_id}
        )

        return None
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error("Error deleting schema authoritative definition %s for schema %s", definition_id, schema_id, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to delete schema authoritative definition")


# ===== Property-Level Authoritative Definitions CRUD =====

@router.get('/data-contracts/{contract_id}/schemas/{schema_id}/properties/{property_id}/authoritative-definitions', response_model=List[dict])
async def get_property_authoritative_definitions(
    contract_id: str,
    schema_id: str,
    property_id: str,
    db: DBSessionDep,
    _: bool = Depends(PermissionChecker('data-contracts', FeatureAccessLevel.READ_ONLY))
):
    """Get all authoritative definitions for a schema property."""
    from src.repositories.data_contracts_repository import property_authoritative_definition_repo
    from src.models.data_contracts_api import AuthoritativeDefinitionRead

    contract = data_contract_repo.get(db, id=contract_id)
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")

    try:
        definitions = property_authoritative_definition_repo.get_by_property(db=db, property_id=property_id)
        return [AuthoritativeDefinitionRead.model_validate(d).model_dump() for d in definitions]
    except Exception as e:
        logger.error("Error fetching property authoritative definitions for property %s", property_id, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch property authoritative definitions")


@router.post('/data-contracts/{contract_id}/schemas/{schema_id}/properties/{property_id}/authoritative-definitions', response_model=dict, status_code=201)
async def create_property_authoritative_definition(
    contract_id: str,
    schema_id: str,
    property_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    definition_data: dict = Body(...),
    _: bool = Depends(PermissionChecker('data-contracts', FeatureAccessLevel.READ_WRITE))
):
    """Create an authoritative definition for a schema property."""
    from src.repositories.data_contracts_repository import property_authoritative_definition_repo
    from src.models.data_contracts_api import AuthoritativeDefinitionCreate, AuthoritativeDefinitionRead

    contract = data_contract_repo.get(db, id=contract_id)
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")

    try:
        definition_create = AuthoritativeDefinitionCreate(**definition_data)
        new_definition = property_authoritative_definition_repo.create_definition(
            db=db, property_id=property_id, url=definition_create.url, type=definition_create.type
        )
        db.commit()

        audit_manager.log_action(
            db=db,
            username=current_user.username if current_user else 'anonymous',
            ip_address=request.client.host if request.client else None,
            feature='data-contracts',
            action='CREATE_PROPERTY_AUTHORITATIVE_DEFINITION',
            success=True,
            details={"contract_id": contract_id, "property_id": property_id, "definition_id": new_definition.id}
        )

        return AuthoritativeDefinitionRead.model_validate(new_definition).model_dump()
    except HTTPException:
        raise
    except ValueError as e:
        logger.error("Validation error creating property authoritative definition for property %s: %s", property_id, e)
        raise HTTPException(status_code=400, detail="Invalid definition data")
    except Exception as e:
        db.rollback()
        logger.error("Error creating property authoritative definition for property %s", property_id, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to create property authoritative definition")


@router.put('/data-contracts/{contract_id}/schemas/{schema_id}/properties/{property_id}/authoritative-definitions/{definition_id}', response_model=dict)
async def update_property_authoritative_definition(
    contract_id: str,
    schema_id: str,
    property_id: str,
    definition_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    definition_data: dict = Body(...),
    _: bool = Depends(PermissionChecker('data-contracts', FeatureAccessLevel.READ_WRITE))
):
    """Update a property-level authoritative definition."""
    from src.repositories.data_contracts_repository import property_authoritative_definition_repo
    from src.models.data_contracts_api import AuthoritativeDefinitionUpdate, AuthoritativeDefinitionRead

    contract = data_contract_repo.get(db, id=contract_id)
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")

    try:
        definition_update = AuthoritativeDefinitionUpdate(**definition_data)
        updated_definition = property_authoritative_definition_repo.update_definition(
            db=db, definition_id=definition_id, url=definition_update.url, type=definition_update.type
        )

        if not updated_definition:
            raise HTTPException(status_code=404, detail="Authoritative definition not found")

        db.commit()

        audit_manager.log_action(
            db=db,
            username=current_user.username if current_user else 'anonymous',
            ip_address=request.client.host if request.client else None,
            feature='data-contracts',
            action='UPDATE_PROPERTY_AUTHORITATIVE_DEFINITION',
            success=True,
            details={"contract_id": contract_id, "property_id": property_id, "definition_id": definition_id}
        )

        return AuthoritativeDefinitionRead.model_validate(updated_definition).model_dump()
    except HTTPException:
        raise
    except ValueError as e:
        logger.error("Validation error updating property authoritative definition %s for property %s: %s", definition_id, property_id, e)
        raise HTTPException(status_code=400, detail="Invalid definition data")
    except Exception as e:
        db.rollback()
        logger.error("Error updating property authoritative definition %s for property %s", definition_id, property_id, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to update property authoritative definition")


@router.delete('/data-contracts/{contract_id}/schemas/{schema_id}/properties/{property_id}/authoritative-definitions/{definition_id}', status_code=204)
async def delete_property_authoritative_definition(
    contract_id: str,
    schema_id: str,
    property_id: str,
    definition_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    _: bool = Depends(PermissionChecker('data-contracts', FeatureAccessLevel.READ_WRITE))
):
    """Delete a property-level authoritative definition."""
    from src.repositories.data_contracts_repository import property_authoritative_definition_repo

    contract = data_contract_repo.get(db, id=contract_id)
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")

    try:
        deleted = property_authoritative_definition_repo.delete_definition(db=db, definition_id=definition_id)

        if not deleted:
            raise HTTPException(status_code=404, detail="Authoritative definition not found")

        db.commit()

        audit_manager.log_action(
            db=db,
            username=current_user.username if current_user else 'anonymous',
            ip_address=request.client.host if request.client else None,
            feature='data-contracts',
            action='DELETE_PROPERTY_AUTHORITATIVE_DEFINITION',
            success=True,
            details={"contract_id": contract_id, "property_id": property_id, "definition_id": definition_id}
        )

        return None
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error("Error deleting property authoritative definition %s for property %s", definition_id, property_id, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to delete property authoritative definition")


# ===== Contract Tags CRUD Endpoints =====

@router.get('/data-contracts/{contract_id}/tags', response_model=List[dict])
async def get_contract_tags(
    contract_id: str,
    db: DBSessionDep,
    _: bool = Depends(PermissionChecker('data-contracts', FeatureAccessLevel.READ_ONLY))
):
    """Get all tags for a specific contract."""
    from src.repositories.data_contracts_repository import contract_tag_repo
    from src.models.data_contracts_api import ContractTagRead

    # Verify contract exists
    contract = data_contract_repo.get(db, id=contract_id)
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")

    try:
        tags = contract_tag_repo.get_by_contract(db=db, contract_id=contract_id)
        return [ContractTagRead.model_validate(tag).model_dump() for tag in tags]
    except Exception as e:
        logger.error("Error fetching tags for contract %s", contract_id, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch contract tags")


@router.post('/data-contracts/{contract_id}/tags', response_model=dict, status_code=201)
async def create_contract_tag(
    contract_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    tag_data: dict = Body(...),
    _: bool = Depends(PermissionChecker('data-contracts', FeatureAccessLevel.READ_WRITE))
):
    """Create a new tag for a contract."""
    from src.repositories.data_contracts_repository import contract_tag_repo
    from src.models.data_contracts_api import ContractTagCreate, ContractTagRead

    # Verify contract exists
    contract = data_contract_repo.get(db, id=contract_id)
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")

    try:
        # Validate input
        tag_create = ContractTagCreate(**tag_data)

        # Create tag
        new_tag = contract_tag_repo.create_tag(db=db, contract_id=contract_id, name=tag_create.name)
        db.commit()

        # Audit log
        audit_manager.log_action(
            db=db,
            username=current_user.username if current_user else "anonymous",
            ip_address=request.client.host if request.client else None,
            feature="data-contracts",
            action="CREATE_TAG",
            success=True,
            details={"contract_id": contract_id, "tag_name": tag_create.name}
        )

        return ContractTagRead.model_validate(new_tag).model_dump()

    except ValueError as e:
        logger.error("Validation error creating tag for contract %s: %s", contract_id, e)
        raise HTTPException(status_code=400, detail="Invalid tag data")
    except Exception as e:
        db.rollback()
        logger.error("Error creating tag for contract %s", contract_id, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to create contract tag")


@router.put('/data-contracts/{contract_id}/tags/{tag_id}', response_model=dict)
async def update_contract_tag(
    contract_id: str,
    tag_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    tag_data: dict = Body(...),
    _: bool = Depends(PermissionChecker('data-contracts', FeatureAccessLevel.READ_WRITE))
):
    """Update a contract tag."""
    from src.repositories.data_contracts_repository import contract_tag_repo
    from src.models.data_contracts_api import ContractTagUpdate, ContractTagRead

    # Verify contract exists
    contract = data_contract_repo.get(db, id=contract_id)
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")

    try:
        # Validate input
        tag_update = ContractTagUpdate(**tag_data)

        if tag_update.name is None:
            raise HTTPException(status_code=400, detail="Tag name is required for update")

        # Update tag
        updated_tag = contract_tag_repo.update_tag(db=db, tag_id=tag_id, name=tag_update.name)
        if not updated_tag:
            raise HTTPException(status_code=404, detail="Tag not found")

        # Verify tag belongs to the contract
        if updated_tag.contract_id != contract_id:
            raise HTTPException(status_code=400, detail="Tag does not belong to this contract")

        db.commit()

        # Audit log
        audit_manager.log_action(
            db=db,
            username=current_user.username if current_user else "anonymous",
            ip_address=request.client.host if request.client else None,
            feature="data-contracts",
            action="UPDATE_TAG",
            success=True,
            details={"contract_id": contract_id, "tag_id": tag_id, "new_name": tag_update.name}
        )

        return ContractTagRead.model_validate(updated_tag).model_dump()

    except ValueError as e:
        logger.error("Validation error updating tag %s for contract %s: %s", tag_id, contract_id, e)
        raise HTTPException(status_code=400, detail="Invalid tag data")
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error("Error updating tag %s for contract %s", tag_id, contract_id, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to update contract tag")


@router.delete('/data-contracts/{contract_id}/tags/{tag_id}', status_code=204)
async def delete_contract_tag(
    contract_id: str,
    tag_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    _: bool = Depends(PermissionChecker('data-contracts', FeatureAccessLevel.READ_WRITE))
):
    """Delete a contract tag."""
    from src.repositories.data_contracts_repository import contract_tag_repo

    # Verify contract exists
    contract = data_contract_repo.get(db, id=contract_id)
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")

    try:
        # Get tag first to verify it belongs to this contract
        tag = db.query(DataContractTagDb).filter(DataContractTagDb.id == tag_id).first()
        if not tag:
            raise HTTPException(status_code=404, detail="Tag not found")

        if tag.contract_id != contract_id:
            raise HTTPException(status_code=400, detail="Tag does not belong to this contract")

        # Delete tag
        success = contract_tag_repo.delete_tag(db=db, tag_id=tag_id)
        if not success:
            raise HTTPException(status_code=404, detail="Tag not found")

        db.commit()

        # Audit log
        audit_manager.log_action(
            db=db,
            username=current_user.username if current_user else "anonymous",
            ip_address=request.client.host if request.client else None,
            feature="data-contracts",
            action="DELETE_TAG",
            success=True,
            details={"contract_id": contract_id, "tag_id": tag_id}
        )

        return None

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error("Error deleting tag %s for contract %s", tag_id, contract_id, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to delete contract tag")


# ===== Semantic Versioning Endpoints =====

@router.get('/data-contracts/{contract_id}/versions', response_model=List[dict])
async def get_contract_versions(
    contract_id: str,
    db: DBSessionDep,
    current_user: AuditCurrentUserDep,
    manager: DataContractsManager = Depends(get_data_contracts_manager),
    _: bool = Depends(PermissionChecker('data-contracts', FeatureAccessLevel.READ_ONLY))
):
    """Get every visible version of a contract's family, newest first.

    Grouped by ``version_family_id`` (PRD #442): one indexed equality
    lookup returns every member, regardless of which clone path produced
    them. Personal drafts owned by other users are hidden.
    """
    try:
        from src.common.authorization import is_user_admin
        from src.common.config import get_settings
        user_email = current_user.username if current_user else None
        is_admin = is_user_admin(current_user.groups if current_user else [], get_settings())
        contracts = manager.get_contract_versions(
            db=db,
            contract_id=contract_id,
            user_email=user_email,
            is_admin=is_admin,
        )

        # Map directly to a shape matching the frontend VersionSelector's
        # ContractVersion type — keeps the response tight and skips the
        # heavy eager-loads that DataContractRead would need.
        return [
            {
                "id": c.id,
                "name": c.name,
                "version": c.version,
                "status": c.status,
                "versionFamilyId": c.version_family_id,
                "parentContractId": c.parent_contract_id,
                "baseName": c.base_name,
                "changeSummary": c.change_summary,
                "draftOwnerId": c.draft_owner_id,
                "publicationScope": getattr(c, "publication_scope", None) or "none",
                "createdAt": c.created_at.isoformat() if c.created_at else None,
                "updatedAt": c.updated_at.isoformat() if c.updated_at else None,
            }
            for c in contracts
        ]
    except ValueError as e:
        logger.error("Validation error fetching contract versions for %s: %s", contract_id, e)
        raise HTTPException(status_code=404, detail="Contract not found")
    except Exception as e:
        logger.error("Error fetching contract versions for %s", contract_id, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch contract versions")


@router.post('/data-contracts/{contract_id}/clone', response_model=dict, status_code=201)
async def clone_contract_for_new_version(
    contract_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    body: dict = Body(...),
    manager: DataContractsManager = Depends(get_data_contracts_manager),
    _: bool = Depends(PermissionChecker('data-contracts', FeatureAccessLevel.READ_WRITE))
):
    """Clone a contract to create a new version with all nested entities."""
    new_version = body.get('new_version')
    change_summary = body.get('change_summary')

    if not new_version:
        raise HTTPException(status_code=400, detail="new_version is required")

    try:
        # Business logic now in manager
        new_contract = manager.clone_contract_for_new_version(
            db=db,
            contract_id=contract_id,
            new_version=new_version,
            change_summary=change_summary,
            current_user=current_user.username if current_user else None
        )

        # Audit log
        audit_manager.log_action(
            db=db,
            username=current_user.username if current_user else "anonymous",
            ip_address=request.client.host if request.client else None,
            feature="data-contracts",
            action="CLONE_VERSION",
            success=True,
            details={
                "source_contract_id": contract_id,
                "new_contract_id": new_contract.id,
                "new_version": new_version,
                "change_summary": change_summary
            }
        )

        # Return new contract
        from src.models.data_contracts_api import DataContractRead
        return DataContractRead.model_validate(new_contract).model_dump()

    except ValueError as e:
        logger.error("Validation error cloning contract %s: %s", contract_id, e)
        raise HTTPException(status_code=400, detail="Invalid contract data")
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Error cloning contract %s", contract_id, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to clone contract")


@router.post('/data-contracts/compare', response_model=dict)
async def compare_contract_versions(
    body: dict = Body(...),
    manager: DataContractsManager = Depends(get_data_contracts_manager),
    _: bool = Depends(PermissionChecker('data-contracts', FeatureAccessLevel.READ_ONLY))
):
    """Analyze changes between two contract versions and recommend version bump."""
    old_contract = body.get('old_contract')
    new_contract = body.get('new_contract')

    if not old_contract or not new_contract:
        raise HTTPException(status_code=400, detail="Both old_contract and new_contract are required")

    try:
        # Business logic now in manager
        return manager.compare_contracts(
            old_contract=old_contract,
            new_contract=new_contract
        )
    except ValueError as e:
        logger.error("Validation error comparing contracts: %s", e)
        raise HTTPException(status_code=400, detail="Invalid contract data for comparison")
    except Exception as e:
        logger.error("Error comparing contracts", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to compare contracts")


@router.get('/data-contracts/{contract_id}/version-history', response_model=dict)
async def get_contract_version_history(
    contract_id: str,
    db: DBSessionDep,
    manager: DataContractsManager = Depends(get_data_contracts_manager),
    _: bool = Depends(PermissionChecker('data-contracts', FeatureAccessLevel.READ_ONLY))
):
    """Get version history lineage for a contract with parent-child relationships."""
    try:
        from src.models.data_contracts_api import DataContractRead

        # Business logic now in manager
        history = manager.get_version_history(db=db, contract_id=contract_id)

        # Convert database objects to API models
        return {
            "current": DataContractRead.model_validate(history["current"]).model_dump(),
            "parent": DataContractRead.model_validate(history["parent"]).model_dump() if history["parent"] else None,
            "children": [DataContractRead.model_validate(c).model_dump() for c in history["children"]],
            "siblings": [DataContractRead.model_validate(s).model_dump() for s in history["siblings"]]
        }
    except ValueError as e:
        logger.error("Validation error fetching version history for %s: %s", contract_id, e)
        raise HTTPException(status_code=404, detail="Contract not found")
    except Exception as e:
        logger.error("Error fetching version history for %s", contract_id, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch version history")


@router.get('/data-contracts/{contract_id}/import-team-members', response_model=list)
async def get_team_members_for_import(
    contract_id: str,
    team_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager: DataContractsManager = Depends(get_data_contracts_manager),
    _: bool = Depends(PermissionChecker('data-contracts', FeatureAccessLevel.READ_WRITE))
):
    """Get team members formatted for import into contract ODCS team array.
    
    Route handler: parses parameters, audits request, delegates to manager, returns response.
    All business logic is in the manager.
    """
    success = False
    members = []
    try:
        # Delegate business logic to manager
        members = manager.get_team_members_for_import(
            db=db,
            contract_id=contract_id,
            team_id=team_id,
            current_user=current_user.username if current_user else None
        )
        
        success = True
        return members
        
    except ValueError as e:
        logger.error("Validation error fetching team members for contract %s: %s", contract_id, e)
        raise HTTPException(status_code=404, detail="Contract or team not found")
    except Exception as e:
        logger.error("Error fetching team members for import for contract %s", contract_id, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch team members for import")
    finally:
        # Audit the action
        audit_manager.log_action(
            db=db,
            username=current_user.username if current_user else 'anonymous',
            ip_address=request.client.host if request.client else None,
            feature='data-contracts',
            action='GET_TEAM_MEMBERS_FOR_IMPORT',
            success=success,
            details={"contract_id": contract_id, "team_id": team_id, "member_count": len(members)}
        )


# ===== Personal Draft Endpoints =====

@router.post('/data-contracts/{contract_id}/clone-for-editing', response_model=dict, status_code=201)
async def clone_contract_for_editing(
    contract_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager: DataContractsManager = Depends(get_data_contracts_manager),
    _: bool = Depends(PermissionChecker('data-contracts', FeatureAccessLevel.READ_WRITE))
):
    """Clone a contract to create a personal draft for editing.
    
    Creates a personal draft that is only visible to the owner.
    The draft version is set to "{parent_version}-draft" as a placeholder.
    The user can edit the draft and then commit it with a final version.
    """
    success = False
    response_status_code = 201
    
    try:
        # Get parent contract to create placeholder version
        parent = data_contract_repo.get(db, id=contract_id)
        if not parent:
            raise HTTPException(status_code=404, detail="Contract not found")
        
        # Create personal draft with placeholder version
        placeholder_version = f"{parent.version}-draft"
        
        new_contract = manager.clone_contract_for_new_version(
            db=db,
            contract_id=contract_id,
            new_version=placeholder_version,
            change_summary=None,
            current_user=current_user.username if current_user else None,
            as_personal_draft=True
        )
        
        success = True
        return {
            "id": new_contract.id,
            "name": new_contract.name,
            "version": new_contract.version,
            "status": new_contract.status,
            "draft_owner_id": new_contract.draft_owner_id,
            "parent_contract_id": new_contract.parent_contract_id,
            "message": "Personal draft created. Edit and commit when ready."
        }
        
    except ValueError as e:
        response_status_code = 400
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        response_status_code = 500
        logger.error("Error creating personal draft from contract %s", contract_id, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to create personal draft")
    finally:
        audit_manager.log_action(
            db=db,
            username=current_user.username if current_user else 'anonymous',
            ip_address=request.client.host if request.client else None,
            feature='data-contracts',
            action='CLONE_FOR_EDITING',
            success=success,
            details={"contract_id": contract_id}
        )


@router.get('/data-contracts/{contract_id}/diff-from-parent', response_model=dict)
async def get_diff_from_parent(
    contract_id: str,
    db: DBSessionDep,
    manager: DataContractsManager = Depends(get_data_contracts_manager),
    _: bool = Depends(PermissionChecker('data-contracts', FeatureAccessLevel.READ_ONLY))
):
    """Compare a contract to its parent and get version suggestion.
    
    Returns the diff analysis and a suggested version bump based on
    the changes detected between the contract and its parent.
    """
    try:
        result = manager.get_diff_from_parent(db=db, contract_id=contract_id)
        return result
        
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("Error getting diff from parent for contract %s", contract_id, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to get diff from parent")


@router.post('/data-contracts/{contract_id}/commit', response_model=dict)
async def commit_personal_draft(
    contract_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    body: dict = Body(...),
    manager: DataContractsManager = Depends(get_data_contracts_manager),
    _: bool = Depends(PermissionChecker('data-contracts', FeatureAccessLevel.READ_WRITE))
):
    """Commit a personal draft to team/project visibility.
    
    This promotes a personal draft from tier 1 (only owner can see) to
    tier 2 (team/project members can see).
    
    Request body:
    - new_version: Final semantic version (e.g., "1.1.0")
    - change_summary: Summary of changes in this version
    """
    success = False
    
    try:
        new_version = body.get('new_version')
        change_summary = body.get('change_summary')
        
        if not new_version:
            raise HTTPException(status_code=400, detail="new_version is required")
        if not change_summary:
            raise HTTPException(status_code=400, detail="change_summary is required")
        
        result = manager.commit_personal_draft(
            db=db,
            draft_id=contract_id,
            new_version=new_version,
            change_summary=change_summary,
            current_user=current_user.username if current_user else None
        )
        
        success = True
        return {
            "id": result.id,
            "name": result.name,
            "version": result.version,
            "status": result.status,
            "message": "Draft committed successfully. Now visible to team."
        }
        
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("Error committing personal draft %s", contract_id, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to commit draft")
    finally:
        audit_manager.log_action(
            db=db,
            username=current_user.username if current_user else 'anonymous',
            ip_address=request.client.host if request.client else None,
            feature='data-contracts',
            action='COMMIT_PERSONAL_DRAFT',
            success=success,
            details={"contract_id": contract_id, "new_version": body.get('new_version')}
        )


@router.delete('/data-contracts/{contract_id}/discard', response_model=dict)
async def discard_personal_draft(
    contract_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager: DataContractsManager = Depends(get_data_contracts_manager),
    _: bool = Depends(PermissionChecker('data-contracts', FeatureAccessLevel.READ_WRITE))
):
    """Discard a personal draft (delete it and all child entities).
    
    Only the draft owner can discard their personal draft.
    """
    success = False
    
    try:
        manager.discard_personal_draft(
            db=db,
            draft_id=contract_id,
            current_user=current_user.username if current_user else None
        )
        
        success = True
        return {"message": "Personal draft discarded successfully"}
        
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("Error discarding personal draft %s", contract_id, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to discard draft")
    finally:
        audit_manager.log_action(
            db=db,
            username=current_user.username if current_user else 'anonymous',
            ip_address=request.client.host if request.client else None,
            feature='data-contracts',
            action='DISCARD_PERSONAL_DRAFT',
            success=success,
            details={"contract_id": contract_id}
        )


@router.get('/data-contracts/my-drafts', response_model=List[dict])
async def get_my_personal_drafts(
    request: Request,
    db: DBSessionDep,
    current_user: AuditCurrentUserDep,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    _: bool = Depends(PermissionChecker('data-contracts', FeatureAccessLevel.READ_ONLY))
):
    """Get all personal drafts owned by the current user."""
    try:
        from src.models.data_contracts_api import DataContractRead
        
        drafts = data_contract_repo.get_user_personal_drafts(
            db=db,
            current_user=current_user.username if current_user else None,
            skip=skip,
            limit=limit
        )
        
        return [DataContractRead.model_validate(d).model_dump() for d in drafts]
        
    except Exception as e:
        logger.error("Error fetching personal drafts", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch personal drafts")


# ===== ODCS v3.1.0: Schema-Level Relationship CRUD =====

def _relationship_db_to_dict(rel) -> dict:
    """Convert a relationship DB row to an API-friendly dict."""
    to_val = rel.to_value
    try:
        to_val = json.loads(rel.to_value)
    except (json.JSONDecodeError, TypeError):
        pass
    result = {
        'id': rel.id,
        'type': rel.relationship_type,
        'to': to_val,
    }
    if hasattr(rel, 'from_value'):
        from_val = rel.from_value
        try:
            from_val = json.loads(rel.from_value)
        except (json.JSONDecodeError, TypeError):
            pass
        result['from'] = from_val
    if hasattr(rel, 'schema_object_id'):
        result['schema_object_id'] = rel.schema_object_id
    if hasattr(rel, 'property_id'):
        result['property_id'] = rel.property_id
    if rel.custom_properties_json:
        try:
            result['customProperties'] = json.loads(rel.custom_properties_json)
        except (json.JSONDecodeError, TypeError):
            pass
    return result


@router.get('/data-contracts/{contract_id}/schemas/{schema_id}/relationships', response_model=List[dict])
async def list_schema_relationships(
    contract_id: str,
    schema_id: str,
    db: DBSessionDep,
    _: bool = Depends(PermissionChecker('data-contracts', FeatureAccessLevel.READ_ONLY))
):
    schema_obj = db.query(SchemaObjectDb).filter(
        SchemaObjectDb.id == schema_id,
        SchemaObjectDb.contract_id == contract_id
    ).first()
    if not schema_obj:
        raise HTTPException(404, "Schema object not found")
    rels = db.query(SchemaObjectRelationshipDb).filter(
        SchemaObjectRelationshipDb.schema_object_id == schema_id
    ).all()
    return [_relationship_db_to_dict(r) for r in rels]


@router.post('/data-contracts/{contract_id}/schemas/{schema_id}/relationships', response_model=dict, status_code=201)
async def create_schema_relationship(
    contract_id: str,
    schema_id: str,
    body: dict = Body(...),
    db: DBSessionDep = None,
    _: bool = Depends(PermissionChecker('data-contracts', FeatureAccessLevel.READ_WRITE))
):
    schema_obj = db.query(SchemaObjectDb).filter(
        SchemaObjectDb.id == schema_id,
        SchemaObjectDb.contract_id == contract_id
    ).first()
    if not schema_obj:
        raise HTTPException(404, "Schema object not found")

    from_val = body.get('from', '')
    to_val = body.get('to', '')
    rel = SchemaObjectRelationshipDb(
        id=str(uuid4()),
        schema_object_id=schema_id,
        relationship_type=body.get('type', 'foreignKey'),
        from_value=json.dumps(from_val) if isinstance(from_val, list) else str(from_val),
        to_value=json.dumps(to_val) if isinstance(to_val, list) else str(to_val),
        custom_properties_json=json.dumps(body['customProperties']) if body.get('customProperties') else None,
    )
    db.add(rel)
    db.commit()
    db.refresh(rel)
    return _relationship_db_to_dict(rel)


@router.put('/data-contracts/{contract_id}/schemas/{schema_id}/relationships/{rel_id}', response_model=dict)
async def update_schema_relationship(
    contract_id: str,
    schema_id: str,
    rel_id: str,
    body: dict = Body(...),
    db: DBSessionDep = None,
    _: bool = Depends(PermissionChecker('data-contracts', FeatureAccessLevel.READ_WRITE))
):
    rel = db.query(SchemaObjectRelationshipDb).filter(
        SchemaObjectRelationshipDb.id == rel_id,
        SchemaObjectRelationshipDb.schema_object_id == schema_id
    ).first()
    if not rel:
        raise HTTPException(404, "Relationship not found")

    if 'type' in body:
        rel.relationship_type = body['type']
    if 'from' in body:
        from_val = body['from']
        rel.from_value = json.dumps(from_val) if isinstance(from_val, list) else str(from_val)
    if 'to' in body:
        to_val = body['to']
        rel.to_value = json.dumps(to_val) if isinstance(to_val, list) else str(to_val)
    if 'customProperties' in body:
        rel.custom_properties_json = json.dumps(body['customProperties']) if body['customProperties'] else None

    db.commit()
    db.refresh(rel)
    return _relationship_db_to_dict(rel)


@router.delete('/data-contracts/{contract_id}/schemas/{schema_id}/relationships/{rel_id}', status_code=204)
async def delete_schema_relationship(
    contract_id: str,
    schema_id: str,
    rel_id: str,
    db: DBSessionDep = None,
    _: bool = Depends(PermissionChecker('data-contracts', FeatureAccessLevel.READ_WRITE))
):
    deleted = db.query(SchemaObjectRelationshipDb).filter(
        SchemaObjectRelationshipDb.id == rel_id,
        SchemaObjectRelationshipDb.schema_object_id == schema_id
    ).delete()
    if not deleted:
        raise HTTPException(404, "Relationship not found")
    db.commit()


# ===== ODCS v3.1.0: Property-Level Relationship CRUD =====

@router.get('/data-contracts/{contract_id}/schemas/{schema_id}/properties/{prop_id}/relationships', response_model=List[dict])
async def list_property_relationships(
    contract_id: str,
    schema_id: str,
    prop_id: str,
    db: DBSessionDep = None,
    _: bool = Depends(PermissionChecker('data-contracts', FeatureAccessLevel.READ_ONLY))
):
    prop = db.query(SchemaPropertyDb).filter(
        SchemaPropertyDb.id == prop_id,
        SchemaPropertyDb.object_id == schema_id
    ).first()
    if not prop:
        raise HTTPException(404, "Property not found")
    rels = db.query(SchemaPropertyRelationshipDb).filter(
        SchemaPropertyRelationshipDb.property_id == prop_id
    ).all()
    return [_relationship_db_to_dict(r) for r in rels]


@router.post('/data-contracts/{contract_id}/schemas/{schema_id}/properties/{prop_id}/relationships', response_model=dict, status_code=201)
async def create_property_relationship(
    contract_id: str,
    schema_id: str,
    prop_id: str,
    body: dict = Body(...),
    db: DBSessionDep = None,
    _: bool = Depends(PermissionChecker('data-contracts', FeatureAccessLevel.READ_WRITE))
):
    prop = db.query(SchemaPropertyDb).filter(
        SchemaPropertyDb.id == prop_id,
        SchemaPropertyDb.object_id == schema_id
    ).first()
    if not prop:
        raise HTTPException(404, "Property not found")

    to_val = body.get('to', '')
    rel = SchemaPropertyRelationshipDb(
        id=str(uuid4()),
        property_id=prop_id,
        relationship_type=body.get('type', 'foreignKey'),
        to_value=json.dumps(to_val) if isinstance(to_val, list) else str(to_val),
        custom_properties_json=json.dumps(body['customProperties']) if body.get('customProperties') else None,
    )
    db.add(rel)
    db.commit()
    db.refresh(rel)
    return _relationship_db_to_dict(rel)


@router.put('/data-contracts/{contract_id}/schemas/{schema_id}/properties/{prop_id}/relationships/{rel_id}', response_model=dict)
async def update_property_relationship(
    contract_id: str,
    schema_id: str,
    prop_id: str,
    rel_id: str,
    body: dict = Body(...),
    db: DBSessionDep = None,
    _: bool = Depends(PermissionChecker('data-contracts', FeatureAccessLevel.READ_WRITE))
):
    rel = db.query(SchemaPropertyRelationshipDb).filter(
        SchemaPropertyRelationshipDb.id == rel_id,
        SchemaPropertyRelationshipDb.property_id == prop_id
    ).first()
    if not rel:
        raise HTTPException(404, "Relationship not found")

    if 'type' in body:
        rel.relationship_type = body['type']
    if 'to' in body:
        to_val = body['to']
        rel.to_value = json.dumps(to_val) if isinstance(to_val, list) else str(to_val)
    if 'customProperties' in body:
        rel.custom_properties_json = json.dumps(body['customProperties']) if body['customProperties'] else None

    db.commit()
    db.refresh(rel)
    return _relationship_db_to_dict(rel)


@router.delete('/data-contracts/{contract_id}/schemas/{schema_id}/properties/{prop_id}/relationships/{rel_id}', status_code=204)
async def delete_property_relationship(
    contract_id: str,
    schema_id: str,
    prop_id: str,
    rel_id: str,
    db: DBSessionDep = None,
    _: bool = Depends(PermissionChecker('data-contracts', FeatureAccessLevel.READ_WRITE))
):
    deleted = db.query(SchemaPropertyRelationshipDb).filter(
        SchemaPropertyRelationshipDb.id == rel_id,
        SchemaPropertyRelationshipDb.property_id == prop_id
    ).delete()
    if not deleted:
        raise HTTPException(404, "Relationship not found")
    db.commit()


# ===== ODCS v3.1.0: Team Metadata =====

@router.get('/data-contracts/{contract_id}/team-metadata', response_model=dict)
async def get_team_metadata(
    contract_id: str,
    db: DBSessionDep = None,
    _: bool = Depends(PermissionChecker('data-contracts', FeatureAccessLevel.READ_ONLY))
):
    contract = data_contract_repo.get(db, id=contract_id)
    if not contract:
        raise HTTPException(404, "Contract not found")

    meta = db.query(DataContractTeamMetadataDb).filter(
        DataContractTeamMetadataDb.contract_id == contract_id
    ).first()
    if not meta:
        return {'contract_id': contract_id, 'name': None, 'description': None}

    result = {
        'id': meta.id,
        'contract_id': meta.contract_id,
        'stable_id': meta.stable_id,
        'name': meta.name,
        'description': meta.description,
    }
    if meta.tags_json:
        try:
            result['tags'] = json.loads(meta.tags_json)
        except (json.JSONDecodeError, TypeError):
            result['tags'] = None
    if meta.custom_properties_json:
        try:
            result['customProperties'] = json.loads(meta.custom_properties_json)
        except (json.JSONDecodeError, TypeError):
            result['customProperties'] = None
    if meta.authoritative_definitions_json:
        try:
            result['authoritativeDefinitions'] = json.loads(meta.authoritative_definitions_json)
        except (json.JSONDecodeError, TypeError):
            result['authoritativeDefinitions'] = None
    return result


@router.put('/data-contracts/{contract_id}/team-metadata', response_model=dict)
async def update_team_metadata(
    contract_id: str,
    body: dict = Body(...),
    db: DBSessionDep = None,
    _: bool = Depends(PermissionChecker('data-contracts', FeatureAccessLevel.READ_WRITE))
):
    contract = data_contract_repo.get(db, id=contract_id)
    if not contract:
        raise HTTPException(404, "Contract not found")

    meta = db.query(DataContractTeamMetadataDb).filter(
        DataContractTeamMetadataDb.contract_id == contract_id
    ).first()
    if not meta:
        meta = DataContractTeamMetadataDb(
            id=str(uuid4()),
            contract_id=contract_id,
        )
        db.add(meta)

    if 'name' in body:
        meta.name = body['name']
    if 'description' in body:
        meta.description = body['description']
    if 'tags' in body:
        meta.tags_json = json.dumps(body['tags']) if body['tags'] else None
    if 'customProperties' in body:
        meta.custom_properties_json = json.dumps(body['customProperties']) if body['customProperties'] else None
    if 'authoritativeDefinitions' in body:
        meta.authoritative_definitions_json = json.dumps(body['authoritativeDefinitions']) if body['authoritativeDefinitions'] else None

    db.commit()
    db.refresh(meta)

    result = {
        'id': meta.id,
        'contract_id': meta.contract_id,
        'stable_id': meta.stable_id,
        'name': meta.name,
        'description': meta.description,
    }
    if meta.tags_json:
        try:
            result['tags'] = json.loads(meta.tags_json)
        except (json.JSONDecodeError, TypeError):
            pass
    if meta.custom_properties_json:
        try:
            result['customProperties'] = json.loads(meta.custom_properties_json)
        except (json.JSONDecodeError, TypeError):
            pass
    if meta.authoritative_definitions_json:
        try:
            result['authoritativeDefinitions'] = json.loads(meta.authoritative_definitions_json)
        except (json.JSONDecodeError, TypeError):
            pass
    return result


def register_routes(app):
    """Register routes with the app"""
    app.include_router(router)
    logger.info("Data contract routes registered")
