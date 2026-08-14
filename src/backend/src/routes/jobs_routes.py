import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from src.common.authorization import PermissionChecker
from src.common.dependencies import DBSessionDep, AuditManagerDep, AuditCurrentUserDep, CurrentUserDep
from src.common.features import FeatureAccessLevel
from src.common.manager_dependencies import (
    get_jobs_manager,
    get_notifications_manager,
    get_settings_manager,
)
from src.common.database import get_db
from src.controller.jobs_manager import JobsManager
from src.controller.notifications_manager import NotificationsManager
from src.controller.settings_manager import SettingsManager
from src.models.notifications import Notification, NotificationType
from src.repositories.workflow_job_runs_repository import workflow_job_run_repo
from src.models.workflow_job_runs import WorkflowJobRun
from src.repositories.workflow_installations_repository import workflow_installation_repo
from src.models.workflow_configurations import (
    WorkflowParameterDefinition,
    WorkflowConfiguration,
    WorkflowConfigurationUpdate,
    WorkflowConfigurationResponse
)

# Configure logging
from src.common.logging import get_logger
logger = get_logger(__name__)

router = APIRouter(prefix="/api", tags=["Jobs"])

@router.get('/jobs/runs')
async def get_job_runs(
    request: Request,
    audit_db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    workflow_installation_id: Optional[str] = None,
    workflow_id: Optional[str] = None,
    limit: int = 10,
    db: Session = Depends(get_db),
    _: bool = Depends(PermissionChecker('jobs', FeatureAccessLevel.READ_ONLY))
) -> List[WorkflowJobRun]:
    """Get recent job runs, optionally filtered by workflow installation or workflow ID.

    Args:
        workflow_installation_id: Optional filter by workflow installation UUID
        workflow_id: Optional filter by workflow ID (e.g., 'business-glossary-sync')
        limit: Maximum number of runs to return (default 10, max 100)

    Returns:
        List of job runs ordered by start_time descending
    """
    success = False
    details = {
        "params": {
            "workflow_installation_id": workflow_installation_id,
            "workflow_id": workflow_id,
            "limit": limit
        }
    }

    try:
        # Cap limit at 100
        limit = min(limit, 100)

        runs = workflow_job_run_repo.get_recent_runs(
            db,
            workflow_installation_id=workflow_installation_id,
            workflow_id=workflow_id,
            limit=limit
        )

        logger.info(f"get_job_runs: Found {len(runs)} runs (workflow_id={workflow_id}, installation_id={workflow_installation_id})")

        # Convert to Pydantic models (Pydantic v2)
        result = [WorkflowJobRun.model_validate(run) for run in runs]
        logger.info(f"get_job_runs: Returning {len(result)} validated runs")
        success = True
        details["run_count"] = len(result)
        return result
    except HTTPException as e:
        details["exception"] = {
            "type": "HTTPException",
            "status_code": e.status_code,
            "detail": e.detail
        }
        raise
    except Exception as e:
        logger.error(f"Error getting job runs: {e}")
        details["exception"] = {
            "type": type(e).__name__,
            "message": str(e)
        }
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get job runs: {str(e)}"
        )
    finally:
        audit_manager.log_action(
            db=audit_db,
            username=current_user.username if current_user else "anonymous",
            ip_address=request.client.host if request.client else None,
            feature="jobs",
            action="LIST",
            success=success,
            details=details
        )

