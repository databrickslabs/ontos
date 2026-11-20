"""Add Authority Resolution (ARF) tables

Revision ID: aa1_authority_resolution
Revises: l1_entity_domain_associations
Create Date: 2026-09-20

Creates the Authority Resolution feature tables: authority_relations (the AR
Definition / rule), authority_affirmations (N-functional affirmation
stakeholders), authority_dna_runs (a DNA-Coefficient computation), and
authority_decisions (per-evaluation / per-evidence-row records).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'aa1_authority_resolution'
down_revision: Union[str, None] = 'l1_entity_domain_associations'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'authority_relations',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('slug', sa.String(), nullable=True),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('status', sa.String(), nullable=False, server_default='draft'),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('version_family_id', sa.String(), nullable=True),
        sa.Column('actor_role', sa.String(), nullable=True),
        sa.Column('actor_identity', sa.String(), nullable=True),
        sa.Column('actor_since', sa.DateTime(timezone=True), nullable=True),
        sa.Column('action', sa.String(), nullable=True),
        sa.Column('object_type', sa.String(), nullable=True),
        sa.Column('object_id', sa.String(), nullable=True),
        sa.Column('object_resolves_to', sa.JSON(), nullable=True),
        sa.Column('domain_context', sa.JSON(), nullable=True),
        sa.Column('justification_chain', sa.JSON(), nullable=True),
        sa.Column('decision_logic', sa.JSON(), nullable=True),
        sa.Column('evidence_binding', sa.JSON(), nullable=True),
        sa.Column('dna_magnitude', sa.Float(), nullable=True),
        sa.Column('dna_direction', sa.String(), nullable=True),
        sa.Column('dna_measured_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('dna_max_threshold', sa.Float(), nullable=False, server_default='0.3'),
        sa.Column('dna_scoring_config', sa.JSON(), nullable=True),
        sa.Column('schedule_cron', sa.String(), nullable=True),
        sa.Column('usage_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('approved_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('denied_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('created_by', sa.String(), nullable=True),
    )
    op.create_index('ix_authority_relations_slug', 'authority_relations', ['slug'], unique=True)
    op.create_index('ix_authority_relations_status', 'authority_relations', ['status'])
    op.create_index('ix_authority_relations_version_family', 'authority_relations', ['version_family_id'])

    op.create_table(
        'authority_affirmations',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('relation_id', sa.String(), sa.ForeignKey('authority_relations.id'), nullable=False),
        sa.Column('role', sa.String(), nullable=False),
        sa.Column('principal', sa.String(), nullable=False),
        sa.Column('principal_type', sa.String(), nullable=False, server_default='user'),
        sa.Column('required', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('affirmed', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('affirmed_by', sa.String(), nullable=True),
        sa.Column('affirmed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0'),
    )
    op.create_index('ix_authority_affirmations_relation', 'authority_affirmations', ['relation_id'])

    op.create_table(
        'authority_dna_runs',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('relation_id', sa.String(), sa.ForeignKey('authority_relations.id'), nullable=False),
        sa.Column('status', sa.String(), nullable=False, server_default='queued'),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('sampled_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('divergent_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('magnitude', sa.Float(), nullable=False, server_default='0'),
        sa.Column('direction', sa.String(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
    )
    op.create_index('ix_authority_dna_runs_relation', 'authority_dna_runs', ['relation_id'])
    op.create_index('ix_authority_dna_runs_status', 'authority_dna_runs', ['status'])

    op.create_table(
        'authority_decisions',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('relation_id', sa.String(), sa.ForeignKey('authority_relations.id'), nullable=False),
        sa.Column('relation_version', sa.Integer(), nullable=True),
        sa.Column('source', sa.String(), nullable=False, server_default='mcp'),
        sa.Column('dna_run_id', sa.String(), sa.ForeignKey('authority_dna_runs.id'), nullable=True),
        sa.Column('actor_identity', sa.String(), nullable=True),
        sa.Column('action', sa.String(), nullable=True),
        sa.Column('object_id', sa.String(), nullable=True),
        sa.Column('request_params', sa.JSON(), nullable=True),
        sa.Column('verdict', sa.String(), nullable=True),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('divergence_magnitude', sa.Float(), nullable=True),
        sa.Column('direction', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_authority_decisions_relation', 'authority_decisions', ['relation_id'])
    op.create_index('ix_authority_decisions_source', 'authority_decisions', ['source'])
    op.create_index('ix_authority_decisions_dna_run', 'authority_decisions', ['dna_run_id'])
    op.create_index('ix_authority_decisions_created', 'authority_decisions', ['created_at'])


def downgrade() -> None:
    op.drop_table('authority_decisions')
    op.drop_table('authority_dna_runs')
    op.drop_table('authority_affirmations')
    op.drop_index('ix_authority_relations_version_family', table_name='authority_relations')
    op.drop_index('ix_authority_relations_status', table_name='authority_relations')
    op.drop_index('ix_authority_relations_slug', table_name='authority_relations')
    op.drop_table('authority_relations')
