import uuid

from sqlalchemy import JSON, TIMESTAMP, Column, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.sql import func

from src.common.database import Base


class MetricViewChangeRequestDb(Base):
    """A proposed definition of a Unity Catalog metric view (#1124 phase 3).

    ``base_definition`` is the ``view_definition`` read from Unity Catalog when
    the draft was made and ``base_digest`` the digest of its normalized form
    (``common/metric_view_normalization.py``); ``proposed_digest`` is the same for
    ``proposed_definition``. ``metric_view_fqn`` is ``catalog.schema.view``
    lower-cased, as on the view's baseline.

    ``status``: ``draft`` → ``in_review`` (submitted, a workflow runs its
    approval) → ``approved`` → ``delivered`` (handed off: files written, owners
    notified) or ``failed`` (``error_code``); ``rejected`` and ``cancelled``
    end a request without delivery. ``applied_at`` is set when Unity Catalog is
    read back with the proposed definition, which then becomes the baseline.
    """
    __tablename__ = "metric_view_change_requests"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    asset_id = Column(PG_UUID(as_uuid=True), nullable=False, index=True)
    metric_view_fqn = Column(String, nullable=False, index=True)
    base_definition = Column(Text, nullable=False)
    base_digest = Column(String(64), nullable=False)
    base_owner = Column(String, nullable=True)
    proposed_definition = Column(Text, nullable=False)
    proposed_digest = Column(String(64), nullable=False)
    justification = Column(Text, nullable=True)
    status = Column(String(16), nullable=False, default='draft', index=True)
    # Pre-check warnings shown in the review: [{code, message, params}]
    warnings = Column(JSON, nullable=True)
    workflow_execution_id = Column(String, nullable=True)
    # The delivery modes used, comma-separated (indirect, manual)
    delivery_mode = Column(String(32), nullable=True)
    # The files written (Indirect) or the users notified (Manual)
    delivery_reference = Column(String, nullable=True)
    delivery_details = Column(JSON, nullable=True)
    error_code = Column(String(64), nullable=True)
    error_params = Column(JSON, nullable=True)

    requested_by = Column(String, nullable=False)
    decided_by = Column(String, nullable=True)
    decision_message = Column(Text, nullable=True)
    submitted_at = Column(TIMESTAMP(timezone=True), nullable=True)
    decided_at = Column(TIMESTAMP(timezone=True), nullable=True)
    delivered_at = Column(TIMESTAMP(timezone=True), nullable=True)
    applied_at = Column(TIMESTAMP(timezone=True), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )

    def __repr__(self):
        return (f"<MetricViewChangeRequestDb(id='{self.id}', fqn='{self.metric_view_fqn}', "
                f"status='{self.status}')>")
