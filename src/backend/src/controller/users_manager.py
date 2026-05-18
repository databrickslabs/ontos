from typing import Optional, List

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.iam import User as DatabricksUser
from databricks.sdk.errors import DatabricksError, NotFound

from src.models.users import UserInfo

from src.common.logging import get_logger
logger = get_logger(__name__)

class UsersManager:
    def __init__(self, ws_client: Optional[WorkspaceClient] = None):
        """
        Initializes the UsersManager.

        Args:
            ws_client: Optional Databricks WorkspaceClient for SDK operations.
        """
        self._ws_client = ws_client
        if not self._ws_client:
            logger.warning("WorkspaceClient was not provided to UsersManager. SDK operations will fail.")

    @staticmethod
    def _extract_group_displays(databricks_user: DatabricksUser) -> List[str]:
        """Extract display names from a SCIM user.groups list (skipping entries with no display)."""
        if not databricks_user or not databricks_user.groups:
            return []
        return [g.display for g in databricks_user.groups if getattr(g, "display", None)]

    @staticmethod
    def _resolve_scim_groups(
        client: WorkspaceClient,
        databricks_user: DatabricksUser,
        user_label: str,
    ) -> List[str]:
        """Resolve real workspace SCIM group memberships for a user.

        ``current_user.me()`` does not always populate ``groups`` (depends on
        token scope / SCIM attribute defaults). When the initial SCIM payload
        omits groups but we have a user id, re-fetch the full SCIM record via
        ``users.get(id)`` — that endpoint reliably returns the user's group
        memberships for the calling identity itself, even without admin
        permissions.

        Returns ``[]`` on any failure so the caller can fall back to the
        email-as-implicit-group behaviour.
        """
        groups = UsersManager._extract_group_displays(databricks_user)
        if groups:
            return groups

        user_id = getattr(databricks_user, "id", None)
        if not user_id:
            logger.debug("No user id on initial SCIM response for %s; cannot re-fetch groups.", user_label)
            return []

        try:
            full_user = client.users.get(user_id)
            groups = UsersManager._extract_group_displays(full_user)
            if groups:
                logger.info("Resolved %d SCIM group(s) for %s via users.get(id).", len(groups), user_label)
            else:
                logger.info("users.get(id) returned no groups for %s.", user_label)
            return groups
        except Exception as e:  # noqa: BLE001 — preserve fallback path for any SDK/permission error
            logger.warning(
                "Failed to re-fetch SCIM groups via users.get(id) for %s: %s. Falling back to implicit-group behaviour.",
                user_label,
                e,
            )
            return []

    def get_user_details_by_email(self, user_email: str, real_ip: Optional[str]) -> UserInfo:
        """
        Looks up a user by email using the Databricks SDK and maps the result
        to the UserInfo model, including group memberships.

        Args:
            user_email: The email address of the user to look up.
            real_ip: The real IP address from request headers (optional).

        Returns:
            A UserInfo object populated with details from the SDK.

        Raises:
            ValueError: If WorkspaceClient is not configured.
            NotFound: If the user is not found.
            RuntimeError: For other Databricks SDK errors or unexpected errors.
        """
        if not self._ws_client:
            logger.error("Cannot get user details: WorkspaceClient is not configured.")
            raise ValueError("WorkspaceClient is not configured in UsersManager.")

        logger.info(f"UsersManager: Attempting to find user details via SDK for email: {user_email}")
        try:
            # Use users.list as users.get requires the Databricks user ID.
            # Explicitly request the ``groups`` attribute — without this the
            # SCIM list endpoint can return user records with groups omitted,
            # which would force the email-as-implicit-group fallback even when
            # real groups are available.
            user_iterator = self._ws_client.users.list(
                filter=f'userName eq "{user_email}"',
                attributes="id,userName,displayName,emails,groups,active",
            )
            
            databricks_user: DatabricksUser | None = None
            try:
                databricks_user = next(user_iterator)
                try:
                    next(user_iterator)
                    logger.warning(f"UsersManager: Multiple users found via SDK for email {user_email}. Using the first one.")
                except StopIteration:
                    pass # Expected: only one user
            except StopIteration:
                logger.warning(f"UsersManager: User with email {user_email} not found in Databricks workspace via SDK.")
                raise NotFound(f"User with email {user_email} not found via SDK.") 

            if not databricks_user:
                raise NotFound(f"User with email {user_email} not found via SDK (post-iteration check).")

            logger.info(f"UsersManager: Successfully retrieved SDK user info for: {databricks_user.user_name}")

            # Resolve real workspace SCIM groups (with users.get(id) fallback if
            # the listing payload omitted them). Only fall back to
            # email-as-implicit-group when no real groups can be resolved.
            group_names: List[str] = self._resolve_scim_groups(
                self._ws_client, databricks_user, user_email
            )
            if not group_names and user_email:
                logger.info(
                    "Falling back to email-as-implicit-group for %s (no SCIM groups resolved).",
                    user_email,
                )
                group_names = [user_email]

            # Map DatabricksUser fields to UserInfo model
            user_info_response = UserInfo(
                email=(databricks_user.emails[0].value if databricks_user.emails else databricks_user.user_name),
                username=databricks_user.user_name,
                user=databricks_user.display_name,
                ip=real_ip, # Pass through the IP from the request
                groups=group_names # Add the extracted group names
            )
            return user_info_response

        except NotFound as e:
            logger.warning(f"NotFound error in UsersManager for {user_email}: {e}")
            raise e 
        except DatabricksError as e:
            logger.error(f"UsersManager: Databricks SDK error fetching user details for {user_email}: {e}", exc_info=True)
            raise RuntimeError(f"Databricks SDK error: {e}") from e
        except Exception as e:
            logger.error(f"UsersManager: Unexpected error fetching SDK user details for {user_email}: {e}", exc_info=True)
            raise RuntimeError(f"Unexpected error during SDK user lookup: {e}") from e

    def get_current_user(self, obo_client: WorkspaceClient, real_ip: Optional[str] = None) -> UserInfo:
        """
        Get the current user's details using the CurrentUserApi.
        
        This method uses the OBO (On-Behalf-Of) client's current_user.me() API,
        which returns the calling user's info without requiring Workspace Admin
        permissions (unlike users.list which requires elevated privileges).

        Args:
            obo_client: WorkspaceClient authenticated with the user's OBO token.
            real_ip: The real IP address from request headers (optional).

        Returns:
            A UserInfo object populated with details from the SDK.

        Raises:
            ValueError: If obo_client is not provided.
            RuntimeError: For Databricks SDK errors or unexpected errors.
        """
        if not obo_client:
            logger.error("Cannot get current user: OBO WorkspaceClient is not provided.")
            raise ValueError("OBO WorkspaceClient is required for get_current_user.")

        logger.info("UsersManager: Fetching current user details via current_user.me()")
        try:
            # Use current_user.me() which works without admin permissions
            databricks_user: DatabricksUser = obo_client.current_user.me()

            logger.info(f"UsersManager: Successfully retrieved current user info for: {databricks_user.user_name}")

            # Resolve real workspace SCIM groups. ``current_user.me()`` often returns
            # groups=[] depending on token scope; in that case re-fetch via
            # users.get(id) so the picker / permissions layer sees actual group
            # memberships rather than only the email-as-implicit-group fallback.
            user_email_resolved = (
                databricks_user.emails[0].value if databricks_user.emails else databricks_user.user_name
            )
            user_label = user_email_resolved or databricks_user.user_name or "<unknown>"
            group_names: List[str] = self._resolve_scim_groups(obo_client, databricks_user, user_label)

            # Fallback: if SCIM gave us nothing, preserve the legacy
            # email-as-implicit-group behaviour so role rules that match on
            # email continue to work in FEVM-style workspaces where SCIM
            # group reads aren't available.
            if not group_names and user_email_resolved:
                logger.info(
                    "Falling back to email-as-implicit-group for %s (no SCIM groups resolved).",
                    user_label,
                )
                group_names = [user_email_resolved]

            # Map DatabricksUser fields to UserInfo model
            user_info_response = UserInfo(
                email=user_email_resolved,
                username=databricks_user.user_name,
                user=databricks_user.display_name,
                ip=real_ip,
                groups=group_names
            )
            return user_info_response

        except DatabricksError as e:
            logger.error(f"UsersManager: Databricks SDK error fetching current user: {e}", exc_info=True)
            raise RuntimeError(f"Databricks SDK error: {e}") from e
        except Exception as e:
            logger.error(f"UsersManager: Unexpected error fetching current user: {e}", exc_info=True)
            raise RuntimeError(f"Unexpected error during current user lookup: {e}") from e
