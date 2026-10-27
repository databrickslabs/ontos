"""add metadata generation runs and description suggestions

A Generation Run executes dbxmetagen over a selection of Unity Catalog
objects; its output is ingested as Description Suggestions which go through
Asset Review before being applied to UC (PRD #1184).

Revision ID: b8_metadata_generation
Revises: b7_workflow_step_results_kept
Create Date: 2026-10-23 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON


revision: str = 'b8_metadata_generation'
down_revision: Union[str, None] = 'b7_workflow_step_results_kept'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'metagen_runs',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False, server_default='pending'),
        sa.Column('progress_message', sa.String(), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('selection', JSON(), nullable=False),
        sa.Column('options', JSON(), nullable=True),
        sa.Column('job_run_id', sa.String(), nullable=True),
        sa.Column('token_usage', JSON(), nullable=True),
        sa.Column('suggestion_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('ingest_attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('status_unavailable_since', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_metagen_runs_user_id', 'metagen_runs', ['user_id'])
    op.create_index('ix_metagen_runs_job_run_id', 'metagen_runs', ['job_run_id'])
    op.create_index('ix_metagen_runs_user_status', 'metagen_runs', ['user_id', 'status'])
    op.create_index('ix_metagen_runs_user_created', 'metagen_runs', ['user_id', 'created_at'])

    op.create_table(
        'metagen_suggestions',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('run_id', sa.String(), sa.ForeignKey('metagen_runs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('kind', sa.String(), nullable=False, server_default='description'),
        sa.Column('object_type', sa.String(), nullable=False),
        sa.Column('table_fqn', sa.String(), nullable=False),
        sa.Column('column_name', sa.String(), nullable=True),
        sa.Column('base_text', sa.Text(), nullable=True),
        sa.Column('proposed_text', sa.Text(), nullable=False),
        sa.Column('edited_text', sa.Text(), nullable=True),
        sa.Column('status', sa.String(), nullable=False, server_default='pending'),
        sa.Column('review_request_id', sa.String(), nullable=True),
        sa.Column('reviewed_asset_id', sa.String(), nullable=True),
        sa.Column('decided_by', sa.String(), nullable=True),
        sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('applied_by', sa.String(), nullable=True),
        sa.Column('applied_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('applied_text', sa.Text(), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_metagen_suggestions_run_id', 'metagen_suggestions', ['run_id'])
    op.create_index('ix_metagen_suggestions_run_status', 'metagen_suggestions', ['run_id', 'status'])
    op.create_index('ix_metagen_suggestions_target', 'metagen_suggestions', ['table_fqn', 'column_name'])


def downgrade() -> None:
    op.drop_table('metagen_suggestions')
    op.drop_table('metagen_runs')
