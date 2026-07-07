from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status, Query, Request, BackgroundTasks

from src.models.teams import (
    TeamCreate,
    TeamUpdate,
    TeamRead,
    TeamSummary,
    TeamMemberCreate,
    TeamMemberUpdate,
    TeamMemberRead
)
from src.controller.teams_manager import teams_manager
from src.common.database import get_db
from sqlalchemy.orm import Session
from src.common.authorization import PermissionChecker
from src.common.features import FeatureAccessLevel
from src.common.dependencies import (
    DBSessionDep,
    CurrentUserDep,
    AuditManagerDep,
    AuditCurrentUserDep
)
from src.models.users import UserInfo
from src.common.errors import NotFoundError, ConflictError

from src.common.logging import get_logger
logger = get_logger(__name__)

# Define router
router = APIRouter(prefix="/api", tags=["Teams"])

# Feature ID constant
TEAMS_FEATURE_ID = "teams"

# Team dependency
def get_teams_manager():
    return teams_manager


# Team Routes
@router.post(
    "/teams",
    response_model=TeamRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(PermissionChecker(TEAMS_FEATURE_ID, FeatureAccessLevel.READ_WRITE))]
)
def create_team(
    request: Request,
    team_in: TeamCreate,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager = Depends(get_teams_manager)
):
    """Creates a new team."""
    success = False
    details_for_audit = {
        "params": {"team_name": team_in.name, "domain_ids": team_in.domain_ids},
    }
    created_team_id = None

    logger.info(f"User '{current_user.email}' attempting to create team: {team_in.name}")
    try:
        created_team = manager.create_team(db=db, team_in=team_in, current_user_id=current_user.email)
        db.commit()
        success = True
        created_team_id = str(created_team.id)
        return created_team
    except ConflictError as e:
        db.rollback()
        logger.error("Team creation conflict for '%s': %s", team_in.name, e)
        details_for_audit["exception"] = {"type": "ConflictError", "message": str(e)}
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Team already exists")
    except Exception as e:
        db.rollback()
        logger.exception("Failed to create team '%s'", team_in.name)
        details_for_audit["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create team")
    finally:
        if created_team_id:
            details_for_audit["created_resource_id"] = created_team_id
        audit_manager.log_action(
            db=db,
            username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=TEAMS_FEATURE_ID,
            action="CREATE",
            success=success,
            details=details_for_audit
        )


@router.get(
    "/teams",
    response_model=List[TeamRead],
    dependencies=[Depends(PermissionChecker(TEAMS_FEATURE_ID, FeatureAccessLevel.READ_ONLY))]
)
def get_all_teams(
    db: DBSessionDep,
    manager = Depends(get_teams_manager),
    skip: int = 0,
    limit: int = 100,
    domain_id: Optional[str] = Query(None, description="Filter teams by a single domain ID (any-of)"),
    domain_ids: Optional[str] = Query(None, description="Filter teams by multiple domain IDs, comma-separated (any-of)")
):
    """Lists all teams, optionally filtered by domain(s) (any-of)."""
    logger.debug(f"Fetching teams (skip={skip}, limit={limit}, domain_id={domain_id}, domain_ids={domain_ids})")
    try:
        domain_id_list = [d for d in (domain_ids.split(",") if domain_ids else []) if d.strip()]
        return manager.get_all_teams(
            db=db, skip=skip, limit=limit, domain_id=domain_id, domain_ids=domain_id_list or None
        )
    except Exception as e:
        logger.exception(f"Failed to fetch teams: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to fetch teams")


@router.get(
    "/teams/summary",
    response_model=List[TeamSummary],
    dependencies=[Depends(PermissionChecker(TEAMS_FEATURE_ID, FeatureAccessLevel.READ_ONLY))]
)
def get_teams_summary(
    db: DBSessionDep,
    manager = Depends(get_teams_manager),
    domain_id: Optional[str] = Query(None, description="Filter teams by a single domain ID (any-of)"),
    domain_ids: Optional[str] = Query(None, description="Filter teams by multiple domain IDs, comma-separated (any-of)")
):
    """Gets a summary list of teams for dropdowns/selection."""
    logger.debug(f"Fetching teams summary for domain_id={domain_id}, domain_ids={domain_ids}")
    try:
        domain_id_list = [d for d in (domain_ids.split(",") if domain_ids else []) if d.strip()]
        return manager.get_teams_summary(db=db, domain_id=domain_id, domain_ids=domain_id_list or None)
    except Exception as e:
        logger.exception(f"Failed to fetch teams summary: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to fetch teams summary")


@router.get(
    "/teams/{team_id}",
    response_model=TeamRead,
    dependencies=[Depends(PermissionChecker(TEAMS_FEATURE_ID, FeatureAccessLevel.READ_ONLY))]
)
def get_team(
    team_id: str,
    db: DBSessionDep,
    manager = Depends(get_teams_manager)
):
    """Gets a specific team by its ID."""
    logger.debug(f"Fetching team with id: {team_id}")
    team = manager.get_team_by_id(db=db, team_id=team_id)
    if not team:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Team with id '{team_id}' not found")
    return team


