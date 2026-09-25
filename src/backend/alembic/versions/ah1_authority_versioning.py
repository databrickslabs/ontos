"""Authority Relation versioning parity (DP/DC snapshot model)

Revision ID: ah1_authority_versioning
Revises: ag1_authority_dna_dimensions
Create Date: 2026-09-25

Authority Relations move from mutate-in-place + integer version bump to the
immutable-snapshot model already used by Data Products and Data Contracts:
edits mutate the current row, and an explicit "New Version" clones the
definition into a fresh row in the same ``version_family_id``.

* ``authority_relations.version`` Integer → String (semantic version, e.g. 1.0.0).
* Adds ``parent_relation_id`` (lineage edge), ``base_name`` (stable family label),
  ``change_summary`` and ``draft_owner_id`` — mirroring the DP/DC columns.
* ``authority_decisions.relation_version`` Integer → String (records the semantic
  version of the AR that produced the decision).

No backfill (the schema is wiped on boot in the PoC environment); the type
changes cast any existing values to text.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'ah1_authority_versioning'
down_revision: Union[str, None] = 'ag1_authority_dna_dimensions'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # version: Integer -> String (semantic version string). Cast existing values.
    op.alter_column(
        'authority_relations', 'version',
        existing_type=sa.Integer(),
        type_=sa.String(),
        existing_nullable=False,
        server_default='1.0.0',
        postgresql_using='version::varchar',
    )
    op.add_column('authority_relations', sa.Column('parent_relation_id', sa.String(), nullable=True))
    op.add_column('authority_relations', sa.Column('base_name', sa.String(), nullable=True))
    op.add_column('authority_relations', sa.Column('change_summary', sa.Text(), nullable=True))
    op.add_column('authority_relations', sa.Column('draft_owner_id', sa.String(), nullable=True))
    op.create_index('ix_authority_relations_parent_relation_id', 'authority_relations', ['parent_relation_id'])
    op.create_index('ix_authority_relations_draft_owner_id', 'authority_relations', ['draft_owner_id'])

    op.alter_column(
        'authority_decisions', 'relation_version',
        existing_type=sa.Integer(),
        type_=sa.String(),
        existing_nullable=True,
        postgresql_using='relation_version::varchar',
    )


def downgrade() -> None:
    op.alter_column(
        'authority_decisions', 'relation_version',
        existing_type=sa.String(),
        type_=sa.Integer(),
        existing_nullable=True,
        postgresql_using='relation_version::integer',
    )
    op.drop_index('ix_authority_relations_draft_owner_id', table_name='authority_relations')
    op.drop_index('ix_authority_relations_parent_relation_id', table_name='authority_relations')
    op.drop_column('authority_relations', 'draft_owner_id')
    op.drop_column('authority_relations', 'change_summary')
    op.drop_column('authority_relations', 'base_name')
    op.drop_column('authority_relations', 'parent_relation_id')
    op.alter_column(
        'authority_relations', 'version',
        existing_type=sa.String(),
        type_=sa.Integer(),
        existing_nullable=False,
        server_default='1',
        postgresql_using='version::integer',
    )
