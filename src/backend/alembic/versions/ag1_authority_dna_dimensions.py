"""Add multi-dimensional DNA-Coefficient columns

Revision ID: ag1_authority_dna_dimensions
Revises: af1_authority_participant_roles
Create Date: 2026-09-25

The DNA-Coefficient is now multi-dimensional: each criterion carries a
``dimension`` (people|policy|…), evidence divergence is scored per dimension, a
built-in ``structural`` dimension scores the AR definition's completeness, and the
overall is the additive combine ``min(1.0, Σ dimension_scores)``.

Adds ``authority_criteria.dimension``, ``authority_dna_runs.per_dimension_scores``
(JSON, this run's breakdown), and ``authority_relations.dna_dimensions`` (JSON,
aggregate breakdown). Additive; no backfill.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'ag1_authority_dna_dimensions'
down_revision: Union[str, None] = 'af1_authority_participant_roles'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('authority_criteria',
                  sa.Column('dimension', sa.String(), nullable=False, server_default='people'))
    op.add_column('authority_dna_runs', sa.Column('per_dimension_scores', sa.JSON(), nullable=True))
    op.add_column('authority_relations', sa.Column('dna_dimensions', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('authority_relations', 'dna_dimensions')
    op.drop_column('authority_dna_runs', 'per_dimension_scores')
    op.drop_column('authority_criteria', 'dimension')