@router.post('/jobs/{run_id}/cancel')
async def cancel_job(
    run_id: int,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    jobs_manager: JobsManager = Depends(get_jobs_manager),
    _: bool = Depends(PermissionChecker('jobs', FeatureAccessLevel.ADMIN))
) -> Dict[str, bool]:
    """Cancel a running job."""
    success = False
    details = {
        "params": {
            "run_id": run_id
        }
    }

    try:
        jobs_manager.cancel_run(run_id=run_id)
        success = True
        return {"success": True}
    except HTTPException as e:
        details["exception"] = {
            "type": "HTTPException",
            "status_code": e.status_code,
            "detail": e.detail
        }
        raise
    except Exception as e:
        logger.error(f"Error cancelling job run {run_id}: {e}")
        details["exception"] = {
            "type": type(e).__name__,
            "message": str(e)
        }
        raise HTTPException(
            status_code=500,
            detail=f"Failed to cancel job run: {str(e)}"
        )
    finally:
        audit_manager.log_action(
            db=db,
            username=current_user.username if current_user else "anonymous",
            ip_address=request.client.host if request.client else None,
            feature="jobs",
            action="CANCEL",
            success=success,
            details=details
        )

def register_routes(app):
    """Register job routes with the FastAPI app."""
    app.include_router(router)
    logger.info("Job routes registered")


@router.get('/jobs/workflows/status')
async def get_workflow_statuses(
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    jobs_manager: JobsManager = Depends(get_jobs_manager),
    _: bool = Depends(PermissionChecker('jobs', FeatureAccessLevel.READ_ONLY))
) -> Dict[str, Any]:
    success = False
    details = {"params": {}}

    try:
        result = jobs_manager.get_workflow_statuses()
        success = True
        details["workflow_count"] = len(result) if isinstance(result, dict) else 0
        return result
    except HTTPException as e:
        details["exception"] = {
            "type": "HTTPException",
            "status_code": e.status_code,
            "detail": e.detail
        }
        raise
    except Exception as e:
        logger.error(f"Error getting workflow statuses: {e}")
        details["exception"] = {
            "type": type(e).__name__,
            "message": str(e)
        }
        raise HTTPException(status_code=500, detail="Failed to fetch workflow statuses")
    finally:
        audit_manager.log_action(
            db=db,
            username=current_user.username if current_user else "anonymous",
            ip_address=request.client.host if request.client else None,
            feature="jobs",
            action="GET",
            success=success,
            details=details
        )

# Non-conflicting alias to avoid path-param capture by /jobs/{run_id}/status
@router.get('/jobs/workflows/statuses')
async def get_workflow_statuses_alias(
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    jobs_manager: JobsManager = Depends(get_jobs_manager),
    _: bool = Depends(PermissionChecker('jobs', FeatureAccessLevel.READ_ONLY))
) -> Dict[str, Any]:
    success = False
    details = {"params": {}}

    try:
        result = jobs_manager.get_workflow_statuses()
        success = True
        details["workflow_count"] = len(result) if isinstance(result, dict) else 0
        return result
    except HTTPException as e:
        details["exception"] = {
            "type": "HTTPException",
            "status_code": e.status_code,
            "detail": e.detail
        }
        raise
    except Exception as e:
        logger.error(f"Error getting workflow statuses: {e}")
        details["exception"] = {
            "type": type(e).__name__,
            "message": str(e)
        }
        raise HTTPException(status_code=500, detail="Failed to fetch workflow statuses")
    finally:
        audit_manager.log_action(
            db=db,
            username=current_user.username if current_user else "anonymous",
            ip_address=request.client.host if request.client else None,
            feature="jobs",
            action="GET",
            success=success,
            details=details
        )


