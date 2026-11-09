"""Add hidden_nav_features to app_roles (per-role "show in navigation" flag)

Adds a non-null JSON-text ``hidden_nav_features`` column to ``app_roles``
(default ``'[]'``): the feature ids a role hides from the navigation (sidebar,
home quick actions, About). Empty means every feature is shown, as before, so
existing roles keep their menus. Access levels are not affected (#1325).

Revision ID: r1_role_hidden_nav_features
Revises: b10_compliance_run_warning_code
Create Date: 2026-11-09
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "r1_role_hidden_nav_features"
down_revision: Union[str, Sequence[str], None] = "b10_compliance_run_warning_code"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "app_roles"
COLUMN = "hidden_nav_features"


def _column_exists(conn, table: str, column: str) -> bool:
    return any(col["name"] == column for col in sa.inspect(conn).get_columns(table))


def upgrade() -> None:
    conn = op.get_bind()
    if not _column_exists(conn, TABLE, COLUMN):
        op.add_column(
            TABLE,
            sa.Column(
                COLUMN, sa.Text(), nullable=False, server_default="[]",
                comment="Feature ids this role hides from the navigation (JSON list)",
            ),
        )


def downgrade() -> None:
    conn = op.get_bind()
    if _column_exists(conn, TABLE, COLUMN):
        op.drop_column(TABLE, COLUMN)
