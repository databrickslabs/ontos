"""Authority Resolution — Policy references (justification metadata)

Revision ID: am1_authority_policies
Revises: al1_authority_scoped_context
Create Date: 2026-11-12

Creates ``authority_policies``: the shared, non-enforcing list of Policy
references an Authority Relation cites for its justification (name, external id,
description, version and its family, validity window, optional URL, owner team,
optional clause-label suggestions). An AR cites one reference
(``authority_relations.authority_policy_id``) and the clause labels it uses
(``policy_clause_refs``); a check can carry a clause label
(``authority_criteria.policy_clause_ref``). Nothing in the table is enforced.

This revision was rewritten in place for ARF 1.2.0 (#1294 batch 5): it had never
shipped, so no deployed database is stamped at it. A database that was migrated
to the earlier shape (approval, lifecycle and document columns) must be recreated.
The downgrade drops the table and the three columns it added, so it is complete.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'am1_authority_policies'
down_revision: Union[str, None] = 'al1_authority_scoped_context'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'authority_policies',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('policy_key', sa.String(), nullable=False),
        sa.Column('version', sa.String(), nullable=False, server_default='1'),
        sa.Column('version_family_id', sa.String(), nullable=True),
        sa.Column('parent_policy_id', sa.String(), nullable=True),
        sa.Column('change_summary', sa.Text(), nullable=True),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('owner_team_id', sa.String(), sa.ForeignKey('teams.id', ondelete='SET NULL'), nullable=True),
        sa.Column('url', sa.String(), nullable=True),
        sa.Column('valid_from', sa.DateTime(timezone=True), nullable=True),
        sa.Column('valid_to', sa.DateTime(timezone=True), nullable=True),
        sa.Column('clauses', sa.JSON(), nullable=True),
        sa.Column('created_by', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index('ix_authority_policies_policy_key', 'authority_policies', ['policy_key'])
    op.create_index('ix_authority_policies_version_family_id', 'authority_policies', ['version_family_id'])
    op.create_index('ix_authority_policies_parent_policy_id', 'authority_policies', ['parent_policy_id'])
    op.create_index('ix_authority_policies_owner_team_id', 'authority_policies', ['owner_team_id'])

    op.add_column('authority_relations', sa.Column('authority_policy_id', sa.String(), nullable=True))
    op.add_column('authority_relations', sa.Column('policy_clause_refs', sa.JSON(), nullable=True))
    op.create_foreign_key(
        'fk_authority_relations_authority_policy_id', 'authority_relations', 'authority_policies',
        ['authority_policy_id'], ['id'], ondelete='SET NULL',
    )
    op.create_index('ix_authority_relations_authority_policy_id', 'authority_relations', ['authority_policy_id'])

    op.add_column('authority_criteria', sa.Column('policy_clause_ref', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('authority_criteria', 'policy_clause_ref')
    # Dropping the column drops its FK and index too (whatever they were named:
    # a create_all-provisioned schema uses the dialect's default FK name).
    op.drop_column('authority_relations', 'policy_clause_refs')
    op.drop_column('authority_relations', 'authority_policy_id')
    op.drop_table('authority_policies')  # its indexes go with it
