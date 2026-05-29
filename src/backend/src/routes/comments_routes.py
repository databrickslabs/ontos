from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from sqlalchemy.orm import Session

from src.common.dependencies import DBSessionDep, CurrentUserDep, AuditManagerDep, AuditCurrentUserDep
from src.common.features import FeatureAccessLevel
from src.common.authorization import PermissionChecker, get_user_groups, is_user_admin, get_user_team_role_overrides
from src.common.config import get_settings, Settings
from src.controller.comments_manager import CommentsManager
from src.controller.change_log_manager import change_log_manager
from src.common.manager_dependencies import get_comments_manager, get_settings_manager
from src.models.comments import Comment, CommentCreate, CommentUpdate, CommentListResponse, RatingCreate, RatingAggregation
from src.repositories.teams_repository import team_repo

from src.common.logging import get_logger
logger = get_logger(__name__)

router = APIRouter(prefix="/api", tags=["Comments"])

# Comments feature - cross-cutting feature for social interaction
# All users get READ_WRITE by default, Admin role gets ADMIN to manage all comments
FEATURE_ID = "comments"


@router.post("/entities/{entity_type}/{entity_id}/comments", response_model=Comment, status_code=status.HTTP_201_CREATED)
async def create_comment(
    entity_type: str,
    entity_id: str,
    payload: CommentCreate,
    request: Request,
    db: DBSessionDep,
    current_user: CurrentUserDep,
    audit_manager: AuditManagerDep,
    audit_user: AuditCurrentUserDep,
    manager: CommentsManager = Depends(get_comments_manager),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    """Create a comment on an entity."""
    success = False
    details = {
        "params": {
            "entity_type": entity_type,
            "entity_id": entity_id,
            "title": payload.title,
            "audience": payload.audience,
            "project_id": payload.project_id
        }
    }

    try:
        # Validate that path matches payload
        if payload.entity_type != entity_type or payload.entity_id != entity_id:
            raise HTTPException(
                status_code=400,
                detail="Entity path does not match request body"
            )

        # Get user's groups and check admin status
        user_groups = await get_user_groups(current_user.email, request)
        is_admin = is_user_admin(user_groups, get_settings())
        
        # Get user's teams (for validation if needed)
        user_teams = team_repo.get_teams_for_user(db, current_user.email, user_groups)
        user_team_ids = [team.id for team in user_teams]

        result = manager.create_comment(
            db, 
            data=payload, 
            user_email=current_user.email,
            user_teams=user_team_ids,
            is_admin=is_admin
        )
        success = True
        details["comment_id"] = result.id
        return result
    except ValueError as e:
        details["exception"] = {"type": "ValueError", "message": str(e)}
        raise HTTPException(status_code=403, detail=str(e))
    except HTTPException as e:
        details["exception"] = {"type": "HTTPException", "status_code": e.status_code, "detail": e.detail}
        raise
    except Exception as e:
        logger.exception("Failed creating comment for %s/%s", entity_type, entity_id)
        details["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise HTTPException(status_code=500, detail="Failed to create comment")
    finally:
        audit_manager.log_action(
            db=db,
            username=audit_user.username,
            ip_address=request.client.host if request.client else None,
            feature="comments",
            action="CREATE",
            success=success,
            details=details
        )


@router.get("/entities/{entity_type}/{entity_id}/comments", response_model=CommentListResponse)
async def list_comments(
    entity_type: str,
    entity_id: str,
    request: Request,
    db: DBSessionDep,
    current_user: CurrentUserDep,
    project_id: Optional[str] = Query(None, description="Filter by project context"),
    include_deleted: bool = Query(False, description="Include soft-deleted comments (admin only)"),
    manager: CommentsManager = Depends(get_comments_manager),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY)),
):
    """List comments for an entity, filtered by project context and user's visibility permissions."""
    try:
        # Get user's groups for audience filtering
        user_groups = await get_user_groups(current_user.email, request)

        # Get user's teams for team-based audience filtering
        user_teams = team_repo.get_teams_for_user(db, current_user.email, user_groups)
        user_team_ids = [team.id for team in user_teams]

        # Legacy team-override role name (kept for backward-compat with role:<name> tokens)
        user_app_role = await get_user_team_role_overrides(current_user.email, user_groups, request=request)

        # Applied role-ID override (role-switcher / impersonation) — used for the
        # group-derived role resolution path introduced in issue #326.
        applied_role_override_id: Optional[str] = None
        try:
            settings_mgr = get_settings_manager(request)
            applied_role_override_id = settings_mgr.get_applied_role_override_for_user(
                current_user.email
            )
        except Exception:
            logger.debug("list_comments: could not fetch applied role override; proceeding without it")

        # Only admins can see deleted comments
        if include_deleted:
            is_admin = is_user_admin(user_groups, get_settings())
            if not is_admin:
                include_deleted = False

        return manager.list_comments(
            db,
            entity_type=entity_type,
            entity_id=entity_id,
            project_id=project_id,
            user_groups=user_groups,
            user_teams=user_team_ids,
            user_app_role=user_app_role,
            user_email=current_user.email,
            applied_role_override_id=applied_role_override_id,
            include_deleted=include_deleted
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed listing comments for %s/%s", entity_type, entity_id)
        raise HTTPException(status_code=500, detail="Failed to list comments")


@router.get("/entities/{entity_type}/{entity_id}/timeline/count")
async def get_entity_timeline_count(
    entity_type: str,
    entity_id: str,
    request: Request,
    db: DBSessionDep,
    current_user: CurrentUserDep,
    project_id: Optional[str] = Query(None, description="Filter by project context"),
    include_deleted: bool = Query(False, description="Include soft-deleted comments (admin only)"),
    filter_type: str = Query("all", description="Filter type: 'all', 'comments', 'changes'"),
    manager: CommentsManager = Depends(get_comments_manager),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY)),
):
    """Get count of timeline entries for an entity without fetching full data."""
    try:
        total_count = 0

        # Get user's groups for audience filtering
        user_groups = await get_user_groups(current_user.email, request)
        is_admin = is_user_admin(user_groups, get_settings())

        # Get user's teams and app role
        user_teams = team_repo.get_teams_for_user(db, current_user.email, user_groups)
        user_team_ids = [team.id for team in user_teams]
        user_app_role = await get_user_team_role_overrides(current_user.email, user_groups, request=request)

        applied_role_override_id: Optional[str] = None
        try:
            settings_mgr = get_settings_manager(request)
            applied_role_override_id = settings_mgr.get_applied_role_override_for_user(
                current_user.email
            )
        except Exception:
            logger.debug("get_entity_timeline_count: could not fetch applied role override")

        if filter_type in ("all", "comments"):
            # Get comments count
            if include_deleted and not is_admin:
                include_deleted = False

            comments_response = manager.list_comments(
                db,
                entity_type=entity_type,
                entity_id=entity_id,
                project_id=project_id,
                user_groups=user_groups,
                user_teams=user_team_ids,
                user_app_role=user_app_role,
                user_email=current_user.email,
                applied_role_override_id=applied_role_override_id,
                include_deleted=include_deleted
            )
            total_count += len(comments_response.comments)

        if filter_type in ("all", "changes"):
            # Get change log entries count
            change_entries = change_log_manager.list_changes_for_entity(
                db,
                entity_type=entity_type,
                entity_id=entity_id,
                limit=10000  # High limit to get actual count
            )
            total_count += len(change_entries)

        return {
            "total_count": total_count,
            "filter_type": filter_type
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed getting entity timeline count for %s/%s", entity_type, entity_id)
        raise HTTPException(status_code=500, detail="Failed to get timeline count")


@router.get("/entities/{entity_type}/{entity_id}/timeline")
async def get_entity_timeline(
    entity_type: str,
    entity_id: str,
    request: Request,
    db: DBSessionDep,
    current_user: CurrentUserDep,
    project_id: Optional[str] = Query(None, description="Filter by project context"),
    include_deleted: bool = Query(False, description="Include soft-deleted comments (admin only)"),
    filter_type: str = Query("all", description="Filter type: 'all', 'comments', 'changes'"),
    limit: int = Query(100, ge=1, le=1000, description="Max number of entries"),
    manager: CommentsManager = Depends(get_comments_manager),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY)),
):
    """Get a unified timeline of comments and change log entries for an entity."""
    try:
        timeline_entries = []

        # Get user's groups for audience filtering
        user_groups = await get_user_groups(current_user.email, request)
        is_admin = is_user_admin(user_groups, get_settings())

        # Get user's teams and app role
        user_teams = team_repo.get_teams_for_user(db, current_user.email, user_groups)
        user_team_ids = [team.id for team in user_teams]
        user_app_role = await get_user_team_role_overrides(current_user.email, user_groups, request=request)

        applied_role_override_id: Optional[str] = None
        try:
            settings_mgr = get_settings_manager(request)
            applied_role_override_id = settings_mgr.get_applied_role_override_for_user(
                current_user.email
            )
        except Exception:
            logger.debug("get_entity_timeline: could not fetch applied role override")

        if filter_type in ("all", "comments"):
            # Get comments
            if include_deleted and not is_admin:
                include_deleted = False

            comments_response = manager.list_comments(
                db,
                entity_type=entity_type,
                entity_id=entity_id,
                project_id=project_id,
                user_groups=user_groups,
                user_teams=user_team_ids,
                user_app_role=user_app_role,
                user_email=current_user.email,
                applied_role_override_id=applied_role_override_id,
                include_deleted=include_deleted
            )
            
            # Convert comments to timeline format
            for comment in comments_response.comments:
                timeline_entries.append({
                    "id": comment.id,
                    "type": "comment",
                    "entity_type": entity_type,
                    "entity_id": entity_id,
                    "title": comment.title,
                    "content": comment.comment,
                    "username": comment.created_by,
                    "timestamp": comment.created_at.isoformat(),
                    "updated_at": comment.updated_at.isoformat() if comment.updated_at != comment.created_at else None,
                    "audience": comment.audience,
                    "status": comment.status,
                    "metadata": {
                        "updated_by": comment.updated_by if comment.updated_by != comment.created_by else None
                    }
                })
        
        if filter_type in ("all", "changes"):
            # Get change log entries
            change_entries = change_log_manager.list_changes_for_entity(
                db,
                entity_type=entity_type,
                entity_id=entity_id,
                limit=limit
            )
            
            # Convert change log entries to timeline format
            for change in change_entries:
                timeline_entries.append({
                    "id": change.id,
                    "type": "change",
                    "entity_type": change.entity_type,
                    "entity_id": change.entity_id,
                    "title": f"{change.action.replace('_', ' ').title()}",
                    "content": change.details_json or f"{change.action} performed on {change.entity_type}",
                    "username": change.username,
                    "timestamp": change.timestamp.isoformat(),
                    "updated_at": None,
                    "audience": None,
                    "status": None,
                    "metadata": {
                        "action": change.action
                    }
                })
        
        # Sort by timestamp (newest first)
        timeline_entries.sort(key=lambda x: x["timestamp"], reverse=True)

        # Calculate total count before applying limit
        total_count = len(timeline_entries)

        # Apply limit
        if len(timeline_entries) > limit:
            timeline_entries = timeline_entries[:limit]

        return {
            "timeline": timeline_entries,
            "total_count": total_count,
            "filter_type": filter_type
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed getting entity timeline for %s/%s", entity_type, entity_id)
        raise HTTPException(status_code=500, detail="Failed to get timeline")


@router.get("/comments/{comment_id}", response_model=Comment)
async def get_comment(
    comment_id: str,
    db: DBSessionDep,
    manager: CommentsManager = Depends(get_comments_manager),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY)),
):
    """Get a single comment by ID."""
    comment = manager.get_comment(db, comment_id=comment_id)
    if not comment:
        raise HTTPException(status_code=404, detail="Comment not found")
    return comment