@router.post('/jobs/workflows/{workflow_id}/start')
async def start_workflow(
    workflow_id: str,
    request: Request,
    audit_db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    jobs_manager: JobsManager = Depends(get_jobs_manager),
    db: Session = Depends(get_db),
    _: bool = Depends(PermissionChecker('jobs', FeatureAccessLevel.ADMIN))
) -> Dict[str, Any]:
    success = False
    details = {
        "params": {
            "workflow_id": workflow_id
        }
    }
    run_id = None

    try:
        # Lookup installation
        inst = workflow_installation_repo.get_by_workflow_id(db=db, workflow_id=workflow_id)
        if inst is None:
            raise HTTPException(status_code=404, detail=f"Workflow '{workflow_id}' not installed")

        # Run job - database params and saved configuration are auto-injected
        run_id = jobs_manager.run_job(
            job_id=int(inst.job_id),
            job_name=workflow_id,
            workflow_id=workflow_id  # Enable auto-injection of database params
        )
        success = True
        details["run_id"] = run_id
        return {"run_id": run_id}
    except HTTPException as e:
        details["exception"] = {
            "type": "HTTPException",
            "status_code": e.status_code,
            "detail": e.detail
        }
        raise
    except Exception as e:
        logger.error(f"Failed to start workflow {workflow_id}: {e}")
        details["exception"] = {
            "type": type(e).__name__,
            "message": str(e)
        }
        raise HTTPException(status_code=500, detail="Failed to start workflow")
    finally:
        audit_manager.log_action(
            db=audit_db,
            username=current_user.username if current_user else "anonymous",
            ip_address=request.client.host if request.client else None,
            feature="jobs",
            action="START",
            success=success,
            details=details
        )


@router.post('/jobs/workflows/{workflow_id}/stop')
async def stop_workflow(
    workflow_id: str,
    request: Request,
    audit_db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    jobs_manager: JobsManager = Depends(get_jobs_manager),
    db: Session = Depends(get_db),
    _: bool = Depends(PermissionChecker('jobs', FeatureAccessLevel.ADMIN))
) -> Dict[str, Any]:
    success = False
    details = {
        "params": {
            "workflow_id": workflow_id
        }
    }

    try:
        # Lookup installation and active run
        inst = workflow_installation_repo.get_by_workflow_id(db=db, workflow_id=workflow_id)
        if inst is None:
            raise HTTPException(status_code=404, detail=f"Workflow '{workflow_id}' not installed")
        active_run_id = jobs_manager.get_active_run_id(int(inst.job_id))
        if not active_run_id:
            raise HTTPException(status_code=400, detail="Workflow is not running")
        jobs_manager.cancel_run(active_run_id)
        success = True
        details["stopped_run_id"] = active_run_id
        return {"success": True}
    except HTTPException as e:
        details["exception"] = {
            "type": "HTTPException",
            "status_code": e.status_code,
            "detail": e.detail
        }
        raise
    except Exception as e:
        logger.error(f"Failed to stop workflow {workflow_id}: {e}")
        details["exception"] = {
            "type": type(e).__name__,
            "message": str(e)
        }
        raise HTTPException(status_code=500, detail="Failed to stop workflow")
    finally:
        audit_manager.log_action(
            db=audit_db,
            username=current_user.username if current_user else "anonymous",
            ip_address=request.client.host if request.client else None,
            feature="jobs",
            action="STOP",
            success=success,
            details=details
        )


@router.post('/jobs/workflows/{workflow_id}/pause')
async def pause_workflow(
    workflow_id: str,
    request: Request,
    audit_db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    jobs_manager: JobsManager = Depends(get_jobs_manager),
    db: Session = Depends(get_db),
    _: bool = Depends(PermissionChecker('jobs', FeatureAccessLevel.ADMIN))
) -> Dict[str, Any]:
    success = False
    details = {
        "params": {
            "workflow_id": workflow_id
        }
    }

    try:
        inst = workflow_installation_repo.get_by_workflow_id(db=db, workflow_id=workflow_id)
        if not inst:
            raise HTTPException(status_code=404, detail=f"Workflow '{workflow_id}' not installed")
        jobs_manager.pause_job(int(inst.job_id))
        success = True
        details["job_id"] = inst.job_id
        return {"success": True}
    except HTTPException as e:
        details["exception"] = {
            "type": "HTTPException",
            "status_code": e.status_code,
            "detail": e.detail
        }
        raise
    except Exception as e:
        logger.error(f"Failed to pause workflow {workflow_id}: {e}")
        details["exception"] = {
            "type": type(e).__name__,
            "message": str(e)
        }
        raise HTTPException(status_code=500, detail="Failed to pause workflow")
    finally:
        audit_manager.log_action(
            db=audit_db,
            username=current_user.username if current_user else "anonymous",
            ip_address=request.client.host if request.client else None,
            feature="jobs",
            action="PAUSE",
            success=success,
            details=details
        )


