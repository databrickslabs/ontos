"""
Access Grants Manager.

Manages time-limited access grants to assets including:
- Creating and handling access requests
- Managing active grants
- Checking for expiring/expired grants
- Triggering expiry workflows
"""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from src.common.logging import get_logger
from src.db_models.access_grants import (
    AccessGrantDb,
    AccessGrantDurationConfigDb,
    AccessGrantRequestDb,
    AccessGrantRequestStatus,
    AccessGrantStatus,
)
from src.models.access_grants import (
    AccessGrantDurationConfigCreate,
    AccessGrantDurationConfigResponse,
    AccessGrantHandlePayload,
    AccessGrantList,
    AccessGrantRequestCreate,
    AccessGrantRequestList,
    AccessGrantRequestResponse,
    AccessGrantResponse,
    AccessGrantSummary,
    UserAccessGrantsSummary,
)
from src.models.notifications import Notification, NotificationType
from src.repositories.access_grants_repository import (
    access_grant_duration_config_repo,
    access_grant_repo,
    access_grant_request_repo,
)

logger = get_logger(__name__)


class AccessGrantsManager:
    """Manager for access grant operations."""
    
    def __init__(
        self,
        notifications_manager=None,
        process_workflows_manager=None
    ):
        """
        Initialize the access grants manager.
        
        Args:
            notifications_manager: NotificationsManager for sending notifications
            process_workflows_manager: ProcessWorkflowsManager for triggering expiry workflows
        """
        self._notifications_manager = notifications_manager
        self._process_workflows_manager = process_workflows_manager
        self._request_repo = access_grant_request_repo
        self._grant_repo = access_grant_repo
        self._config_repo = access_grant_duration_config_repo
    
    # =========================================================================
    # Access Request Operations
    # =========================================================================
    
    def create_request(
        self,
        db: Session,
        requester_email: str,
        data: AccessGrantRequestCreate
    ) -> AccessGrantRequestResponse:
        """
        Create a new access grant request via workflow.
        
        Fires ON_REQUEST_ACCESS trigger to execute configured workflows
        for notifications and approvals.
        
        Args:
            db: Database session
            requester_email: Email of the requesting user
            data: Request creation data
            
        Returns:
            The created request
            
        Raises:
            ValueError: If there's already a pending request
        """
        from src.common.workflow_triggers import get_trigger_registry
        from src.models.process_workflows import EntityType
        
        # Check for existing pending request
        existing = self._request_repo.check_existing_pending(
            db,
            requester_email=requester_email,
            entity_type=data.entity_type,
            entity_id=data.entity_id
        )
        if existing:
            raise ValueError(
                f"You already have a pending access request for this {data.entity_type}. "
                f"Please wait for it to be processed."
            )
        
        # Check if user already has an active grant
        active_grant = self._grant_repo.check_active_grant(
            db,
            grantee_email=requester_email,
            entity_type=data.entity_type,
            entity_id=data.entity_id
        )
        if active_grant:
            raise ValueError(
                f"You already have active access to this {data.entity_type} "
                f"(expires {active_grant.expires_at.strftime('%Y-%m-%d')})."
            )
        
        # Validate duration against config (if config exists)
        config = self._config_repo.get_by_entity_type(db, data.entity_type)
        if config and not config.is_duration_allowed(data.requested_duration_days):
            options = config.get_duration_options()
            raise ValueError(
                f"Requested duration ({data.requested_duration_days} days) is not allowed. "
                f"Allowed options: {options}"
            )
        
        # Create the request
        request_db = self._request_repo.create(
            db,
            requester_email=requester_email,
            entity_type=data.entity_type,
            entity_id=data.entity_id,
            entity_name=data.entity_name,
            requested_duration_days=data.requested_duration_days,
            permission_level=data.permission_level.value,
            reason=data.reason
        )
        
        db.commit()
        
        # Fire the ON_REQUEST_ACCESS trigger.
        # Path-B portable wizard launch: the FE merges fields collected by the
        # ``for_request_access`` approval wizard's ``user_action`` steps into
        # ``data.wizard_data``. We splat that dict at the top level of
        # ``entity_data`` so Process workflow steps can reference each field
        # via ``${entity.<field_id>}`` without the workflow author needing to
        # know the wrapper key. First-class fields take precedence on
        # collision (workflow authors should namespace custom field ids).
        # Pydantic ``extra='allow'`` may also bag other ad-hoc fields onto the
        # model — we forward those too to keep the surface flexible.
        entity_data: Dict[str, object] = {
            "request_id": str(request_db.id),
            "entity_type": data.entity_type,
            "entity_id": data.entity_id,
            "entity_name": data.entity_name,
            "requested_duration_days": data.requested_duration_days,
            "permission_level": data.permission_level.value,
            "reason": data.reason,
        }
        wizard_data = getattr(data, "wizard_data", None) or {}
        if isinstance(wizard_data, dict) and wizard_data:
            for k, v in wizard_data.items():
                if k not in entity_data:
                    entity_data[k] = v
            # Preserve the original namespaced bag too so workflow authors who
            # prefer ``${entity.wizard_data.<id>}`` over the splatted form can
            # use either. Only set when non-empty so legacy callers without a
            # wizard see the original ``entity_data`` shape unchanged.
            entity_data["wizard_data"] = wizard_data
        # Forward any other ``extra='allow'`` fields from the request body.
        extra_fields = getattr(data, "model_extra", None) or {}
        for k, v in extra_fields.items():
            if k != "wizard_data" and k not in entity_data:
                entity_data[k] = v

        trigger_registry = get_trigger_registry(db)
        executions = trigger_registry.on_request_access(
            entity_type=EntityType.ACCESS_GRANT,
            entity_id=str(request_db.id),
            entity_name=data.entity_name,
            entity_data=entity_data,
            user_email=requester_email,
        )
        
        logger.info(
            f"Created access request {request_db.id} from {requester_email} "
            f"for {data.entity_type}/{data.entity_id} "
            f"(workflows triggered: {len(executions)})"
        )
        
        # Fall back to direct notification if no workflows configured
        if not executions:
            self._notify_admins_new_request(db, request_db)
        
        return AccessGrantRequestResponse.model_validate(request_db)
    
    def handle_request(
        self,
        db: Session,
        admin_email: str,
        payload: AccessGrantHandlePayload
    ) -> Tuple[AccessGrantRequestResponse, Optional[AccessGrantResponse]]:
        """
        Handle (approve/deny) an access grant request.
        
        Args:
            db: Database session
            admin_email: Email of the admin handling the request
            payload: Decision payload
            
        Returns:
            Tuple of (updated request, created grant if approved)
        """
        request = self._request_repo.get_by_id(db, payload.request_id)
        if not request:
            raise ValueError(f"Request {payload.request_id} not found")
        
        if request.status != AccessGrantRequestStatus.PENDING.value:
            raise ValueError(f"Request {payload.request_id} is not pending (status: {request.status})")
        
        grant = None
        
        if payload.approved:
            # Create the grant
            duration_days = payload.granted_duration_days or request.requested_duration_days
            permission_level = payload.permission_level.value if payload.permission_level else request.permission_level
            expires_at = datetime.now(timezone.utc) + timedelta(days=duration_days)
            
            grant_db = self._grant_repo.create(
                db,
                request_id=request.id,
                grantee_email=request.requester_email,
                entity_type=request.entity_type,
                entity_id=request.entity_id,
                entity_name=request.entity_name,
                permission_level=permission_level,
                expires_at=expires_at,
                granted_by=admin_email
            )
            
            # Update request status
            self._request_repo.update_status(
                db,
                request.id,
                status=AccessGrantRequestStatus.APPROVED.value,
                handled_by=admin_email,
                admin_message=payload.message
            )
            
            grant = AccessGrantResponse.model_validate(grant_db)
            grant.days_until_expiry = grant_db.days_until_expiry
            grant.is_active = grant_db.is_active
            
            # Notify requester of approval
            self._notify_requester_decision(
                db, 
                request, 
                approved=True, 
                message=payload.message,
                expires_at=expires_at
            )
            
            logger.info(
                f"Approved access request {request.id}: {request.requester_email} "
                f"granted {permission_level} access to {request.entity_type}/{request.entity_id} "
                f"for {duration_days} days"
            )
        else:
            # Deny the request
            self._request_repo.update_status(
                db,
                request.id,
                status=AccessGrantRequestStatus.DENIED.value,
                handled_by=admin_email,
                admin_message=payload.message
            )
            
            # Notify requester of denial
            self._notify_requester_decision(db, request, approved=False, message=payload.message)
            
            logger.info(f"Denied access request {request.id}")
        
        db.commit()
        
        # Refresh request
        db.refresh(request)
        request_response = AccessGrantRequestResponse.model_validate(request)
        
        return request_response, grant
    
    def get_pending_requests_for_entity(
        self,
        db: Session,
        entity_type: str,
        entity_id: str,
        limit: int = 100,
        offset: int = 0
    ) -> AccessGrantRequestList:
        """Get pending requests for an entity."""
        requests, total = self._request_repo.get_pending_for_entity(
            db, entity_type, entity_id, limit, offset
        )
        return AccessGrantRequestList(
            requests=[AccessGrantRequestResponse.model_validate(r) for r in requests],
            total=total
        )
    
    def get_all_pending_requests(
        self,
        db: Session,
        limit: int = 100,
        offset: int = 0
    ) -> AccessGrantRequestList:
        """Get all pending requests (for admins)."""
        requests, total = self._request_repo.get_all_pending(db, limit, offset)
        return AccessGrantRequestList(
            requests=[AccessGrantRequestResponse.model_validate(r) for r in requests],
            total=total
        )
    
    def get_my_pending_requests(
        self,
        db: Session,
        email: str,
        limit: int = 100,
        offset: int = 0
    ) -> AccessGrantRequestList:
        """Get pending requests for a user."""
        requests, total = self._request_repo.get_pending_for_user(db, email, limit, offset)
        return AccessGrantRequestList(
            requests=[AccessGrantRequestResponse.model_validate(r) for r in requests],
            total=total
        )

    def get_my_requests(
        self,
        db: Session,
        email: str,
        limit: int = 100,
        offset: int = 0
    ) -> AccessGrantRequestList:
        """Get all requests made by a user (any status: pending, approved, denied, etc.)."""
        requests, total = self._request_repo.get_all_for_user(db, email, limit, offset)
        return AccessGrantRequestList(
            requests=[AccessGrantRequestResponse.model_validate(r) for r in requests],
            total=total
        )

    def cancel_request(self, db: Session, request_id: str, user_email: str) -> bool:
        """Cancel a pending request (by the requester)."""
        request = self._request_repo.get_by_id(db, request_id)
        if not request:
            raise ValueError(f"Request {request_id} not found")
        
        if request.requester_email != user_email:
            raise ValueError("You can only cancel your own requests")
        
        if request.status != AccessGrantRequestStatus.PENDING.value:
            raise ValueError("Only pending requests can be cancelled")
        
        result = self._request_repo.cancel(db, request_id)
        db.commit()
        return result
    
    # =========================================================================
    # Access Grant Operations
    # =========================================================================
    
    def get_grants_for_entity(
        self,
        db: Session,
        entity_type: str,
        entity_id: str,
        include_inactive: bool = False,
        limit: int = 100,
        offset: int = 0
    ) -> AccessGrantList:
        """Get grants for an entity."""
        if include_inactive:
            grants, total = self._grant_repo.get_all_for_entity(
                db, entity_type, entity_id, limit, offset
            )
        else:
            grants, total = self._grant_repo.get_active_for_entity(
                db, entity_type, entity_id, limit, offset
            )
        
        grant_responses = []
        for g in grants:
            resp = AccessGrantResponse.model_validate(g)
            resp.days_until_expiry = g.days_until_expiry
            resp.is_active = g.is_active
            grant_responses.append(resp)
        
        return AccessGrantList(grants=grant_responses, total=total)
    
    def get_my_grants(
        self,
        db: Session,
        email: str,
        limit: int = 100,
        offset: int = 0
    ) -> AccessGrantList:
        """Get active grants for the current user."""
        grants, total = self._grant_repo.get_active_for_user(db, email, limit, offset)
        
        grant_responses = []
        for g in grants:
            resp = AccessGrantResponse.model_validate(g)
            resp.days_until_expiry = g.days_until_expiry
            resp.is_active = g.is_active
            grant_responses.append(resp)
        
        return AccessGrantList(grants=grant_responses, total=total)
    
    def revoke_grant(
        self,
        db: Session,
        grant_id: str,
        revoked_by: str,
        reason: Optional[str] = None
    ) -> AccessGrantResponse:
        """Revoke an active grant."""
        grant = self._grant_repo.revoke(db, grant_id, revoked_by, reason)
        if not grant:
            raise ValueError(f"Grant {grant_id} not found")
        
        db.commit()
        
        # Notify the grantee
        self._notify_grant_revoked(db, grant, reason)
        
        logger.info(f"Revoked grant {grant_id} by {revoked_by}")
        
        resp = AccessGrantResponse.model_validate(grant)
        resp.days_until_expiry = grant.days_until_expiry
        resp.is_active = grant.is_active
        return resp
    
    def get_entity_summary(
        self,
        db: Session,
        entity_type: str,
        entity_id: str
    ) -> AccessGrantSummary:
        """Get a summary of grants and requests for an entity."""
        # Get grant counts
        grant_counts = self._grant_repo.count_by_entity(db, entity_type, entity_id)
        
        # Get pending requests count
        _, pending_count = self._request_repo.get_pending_for_entity(
            db, entity_type, entity_id, limit=0, offset=0
        )
        
        # Get expiring soon count
        config = self._config_repo.get_by_entity_type(db, entity_type)
        warning_days = config.expiry_warning_days if config else 7
        expiring = self._grant_repo.get_expiring_soon(db, warning_days)
        expiring_for_entity = [
            g for g in expiring 
            if g.entity_type == entity_type and g.entity_id == entity_id
        ]
        
        return AccessGrantSummary(
            entity_type=entity_type,
            entity_id=entity_id,
            active_grants_count=grant_counts["active"],
            pending_requests_count=pending_count,
            expiring_soon_count=len(expiring_for_entity),
            total_grants_count=grant_counts["total"]
        )
    
    def get_user_summary(self, db: Session, email: str) -> UserAccessGrantsSummary:
        """Get a summary of a user's grants and requests."""
        active_grants, _ = self._grant_repo.get_active_for_user(db, email)
        pending_requests, _ = self._request_repo.get_pending_for_user(db, email)
        
        # Find expiring soon grants
        expiring_soon = [g for g in active_grants if g.days_until_expiry and g.days_until_expiry <= 7]
        
        return UserAccessGrantsSummary(
            email=email,
            active_grants=[AccessGrantResponse.model_validate(g) for g in active_grants],
            pending_requests=[AccessGrantRequestResponse.model_validate(r) for r in pending_requests],
            expiring_soon=[AccessGrantResponse.model_validate(g) for g in expiring_soon]
        )
    
    # =========================================================================
    # Duration Configuration Operations
    # =========================================================================
    
    def get_duration_config(
        self,
        db: Session,
        entity_type: str
    ) -> Optional[AccessGrantDurationConfigResponse]:
        """Get duration configuration for an entity type."""
        config = self._config_repo.get_by_entity_type(db, entity_type)
        if not config:
            return None
        
        resp = AccessGrantDurationConfigResponse.model_validate(config)
        resp.duration_options = config.get_duration_options()
        return resp
    
    def get_all_duration_configs(self, db: Session) -> List[AccessGrantDurationConfigResponse]:
        """Get all duration configurations."""
        configs = self._config_repo.get_all(db)
        results = []
        for c in configs:
            resp = AccessGrantDurationConfigResponse.model_validate(c)
            resp.duration_options = c.get_duration_options()
            results.append(resp)
        return results
    
    def upsert_duration_config(
        self,
        db: Session,
        data: AccessGrantDurationConfigCreate,
        user_email: Optional[str] = None
    ) -> AccessGrantDurationConfigResponse:
        """Create or update a duration configuration."""
        # Convert allowed_durations to dict if it's a DurationRangeConfig
        allowed_durations = data.allowed_durations
        if hasattr(allowed_durations, 'model_dump'):
            allowed_durations = allowed_durations.model_dump()
        
        config = self._config_repo.upsert(
            db,
            entity_type=data.entity_type,
            allowed_durations=allowed_durations,
            default_duration=data.default_duration,
            expiry_workflow_id=data.expiry_workflow_id,
            expiry_warning_days=data.expiry_warning_days,
            allow_renewal=data.allow_renewal,
            max_renewals=data.max_renewals,
            user_email=user_email
        )
        
        db.commit()
        
        resp = AccessGrantDurationConfigResponse.model_validate(config)
        resp.duration_options = config.get_duration_options()
        return resp
    
    def get_duration_options(self, db: Session, entity_type: str) -> List[int]:
        """Get available duration options for an entity type."""
        config = self._config_repo.get_by_entity_type(db, entity_type)
        if config:
            return config.get_duration_options()
        # Default options
        return [30, 60, 90]
    
    # =========================================================================
    # Expiration Handling
    # =========================================================================
    
    def check_and_process_expirations(self, db: Session) -> Dict[str, int]:
        """
        Check for expired grants and trigger appropriate workflows.
        
        This should be called by a background job.
        
        Returns:
            Dict with counts of processed items
        """
        results = {
            "expired_marked": 0,
            "warnings_sent": 0,
            "workflows_triggered": 0
        }
        
        # Mark expired grants
        expired = self._grant_repo.get_expired(db)
        for grant in expired:
            self._grant_repo.mark_expired(db, grant.id)
            self._trigger_expiry_workflow(db, grant)
            results["expired_marked"] += 1
            results["workflows_triggered"] += 1
        
        # Send expiry warnings
        expiring_soon = self._grant_repo.get_expiring_soon(db)
        for grant in expiring_soon:
            # Check if we should send a warning based on config
            config = self._config_repo.get_by_entity_type(db, grant.entity_type)
            warning_days = config.expiry_warning_days if config else 7
            
            if grant.days_until_expiry and grant.days_until_expiry <= warning_days:
                self._send_expiry_warning(db, grant)
                results["warnings_sent"] += 1
        
        db.commit()
        
        logger.info(
            f"Expiration check complete: {results['expired_marked']} expired, "
            f"{results['warnings_sent']} warnings, {results['workflows_triggered']} workflows"
        )
        
        return results
    
    def _trigger_expiry_workflow(self, db: Session, grant: AccessGrantDb) -> None:
        """Trigger the expiry workflow for a grant."""
        config = self._config_repo.get_by_entity_type(db, grant.entity_type)
        
        if not config or not config.expiry_workflow_id:
            logger.debug(f"No expiry workflow configured for {grant.entity_type}")
            return
        
        if not self._process_workflows_manager:
            logger.warning("Process workflows manager not available, cannot trigger expiry workflow")
            return
        
        try:
            # Prepare workflow context
            context = {
                "grant_id": str(grant.id),
                "grantee_email": grant.grantee_email,
                "entity_type": grant.entity_type,
                "entity_id": grant.entity_id,
                "entity_name": grant.entity_name,
                "permission_level": grant.permission_level,
                "expired_at": grant.expires_at.isoformat() if grant.expires_at else None,
                "granted_by": grant.granted_by,
                "event_type": "access_grant_expired"
            }
            
            # Trigger the workflow
            self._process_workflows_manager.trigger_workflow(
                db=db,
                workflow_id=config.expiry_workflow_id,
                context=context
            )
            
            logger.info(
                f"Triggered expiry workflow {config.expiry_workflow_id} for grant {grant.id}"
            )
        except Exception as e:
            logger.error(f"Failed to trigger expiry workflow for grant {grant.id}: {e}")
    
    # =========================================================================
    # Notification Helpers
    # =========================================================================
    
    def _notify_admins_new_request(self, db: Session, request: AccessGrantRequestDb) -> None:
        """Send notification to admins about a new access request."""
        if not self._notifications_manager:
            logger.debug("Notifications manager not available")
            return
        
        try:
            notification = Notification(
                id=str(uuid.uuid4()),
                created_at=datetime.utcnow(),
                type=NotificationType.ACTION_REQUIRED,
                title="New Access Grant Request",
                subtitle=f"From: {request.requester_email}",
                description=(
                    f"Request for {request.permission_level} access to "
                    f"{request.entity_type} '{request.entity_name or request.entity_id}' "
                    f"for {request.requested_duration_days} days."
                    + (f"\n\nReason: {request.reason}" if request.reason else "")
                ),
                recipient="Admin",  # Role-based notification
                action_type="handle_access_grant_request",
                action_payload={
                    "request_id": str(request.id),
                    "entity_type": request.entity_type,
                    "entity_id": request.entity_id,
                    "entity_name": request.entity_name,
                    "requester_email": request.requester_email,
                    "requested_duration_days": request.requested_duration_days,
                    "permission_level": request.permission_level,
                    "reason": request.reason,
                    "created_at": request.created_at.isoformat() if request.created_at else None
                },
                can_delete=False
            )
            self._notifications_manager.create_notification(notification=notification, db=db)
        except Exception as e:
            logger.error(f"Failed to send admin notification for request {request.id}: {e}")
    
    def _notify_requester_decision(
        self,
        db: Session,
        request: AccessGrantRequestDb,
        approved: bool,
        message: Optional[str] = None,
        expires_at: Optional[datetime] = None
    ) -> None:
        """Notify the requester about the decision."""
        if not self._notifications_manager:
            return
        
        try:
            if approved:
                title = "Access Request Approved"
                description = (
                    f"Your request for access to {request.entity_type} "
                    f"'{request.entity_name or request.entity_id}' has been approved."
                )
                if expires_at:
                    description += f"\n\nAccess expires: {expires_at.strftime('%Y-%m-%d %H:%M UTC')}"
            else:
                title = "Access Request Denied"
                description = (
                    f"Your request for access to {request.entity_type} "
                    f"'{request.entity_name or request.entity_id}' has been denied."
                )
            
            if message:
                description += f"\n\nAdmin message: {message}"
            
            notification = Notification(
                id=str(uuid.uuid4()),
                created_at=datetime.utcnow(),
                type=NotificationType.INFO if approved else NotificationType.WARNING,
                title=title,
                description=description,
                recipient=request.requester_email,
                can_delete=True
            )
            self._notifications_manager.create_notification(notification=notification, db=db)
        except Exception as e:
            logger.error(f"Failed to send decision notification: {e}")
    
    def _notify_grant_revoked(
        self,
        db: Session,
        grant: AccessGrantDb,
        reason: Optional[str] = None
    ) -> None:
        """Notify the grantee that their access has been revoked using workflow triggers."""
        # Try workflow trigger first
        try:
            from src.common.workflow_triggers import get_trigger_registry
            from src.models.process_workflows import EntityType
            
            trigger_registry = get_trigger_registry(db)
            entity_data = {
                "grant_id": str(grant.id),
                "grantee_email": grant.grantee_email,
                "entity_type": grant.entity_type,
                "entity_id": grant.entity_id,
                "entity_name": grant.entity_name,
                "permission_level": grant.permission_level,
                "revocation_reason": reason,
            }
            
            executions = trigger_registry.on_revoke(
                entity_type=EntityType.ACCESS_GRANT,
                entity_id=str(grant.id),
                entity_name=grant.entity_name or grant.entity_id,
                entity_data=entity_data,
                user_email=grant.grantee_email,
                revoked_by=grant.revoked_by,
                blocking=False,
            )
            
            if executions:
                logger.info(f"Triggered {len(executions)} workflow(s) for access revocation (grant {grant.id})")
                return
        except Exception as workflow_err:
            logger.error(f"Failed to trigger workflow for access revocation: {workflow_err}", exc_info=True)
        
        # Fallback to direct notification
        if not self._notifications_manager:
            return
        
        try:
            description = (
                f"Your access to {grant.entity_type} "
                f"'{grant.entity_name or grant.entity_id}' has been revoked."
            )
            if reason:
                description += f"\n\nReason: {reason}"
            
            notification = Notification(
                id=str(uuid.uuid4()),
                created_at=datetime.utcnow(),
                type=NotificationType.WARNING,
                title="Access Revoked",
                description=description,
                recipient=grant.grantee_email,
                can_delete=True
            )
            self._notifications_manager.create_notification(notification=notification, db=db)
            logger.info(f"No workflow configured; sent direct revocation notification for grant {grant.id}")
        except Exception as e:
            logger.error(f"Failed to send revocation notification: {e}")
    
    def _send_expiry_warning(self, db: Session, grant: AccessGrantDb) -> None:
        """Send a warning that access is about to expire using workflow triggers."""
        days = grant.days_until_expiry or 0
        
        # Try workflow trigger first
        try:
            from src.common.workflow_triggers import get_trigger_registry
            from src.models.process_workflows import EntityType
            
            trigger_registry = get_trigger_registry(db)
            entity_data = {
                "grant_id": str(grant.id),
                "grantee_email": grant.grantee_email,
                "entity_type": grant.entity_type,
                "entity_id": grant.entity_id,
                "entity_name": grant.entity_name,
                "permission_level": grant.permission_level,
                "days_until_expiry": days,
                "expires_at": grant.expires_at.isoformat() if grant.expires_at else None,
            }
            
            executions = trigger_registry.on_expiring(
                entity_type=EntityType.ACCESS_GRANT,
                entity_id=str(grant.id),
                entity_name=grant.entity_name or grant.entity_id,
                entity_data=entity_data,
                user_email=grant.grantee_email,
                blocking=False,
            )
            
            if executions:
                logger.info(f"Triggered {len(executions)} workflow(s) for expiry warning (grant {grant.id})")
                return
        except Exception as workflow_err:
            logger.error(f"Failed to trigger workflow for expiry warning: {workflow_err}", exc_info=True)
        
        # Fallback to direct notification
        if not self._notifications_manager:
            return
        
        try:
            notification = Notification(
                id=str(uuid.uuid4()),
                created_at=datetime.utcnow(),
                type=NotificationType.WARNING,
                title="Access Expiring Soon",
                description=(
                    f"Your access to {grant.entity_type} "
                    f"'{grant.entity_name or grant.entity_id}' expires in {days} day(s). "
                    f"Contact the owner if you need to extend your access."
                ),
                recipient=grant.grantee_email,
                can_delete=True
            )
            self._notifications_manager.create_notification(notification=notification, db=db)
            logger.info(f"No workflow configured; sent direct expiry warning for grant {grant.id}")
        except Exception as e:
            logger.error(f"Failed to send expiry warning: {e}")


# Singleton instance (will be properly initialized in app startup)
access_grants_manager: Optional[AccessGrantsManager] = None


def get_access_grants_manager() -> AccessGrantsManager:
    """Get the access grants manager instance."""
    global access_grants_manager
    if access_grants_manager is None:
        access_grants_manager = AccessGrantsManager()
    return access_grants_manager

