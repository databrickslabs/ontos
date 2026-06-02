"""Add term-mapping run and suggestion tables.

Adds the two backing tables for the bulk ontology term-suggestion
feature (PRD #469). Suggestions carry MDM-style nullable back-pointers
to data_asset_review_requests / reviewed_assets so a steward can spawn
a review for the queue and decisions propagate both ways.

Revision ID: aa1_term_mapping
Revises: g2_ontology_gen_runs
Create Date: 2026-06-02
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PG_UUID


revision: str = 'aa1_term_mapping'
down_revision: Union[str, None] = 'g2_ontology_gen_runs'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'term_mapping_runs',
        sa.Column('id', PG_UUID(as_uuid=True), primary_key=True),
        sa.Column('ontology_contexts', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('include_shipped', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('target_filter', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('engines', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('status', sa.String(), nullable=False, server_default='pending'),
        sa.Column('comment', sa.Text(), nullable=True),
        sa.Column('stats', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('applied_link_ids', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('created_by', sa.String(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('started_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('finished_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('applied_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('undone_at', sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index('ix_term_mapping_runs_status', 'term_mapping_runs', ['status'])
    op.create_index('ix_term_mapping_runs_created_by', 'term_mapping_runs', ['created_by'])

    op.create_table(
        'term_mapping_suggestions',
        sa.Column('id', PG_UUID(as_uuid=True), primary_key=True),
        sa.Column('run_id', PG_UUID(as_uuid=True), nullable=False),
        sa.Column('source_entity_type', sa.String(), nullable=False),
        sa.Column('source_entity_id', sa.String(), nullable=False),
        sa.Column('source_label', sa.String(), nullable=True),
        sa.Column('suggestion_kind', sa.String(), nullable=False),
        sa.Column('target_concept_iri', sa.Text(), nullable=False),
        sa.Column('target_concept_label', sa.Text(), nullable=True),
        sa.Column('confidence', sa.Float(), nullable=False, server_default='0'),
        sa.Column('reason', sa.Text(), nullable=False, server_default=''),
        sa.Column('auto_apply', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('engine', sa.String(), nullable=False, server_default='heuristic'),
        sa.Column('engine_metadata', sa.JSON(), nullable=True),
        sa.Column('status', sa.String(), nullable=False, server_default='pending'),
        sa.Column('decided_by', sa.String(), nullable=True),
        sa.Column('decided_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('custom_iri', sa.Text(), nullable=True),
        sa.Column('applied_link_id', PG_UUID(as_uuid=True), nullable=True),
        sa.Column('warnings', sa.JSON(), nullable=True),
        sa.Column('review_request_id', PG_UUID(as_uuid=True), nullable=True),
        sa.Column('reviewed_asset_id', PG_UUID(as_uuid=True), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['run_id'], ['term_mapping_runs.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['review_request_id'], ['data_asset_review_requests.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['reviewed_asset_id'], ['reviewed_assets.id'], ondelete='SET NULL'),
    )
    op.create_index('ix_term_mapping_suggestions_run_id', 'term_mapping_suggestions', ['run_id'])
    op.create_index('ix_term_mapping_suggestions_status', 'term_mapping_suggestions', ['status'])
    op.create_index('ix_term_mapping_suggestions_source_entity_type', 'term_mapping_suggestions', ['source_entity_type'])
    op.create_index('ix_term_mapping_suggestions_source_entity_id', 'term_mapping_suggestions', ['source_entity_id'])
    op.create_index('ix_term_mapping_suggestions_source', 'term_mapping_suggestions', ['source_entity_type', 'source_entity_id'])
    op.create_index('ix_term_mapping_suggestions_run_status', 'term_mapping_suggestions', ['run_id', 'status'])
    op.create_index('ix_term_mapping_suggestions_review_request_id', 'term_mapping_suggestions', ['review_request_id'])
    op.create_index('ix_term_mapping_suggestions_reviewed_asset_id', 'term_mapping_suggestions', ['reviewed_asset_id'])


def downgrade() -> None:
    op.drop_index('ix_term_mapping_suggestions_reviewed_asset_id', table_name='term_mapping_suggestions')
    op.drop_index('ix_term_mapping_suggestions_review_request_id', table_name='term_mapping_suggestions')
    op.drop_index('ix_term_mapping_suggestions_run_status', table_name='term_mapping_suggestions')
    op.drop_index('ix_term_mapping_suggestions_source', table_name='term_mapping_suggestions')
    op.drop_index('ix_term_mapping_suggestions_source_entity_id', table_name='term_mapping_suggestions')
    op.drop_index('ix_term_mapping_suggestions_source_entity_type', table_name='term_mapping_suggestions')
    op.drop_index('ix_term_mapping_suggestions_status', table_name='term_mapping_suggestions')
    op.drop_index('ix_term_mapping_suggestions_run_id', table_name='term_mapping_suggestions')
    op.drop_table('term_mapping_suggestions')
    op.drop_index('ix_term_mapping_runs_created_by', table_name='term_mapping_runs')
    op.drop_index('ix_term_mapping_runs_status', table_name='term_mapping_runs')
    op.drop_table('term_mapping_runs')
