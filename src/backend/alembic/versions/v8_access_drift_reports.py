"""Access Policies: report-only drift reconciliation reports per target

Revision ID: v8_access_drift_reports
Revises: v7_access_targets
Create Date: 2026-10-24
"""
import sqlalchemy as sa
from alembic import op

revision = 'v8_access_drift_reports'
down_revision = 'v7_access_targets'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'access_drift_reports',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('target', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('checked_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('checked_by', sa.String(), nullable=True),
        sa.Column('counts', sa.JSON(), nullable=False),
        sa.Column('report', sa.JSON(), nullable=False),
    )
    op.create_index('ix_access_drift_reports_target', 'access_drift_reports', ['target'])
    op.create_index('ix_access_drift_reports_checked_at', 'access_drift_reports', ['checked_at'])


def downgrade() -> None:
    op.drop_table('access_drift_reports')