@router.put("/comments/{comment_id}", response_model=Comment)
async def update_comment(
    comment_id: str,
    payload: CommentUpdate,
    request: Request,
    db: DBSessionDep,
    current_user: CurrentUserDep,
    audit_manager: AuditManagerDep,
    audit_user: AuditCurrentUserDep,
    manager: CommentsManager = Depends(get_comments_manager),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    """Update a comment. Only the comment author or admins can update."""
    success = False
    details = {
        "params": {
            "comment_id": comment_id,
            "updates": payload.dict(exclude_unset=True)
        }
    }

    try:
        # Get user's groups to check for admin status
        user_groups = await get_user_groups(current_user.email, request)
        is_admin = is_user_admin(user_groups, get_settings())

        updated = manager.update_comment(
            db,
            comment_id=comment_id,
            data=payload,
            user_email=current_user.email,
            is_admin=is_admin
        )

        if not updated:
            raise HTTPException(
                status_code=404,
                detail="Comment not found or you don't have permission to update it"
            )

        success = True
        return updated
    except HTTPException as e:
        details["exception"] = {"type": "HTTPException", "status_code": e.status_code, "detail": e.detail}
        raise
    except Exception as e:
        logger.exception("Failed updating comment %s", comment_id)
        details["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise HTTPException(status_code=500, detail="Failed to update comment")
    finally:
        audit_manager.log_action(
            db=db,
            username=audit_user.username,
            ip_address=request.client.host if request.client else None,
            feature="comments",
            action="UPDATE",
            success=success,
            details=details
        )


@router.delete("/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_comment(
    comment_id: str,
    request: Request,
    db: DBSessionDep,
    current_user: CurrentUserDep,
    audit_manager: AuditManagerDep,
    audit_user: AuditCurrentUserDep,
    hard_delete: bool = Query(False, description="Permanently delete comment (admin only)"),
    manager: CommentsManager = Depends(get_comments_manager),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    """Delete a comment. Only the comment author or admins can delete."""
    success_flag = False
    details = {
        "params": {
            "comment_id": comment_id,
            "hard_delete": hard_delete
        }
    }

    try:
        # Get user's groups to check for admin status
        user_groups = await get_user_groups(current_user.email, request)
        is_admin = is_user_admin(user_groups, get_settings())

        # Only admins can hard delete
        if hard_delete and not is_admin:
            hard_delete = False
            details["params"]["hard_delete"] = False
            details["note"] = "Hard delete denied - not admin"

        success = manager.delete_comment(
            db,
            comment_id=comment_id,
            user_email=current_user.email,
            is_admin=is_admin,
            hard_delete=hard_delete
        )

        if not success:
            raise HTTPException(
                status_code=404,
                detail="Comment not found or you don't have permission to delete it"
            )

        success_flag = True
        return  # 204 No Content
    except HTTPException as e:
        details["exception"] = {"type": "HTTPException", "status_code": e.status_code, "detail": e.detail}
        raise
    except Exception as e:
        logger.exception("Failed deleting comment %s", comment_id)
        details["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise HTTPException(status_code=500, detail="Failed to delete comment")
    finally:
        audit_manager.log_action(
            db=db,
            username=audit_user.username,
            ip_address=request.client.host if request.client else None,
            feature="comments",
            action="DELETE",
            success=success_flag,
            details=details
        )


@router.get("/comments/{comment_id}/permissions")
async def check_comment_permissions(
    comment_id: str,
    db: DBSessionDep,
    current_user: CurrentUserDep,
    manager: CommentsManager = Depends(get_comments_manager),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY)),
):
    """Check if current user can modify a specific comment."""
    try:
        # Get user's groups to check for admin status
        user_groups = await get_user_groups(current_user.email, request)
        is_admin = is_user_admin(user_groups, get_settings())
        
        can_modify = manager.can_user_modify_comment(
            db,
            comment_id=comment_id,
            user_email=current_user.email,
            is_admin=is_admin
        )
        
        return {
            "can_modify": can_modify,
            "is_admin": is_admin
        }
    except Exception as e:
        logger.exception("Failed checking comment permissions for %s", comment_id)
        raise HTTPException(status_code=500, detail="Failed to check comment permissions")


# =============================================================================
# Rating Endpoints
# =============================================================================

@router.post("/entities/{entity_type}/{entity_id}/ratings", response_model=Comment, status_code=status.HTTP_201_CREATED)
async def create_rating(
    entity_type: str,
    entity_id: str,
    payload: RatingCreate,
    request: Request,
    db: DBSessionDep,
    current_user: CurrentUserDep,
    audit_manager: AuditManagerDep,
    audit_user: AuditCurrentUserDep,
    manager: CommentsManager = Depends(get_comments_manager),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    """Create a star rating for an entity.
    
    Each user can submit multiple ratings over time. The latest rating
    is considered the user's "current" rating for aggregation purposes.
    """
    success = False
    details = {
        "params": {
            "entity_type": entity_type,
            "entity_id": entity_id,
            "rating": payload.rating,
        }
    }

    try:
        # Validate that path matches payload
        if payload.entity_type != entity_type or payload.entity_id != entity_id:
            raise HTTPException(
                status_code=400,
                detail="Entity path does not match request body"
            )

        result = manager.create_rating(
            db,
            entity_type=entity_type,
            entity_id=entity_id,
            rating=payload.rating,
            comment=payload.comment,
            project_id=payload.project_id,
            user_email=current_user.email
        )
        success = True
        details["rating_id"] = str(result.id)
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed creating rating for %s/%s", entity_type, entity_id)
        details["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise HTTPException(status_code=500, detail="Failed to create rating")
    finally:
        audit_manager.log_action(
            db=db,
            username=audit_user.username,
            ip_address=request.client.host if request.client else None,
            feature="ratings",
            action="CREATE",
            success=success,
            details=details
        )


@router.get("/entities/{entity_type}/{entity_id}/ratings", response_model=RatingAggregation)
async def get_entity_ratings(
    entity_type: str,
    entity_id: str,
    db: DBSessionDep,
    current_user: CurrentUserDep,
    manager: CommentsManager = Depends(get_comments_manager),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY)),
):
    """Get aggregated ratings for an entity.
    
    Returns average rating, total count, distribution, and current user's rating.
    """
    try:
        return manager.get_rating_aggregation(
            db,
            entity_type=entity_type,
            entity_id=entity_id,
            user_email=current_user.email
        )
    except Exception as e:
        logger.exception("Failed getting ratings for %s/%s", entity_type, entity_id)
        raise HTTPException(status_code=500, detail="Failed to get ratings")


@router.get("/entities/{entity_type}/{entity_id}/ratings/history", response_model=CommentListResponse)
async def get_rating_history(
    entity_type: str,
    entity_id: str,
    db: DBSessionDep,
    current_user: CurrentUserDep,
    user_only: bool = Query(False, description="Only show current user's ratings"),
    manager: CommentsManager = Depends(get_comments_manager),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY)),
):
    """Get rating history for an entity (all individual rating entries)."""
    try:
        return manager.list_ratings(
            db,
            entity_type=entity_type,
            entity_id=entity_id,
            user_email=current_user.email if user_only else None
        )
    except Exception as e:
        logger.exception("Failed getting rating history for %s/%s", entity_type, entity_id)
        raise HTTPException(status_code=500, detail="Failed to get rating history")


def register_routes(app):
    """Register comment routes with the FastAPI app."""
    app.include_router(router)
    logger.info("Comments routes registered with prefix /api")