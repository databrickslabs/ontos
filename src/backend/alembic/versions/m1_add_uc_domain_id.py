"""Add uc_domain_id to data_domains (UC domain sync)

Adds a nullable, indexed ``uc_domain_id`` column to ``data_domains`` so Ontos
domains can be matched idempotently to Unity Catalog domains across sync runs
(#761). Not unique: unsynced domains have NULL, and a deleted+recreated UC domain
may reuse a name but gets a fresh id.

Revision ID: m1_uc_domain_id
Revises: l1_entity_domain_associations
Create Date: 2026-09-20
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "m1_uc_domain_id"
down_revision: Union[str, Sequence[str], None] = "l1_entity_domain_associations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "data_domains"
COLUMN = "uc_domain_id"
INDEX = "ix_data_domains_uc_domain_id"


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
        op.add_column(TABLE, sa.Column(COLUMN, sa.String(), nullable=True))
        op.create_index(INDEX, TABLE, [COLUMN])


def downgrade() -> None:
    conn = op.get_bind()
    if _column_exists(conn, TABLE, COLUMN):
        op.drop_index(INDEX, table_name=TABLE)
        op.drop_column(TABLE, COLUMN)
