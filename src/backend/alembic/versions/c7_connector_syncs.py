"""connector syncs: scheduled re-imports of a Schema Importer selection

A saved selection of a connection that the connector_sync job imports again on
a schedule, retiring assets the source no longer has (#1312). Import runs record
the sync that started them.

Revision ID: c7_connector_syncs
Revises: c6_metric_view_baselines
Create Date: 2026-11-06 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'c7_connector_syncs'
down_revision: Union[str, None] = 'c6_metric_view_baselines'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'connector_syncs',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('connection_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('request', postgresql.JSON(astext_type=sa.Text()), nullable=False),
        sa.Column('interval_minutes', sa.Integer(), nullable=False, server_default='1440'),
        sa.Column('retire_after_misses', sa.Integer(), nullable=False, server_default='3'),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('last_run_id', sa.String(), nullable=True),
        sa.Column('last_run_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_status', sa.String(), nullable=True),
        sa.Column('last_complete_sync_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('next_due_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_by', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(['connection_id'], ['connections.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_connector_syncs_connection_id', 'connector_syncs', ['connection_id'])
    op.create_index('ix_connector_syncs_next_due_at', 'connector_syncs', ['next_due_at'])

    op.add_column('schema_import_runs', sa.Column('sync_id', sa.String(), nullable=True))
    op.add_column('schema_import_runs', sa.Column('trigger', sa.String(), nullable=True))
    op.create_index('ix_schema_import_runs_sync_id', 'schema_import_runs', ['sync_id'])


def downgrade() -> None:
    op.drop_index('ix_schema_import_runs_sync_id', table_name='schema_import_runs')
    op.drop_column('schema_import_runs', 'trigger')
    op.drop_column('schema_import_runs', 'sync_id')
    op.drop_index('ix_connector_syncs_next_due_at', table_name='connector_syncs')
    op.drop_index('ix_connector_syncs_connection_id', table_name='connector_syncs')
    op.drop_table('connector_syncs')
