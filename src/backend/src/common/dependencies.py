from typing import Optional, Annotated
from fastapi import Request, HTTPException, status, Depends
from sqlalchemy.orm import Session

# Import manager classes needed for Annotated types
from src.controller.settings_manager import SettingsManager
from src.controller.audit_manager import AuditManager
from src.controller.authorization_manager import AuthorizationManager # Needed for PermissionCheckerDep
from src.controller.users_manager import UsersManager # Needed for CurrentUserDep
# Import DataAssetReviewManager for Annotated type
from src.controller.data_asset_reviews_manager import DataAssetReviewManager
from src.controller.notifications_manager import NotificationsManager # Added
from src.controller.data_products_manager import DataProductsManager # Added for DataProductsManagerDep
from src.controller.data_domains_manager import DataDomainManager # Add import
from databricks.sdk import WorkspaceClient # Added for WorkspaceClientDep
# Import other managers
from src.controller.data_contracts_manager import DataContractsManager
from src.controller.semantic_models_manager import SemanticModelsManager
from src.controller.search_manager import SearchManager
from src.controller.tags_manager import TagsManager # Import TagsManager
from src.controller.workspace_manager import WorkspaceManager # Import WorkspaceManager
from src.controller.change_log_manager import ChangeLogManager # Import ChangeLogManager
from src.controller.assets_manager import AssetsManager
from src.controller.business_roles_manager import BusinessRolesManager
from src.controller.business_owners_manager import BusinessOwnersManager
from src.controller.delivery_methods_manager import DeliveryMethodsManager
from src.controller.ontology_generator_manager import OntologyGeneratorManager
from src.controller.directory_manager import DirectoryManager

# Import base dependencies
from src.common.database import get_session_factory # Import the factory function
from src.common.config import Settings
from src.models.users import UserInfo # Corrected import to UserInfo
from src.common.features import FeatureAccessLevel
from src.common.logging import get_logger

# Import the PermissionChecker class directly for use in require_permission
from src.common.authorization import PermissionChecker, get_user_details_from_sdk # Import checker and user getter
# Import manager getters from the new file
from src.common.manager_dependencies import (
    get_auth_manager,
    get_settings_manager,
    get_audit_manager,
    get_users_manager,
    get_data_asset_review_manager,
    get_notifications_manager,
    get_data_products_manager,
    get_data_domain_manager,
    get_data_contracts_manager,
    get_semantic_models_manager,
    get_search_manager,
    get_workspace_manager,
    get_change_log_manager,
    get_assets_manager,
    get_business_roles_manager,
    get_business_owners_manager,
    get_delivery_methods_manager,
    get_ontology_generator_manager,
    get_directory_manager,
)
# Import workspace client getter separately as it might be structured differently
from src.common.workspace_client import get_workspace_client_dependency  # Fixed to use proper wrapper

logger = get_logger(__name__)

# --- Core Dependency Functions --- #

# Database Session Dependency Provider (Function)
def get_db():
    session_factory = get_session_factory() # Get the factory
    if not session_factory:
        # This should ideally not happen if init_db ran successfully
        logger.critical("Database session factory not initialized!")
        raise HTTPException(status_code=503, detail="Database session factory not available.")
    
    db = session_factory() # Create a session instance from the factory
    try:
        yield db
        db.commit()  # Commit the transaction on successful completion of the request
    except Exception as e: # Catch all exceptions to ensure rollback
        logger.error(f"Error during database session for request, rolling back: {e}", exc_info=True)
        db.rollback()
        raise
    finally:
        db.close()

# Settings Dependency Provider (Function)
def get_settings(request: Request) -> Settings:
    # Assuming settings are loaded into app.state during startup
    settings = getattr(request.app.state, 'settings', None)
    if settings is None:
        logger.critical("Settings not found in application state!")
        # Depending on recovery strategy, you might load defaults or raise a critical error
        raise HTTPException(status_code=503, detail="Application settings not available.")
    return settings

# Current User Dependency Provider (Function)
# This relies on the actual implementation of get_user_details_from_sdk
async def get_current_user(user_details: UserInfo = Depends(get_user_details_from_sdk)) -> UserInfo:
    """Dependency to get the currently authenticated user's details."""
    # get_user_details_from_sdk handles fetching or mocking user details
    # We might want to adapt the User model or UserInfo based on what get_user_details_from_sdk returns
    # For now, assuming it returns a compatible UserInfo object or can be adapted.
    if not user_details:
        # This case should ideally be handled within get_user_details_from_sdk by raising HTTPException
        logger.error("get_user_details_from_sdk returned None, but should have raised HTTPException.")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to retrieve user information.")
    return user_details # Return the user object obtained from the underlying function

# --- Annotated Dependency Types --- #
# Define ALL Annotated types first