@router.post('/jobs/workflows/{workflow_id}/resume')
async def resume_workflow(
    workflow_id: str,
    request: Request,
    audit_db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    jobs_manager: JobsManager = Depends(get_jobs_manager),
    db: Session = Depends(get_db),
    _: bool = Depends(PermissionChecker('jobs', FeatureAccessLevel.ADMIN))
) -> Dict[str, Any]:
    success = False
    details = {
        "params": {
            "workflow_id": workflow_id
        }
    }

    try:
        inst = workflow_installation_repo.get_by_workflow_id(db=db, workflow_id=workflow_id)
        if not inst:
            raise HTTPException(status_code=404, detail=f"Workflow '{workflow_id}' not installed")
        jobs_manager.resume_job(int(inst.job_id))
        success = True
        details["job_id"] = inst.job_id
        return {"success": True}
    except HTTPException as e:
        details["exception"] = {
            "type": "HTTPException",
            "status_code": e.status_code,
            "detail": e.detail
        }
        raise
    except Exception as e:
        logger.error(f"Failed to resume workflow {workflow_id}: {e}")
        details["exception"] = {
            "type": type(e).__name__,
            "message": str(e)
        }
        raise HTTPException(status_code=500, detail="Failed to resume workflow")
    finally:
        audit_manager.log_action(
            db=audit_db,
            username=current_user.username if current_user else "anonymous",
            ip_address=request.client.host if request.client else None,
            feature="jobs",
            action="RESUME",
            success=success,
            details=details
        )

@router.get('/jobs/{run_id}/status')
async def get_job_status(
    run_id: int,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    jobs_manager: JobsManager = Depends(get_jobs_manager),
    _: bool = Depends(PermissionChecker('jobs', FeatureAccessLevel.READ_ONLY))
) -> Dict[str, Any]:
    """Get status of a job run."""
    success = False
    details = {
        "params": {
            "run_id": run_id
        }
    }

    try:
        status = jobs_manager.get_job_status(run_id=run_id)
        if status is None:
            raise HTTPException(
                status_code=404,
                detail=f"Job run {run_id} not found"
            )
        success = True
        return status
    except HTTPException as e:
        details["exception"] = {
            "type": "HTTPException",
            "status_code": e.status_code,
            "detail": e.detail
        }
        raise
    except Exception as e:
        logger.error(f"Error getting job status for run {run_id}: {e}")
        details["exception"] = {
            "type": type(e).__name__,
            "message": str(e)
        }
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get job status: {str(e)}"
        )
    finally:
        audit_manager.log_action(
            db=db,
            username=current_user.username if current_user else "anonymous",
            ip_address=request.client.host if request.client else None,
            feature="jobs",
            action="GET",
            success=success,
            details=details
        )


# --- Workflow Configuration Routes ---

@router.get('/jobs/workflows/{workflow_id}/parameter-definitions')
async def get_workflow_parameter_definitions(
    workflow_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    jobs_manager: JobsManager = Depends(get_jobs_manager),
    _: bool = Depends(PermissionChecker('jobs', FeatureAccessLevel.READ_ONLY))
) -> List[WorkflowParameterDefinition]:
    """Get parameter definitions for a workflow from its YAML configuration.

    Returns the configurable_parameters section from the workflow YAML.
    """
    success = False
    details = {
        "params": {
            "workflow_id": workflow_id
        }
    }

    try:
        definitions = jobs_manager.get_workflow_parameter_definitions(workflow_id)
        success = True
        details["parameter_count"] = len(definitions)
        return definitions
    except HTTPException as e:
        details["exception"] = {
            "type": "HTTPException",
            "status_code": e.status_code,
            "detail": e.detail
        }
        raise
    except Exception as e:
        logger.error(f"Error getting parameter definitions for {workflow_id}: {e}")
        details["exception"] = {
            "type": type(e).__name__,
            "message": str(e)
        }
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get parameter definitions: {str(e)}"
        )
    finally:
        audit_manager.log_action(
            db=db,
            username=current_user.username if current_user else "anonymous",
            ip_address=request.client.host if request.client else None,
            feature="jobs",
            action="GET",
            success=success,
            details=details
        )


