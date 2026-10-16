"""Database model for RDF triples storage.

This table stores all RDF triples from ontologies, taxonomies, and semantic links,
making the database the source of truth for the knowledge graph.
"""
import uuid
from sqlalchemy import Column, String, Text, Boolean, TIMESTAMP, Index, UniqueConstraint, ForeignKey
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.sql import func

from src.common.database import Base


class RdfTripleDb(Base):
    """Stores RDF triples for the knowledge graph.
    
    Each row represents a single RDF triple (subject, predicate, object) with
    optional context (named graph) and metadata about its source.
    
    Uniqueness is enforced by a unique constraint on (subject_uri, predicate_uri,
    object_value, object_language, object_datatype, context_name).
    The constraint is created by Alembic migration g7244c158ee0 (or create_all).
    """
    __tablename__ = "rdf_triples"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # RDF triple components
    subject_uri = Column(Text, nullable=False, index=True)
    predicate_uri = Column(Text, nullable=False, index=True)
    object_value = Column(Text, nullable=False)
    
    # Object type information
    object_is_uri = Column(Boolean, nullable=False, default=True)
    object_language = Column(String(10), nullable=False, default='', server_default='')  # e.g., "en", "de" for lang-tagged literals
    object_datatype = Column(Text, nullable=False, default='', server_default='')  # e.g., xsd:integer for typed literals
    
    # Named graph / context
    context_name = Column(Text, nullable=False, default='default', index=True)
    
    # Source tracking
    source_type = Column(String(20), nullable=True)  # file, upload, demo, link
    source_identifier = Column(Text, nullable=True)  # filename, model_id, entity info

    # Concept-versioning ownership (P0-1). Which concept-version owns this triple.
    # Ownership is determined by the SUBJECT IRI; blank-node closures follow the
    # IRI subject they hang off. NULL for triples whose subject is not a concept
    # IRI (e.g. scheme headers, semantic-link edges). FK added by migration
    # m1_concept_versioning.
    concept_version_id = Column(
        PG_UUID(as_uuid=True),
        ForeignKey("concept_version.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    
    # Audit fields
    created_by = Column(String, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)

    # Unique constraint required for ON CONFLICT DO NOTHING in rdf_triples_repository.
    # Includes concept_version_id (migration m4_rdf_triple_version_uq) so per-version
    # snapshot rows (same triple owned by different versions) coexist, while
    # NULLS NOT DISTINCT keeps NULL-owned (unversioned/metadata) triples deduped.
    __table_args__ = (
        UniqueConstraint(
            'subject_uri', 'predicate_uri', 'object_value',
            'object_language', 'object_datatype', 'context_name', 'concept_version_id',
            name='uq_rdf_triple',
            postgresql_nulls_not_distinct=True,
        ),
        # Partial unique index for UNVERSIONED triples (concept_version_id IS
        # NULL) on the natural key. The uq_rdf_triple constraint above already
        # dedups these on Postgres via NULLS NOT DISTINCT, but that clause is a
        # no-op on SQLite (unit tests) where NULLs are DISTINCT — so imports/bulk
        # inserts (always unversioned) target THIS index instead, which dedups
        # identically on both dialects. See rdf_triples_repository
        # _NULL_VERSION_CONFLICT_COLS. Prod migration: m5_rdf_triple_null_version_uq.
        Index(
            'uq_rdf_triple_null_version',
            'subject_uri', 'predicate_uri', 'object_value',
            'object_language', 'object_datatype', 'context_name',
            unique=True,
            sqlite_where=concept_version_id.is_(None),
            postgresql_where=concept_version_id.is_(None),
        ),
        # Composite index for SPO lookups
        Index('ix_rdf_triples_spo', 'subject_uri', 'predicate_uri', 'object_value'),
    )

    def __repr__(self):
        obj_display = self.object_value[:50] + '...' if len(self.object_value) > 50 else self.object_value
        return f"<RdfTripleDb(s='{self.subject_uri}', p='{self.predicate_uri}', o='{obj_display}')>"

