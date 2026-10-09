from typing import List

from fastapi import APIRouter, Depends, HTTPException, status, Request, BackgroundTasks

from src.models.projects import (
    ProjectCreate,
    ProjectUpdate,
    ProjectRead,
    ProjectSummary,
    UserProjectAccess,
    ProjectTeamAssignment,
    ProjectContext,
    ProjectAccessRequest,
    ProjectAccessRequestResponse
)
from src.controller.projects_manager import ProjectsManager, projects_manager
from src.common.database import get_db
from sqlalchemy.orm import Session
from src.common.authorization import PermissionChecker, is_user_admin
from src.common.features import FeatureAccessLevel
from src.common.config import get_settings, Settings
from src.common.dependencies import (
    DBSessionDep,
    CurrentUserDep,
    NotificationsManagerDep,
    AuditManagerDep,
    AuditCurrentUserDep
)
from src.models.users import UserInfo
from src.common.errors import NotFoundError, ConflictError

from src.common.logging import get_logger
logger = get_logger(__name__)

# Define router
router = APIRouter(prefix="/api", tags=["Projects"])

# Feature ID constant
PROJECTS_FEATURE_ID = "projects"

# Project dependency — resolve from app.state so index-upsert/remove hooks fire.
# Startup builds the ProjectsManager instance that `set_search_manager(...)` wires
# up (``app.state.projects_manager``). The module-level ``projects_manager``
# singleton is a separate instance whose ``_search_manager`` stays None, so a
# route that reaches it would silently skip the search index notification.
# Falls back to the singleton for the handful of unit tests that call the
# getter without a request context.
def get_projects_manager(request: Request = None) -> ProjectsManager:
    if request is not None:
        state_mgr = getattr(request.app.state, "projects_manager", None)
        if isinstance(state_mgr, ProjectsManager):
            return state_mgr
    return projects_manager


# Project Routes
@router.post(
    "/projects",
    response_model=ProjectRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(PermissionChecker(PROJECTS_FEATURE_ID, FeatureAccessLevel.READ_WRITE))]
)
def create_project(
    request: Request,
    project_in: ProjectCreate,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager = Depends(get_projects_manager)
):
    """Creates a new project."""
    success = False
    details_for_audit = {
        "params": {"project_name": project_in.name, "owner_team_id": project_in.owner_team_id if hasattr(project_in, 'owner_team_id') else None},
    }
    created_project_id = None

    logger.info(f"User '{current_user.email}' attempting to create project: {project_in.name}")
    try:
        created_project = manager.create_project(db=db, project_in=project_in, current_user_id=current_user.email)
        db.commit()
        success = True
        created_project_id = str(created_project.id)
        return created_project
    except ConflictError as e:
        db.rollback()
        logger.error("Project creation conflict for '%s': %s", project_in.name, e)
        details_for_audit["exception"] = {"type": "ConflictError", "message": str(e)}
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Project already exists")
    except Exception as e:
        db.rollback()
        logger.exception("Failed to create project '%s'", project_in.name)
        details_for_audit["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create project")
    finally:
        if created_project_id:
            details_for_audit["created_resource_id"] = created_project_id
        audit_manager.log_action(
            db=db,
            username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=PROJECTS_FEATURE_ID,
            action="CREATE",
            success=success,
            details=details_for_audit
        )


@router.get(
    "/projects",
    response_model=List[ProjectRead],
    dependencies=[Depends(PermissionChecker(PROJECTS_FEATURE_ID, FeatureAccessLevel.READ_ONLY))]
)
def get_all_projects(
    db: DBSessionDep,
    current_user: CurrentUserDep,
    settings: Settings = Depends(get_settings),
    manager = Depends(get_projects_manager),
    skip: int = 0,
    limit: int = 100
):
    """Lists projects visible to the user based on domain relationships."""
    logger.debug(f"Fetching projects (skip={skip}, limit={limit}) for user: {current_user.email}")
    try:
        # Check if user is admin using configured admin groups
        user_groups = current_user.groups or []
        is_admin = is_user_admin(user_groups, settings)
        
        return manager.get_all_projects(
            db=db, 
            skip=skip, 
            limit=limit,
            user_identifier=current_user.email,
            user_groups=user_groups,
            is_admin=is_admin
        )
    except Exception as e:
        logger.exception(f"Failed to fetch projects: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to fetch projects")


@router.get(
    "/projects/summary",
    response_model=List[ProjectSummary],
    dependencies=[Depends(PermissionChecker(PROJECTS_FEATURE_ID, FeatureAccessLevel.READ_ONLY))]
)
def get_projects_summary(
    db: DBSessionDep,
    manager = Depends(get_projects_manager)
):
    """Gets a summary list of projects for dropdowns/selection."""
    logger.debug("Fetching projects summary")
    try:
        return manager.get_projects_summary(db=db)
    except Exception as e:
        logger.exception(f"Failed to fetch projects summary: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to fetch projects summary")


