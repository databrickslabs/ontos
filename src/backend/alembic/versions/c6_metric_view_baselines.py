"""store metric view baselines and their drift state

The definition a Unity Catalog metric view is checked against for drift
(normalized spec and digest), when and by which request it was approved, and
the drift state as of the last check (#1124).

Revision ID: c6_metric_view_baselines
Revises: c5_merge_cv2_b8
Create Date: 2026-11-01 01:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = 'c6_metric_view_baselines'
down_revision: Union[str, None] = 'c5_merge_cv2_b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'metric_view_baselines',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('metric_view_fqn', sa.String(), nullable=False),
        sa.Column('definition', sa.JSON(), nullable=False),
        sa.Column('digest', sa.String(length=64), nullable=False),
        sa.Column('approved_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('request_id', sa.String(), nullable=True),
        sa.Column('drift_state', sa.String(length=16), nullable=False),
        sa.Column('observed_digest', sa.String(length=64), nullable=True),
        sa.Column('last_checked_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('created_by', sa.String(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        'ix_metric_view_baselines_metric_view_fqn', 'metric_view_baselines',
        ['metric_view_fqn'], unique=True,
    )


def downgrade() -> None:
    op.drop_index('ix_metric_view_baselines_metric_view_fqn', table_name='metric_view_baselines')
    op.drop_table('metric_view_baselines')
