import uuid

from sqlalchemy import JSON, TIMESTAMP, Column, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.sql import func

from src.common.database import Base


class MetricViewBaselineDb(Base):
    """The definition of a Unity Catalog metric view that its drift is checked against (#1124).

    One row per metric view (``metric_view_fqn``, ``catalog.schema.view`` lower-cased).
    ``definition`` is the normalized spec (``common/metric_view_normalization.py``) and
    ``digest`` its SHA-256. A baseline recorded from the first definition Ontos read
    has no ``approved_at`` / ``request_id``; an approved change request (#1124 phase 3)
    sets both.

    ``drift_state`` is ``in_sync``, ``drifted`` or ``unknown`` (the definition could not
    be parsed) as of ``last_checked_at``; ``observed_digest`` is the digest last read
    from Unity Catalog, so a change is notified once.
    """
    __tablename__ = "metric_view_baselines"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    metric_view_fqn = Column(String, nullable=False, unique=True, index=True)
    definition = Column(JSON, nullable=False)
    digest = Column(String(64), nullable=False)
    approved_at = Column(TIMESTAMP(timezone=True), nullable=True)
    request_id = Column(String, nullable=True)
    drift_state = Column(String(16), nullable=False, default='in_sync')
    observed_digest = Column(String(64), nullable=True)
    last_checked_at = Column(TIMESTAMP(timezone=True), nullable=True)

    created_by = Column(String, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )

    def __repr__(self):
        return (f"<MetricViewBaselineDb(fqn='{self.metric_view_fqn}', "
                f"drift_state='{self.drift_state}')>")
