"""Term-mapping persistence: apply-run records and suggestion queue.

The "term mapping" feature bulk-suggests customer-ontology concept links for
Assets, Data Contract schemas/properties, and Data Products. Applied links are
written through SemanticLinksManager into the existing entity_semantic_links
table; these two tables capture the run-level traceability + the persistent
suggestion queue. See docs/prds/prd-ontology-term-mapping.md.
"""
import uuid
from sqlalchemy import (
    Column,
    String,
    Text,
    Float,
    Boolean,
    Integer,
    TIMESTAMP,
    JSON,
    ForeignKey,
    Index,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from src.common.database import Base


# Run statuses
RUN_STATUS_PENDING = "pending"          # created but suggester not started
RUN_STATUS_SUGGESTING = "suggesting"    # suggester executing
RUN_STATUS_SUGGESTED = "suggested"      # suggester finished; queue ready for review
RUN_STATUS_APPLYING = "applying"
RUN_STATUS_APPLIED = "applied"
RUN_STATUS_UNDONE = "undone"
RUN_STATUS_FAILED = "failed"

# Suggestion statuses
SUG_STATUS_PENDING = "pending"
SUG_STATUS_ACCEPTED = "accepted"
SUG_STATUS_REJECTED = "rejected"
SUG_STATUS_APPLIED = "applied"
SUG_STATUS_SUPERSEDED = "superseded"
SUG_STATUS_NEEDS_CLARIFICATION = "needs_clarification"  # mirrored from ReviewedAssetStatus

# Suggestion kinds
SUG_KIND_ENTITY = "entity_assignment"
SUG_KIND_ATTRIBUTE = "attribute_assignment"

# Engines
ENGINE_HEURISTIC = "heuristic"
ENGINE_LLM_JUDGE = "llm_judge"


class MappingApplyRunDb(Base):
    """One suggester+apply run. Captures config, stats, and the link ids
    created on apply (for single-click undo). See PRD."""
    __tablename__ = "term_mapping_runs"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Concept source scoping. ontology_contexts = customer ontologies
    # (urn:semantic-model:*). include_shipped = explicit opt-in for shipped
    # taxonomies (databricks_ontology, odcs-ontology). The internal
    # urn:taxonomy:ontos-ontology context is rejected by the manager.
    ontology_contexts = Column(JSON, nullable=False, default=list)
    include_shipped = Column(JSON, nullable=False, default=list)

    # Target selection filter, e.g.
    # {"entity_types": ["data_contract_property", "asset"],
    #  "domain_ids": [...], "contract_ids": [...], "asset_type_names": ["Column"]}
    target_filter = Column(JSON, nullable=False, default=dict)

    # Enabled engines, e.g. ["heuristic"] or ["heuristic", "llm_judge"]
    engines = Column(JSON, nullable=False, default=list)

    status = Column(String, nullable=False, default=RUN_STATUS_PENDING, index=True)
    comment = Column(Text, nullable=True)

    # Runtime stats; merged in as the run progresses.
    # {"targets": N, "suggestions_total": N, "suggestions_pending": N,
    #  "suggestions_accepted": N, "suggestions_rejected": N,
    #  "links_created": N, "llm_calls": N,
    #  "llm_tokens_in": N, "llm_tokens_out": N}
    stats = Column(JSON, nullable=False, default=dict)
    error = Column(Text, nullable=True)

    # IDs of the entity_semantic_links rows this run created. Used by undo
    # to remove exactly the run's contribution. List[str] of UUIDs.
    applied_link_ids = Column(JSON, nullable=False, default=list)

    created_by = Column(String, nullable=True, index=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    started_at = Column(TIMESTAMP(timezone=True), nullable=True)
    finished_at = Column(TIMESTAMP(timezone=True), nullable=True)
    applied_at = Column(TIMESTAMP(timezone=True), nullable=True)
    undone_at = Column(TIMESTAMP(timezone=True), nullable=True)

    suggestions = relationship(
        "MappingSuggestionDb",
        back_populates="run",
        cascade="all, delete-orphan",
    )

    def __repr__(self):
        return f"<MappingApplyRunDb(id={self.id}, status='{self.status}')>"


class MappingSuggestionDb(Base):
    """One proposed assignment of a customer-ontology concept to a single
    source entity. Persistent queue (pending/accepted/rejected/applied/
    superseded) so stewards can triage over time and the suggester can
    skip already-decided pairs on future runs."""
    __tablename__ = "term_mapping_suggestions"

    id = Column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id = Column(
        PG_UUID(as_uuid=True),
        ForeignKey("term_mapping_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Source entity. entity_type matches models/semantic_links.py EntityType
    # literal (data_product, data_contract, data_contract_schema,
    # data_contract_property, dataset, asset, uc_*).
    source_entity_type = Column(String, nullable=False, index=True)
    source_entity_id = Column(String, nullable=False, index=True)
    # Denormalised display name to avoid joining back on every read.
    source_label = Column(String, nullable=True)

    suggestion_kind = Column(String, nullable=False)  # entity_assignment | attribute_assignment

    target_concept_iri = Column(Text, nullable=False)
    target_concept_label = Column(Text, nullable=True)

    confidence = Column(Float, nullable=False, default=0.0)
    reason = Column(Text, nullable=False, default="")  # rendered verbatim in UI
    auto_apply = Column(Boolean, nullable=False, default=False)

    engine = Column(String, nullable=False, default=ENGINE_HEURISTIC)
    # Engine-specific extras (heuristic signals, LLM rationale, etc.).
    engine_metadata = Column(JSON, nullable=True)

    # Lifecycle.
    status = Column(String, nullable=False, default=SUG_STATUS_PENDING, index=True)
    decided_by = Column(String, nullable=True)
    decided_at = Column(TIMESTAMP(timezone=True), nullable=True)
    # Steward override of target_concept_iri at decision time.
    custom_iri = Column(Text, nullable=True)
    # Set after apply: the entity_semantic_links.id row this suggestion
    # produced. Used by undo.
    applied_link_id = Column(PG_UUID(as_uuid=True), nullable=True)

    # Flags surfaced from engine guards (e.g. orphan_attribute, conflict).
    warnings = Column(JSON, nullable=True)

    # MDM-style back-pointers populated when a steward generates a
    # DataAssetReviewRequest from the run. Decisions made in the AR editor
    # PUT through the term-mapping decide endpoint, which updates this row
    # and forward-syncs the linked ReviewedAsset. Nullable FKs so the
    # review can be deleted without losing the suggestion.
    # NOTE: data_asset_review_requests.id + reviewed_assets.id are
    # String (varchar) PKs, not Postgres uuid; FK column types must match.
    review_request_id = Column(
        String,
        ForeignKey("data_asset_review_requests.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    reviewed_asset_id = Column(
        String,
        ForeignKey("reviewed_assets.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    run = relationship("MappingApplyRunDb", back_populates="suggestions")

    __table_args__ = (
        Index(
            "ix_term_mapping_suggestions_source",
            "source_entity_type",
            "source_entity_id",
        ),
        Index(
            "ix_term_mapping_suggestions_run_status",
            "run_id",
            "status",
        ),
    )

    def __repr__(self):
        return (
            f"<MappingSuggestionDb(id={self.id}, "
            f"src={self.source_entity_type}:{self.source_entity_id}, "
            f"iri={self.target_concept_iri}, status={self.status})>"
        )
