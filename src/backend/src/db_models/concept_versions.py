"""Database models for the concept-versioning engine (P0-1).

The versioned unit is ``(iri, version)``; ``iri`` is the stable identity. Mirrors
the Data Products versioning pattern (indexed ``version`` + self-referential
``parent_version_id`` lineage). Exactly one ``is_current=true`` row per ``iri`` is
enforced at the DB level by a partial unique index created in Alembic migration
``m1_concept_versioning`` (``UNIQUE(iri) WHERE is_current``).

``scheme_membership`` is the unversioned many-to-many (``skos:inScheme``) tag
linking a concept IRI to a scheme IRI. No "scheme version" object exists.
"""
import uuid

from sqlalchemy import (
    Column, String, Text, Boolean, Integer, TIMESTAMP,
    ForeignKey, Index, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.sql import func

from src.common.database import Base


class ConceptVersionDb(Base):
    """One version of a concept. ``(iri, version)`` is the versioned unit.

    Exactly one row per ``iri`` has ``is_current=true`` (the hot set), enforced by
    the partial unique index ``uq_concept_version_current_per_iri``. History rows
    (``is_current=false``) are cold and fetched on demand by ``(iri, version)``.
    """
    __tablename__ = "concept_version"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Stable identity across versions.
    iri = Column(Text, nullable=False, index=True)
    # Monotonic per iri.
    version = Column(Integer, nullable=False, default=1, index=True)
    # Exactly one true per iri (partial unique index enforces this).
    is_current = Column(Boolean, nullable=False, default=True, index=True)
    status = Column(String(20), nullable=False, default="active")

    # Self-referential lineage / fork.
    parent_version_id = Column(
        PG_UUID(as_uuid=True),
        ForeignKey("concept_version.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Set on a 2B meaning-split (this version's IRI replaces an old IRI).
    replaces_iri = Column(Text, nullable=True)

    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    created_by = Column(String, nullable=True)

    __table_args__ = (
        UniqueConstraint("iri", "version", name="uq_concept_version_iri_version"),
        # Documents the DB-level partial unique index (created via raw DDL in the
        # migration because SQLAlchemy Core cannot express a partial index in a
        # portable way here). Reflected for awareness; the migration owns it.
        Index(
            "uq_concept_version_current_per_iri",
            "iri",
            unique=True,
            postgresql_where=Column("is_current"),
        ),
    )

    def __repr__(self):
        return (
            f"<ConceptVersionDb(iri='{self.iri}', version={self.version}, "
            f"is_current={self.is_current}, status='{self.status}')>"
        )


class SchemeMembershipDb(Base):
    """Unversioned many-to-many membership of a concept IRI in a scheme IRI.

    Corresponds to ``skos:inScheme``. A concept can be in many schemes; there is
    no versioned scheme object.
    """
    __tablename__ = "scheme_membership"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    concept_iri = Column(Text, nullable=False, index=True)
    scheme_iri = Column(Text, nullable=False, index=True)

    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    created_by = Column(String, nullable=True)

    __table_args__ = (
        UniqueConstraint("concept_iri", "scheme_iri",
                         name="uq_scheme_membership_concept_scheme"),
    )

    def __repr__(self):
        return (
            f"<SchemeMembershipDb(concept_iri='{self.concept_iri}', "
            f"scheme_iri='{self.scheme_iri}')>"
        )
