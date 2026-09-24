"""Add schema_import_runs table (async Schema Importer run state)

Creates the ``schema_import_runs`` table that backs the async Schema Importer's
in-app background execution (mirrors ``ontology_generation_runs``). A run row
tracks status, live progress counters, the ImportRequest payload, the final
ImportResult blob, and the JOB_PROGRESS notification id.

Revision ID: m2_schema_import_runs
Revises: m1_assigned_users
Create Date: 2026-09-19
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "m2_schema_import_runs"
down_revision: Union[str, Sequence[str], None] = "m1_assigned_users"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "schema_import_runs"


def _table_exists(conn, name: str) -> bool:
    return conn.execute(
        sa.text("SELECT 1 FROM information_schema.tables WHERE table_name = :n"),
        {"n": name},
    ).scalar() is not None


def upgrade() -> None:
    conn = op.get_bind()
    if _table_exists(conn, TABLE):
        return

    op.create_table(
        TABLE,
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("progress_message", sa.String(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("connection_id", sa.String(), nullable=True),
        sa.Column("request", sa.JSON(), nullable=True),
        sa.Column("total_items", sa.Integer(), nullable=True),
        sa.Column("processed_items", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("notification_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index("ix_schema_import_runs_user_id", TABLE, ["user_id"])
    op.create_index("ix_schema_import_runs_user_status", TABLE, ["user_id", "status"])
    op.create_index("ix_schema_import_runs_user_created", TABLE, ["user_id", "created_at"])


def downgrade() -> None:
    conn = op.get_bind()
    if _table_exists(conn, TABLE):
        op.drop_table(TABLE)
