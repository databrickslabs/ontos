from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status, Query, Request, BackgroundTasks

from src.models.teams import (
    TeamCreate,
    TeamUpdate,
    TeamRead,
    TeamSummary,
    TeamMemberCreate,
    TeamMemberUpdate,
    TeamMemberRead,
    TeamMembersReplace,
)
from src.controller.teams_manager import InvalidMemberSetError, TeamsManager, teams_manager
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

# Team dependency — resolve from app.state so index-upsert/remove hooks fire.
# Startup builds the TeamsManager instance that `set_search_manager(...)` wires
# up (``app.state.teams_manager``). The module-level ``teams_manager`` singleton
# is a separate instance whose ``_search_manager`` stays None, so a route that
# reaches it would silently skip the search index notification. Falls back to
# the singleton for the handful of unit tests that call the getter without a
# request context.
def get_teams_manager(request: Request = None) -> TeamsManager:
    if request is not None:
        state_mgr = getattr(request.app.state, "teams_manager", None)
        if isinstance(state_mgr, TeamsManager):
            return state_mgr
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


# Before /teams/{team_id}, which would otherwise take "standalone" as a team id.
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
        _ensure_keeps_team_access(request, db, manager, team_id, [], current_user, details_for_audit)
        deleted_team = manager.delete_team(db=db, team_id=team_id)
        db.commit()
        success = True
        return deleted_team
    except HTTPException:
        db.rollback()
        raise
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


SELF_LOCKOUT_DETAIL = (
    "This change would remove your own permission to manage teams. "
    "Keep your own membership or role, or ask another administrator."
)
INVALID_MEMBER_SET_DETAIL = "Each member needs an identifier and may be listed only once."


def _would_lose_team_write_access(
    request: Request,
    db: Session,
    manager: TeamsManager,
    team_id: str,
    members_after: List[TeamMemberCreate],
    current_user: UserInfo,
) -> bool:
    """True if ``team_id`` having ``members_after`` would leave the caller unable to manage teams."""
    auth_manager = getattr(request.app.state, "authorization_manager", None)
    if auth_manager is None:
        return False

    settings_manager = getattr(request.app.state, "settings_manager", None)
    if settings_manager is not None:
        try:
            if settings_manager.get_applied_role_override_for_user(current_user.email):
                # An applied role override wins over team overrides, so team edits can't remove it.
                return False
        except Exception:
            logger.debug("Could not read applied role override for %s", current_user.email, exc_info=True)

    groups = current_user.groups or []
    override_after = manager.team_role_override_with_members(
        db=db, team_id=team_id, members=members_after,
        user_identifier=current_user.email, user_groups=groups,
    )
    permissions_after = auth_manager.get_user_effective_permissions(
        groups, override_after, user_email=current_user.email
    )
    return not auth_manager.has_permission(
        permissions_after, TEAMS_FEATURE_ID, FeatureAccessLevel.READ_WRITE
    )


def _ensure_keeps_team_access(
    request: Request,
    db: Session,
    manager: TeamsManager,
    team_id: str,
    members_after: List[TeamMemberCreate],
    current_user: UserInfo,
    details_for_audit: dict,
) -> None:
    if _would_lose_team_write_access(request, db, manager, team_id, members_after, current_user):
        details_for_audit["exception"] = {
            "type": "SelfLockout", "message": "Change would remove the caller's own team access",
        }
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=SELF_LOCKOUT_DETAIL)


@router.put(
    "/teams/{team_id}/members",
    response_model=List[TeamMemberRead],
    dependencies=[Depends(PermissionChecker(TEAMS_FEATURE_ID, FeatureAccessLevel.READ_WRITE))]
)
def replace_team_members(
    team_id: str,
    request: Request,
    body: TeamMembersReplace,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager = Depends(get_teams_manager)
):
    """Replaces a team's member set in one transaction (adds, removes and updates only what changed)."""
    success = False
    details_for_audit = {
        "params": {
            "team_id": team_id,
            "member_identifiers": [m.member_identifier for m in body.members],
        },
    }

    logger.info(
        "User %s replacing members of team %s (%d members)",
        current_user.email, team_id, len(body.members),
    )
    try:
        members_after = manager.validate_member_set(body.members)
        _ensure_keeps_team_access(
            request, db, manager, team_id, members_after, current_user, details_for_audit
        )
        members = manager.replace_team_members(
            db=db, team_id=team_id, members_in=members_after, current_user_id=current_user.email
        )
        db.commit()
        success = True
        return members
    except HTTPException:
        db.rollback()
        raise
    except NotFoundError as e:
        db.rollback()
        logger.error("Team not found for replacing members %s: %s", team_id, e)
        details_for_audit["exception"] = {"type": "NotFoundError", "message": str(e)}
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")
    except InvalidMemberSetError as e:
        db.rollback()
        details_for_audit["exception"] = {"type": "InvalidMemberSetError", "message": str(e)}
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=INVALID_MEMBER_SET_DETAIL)
    except Exception as e:
        db.rollback()
        logger.exception("Failed to replace members of team %s", team_id)
        details_for_audit["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to update team members")
    finally:
        audit_manager.log_action(
            db=db,
            username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=TEAMS_FEATURE_ID,
            action="REPLACE_MEMBERS",
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
        target = manager.team_member_repo.get(db, member_id)
        if target is not None and target.team_id == team_id and "app_role_override" in member_in.model_fields_set:
            members_after = [
                m.model_copy(update={"app_role_override": member_in.app_role_override})
                if m.member_identifier == target.member_identifier else m
                for m in manager.current_member_set(db, team_id)
            ]
            _ensure_keeps_team_access(
                request, db, manager, team_id, members_after, current_user, details_for_audit
            )
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
    except HTTPException:
        db.rollback()
        raise
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
        members_after = [
            m for m in manager.current_member_set(db, team_id)
            if m.member_identifier != member_identifier
        ]
        _ensure_keeps_team_access(
            request, db, manager, team_id, members_after, current_user, details_for_audit
        )
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
        logger.exception("Failed to remove team member %s from team %s", member_identifier, team_id)
        details_for_audit["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to remove team member")
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


def register_routes(app):
    app.include_router(router)
    logger.info("Teams routes registered with prefix /api/teams")