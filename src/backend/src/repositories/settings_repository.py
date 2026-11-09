import json
from typing import Any, Dict, Optional, Union, List
from uuid import UUID # Import UUID

from sqlalchemy.orm import Session
from sqlalchemy import func
from uuid import uuid4

from src.common.repository import CRUDBase
from src.db_models.settings import AppRoleDb, RoleRequestPermissionDb, RoleApprovalPermissionDb, NO_ROLE_SENTINEL
from src.models.settings import AppRole as AppRoleApi, AppRoleCreate, AppRoleUpdate
from src.common.logging import get_logger

logger = get_logger(__name__)

# Define Pydantic models for create/update if they differ
AppRoleCreate = AppRoleApi
AppRoleUpdate = AppRoleApi

class AppRoleRepository(CRUDBase[AppRoleDb, AppRoleCreate, AppRoleUpdate]):
    """Repository for AppRole CRUD operations."""

    def create(self, db: Session, *, obj_in: AppRoleCreate) -> AppRoleDb:
        """Creates an AppRole, serializing JSON fields."""
        # Remove exclude_unset=True to ensure all fields are included
        db_obj_data = obj_in.model_dump() 
        # Remove fields that are stored in separate tables (role hierarchy)
        db_obj_data.pop('requestable_by_roles', None)
        db_obj_data.pop('approver_roles', None)
        # Serialize complex fields
        # Make sure assigned_groups and feature_permissions exist on obj_in
        db_obj_data['assigned_groups'] = json.dumps(getattr(obj_in, 'assigned_groups', []))
        # assigned_users is parallel to assigned_groups (normalized by Pydantic validator)
        db_obj_data['assigned_users'] = json.dumps(getattr(obj_in, 'assigned_users', []) or [])
        permissions_dict = getattr(obj_in, 'feature_permissions', {})
        db_obj_data['feature_permissions'] = json.dumps(
            {k: v.value for k, v in permissions_dict.items()} # Save enum values
        )
        # Home sections stored as list of strings
        home_sections_list = getattr(obj_in, 'home_sections', [])
        db_obj_data['home_sections'] = json.dumps(home_sections_list)
        # Approval privileges stored as dict of booleans
        approval_privs = getattr(obj_in, 'approval_privileges', {}) or {}
        # Keys are enums or strings; normalize to strings
        approval_privs_str = { (k.value if hasattr(k, 'value') else str(k)): bool(v) for k, v in approval_privs.items() }
        db_obj_data['approval_privileges'] = json.dumps(approval_privs_str)
        # Deployment policy stored as JSON
        deployment_policy = getattr(obj_in, 'deployment_policy', None)
        if deployment_policy:
            # If it's a Pydantic model, convert to dict; otherwise assume it's already a dict
            if hasattr(deployment_policy, 'model_dump'):
                db_obj_data['deployment_policy'] = json.dumps(deployment_policy.model_dump())
            else:
                db_obj_data['deployment_policy'] = json.dumps(deployment_policy)
        else:
            db_obj_data['deployment_policy'] = None
        db_obj = self.model(**db_obj_data)
        db.add(db_obj)
        db.flush() # Use flush instead of commit within repository method
        db.refresh(db_obj)
        logger.info(f"Created AppRoleDb with id: {db_obj.id}")
        return db_obj

    def update(self, db: Session, *, db_obj: AppRoleDb, obj_in: Union[AppRoleUpdate, Dict[str, Any]]) -> AppRoleDb:
        """Updates an AppRole, serializing JSON fields."""
        if isinstance(obj_in, dict):
            update_data = obj_in
        else:
            update_data = obj_in.model_dump(exclude_unset=True)

        # Remove fields that are stored in separate tables (role hierarchy)
        update_data.pop('requestable_by_roles', None)
        update_data.pop('approver_roles', None)

        # Serialize complex fields if they are present in the update data
        if 'assigned_groups' in update_data and update_data['assigned_groups'] is not None:
            update_data['assigned_groups'] = json.dumps(update_data['assigned_groups'])
        if 'assigned_users' in update_data and update_data['assigned_users'] is not None:
            update_data['assigned_users'] = json.dumps(update_data['assigned_users'])
        if 'feature_permissions' in update_data and update_data['feature_permissions'] is not None:
            perm_dict = update_data['feature_permissions']
            update_data['feature_permissions'] = json.dumps(
                 {k: (v.value if hasattr(v, 'value') else v) for k, v in perm_dict.items()}
            )
        if 'home_sections' in update_data and update_data['home_sections'] is not None:
            update_data['home_sections'] = json.dumps(update_data['home_sections'])
        if 'approval_privileges' in update_data and update_data['approval_privileges'] is not None:
            ap = update_data['approval_privileges'] or {}
            ap_norm = { (k.value if hasattr(k, 'value') else str(k)): bool(v) for k, v in ap.items() }
            update_data['approval_privileges'] = json.dumps(ap_norm)
        if 'deployment_policy' in update_data:
            dp = update_data['deployment_policy']
            if dp is not None:
                # If it's a Pydantic model, convert to dict; otherwise assume it's already a dict
                if hasattr(dp, 'model_dump'):
                    update_data['deployment_policy'] = json.dumps(dp.model_dump())
                else:
                    update_data['deployment_policy'] = json.dumps(dp)
            else:
                update_data['deployment_policy'] = None

        logger.debug(f"Updating AppRoleDb {db_obj.id} with data: {update_data}")
        # Use the base class update method which handles attribute setting
        updated_db_obj = super().update(db, db_obj=db_obj, obj_in=update_data)
        logger.info(f"Updated AppRoleDb with id: {updated_db_obj.id}")
        return updated_db_obj

    def get_by_name(self, db: Session, *, name: str) -> Optional[AppRoleDb]:
        """Retrieves an AppRole by its name."""
        return db.query(self.model).filter(self.model.name == name).first()

    def get_roles_count(self, db: Session) -> int:
        """Returns the total number of AppRole records in the database."""
        count = db.query(func.count(self.model.id)).scalar()
        return count or 0 # Return 0 if count is None

    def get_all_roles(self, db: Session) -> List[AppRoleDb]:
        """Retrieves all AppRole records from the database."""
        logger.debug("Retrieving all roles from the database.")
        return self.get_multi(db=db) # Use the inherited get_multi

    # get and get_multi are inherited from CRUDBase and should work directly


