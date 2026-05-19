from typing import Optional, Dict, List

from fastapi import Depends, HTTPException, Request, status

from src.controller.authorization_manager import AuthorizationManager
from src.models.users import UserInfo
from src.common.features import FeatureAccessLevel
from src.common.logging import get_logger
from src.common.database import get_db
# Import dependencies for user info and managers (adjust paths if needed)
# Import dependencies needed for the moved function
from databricks.sdk.errors import NotFound
from src.controller.users_manager import UsersManager
from src.common.config import get_settings, Settings
# Import from the new dependencies file
from src.common.manager_dependencies import get_auth_manager, get_users_manager, get_settings_manager
from src.controller.settings_manager import SettingsManager
from src.models.settings import ApprovalEntity
# Import OBO workspace client for current user lookup
from src.common.workspace_client import get_obo_workspace_client

logger = get_logger(__name__)


def is_user_admin(user_groups: Optional[List[str]], settings: Settings) -> bool:
    """
    Check if user is an admin based on APP_ADMIN_DEFAULT_GROUPS configuration.
    
    Args:
        user_groups: List of user's groups
        settings: Application settings containing APP_ADMIN_DEFAULT_GROUPS
        
    Returns:
        True if user belongs to any admin group, False otherwise
    """
    if not user_groups:
        return False
    
    try:
        import json
        admin_groups_str = settings.APP_ADMIN_DEFAULT_GROUPS or '["admins"]'
        admin_groups = json.loads(admin_groups_str)
        
        # Check if any user group matches any admin group (case-insensitive)
        user_groups_lower = [g.lower() for g in user_groups]
        admin_groups_lower = [g.lower() for g in admin_groups]
        
        return any(ug in admin_groups_lower for ug in user_groups_lower)
    except (json.JSONDecodeError, Exception) as e:
        logger.error("Error parsing APP_ADMIN_DEFAULT_GROUPS: %s", e)
        # Fallback to simple check
        return "admins" in [g.lower() for g in user_groups]


async def is_user_feature_admin(
    user_email: Optional[str],
    user_groups: Optional[List[str]],
    feature_id: str,
    request: Request,
) -> bool:
    """Return True if the user has admin-level rights for the given feature.

    Distinct from :func:`is_user_admin`, which only checks workspace-group
    membership (``APP_ADMIN_DEFAULT_GROUPS``). This helper also consults the
    Ontos role system: a user whose effective permissions include
    ``FeatureAccessLevel.ADMIN`` on ``feature_id`` is considered admin for
    cascade-bypass purposes — even when their workspace groups don't include
    the literal ``admins`` group.

    Use this when deciding whether a user should bypass ownership scoping
    on a specific feature (e.g., "should this user see all data products?").
    It mirrors the resolution used by :func:`enforce_feature_permission`
    (team-role override → applied-role override → group-based merge) so the
    bypass stays consistent with whatever role the user is currently acting
    under.

    Resolution failures fall back to the workspace-admin check only — i.e.,
    a transient DB error never flips a non-admin into admin.

    Args:
        user_email: Caller's email (matched against role ``assigned_groups``
            via the auth manager's email-as-group support).
        user_groups: Caller's workspace groups.
        feature_id: Feature identifier (e.g., ``"data-products"``).
        request: FastAPI request — used to reach ``auth_manager`` and
            ``settings_manager`` from ``request.app.state``.

    Returns:
        True if the user is admin via workspace group OR Ontos role.
    """
    workspace_admin = is_user_admin(user_groups or [], get_settings())
    if workspace_admin:
        return True
    if not user_email:
        return False
    try:
        auth_manager: Optional[AuthorizationManager] = getattr(
            request.app.state, "authorization_manager", None
        )
        settings_manager: Optional[SettingsManager] = getattr(
            request.app.state, "settings_manager", None
        )
        if auth_manager is None:
            return False

        team_role_override = await get_user_team_role_overrides(
            user_email, user_groups or [], request
        )

        applied_role_id: Optional[str] = None
        if settings_manager is not None:
            try:
                applied_role_id = settings_manager.get_applied_role_override_for_user(
                    user_email
                )
            except Exception:
                applied_role_id = None

        if applied_role_id and settings_manager is not None:
            effective = settings_manager.get_feature_permissions_for_role_id(
                applied_role_id
            )
        else:
            effective = auth_manager.get_user_effective_permissions(
                user_groups or [], team_role_override
            )

        return effective.get(feature_id) == FeatureAccessLevel.ADMIN
    except Exception:
        logger.exception(
            "is_user_feature_admin: failed to resolve Ontos-role admin for user '%s' on feature '%s'; "
            "falling back to workspace-admin check (False)",
            user_email,
            feature_id,
        )
        return False


