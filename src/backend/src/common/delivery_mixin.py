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

from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import Session

from src.common.after_commit import run_after_commit
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
            if not delivery_service or not delivery_service.get_active_modes():
                logger.debug(f"No active delivery modes, skipping delivery for {self.DELIVERY_ENTITY_TYPE}")
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
            
            if background_tasks:
                # Queue for async execution
                background_tasks.add_task(delivery_service.deliver, payload)
                logger.info(f"Queued delivery for {self.DELIVERY_ENTITY_TYPE} {entity_id}")
            else:
                # Execute synchronously (not ideal, but works for testing)
                result = delivery_service.deliver(payload)
                logger.info(f"Delivered {self.DELIVERY_ENTITY_TYPE} {entity_id}: {result.all_success}")
                
            return True
            
        except Exception as e:
            logger.warning(f"Failed to queue delivery for {self.DELIVERY_ENTITY_TYPE}: {e}")
            return False
    
    def _queue_delivery_after_commit(
        self,
        db: Session,
        entity: Any,
        change_type: 'DeliveryChangeType',
        user: Optional[str] = None,
    ) -> None:
        """Deliver a changed entity once ``db`` commits (synchronously, best effort).

        For callers that write in a transaction they don't commit themselves (an
        import): delivering before the commit would leave a Unity Catalog change
        or a Git file behind for an entity a rollback removes. Nothing is
        delivered when the transaction, or the savepoint the entity was queued
        in, rolls back.
        """
        # The committed session can't be used for SQL in ``after_commit``, and the
        # entity it holds is expired: deliver a copy read in a session of its own.
        state = sa_inspect(entity, raiseerr=False)
        orm_class = type(entity) if state is not None and state.mapper else None
        entity_id = self._get_entity_id(entity)
        bind = db.get_bind()

        def deliver() -> None:
            if orm_class is None:
                self._queue_delivery(entity=entity, change_type=change_type, user=user)
                return
            with Session(bind=bind, expire_on_commit=False) as own:
                fresh = own.get(orm_class, entity_id)
                if fresh is None:
                    logger.warning("Not delivering %s %s: not found after commit",
                                   self.DELIVERY_ENTITY_TYPE, entity_id)
                    return
                self._queue_delivery(entity=fresh, change_type=change_type, user=user)

        run_after_commit(db, deliver)

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