# Create singleton instance of the repository
app_role_repo = AppRoleRepository(AppRoleDb)


class RoleHierarchyRepository:
    """Repository for role request and approval permission operations."""

    # --- Request Permissions ---
    
    def get_requestable_by_roles(self, db: Session, role_id: str) -> List[str]:
        """Get list of role IDs that can request the given role.
        
        Returns list of role IDs. '__NO_ROLE__' indicates users without any role can request.
        """
        permissions = db.query(RoleRequestPermissionDb).filter(
            RoleRequestPermissionDb.role_id == role_id
        ).all()
        return [p.requestable_by_role_id for p in permissions]

    def set_requestable_by_roles(self, db: Session, role_id: str, requestable_by_role_ids: List[str]) -> None:
        """Set which roles can request the given role.
        
        Replaces all existing request permissions for this role.
        Use '__NO_ROLE__' in the list to allow users without any role to request.
        """
        # Delete existing permissions
        db.query(RoleRequestPermissionDb).filter(
            RoleRequestPermissionDb.role_id == role_id
        ).delete(synchronize_session=False)
        
        # Add new permissions
        for requestable_by_id in requestable_by_role_ids:
            permission = RoleRequestPermissionDb(
                role_id=role_id,
                requestable_by_role_id=requestable_by_id
            )
            db.add(permission)
        
        db.flush()
        logger.debug(f"Set requestable_by_roles for role {role_id}: {requestable_by_role_ids}")

    def get_roles_requestable_by_role(self, db: Session, requester_role_id: str) -> List[str]:
        """Get list of role IDs that the given role can request."""
        permissions = db.query(RoleRequestPermissionDb).filter(
            RoleRequestPermissionDb.requestable_by_role_id == requester_role_id
        ).all()
        return [p.role_id for p in permissions]

    def get_roles_requestable_by_no_role(self, db: Session) -> List[str]:
        """Get list of role IDs that users with no role can request."""
        permissions = db.query(RoleRequestPermissionDb).filter(
            RoleRequestPermissionDb.requestable_by_role_id == NO_ROLE_SENTINEL
        ).all()
        return [p.role_id for p in permissions]

    # --- Approval Permissions ---
    
    def get_approver_roles(self, db: Session, role_id: str) -> List[str]:
        """Get list of role IDs that can approve access to the given role."""
        permissions = db.query(RoleApprovalPermissionDb).filter(
            RoleApprovalPermissionDb.role_id == role_id
        ).all()
        return [p.approver_role_id for p in permissions]

    def set_approver_roles(self, db: Session, role_id: str, approver_role_ids: List[str]) -> None:
        """Set which roles can approve access to the given role.
        
        Replaces all existing approval permissions for this role.
        """
        # Delete existing permissions
        db.query(RoleApprovalPermissionDb).filter(
            RoleApprovalPermissionDb.role_id == role_id
        ).delete(synchronize_session=False)
        
        # Add new permissions
        for approver_id in approver_role_ids:
            permission = RoleApprovalPermissionDb(
                role_id=role_id,
                approver_role_id=approver_id
            )
            db.add(permission)
        
        db.flush()
        logger.debug(f"Set approver_roles for role {role_id}: {approver_role_ids}")

    def get_roles_approvable_by_role(self, db: Session, approver_role_id: str) -> List[str]:
        """Get list of role IDs that the given role can approve."""
        permissions = db.query(RoleApprovalPermissionDb).filter(
            RoleApprovalPermissionDb.approver_role_id == approver_role_id
        ).all()
        return [p.role_id for p in permissions]

    def delete_role_hierarchy_for_role(self, db: Session, role_id: str) -> None:
        """Delete all request and approval permissions involving a role.
        
        Note: This is typically handled by CASCADE on the FK, but can be called explicitly.
        """
        db.query(RoleRequestPermissionDb).filter(
            RoleRequestPermissionDb.role_id == role_id
        ).delete(synchronize_session=False)
        db.query(RoleRequestPermissionDb).filter(
            RoleRequestPermissionDb.requestable_by_role_id == role_id
        ).delete(synchronize_session=False)
        db.query(RoleApprovalPermissionDb).filter(
            RoleApprovalPermissionDb.role_id == role_id
        ).delete(synchronize_session=False)
        db.query(RoleApprovalPermissionDb).filter(
            RoleApprovalPermissionDb.approver_role_id == role_id
        ).delete(synchronize_session=False)
        db.flush()
        logger.debug(f"Deleted all role hierarchy permissions for role {role_id}")


# Create singleton instance of the role hierarchy repository
role_hierarchy_repo = RoleHierarchyRepository()