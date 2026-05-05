from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field

from src.common.dependencies import DBSessionDep, CurrentUserDep
from src.common.authorization import PermissionChecker
from src.common.features import FeatureAccessLevel
from src.controller.approvals_manager import ApprovalsManager
from src.controller.agreement_wizard_manager import AgreementWizardManager
from src.models.data_products import OnBehalfOf
from src.common.logging import get_logger


logger = get_logger(__name__)

router = APIRouter(prefix="/api", tags=["Approvals"])


def get_approvals_manager(request: Request) -> ApprovalsManager:
    """Dependency provider for ApprovalsManager."""
    manager = getattr(request.app.state, 'approvals_manager', None)
    if not manager:
        # Create on-demand if not in app.state
        logger.warning("ApprovalsManager not found in app.state, creating new instance")
        manager = ApprovalsManager()
    return manager


def get_agreement_wizard_manager(
    db: DBSessionDep,
    request: Request,
) -> AgreementWizardManager:
    """Get AgreementWizardManager with optional PDF storage path and notifications from app.state."""
    storage_base_path = getattr(request.app.state, 'agreement_pdf_volume_path', None)
    notifications_manager = getattr(request.app.state, 'notifications_manager', None)
    return AgreementWizardManager(
        db,
        storage_base_path=storage_base_path,
        notifications_manager=notifications_manager,
    )


@router.get('/approvals/sessions')
async def list_approval_sessions(
    limit: int = Query(50, ge=1, le=100),
    wizard_manager: AgreementWizardManager = Depends(get_agreement_wizard_manager),
    _: bool = Depends(PermissionChecker('settings', FeatureAccessLevel.READ_ONLY)),
):
    """List recent approval wizard sessions."""
    return wizard_manager.list_sessions(limit=limit)


@router.get('/approvals/queue')
async def get_approvals_queue(
    db: DBSessionDep,
    current_user: CurrentUserDep,
    manager: ApprovalsManager = Depends(get_approvals_manager),
    _: bool = Depends(PermissionChecker('data-contracts', FeatureAccessLevel.READ_ONLY)),
):
    """Get all items awaiting approval (contracts, products, etc.)."""
    try:
        return manager.get_approvals_queue(db)
    except Exception as e:
        logger.exception("Failed to build approvals queue")
        raise HTTPException(status_code=500, detail="Failed to build approvals queue")


# --- Agreement wizard (approval workflows) ---

class CreateSessionBody(BaseModel):
    """Body for POST /api/approvals/sessions."""
    workflow_id: str = Field(..., description="Approval workflow ID")
    entity_type: str = Field(..., description="Entity type (e.g. data_contract, data_product, dataset)")
    entity_id: str = Field(..., description="Entity ID")
    completion_action: Optional[str] = Field(None, description="Action after complete, e.g. 'subscribe'")
    # when completion_action='subscribe', this OBO
    # is persisted on the session row and forwarded to dp.subscribe() when the
    # wizard completes — so wizard-completed subscriptions match the direct
    # /api/data-products/{id}/subscribe path.
    on_behalf_of: Optional[OnBehalfOf] = Field(
        None,
        description="Optional: subscribe on behalf of a group/SP (validated against workspace SCIM at subscribe time)",
    )


class SubmitStepBody(BaseModel):
    """Body for POST /api/approvals/sessions/{id}/steps."""
    step_id: str = Field(..., description="Step ID being submitted")
    payload: Dict[str, Any] = Field(default_factory=dict, description="Step payload (e.g. reason, acceptances)")


