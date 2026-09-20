"""Add assigned_users to app_roles (individual user role assignment)

Adds a non-null JSON-text ``assigned_users`` column to ``app_roles`` (default
``'[]'``), parallel to ``assigned_groups``. Enables assigning individual users to
a role by email and is the mechanism by which approving a role access request
grants the role (#196 / #760 / #311). Backward compatible: existing roles default
to an empty list.

Revision ID: m1_assigned_users
Revises: l1_entity_domain_associations
Create Date: 2026-09-20
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "m1_assigned_users"
down_revision: Union[str, Sequence[str], None] = "l1_entity_domain_associations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "app_roles"
COLUMN = "assigned_users"


def _column_exists(conn, table: str, column: str) -> bool:
    return conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = :t AND column_name = :c"
        ),
        {"t": table, "c": column},
    ).scalar() is not None


def upgrade() -> None:
    conn = op.get_bind()
    if not _column_exists(conn, TABLE, COLUMN):
        op.add_column(
            TABLE,
            sa.Column(COLUMN, sa.Text(), nullable=False, server_default="[]"),
        )


def downgrade() -> None:
    conn = op.get_bind()
    if _column_exists(conn, TABLE, COLUMN):
        op.drop_column(TABLE, COLUMN)
