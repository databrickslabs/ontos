"""Add is_keyless_default to mcp_tokens for keyless MCP access

Adds the ``is_keyless_default`` boolean column (plus a matching index) to
``mcp_tokens``. When an MCP request carries no X-API-Key but has cleared the
Databricks app-gate, it is resolved to the single active token flagged here.
Defaults to false, so keyless access is off until an admin designates a default.

Revision ID: m1_mcp_keyless_default
Revises: l1_entity_domain_associations
Create Date: 2026-09-17
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'm1_mcp_keyless_default'
down_revision: Union[str, Sequence[str], None] = 'l1_entity_domain_associations'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "mcp_tokens"
COLUMN = "is_keyless_default"
INDEX = "ix_mcp_tokens_is_keyless_default"


def _column_exists(conn, table: str, column: str) -> bool:
    return conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = :t AND column_name = :c"
        ),
        {"t": table, "c": column},
    ).scalar() is not None


def _index_exists(conn, index: str) -> bool:
    return conn.execute(
        sa.text("SELECT 1 FROM pg_indexes WHERE indexname = :i"),
        {"i": index},
    ).scalar() is not None


def upgrade() -> None:
    conn = op.get_bind()
    if not _column_exists(conn, TABLE, COLUMN):
        op.add_column(
            TABLE,
            sa.Column(
                COLUMN,
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
                comment="Keyless default token: resolves app-gate MCP requests with no X-API-Key",
            ),
        )
    if not _index_exists(conn, INDEX):
        op.create_index(INDEX, TABLE, [COLUMN])


def downgrade() -> None:
    conn = op.get_bind()
    if _index_exists(conn, INDEX):
        op.drop_index(INDEX, table_name=TABLE)
    if _column_exists(conn, TABLE, COLUMN):
        op.drop_column(TABLE, COLUMN)
