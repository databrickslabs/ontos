"""store metric view definition change requests

A proposed definition of a Unity Catalog metric view, the base definition it
was written against, its review (status, decision) and its delivery (#1124
phase 3).

Revision ID: c7_metric_view_change_requests
Revises: c6_metric_view_baselines
Create Date: 2026-11-01 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'c7_metric_view_change_requests'
down_revision: Union[str, None] = 'c6_metric_view_baselines'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'metric_view_change_requests',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('asset_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('metric_view_fqn', sa.String(), nullable=False),
        sa.Column('base_definition', sa.Text(), nullable=False),
        sa.Column('base_digest', sa.String(length=64), nullable=False),
        sa.Column('base_owner', sa.String(), nullable=True),
        sa.Column('proposed_definition', sa.Text(), nullable=False),
        sa.Column('proposed_digest', sa.String(length=64), nullable=False),
        sa.Column('justification', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('warnings', sa.JSON(), nullable=True),
        sa.Column('workflow_execution_id', sa.String(), nullable=True),
        sa.Column('delivery_mode', sa.String(length=32), nullable=True),
        sa.Column('delivery_reference', sa.String(), nullable=True),
        sa.Column('delivery_details', sa.JSON(), nullable=True),
        sa.Column('error_code', sa.String(length=64), nullable=True),
        sa.Column('error_params', sa.JSON(), nullable=True),
        sa.Column('requested_by', sa.String(), nullable=False),
        sa.Column('decided_by', sa.String(), nullable=True),
        sa.Column('decision_message', sa.Text(), nullable=True),
        sa.Column('submitted_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('decided_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('delivered_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('applied_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_metric_view_change_requests_asset_id', 'metric_view_change_requests', ['asset_id'],
    )
    op.create_index(
        'ix_metric_view_change_requests_metric_view_fqn', 'metric_view_change_requests',
        ['metric_view_fqn'],
    )
    op.create_index(
        'ix_metric_view_change_requests_status', 'metric_view_change_requests', ['status'],
    )


def downgrade() -> None:
    op.drop_index('ix_metric_view_change_requests_status',
                  table_name='metric_view_change_requests')
    op.drop_index('ix_metric_view_change_requests_metric_view_fqn',
                  table_name='metric_view_change_requests')
    op.drop_index('ix_metric_view_change_requests_asset_id',
                  table_name='metric_view_change_requests')
    op.drop_table('metric_view_change_requests')
