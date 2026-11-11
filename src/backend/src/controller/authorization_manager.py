import json
from typing import Dict, List, Optional, Sequence, Set, Union
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

    def get_user_effective_permissions(
        self,
        user_groups: Optional[List[str]],
        team_role_override: Optional[Union[str, Sequence[str]]] = None,
        user_email: Optional[str] = None,
    ) -> Dict[str, FeatureAccessLevel]:
        """
        Calculates the effective permission level for each feature based on the user's groups,
        their direct user-by-email assignment, and team role overrides.
        Permissions are merged by taking the highest level granted by any matching role.
        Team role overrides are roles like any other: they add to the group and email
        roles, per feature by the highest level, and never lower a level (#1245). An
        applied role override ("act as role") is resolved by the caller and replaces
        everything; see ``common.authorization.resolve_effective_permissions``.

        Role matching (#196/#760): a role matches the user if EITHER
          - the user's groups intersect with `role.assigned_groups` (case-insensitive), OR
          - the user's email is in `role.assigned_users` (case-insensitive).

        Args:
            user_groups: A list of group names the user belongs to.
            team_role_override: Optional team role name, or names, granted to the user by
                        team membership. Unknown names are ignored.
            user_email: Optional user email for direct-assignment matching against
                        `role.assigned_users`. When provided, OR-combined with group matching.

        Returns:
            A dictionary mapping feature IDs to the highest granted FeatureAccessLevel.
        """
        if not user_groups:
            user_groups = []

        # Normalize user groups to lowercase for case-insensitive matching
        user_group_set = set(g.lower() for g in user_groups)
        # Normalize the email for case-insensitive direct-assignment matching
        user_email_norm = (user_email or "").strip().lower() or None

        if not user_group_set and not user_email_norm:
            logger.warning("Received empty user_groups and no user_email for permission calculation.")
        else:
            logger.debug(f"Calculating effective permissions for groups={user_groups}, email={user_email_norm}")

        effective_permissions: Dict[str, FeatureAccessLevel] = defaultdict(lambda: FeatureAccessLevel.NONE)

        # Log before fetching roles
        logger.debug("Fetching all application roles from SettingsManager...")
        all_roles = self._settings_manager.list_app_roles() # Fetches roles from DB via SettingsManager
        logger.debug(f"Fetched {len(all_roles)} roles total.")

        feature_config = get_feature_config()

        if isinstance(team_role_override, str):
            team_role_names = [team_role_override]
        else:
            team_role_names = [n for n in (team_role_override or []) if n]

        matching_roles = []
        logger.debug("Identifying matching roles based on group intersection OR email assignment...")
        for role in all_roles:
            # Normalize role groups + assigned_users to lowercase for case-insensitive
            # matching. `(x or '')` guards against None entries in dirty data (a None
            # element would raise on .lower()).
            role_assigned_groups_set = set((g or '').lower() for g in (role.assigned_groups or []))
            role_assigned_users_set = set((u or '').lower() for u in (getattr(role, 'assigned_users', None) or []))

            group_match = bool(user_group_set.intersection(role_assigned_groups_set))
            email_match = bool(user_email_norm and user_email_norm in role_assigned_users_set)

            if group_match or email_match:
                matching_roles.append(role)
                reason = "groups+email" if (group_match and email_match) else ("groups" if group_match else "email")
                logger.debug(f"  MATCH FOUND ({reason}): role '{role.name}'")

        roles_by_name = {role.name: role for role in all_roles}
        for name in team_role_names:
            team_role = roles_by_name.get(name)
            if team_role is None:
                logger.warning("Team role override '%s' not found in available roles. Ignoring it.", name)
            elif team_role not in matching_roles:
                matching_roles.append(team_role)
                logger.debug("  MATCH FOUND (team): role '%s'", name)

        if not matching_roles:
            logger.warning(f"No matching roles for groups={user_groups}, email={user_email_norm}. Returning NONE access for all features.")
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

    def user_can_adopt_entity_ids(self, user_groups: Optional[List[str]]) -> bool:
        """Return True iff the user holds any role flagged ``can_adopt_entity_ids=True``.

        Mirrors :meth:`is_user_ontos_admin`: resolves roles by case-insensitive group
        intersection and returns True if any resolved role has the import adoption
        privilege. Gates the "Adopt IDs from file" import toggle so a contract/
        product writer cannot silently claim an arbitrary UUID (#853 review).
        """
        if not user_groups:
            return False
        user_group_set = {(g or '').lower() for g in user_groups}
        if not user_group_set:
            return False
        try:
            all_roles = self._settings_manager.list_app_roles()
        except Exception:
            logger.exception("user_can_adopt_entity_ids: failed to load app roles; denying")
            return False
        for role in all_roles:
            if not getattr(role, 'can_adopt_entity_ids', False):
                continue
            role_groups = {(g or '').lower() for g in (role.assigned_groups or [])}
            if role_groups and role_groups.intersection(user_group_set):
                return True
        return False

    def get_role_permissions_by_name(self, role_name: str) -> Optional[Dict[str, FeatureAccessLevel]]:
        """Feature levels the named role grants, or None if no role has that name."""
        role = next((r for r in self._settings_manager.list_app_roles() if r.name == role_name), None)
        if role is None:
            return None
        feature_config = get_feature_config()
        return {f: lvl for f, lvl in (role.feature_permissions or {}).items() if f in feature_config}

    def get_user_effective_role_ids(
        self,
        user_groups: Optional[List[str]],
        applied_role_override_id: Optional[str] = None,
        user_email: Optional[str] = None,
        team_role_names: Optional[Sequence[str]] = None,
    ) -> Set[str]:
        """Return the set of AppRole UUIDs the viewer currently holds.

        Resolution order (mirrors ``get_user_effective_permissions``):
        1. If *applied_role_override_id* is set, the viewer is pinned to exactly
           that one role (same as the impersonation override path).
        2. Otherwise, every AppRole whose ``assigned_groups`` intersects the
           viewer's *user_groups* OR whose ``assigned_users`` contains the
           viewer's *user_email* is included (case-insensitive) (#196/#760),
           plus the roles named in *team_role_names* (team overrides, #1245).

        Args:
            user_groups: Workspace/IdP groups for the viewing user.
            applied_role_override_id: Optional role-ID override (from
                ``SettingsManager.get_applied_role_override_for_user``).
            user_email: Optional email for direct-assignment matching.

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

        user_group_set = set(g.lower() for g in (user_groups or []))
        user_email_norm = (user_email or "").strip().lower() or None
        team_names = {n for n in (team_role_names or []) if n}
        if not user_group_set and not user_email_norm and not team_names:
            return set()

        role_ids: Set[str] = {str(r.id) for r in all_roles if r.name in team_names}
        for role in all_roles:
            # `(x or '')` guards against None entries in dirty data.
            role_groups = set((g or '').lower() for g in (role.assigned_groups or []))
            role_users = set((u or '').lower() for u in (getattr(role, 'assigned_users', None) or []))
            if user_group_set.intersection(role_groups) or (user_email_norm and user_email_norm in role_users):
                role_ids.add(str(role.id))
        return role_ids

    def get_user_hidden_nav_features(
        self,
        user_groups: Optional[List[str]],
        applied_role_override_id: Optional[str] = None,
        user_email: Optional[str] = None,
        team_role_names: Optional[Sequence[str]] = None,
    ) -> List[str]:
        """Feature ids the viewer's menus hide (sidebar, home quick actions, About) (#1325).

        Roles are resolved like the permissions (``get_user_effective_role_ids``: the
        applied role override pins one role, otherwise group or email matches). A
        feature is hidden only when every resolved role that grants it at least
        Read-only hides it, so one role that shows it is enough. A resolved
        ``is_admin`` role hides nothing. Visibility only: access is unchanged.
        """
        role_ids = self.get_user_effective_role_ids(
            user_groups,
            applied_role_override_id=applied_role_override_id,
            user_email=user_email,
            team_role_names=team_role_names,
        )
        if not role_ids:
            return []
        roles = [r for r in self._settings_manager.list_app_roles() if str(r.id) in role_ids]
        if not roles or any(getattr(r, 'is_admin', False) for r in roles):
            return []

        read_only = ACCESS_LEVEL_ORDER[FeatureAccessLevel.READ_ONLY]
        hidden: List[str] = []
        for feature_id in get_feature_config():
            granting = [
                r for r in roles
                if ACCESS_LEVEL_ORDER.get(
                    (r.feature_permissions or {}).get(feature_id, FeatureAccessLevel.NONE), 0
                ) >= read_only
            ]
            if granting and all(
                feature_id in (r.hidden_nav_features or []) for r in granting
            ):
                hidden.append(feature_id)
        return hidden
