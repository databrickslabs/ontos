import json
from datetime import datetime
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


def _agreement_has_pdf_step(agreement) -> bool:
    """Check if the agreement's workflow snapshot includes a generate_pdf step."""
    snapshot = getattr(agreement, 'workflow_snapshot', None)
    if not snapshot:
        return False
    try:
        data = json.loads(snapshot) if isinstance(snapshot, str) else snapshot
        return any(s.get('step_type') == 'generate_pdf' for s in data.get('steps', []))
    except (json.JSONDecodeError, TypeError, AttributeError):
        return False

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
    request: Request,
    db: DBSessionDep,
    limit: int = Query(50, ge=1, le=100),
    _: bool = Depends(PermissionChecker('settings', FeatureAccessLevel.READ_ONLY)),
):
    """List recent approval wizard sessions."""
    from src.repositories.agreement_wizard_sessions_repository import AgreementWizardSessionsRepository
    repo = AgreementWizardSessionsRepository()
    sessions = repo.list_recent(db, limit=limit)
    return {"sessions": sessions, "total": len(sessions)}


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
    # Daimler #486363 gap-fill: when completion_action='subscribe', this OBO
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
    request: Request,
    db: DBSessionDep,
    entity_type: Optional[str] = Query(None),
    entity_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=100),
    _: bool = Depends(PermissionChecker('settings', FeatureAccessLevel.READ_ONLY)),
):
    """List agreements, optionally filtered by entity type/id."""
    from src.repositories.agreements_repository import AgreementsRepository
    repo = AgreementsRepository()
    agreements = repo.list_recent(db, entity_type=entity_type, entity_id=entity_id, limit=limit)
    return {"agreements": agreements, "total": len(agreements)}


@router.get('/approvals/agreements/{agreement_id}')
async def get_agreement(
    agreement_id: str,
    db: DBSessionDep,
    _: bool = Depends(PermissionChecker('settings', FeatureAccessLevel.READ_ONLY)),
):
    """Get a single agreement by ID."""
    from src.repositories.agreements_repository import AgreementsRepository
    repo = AgreementsRepository()
    agreement = repo.get(db, agreement_id)
    if not agreement:
        raise HTTPException(status_code=404, detail="Agreement not found")
    step_results = []
    if agreement.step_results:
        try:
            step_results = json.loads(agreement.step_results) if isinstance(agreement.step_results, str) else agreement.step_results
        except (json.JSONDecodeError, TypeError):
            pass
    return {
        "id": agreement.id,
        "entity_type": agreement.entity_type,
        "entity_id": agreement.entity_id,
        "workflow_id": agreement.workflow_id,
        "workflow_name": agreement.workflow_name,
        "wizard_session_id": agreement.wizard_session_id,
        "step_results": step_results,
        "pdf_storage_path": agreement.pdf_storage_path,
        "created_by": agreement.created_by,
        "created_at": agreement.created_at.isoformat() if agreement.created_at else None,
        "pdf_url": f"/api/approvals/agreements/{agreement.id}/pdf" if _agreement_has_pdf_step(agreement) else None,
    }


@router.get('/approvals/agreements/{agreement_id}/pdf')
async def download_agreement_pdf(
    agreement_id: str,
    db: DBSessionDep,
    _: bool = Depends(PermissionChecker('settings', FeatureAccessLevel.READ_ONLY)),
):
    """Download the agreement as a PDF document.

    Generation priority:
    1. Pre-generated PDF file on disk (if ``pdf_storage_path`` exists).
    2. On-the-fly PDF via fpdf2 (``build_agreement_pdf``).
    3. Fallback to styled HTML if fpdf2 is not installed.
    """
    from src.repositories.agreements_repository import AgreementsRepository
    from src.utils.agreement_pdf_builder import build_agreement_pdf, build_agreement_html, _HAS_FPDF

    repo = AgreementsRepository()
    agreement = repo.get(db, agreement_id)
    if not agreement:
        raise HTTPException(status_code=404, detail="Agreement not found")

    # Only generate PDF if the workflow included a generate_pdf step
    if not _agreement_has_pdf_step(agreement) and not getattr(agreement, 'pdf_storage_path', None):
        raise HTTPException(status_code=404, detail="This agreement does not have PDF generation enabled")

    # If a pre-generated PDF was persisted, serve it directly. Inside the
    # Databricks Apps runtime, /Volumes/... is NOT a real filesystem mount —
    # raw os.path.isfile() returns False and open() raises EACCES, so the
    # endpoint would silently fall through to fpdf2 regeneration and serve a
    # PDF with a different /CreationDate than the persisted one. Mirror the
    # upload-side fix: use the SDK Files API for /Volumes/ paths and keep the
    # plain filesystem path for local dev where pdf_storage_path may
    # legitimately be a tmp dir.
    stored_path = agreement.pdf_storage_path
    if stored_path:
        if stored_path.startswith("/Volumes/"):
            try:
                from src.common.workspace_client import get_workspace_client
                ws = get_workspace_client()
                resp = ws.files.download(file_path=stored_path)
                # SDK returns a DownloadResponse with .contents stream-like obj
                if hasattr(resp, "contents") and resp.contents is not None:
                    pdf_bytes = resp.contents.read()
                else:
                    pdf_bytes = resp.read()  # type: ignore[union-attr]
                return Response(
                    content=pdf_bytes,
                    media_type="application/pdf",
                    headers={
                        "Content-Disposition": f'attachment; filename="agreement-{agreement_id[:8]}.pdf"',
                    },
                )
            except Exception as e:
                logger.warning(
                    "Volume download failed for %s: %s — regenerating",
                    stored_path,
                    e,
                )
                # Fall through to regeneration below
        else:
            import os
            if os.path.isfile(stored_path):
                with open(stored_path, "rb") as f:
                    pdf_bytes = f.read()
                return Response(
                    content=pdf_bytes,
                    media_type="application/pdf",
                    headers={
                        "Content-Disposition": f'attachment; filename="agreement-{agreement_id[:8]}.pdf"',
                    },
                )

    # Parse step_results from the agreement record
    step_results: list = []
    if agreement.step_results:
        try:
            parsed = json.loads(agreement.step_results) if isinstance(agreement.step_results, str) else agreement.step_results
            if isinstance(parsed, list):
                step_results = parsed
        except (json.JSONDecodeError, TypeError):
            pass

    # Try real PDF generation via fpdf2
    if _HAS_FPDF:
        pdf_bytes = build_agreement_pdf(
            workflow_name=agreement.workflow_name or "Agreement",
            entity_type=agreement.entity_type,
            entity_id=agreement.entity_id,
            step_results=step_results,
            snapshot=agreement.workflow_snapshot,
            created_by=agreement.created_by,
            created_at=agreement.created_at,
            workflow_version=getattr(agreement, 'workflow_version', None),
        )
        return Response(
            content=bytes(pdf_bytes),
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="agreement-{agreement_id[:8]}.pdf"',
            },
        )

    # Fallback to on-the-fly HTML generation when fpdf2 is not available
    html = build_agreement_html(
        workflow_name=agreement.workflow_name or "Agreement",
        entity_type=agreement.entity_type,
        entity_id=agreement.entity_id,
        step_results=step_results,
        snapshot=agreement.workflow_snapshot,
        created_by=agreement.created_by,
        created_at=agreement.created_at,
    )

    return HTMLResponse(
        content=html,
        headers={
            "Content-Disposition": f'attachment; filename="agreement-{agreement_id[:8]}.html"',
        },
    )


def register_routes(app):
    app.include_router(router)
    logger.info("Approvals routes registered")