@router.post('/approvals/sessions')
async def create_approval_session(
    db: DBSessionDep,
    body: CreateSessionBody,
    current_user: CurrentUserDep,
    wizard_manager: AgreementWizardManager = Depends(get_agreement_wizard_manager),
    _: bool = Depends(PermissionChecker('data-contracts', FeatureAccessLevel.READ_WRITE)),
) -> Dict[str, Any]:
    """Create a new agreement wizard session; returns session_id and first step."""
    try:
        created_by = current_user.email if current_user else None
        return wizard_manager.create_session(
            workflow_id=body.workflow_id,
            entity_type=body.entity_type,
            entity_id=body.entity_id,
            completion_action=body.completion_action,
            created_by=created_by,
            on_behalf_of=body.on_behalf_of,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get('/approvals/sessions/{session_id}')
async def get_approval_session(
    session_id: str,
    db: DBSessionDep,
    wizard_manager: AgreementWizardManager = Depends(get_agreement_wizard_manager),
    _: bool = Depends(PermissionChecker('data-contracts', FeatureAccessLevel.READ_ONLY)),
) -> Dict[str, Any]:
    """Get current step and step_results (for Back/refresh)."""
    data = wizard_manager.get_session(session_id)
    if not data:
        raise HTTPException(status_code=404, detail="Session not found or not in progress")
    return data


@router.post('/approvals/sessions/{session_id}/steps')
async def submit_approval_step(
    session_id: str,
    db: DBSessionDep,
    body: SubmitStepBody,
    current_user: CurrentUserDep,
    wizard_manager: AgreementWizardManager = Depends(get_agreement_wizard_manager),
    _: bool = Depends(PermissionChecker('data-contracts', FeatureAccessLevel.READ_WRITE)),
) -> Dict[str, Any]:
    """Submit step payload; returns next step or { complete: true, agreement_id, pdf_storage_path? }."""
    try:
        created_by = current_user.email if current_user else None
        return wizard_manager.submit_step(
            session_id=session_id,
            step_id=body.step_id,
            payload=body.payload,
            created_by=created_by,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post('/approvals/sessions/{session_id}/abort')
async def abort_approval_session(
    session_id: str,
    db: DBSessionDep,
    wizard_manager: AgreementWizardManager = Depends(get_agreement_wizard_manager),
    _: bool = Depends(PermissionChecker('data-contracts', FeatureAccessLevel.READ_WRITE)),
) -> Dict[str, Any]:
    """Mark session as abandoned."""
    ok = wizard_manager.abort_session(session_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Session not found or not in progress")
    return {"session_id": session_id, "status": "abandoned"}


# --- Agreements ---

@router.get('/approvals/agreements')
async def list_agreements(
    entity_type: Optional[str] = Query(None),
    entity_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=100),
    wizard_manager: AgreementWizardManager = Depends(get_agreement_wizard_manager),
    _: bool = Depends(PermissionChecker('settings', FeatureAccessLevel.READ_ONLY)),
):
    """List agreements, optionally filtered by entity type/id."""
    return wizard_manager.list_agreements(
        entity_type=entity_type, entity_id=entity_id, limit=limit
    )


@router.get('/approvals/agreements/{agreement_id}')
async def get_agreement(
    agreement_id: str,
    wizard_manager: AgreementWizardManager = Depends(get_agreement_wizard_manager),
    _: bool = Depends(PermissionChecker('settings', FeatureAccessLevel.READ_ONLY)),
):
    """Get a single agreement by ID."""
    result = wizard_manager.get_agreement(agreement_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Agreement not found")
    return result


@router.get('/approvals/agreements/{agreement_id}/pdf')
async def download_agreement_pdf(
    agreement_id: str,
    wizard_manager: AgreementWizardManager = Depends(get_agreement_wizard_manager),
    _: bool = Depends(PermissionChecker('settings', FeatureAccessLevel.READ_ONLY)),
):
    """Download the agreement as a PDF document.

    Resolution + generation logic lives in
    :py:meth:`AgreementWizardManager.get_agreement_pdf`; the route maps the
    manager's discriminated-result onto the appropriate ``Response`` type.
    """
    result = wizard_manager.get_agreement_pdf(agreement_id)
    kind = result.get("kind")
    if kind == "not_found":
        raise HTTPException(status_code=404, detail="Agreement not found")
    if kind == "no_pdf_step":
        raise HTTPException(
            status_code=404,
            detail="This agreement does not have PDF generation enabled",
        )
    headers = {"Content-Disposition": f'attachment; filename="{result["filename"]}"'}
    if kind == "pdf":
        return Response(content=result["content"], media_type="application/pdf", headers=headers)
    if kind == "html":
        return HTMLResponse(content=result["content"], headers=headers)
    raise HTTPException(status_code=500, detail=f"Unexpected agreement-pdf result: {kind}")


def register_routes(app):
    app.include_router(router)
    logger.info("Approvals routes registered")


