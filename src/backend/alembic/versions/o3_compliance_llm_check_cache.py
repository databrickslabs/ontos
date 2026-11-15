"""Add compliance_llm_check_cache and the LLM_CHECK call counts of a run

Revision ID: o3_compliance_llm_check_cache
Revises: o2_step_execution_message
Create Date: 2026-11-12

Verdicts of the LLM_CHECK compliance DSL function, keyed by a sha256 of the
text, the criterion and the serving endpoint, so a rule run again over
unchanged text makes no model call. compliance_runs.llm_calls and
llm_cache_hits count a run's model calls and cached verdicts.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'o3_compliance_llm_check_cache'
down_revision: Union[str, None] = 'o2_step_execution_message'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'compliance_llm_check_cache',
        sa.Column('key', sa.String(length=64), nullable=False),
        sa.Column('model', sa.String(), nullable=False),
        sa.Column('passed', sa.Boolean(), nullable=False),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('key'),
    )
    op.add_column('compliance_runs', sa.Column('llm_calls', sa.Integer(), nullable=True))
    op.add_column('compliance_runs', sa.Column('llm_cache_hits', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('compliance_runs', 'llm_cache_hits')
    op.drop_column('compliance_runs', 'llm_calls')
    op.drop_table('compliance_llm_check_cache')
