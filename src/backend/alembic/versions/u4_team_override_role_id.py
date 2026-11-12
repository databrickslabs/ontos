"""Store team member role overrides by role id

Revision ID: u4_team_override_role_id
Revises: s1_workflow_is_customized
Create Date: 2026-11-12

Team entries stored the role name, so renaming or deleting a role dropped its
overrides silently, and a role created later under an old name brought them back.
This stores the role id in ``app_role_override_id`` (a foreign key, cleared when the
role is deleted) and drops the name column.

Names are matched to roles exactly, after trimming, as the resolver read them. A name
that matches no role leaves the override empty and is logged; the resolver already
ignored such names. Downgrade writes the current role names back.
"""
import logging
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'u4_team_override_role_id'
down_revision: Union[str, None] = 's1_workflow_is_customized'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

logger = logging.getLogger("alembic.runtime.migration")

_FK = 'fk_team_members_app_role_override_id'
_INDEX = 'ix_team_members_lower_identifier'


def upgrade() -> None:
    conn = op.get_bind()
    role_ids: dict = {}
    for role_id, name in conn.execute(sa.text("SELECT id, name FROM app_roles ORDER BY id")).all():
        role_ids.setdefault(name, role_id)

    with op.batch_alter_table('team_members') as batch:
        batch.add_column(sa.Column('app_role_override_id', sa.String(), nullable=True))
        batch.create_foreign_key(_FK, 'app_roles', ['app_role_override_id'], ['id'], ondelete='SET NULL')

    rows = conn.execute(sa.text(
        "SELECT id, team_id, member_identifier, app_role_override FROM team_members "
        "WHERE app_role_override IS NOT NULL"
    )).all()
    for member_id, team_id, identifier, name in rows:
        key = (name or '').strip()
        if not key:
            continue
        role_id = role_ids.get(key)
        if role_id is None:
            logger.warning(
                "Team %s member %s has role override '%s' that matches no app role; the override is cleared",
                team_id, identifier, key,
            )
        conn.execute(
            sa.text("UPDATE team_members SET app_role_override_id = :role_id WHERE id = :id"),
            {'role_id': role_id, 'id': member_id},
        )

    with op.batch_alter_table('team_members') as batch:
        batch.drop_column('app_role_override')

    op.create_index(_INDEX, 'team_members', [sa.text('lower(member_identifier)')])


def downgrade() -> None:
    conn = op.get_bind()
    op.drop_index(_INDEX, table_name='team_members')

    with op.batch_alter_table('team_members') as batch:
        batch.add_column(sa.Column('app_role_override', sa.String(), nullable=True))

    names = dict(conn.execute(sa.text("SELECT id, name FROM app_roles")).all())
    rows = conn.execute(sa.text(
        "SELECT id, app_role_override_id FROM team_members WHERE app_role_override_id IS NOT NULL"
    )).all()
    for member_id, role_id in rows:
        conn.execute(
            sa.text("UPDATE team_members SET app_role_override = :name WHERE id = :id"),
            {'name': names.get(role_id), 'id': member_id},
        )

    with op.batch_alter_table('team_members') as batch:
        batch.drop_constraint(_FK, type_='foreignkey')
        batch.drop_column('app_role_override_id')