@router.get(
    "/user/teams",
    response_model=List[TeamRead]
)
def get_user_teams(
    db: DBSessionDep,
    current_user: CurrentUserDep,
    manager = Depends(get_teams_manager)
):
    """Gets all teams that the current user is a member of."""
    logger.debug(f"Fetching teams for user: {current_user.email}")
    try:
        user_groups = current_user.groups or []
        return manager.get_teams_for_user(
            db=db, 
            user_identifier=current_user.email,
            user_groups=user_groups
        )
    except Exception as e:
        logger.exception(f"Failed to fetch user teams: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to fetch user teams")


@router.put(
    "/teams/{team_id}",
    response_model=TeamRead,
    dependencies=[Depends(PermissionChecker(TEAMS_FEATURE_ID, FeatureAccessLevel.READ_WRITE))]
)
def update_team(
    team_id: str,
    request: Request,
    team_in: TeamUpdate,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager = Depends(get_teams_manager)
):
    """Updates an existing team."""
    success = False
    details_for_audit = {
        "params": {"team_id": team_id},
    }

    logger.info(f"User '{current_user.email}' attempting to update team: {team_id}")
    try:
        updated_team = manager.update_team(
            db=db,
            team_id=team_id,
            team_in=team_in,
            current_user_id=current_user.email
        )
        db.commit()
        success = True
        return updated_team
    except NotFoundError as e:
        db.rollback()
        logger.error("Team not found for update %s: %s", team_id, e)
        details_for_audit["exception"] = {"type": "NotFoundError", "message": str(e)}
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")
    except ConflictError as e:
        db.rollback()
        logger.error("Team update conflict %s: %s", team_id, e)
        details_for_audit["exception"] = {"type": "ConflictError", "message": str(e)}
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Team conflict")
    except Exception as e:
        db.rollback()
        logger.exception("Failed to update team %s", team_id)
        details_for_audit["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to update team")
    finally:
        if success:
            details_for_audit["updated_resource_id"] = team_id
        audit_manager.log_action(
            db=db,
            username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=TEAMS_FEATURE_ID,
            action="UPDATE",
            success=success,
            details=details_for_audit
        )


@router.delete(
    "/teams/{team_id}",
    response_model=TeamRead,
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(PermissionChecker(TEAMS_FEATURE_ID, FeatureAccessLevel.ADMIN))]
)
def delete_team(
    team_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager = Depends(get_teams_manager)
):
    """Deletes a team. Requires Admin privileges."""
    success = False
    details_for_audit = {
        "params": {"team_id": team_id},
    }

    logger.info(f"User '{current_user.email}' attempting to delete team: {team_id}")
    try:
        deleted_team = manager.delete_team(db=db, team_id=team_id)
        db.commit()
        success = True
        return deleted_team
    except NotFoundError as e:
        db.rollback()
        logger.error("Team not found for deletion %s: %s", team_id, e)
        details_for_audit["exception"] = {"type": "NotFoundError", "message": str(e)}
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")
    except Exception as e:
        db.rollback()
        logger.exception("Failed to delete team %s", team_id)
        details_for_audit["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to delete team")
    finally:
        if success:
            details_for_audit["deleted_resource_id"] = team_id
        audit_manager.log_action(
            db=db,
            username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=TEAMS_FEATURE_ID,
            action="DELETE",
            success=success,
            details=details_for_audit
        )


# Team Member Routes
@router.post(
    "/teams/{team_id}/members",
    response_model=TeamMemberRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(PermissionChecker(TEAMS_FEATURE_ID, FeatureAccessLevel.READ_WRITE))]
)
def add_team_member(
    team_id: str,
    request: Request,
    member_in: TeamMemberCreate,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager = Depends(get_teams_manager)
):
    """Adds a member to a team."""
    success = False
    details_for_audit = {
        "params": {"team_id": team_id, "member_identifier": member_in.member_identifier},
    }
    created_member_id = None

    logger.info(f"User '{current_user.email}' adding member {member_in.member_identifier} to team {team_id}")
    try:
        member = manager.add_team_member(
            db=db,
            team_id=team_id,
            member_in=member_in,
            current_user_id=current_user.email
        )
        db.commit()
        success = True
        created_member_id = str(member.id) if hasattr(member, 'id') else None
        return member
    except NotFoundError as e:
        db.rollback()
        logger.error("Team not found for adding member %s: %s", team_id, e)
        details_for_audit["exception"] = {"type": "NotFoundError", "message": str(e)}
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")
    except ConflictError as e:
        db.rollback()
        logger.error("Member already exists in team %s: %s", team_id, e)
        details_for_audit["exception"] = {"type": "ConflictError", "message": str(e)}
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Member already exists in team")
    except Exception as e:
        db.rollback()
        logger.exception("Failed to add member to team %s", team_id)
        details_for_audit["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to add team member")
    finally:
        if created_member_id:
            details_for_audit["created_resource_id"] = created_member_id
        audit_manager.log_action(
            db=db,
            username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=TEAMS_FEATURE_ID,
            action="ADD_MEMBER",
            success=success,
            details=details_for_audit
        )


