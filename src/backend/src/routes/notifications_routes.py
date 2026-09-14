import os
from pathlib import Path
from typing import List

from fastapi import APIRouter, HTTPException, Depends, Request
from sqlalchemy.orm import Session

from src.common.authorization import PermissionChecker
from src.common.dependencies import NotificationsManagerDep, DBSessionDep, CurrentUserDep, AuditManagerDep, AuditCurrentUserDep
from src.common.features import FeatureAccessLevel
from src.models.users import UserInfo
from src.controller.notifications_manager import (
    NotificationNotDeletableError,
    NotificationNotFoundError,
    NotificationsManager,
)
from src.models.notifications import Notification

# Configure logging
from src.common.logging import get_logger
logger = get_logger(__name__)

router = APIRouter(prefix="/api", tags=["Notifications"])

@router.get('/notifications', response_model=List[Notification])
async def get_notifications(
    db: DBSessionDep,
    user_info: CurrentUserDep,
    manager: NotificationsManagerDep
):
    """Get notifications filtered for the current user."""
    try:
        logger.debug(f"Retrieving notifications for user: {user_info.email} with groups: {user_info.groups}")
        notifications = manager.get_notifications(db=db, user_info=user_info)
        logger.debug(f"Number of notifications retrieved: {len(notifications)}")
        return notifications
    except Exception as e:
        logger.error(f"Error retrieving notifications: {e!s}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error retrieving notifications.")

@router.post('/notifications', response_model=Notification)
async def create_notification(
    notification: Notification,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager: NotificationsManagerDep,
    _: bool = Depends(PermissionChecker('notifications', FeatureAccessLevel.ADMIN))
):
    """Create a new notification."""
    success = False
    details = {
        "params": {
            "notification_type": notification.type if hasattr(notification, 'type') else None,
            "user_email": notification.user_email if hasattr(notification, 'user_email') else None
        }
    }
    created_notification_id = None

    try:
        created_notification = manager.create_notification(db=db, notification=notification)
        success = True
        created_notification_id = created_notification.id if hasattr(created_notification, 'id') else None
        return created_notification
    except HTTPException as e:
        details["exception"] = {
            "type": "HTTPException",
            "status_code": e.status_code,
            "detail": e.detail
        }
        raise
    except Exception as e:
        logger.error(f"Error creating notification: {e!s}", exc_info=True)
        details["exception"] = {
            "type": type(e).__name__,
            "message": str(e)
        }
        raise HTTPException(status_code=500, detail="Internal server error creating notification.")
    finally:
        if created_notification_id:
            details["created_resource_id"] = created_notification_id
        audit_manager.log_action(
            db=db,
            username=current_user.username if current_user else "anonymous",
            ip_address=request.client.host if request.client else None,
            feature="notifications",
            action="CREATE",
            success=success,
            details=details
        )

@router.delete('/notifications/{notification_id}', status_code=204)
async def delete_notification(
    notification_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager: NotificationsManagerDep,
    _: bool = Depends(PermissionChecker('notifications', FeatureAccessLevel.ADMIN))
):
    """Delete a notification by ID."""
    success = False
    details = {
        "params": {
            "notification_id": notification_id
        }
    }

    try:
        # Mirror the mark-as-read endpoint: the feature permission says the
        # caller may use notifications at all, not that they may act on
        # someone else's. Without this a principal with notifications:ADMIN
        # could delete any other user's notification, including ones scoped
        # to a role they are not in.
        notification = manager.get_notification_by_id(db=db, notification_id=notification_id)
        if not notification:
            raise HTTPException(status_code=404, detail="Notification not found")

        if not manager.can_user_access_notification(db=db, notification=notification, user_info=current_user):
            raise HTTPException(status_code=403, detail="Cannot delete other user's notifications")

        is_admin = manager.is_app_admin(current_user)
        details["params"]["admin_override"] = is_admin and not notification.can_delete

        deleted = manager.delete_notification(
            db=db, notification_id=notification_id, is_admin=is_admin
        )
        if not deleted:
            raise HTTPException(status_code=404, detail="Notification not found")
        success = True
        return None
    except NotificationNotFoundError:
        details["exception"] = {"type": "NotificationNotFoundError", "status_code": 404}
        raise HTTPException(status_code=404, detail="Notification not found")
    except NotificationNotDeletableError:
        details["exception"] = {"type": "NotificationNotDeletableError", "status_code": 403}
        raise HTTPException(
            status_code=403,
            detail="This notification requires a response and cannot be dismissed",
        )
    except HTTPException as e:
        details["exception"] = {
            "type": "HTTPException",
            "status_code": e.status_code,
            "detail": e.detail
        }
        raise
    except Exception as e:
        logger.error(f"Error deleting notification {notification_id}: {e!s}", exc_info=True)
        details["exception"] = {
            "type": type(e).__name__,
            "message": str(e)
        }
        raise HTTPException(status_code=500, detail="Internal server error deleting notification.")
    finally:
        audit_manager.log_action(
            db=db,
            username=current_user.username if current_user else "anonymous",
            ip_address=request.client.host if request.client else None,
            feature="notifications",
            action="DELETE",
            success=success,
            details=details
        )

@router.put('/notifications/{notification_id}/read', response_model=Notification)
async def mark_notification_read(
    notification_id: str,
    db: DBSessionDep,
    user_info: CurrentUserDep,
    manager: NotificationsManagerDep
):
    """Mark a notification as read."""
    try:
        # Verify notification exists and user can access it
        notification = manager.get_notification_by_id(db=db, notification_id=notification_id)
        if not notification:
            raise HTTPException(status_code=404, detail="Notification not found")
        
        # Use role-based access check (same logic as get_notifications)
        if not manager.can_user_access_notification(db=db, notification=notification, user_info=user_info):
            raise HTTPException(status_code=403, detail="Cannot modify other user's notifications")

        updated_notification = manager.mark_notification_read(db=db, notification_id=notification_id)
        if updated_notification is None:
            raise HTTPException(status_code=404, detail="Notification not found")
        return updated_notification
    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Error marking notification {notification_id} as read: {e!s}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error marking notification as read.")

def register_routes(app):
    """Register notification routes with the FastAPI app."""
    app.include_router(router)
    logger.info("Notifications routes registered")

