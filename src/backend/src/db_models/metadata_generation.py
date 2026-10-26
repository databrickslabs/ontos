"""
Metadata Generation Database Models

A Generation Run executes dbxmetagen as a background job over a selection of
Unity Catalog objects; its output is ingested as Description Suggestions.
See docs/prds/prd-metadata-generation.md.
"""

from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import relationship

from src.common.database import Base


class MetadataGenerationRunDb(Base):
    """Tracks one Generation Run (one Databricks job run of metagen_generate)."""
    __tablename__ = 'metagen_runs'

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    user_id = Column(String, nullable=False, index=True)

    # pending | running | ingesting | completed | failed | cancelled
    status = Column(String, nullable=False, default='pending')
    progress_message = Column(String, nullable=True)
    error = Column(Text, nullable=True)

    # What the user picked: [{"type": "catalog|schema|table", "fqn": "..."}]
    selection = Column(JSON, nullable=False)
    # Run options: comment_style, model, allow_data, sample_size,
    # regenerate_existing, auto_submit
    options = Column(JSON, nullable=True)

    # Databricks job run id of the metagen_generate job
    job_run_id = Column(String, nullable=True, index=True)
    # Token usage reported by dbxmetagen (filled in a later slice)
    token_usage = Column(JSON, nullable=True)
    suggestion_count = Column(Integer, nullable=False, default=0)
    # Failed attempts at loading the job's results; retried up to a limit
    ingest_attempts = Column(Integer, nullable=False, default=0)
    # Since when the Jobs API has kept failing to report this run's job
    status_unavailable_since = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    suggestions = relationship(
        'DescriptionSuggestionDb',
        back_populates='run',
        cascade='all, delete-orphan',
        passive_deletes=True,
    )

    __table_args__ = (
        Index('ix_metagen_runs_user_status', 'user_id', 'status'),
        Index('ix_metagen_runs_user_created', 'user_id', 'created_at'),
    )

    def __repr__(self):
        return f"<MetadataGenerationRunDb(id='{self.id}', user='{self.user_id}', status='{self.status}')>"


class DescriptionSuggestionDb(Base):
    """A proposed description for one table, view or column."""
    __tablename__ = 'metagen_suggestions'

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    run_id = Column(String, ForeignKey('metagen_runs.id', ondelete='CASCADE'), nullable=False, index=True)

    # Discriminator for later dbxmetagen modes (pi, domain); v1 only 'description'
    kind = Column(String, nullable=False, default='description')
    # table | view | column
    object_type = Column(String, nullable=False)
    table_fqn = Column(String, nullable=False)
    column_name = Column(String, nullable=True)

    # UC description at generation time (None/empty = there was none)
    base_text = Column(Text, nullable=True)
    proposed_text = Column(Text, nullable=False)
    # Reviewer's edit of proposed_text, if any
    edited_text = Column(Text, nullable=True)

    # pending | accepted | rejected | applied | conflict | not_applicable | superseded
    status = Column(String, nullable=False, default='pending')

    # Asset Review back-pointers (set when the run is submitted for review)
    review_request_id = Column(String, nullable=True)
    reviewed_asset_id = Column(String, nullable=True)
    decided_by = Column(String, nullable=True)
    decided_at = Column(DateTime(timezone=True), nullable=True)
    # Reviewer's comment on the last decision (e.g. what needs clarifying)
    review_comment = Column(Text, nullable=True)

    # Apply outcome
    applied_by = Column(String, nullable=True)
    applied_at = Column(DateTime(timezone=True), nullable=True)
    applied_text = Column(Text, nullable=True)
    error = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    run = relationship('MetadataGenerationRunDb', back_populates='suggestions')

    __table_args__ = (
        Index('ix_metagen_suggestions_run_status', 'run_id', 'status'),
        Index('ix_metagen_suggestions_target', 'table_fqn', 'column_name'),
    )

    def __repr__(self):
        target = f"{self.table_fqn}.{self.column_name}" if self.column_name else self.table_fqn
        return f"<DescriptionSuggestionDb(id='{self.id}', target='{target}', status='{self.status}')>"
