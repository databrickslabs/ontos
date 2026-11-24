"""
Master Data Management (MDM) API Routes

FastAPI routes for MDM functionality.
"""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Body, Query, Request, status
from sqlalchemy.orm import Session

from src.common.dependencies import (
    DBSessionDep,
    AuditManagerDep,
    AuditCurrentUserDep,
)
from src.common.authorization import PermissionChecker
from src.common.features import FeatureAccessLevel
from src.common.database import get_db
from src.common.logging import get_logger

from src.controller.mdm_manager import MdmManager
from src.models.mdm import (
    MdmConfigCreate,
    MdmConfigUpdate,
    MdmConfigApi,
    MdmSourceLinkCreate,
    MdmSourceLinkUpdate,
    MdmSourceLinkApi,
    MdmMatchRunApi,
    MdmMatchCandidateApi,
    MdmMatchCandidateUpdate,
    MdmCreateReviewRequest,
    MdmCreateReviewResponse,
    MdmMergeRequest,
    MdmMergeResponse,
)

logger = get_logger(__name__)
router = APIRouter(prefix="/api/mdm", tags=["Master Data Management"])

MDM_FEATURE_ID = "master-data"


# --- Dependency Injection ---

def get_mdm_manager(request: Request, db: Session = Depends(get_db)) -> MdmManager:
    """Get MDM manager with injected dependencies"""
    # Get managers from app state if available
    reviews_manager = getattr(request.app.state, 'data_asset_review_manager', None)
    jobs_manager = getattr(request.app.state, 'jobs_manager', None)
    notifications_manager = getattr(request.app.state, 'notifications_manager', None)
    contracts_manager = getattr(request.app.state, 'data_contracts_manager', None)
    
    return MdmManager(
        db=db,
        reviews_manager=reviews_manager,
        jobs_manager=jobs_manager,
        notifications_manager=notifications_manager,
        contracts_manager=contracts_manager,
    )


MdmManagerDep = Depends(get_mdm_manager)


# ==================== Configuration Endpoints ====================

@router.get("/configs", response_model=List[MdmConfigApi])
async def list_mdm_configs(
    project_id: Optional[str] = Query(None, description="Filter by project ID"),
    status: Optional[str] = Query(None, description="Filter by status"),
    skip: int = Query(0, ge=0),
    limit: Optional[int] = Query(None, ge=1),
    manager: MdmManager = MdmManagerDep,
    _: bool = Depends(PermissionChecker(MDM_FEATURE_ID, FeatureAccessLevel.READ_ONLY))
):
    """List all MDM configurations"""
    try:
        configs = manager.list_configs(project_id=project_id, status=status, skip=skip, limit=limit)
        logger.info(f"Listed {len(configs)} MDM configs (project_id={project_id}, status={status})")
        return configs
    except Exception as e:
        logger.exception("Error listing MDM configs")
        raise HTTPException(status_code=500, detail=f"Failed to list MDM configurations: {str(e)}")


@router.get("/configs/{config_id}", response_model=MdmConfigApi)
async def get_mdm_config(
    config_id: str,
    manager: MdmManager = MdmManagerDep,
    _: bool = Depends(PermissionChecker(MDM_FEATURE_ID, FeatureAccessLevel.READ_ONLY))
):
    """Get an MDM configuration by ID"""
    try:
        config = manager.get_config(config_id)
        if not config:
            raise HTTPException(status_code=404, detail="MDM configuration not found")
        return config
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error getting MDM config {config_id}")
        raise HTTPException(status_code=500, detail="Failed to get MDM configuration")


