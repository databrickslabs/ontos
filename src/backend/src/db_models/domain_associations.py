import uuid

from sqlalchemy import (
    Boolean,
    Column,
    ForeignKey,
    Index,
    String,
    TIMESTAMP,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.sql import func

from src.common.database import Base


class EntityDomainAssociationDb(Base):
    """Association of a Data Domain to an entity (team, data_contract, data_product, asset).

    Polymorphic junction table modeled on ``EntityTagAssociationDb``. Each entity may be
    assigned to many domains; at most one association per ``(entity_type, entity_id)`` may
    carry ``is_primary=True``. The primary domain feeds single-value integrations (ODCS
    ``domain`` field, Unity Catalog ``data_domain`` tag); additional domains participate in
    any-of search/filter/discovery and are emitted through extension fields.

    Replaces the legacy single-domain columns ``teams.domain_id``,
    ``data_contracts.domain_id``, ``assets.domain_id`` and ``data_products.domain``.
    """

    __tablename__ = "entity_domain_associations"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    domain_id = Column(String, ForeignKey("data_domains.id"), nullable=False, index=True)
    entity_id = Column(String, nullable=False, index=True)  # ID of the domain-assigned entity
    entity_type = Column(String, nullable=False, index=True)  # e.g. "team", "data_contract", "data_product", "asset"
    is_primary = Column(Boolean, nullable=False, default=False, index=True)

    assigned_by = Column(String, nullable=True)  # User email or ID
    assigned_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        # An entity can be assigned to a given domain at most once.
        UniqueConstraint("domain_id", "entity_type", "entity_id", name="uq_entity_domain_assignment"),
        # At most one primary domain per entity. Partial unique index works on both
        # PostgreSQL (production/Lakebase) and SQLite (test suite).
        Index(
            "uq_entity_domain_primary",
            "entity_type",
            "entity_id",
            unique=True,
            postgresql_where=text("is_primary"),
            sqlite_where=text("is_primary = 1"),
        ),
        # Composite index for the common batch lookup by entity.
        Index("ix_entity_domain_entity", "entity_type", "entity_id"),
    )

    def __repr__(self):
        return (
            f"<EntityDomainAssociationDb(id={self.id}, domain_id='{self.domain_id}', "
            f"entity_id='{self.entity_id}', entity_type='{self.entity_type}', is_primary={self.is_primary})>"
        )
