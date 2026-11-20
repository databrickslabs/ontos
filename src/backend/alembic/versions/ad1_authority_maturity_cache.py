"""Add maturity cache columns to authority_relations

Revision ID: ad1_authority_maturity
Revises: ac1_authority_evidence
Create Date: 2026-09-24

Adds ``maturity_level_order`` + ``maturity_evaluated_at`` so Authority Relations
participate in the shared, compliance-gated Maturity Level feature (mirrors the
cache columns on data_products / data_contracts). Nullable; no backfill.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'ad1_authority_maturity'
down_revision: Union[str, None] = 'ac1_authority_evidence'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('authority_relations', sa.Column('maturity_level_order', sa.Integer(), nullable=True))
    op.add_column('authority_relations', sa.Column('maturity_evaluated_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('authority_relations', 'maturity_evaluated_at')
    op.drop_column('authority_relations', 'maturity_level_order')