# Local Dev Mock User (keep here for the dependency function)
LOCAL_DEV_USER = UserInfo(
    email="localdev@example.com",  # Use example.com which is reserved for documentation
    username="localdev",
    user="Local Developer",
    ip="127.0.0.1",
    groups=["admins", "local-admins", "developers"] # Added 'admins' for testing
)

async def get_user_details_from_sdk(
    request: Request,
    settings: Settings = Depends(get_settings),
    manager: UsersManager = Depends(get_users_manager)
) -> UserInfo:
    """
    Retrieves detailed user information via SDK using UsersManager, or mock data if local dev.
    
    For non-local environments, uses the OBO (On-Behalf-Of) client with current_user.me() API
    which doesn't require Workspace Admin permissions (unlike users.list).
    
    Falls back to get_user_details_by_email if OBO token is not available.
    """
    # Check for local development environment or explicit mock flag
    if settings.ENV.upper().startswith("LOCAL") or getattr(settings, "MOCK_USER_DETAILS", False):
        # Build mock user from env-var overrides if provided
        mock_email = settings.MOCK_USER_EMAIL or LOCAL_DEV_USER.email
        mock_username = settings.MOCK_USER_USERNAME or LOCAL_DEV_USER.username
        mock_name = settings.MOCK_USER_NAME or LOCAL_DEV_USER.user
        mock_ip = settings.MOCK_USER_IP or LOCAL_DEV_USER.ip
        groups_source = "default"
        mock_groups = LOCAL_DEV_USER.groups
        if settings.MOCK_USER_GROUPS:
            try:
                # Try JSON first (e.g. '["a","b"]')
                import json as _json
                parsed = _json.loads(settings.MOCK_USER_GROUPS)
                if isinstance(parsed, list) and all(isinstance(x, str) for x in parsed):
                    mock_groups = parsed
                    groups_source = "json"
                else:
                    raise ValueError("MOCK_USER_GROUPS JSON must be an array of strings")
            except Exception:
                # Fallback to comma-separated string
                csv = [g.strip() for g in settings.MOCK_USER_GROUPS.split(',') if g.strip()]
                if csv:
                    mock_groups = csv
                    groups_source = "csv"
        logger.info(
            f"Local/mock user mode: using overrides(email={mock_email}, username={mock_username}, user={mock_name}, ip={mock_ip}, groups_source={groups_source}, groups={mock_groups})"
        )
        return UserInfo(
            email=mock_email,
            username=mock_username,
            user=mock_name,
            ip=mock_ip,
            groups=mock_groups,
        )

    # Logic for non-local environments
    real_ip = request.headers.get("X-Real-Ip")

    # Try using OBO client with current_user.me() first (no admin permissions required)
    obo_token = request.headers.get('x-forwarded-access-token')
    # Diagnostic: surface which forwarded headers actually arrive from the
    # Databricks Apps proxy. Without these at INFO level we can't tell the
    # difference between "OBO header missing" vs "OBO header present but empty"
    # vs "scope not granted" when triaging a deployed app.
    fwd_email = request.headers.get('X-Forwarded-Email')
    fwd_user = request.headers.get('X-Forwarded-User')
    logger.info(
        "auth.headers: x-forwarded-access-token=%s, X-Forwarded-Email=%s, X-Forwarded-User=%s",
        "present" if obo_token else "MISSING",
        fwd_email or "<none>",
        fwd_user or "<none>",
    )
    if obo_token:
        logger.info("Using OBO token with current_user.me() for user lookup (no admin permissions required).")
        try:
            obo_client = get_obo_workspace_client(request, settings)
            user_info_response = manager.get_current_user(obo_client=obo_client, real_ip=real_ip)
            return user_info_response
        except ValueError as e:
            logger.error("Configuration error using OBO client: %s", e)
            raise HTTPException(status_code=500, detail="Server configuration error")
        except RuntimeError as e:
            logger.error("Runtime error from get_current_user", exc_info=True)
            raise HTTPException(status_code=500, detail="Failed to retrieve user details")
        except Exception as e:
            logger.error("Unexpected error in get_current_user: %s", e, exc_info=True)
            raise HTTPException(status_code=500, detail="An unexpected error occurred")

    # Fallback: Use get_user_details_by_email if no OBO token (requires admin permissions)
    logger.info(
        "No OBO token (x-forwarded-access-token) on request, falling back to SP-scoped get_user_details_by_email. "
        "If groups appear missing in the response, the app's user_authorization scopes likely need iam.current-user:read."
    )
    user_email = request.headers.get("X-Forwarded-Email")
    if not user_email:
        user_email = request.headers.get("X-Forwarded-User")

    if not user_email:
        logger.error("Could not find user email in request headers (X-Forwarded-Email or X-Forwarded-User) for SDK lookup.")
        raise HTTPException(status_code=400, detail="User email not found in request headers for SDK lookup.")

    try:
        # Call the manager method (fallback, requires admin permissions)
        user_info_response = manager.get_user_details_by_email(user_email=user_email, real_ip=real_ip)
        return user_info_response

    except NotFound as e:
        logger.warning("User not found via manager for email %s: %s", user_email, e)
        raise HTTPException(status_code=404, detail="User not found")
    except ValueError as e:
        logger.error("Configuration error in UsersManager: %s", e)
        raise HTTPException(status_code=500, detail="Server configuration error")
    except RuntimeError as e:
        logger.error("Runtime error from UsersManager for %s", user_email, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve user details")
    except HTTPException:
        raise # Re-raise potential 400 from header check above
    except Exception as e:
        logger.error("Unexpected error in get_user_details_from_sdk dependency for %s", user_email, exc_info=True)
        raise HTTPException(status_code=500, detail="An unexpected error occurred")


async def get_user_groups(user_email: str) -> List[str]:
    """Get user groups for the given user email."""
    # Get settings directly instead of using dependency injection
    settings = get_settings()

    if settings.ENV.upper().startswith("LOCAL") or getattr(settings, "MOCK_USER_DETAILS", False):
        # Return mock groups for local/mock development honoring overrides
        if settings.MOCK_USER_GROUPS:
            try:
                import json as _json
                parsed = _json.loads(settings.MOCK_USER_GROUPS)
                if isinstance(parsed, list) and all(isinstance(x, str) for x in parsed):
                    return parsed
            except Exception:
                csv = [g.strip() for g in settings.MOCK_USER_GROUPS.split(',') if g.strip()]
                if csv:
                    return csv
        return LOCAL_DEV_USER.groups

    # In production, you would get groups from the user details
    # For now, returning empty list as fallback
    return []


async def get_user_team_role_overrides(user_identifier: str, user_groups: List[str], request: Request) -> Optional[str]:
    """Get the highest team role override for a user."""
    try:
        # Get teams manager from app state
        teams_manager = getattr(request.app.state, 'teams_manager', None)
        if not teams_manager:
            logger.debug("Teams manager not available in app state")
            return None

        # Get database session
        db = next(get_db())
        try:
            # Get teams where user is a member
            user_teams = teams_manager.get_teams_for_user(db, user_identifier)

            # Normalize user groups to lowercase for case-insensitive matching
            user_groups_lower = set(g.lower() for g in user_groups)

            # Collect all role overrides for this user across teams
            role_overrides = []
            for team in user_teams:
                for member in team.members:
                    if member.member_identifier == user_identifier and member.app_role_override:
                        role_overrides.append(member.app_role_override)

            # Also check group memberships (case-insensitive)
            for team in user_teams:
                for member in team.members:
                    if member.member_identifier.lower() in user_groups_lower and member.app_role_override:
                        role_overrides.append(member.app_role_override)

            if not role_overrides:
                return None

            # Return the highest role override (assuming role names have hierarchical order)
            # For now, just return the first one found - in practice you'd need proper role hierarchy
            logger.debug("Found team role overrides for user %s: %s", user_identifier, role_overrides)
            return role_overrides[0]

        finally:
            db.close()
    except Exception as e:
        logger.warning("Error checking team role overrides for user %s: %s", user_identifier, e)
        return None


async def check_user_project_access(user_identifier: str, user_groups: List[str], project_id: str, request: Request) -> bool:
    """Check if a user has access to a specific project."""
    try:
        # Get projects manager from app state
        projects_manager = getattr(request.app.state, 'projects_manager', None)
        if not projects_manager:
            logger.debug("Projects manager not available in app state")
            return False

        # Get database session
        db = next(get_db())
        try:
            # Check if user has access to the project
            return projects_manager.check_user_project_access(db, user_identifier, user_groups, project_id)
        finally:
            db.close()
    except Exception as e:
        logger.warning("Error checking project access for user %s to project %s: %s", user_identifier, project_id, e)
        return False


class ProjectAccessChecker:
    """FastAPI Dependency to check user access to a specific project."""
    def __init__(self, project_id_param: str = "project_id"):
        self.project_id_param = project_id_param
        logger.debug("ProjectAccessChecker initialized for parameter '%s'", self.project_id_param)

    async def __call__(
        self,
        request: Request,
        user_details: UserInfo = Depends(get_user_details_from_sdk)
    ):
        """Performs the project access check when the dependency is called."""
        # Extract project_id from path parameters
        project_id = request.path_params.get(self.project_id_param)
        if not project_id:
            logger.warning("Project ID parameter '%s' not found in request", self.project_id_param)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Project ID parameter '{self.project_id_param}' not found"
            )

        logger.debug("Checking project access for user '%s' to project '%s'", user_details.email, project_id)

        user_groups = user_details.groups or []
        has_access = await check_user_project_access(
            user_details.email,
            user_groups,
            project_id,
            request
        )

        if not has_access:
            logger.warning(
                f"Project access denied for user '{user_details.email}' to project '{project_id}'"
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied to project '{project_id}'"
            )

        logger.debug("Project access granted for user '%s' to project '%s'", user_details.email, project_id)
        return


