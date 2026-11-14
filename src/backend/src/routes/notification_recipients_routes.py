from typing import Any, Dict, List

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status

from src.common.dependencies import AuditCurrentUserDep, AuditManagerDep, DBSessionDep
from src.common.features import FeatureAccessLevel
from src.common.authorization import PermissionChecker
from src.common.logging import get_logger
from src.common.manager_dependencies import get_auth_manager
from src.common.notification_audience import audience_for_request
from src.controller.authorization_manager import AuthorizationManager
from src.controller.notification_recipients_manager import NotificationRecipientError, notification_recipients_manager
from src.db_models.notification_recipients import NotificationRecipientDb
from src.models.notification_recipients import (
    NotificationRecipient,
    NotificationRecipientCreate,
    NotificationRecipientUpdate,
)
from src.repositories.notification_recipient_repository import json_list

logger = get_logger(__name__)

router = APIRouter(prefix="/api", tags=["Notification Recipients"])

# Managed in Settings, next to app roles: admins only
SETTINGS_FEATURE_ID = 'settings-roles'
AUDIT_FEATURE_ID = 'notification-recipients'


def _to_api(recipient: NotificationRecipientDb) -> Dict[str, Any]:
    return NotificationRecipient(
        id=str(recipient.id),
        name=recipient.name,
        description=recipient.description,
        targets=json_list(recipient.targets),
        allowed_role_ids=json_list(recipient.allowed_role_ids),
        is_active=bool(recipient.is_active),
        created_by=recipient.created_by,
        updated_by=recipient.updated_by,
        created_at=recipient.created_at,
        updated_at=recipient.updated_at,
    ).model_dump()


def _audit(audit_manager, request: Request, db, current_user, action: str, recipient_id: str, name: str) -> None:
    audit_manager.log_action(
        db=db,
        username=current_user.username if current_user else 'unknown',
        ip_address=request.client.host if request.client else None,
        feature=AUDIT_FEATURE_ID,
        action=action,
        success=True,
        details={'recipient_id': recipient_id, 'name': name},
    )


@router.get('/settings/notification-recipients')
async def list_notification_recipients(
    db: DBSessionDep,
    _: bool = Depends(PermissionChecker(SETTINGS_FEATURE_ID, FeatureAccessLevel.ADMIN)),
) -> List[Dict[str, Any]]:
    return [_to_api(r) for r in notification_recipients_manager.list(db)]


@router.post('/settings/notification-recipients', status_code=status.HTTP_201_CREATED)
async def create_notification_recipient(
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    recipient: NotificationRecipientCreate = Body(...),
    _: bool = Depends(PermissionChecker(SETTINGS_FEATURE_ID, FeatureAccessLevel.ADMIN)),
) -> Dict[str, Any]:
    try:
        created = notification_recipients_manager.create(
            db, recipient, username=current_user.email if current_user else None,
        )
    except NotificationRecipientError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    _audit(audit_manager, request, db, current_user, 'CREATE_NOTIFICATION_RECIPIENT', created.id, created.name)
    return _to_api(created)


@router.put('/settings/notification-recipients/{recipient_id}')
async def update_notification_recipient(
    recipient_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    recipient: NotificationRecipientUpdate = Body(...),
    _: bool = Depends(PermissionChecker(SETTINGS_FEATURE_ID, FeatureAccessLevel.ADMIN)),
) -> Dict[str, Any]:
    try:
        updated = notification_recipients_manager.update(
            db, recipient_id, recipient, username=current_user.email if current_user else None,
        )
    except NotificationRecipientError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    if updated is None:
        raise HTTPException(status_code=404, detail="Notification recipient not found")
    _audit(audit_manager, request, db, current_user, 'UPDATE_NOTIFICATION_RECIPIENT', recipient_id, updated.name)
    return _to_api(updated)


@router.delete('/settings/notification-recipients/{recipient_id}', status_code=status.HTTP_204_NO_CONTENT)
async def delete_notification_recipient(
    recipient_id: str,
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    _: bool = Depends(PermissionChecker(SETTINGS_FEATURE_ID, FeatureAccessLevel.ADMIN)),
) -> None:
    existing = notification_recipients_manager.get(db, recipient_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Notification recipient not found")
    name = existing.name
    notification_recipients_manager.delete(db, recipient_id)
    _audit(audit_manager, request, db, current_user, 'DELETE_NOTIFICATION_RECIPIENT', recipient_id, name)


@router.get('/compliance/notification-recipients/available')
async def list_available_notification_recipients(
    request: Request,
    db: DBSessionDep,
    current_user: AuditCurrentUserDep,
    auth_manager: AuthorizationManager = Depends(get_auth_manager),
    _: bool = Depends(PermissionChecker('compliance', FeatureAccessLevel.READ_WRITE)),
) -> List[Dict[str, Any]]:
    """The active recipients the current user may name in a NOTIFY action (admins: all)."""
    audience = await audience_for_request(
        db, request, auth_manager,
        current_user.email if current_user else None, current_user.groups if current_user else [],
    )
    usable = notification_recipients_manager.usable_by_user(db, audience)
    return [{'id': str(r.id), 'name': r.name, 'description': r.description} for r in usable]


def register_routes(app) -> None:
    app.include_router(router)
