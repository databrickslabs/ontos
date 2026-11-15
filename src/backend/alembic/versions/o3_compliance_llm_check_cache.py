"""Add compliance_llm_check_cache, the LLM_CHECK call counts of a run, the daily usage

Revision ID: o3_compliance_llm_check_cache
Revises: o2_step_execution_message
Create Date: 2026-11-12

Verdicts of the LLM_CHECK compliance DSL function, keyed by a sha256 of the
text, the criterion and the serving endpoint, so a rule run again over
unchanged text makes no model call. compliance_runs.llm_calls and
llm_cache_hits count a run's model calls and cached verdicts.
compliance_llm_check_usage counts the calls each user started per day
(UTC), for the daily quota. compliance_results.not_evaluated marks the
entities an LLM_CHECK couldn't judge (compliance_runs.not_evaluated_count),
which the run's counts and score leave out.
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
        sa.Column('response_model', sa.String(), nullable=True),
        sa.Column('passed', sa.Boolean(), nullable=False),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('key'),
    )
    op.add_column('compliance_runs', sa.Column('llm_calls', sa.Integer(), nullable=True))
    op.add_column('compliance_runs', sa.Column('llm_cache_hits', sa.Integer(), nullable=True))
    op.add_column(
        'compliance_runs', sa.Column('not_evaluated_count', sa.Integer(), nullable=True),
    )
    op.add_column('compliance_results', sa.Column(
        'not_evaluated', sa.Boolean(), nullable=False, server_default=sa.false(),
    ))
    op.create_table(
        'compliance_llm_check_usage',
        sa.Column('username', sa.String(), nullable=False),
        sa.Column('day', sa.Date(), nullable=False),
        sa.Column('calls', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('username', 'day'),
    )


def downgrade() -> None:
    op.drop_table('compliance_llm_check_usage')
    op.drop_column('compliance_results', 'not_evaluated')
    op.drop_column('compliance_runs', 'not_evaluated_count')
    op.drop_column('compliance_runs', 'llm_cache_hits')
    op.drop_column('compliance_runs', 'llm_calls')
    op.drop_table('compliance_llm_check_cache')
