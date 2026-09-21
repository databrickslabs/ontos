"""Add assigned_users to app_roles (individual user role assignment)

Adds a non-null JSON-text ``assigned_users`` column to ``app_roles`` (default
``'[]'``), parallel to ``assigned_groups``. Enables assigning individual users to
a role by email and is the mechanism by which approving a role access request
grants the role (#196 / #760 / #311). Backward compatible: existing roles default
to an empty list.

Also acts as the merge point for the two migration heads that landed on
development in parallel off ``l1_entity_domain_associations`` — ``m1_uc_domain_id``
(#761) and ``m1_mcp_keyless_default`` — so the tree keeps a single head. This
revision only adds the column; it depends on both parents purely to unify them.

Revision ID: m1_assigned_users
Revises: m1_uc_domain_id, m1_mcp_keyless_default
Create Date: 2026-09-20
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "m1_assigned_users"
down_revision: Union[str, Sequence[str], None] = ("m1_uc_domain_id", "m1_mcp_keyless_default")
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
