import json
from typing import Dict, List, Optional, Set
from collections import defaultdict

from src.controller.settings_manager import SettingsManager
from src.models.settings import AppRole
from src.common.features import FeatureAccessLevel, ACCESS_LEVEL_ORDER, get_feature_config
from src.common.logging import get_logger

logger = get_logger(__name__)

class AuthorizationManager:
    def __init__(self, settings_manager: SettingsManager):
        """Requires SettingsManager to access role configurations."""
        self._settings_manager = settings_manager

    def get_user_effective_permissions(self, user_groups: Optional[List[str]], team_role_override: Optional[str] = None) -> Dict[str, FeatureAccessLevel]:
        """
        Calculates the effective permission level for each feature based on the user's groups and team role overrides.
        Permissions are merged by taking the highest level granted by any matching role.
        Team role overrides take precedence over group-based roles.

        Args:
            user_groups: A list of group names the user belongs to.
            team_role_override: Optional team role that overrides group-based permissions.

        Returns:
            A dictionary mapping feature IDs to the highest granted FeatureAccessLevel.
        """
        if not user_groups:
            user_groups = []
            logger.warning("Received empty or None user_groups for permission calculation.") # Log if groups are empty
        else:
            logger.debug(f"Calculating effective permissions for user groups: {user_groups}") # Log received groups

        # Normalize user groups to lowercase for case-insensitive matching
        user_group_set = set(g.lower() for g in user_groups)
        effective_permissions: Dict[str, FeatureAccessLevel] = defaultdict(lambda: FeatureAccessLevel.NONE)

        # Log before fetching roles
        logger.debug("Fetching all application roles from SettingsManager...")
        all_roles = self._settings_manager.list_app_roles() # Fetches roles from DB via SettingsManager
        logger.debug(f"Fetched {len(all_roles)} roles total.")

        feature_config = get_feature_config()

        # If team role override is provided, prioritize it
        if team_role_override:
            logger.debug(f"Processing team role override: {team_role_override}")
            team_role = next((role for role in all_roles if role.name == team_role_override), None)
            if team_role:
                logger.debug(f"Found team role '{team_role_override}' in roles, applying as override")
                for feature_id, assigned_level in team_role.feature_permissions.items():
                    if feature_id in feature_config:
                        effective_permissions[feature_id] = assigned_level
                        logger.debug(f"Applied team role override for '{feature_id}': {assigned_level.value}")
                    else:
                        logger.warning(f"Team role '{team_role_override}' contains permission for unknown feature ID '{feature_id}'. Skipping.")

                # Return team role permissions (team override takes full precedence)
                for feature_id in feature_config:
                    if feature_id not in effective_permissions:
                        effective_permissions[feature_id] = FeatureAccessLevel.NONE

                final_perms_str = {k: v.value for k, v in effective_permissions.items()}
                logger.debug(f"Final permissions using team role override '{team_role_override}': {final_perms_str}")
                return dict(effective_permissions)
            else:
                logger.warning(f"Team role override '{team_role_override}' not found in available roles. Falling back to group-based permissions.")

        matching_roles = []
        logger.debug("Identifying matching roles based on group intersection...")
        for role in all_roles:
            # Normalize role groups to lowercase for case-insensitive matching
            role_assigned_groups_set = set(g.lower() for g in (role.assigned_groups or []))
            # Check for intersection
            if user_group_set.intersection(role_assigned_groups_set):
                matching_roles.append(role)
                logger.debug(f"  MATCH FOUND: User group(s) {list(user_group_set.intersection(role_assigned_groups_set))} match role: '{role.name}' (Assigned: {role.assigned_groups})")
            # else: 
            #    logger.debug(f"  NO MATCH: User groups {list(user_group_set)} vs Role '{role.name}' groups {list(role_assigned_groups_set)}")

        if not matching_roles:
            logger.warning(f"No matching roles found for user groups: {user_groups}. Returning NONE access for all features.")
            return {feat_id: FeatureAccessLevel.NONE for feat_id in feature_config}

        logger.debug(f"Merging permissions from {len(matching_roles)} matching roles...")
        # Merge permissions from matching roles
        for role in matching_roles:
            logger.debug(f"Processing permissions from role: '{role.name}'")
            for feature_id, assigned_level in role.feature_permissions.items():
                if feature_id not in feature_config:
                    logger.warning(f"Role '{role.name}' contains permission for unknown feature ID '{feature_id}'. Skipping.")
                    continue

                current_effective_level = effective_permissions[feature_id]
                # Compare levels using the defined order
                if ACCESS_LEVEL_ORDER[assigned_level] > ACCESS_LEVEL_ORDER[current_effective_level]:
                    effective_permissions[feature_id] = assigned_level
                    logger.debug(f"  Updated effective permission for '{feature_id}' to '{assigned_level.value}' (was '{current_effective_level.value}') from role '{role.name}'")
                # else:
                #    logger.debug(f"  Keeping existing permission for '{feature_id}' ('{current_effective_level.value}') - Role '{role.name}' level ('{assigned_level.value}') is not higher.")

        # Ensure all features have at least NONE permission defined
        for feature_id in feature_config:
            if feature_id not in effective_permissions:
                effective_permissions[feature_id] = FeatureAccessLevel.NONE

        # Log the final permissions
        final_perms_str = {k: v.value for k, v in effective_permissions.items()}
        logger.debug(f"Final calculated effective permissions: {final_perms_str}")
        return dict(effective_permissions)

    def has_permission(self, effective_permissions: Dict[str, FeatureAccessLevel], feature_id: str, required_level: FeatureAccessLevel) -> bool:
        """
        Checks if the user's effective permissions meet the required level for a specific feature.

        Args:
            effective_permissions: The user's calculated effective permissions.
            feature_id: The ID of the feature to check.
            required_level: The minimum FeatureAccessLevel required.

        Returns:
            True if the user has sufficient permission, False otherwise.
        """
        user_level = effective_permissions.get(feature_id, FeatureAccessLevel.NONE)
        has_perm = ACCESS_LEVEL_ORDER[user_level] >= ACCESS_LEVEL_ORDER[required_level]
        logger.debug(f"Permission check for feature '{feature_id}': Required='{required_level.value}', User has='{user_level.value}'. Granted: {has_perm}")
        return has_perm

    def is_user_ontos_admin(self, user_groups: Optional[List[str]]) -> bool:
        """Return True iff the user belongs to any AppRole flagged ``is_admin=True``.

        Membership is determined by case-insensitive intersection between the
        user's workspace groups and the role's ``assigned_groups``. This is the
        canonical "Ontos admin" check used to gate admin-only capabilities such
        as the role switcher (impersonation), the alpha-features toggle, MCP
        token management, and the unrestricted view of ``/api/settings/roles``.

        It is intentionally decoupled from ``settings:ADMIN``: a user may
        administer Settings without being an Ontos admin, and vice versa.

        Args:
            user_groups: Caller's workspace groups (from SDK or identity headers).

        Returns:
            True if any role with ``is_admin=True`` has an assigned group that
            matches one of the user's groups; False otherwise (including the
            empty-groups case).
        """
        if not user_groups:
            return False

        user_group_set = {(g or '').lower() for g in user_groups}
        if not user_group_set:
            return False

        try:
            all_roles = self._settings_manager.list_app_roles()
        except Exception:
            logger.exception("is_user_ontos_admin: failed to load app roles; denying admin")
            return False

        for role in all_roles:
            if not getattr(role, 'is_admin', False):
                continue
            role_groups = {(g or '').lower() for g in (role.assigned_groups or [])}
            if role_groups and role_groups.intersection(user_group_set):
                return True
        return False

    def get_user_effective_role_ids(
        self,
        user_groups: Optional[List[str]],
        applied_role_override_id: Optional[str] = None,
    ) -> Set[str]:
        """Return the set of AppRole UUIDs the viewer currently holds.

        Resolution order (mirrors ``get_user_effective_permissions``):
        1. If *applied_role_override_id* is set, the viewer is pinned to exactly
           that one role (same as the impersonation override path).
        2. Otherwise, every AppRole whose ``assigned_groups`` intersects the
           viewer's *user_groups* is included (case-insensitive).

        Args:
            user_groups: Workspace/IdP groups for the viewing user.
            applied_role_override_id: Optional role-ID override (from
                ``SettingsManager.get_applied_role_override_for_user``).

        Returns:
            A (possibly empty) set of role-ID strings.
        """
        all_roles = self._settings_manager.list_app_roles()

        if applied_role_override_id:
            # Pin to the overridden role only
            if any(str(r.id) == applied_role_override_id for r in all_roles):
                return {applied_role_override_id}
            logger.warning(
                "get_user_effective_role_ids: applied override '%s' not found in roles list",
                applied_role_override_id,
            )
            return set()

        if not user_groups:
            return set()

        user_group_set = set(g.lower() for g in user_groups)
        role_ids: Set[str] = set()
        for role in all_roles:
            role_groups = set(g.lower() for g in (role.assigned_groups or []))
            if user_group_set.intersection(role_groups):
                role_ids.add(str(role.id))
        return role_ids