DBSessionDep = Annotated[Session, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
CurrentUserDep = Annotated[UserInfo, Depends(get_current_user)]
WorkspaceClientDep = Annotated[WorkspaceClient, Depends(get_workspace_client_dependency())]

# Manager Dependencies
SettingsManagerDep = Annotated[SettingsManager, Depends(get_settings_manager)]
AuditManagerDep = Annotated[AuditManager, Depends(get_audit_manager)]
UsersManagerDep = Annotated[UsersManager, Depends(get_users_manager)]
AuthorizationManagerDep = Annotated[AuthorizationManager, Depends(get_auth_manager)]
DataAssetReviewManagerDep = Annotated[DataAssetReviewManager, Depends(get_data_asset_review_manager)]
NotificationsManagerDep = Annotated[NotificationsManager, Depends(get_notifications_manager)]
DataProductsManagerDep = Annotated[DataProductsManager, Depends(get_data_products_manager)]
DataDomainManagerDep = Annotated[DataDomainManager, Depends(get_data_domain_manager)]
DataContractsManagerDep = Annotated[DataContractsManager, Depends(get_data_contracts_manager)]
SemanticModelsManagerDep = Annotated[SemanticModelsManager, Depends(get_semantic_models_manager)]
SearchManagerDep = Annotated[SearchManager, Depends(get_search_manager)]
WorkspaceManagerDep = Annotated[WorkspaceManager, Depends(get_workspace_manager)]
ChangeLogManagerDep = Annotated[ChangeLogManager, Depends(get_change_log_manager)]
AssetsManagerDep = Annotated[AssetsManager, Depends(get_assets_manager)]
BusinessRolesManagerDep = Annotated[BusinessRolesManager, Depends(get_business_roles_manager)]
BusinessOwnersManagerDep = Annotated[BusinessOwnersManager, Depends(get_business_owners_manager)]
DeliveryMethodsManagerDep = Annotated[DeliveryMethodsManager, Depends(get_delivery_methods_manager)]
OntologyGeneratorManagerDep = Annotated[OntologyGeneratorManager, Depends(get_ontology_generator_manager)]
DirectoryManagerDep = Annotated[DirectoryManager, Depends(get_directory_manager)]

# Permission Checker Dependency
PermissionCheckerDep = AuthorizationManagerDep 

# --- Permission Checking Function --- #
# Can now safely use Annotated types defined above
async def require_permission(
    feature: str,
    level: FeatureAccessLevel,
    user: CurrentUserDep, 
    auth_manager: AuthorizationManagerDep
):
    """
    FastAPI Dependency function to check if the current user has the required permission level
    for a given feature string ID using the AuthorizationManager.
    """
    # The PermissionChecker class itself is used directly in routes like Depends(PermissionChecker(...))
    # This function provides a simpler way if complex instantiation isn't needed.
    logger.debug(f"Checking permission via require_permission for feature '{feature}' (level: {level.value}) for user '{user.username}'")

    if not user.groups:
        logger.warning(f"User '{user.username}' has no groups. Denying access for '{feature}'.")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User has no assigned groups, cannot determine permissions."
        )

    try:
        effective_permissions = auth_manager.get_user_effective_permissions(user.groups)
        has_required_permission = auth_manager.has_permission(
            effective_permissions,
            feature,
            level
        )

        if not has_required_permission:
            user_level = effective_permissions.get(feature, FeatureAccessLevel.NONE)
            logger.warning(
                f"Permission denied via require_permission for user '{user.username}' "
                f"on feature '{feature}'. Required: '{level.value}', Found: '{user_level.value}'"
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions for feature '{feature}'. Required level: {level.value}."
            )

        logger.debug(f"Permission granted via require_permission for user '{user.username}' on feature '{feature}'")
        return

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error during permission check (require_permission) for feature '{feature}': {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error checking user permissions."
        )

# --- Helper to get current user for audit logging --- #
# Defined *after* CurrentUserDep is defined
async def get_current_user_details_for_audit(
    current_user: CurrentUserDep # Uses Annotated type defined above
) -> UserInfo:
    """
    Provides UserInfo specifically for audit logging purposes.
    """
    if not current_user:
        logger.error("Audit specific user fetch: CurrentUserDep resolved to None unexpectedly.")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not authenticated for audit log generation.")
    return current_user

# Define AuditCurrentUserDep *after* its dependency function is defined
AuditCurrentUserDep = Annotated[UserInfo, Depends(get_current_user_details_for_audit)]

# --- Other Manager Annotated Types (Add as needed) --- #
# (The example can be removed or kept)
# Example:
# from src.controller.data_products_manager import DataProductsManager
# from src.common.manager_dependencies import get_data_products_manager
# DataProductsManagerDep = Annotated[DataProductsManager, Depends(get_data_products_manager)]

# --- TagsManager Dependency ---
async def get_tags_manager(request: Request) -> TagsManager:
    manager = getattr(request.app.state, 'tags_manager', None)
    if manager is None:
        logger.critical("TagsManager instance not found in app.state!")
        raise HTTPException(status_code=500, detail="Tags service is not available.")
    if not isinstance(manager, TagsManager):
        logger.critical(f"Object found at app.state.tags_manager is not a TagsManager instance (Type: {type(manager)})!")
        raise HTTPException(status_code=500, detail="Tags service configuration error.")
    return manager

# Type alias for dependency injection
TagsManagerDep = Annotated[TagsManager, Depends(get_tags_manager)]

# --- Feature Flags Manager Dependency (Example if you add one) ---
# async def get_feature_flags_manager(request: Request) -> FeatureFlagsManager: