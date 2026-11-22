"""add scheduler_claims for at-most-once scheduled workflow runs

One row per run of a scheduled task (#941): the app instance whose insert
succeeds (``ON CONFLICT DO NOTHING`` on the primary key) runs the slot.
``process_workflows.schedule_changed_at`` records when a workflow's schedule or
``is_active`` last changed; existing rows start at their ``updated_at``.

Revision ID: c8_workflow_scheduler_claims
Revises: o2_step_execution_message
Create Date: 2026-11-04 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c8_workflow_scheduler_claims'
down_revision: Union[str, None] = 'o2_step_execution_message'
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
    op.add_column('process_workflows', sa.Column(
        'schedule_changed_at', sa.TIMESTAMP(timezone=True), nullable=True,
    ))
    op.execute('UPDATE process_workflows SET schedule_changed_at = updated_at')


def downgrade() -> None:
    op.drop_column('process_workflows', 'schedule_changed_at')
    op.drop_table('scheduler_claims')
