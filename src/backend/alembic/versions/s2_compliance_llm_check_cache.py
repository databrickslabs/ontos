"""Add compliance_llm_check_cache

Revision ID: s2_compliance_llm_check_cache
Revises: r2_canonical_relationship_types
Create Date: 2026-11-12

Verdicts of the LLM_CHECK compliance DSL function, keyed by a sha256 of the
text, the criterion and the serving endpoint, so a rule run again over
unchanged text makes no model call.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 's2_compliance_llm_check_cache'
down_revision: Union[str, None] = 'r2_canonical_relationship_types'
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


def downgrade() -> None:
    op.drop_table('compliance_llm_check_cache')
