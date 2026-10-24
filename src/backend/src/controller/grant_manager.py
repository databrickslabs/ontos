"""Grant Manager for direct Unity Catalog GRANT/REVOKE operations.

This manager handles direct mode delivery by applying access control
changes directly to Unity Catalog via the Databricks SDK.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.catalog import (
    Privilege,
    PrivilegeAssignment,
    SecurableType,
    PermissionsChange,
)

from src.common.config import Settings, get_settings
from src.common.logging import get_logger

logger = get_logger(__name__)


class GrantPrivilege(str, Enum):
    """Standard Unity Catalog privileges."""
    SELECT = "SELECT"
    MODIFY = "MODIFY"
    CREATE = "CREATE"
    USAGE = "USAGE"
    READ_FILES = "READ_FILES"
    WRITE_FILES = "WRITE_FILES"
    EXECUTE = "EXECUTE"
    CREATE_TABLE = "CREATE_TABLE"
    CREATE_VIEW = "CREATE_VIEW"
    CREATE_FUNCTION = "CREATE_FUNCTION"
    CREATE_MODEL = "CREATE_MODEL"
    CREATE_VOLUME = "CREATE_VOLUME"
    READ_VOLUME = "READ_VOLUME"
    WRITE_VOLUME = "WRITE_VOLUME"
    ALL_PRIVILEGES = "ALL_PRIVILEGES"


class SecurableObjectType(str, Enum):
    """Types of securable objects in Unity Catalog."""
    CATALOG = "catalog"
    SCHEMA = "schema"
    TABLE = "table"
    VIEW = "view"
    FUNCTION = "function"
    VOLUME = "volume"
    MODEL = "model"
    SHARE = "share"
    RECIPIENT = "recipient"
    PROVIDER = "provider"
    STORAGE_CREDENTIAL = "storage_credential"
    EXTERNAL_LOCATION = "external_location"


@dataclass
class GrantRequest:
    """Request to grant privileges."""
    principal: str  # User email, group name, or service principal
    principal_type: str  # "user", "group", "service_principal"
    privileges: List[str]  # List of privileges to grant
    securable_type: str  # Type of object
    securable_name: str  # Full name of the object (catalog.schema.table)
    

@dataclass
class GrantResult:
    """Result of a grant/revoke operation."""
    success: bool
    principal: str
    privileges: List[str]
    securable_name: str
    action: str  # "grant" or "revoke"
    message: Optional[str] = None
    error: Optional[str] = None
    dry_run: bool = False
    timestamp: Optional[datetime] = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.utcnow()
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "principal": self.principal,
            "privileges": self.privileges,
            "securable_name": self.securable_name,
            "action": self.action,
            "message": self.message,
            "error": self.error,
            "dry_run": self.dry_run,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
        }


class GrantManager:
    """Manager for Unity Catalog GRANT/REVOKE operations.
    
    Provides direct mode delivery by applying access control changes
    to Unity Catalog using the Databricks SDK.
    """
    
    def __init__(
        self,
        ws_client: Optional[WorkspaceClient] = None,
        settings: Optional[Settings] = None,
    ):
        """Initialize the grant manager.
        
        Args:
            ws_client: Databricks WorkspaceClient
            settings: Application settings
        """
        self._ws = ws_client
        self._settings = settings or get_settings()
    
    def set_workspace_client(self, ws_client: WorkspaceClient) -> None:
        """Set the workspace client."""
        self._ws = ws_client

    @property
    def workspace_client(self) -> Optional[WorkspaceClient]:
        return self._ws
    
    def _get_securable_type(self, type_str: str) -> SecurableType:
        """Convert string type to SDK SecurableType enum."""
        type_map = {
            "catalog": SecurableType.CATALOG,
            "schema": SecurableType.SCHEMA,
            "table": SecurableType.TABLE,
            "view": SecurableType.TABLE,  # Views use TABLE type
            "function": SecurableType.FUNCTION,
            "volume": SecurableType.VOLUME,
            "model": SecurableType.REGISTERED_MODEL,
            "share": SecurableType.SHARE,
            "recipient": SecurableType.RECIPIENT,
            "provider": SecurableType.PROVIDER,
            "storage_credential": SecurableType.STORAGE_CREDENTIAL,
            "external_location": SecurableType.EXTERNAL_LOCATION,
        }
        return type_map.get(type_str.lower(), SecurableType.TABLE)
    
    def _get_privileges(self, privilege_strs: List[str]) -> List[Privilege]:
        """Convert string privileges to SDK Privilege enum."""
        privileges = []
        for priv_str in privilege_strs:
            try:
                priv = Privilege(priv_str.upper())
                privileges.append(priv)
            except ValueError:
                logger.warning(f"Unknown privilege: {priv_str}")
        return privileges
    
    def apply_grant(
        self,
        data: Dict[str, Any],
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """Apply a GRANT operation.
        
        Args:
            data: Grant request data containing:
                - principal: The user/group/service principal
                - principal_type: Type of principal
                - privileges: List of privileges to grant
                - securable_type: Type of securable object
                - securable_name: Full name of the object
            dry_run: If True, only log what would be done
            
        Returns:
            Result dictionary with success status and details
        """
        if not self._ws:
            return {
                "success": False,
                "error": "Workspace client not available",
            }
        
        principal = data.get("principal")
        privileges = data.get("privileges", [])
        securable_type = data.get("securable_type", "table")
        securable_name = data.get("securable_name")
        
        if not all([principal, privileges, securable_name]):
            return {
                "success": False,
                "error": "Missing required fields: principal, privileges, securable_name",
            }
        
        logger.info(
            f"{'[DRY-RUN] ' if dry_run else ''}Granting {privileges} to {principal} "
            f"on {securable_type}:{securable_name}"
        )
        
        if dry_run:
            return {
                "success": True,
                "dry_run": True,
                "message": f"Would grant {privileges} to {principal} on {securable_name}",
                "principal": principal,
                "privileges": privileges,
                "securable_name": securable_name,
            }
        
        try:
            # Determine the securable type
            sdk_securable_type = self._get_securable_type(securable_type)
            
            # Build the permissions change
            changes = [
                PermissionsChange(
                    add=self._get_privileges(privileges),
                    principal=principal,
                )
            ]
            
            # Apply the grant using the grants API
            self._ws.grants.update(
                securable_type=sdk_securable_type,
                full_name=securable_name,
                changes=changes,
            )
            
            logger.info(f"Successfully granted {privileges} to {principal} on {securable_name}")
            
            return {
                "success": True,
                "message": f"Granted {privileges} to {principal} on {securable_name}",
                "principal": principal,
                "privileges": privileges,
                "securable_name": securable_name,
            }
            
        except Exception as e:
            logger.error(f"Failed to grant privileges: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "principal": principal,
                "privileges": privileges,
                "securable_name": securable_name,
            }
    
    def apply_revoke(
        self,
        data: Dict[str, Any],
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """Apply a REVOKE operation.
        
        Args:
            data: Revoke request data containing:
                - principal: The user/group/service principal
                - privileges: List of privileges to revoke (optional, revokes all if not specified)
                - securable_type: Type of securable object
                - securable_name: Full name of the object
            dry_run: If True, only log what would be done
            
        Returns:
            Result dictionary with success status and details
        """
        if not self._ws:
            return {
                "success": False,
                "error": "Workspace client not available",
            }
        
        principal = data.get("principal")
        privileges = data.get("privileges", [])
        securable_type = data.get("securable_type", "table")
        securable_name = data.get("securable_name")
        
        if not all([principal, securable_name]):
            return {
                "success": False,
                "error": "Missing required fields: principal, securable_name",
            }
        
        logger.info(
            f"{'[DRY-RUN] ' if dry_run else ''}Revoking {privileges or 'all'} from {principal} "
            f"on {securable_type}:{securable_name}"
        )
        
        if dry_run:
            return {
                "success": True,
                "dry_run": True,
                "message": f"Would revoke {privileges or 'all'} from {principal} on {securable_name}",
                "principal": principal,
                "privileges": privileges,
                "securable_name": securable_name,
            }
        
        try:
            # Determine the securable type
            sdk_securable_type = self._get_securable_type(securable_type)
            
            # If no specific privileges, get current privileges first
            if not privileges:
                try:
                    current = self._ws.grants.get(
                        securable_type=sdk_securable_type,
                        full_name=securable_name,
                    )
                    for assignment in current.privilege_assignments or []:
                        if assignment.principal == principal:
                            privileges = [p.value for p in (assignment.privileges or [])]
                            break
                except Exception:
                    pass
            
            if not privileges:
                return {
                    "success": True,
                    "message": f"No privileges to revoke from {principal} on {securable_name}",
                    "principal": principal,
                    "securable_name": securable_name,
                }
            
            # Build the permissions change
            changes = [
                PermissionsChange(
                    remove=self._get_privileges(privileges),
                    principal=principal,
                )
            ]
            
            # Apply the revoke using the grants API
            self._ws.grants.update(
                securable_type=sdk_securable_type,
                full_name=securable_name,
                changes=changes,
            )
            
            logger.info(f"Successfully revoked {privileges} from {principal} on {securable_name}")
            
            return {
                "success": True,
                "message": f"Revoked {privileges} from {principal} on {securable_name}",
                "principal": principal,
                "privileges": privileges,
                "securable_name": securable_name,
            }
            
        except Exception as e:
            logger.error(f"Failed to revoke privileges: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "principal": principal,
                "privileges": privileges,
                "securable_name": securable_name,
            }
    
    def get_grants(
        self,
        securable_type: str,
        securable_name: str,
    ) -> Dict[str, Any]:
        """Get current grants on an object.
        
        Args:
            securable_type: Type of securable object
            securable_name: Full name of the object
            
        Returns:
            Dictionary with grant information
        """
        if not self._ws:
            return {
                "success": False,
                "error": "Workspace client not available",
            }
        
        try:
            sdk_securable_type = self._get_securable_type(securable_type)
            
            result = self._ws.grants.get(
                securable_type=sdk_securable_type,
                full_name=securable_name,
            )
            
            grants = []
            for assignment in result.privilege_assignments or []:
                grants.append({
                    "principal": assignment.principal,
                    "privileges": [p.value for p in (assignment.privileges or [])],
                })
            
            return {
                "success": True,
                "securable_name": securable_name,
                "securable_type": securable_type,
                "grants": grants,
            }
            
        except Exception as e:
            logger.error(f"Failed to get grants: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
            }


# Global grant manager instance
_grant_manager: Optional[GrantManager] = None


def init_grant_manager(
    ws_client: Optional[WorkspaceClient] = None,
    settings: Optional[Settings] = None,
) -> GrantManager:
    """Initialize the global grant manager instance."""
    global _grant_manager
    _grant_manager = GrantManager(ws_client=ws_client, settings=settings)
    return _grant_manager


def get_grant_manager() -> GrantManager:
    """Get the global grant manager instance."""
    if not _grant_manager:
        raise RuntimeError("Grant manager not initialized")
    return _grant_manager