@router.get(
    "/teams/{team_id}/members",
    response_model=List[TeamMemberRead],
    dependencies=[Depends(PermissionChecker(TEAMS_FEATURE_ID, FeatureAccessLevel.READ_ONLY))]
)
def get_team_members(
    team_id: str,
    db: DBSessionDep,
    manager = Depends(get_teams_manager)
):
    """Gets all members of a team."""
    logger.debug(f"Fetching members for team: {team_id}")
    try:
        return manager.get_team_members(db=db, team_id=team_id)
    except Exception as e:
        logger.exception(f"Failed to fetch team members: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to fetch team members")


@router.put(
    "/teams/{team_id}/members/{member_id}",
    response_model=TeamMemberRead,
    dependencies=[Depends(PermissionChecker(TEAMS_FEATURE_ID, FeatureAccessLevel.READ_WRITE))]
)
def update_team_member(
    team_id: str,
    member_id: str,
    request: Request,
    member_in: TeamMemberUpdate,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager = Depends(get_teams_manager)
):
    """Updates a team member."""
    success = False
    details_for_audit = {
        "params": {"team_id": team_id, "member_id": member_id},
    }

    logger.info(f"User '{current_user.email}' updating team member {member_id} in team {team_id}")
    try:
        updated_member = manager.update_team_member(
            db=db,
            team_id=team_id,
            member_id=member_id,
            member_in=member_in,
            current_user_id=current_user.email
        )
        db.commit()
        success = True
        return updated_member
    except NotFoundError as e:
        db.rollback()
        logger.error("Team or member not found for update %s/%s: %s", team_id, member_id, e)
        details_for_audit["exception"] = {"type": "NotFoundError", "message": str(e)}
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team or member not found")
    except Exception as e:
        db.rollback()
        logger.exception("Failed to update team member %s/%s", team_id, member_id)
        details_for_audit["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to update team member")
    finally:
        if success:
            details_for_audit["updated_resource_id"] = member_id
        audit_manager.log_action(
            db=db,
            username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=TEAMS_FEATURE_ID,
            action="UPDATE_MEMBER",
            success=success,
            details=details_for_audit
        )


@router.delete(
    "/teams/{team_id}/members/{member_identifier}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(PermissionChecker(TEAMS_FEATURE_ID, FeatureAccessLevel.READ_WRITE))]
)
def remove_team_member(
    team_id: str,
    member_identifier: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager = Depends(get_teams_manager)
):
    """Removes a member from a team."""
    success = False
    details_for_audit = {
        "params": {"team_id": team_id, "member_identifier": member_identifier},
    }

    logger.info(f"User '{current_user.email}' removing member {member_identifier} from team {team_id}")
    try:
        removed = manager.remove_team_member(db=db, team_id=team_id, member_identifier=member_identifier)
        if not removed:
            details_for_audit["exception"] = {"type": "NotFoundError", "message": f"Member '{member_identifier}' not found in team"}
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Member '{member_identifier}' not found in team")
        db.commit()
        success = True
        return None
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.exception(f"Failed to remove team member: {e}")
        details_for_audit["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to remove team member: {e!s}")
    finally:
        if success:
            details_for_audit["deleted_resource_id"] = member_identifier
        audit_manager.log_action(
            db=db,
            username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=TEAMS_FEATURE_ID,
            action="REMOVE_MEMBER",
            success=success,
            details=details_for_audit
        )


# Domain-specific routes
@router.get(
    "/domains/{domain_id}/teams",
    response_model=List[TeamRead],
    dependencies=[Depends(PermissionChecker(TEAMS_FEATURE_ID, FeatureAccessLevel.READ_ONLY))]
)
def get_teams_by_domain(
    domain_id: str,
    db: DBSessionDep,
    manager = Depends(get_teams_manager)
):
    """Gets all teams belonging to a specific domain."""
    logger.debug(f"Fetching teams for domain: {domain_id}")
    try:
        return manager.get_teams_by_domain(db=db, domain_id=domain_id)
    except Exception as e:
        logger.exception(f"Failed to fetch teams for domain: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to fetch teams for domain")


@router.get(
    "/teams/standalone",
    response_model=List[TeamRead],
    dependencies=[Depends(PermissionChecker(TEAMS_FEATURE_ID, FeatureAccessLevel.READ_ONLY))]
)
def get_standalone_teams(
    db: DBSessionDep,
    manager = Depends(get_teams_manager)
):
    """Gets all standalone teams (not assigned to a domain)."""
    logger.debug("Fetching standalone teams")
    try:
        return manager.get_standalone_teams(db=db)
    except Exception as e:
        logger.exception(f"Failed to fetch standalone teams: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to fetch standalone teams")


def register_routes(app):
    app.include_router(router)
    logger.info("Teams routes registered with prefix /api/teams")