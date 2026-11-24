"""The delivery outbox: a change still to deliver, or the last outcome of its delivery.

A row is written in the transaction of the change it delivers (a rolled-back
change leaves none), one per active delivery mode (``direct``, ``indirect``,
``manual``), so a retry re-runs only the mode that failed. It is tried once after
the commit and then by the workflow scheduler's thread (``delivery_outbox_manager``).

``status``:
- ``pending``: to deliver at ``next_attempt_at``. ``code``/``params`` hold the
  last failed attempt's reason, if any.
- ``delivered``: nothing left to do. ``code`` is None, or why there was nothing
  to do: ``delivery_not_applicable`` (the mode doesn't apply to the change) or
  ``delivery_mode_inactive`` (the mode was turned off before it ran). Deleted
  after the retention period.
- ``failed``: past its attempts, or its entity is gone; kept until it is
  delivered again (``POST /api/delivery/{entity_type}/{entity_id}/redeliver``).
"""
from sqlalchemy import JSON, TIMESTAMP, Column, Index, Integer, String
from sqlalchemy.sql import func

from src.common.database import Base


class DeliveryOutboxDb(Base):
    __tablename__ = "delivery_outbox"
    __table_args__ = (
        # The worker's query: due pending rows, oldest first
        Index('ix_delivery_outbox_status_next_attempt', 'status', 'next_attempt_at'),
        Index('ix_delivery_outbox_entity', 'entity_type', 'entity_id'),
    )

    id = Column(String, primary_key=True)
    # The managers' DELIVERY_ENTITY_TYPE, e.g. 'DataProduct'
    entity_type = Column(String(64), nullable=False)
    entity_id = Column(String, nullable=False)
    # DeliveryChangeType value, e.g. 'product_create'
    change_type = Column(String(64), nullable=False)
    # DeliveryMode value: 'direct', 'indirect' or 'manual'
    mode = Column(String(32), nullable=False)
    status = Column(String(16), nullable=False, default='pending')
    code = Column(String(128), nullable=True)
    params = Column(JSON, nullable=True)
    attempts = Column(Integer, nullable=False, default=0)
    next_attempt_at = Column(TIMESTAMP(timezone=True), nullable=True)
    last_attempt_at = Column(TIMESTAMP(timezone=True), nullable=True)
    delivered_at = Column(TIMESTAMP(timezone=True), nullable=True)
    # Who made the change, or asked to deliver it again
    queued_by = Column(String, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(),
                        onupdate=func.now(), nullable=False)

    def __repr__(self):
        return (f"<DeliveryOutboxDb(id='{self.id}', entity='{self.entity_type}:{self.entity_id}', "
                f"mode='{self.mode}', status='{self.status}')>")