@router.get(
    "/projects/{project_id}",
    response_model=ProjectRead,
    dependencies=[Depends(PermissionChecker(PROJECTS_FEATURE_ID, FeatureAccessLevel.READ_ONLY))]
)
def get_project(
    project_id: str,
    db: DBSessionDep,
    manager = Depends(get_projects_manager)
):
    """Gets a specific project by its ID."""
    logger.debug(f"Fetching project with id: {project_id}")
    project = manager.get_project_by_id(db=db, project_id=project_id)
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Project with id '{project_id}' not found")
    return project


@router.put(
    "/projects/{project_id}",
    response_model=ProjectRead,
    dependencies=[Depends(PermissionChecker(PROJECTS_FEATURE_ID, FeatureAccessLevel.READ_WRITE))]
)
def update_project(
    project_id: str,
    request: Request,
    project_in: ProjectUpdate,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager = Depends(get_projects_manager)
):
    """Updates an existing project."""
    success = False
    details_for_audit = {
        "params": {"project_id": project_id},
    }

    logger.info(f"User '{current_user.email}' attempting to update project: {project_id}")
    try:
        updated_project = manager.update_project(
            db=db,
            project_id=project_id,
            project_in=project_in,
            current_user_id=current_user.email
        )
        db.commit()
        success = True
        return updated_project
    except NotFoundError as e:
        db.rollback()
        logger.error("Project not found for update %s: %s", project_id, e)
        details_for_audit["exception"] = {"type": "NotFoundError", "message": str(e)}
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    except ConflictError as e:
        db.rollback()
        logger.error("Project update conflict %s: %s", project_id, e)
        details_for_audit["exception"] = {"type": "ConflictError", "message": str(e)}
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Project conflict")
    except Exception as e:
        db.rollback()
        logger.exception("Failed to update project %s", project_id)
        details_for_audit["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to update project")
    finally:
        if success:
            details_for_audit["updated_resource_id"] = project_id
        audit_manager.log_action(
            db=db,
            username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=PROJECTS_FEATURE_ID,
            action="UPDATE",
            success=success,
            details=details_for_audit
        )


@router.delete(
    "/projects/{project_id}",
    response_model=ProjectRead,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(PermissionChecker(PROJECTS_FEATURE_ID, FeatureAccessLevel.ADMIN))]
)
def delete_project(
    project_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager = Depends(get_projects_manager)
):
    """Deletes a project. Requires Admin privileges."""
    success = False
    details_for_audit = {
        "params": {"project_id": project_id},
    }

    logger.info(f"User '{current_user.email}' attempting to delete project: {project_id}")
    try:
        deleted_project = manager.delete_project(db=db, project_id=project_id)
        db.commit()
        success = True
        return deleted_project
    except NotFoundError as e:
        db.rollback()
        logger.error("Project not found for deletion %s: %s", project_id, e)
        details_for_audit["exception"] = {"type": "NotFoundError", "message": str(e)}
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    except Exception as e:
        db.rollback()
        logger.exception(f"Failed to delete project {project_id}: {e}")
        details_for_audit["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to delete project: {e!s}")
    finally:
        if success:
            details_for_audit["deleted_resource_id"] = project_id
        audit_manager.log_action(
            db=db,
            username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=PROJECTS_FEATURE_ID,
            action="DELETE",
            success=success,
            details=details_for_audit
        )


# Team Assignment Routes
@router.post(
    "/projects/{project_id}/teams",
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(PermissionChecker(PROJECTS_FEATURE_ID, FeatureAccessLevel.READ_WRITE))]
)
def assign_team_to_project(
    project_id: str,
    assignment: ProjectTeamAssignment,
    db: DBSessionDep,
    current_user: CurrentUserDep,
    manager = Depends(get_projects_manager)
):
    """Assigns a team to a project."""
    logger.info(f"User '{current_user.email}' assigning team {assignment.team_id} to project {project_id}")
    try:
        success = manager.assign_team_to_project(
            db=db,
            project_id=project_id,
            team_id=assignment.team_id,
            assigned_by=current_user.email
        )
        db.commit()
        return {"message": "Team assigned to project successfully"}
    except NotFoundError as e:
        db.rollback()
        logger.error("Project team member not found %s: %s", project_id, e)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project or member not found")
    except ConflictError as e:
        db.rollback()
        logger.error("Project team member conflict %s: %s", project_id, e)
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Member conflict")
    except Exception as e:
        db.rollback()
        logger.exception(f"Failed to assign team to project: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to assign team: {e!s}")


