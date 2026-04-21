"""Add quality_items table

Revision ID: a3_quality_items
Revises: a2_drop_policies_tables
Create Date: 2026-02-17
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID


revision: str = "a3_quality_items"
down_revision: Union[str, None] = "z8_fix_nulls"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Guard against partial previous runs where table already exists
    conn = op.get_bind()
    result = conn.execute(sa.text(
        "SELECT 1 FROM information_schema.tables WHERE table_name = 'quality_items'"
    ))
    if result.scalar() is not None:
        return  # Table already exists, skip
    op.create_table(
        "quality_items",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column("entity_type", sa.String(), nullable=False, index=True),
        sa.Column("entity_id", sa.String(), nullable=False, index=True),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("dimension", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False, server_default="manual"),
        sa.Column("score_percent", sa.Float(), nullable=False),
        sa.Column("checks_passed", sa.Integer(), nullable=True),
        sa.Column("checks_total", sa.Integer(), nullable=True),
        sa.Column("measured_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column("updated_by", sa.String(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_quality_items_entity", "quality_items", ["entity_type", "entity_id"])
    op.create_index("ix_quality_items_entity_measured", "quality_items", ["entity_type", "entity_id", "measured_at"])


def downgrade() -> None:
    op.drop_index("ix_quality_items_entity_measured", table_name="quality_items")
    op.drop_index("ix_quality_items_entity", table_name="quality_items")
    op.drop_table("quality_items")
