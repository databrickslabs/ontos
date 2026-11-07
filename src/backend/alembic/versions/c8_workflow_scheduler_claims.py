"""add scheduler_claims for exactly-once scheduled workflow runs

One row per run of a scheduled task (#941): the app instance whose insert
succeeds (``ON CONFLICT DO NOTHING`` on the primary key) runs the slot.

Revision ID: c8_workflow_scheduler_claims
Revises: c7_metric_view_change_requests
Create Date: 2026-11-04 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c8_workflow_scheduler_claims'
down_revision: Union[str, None] = 'c7_metric_view_change_requests'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'scheduler_claims',
        sa.Column('task_key', sa.String(length=255), nullable=False),
        sa.Column('slot', sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column('claimed_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.Column('claimed_by', sa.String(length=255), nullable=True),
        sa.Column('execution_id', sa.String(), nullable=True),
        sa.Column('outcome', sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint('task_key', 'slot', name='pk_scheduler_claims'),
    )


def downgrade() -> None:
    op.drop_table('scheduler_claims')
