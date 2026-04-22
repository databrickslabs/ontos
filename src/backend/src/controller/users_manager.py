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
            # Use users.list as users.get requires the Databricks user ID
            user_iterator = self._ws_client.users.list(filter=f'userName eq "{user_email}"')
            
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

            # Extract group names — always include user email as implicit group
            # so that role assigned_groups can match on email directly
            group_names: List[str] = []
            if databricks_user.groups:
                group_names = [group.display for group in databricks_user.groups if group.display]
                logger.info(f"Extracted groups for {user_email}: {group_names}")
            else:
                logger.info(f"No group information found for {user_email} in SDK response.")
            # Always add user email as implicit group for direct role assignment
            if user_email and user_email not in group_names:
                group_names.append(user_email)

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

            # Extract group names — always include user email as implicit group
            group_names: List[str] = []
            if databricks_user.groups:
                group_names = [group.display for group in databricks_user.groups if group.display]
                logger.info(f"Extracted groups for current user: {group_names}")
            else:
                logger.info("No group information found for current user in SDK response.")
            # Always add user email as implicit group for direct role assignment
            user_email_resolved = (databricks_user.emails[0].value if databricks_user.emails else databricks_user.user_name)
            if user_email_resolved and user_email_resolved not in group_names:
                group_names.append(user_email_resolved)

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
