import json
import uuid
from sqlalchemy import Boolean, Column, String, Text, func, UniqueConstraint, TIMESTAMP, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB # Use JSONB if available, falls back for others
from sqlalchemy.orm import relationship

from src.common.database import Base

# Sentinel value for "no role required" in role_request_permissions
NO_ROLE_SENTINEL = '__NO_ROLE__'

class AppRoleDb(Base):
    """App role: name, assigned groups, feature permissions, home sections, approval privileges; used for RBAC (SettingsManager, AuthorizationManager)."""
    __tablename__ = 'app_roles'

    # Use UUID for primary key, store as string
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    # Store lists/dicts as JSON strings or Text
    # Using Text for broader compatibility, can switch to JSONB if needed
    assigned_groups = Column(Text, nullable=False, default='[]')
    # Individual users (by email) assigned to this role, parallel to assigned_groups.
    # Matched case-insensitively against the user's IdP-issued email at auth time (#196/#760).
    assigned_users = Column(Text, nullable=False, default='[]', server_default='[]')
    feature_permissions = Column(Text, nullable=False, default='{}')
    home_sections = Column(Text, nullable=False, default='[]')
    # Approval privileges JSON (e.g., {"CONTRACTS": true, "PRODUCTS": true})
    approval_privileges = Column(Text, nullable=False, default='{}')
    # Deployment policy JSON (catalog/schema restrictions, nullable for backward compatibility)
    deployment_policy = Column(Text, nullable=True, comment="Deployment policy for this role (catalog/schema restrictions)")
    is_admin = Column(Boolean, nullable=False, default=False, server_default='false',
                      comment="Whether this role is the admin role")

    # Add timestamp columns - Make them nullable
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=True)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=True)

    # Define uniqueness constraint on 'name' if desired
    __table_args__ = (UniqueConstraint('name', name='uq_app_roles_name'),)

    def __repr__(self):
        return f"<AppRoleDb(id='{self.id}', name='{self.name}')>"


class RoleRequestPermissionDb(Base):
    """Maps which roles can request access to other roles.
    
    requestable_by_role_id can be:
    - A valid role ID: Users with that role can request access
    - '__NO_ROLE__': Users without any role can request access
    """
    __tablename__ = 'role_request_permissions'

    role_id = Column(
        String, 
        ForeignKey('app_roles.id', ondelete='CASCADE'), 
        primary_key=True,
        comment='The role that can be requested'
    )
    requestable_by_role_id = Column(
        String, 
        primary_key=True,
        comment='Role that can request (use __NO_ROLE__ for users without any role)'
    )
    
    # Relationship to the role being requested
    role = relationship("AppRoleDb", foreign_keys=[role_id], backref="request_permissions")
    
    def __repr__(self):
        return f"<RoleRequestPermissionDb(role_id='{self.role_id}', requestable_by='{self.requestable_by_role_id}')>"


class RoleApprovalPermissionDb(Base):
    """Maps which roles can approve access requests for other roles."""
    __tablename__ = 'role_approval_permissions'

    role_id = Column(
        String, 
        ForeignKey('app_roles.id', ondelete='CASCADE'), 
        primary_key=True,
        comment='The role being requested'
    )
    approver_role_id = Column(
        String, 
        ForeignKey('app_roles.id', ondelete='CASCADE'), 
        primary_key=True,
        comment='Role that can approve the request'
    )
    
    # Relationships
    role = relationship("AppRoleDb", foreign_keys=[role_id], backref="approval_permissions")
    approver_role = relationship("AppRoleDb", foreign_keys=[approver_role_id])
    
    def __repr__(self):
        return f"<RoleApprovalPermissionDb(role_id='{self.role_id}', approver='{self.approver_role_id}')>"