@router.get('/jobs/workflows/{workflow_id}/configuration')
async def get_workflow_configuration(
    workflow_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    jobs_manager: JobsManager = Depends(get_jobs_manager),
    _: bool = Depends(PermissionChecker('jobs', FeatureAccessLevel.READ_ONLY))
) -> Dict[str, Any]:
    """Get saved configuration for a workflow.

    Returns the stored parameter values for this workflow, or empty dict if not configured.
    """
    success = False
    details = {
        "params": {
            "workflow_id": workflow_id
        }
    }

    try:
        configuration = jobs_manager.get_workflow_configuration(workflow_id)
        success = True
        return {"workflow_id": workflow_id, "configuration": configuration or {}}
    except HTTPException as e:
        details["exception"] = {
            "type": "HTTPException",
            "status_code": e.status_code,
            "detail": e.detail
        }
        raise
    except Exception as e:
        logger.error(f"Error getting configuration for {workflow_id}: {e}")
        details["exception"] = {
            "type": type(e).__name__,
            "message": str(e)
        }
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get configuration: {str(e)}"
        )
    finally:
        audit_manager.log_action(
            db=db,
            username=current_user.username if current_user else "anonymous",
            ip_address=request.client.host if request.client else None,
            feature="jobs",
            action="GET",
            success=success,
            details=details
        )


@router.put('/jobs/workflows/{workflow_id}/configuration')
async def update_workflow_configuration(
    workflow_id: str,
    config_update: WorkflowConfigurationUpdate,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    jobs_manager: JobsManager = Depends(get_jobs_manager),
    _: bool = Depends(PermissionChecker('jobs', FeatureAccessLevel.ADMIN))
) -> WorkflowConfiguration:
    """Update workflow configuration.

    Saves parameter values for a workflow. These will be merged with runtime parameters
    when the workflow is executed.
    """
    success = False
    details = {
        "params": {
            "workflow_id": workflow_id,
            "configuration_keys": list(config_update.configuration.keys()) if config_update.configuration else []
        }
    }

    try:
        updated_config = jobs_manager.update_workflow_configuration(
            workflow_id=workflow_id,
            configuration=config_update.configuration
        )
        success = True
        return updated_config
    except HTTPException as e:
        details["exception"] = {
            "type": "HTTPException",
            "status_code": e.status_code,
            "detail": e.detail
        }
        raise
    except Exception as e:
        logger.error(f"Error updating configuration for {workflow_id}: {e}")
        details["exception"] = {
            "type": type(e).__name__,
            "message": str(e)
        }
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update configuration: {str(e)}"
        )
    finally:
        audit_manager.log_action(
            db=db,
            username=current_user.username if current_user else "anonymous",
            ip_address=request.client.host if request.client else None,
            feature="jobs",
            action="UPDATE",
            success=success,
            details=details
        )


# Workflows whose install state gates a user-facing feature. Features backed by these
# jobs need to know whether the job is installed so they can disable their entry point
# instead of failing on click. Deliberately an allowlist: the capabilities endpoint is
# readable by every authenticated user, so it must not become a full job inventory.
FEATURE_GATING_WORKFLOW_IDS = (
    'dqx_profile_datasets',
    'mdm_match_detect',
)


