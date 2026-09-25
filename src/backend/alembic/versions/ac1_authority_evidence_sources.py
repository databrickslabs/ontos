"""Add multi-source evidence to authority_relations

Revision ID: ac1_authority_evidence
Revises: ab1_authority_review
Create Date: 2026-09-24

Adds an ``evidence_sources`` JSON column so an Authority Relation can bind several
typed evidence sources (delta_table | data_product | asset), each with its own
column map. The legacy single ``evidence_binding`` column is retained and used as
a fallback when no sources are declared. Nullable; no backfill.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'ac1_authority_evidence'
down_revision: Union[str, None] = 'ab1_authority_review'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('authority_relations', sa.Column('evidence_sources', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('authority_relations', 'evidence_sources')