async def enforce_feature_permission(
    feature_id: str,
    required_level: FeatureAccessLevel,
    user_details: UserInfo,
    request: Request,
) -> None:
    """Programmatic equivalent of :class:`PermissionChecker` for use inside
    route handler bodies.

    Raises ``HTTPException(403)`` if the user lacks the required permission
    level for the given feature. Reuses the same precedence as
    ``PermissionChecker.__call__``: explicit role override > team role
    override > group-based effective permissions.

    Exists because some endpoints (notably the wizard endpoints) need to
    dispatch the feature_id at request time based on path/body data, which
    can't be done with FastAPI's ``Depends`` (resolved before the handler
    runs).
    """
    if not user_details.groups:
        logger.warning(
            "User '%s' has no groups. Denying access for '%s'",
            user_details.user or user_details.email,
            feature_id,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User has no assigned groups, cannot determine permissions.",
        )

    auth_manager: AuthorizationManager = getattr(request.app.state, "authorization_manager", None)
    if not auth_manager:
        logger.critical("AuthorizationManager not found in app state during enforce_feature_permission")
        raise HTTPException(status_code=503, detail="Authorization service not configured.")

    try:
        # Mirror PermissionChecker.__call__: team override → applied role override → group merge.
        team_role_override = await get_user_team_role_overrides(
            user_details.email,
            user_details.groups or [],
            request,
        )

        applied_role_id = None
        settings_manager = getattr(request.app.state, "settings_manager", None)
        try:
            if settings_manager:
                applied_role_id = settings_manager.get_applied_role_override_for_user(user_details.email)
        except Exception:
            applied_role_id = None

        if applied_role_id and settings_manager:
            effective_permissions = settings_manager.get_feature_permissions_for_role_id(applied_role_id)
        else:
            effective_permissions = auth_manager.get_user_effective_permissions(
                user_details.groups,
                team_role_override,
            )

        if not auth_manager.has_permission(effective_permissions, feature_id, required_level):
            user_level = effective_permissions.get(feature_id, FeatureAccessLevel.NONE)
            logger.warning(
                "Permission denied for user '%s' on feature '%s'. Required: '%s', Found: '%s'",
                user_details.user or user_details.email,
                feature_id,
                required_level.value,
                user_level.value,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions for feature '{feature_id}'. Required level: {required_level.value}.",
            )
    except HTTPException:
        raise
    except Exception:
        logger.error(
            "Unexpected error during enforce_feature_permission for feature '%s'",
            feature_id,
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error checking user permissions.",
        )