@router.get('/jobs/capabilities')
async def get_job_capabilities(
    db: DBSessionDep,
    _current_user: CurrentUserDep,
    settings_manager: SettingsManager = Depends(get_settings_manager),
) -> Dict[str, Any]:
    """Report install state of feature-gating workflows to any authenticated user.

    The regular job endpoints require the 'jobs' feature permission, which non-admin
    roles do not have. Features like DQX profiling still need to know whether their
    backing job exists so the UI can disable the button and explain why, so this
    endpoint exposes only booleans for an allowlist of workflow IDs — no job IDs,
    cluster IDs or run history.
    """
    installed_ids = {inst.workflow_id for inst in workflow_installation_repo.get_all_installed(db)}

    return {
        'workflows': {
            workflow_id: {'installed': workflow_id in installed_ids}
            for workflow_id in FEATURE_GATING_WORKFLOW_IDS
        },
        # Whether users may ask an admin to enable a disabled job.
        'enablement_requests_allowed': settings_manager.get_settings().get(
            'allow_job_enablement_requests', False
        ),
    }


@router.post('/jobs/workflows/{workflow_id}/request-enablement')
async def request_workflow_enablement(
    workflow_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    settings_manager: SettingsManager = Depends(get_settings_manager),
    notifications_manager: NotificationsManager = Depends(get_notifications_manager),
) -> Dict[str, Any]:
    """Notify admins that a user needs a disabled background job enabled.

    Intentionally not gated by the 'jobs' permission: the point is to let ordinary
    users who cannot manage jobs ask someone who can. Guarded instead by the
    ALLOW_JOB_ENABLEMENT_REQUESTS setting and the workflow allowlist, and deduplicated
    so repeated clicks do not flood the admin bell.
    """
    success = False
    details: Dict[str, Any] = {'workflow_id': workflow_id}

    try:
        if workflow_id not in FEATURE_GATING_WORKFLOW_IDS:
            raise HTTPException(status_code=404, detail="Unknown workflow")

        if not settings_manager.get_settings().get('allow_job_enablement_requests', False):
            raise HTTPException(
                status_code=403,
                detail="Background job enablement requests are disabled for this deployment.",
            )

        # Nothing to request if it is already installed.
        if workflow_installation_repo.get_by_workflow_id(db=db, workflow_id=workflow_id):
            details['already_installed'] = True
            success = True
            return {'requested': False, 'reason': 'already_installed'}

        requester_email = current_user.email or current_user.username if current_user else 'unknown'
        action_payload = {'workflow_id': workflow_id}

        # Dedupe on workflow only (not requester) so one pending ask per job reaches admins.
        if notifications_manager.has_unhandled_actionable_notification(
            db=db,
            action_type='handle_job_enable_request',
            action_payload=action_payload,
        ):
            details['deduplicated'] = True
            success = True
            return {'requested': False, 'reason': 'already_requested'}

        display_name = next(
            (w['name'] for w in settings_manager.list_available_workflows() if w.get('id') == workflow_id),
            workflow_id,
        )

        notification = Notification(
            id=str(uuid.uuid4()),
            created_at=datetime.utcnow(),
            type=NotificationType.ACTION_REQUIRED,
            title="Background job enablement requested",
            subtitle=f"Job: {display_name}",
            description=(
                f"User '{requester_email}' tried to use a feature that needs the "
                f"'{display_name}' background job, which is not enabled. "
                f"Enable it under Settings > Jobs."
            ),
            link='/settings/jobs',
            recipient="Admin",
            action_type='handle_job_enable_request',
            action_payload={**action_payload, 'requester_email': requester_email},
            can_delete=False,
        )
        notifications_manager.create_notification(notification=notification, db=db)

        success = True
        return {'requested': True}
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to request enablement for workflow %s: %s", workflow_id, e, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to submit enablement request")
    finally:
        audit_manager.log_action(
            db=db,
            username=current_user.username if current_user else "anonymous",
            ip_address=request.client.host if request.client else None,
            feature="jobs",
            action="REQUEST_ENABLEMENT",
            success=success,
            details=details,
        )
