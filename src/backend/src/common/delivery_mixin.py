"""Delivery Mixin for Manager classes.

Provides a centralized way for managers to queue delivery operations
for their entity changes. This follows the Controller Pattern - business
logic (including delivery) belongs in managers, not routes.

Usage:
    class DataProductsManager(DeliveryMixin):
        DELIVERY_ENTITY_TYPE = "DataProduct"
        
        def update_product(self, ...):
            # ... update logic ...
            self._queue_delivery(
                entity=updated_product,
                change_type=DeliveryChangeType.PRODUCT_UPDATE,
                user=current_user,
                background_tasks=background_tasks
            )
            return updated_product
"""

from typing import Any, Callable, Optional, TYPE_CHECKING

from src.common.logging import get_logger

if TYPE_CHECKING:
    from fastapi import BackgroundTasks
    from src.controller.delivery_service import DeliveryChangeType

logger = get_logger(__name__)


class DeliveryMixin:
    """Mixin providing delivery functionality for Manager classes.
    
    Managers should set DELIVERY_ENTITY_TYPE class attribute to their entity type.
    """
    
    # Override in subclass
    DELIVERY_ENTITY_TYPE: str = ""
    
    def _queue_delivery(
        self,
        entity: Any,
        change_type: 'DeliveryChangeType',
        user: Optional[str] = None,
        background_tasks: Optional['BackgroundTasks'] = None,
    ) -> bool:
        """Queue a delivery operation for a changed entity.
        
        Args:
            entity: The entity that was changed (DB model or dict)
            change_type: Type of change (CREATE, UPDATE, DELETE)
            user: User who made the change
            background_tasks: FastAPI BackgroundTasks for async execution
            
        Returns:
            True if delivery was queued, False otherwise
        """
        try:
            from src.controller.delivery_service import (
                get_delivery_service,
                DeliveryPayload,
            )
            
            delivery_service = get_delivery_service()
            
            # Check if any delivery modes are active
            if not delivery_service:
                logger.debug("Delivery service is unavailable, skipping delivery for %s", self.DELIVERY_ENTITY_TYPE)
                return False

            active_modes = delivery_service.get_active_modes()
            if not active_modes:
                logger.debug(
                    "No active delivery modes, skipping delivery for %s",
                    self.DELIVERY_ENTITY_TYPE,
                )
                return False
            
            # Extract entity ID
            entity_id = self._get_entity_id(entity)
            
            # Build payload - wrap entity in 'entity' key for file model processing
            payload = DeliveryPayload(
                change_type=change_type,
                entity_type=self.DELIVERY_ENTITY_TYPE,
                entity_id=entity_id,
                data={"entity": entity},  # Wrap for file model compatibility
                user=user,
            )
            
            from src.controller.delivery_service import DeliveryMode

            # Indirect delivery serializes ORM relationships. Do it while the
            # request's session is still open; a FastAPI background task runs
            # after the session dependency closes and receives a detached ORM
            # object whose lazy relationships cannot be loaded.
            indirect_modes = [mode for mode in active_modes if mode == DeliveryMode.INDIRECT]
            background_modes = [mode for mode in active_modes if mode != DeliveryMode.INDIRECT]

            if indirect_modes:
                result = delivery_service.deliver(payload, modes=indirect_modes)
                logger.info(
                    "Delivered %s %s synchronously via indirect mode: %s",
                    self.DELIVERY_ENTITY_TYPE,
                    entity_id,
                    result.all_success,
                )

            if background_tasks and background_modes:
                background_tasks.add_task(delivery_service.deliver, payload, background_modes)
                logger.info("Queued delivery for %s %s", self.DELIVERY_ENTITY_TYPE, entity_id)
            elif background_modes:
                result = delivery_service.deliver(payload, modes=background_modes)
                logger.info(
                    "Delivered %s %s: %s",
                    self.DELIVERY_ENTITY_TYPE,
                    entity_id,
                    result.all_success,
                )
                
            return True
            
        except Exception as e:
            logger.warning(
                "Failed to queue delivery for %s: %s",
                self.DELIVERY_ENTITY_TYPE,
                e,
            )
            return False
    
    def _get_entity_id(self, entity: Any) -> str:
        """Extract ID from an entity.
        
        Handles both ORM objects and dicts.
        
        Args:
            entity: Entity object or dict
            
        Returns:
            String ID
        """
        if isinstance(entity, dict):
            return str(entity.get('id', ''))
        elif hasattr(entity, 'id'):
            return str(entity.id)
        else:
            return str(hash(entity))
    
    def _queue_delivery_if_active(
        self,
        entity: Any,
        change_type: 'DeliveryChangeType',
        user: Optional[str] = None,
        background_tasks: Optional['BackgroundTasks'] = None,
    ) -> None:
        """Convenience method that silently queues delivery without return value.
        
        Use this when you don't need to check if delivery was queued.
        """
        self._queue_delivery(
            entity=entity,
            change_type=change_type,
            user=user,
            background_tasks=background_tasks,
        )

