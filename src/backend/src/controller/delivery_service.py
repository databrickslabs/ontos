"""Delivery Service for multi-mode change propagation.

This service orchestrates the delivery of governance changes across
multiple modes: Direct, Indirect, and Manual.

Updated: 2026-01-24 14:47
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from src.common.config import Settings, get_settings
from src.common.logging import get_logger

if TYPE_CHECKING:
    from src.common.git import GitService
    from src.controller.grant_manager import GrantManager
    from src.controller.notifications_manager import NotificationsManager

logger = get_logger(__name__)


class DeliveryMode(str, Enum):
    """Delivery modes for governance changes."""
    DIRECT = "direct"      # Apply changes directly via SDK
    INDIRECT = "indirect"  # Persist as YAML in Git repository
    MANUAL = "manual"      # Create notifications for manual action


class DeliveryChangeType(str, Enum):
    """Types of changes that can be delivered."""
    GRANT = "grant"              # Grant access to an asset
    REVOKE = "revoke"            # Revoke access from an asset
    TAG_ASSIGN = "tag_assign"    # Assign tag to an asset
    TAG_REMOVE = "tag_remove"    # Remove tag from an asset
    # Data Contracts
    CONTRACT_CREATE = "contract_create"  # Create data contract
    CONTRACT_UPDATE = "contract_update"  # Update data contract
    CONTRACT_DELETE = "contract_delete"  # Delete data contract
    # Data Products
    PRODUCT_CREATE = "product_create"    # Create data product
    PRODUCT_UPDATE = "product_update"    # Update data product
    PRODUCT_DELETE = "product_delete"    # Delete data product
    # Data Domains
    DOMAIN_CREATE = "domain_create"      # Create data domain
    DOMAIN_UPDATE = "domain_update"      # Update data domain
    DOMAIN_DELETE = "domain_delete"      # Delete data domain
    # Roles
    ROLE_CREATE = "role_create"          # Create role
    ROLE_UPDATE = "role_update"          # Update role permissions
    ROLE_DELETE = "role_delete"          # Delete role
    # Tags
    TAG_CREATE = "tag_create"            # Create tag namespace
    TAG_UPDATE = "tag_update"            # Update tag namespace
    TAG_DELETE = "tag_delete"            # Delete tag namespace
    # Access Policies
    POLICY_RELEASE = "policy_release"    # Apply a compiled Access Policy release (grants + revokes)


@dataclass
class DeliveryPayload:
    """Payload for a delivery change."""
    change_type: DeliveryChangeType
    entity_type: str  # e.g., "DataContract", "Dataset", "Tag"
    entity_id: str
    data: Dict[str, Any] = field(default_factory=dict)
    user: Optional[str] = None
    timestamp: Optional[datetime] = None
    # Optional DB session: lets Manual mode persist a real admin notification.
    db: Optional[Any] = field(default=None, repr=False, compare=False)
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.utcnow()


@dataclass
class DeliveryResult:
    """Result of a delivery operation."""
    success: bool
    mode: DeliveryMode
    change_type: DeliveryChangeType
    entity_type: str
    entity_id: str
    message: Optional[str] = None
    error: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "mode": self.mode.value,
            "change_type": self.change_type.value,
            "entity_type": self.entity_type,
            "entity_id": self.entity_id,
            "message": self.message,
            "error": self.error,
            "details": self.details,
        }


@dataclass
class DeliveryResults:
    """Aggregated results from all delivery modes."""
    results: List[DeliveryResult] = field(default_factory=list)
    
    @property
    def all_success(self) -> bool:
        return all(r.success for r in self.results)
    
    @property
    def any_success(self) -> bool:
        return any(r.success for r in self.results)
    
    @property
    def errors(self) -> List[str]:
        return [r.error for r in self.results if r.error]
    
    def add(self, result: DeliveryResult) -> None:
        self.results.append(result)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "all_success": self.all_success,
            "any_success": self.any_success,
            "results": [r.to_dict() for r in self.results],
            "errors": self.errors,
        }


class DeliveryService:
    """Service for orchestrating delivery of governance changes.
    
    Supports multiple delivery modes that can be active simultaneously:
    - Direct: Apply changes directly to Unity Catalog via SDK
    - Indirect: Persist changes as YAML files in Git repository
    - Manual: Create notifications for admin to apply changes manually
    """
    
    def __init__(
        self,
        settings: Optional[Settings] = None,
        git_service: Optional['GitService'] = None,
        grant_manager: Optional['GrantManager'] = None,
        notifications_manager: Optional['NotificationsManager'] = None,
    ):
        """Initialize the delivery service.
        
        Args:
            settings: Application settings
            git_service: Git service for indirect mode
            grant_manager: Grant manager for direct mode
            notifications_manager: Notifications manager for manual mode
        """
        self._settings = settings or get_settings()
        self._git_service = git_service
        self._grant_manager = grant_manager
        self._notifications_manager = notifications_manager
    
    def set_git_service(self, git_service: 'GitService') -> None:
        """Set the Git service for indirect mode."""
        self._git_service = git_service
    
    def set_grant_manager(self, grant_manager: 'GrantManager') -> None:
        """Set the grant manager for direct mode."""
        self._grant_manager = grant_manager

    @property
    def grant_manager(self) -> Optional['GrantManager']:
        """Grant manager for direct mode (also used to read live grants)."""
        return self._grant_manager
    
    def set_notifications_manager(self, notifications_manager: 'NotificationsManager') -> None:
        """Set the notifications manager for manual mode."""
        self._notifications_manager = notifications_manager
    
    def get_active_modes(self) -> List[DeliveryMode]:
        """Get list of currently active delivery modes.
        
        Reads fresh settings to pick up runtime changes.
        
        Returns:
            List of active DeliveryMode values
        """
        # Get fresh settings to pick up any changes made at runtime
        settings = get_settings()
        modes = []
        if settings.DELIVERY_MODE_DIRECT:
            modes.append(DeliveryMode.DIRECT)
        if settings.DELIVERY_MODE_INDIRECT:
            modes.append(DeliveryMode.INDIRECT)
        if settings.DELIVERY_MODE_MANUAL:
            modes.append(DeliveryMode.MANUAL)
        return modes
    
    def deliver(
        self,
        payload: DeliveryPayload,
        modes: Optional[List[DeliveryMode]] = None,
    ) -> DeliveryResults:
        """Deliver a change across all active modes.
        
        Args:
            payload: The change payload to deliver
            modes: Optional list of modes to use. If None, uses configured modes.
            
        Returns:
            DeliveryResults containing results from each mode
        """
        results = DeliveryResults()
        active_modes = modes if modes is not None else self.get_active_modes()
        
        if not active_modes:
            logger.warning("No delivery modes are active")
            return results
        
        logger.info(
            f"Delivering {payload.change_type.value} for {payload.entity_type}:{payload.entity_id} "
            f"via modes: {[m.value for m in active_modes]}"
        )
        
        for mode in active_modes:
            try:
                result = self._deliver_via_mode(mode, payload)
                results.add(result)
            except Exception as e:
                logger.error(f"Error delivering via {mode.value}: {e}", exc_info=True)
                results.add(DeliveryResult(
                    success=False,
                    mode=mode,
                    change_type=payload.change_type,
                    entity_type=payload.entity_type,
                    entity_id=payload.entity_id,
                    error=str(e)
                ))
        
        return results
    
    def _deliver_via_mode(
        self,
        mode: DeliveryMode,
        payload: DeliveryPayload,
    ) -> DeliveryResult:
        """Deliver a change via a specific mode.
        
        Args:
            mode: The delivery mode to use
            payload: The change payload
            
        Returns:
            DeliveryResult for this mode
        """
        if mode == DeliveryMode.DIRECT:
            return self._deliver_direct(payload)
        elif mode == DeliveryMode.INDIRECT:
            return self._deliver_indirect(payload)
        elif mode == DeliveryMode.MANUAL:
            return self._deliver_manual(payload)
        else:
            raise ValueError(f"Unknown delivery mode: {mode}")
    
    def _deliver_direct(self, payload: DeliveryPayload) -> DeliveryResult:
        """Deliver change directly to Unity Catalog.
        
        Args:
            payload: The change payload
            
        Returns:
            DeliveryResult
        """
        if not self._grant_manager:
            return DeliveryResult(
                success=False,
                mode=DeliveryMode.DIRECT,
                change_type=payload.change_type,
                entity_type=payload.entity_type,
                entity_id=payload.entity_id,
                error="Grant manager not available"
            )
        
        is_dry_run = self._settings.DELIVERY_DIRECT_DRY_RUN
        
        try:
            if payload.change_type == DeliveryChangeType.GRANT:
                result = self._grant_manager.apply_grant(
                    payload.data,
                    dry_run=is_dry_run
                )
            elif payload.change_type == DeliveryChangeType.REVOKE:
                result = self._grant_manager.apply_revoke(
                    payload.data,
                    dry_run=is_dry_run
                )
            elif payload.change_type == DeliveryChangeType.POLICY_RELEASE:
                result = self._apply_release(payload.data, is_dry_run)
            else:
                # Other change types not directly applicable
                return DeliveryResult(
                    success=True,
                    mode=DeliveryMode.DIRECT,
                    change_type=payload.change_type,
                    entity_type=payload.entity_type,
                    entity_id=payload.entity_id,
                    message="Change type not applicable for direct mode",
                    details={"skipped": True}
                )
            
            return DeliveryResult(
                success=result.get('success', True),
                mode=DeliveryMode.DIRECT,
                change_type=payload.change_type,
                entity_type=payload.entity_type,
                entity_id=payload.entity_id,
                message="Applied" if not is_dry_run else "Dry-run completed",
                details={"dry_run": is_dry_run, **result}
            )
            
        except Exception as e:
            logger.error(f"Direct delivery failed: {e}", exc_info=True)
            return DeliveryResult(
                success=False,
                mode=DeliveryMode.DIRECT,
                change_type=payload.change_type,
                entity_type=payload.entity_type,
                entity_id=payload.entity_id,
                error=str(e)
            )
    
    def _apply_release(self, data: Dict[str, Any], dry_run: bool) -> Dict[str, Any]:
        """Apply a policy release item by item: revokes first, then grants.

        ``data["revoke"]`` / ``data["grant"]`` hold ``GrantManager`` payloads; every
        revoke carries explicit privileges (an empty list would revoke everything).
        """
        items: List[Dict[str, Any]] = []
        for op, entries in (("revoke", data.get("revoke") or []), ("grant", data.get("grant") or [])):
            for entry in entries:
                if op == "revoke" and not entry.get("privileges"):
                    items.append({"op": op, **entry, "success": False, "error": "Refusing revoke without privileges"})
                    continue
                fn = self._grant_manager.apply_revoke if op == "revoke" else self._grant_manager.apply_grant
                res = fn(entry, dry_run=dry_run)
                items.append({"op": op, **entry, "success": bool(res.get("success")), "error": res.get("error")})
        return {"success": all(i["success"] for i in items), "items": items,
                "applied": sum(1 for i in items if i["success"]), "failed": sum(1 for i in items if not i["success"])}

    def _deliver_indirect(self, payload: DeliveryPayload) -> DeliveryResult:
        """Deliver change to Git repository as YAML.
        
        Args:
            payload: The change payload
            
        Returns:
            DeliveryResult
        """
        if not self._git_service:
            return DeliveryResult(
                success=False,
                mode=DeliveryMode.INDIRECT,
                change_type=payload.change_type,
                entity_type=payload.entity_type,
                entity_id=payload.entity_id,
                error="Git service not available"
            )
        
        if not self._git_service.is_cloned:
            return DeliveryResult(
                success=False,
                mode=DeliveryMode.INDIRECT,
                change_type=payload.change_type,
                entity_type=payload.entity_type,
                entity_id=payload.entity_id,
                error="Git repository not cloned"
            )
        
        try:
            # Get appropriate file model for the entity type
            from src.file_models import FileModelRegistry
            
            file_model = FileModelRegistry.get(payload.entity_type)
            
            if file_model:
                # Serialize and save using file model
                subdir = file_model.SUBDIRECTORY
                
                if file_model.ONE_FILE_PER_RECORD:
                    # Create individual file for this entity
                    # The payload.data should contain the entity object or dict
                    entity = payload.data.get('entity')
                    if entity:
                        filename = file_model.get_filename(entity)
                        yaml_dict = file_model.to_yaml_dict(entity)
                        wrapped = file_model.wrap_as_resource(entity, yaml_dict)
                        success = self._git_service.save_yaml(filename, wrapped, subdir=subdir)
                    else:
                        # Fallback: save raw data
                        filename = f"{payload.entity_id}.yaml"
                        success = self._git_service.save_yaml(filename, payload.data, subdir=subdir)
                else:
                    # Would need to update the single file with all entities
                    # This is more complex, log and continue
                    filename = file_model.get_filename()
                    success = self._git_service.save_yaml(filename, payload.data, subdir=subdir)
            else:
                # No file model, save raw change data
                subdir = "changes"
                filename = f"{payload.change_type.value}-{payload.entity_id}-{payload.timestamp.strftime('%Y%m%d%H%M%S')}.yaml"
                change_data = {
                    "changeType": payload.change_type.value,
                    "entityType": payload.entity_type,
                    "entityId": payload.entity_id,
                    "timestamp": payload.timestamp.isoformat(),
                    "user": payload.user,
                    "data": payload.data,
                }
                success = self._git_service.save_yaml(filename, change_data, subdir=subdir)
            
            if success:
                return DeliveryResult(
                    success=True,
                    mode=DeliveryMode.INDIRECT,
                    change_type=payload.change_type,
                    entity_type=payload.entity_type,
                    entity_id=payload.entity_id,
                    message="Saved to Git repository",
                    details={"filename": filename, "subdir": subdir}
                )
            else:
                return DeliveryResult(
                    success=False,
                    mode=DeliveryMode.INDIRECT,
                    change_type=payload.change_type,
                    entity_type=payload.entity_type,
                    entity_id=payload.entity_id,
                    error="Failed to save YAML file"
                )
            
        except Exception as e:
            logger.error(f"Indirect delivery failed: {e}", exc_info=True)
            return DeliveryResult(
                success=False,
                mode=DeliveryMode.INDIRECT,
                change_type=payload.change_type,
                entity_type=payload.entity_type,
                entity_id=payload.entity_id,
                error=str(e)
            )
    
    def _deliver_manual(self, payload: DeliveryPayload) -> DeliveryResult:
        """Create notification for manual delivery.
        
        Args:
            payload: The change payload
            
        Returns:
            DeliveryResult
        """
        if not self._notifications_manager:
            return DeliveryResult(
                success=False,
                mode=DeliveryMode.MANUAL,
                change_type=payload.change_type,
                entity_type=payload.entity_type,
                entity_id=payload.entity_id,
                error="Notifications manager not available"
            )
        
        try:
            # Build notification message
            title = self._build_manual_notification_title(payload)
            message = self._build_manual_notification_message(payload)
            
            if payload.db is not None:
                notification = self._notifications_manager.create_delivery_notification(
                    payload.db,
                    change_type=payload.change_type.value,
                    entity_type=payload.entity_type,
                    entity_id=payload.entity_id,
                    # ``entity`` (an ORM object for Indirect mode) isn't JSON-serializable.
                    data={k: v for k, v in payload.data.items() if k != 'entity'},
                    source_user=payload.user,
                )
                if notification is None:
                    return DeliveryResult(
                        success=False,
                        mode=DeliveryMode.MANUAL,
                        change_type=payload.change_type,
                        entity_type=payload.entity_type,
                        entity_id=payload.entity_id,
                        error="Could not create the admin notification",
                    )
                return DeliveryResult(
                    success=True,
                    mode=DeliveryMode.MANUAL,
                    change_type=payload.change_type,
                    entity_type=payload.entity_type,
                    entity_id=payload.entity_id,
                    message="Admin notification created",
                    details={"title": title, "notification_id": notification.id},
                )

            # No DB session supplied by the caller: log the manual action only.
            logger.info(f"Manual delivery requested: {title} - {message}")
            
            return DeliveryResult(
                success=True,
                mode=DeliveryMode.MANUAL,
                change_type=payload.change_type,
                entity_type=payload.entity_type,
                entity_id=payload.entity_id,
                message="Manual action logged (notification pending DB session)",
                details={"title": title, "message": message}
            )
            
        except Exception as e:
            logger.error(f"Manual delivery failed: {e}", exc_info=True)
            return DeliveryResult(
                success=False,
                mode=DeliveryMode.MANUAL,
                change_type=payload.change_type,
                entity_type=payload.entity_type,
                entity_id=payload.entity_id,
                error=str(e)
            )
    
    def _build_manual_notification_title(self, payload: DeliveryPayload) -> str:
        """Build notification title for manual delivery."""
        titles = {
            DeliveryChangeType.GRANT: f"Grant Access: {payload.entity_type}",
            DeliveryChangeType.REVOKE: f"Revoke Access: {payload.entity_type}",
            DeliveryChangeType.TAG_ASSIGN: f"Assign Tag: {payload.entity_type}",
            DeliveryChangeType.TAG_REMOVE: f"Remove Tag: {payload.entity_type}",
            DeliveryChangeType.CONTRACT_UPDATE: "Update Data Contract",
            DeliveryChangeType.PRODUCT_UPDATE: "Update Data Product",
            DeliveryChangeType.ROLE_UPDATE: "Update Role Permissions",
            DeliveryChangeType.POLICY_RELEASE: "Apply Access Policy Release",
        }
        return titles.get(payload.change_type, f"Action Required: {payload.change_type.value}")
    
    def _build_manual_notification_message(self, payload: DeliveryPayload) -> str:
        """Build notification message for manual delivery."""
        base = f"Manual action required for {payload.entity_type} (ID: {payload.entity_id}).\n\n"
        
        if payload.change_type == DeliveryChangeType.GRANT:
            principal = payload.data.get('principal', 'Unknown')
            privileges = payload.data.get('privileges', [])
            target = payload.data.get('target', payload.entity_id)
            base += f"Grant {', '.join(privileges)} to {principal} on {target}"
        elif payload.change_type == DeliveryChangeType.REVOKE:
            principal = payload.data.get('principal', 'Unknown')
            target = payload.data.get('target', payload.entity_id)
            base += f"Revoke access from {principal} on {target}"
        else:
            base += f"Change type: {payload.change_type.value}\n"
            base += f"Data: {payload.data}"
        
        if payload.user:
            base += f"\n\nRequested by: {payload.user}"
        
        return base


# Global delivery service instance
_delivery_service: Optional[DeliveryService] = None


def init_delivery_service(
    settings: Optional[Settings] = None,
    git_service: Optional['GitService'] = None,
    grant_manager: Optional['GrantManager'] = None,
    notifications_manager: Optional['NotificationsManager'] = None,
) -> DeliveryService:
    """Initialize the global delivery service instance."""
    global _delivery_service
    _delivery_service = DeliveryService(
        settings=settings,
        git_service=git_service,
        grant_manager=grant_manager,
        notifications_manager=notifications_manager,
    )
    return _delivery_service


def get_delivery_service() -> DeliveryService:
    """Get the global delivery service instance."""
    if not _delivery_service:
        raise RuntimeError("Delivery service not initialized")
    return _delivery_service

