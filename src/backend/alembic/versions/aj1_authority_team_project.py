"""Authority Resolution — owner team + project (parity with Data Products / Contracts)

Revision ID: aj1_authority_team_project
Revises: ai1_authority_graph
Create Date: 2026-10-17

Adds nullable ``owner_team_id`` (-> teams.id) and ``project_id`` (-> projects.id)
to ``authority_relations``. Both are ``ON DELETE SET NULL`` so removing a team
or project never deletes an Authority Relation. No backfill.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'aj1_authority_team_project'
down_revision: Union[str, None] = 'ai1_authority_graph'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('authority_relations', sa.Column('owner_team_id', sa.String(), nullable=True))
    op.add_column('authority_relations', sa.Column('project_id', sa.String(), nullable=True))
    op.create_foreign_key(
        'fk_authority_relations_owner_team_id', 'authority_relations', 'teams',
        ['owner_team_id'], ['id'], ondelete='SET NULL',
    )
    op.create_foreign_key(
        'fk_authority_relations_project_id', 'authority_relations', 'projects',
        ['project_id'], ['id'], ondelete='SET NULL',
    )
    op.create_index('ix_authority_relations_owner_team_id', 'authority_relations', ['owner_team_id'])
    op.create_index('ix_authority_relations_project_id', 'authority_relations', ['project_id'])


def downgrade() -> None:
    op.drop_index('ix_authority_relations_project_id', table_name='authority_relations')
    op.drop_index('ix_authority_relations_owner_team_id', table_name='authority_relations')
    op.drop_constraint('fk_authority_relations_project_id', 'authority_relations', type_='foreignkey')
    op.drop_constraint('fk_authority_relations_owner_team_id', 'authority_relations', type_='foreignkey')
    op.drop_column('authority_relations', 'project_id')
    op.drop_column('authority_relations', 'owner_team_id')
