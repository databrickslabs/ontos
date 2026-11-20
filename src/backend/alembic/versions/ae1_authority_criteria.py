"""Add authority_criteria (author-configurable decision criteria)

Revision ID: ae1_authority_criteria
Revises: ad1_authority_maturity
Create Date: 2026-09-24

Replaces the hardcoded decision predicates (allowed_principals / threshold /
required_cosign / action) with author-configurable **Compliance Checks** attached
to an Authority Relation, mirroring the Maturity-Level -> Compliance-Policy link.
Each row binds a compliance policy (its DSL ASSERT rule is the condition) and
carries the ARF divergence facets (``direction`` + ``weight``) the plain pass/fail
check cannot. Additive; no backfill.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'ae1_authority_criteria'
down_revision: Union[str, None] = 'ad1_authority_maturity'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'authority_criteria',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('relation_id', sa.String(), nullable=False),
        sa.Column('compliance_policy_id', sa.String(), nullable=False),
        sa.Column('direction', sa.String(), nullable=False, server_default='neutral'),
        sa.Column('weight', sa.Float(), nullable=False, server_default='1.0'),
        sa.Column('display_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['relation_id'], ['authority_relations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['compliance_policy_id'], ['compliance_policies.id'], ondelete='CASCADE'),
    )
    op.create_index('ix_authority_criteria_relation_id', 'authority_criteria', ['relation_id'])
    op.create_index('ix_authority_criteria_compliance_policy_id', 'authority_criteria', ['compliance_policy_id'])


def downgrade() -> None:
    op.drop_index('ix_authority_criteria_compliance_policy_id', table_name='authority_criteria')
    op.drop_index('ix_authority_criteria_relation_id', table_name='authority_criteria')
    op.drop_table('authority_criteria')
