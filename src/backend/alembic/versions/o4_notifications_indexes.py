"""index notifications on (action_type, read) and (created_at, id)

Revision ID: o4_notifications_indexes
Revises: o3_canonical_cost_centers
Create Date: 2026-11-23 20:00:00.000000

On PostgreSQL the indexes are built with ``CREATE INDEX CONCURRENTLY`` so writes to
``notifications`` are not blocked, and each step is safe to re-run: a failed concurrent
build leaves an INVALID index behind, which is dropped and rebuilt on the next run. Other
dialects (SQLite) use a plain ``CREATE INDEX IF NOT EXISTS``.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'o4_notifications_indexes'
down_revision: Union[str, None] = 'o3_canonical_cost_centers'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = 'notifications'
_INDEXES = (
    ('ix_notifications_action_type_read', ['action_type', 'read']),
    ('ix_notifications_created_at_id', ['created_at', 'id']),
)


def _is_postgres() -> bool:
    return op.get_context().dialect.name == 'postgresql'


def _index_state(name: str) -> bool | None:
    """True = valid, False = INVALID (failed concurrent build), None = absent.

    ``to_regclass`` resolves the name through the connection's search_path, so it also
    works when the app migrates inside a non-default schema.
    """
    return op.get_bind().execute(
        sa.text('SELECT indisvalid FROM pg_index WHERE indexrelid = to_regclass(:name)'),
        {'name': name},
    ).scalar()


def _create(name: str, columns: list[str]) -> None:
    if not _is_postgres():
        op.create_index(name, _TABLE, columns, if_not_exists=True)
        return
    # CONCURRENTLY cannot run inside a transaction block.
    with op.get_context().autocommit_block():
        if not op.get_context().as_sql and _index_state(name) is False:
            op.drop_index(name, table_name=_TABLE, if_exists=True, postgresql_concurrently=True)
        op.create_index(
            name, _TABLE, columns, if_not_exists=True, postgresql_concurrently=True,
        )


def _drop(name: str) -> None:
    if not _is_postgres():
        op.drop_index(name, table_name=_TABLE, if_exists=True)
        return
    with op.get_context().autocommit_block():
        op.drop_index(name, table_name=_TABLE, if_exists=True, postgresql_concurrently=True)


def upgrade() -> None:
    for name, columns in _INDEXES:
        _create(name, columns)


def downgrade() -> None:
    for name, _columns in reversed(_INDEXES):
        _drop(name)
