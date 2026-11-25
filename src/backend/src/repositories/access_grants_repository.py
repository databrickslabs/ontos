"""
Repository for Access Grants database operations.

Provides CRUD operations for access grant requests, grants, and duration configurations.
"""

from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple
from uuid import UUID

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from src.common.logging import get_logger
from src.db_models.access_grants import (
    AccessGrantDb,
    AccessGrantDurationConfigDb,
    AccessGrantRequestDb,
    AccessGrantRequestStatus,
    AccessGrantStatus,
)

logger = get_logger(__name__)


class AccessGrantRequestRepository:
    """Repository for access grant request database operations."""
    
    def create(
        self,
        db: Session,
        *,
        requester_email: str,
        entity_type: str,
        entity_id: str,
        requested_duration_days: int,
        permission_level: str = "READ",
        entity_name: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> AccessGrantRequestDb:
        """Create a new access grant request."""
        request = AccessGrantRequestDb(
            requester_email=requester_email,
            entity_type=entity_type,
            entity_id=entity_id,
            entity_name=entity_name,
            requested_duration_days=requested_duration_days,
            permission_level=permission_level,
            reason=reason,
            status=AccessGrantRequestStatus.PENDING.value,
        )
        db.add(request)
        db.flush()
        logger.info(f"Created access grant request: id={request.id}, requester={requester_email}, entity={entity_type}/{entity_id}")
        return request
    
    def get_by_id(self, db: Session, request_id: UUID) -> Optional[AccessGrantRequestDb]:
        """Get a request by its ID."""
        return db.query(AccessGrantRequestDb).filter(AccessGrantRequestDb.id == request_id).first()
    
    def get_pending_for_entity(
        self,
        db: Session,
        entity_type: str,
        entity_id: str,
        limit: int = 100,
        offset: int = 0
    ) -> Tuple[List[AccessGrantRequestDb], int]:
        """Get pending requests for a specific entity."""
        query = db.query(AccessGrantRequestDb).filter(
            and_(
                AccessGrantRequestDb.entity_type == entity_type,
                AccessGrantRequestDb.entity_id == entity_id,
                AccessGrantRequestDb.status == AccessGrantRequestStatus.PENDING.value
            )
        )
        total = query.count()
        requests = query.order_by(AccessGrantRequestDb.created_at.desc()).offset(offset).limit(limit).all()
        return requests, total
    
    def get_pending_for_user(
        self,
        db: Session,
        email: str,
        limit: int = 100,
        offset: int = 0
    ) -> Tuple[List[AccessGrantRequestDb], int]:
        """Get pending requests made by a specific user."""
        query = db.query(AccessGrantRequestDb).filter(
            and_(
                AccessGrantRequestDb.requester_email == email,
                AccessGrantRequestDb.status == AccessGrantRequestStatus.PENDING.value
            )
        )
        total = query.count()
        requests = query.order_by(AccessGrantRequestDb.created_at.desc()).offset(offset).limit(limit).all()
        return requests, total

    def get_all_for_user(
        self,
        db: Session,
        email: str,
        limit: int = 100,
        offset: int = 0,
        status: Optional[str] = None,
    ) -> Tuple[List[AccessGrantRequestDb], int]:
        """Get the requests made by a specific user (any status, or only `status`)."""
        query = db.query(AccessGrantRequestDb).filter(
            AccessGrantRequestDb.requester_email == email
        )
        if status:
            query = query.filter(AccessGrantRequestDb.status == status)
        total = query.count()
        requests = query.order_by(AccessGrantRequestDb.created_at.desc()).offset(offset).limit(limit).all()
        return requests, total

    def get_all_pending(
        self,
        db: Session,
        limit: int = 100,
        offset: int = 0
    ) -> Tuple[List[AccessGrantRequestDb], int]:
        """Get all pending requests (for admins)."""
        query = db.query(AccessGrantRequestDb).filter(
            AccessGrantRequestDb.status == AccessGrantRequestStatus.PENDING.value
        )
        total = query.count()
        requests = query.order_by(AccessGrantRequestDb.created_at.desc()).offset(offset).limit(limit).all()
        return requests, total
    
    def update_status(
        self,
        db: Session,
        request_id: UUID,
        status: str,
        handled_by: Optional[str] = None,
        admin_message: Optional[str] = None
    ) -> Optional[AccessGrantRequestDb]:
        """Update the status of a request."""
        request = self.get_by_id(db, request_id)
        if not request:
            return None
        
        request.status = status
        request.handled_at = datetime.now(timezone.utc)
        request.handled_by = handled_by
        request.admin_message = admin_message
        
        db.flush()
        logger.info(f"Updated request {request_id} status to {status}")
        return request
    
    def cancel(self, db: Session, request_id: UUID) -> bool:
        """Cancel a pending request."""
        result = db.query(AccessGrantRequestDb).filter(
            and_(
                AccessGrantRequestDb.id == request_id,
                AccessGrantRequestDb.status == AccessGrantRequestStatus.PENDING.value
            )
        ).update({
            "status": AccessGrantRequestStatus.CANCELLED.value,
            "handled_at": datetime.now(timezone.utc)
        })
        db.flush()
        return result > 0
    
    def check_existing_pending(
        self,
        db: Session,
        requester_email: str,
        entity_type: str,
        entity_id: str
    ) -> Optional[AccessGrantRequestDb]:
        """Check if there's already a pending request from this user for this entity."""
        return db.query(AccessGrantRequestDb).filter(
            and_(
                AccessGrantRequestDb.requester_email == requester_email,
                AccessGrantRequestDb.entity_type == entity_type,
                AccessGrantRequestDb.entity_id == entity_id,
                AccessGrantRequestDb.status == AccessGrantRequestStatus.PENDING.value
            )
        ).first()


class AccessGrantRepository:
    """Repository for access grant database operations."""
    
    def create(
        self,
        db: Session,
        *,
        grantee_email: str,
        entity_type: str,
        entity_id: str,
        permission_level: str,
        expires_at: datetime,
        granted_by: Optional[str] = None,
        request_id: Optional[UUID] = None,
        entity_name: Optional[str] = None,
    ) -> AccessGrantDb:
        """Create a new access grant."""
        grant = AccessGrantDb(
            request_id=request_id,
            grantee_email=grantee_email,
            entity_type=entity_type,
            entity_id=entity_id,
            entity_name=entity_name,
            permission_level=permission_level,
            expires_at=expires_at,
            granted_by=granted_by,
            status=AccessGrantStatus.ACTIVE.value,
        )
        db.add(grant)
        db.flush()
        logger.info(f"Created access grant: id={grant.id}, grantee={grantee_email}, entity={entity_type}/{entity_id}, expires={expires_at}")
        return grant
    
    def get_by_id(self, db: Session, grant_id: UUID) -> Optional[AccessGrantDb]:
        """Get a grant by its ID."""
        return db.query(AccessGrantDb).filter(AccessGrantDb.id == grant_id).first()
    
    def get_active_for_entity(
        self,
        db: Session,
        entity_type: str,
        entity_id: str,
        limit: int = 100,
        offset: int = 0
    ) -> Tuple[List[AccessGrantDb], int]:
        """Get active grants for a specific entity."""
        now = datetime.now(timezone.utc)
        query = db.query(AccessGrantDb).filter(
            and_(
                AccessGrantDb.entity_type == entity_type,
                AccessGrantDb.entity_id == entity_id,
                AccessGrantDb.status == AccessGrantStatus.ACTIVE.value,
                AccessGrantDb.expires_at > now
            )
        )
        total = query.count()
        grants = query.order_by(AccessGrantDb.expires_at.asc()).offset(offset).limit(limit).all()
        return grants, total
    
    def get_all_for_entity(
        self,
        db: Session,
        entity_type: str,
        entity_id: str,
        limit: int = 100,
        offset: int = 0
    ) -> Tuple[List[AccessGrantDb], int]:
        """Get all grants for a specific entity (including expired/revoked)."""
        query = db.query(AccessGrantDb).filter(
            and_(
                AccessGrantDb.entity_type == entity_type,
                AccessGrantDb.entity_id == entity_id
            )
        )
        total = query.count()
        grants = query.order_by(AccessGrantDb.granted_at.desc()).offset(offset).limit(limit).all()
        return grants, total
    
    def get_active_for_user(
        self,
        db: Session,
        email: str,
        limit: int = 100,
        offset: int = 0
    ) -> Tuple[List[AccessGrantDb], int]:
        """Get active grants for a specific user."""
        now = datetime.now(timezone.utc)
        query = db.query(AccessGrantDb).filter(
            and_(
                AccessGrantDb.grantee_email == email,
                AccessGrantDb.status == AccessGrantStatus.ACTIVE.value,
                AccessGrantDb.expires_at > now
            )
        )
        total = query.count()
        grants = query.order_by(AccessGrantDb.expires_at.asc()).offset(offset).limit(limit).all()
        return grants, total
    
    def get_expiring_soon(
        self,
        db: Session,
        days_ahead: int = 7
    ) -> List[AccessGrantDb]:
        """Get grants that will expire within the specified number of days."""
        now = datetime.now(timezone.utc)
        threshold = now + timedelta(days=days_ahead)
        return db.query(AccessGrantDb).filter(
            and_(
                AccessGrantDb.status == AccessGrantStatus.ACTIVE.value,
                AccessGrantDb.expires_at > now,
                AccessGrantDb.expires_at <= threshold
            )
        ).order_by(AccessGrantDb.expires_at.asc()).all()
    
    def get_expired(self, db: Session) -> List[AccessGrantDb]:
        """Get grants that have expired but are still marked as active."""
        now = datetime.now(timezone.utc)
        return db.query(AccessGrantDb).filter(
            and_(
                AccessGrantDb.status == AccessGrantStatus.ACTIVE.value,
                AccessGrantDb.expires_at <= now
            )
        ).all()
    
    def mark_expired(self, db: Session, grant_id: UUID) -> bool:
        """Mark a grant as expired."""
        result = db.query(AccessGrantDb).filter(AccessGrantDb.id == grant_id).update({
            "status": AccessGrantStatus.EXPIRED.value
        })
        db.flush()
        return result > 0
    
    def revoke(
        self,
        db: Session,
        grant_id: UUID,
        revoked_by: str,
        reason: Optional[str] = None
    ) -> Optional[AccessGrantDb]:
        """Revoke an active grant."""
        grant = self.get_by_id(db, grant_id)
        if not grant:
            return None
        
        grant.status = AccessGrantStatus.REVOKED.value
        grant.revoked_at = datetime.now(timezone.utc)
        grant.revoked_by = revoked_by
        grant.revocation_reason = reason
        
        db.flush()
        logger.info(f"Revoked grant {grant_id} by {revoked_by}")
        return grant
    
    def check_active_grant(
        self,
        db: Session,
        grantee_email: str,
        entity_type: str,
        entity_id: str
    ) -> Optional[AccessGrantDb]:
        """Check if user has an active grant for an entity."""
        now = datetime.now(timezone.utc)
        return db.query(AccessGrantDb).filter(
            and_(
                AccessGrantDb.grantee_email == grantee_email,
                AccessGrantDb.entity_type == entity_type,
                AccessGrantDb.entity_id == entity_id,
                AccessGrantDb.status == AccessGrantStatus.ACTIVE.value,
                AccessGrantDb.expires_at > now
            )
        ).first()
    
    def count_by_entity(self, db: Session, entity_type: str, entity_id: str) -> dict:
        """Get grant counts for an entity."""
        now = datetime.now(timezone.utc)
        
        active_count = db.query(AccessGrantDb).filter(
            and_(
                AccessGrantDb.entity_type == entity_type,
                AccessGrantDb.entity_id == entity_id,
                AccessGrantDb.status == AccessGrantStatus.ACTIVE.value,
                AccessGrantDb.expires_at > now
            )
        ).count()
        
        total_count = db.query(AccessGrantDb).filter(
            and_(
                AccessGrantDb.entity_type == entity_type,
                AccessGrantDb.entity_id == entity_id
            )
        ).count()
        
        return {
            "active": active_count,
            "total": total_count
        }


class AccessGrantDurationConfigRepository:
    """Repository for access grant duration configuration."""
    
    def get_by_entity_type(
        self,
        db: Session,
        entity_type: str
    ) -> Optional[AccessGrantDurationConfigDb]:
        """Get configuration for a specific entity type."""
        return db.query(AccessGrantDurationConfigDb).filter(
            AccessGrantDurationConfigDb.entity_type == entity_type
        ).first()
    
    def get_all(self, db: Session) -> List[AccessGrantDurationConfigDb]:
        """Get all configurations."""
        return db.query(AccessGrantDurationConfigDb).order_by(
            AccessGrantDurationConfigDb.entity_type
        ).all()
    
    def create(
        self,
        db: Session,
        *,
        entity_type: str,
        allowed_durations: list | dict,
        default_duration: int = 30,
        expiry_workflow_id: Optional[str] = None,
        expiry_warning_days: int = 7,
        allow_renewal: bool = True,
        max_renewals: Optional[int] = 3,
        created_by: Optional[str] = None
    ) -> AccessGrantDurationConfigDb:
        """Create a new duration configuration."""
        config = AccessGrantDurationConfigDb(
            entity_type=entity_type,
            allowed_durations=allowed_durations,
            default_duration=default_duration,
            expiry_workflow_id=expiry_workflow_id,
            expiry_warning_days=expiry_warning_days,
            allow_renewal=allow_renewal,
            max_renewals=max_renewals,
            created_by=created_by,
            updated_by=created_by
        )
        db.add(config)
        db.flush()
        logger.info(f"Created duration config for entity type: {entity_type}")
        return config
    
    def update(
        self,
        db: Session,
        entity_type: str,
        *,
        allowed_durations: Optional[list | dict] = None,
        default_duration: Optional[int] = None,
        expiry_workflow_id: Optional[str] = None,
        expiry_warning_days: Optional[int] = None,
        allow_renewal: Optional[bool] = None,
        max_renewals: Optional[int] = None,
        updated_by: Optional[str] = None
    ) -> Optional[AccessGrantDurationConfigDb]:
        """Update an existing duration configuration."""
        config = self.get_by_entity_type(db, entity_type)
        if not config:
            return None
        
        if allowed_durations is not None:
            config.allowed_durations = allowed_durations
        if default_duration is not None:
            config.default_duration = default_duration
        if expiry_workflow_id is not None:
            config.expiry_workflow_id = expiry_workflow_id
        if expiry_warning_days is not None:
            config.expiry_warning_days = expiry_warning_days
        if allow_renewal is not None:
            config.allow_renewal = allow_renewal
        if max_renewals is not None:
            config.max_renewals = max_renewals
        if updated_by is not None:
            config.updated_by = updated_by
        
        config.updated_at = datetime.now(timezone.utc)
        db.flush()
        logger.info(f"Updated duration config for entity type: {entity_type}")
        return config
    
    def upsert(
        self,
        db: Session,
        entity_type: str,
        *,
        allowed_durations: list | dict,
        default_duration: int = 30,
        expiry_workflow_id: Optional[str] = None,
        expiry_warning_days: int = 7,
        allow_renewal: bool = True,
        max_renewals: Optional[int] = 3,
        user_email: Optional[str] = None
    ) -> AccessGrantDurationConfigDb:
        """Create or update a duration configuration."""
        existing = self.get_by_entity_type(db, entity_type)
        if existing:
            return self.update(
                db,
                entity_type,
                allowed_durations=allowed_durations,
                default_duration=default_duration,
                expiry_workflow_id=expiry_workflow_id,
                expiry_warning_days=expiry_warning_days,
                allow_renewal=allow_renewal,
                max_renewals=max_renewals,
                updated_by=user_email
            )
        else:
            return self.create(
                db,
                entity_type=entity_type,
                allowed_durations=allowed_durations,
                default_duration=default_duration,
                expiry_workflow_id=expiry_workflow_id,
                expiry_warning_days=expiry_warning_days,
                allow_renewal=allow_renewal,
                max_renewals=max_renewals,
                created_by=user_email
            )
    
    def delete(self, db: Session, entity_type: str) -> bool:
        """Delete a configuration."""
        result = db.query(AccessGrantDurationConfigDb).filter(
            AccessGrantDurationConfigDb.entity_type == entity_type
        ).delete()
        db.flush()
        return result > 0


# Singleton instances
access_grant_request_repo = AccessGrantRequestRepository()
access_grant_repo = AccessGrantRepository()
access_grant_duration_config_repo = AccessGrantDurationConfigRepository()