class PermissionChecker:
    """FastAPI Dependency to check user permissions for a feature."""
    def __init__(self, feature_id: str, required_level: FeatureAccessLevel):
        self.feature_id = feature_id
        self.required_level = required_level
        logger.debug("PermissionChecker initialized for feature '%s' requiring level '%s'", self.feature_id, self.required_level.value)

    async def __call__(
        self,
        request: Request, # Inject request to potentially access app state
        user_details: UserInfo = Depends(get_user_details_from_sdk), # Now uses local function
        auth_manager: AuthorizationManager = Depends(get_auth_manager)
    ):
        """Performs the permission check when the dependency is called."""
        logger.debug("Checking permission for feature '%s' (level: '%s') for user '%s'", self.feature_id, self.required_level.value, user_details.user or user_details.email)

        if not user_details.groups:
            logger.warning("User '%s' has no groups. Denying access for '%s'", user_details.user or user_details.email, self.feature_id)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User has no assigned groups, cannot determine permissions."
            )

        try:
            # Check for team role overrides
            team_role_override = await get_user_team_role_overrides(
                user_details.email,
                user_details.groups or [],
                request
            )

            # Check if an explicit role override is applied for this user
            applied_role_id = None
            try:
                settings_manager = getattr(request.app.state, 'settings_manager', None)
                if settings_manager:
                    applied_role_id = settings_manager.get_applied_role_override_for_user(user_details.email)
            except Exception:
                applied_role_id = None

            if applied_role_id and settings_manager:
                # Build effective permissions directly from the selected role
                effective_permissions = settings_manager.get_feature_permissions_for_role_id(applied_role_id)
            else:
                effective_permissions = auth_manager.get_user_effective_permissions(
                    user_details.groups,
                    team_role_override
                )
            has_required_permission = auth_manager.has_permission(
                effective_permissions,
                self.feature_id,
                self.required_level
            )

            if not has_required_permission:
                user_level = effective_permissions.get(self.feature_id, FeatureAccessLevel.NONE)
                logger.warning(
                    f"Permission denied for user '{user_details.user or user_details.email}' "
                    f"on feature '{self.feature_id}'. Required: '{self.required_level.value}', Found: '{user_level.value}'"
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Insufficient permissions for feature '{self.feature_id}'. Required level: {self.required_level.value}."
                )

            logger.debug("Permission granted for user '%s' on feature '%s'", user_details.user or user_details.email, self.feature_id)
            # If permission is granted, the dependency resolves successfully (returns None implicitly)
            return

        except HTTPException:
            raise # Re-raise exceptions from dependencies (like 503 from get_auth_manager)
        except Exception as e:
            logger.error("Unexpected error during permission check for feature '%s'", self.feature_id, exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error checking user permissions."
            )

