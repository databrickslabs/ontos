"""store estates and their sharing policies in the database

Estates were read from a YAML file into a manager created on every request,
so estates created through the API were lost on the next request (#146).

Revision ID: b8_estates_tables
Revises: b7_workflow_step_results_kept
Create Date: 2026-10-19 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b8_estates_tables'
down_revision: Union[str, None] = 'b7_workflow_step_results_kept'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'estates',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('workspace_url', sa.String(), nullable=False),
        sa.Column('cloud_type', sa.String(length=16), nullable=False),
        sa.Column('metastore_name', sa.String(), nullable=False),
        sa.Column('connection_type', sa.String(length=32), nullable=False),
        sa.Column('is_enabled', sa.Boolean(), nullable=False),
        sa.Column('sync_schedule', sa.String(), nullable=False),
        sa.Column('last_sync_time', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_sync_status', sa.String(length=16), nullable=True),
        sa.Column('last_sync_error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('created_by', sa.String(), nullable=True),
        sa.Column('updated_by', sa.String(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )
    op.create_table(
        'estate_sharing_policies',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('estate_id', sa.String(), nullable=False),
        sa.Column('direction', sa.String(length=8), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('resource_type', sa.String(length=32), nullable=False),
        sa.Column('is_enabled', sa.Boolean(), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['estate_id'], ['estates.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_estate_sharing_policies_estate_id', 'estate_sharing_policies', ['estate_id'])
    op.create_table(
        'estate_sharing_rules',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('policy_id', sa.String(), nullable=False),
        sa.Column('filter_type', sa.String(), nullable=False),
        sa.Column('operator', sa.String(length=16), nullable=False),
        sa.Column('filter_value', sa.Text(), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['policy_id'], ['estate_sharing_policies.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_estate_sharing_rules_policy_id', 'estate_sharing_rules', ['policy_id'])


def downgrade() -> None:
    op.drop_index('ix_estate_sharing_rules_policy_id', table_name='estate_sharing_rules')
    op.drop_table('estate_sharing_rules')
    op.drop_index('ix_estate_sharing_policies_estate_id', table_name='estate_sharing_policies')
    op.drop_table('estate_sharing_policies')
    op.drop_table('estates')