@router.post("/configs", response_model=MdmConfigApi, status_code=status.HTTP_201_CREATED)
async def create_mdm_config(
    data: MdmConfigCreate,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager: MdmManager = MdmManagerDep,
    _: bool = Depends(PermissionChecker(MDM_FEATURE_ID, FeatureAccessLevel.READ_WRITE))
):
    """Create a new MDM configuration"""
    success = False
    details = {
        "params": {
            "name": data.name,
            "master_contract_id": data.master_contract_id,
            "entity_type": data.entity_type.value
        }
    }
    
    try:
        logger.info(f"Creating MDM config: name={data.name}, master_contract_id={data.master_contract_id}")
        result = manager.create_config(data, created_by=current_user.username)
        success = True
        details["config_id"] = result.id
        logger.info(f"Created MDM config successfully: id={result.id}, name={result.name}")
        return result
    except ValueError as e:
        logger.warning(f"Validation error creating MDM config: {e}")
        details["exception"] = {"type": "ValueError", "message": str(e)}
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error creating MDM config")
        details["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise HTTPException(status_code=500, detail="Failed to create MDM configuration")
    finally:
        audit_manager.log_action(
            db=db,
            username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=MDM_FEATURE_ID,
            action="CREATE",
            success=success,
            details=details
        )


@router.put("/configs/{config_id}", response_model=MdmConfigApi)
async def update_mdm_config(
    config_id: str,
    data: MdmConfigUpdate,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager: MdmManager = MdmManagerDep,
    _: bool = Depends(PermissionChecker(MDM_FEATURE_ID, FeatureAccessLevel.READ_WRITE))
):
    """Update an MDM configuration"""
    success = False
    details = {"params": {"config_id": config_id}}
    
    try:
        result = manager.update_config(config_id, data, updated_by=current_user.username)
        if not result:
            raise HTTPException(status_code=404, detail="MDM configuration not found")
        success = True
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error updating MDM config {config_id}")
        details["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise HTTPException(status_code=500, detail="Failed to update MDM configuration")
    finally:
        audit_manager.log_action(
            db=db,
            username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=MDM_FEATURE_ID,
            action="UPDATE",
            success=success,
            details=details
        )


@router.delete("/configs/{config_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_mdm_config(
    config_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager: MdmManager = MdmManagerDep,
    _: bool = Depends(PermissionChecker(MDM_FEATURE_ID, FeatureAccessLevel.READ_WRITE))
):
    """Delete an MDM configuration"""
    success = False
    details = {"params": {"config_id": config_id}}
    
    try:
        if not manager.delete_config(config_id):
            raise HTTPException(status_code=404, detail="MDM configuration not found")
        success = True
        return None
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error deleting MDM config {config_id}")
        details["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise HTTPException(status_code=500, detail="Failed to delete MDM configuration")
    finally:
        audit_manager.log_action(
            db=db,
            username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=MDM_FEATURE_ID,
            action="DELETE",
            success=success,
            details=details
        )


# ==================== Source Link Endpoints ====================

@router.get("/configs/{config_id}/sources", response_model=List[MdmSourceLinkApi])
async def list_source_links(
    config_id: str,
    manager: MdmManager = MdmManagerDep,
    _: bool = Depends(PermissionChecker(MDM_FEATURE_ID, FeatureAccessLevel.READ_ONLY))
):
    """List source links for a configuration"""
    try:
        return manager.list_source_links(config_id)
    except Exception as e:
        logger.exception(f"Error listing source links for config {config_id}")
        raise HTTPException(status_code=500, detail="Failed to list source links")


@router.post("/configs/{config_id}/sources", response_model=MdmSourceLinkApi, status_code=status.HTTP_201_CREATED)
async def create_source_link(
    config_id: str,
    data: MdmSourceLinkCreate,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager: MdmManager = MdmManagerDep,
    _: bool = Depends(PermissionChecker(MDM_FEATURE_ID, FeatureAccessLevel.READ_WRITE))
):
    """Link a source contract to an MDM configuration"""
    success = False
    details = {
        "params": {
            "config_id": config_id,
            "source_contract_id": data.source_contract_id
        }
    }
    
    try:
        result = manager.create_source_link(config_id, data)
        success = True
        details["link_id"] = result.id
        return result
    except ValueError as e:
        logger.warning(f"Validation error creating source link: {e}")
        details["exception"] = {"type": "ValueError", "message": str(e)}
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error creating source link")
        details["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise HTTPException(status_code=500, detail="Failed to create source link")
    finally:
        audit_manager.log_action(
            db=db,
            username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=MDM_FEATURE_ID,
            action="LINK_SOURCE",
            success=success,
            details=details
        )


@router.put("/sources/{link_id}", response_model=MdmSourceLinkApi)
async def update_source_link(
    link_id: str,
    data: MdmSourceLinkUpdate,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager: MdmManager = MdmManagerDep,
    _: bool = Depends(PermissionChecker(MDM_FEATURE_ID, FeatureAccessLevel.READ_WRITE))
):
    """Update a source link"""
    success = False
    details = {"params": {"link_id": link_id}}
    
    try:
        result = manager.update_source_link(link_id, data)
        if not result:
            raise HTTPException(status_code=404, detail="Source link not found")
        success = True
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error updating source link {link_id}")
        details["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise HTTPException(status_code=500, detail="Failed to update source link")
    finally:
        audit_manager.log_action(
            db=db,
            username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=MDM_FEATURE_ID,
            action="UPDATE_SOURCE_LINK",
            success=success,
            details=details
        )


@router.delete("/sources/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_source_link(
    link_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager: MdmManager = MdmManagerDep,
    _: bool = Depends(PermissionChecker(MDM_FEATURE_ID, FeatureAccessLevel.READ_WRITE))
):
    """Delete a source link"""
    success = False
    details = {"params": {"link_id": link_id}}
    
    try:
        if not manager.delete_source_link(link_id):
            raise HTTPException(status_code=404, detail="Source link not found")
        success = True
        return None
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error deleting source link {link_id}")
        details["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise HTTPException(status_code=500, detail="Failed to delete source link")
    finally:
        audit_manager.log_action(
            db=db,
            username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=MDM_FEATURE_ID,
            action="UNLINK_SOURCE",
            success=success,
            details=details
        )


# ==================== Match Run Endpoints ====================

@router.get("/configs/{config_id}/runs", response_model=List[MdmMatchRunApi])
async def list_match_runs(
    config_id: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    manager: MdmManager = MdmManagerDep,
    _: bool = Depends(PermissionChecker(MDM_FEATURE_ID, FeatureAccessLevel.READ_ONLY))
):
    """List match runs for a configuration"""
    try:
        return manager.list_match_runs(config_id, skip=skip, limit=limit)
    except Exception as e:
        logger.exception(f"Error listing match runs for config {config_id}")
        raise HTTPException(status_code=500, detail="Failed to list match runs")


@router.get("/runs/{run_id}", response_model=MdmMatchRunApi)
async def get_match_run(
    run_id: str,
    manager: MdmManager = MdmManagerDep,
    _: bool = Depends(PermissionChecker(MDM_FEATURE_ID, FeatureAccessLevel.READ_ONLY))
):
    """Get a match run by ID"""
    try:
        run = manager.get_match_run(run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Match run not found")
        return run
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error getting match run {run_id}")
        raise HTTPException(status_code=500, detail="Failed to get match run")


@router.post("/configs/{config_id}/start-run", response_model=MdmMatchRunApi)
async def start_match_run(
    config_id: str,
    source_link_id: Optional[str] = Body(None, embed=True),
    request: Request = None,
    db: DBSessionDep = None,
    audit_manager: AuditManagerDep = None,
    current_user: AuditCurrentUserDep = None,
    manager: MdmManager = MdmManagerDep,
    _: bool = Depends(PermissionChecker(MDM_FEATURE_ID, FeatureAccessLevel.READ_WRITE))
):
    """Start an MDM matching job"""
    success = False
    details = {
        "params": {
            "config_id": config_id,
            "source_link_id": source_link_id
        }
    }
    
    try:
        triggered_by = current_user.username if current_user else "manual"
        result = manager.start_match_run(
            config_id=config_id,
            source_link_id=source_link_id,
            triggered_by=triggered_by
        )
        success = True
        details["run_id"] = result.id
        return result
    except ValueError as e:
        logger.warning(f"Validation error starting match run: {e}")
        details["exception"] = {"type": "ValueError", "message": str(e)}
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error starting match run")
        details["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise HTTPException(status_code=500, detail="Failed to start match run")
    finally:
        if audit_manager and current_user:
            audit_manager.log_action(
                db=db,
                username=current_user.username,
                ip_address=request.client.host if request and request.client else None,
                feature=MDM_FEATURE_ID,
                action="START_MATCH_RUN",
                success=success,
                details=details
            )


# ==================== Match Candidate Endpoints ====================

@router.get("/runs/{run_id}/candidates", response_model=List[MdmMatchCandidateApi])
async def list_match_candidates(
    run_id: str,
    status: Optional[str] = Query(None, description="Filter by status"),
    skip: int = Query(0, ge=0),
    limit: Optional[int] = Query(None, ge=1),
    manager: MdmManager = MdmManagerDep,
    _: bool = Depends(PermissionChecker(MDM_FEATURE_ID, FeatureAccessLevel.READ_ONLY))
):
    """List match candidates for a run"""
    try:
        return manager.list_match_candidates(run_id, status=status, skip=skip, limit=limit)
    except Exception as e:
        logger.exception(f"Error listing match candidates for run {run_id}")
        raise HTTPException(status_code=500, detail="Failed to list match candidates")


@router.get("/candidates/{candidate_id}", response_model=MdmMatchCandidateApi)
async def get_match_candidate(
    candidate_id: str,
    manager: MdmManager = MdmManagerDep,
    _: bool = Depends(PermissionChecker(MDM_FEATURE_ID, FeatureAccessLevel.READ_ONLY))
):
    """Get a match candidate by ID"""
    try:
        candidate = manager.get_match_candidate(candidate_id)
        if not candidate:
            raise HTTPException(status_code=404, detail="Match candidate not found")
        return candidate
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error getting match candidate {candidate_id}")
        raise HTTPException(status_code=500, detail="Failed to get match candidate")


@router.put("/candidates/{candidate_id}", response_model=MdmMatchCandidateApi)
async def update_match_candidate(
    candidate_id: str,
    data: MdmMatchCandidateUpdate,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager: MdmManager = MdmManagerDep,
    _: bool = Depends(PermissionChecker(MDM_FEATURE_ID, FeatureAccessLevel.READ_WRITE))
):
    """Update a match candidate (approve/reject with optional merged data)"""
    success = False
    details = {
        "params": {
            "candidate_id": candidate_id,
            "status": data.status.value
        }
    }
    
    try:
        result = manager.update_match_candidate(
            candidate_id,
            data,
            reviewed_by=current_user.username
        )
        if not result:
            raise HTTPException(status_code=404, detail="Match candidate not found")
        success = True
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error updating match candidate {candidate_id}")
        details["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise HTTPException(status_code=500, detail="Failed to update match candidate")
    finally:
        audit_manager.log_action(
            db=db,
            username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=MDM_FEATURE_ID,
            action=f"REVIEW_{data.status.value.upper()}",
            success=success,
            details=details
        )


# ==================== Review Integration Endpoints ====================

@router.post("/runs/{run_id}/create-review", response_model=MdmCreateReviewResponse)
async def create_review_for_run(
    run_id: str,
    data: MdmCreateReviewRequest,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager: MdmManager = MdmManagerDep,
    _: bool = Depends(PermissionChecker(MDM_FEATURE_ID, FeatureAccessLevel.READ_WRITE))
):
    """Create an Asset Review request for match candidates"""
    success = False
    details = {
        "params": {
            "run_id": run_id,
            "reviewer_email": data.reviewer_email
        }
    }
    
    try:
        requester_email = current_user.email if current_user and current_user.email else "system@company.com"
        result = manager.create_review_for_matches(
            run_id=run_id,
            reviewer_email=data.reviewer_email,
            requester_email=requester_email,
            notes=data.notes
        )
        success = True
        details["review_id"] = result.review_id
        details["candidate_count"] = result.candidate_count
        return result
    except ValueError as e:
        logger.warning(f"Validation error creating review: {e}")
        details["exception"] = {"type": "ValueError", "message": str(e)}
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error creating review for match run")
        details["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise HTTPException(status_code=500, detail="Failed to create review")
    finally:
        audit_manager.log_action(
            db=db,
            username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=MDM_FEATURE_ID,
            action="CREATE_REVIEW",
            success=success,
            details=details
        )


@router.post("/runs/{run_id}/sync-review-statuses")
async def sync_review_statuses(
    run_id: str,
    manager: MdmManager = MdmManagerDep,
    _: bool = Depends(PermissionChecker(MDM_FEATURE_ID, FeatureAccessLevel.READ_WRITE))
):
    """Sync ReviewedAsset statuses with MDM candidate statuses.
    
    This fixes out-of-sync data from before auto-sync was implemented.
    """
    try:
        result = manager.sync_review_asset_statuses(run_id)
        return {
            "success": True,
            "run_id": run_id,
            **result
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception(f"Error syncing review statuses for run {run_id}")
        raise HTTPException(status_code=500, detail="Failed to sync review statuses")


# ==================== Merge Endpoints ====================

@router.post("/runs/{run_id}/merge-approved", response_model=MdmMergeResponse)
async def merge_approved_matches(
    run_id: str,
    data: MdmMergeRequest = Body(default=MdmMergeRequest()),
    request: Request = None,
    db: DBSessionDep = None,
    audit_manager: AuditManagerDep = None,
    current_user: AuditCurrentUserDep = None,
    manager: MdmManager = MdmManagerDep,
    _: bool = Depends(PermissionChecker(MDM_FEATURE_ID, FeatureAccessLevel.READ_WRITE))
):
    """Process and merge all approved matches"""
    success = False
    details = {
        "params": {
            "run_id": run_id,
            "dry_run": data.dry_run
        }
    }
    
    try:
        result = manager.process_approved_matches(run_id, dry_run=data.dry_run)
        success = True
        details["merged_count"] = result.merged_count
        details["failed_count"] = result.failed_count
        return result
    except ValueError as e:
        logger.warning(f"Validation error merging matches: {e}")
        details["exception"] = {"type": "ValueError", "message": str(e)}
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error merging approved matches")
        details["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise HTTPException(status_code=500, detail="Failed to merge approved matches")
    finally:
        if audit_manager and current_user:
            audit_manager.log_action(
                db=db,
                username=current_user.username,
                ip_address=request.client.host if request and request.client else None,
                feature=MDM_FEATURE_ID,
                action="MERGE_APPROVED",
                success=success,
                details=details
            )


def register_routes(app):
    """Register MDM routes with the app"""
    app.include_router(router)
    logger.info("MDM routes registered")

