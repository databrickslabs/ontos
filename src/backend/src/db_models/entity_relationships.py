"""Cross-tier entity relationship table.

Links any entity to any other entity using polymorphic (entity_type, entity_id)
references. Relationship types are validated against the ontology at write time.
"""

import uuid
from sqlalchemy import Column, String, Index, TIMESTAMP, JSON, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import validates
from sqlalchemy.sql import func

from src.common.ontology_type_names import canonical_type_name

from src.common.database import Base


class EntityRelationshipDb(Base):
    """Directed relationship between any two application entities (cross-tier)."""
    __tablename__ = "entity_relationships"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_type = Column(String, nullable=False)
    source_id = Column(String, nullable=False)
    target_type = Column(String, nullable=False)
    target_id = Column(String, nullable=False)
    relationship_type = Column(String, nullable=False)
    properties = Column(JSON, nullable=True)

    created_by = Column(String, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "source_type", "source_id", "target_type", "target_id", "relationship_type",
            name="uq_entity_relationship",
        ),
        Index("ix_entity_rel_source", "source_type", "source_id"),
        Index("ix_entity_rel_target", "target_type", "target_id"),
        Index("ix_entity_rel_type", "relationship_type"),
    )

    @validates("source_type", "target_type")
    def _canonical_type(self, _key, value):
        # Every writer gets the same spelling, so exact lookups find the row.
        return canonical_type_name(value)

    def __repr__(self):
        return (
            f"<EntityRelationshipDb(id={self.id}, "
            f"src={self.source_type}:{self.source_id}, "
            f"tgt={self.target_type}:{self.target_id}, "
            f"type='{self.relationship_type}')>"
        )
