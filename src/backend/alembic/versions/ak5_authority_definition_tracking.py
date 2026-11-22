"""Track who last changed an AR definition, and the definition hash on runs and affirmations

Revision ID: ak5_authority_definition_tracking
Revises: ak4_authority_resolution_grants
Create Date: 2026-11-22

ARF 1.2.0 batch 2 (#859 review B4, B6).

* ``authority_relations.definition_edited_by``: the user who last changed the
  definition. Nobody affirms a definition they created or last changed.
* ``authority_affirmations.definition_hash``: the canonical hash of the definition
  an affirmation vouches for. Only affirmations whose hash equals the current hash
  count toward activation.
* ``authority_dna_runs.definition_hash``: the hash of the definition a DNA run
  measured. Activation requires the latest run to match the current hash.

Additive; no backfill. Existing affirmations and runs have a NULL hash, so they
do not count toward activation until the AR is measured and affirmed again.
Downgrade drops the three columns.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'ak5_authority_definition_tracking'
down_revision: Union[str, None] = 'ak4_authority_resolution_grants'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('authority_relations', sa.Column('definition_edited_by', sa.String(), nullable=True))
    op.add_column('authority_affirmations', sa.Column('definition_hash', sa.String(), nullable=True))
    op.add_column('authority_dna_runs', sa.Column('definition_hash', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('authority_dna_runs', 'definition_hash')
    op.drop_column('authority_affirmations', 'definition_hash')
    op.drop_column('authority_relations', 'definition_edited_by')