@router.delete(
    "/projects/{project_id}/teams/{team_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(PermissionChecker(PROJECTS_FEATURE_ID, FeatureAccessLevel.READ_WRITE))]
)
def remove_team_from_project(
    project_id: str,
    team_id: str,
    db: DBSessionDep,
    current_user: CurrentUserDep,
    manager = Depends(get_projects_manager)
):
    """Removes a team from a project."""
    logger.info(f"User '{current_user.email}' removing team {team_id} from project {project_id}")
    try:
        success = manager.remove_team_from_project(db=db, project_id=project_id, team_id=team_id)
        if not success:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team assignment not found")
        db.commit()
        return None
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.exception(f"Failed to remove team from project: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to remove team: {e!s}")


@router.get(
    "/projects/{project_id}/teams",
    response_model=List[dict],
    dependencies=[Depends(PermissionChecker(PROJECTS_FEATURE_ID, FeatureAccessLevel.READ_ONLY))]
)
def get_project_teams(
    project_id: str,
    db: DBSessionDep,
    manager = Depends(get_projects_manager)
):
    """Gets all teams assigned to a project."""
    logger.debug(f"Fetching teams for project: {project_id}")
    try:
        return manager.get_project_teams(db=db, project_id=project_id)
    except NotFoundError as e:
        logger.error("Project team member not found for removal %s: %s", project_id, e)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project or member not found")
    except Exception as e:
        logger.exception(f"Failed to fetch project teams: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to fetch project teams")


# User Project Access Routes
@router.get(
    "/user/projects",
    response_model=UserProjectAccess
)
def get_user_projects(
    db: DBSessionDep,
    current_user: CurrentUserDep,
    manager = Depends(get_projects_manager)
):
    """Gets all projects that the current user has access to."""
    logger.debug(f"Fetching accessible projects for user: {current_user.email}")
    try:
        user_groups = current_user.groups or []
        return manager.get_user_projects(db=db, user_identifier=current_user.email, user_groups=user_groups)
    except Exception as e:
        logger.exception(f"Failed to fetch user projects: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to fetch user projects")


@router.post(
    "/user/current-project",
    status_code=status.HTTP_204_NO_CONTENT
)
def set_current_project(
    project_context: ProjectContext,
    db: DBSessionDep,
    current_user: CurrentUserDep,
    settings: Settings = Depends(get_settings),
    manager = Depends(get_projects_manager)
):
    """Sets the current project context for the user session."""
    logger.debug(f"Setting current project {project_context.project_id} for user: {current_user.email}")
    try:
        # Verify user has access to the project if project_id is provided
        if project_context.project_id:
            user_groups = current_user.groups or []
            
            # Admins can access any project
            if is_user_admin(user_groups, settings):
                logger.debug(f"User {current_user.email} is admin, allowing project switch")
            else:
                has_access = manager.check_user_project_access(
                    db=db,
                    user_identifier=current_user.email,
                    user_groups=user_groups,
                    project_id=project_context.project_id
                )
                if not has_access:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="User does not have access to this project"
                    )

        # TODO: Store project context in session or user preferences
        # For now, this is a placeholder - actual implementation would depend on session management
        logger.info(f"Project context set to {project_context.project_id} for user {current_user.email}")
        return None
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to set current project: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to set current project")


@router.post(
    "/user/request-project-access",
    response_model=ProjectAccessRequestResponse,
    status_code=status.HTTP_201_CREATED
)
async def request_project_access(
    http_request: Request,
    request: ProjectAccessRequest,
    background_tasks: BackgroundTasks,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    notifications_manager: NotificationsManagerDep,
    manager = Depends(get_projects_manager)
):
    """Request access to a project by sending notifications to project team members."""
    success = False
    details_for_audit = {
        "params": {"project_id": request.project_id, "requester": current_user.email},
    }

    logger.info(f"User '{current_user.email}' requesting access to project: {request.project_id}")
    try:
        user_groups = current_user.groups or []
        response = await manager.request_project_access(
            db=db,
            user_identifier=current_user.email,
            user_groups=user_groups,
            request=request,
            notifications_manager=notifications_manager
        )
        db.commit()
        success = True
        return response
    except NotFoundError as e:
        db.rollback()
        logger.error("Project not found for access request %s: %s", project_id, e)
        details_for_audit["exception"] = {"type": "NotFoundError", "message": str(e)}
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    except ConflictError as e:
        db.rollback()
        logger.error("Project access request conflict %s: %s", project_id, e)
        details_for_audit["exception"] = {"type": "ConflictError", "message": str(e)}
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Access request conflict")
    except Exception as e:
        db.rollback()
        logger.exception("Failed to request project access for %s", project_id)
        details_for_audit["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to request project access: {e!s}")
    finally:
        background_tasks.add_task(
            audit_manager.log_action_background,
            username=current_user.username,
            ip_address=http_request.client.host if http_request.client else None,
            feature=PROJECTS_FEATURE_ID,
            action="REQUEST_ACCESS",
            success=success,
            details=details_for_audit.copy()
        )


def register_routes(app):
    app.include_router(router)
    logger.info("Projects routes registered with prefix /api/projects")