# --- Pre-configured Dependency Instances (Optional but convenient) ---
# You can create instances here for common permission levels

def require_admin(feature_id: str) -> PermissionChecker:
    return PermissionChecker(feature_id, FeatureAccessLevel.ADMIN)

def require_read_write(feature_id: str) -> PermissionChecker:
    return PermissionChecker(feature_id, FeatureAccessLevel.READ_WRITE)

def require_read_only(feature_id: str) -> PermissionChecker:
    return PermissionChecker(feature_id, FeatureAccessLevel.READ_ONLY)

# Example for a feature-specific check
def require_data_product_read() -> PermissionChecker:
    return PermissionChecker('data-products', FeatureAccessLevel.READ_ONLY)

# Project access convenience functions
def require_project_access(project_id_param: str = "project_id") -> ProjectAccessChecker:
    return ProjectAccessChecker(project_id_param) 


class ApprovalChecker:
    """FastAPI Dependency to check if the user has approval privilege for an entity.

    Example: ApprovalChecker(ApprovalEntity.CONTRACTS) or ApprovalChecker('CONTRACTS')
    """
    def __init__(self, entity: ApprovalEntity | str):
        self.entity = ApprovalEntity(entity) if not isinstance(entity, ApprovalEntity) else entity
        logger.debug("ApprovalChecker initialized for entity '%s'", self.entity.value)

    async def __call__(
        self,
        request: Request,
        user_details: UserInfo = Depends(get_user_details_from_sdk),
        settings_manager: SettingsManager = Depends(get_settings_manager)
    ):
        try:
            # If a role override is applied, use it
            applied_role_id = settings_manager.get_applied_role_override_for_user(user_details.email)
            approval = False
            if applied_role_id:
                role = settings_manager.get_app_role(applied_role_id)
                ap = (role.approval_privileges or {}) if role else {}
                approval = bool(ap.get(self.entity, False))
            else:
                # Union across roles assigned to user's groups
                # Normalize to lowercase for case-insensitive matching
                user_groups = set(g.lower() for g in (user_details.groups or []))
                roles = settings_manager.list_app_roles()
                ap_union: dict[ApprovalEntity, bool] = {}
                for role in roles:
                    try:
                        # Normalize role groups to lowercase for case-insensitive matching
                        role_groups = set(g.lower() for g in (role.assigned_groups or []))
                        if not role_groups.intersection(user_groups):
                            continue
                        for k, v in (role.approval_privileges or {}).items():
                            ap_union[ApprovalEntity(k)] = ap_union.get(ApprovalEntity(k), False) or bool(v)
                    except Exception:
                        continue
                approval = bool(ap_union.get(self.entity, False))

            if not approval:
                logger.warning(
                    f"Approval denied for user '{user_details.user or user_details.email}' on entity '{self.entity.value}'"
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Insufficient approval privilege for '{self.entity.value}'."
                )
            return
        except HTTPException:
            raise
        except Exception as e:
            logger.error("Unexpected error during approval check for '%s'", self.entity.value, exc_info=True)
            raise HTTPException(status_code=500, detail="Error checking approval privileges")