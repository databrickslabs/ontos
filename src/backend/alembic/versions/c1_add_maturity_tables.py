"""Add maturity_levels, maturity_gates, maturity_snapshots tables and entity columns

Revision ID: c1_maturity
Revises: b3_cert_ds_asset
Create Date: 2026-06-02
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID


revision: str = "c1_maturity"
down_revision: Union[str, None] = "g2_ontology_gen_runs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- maturity_levels ---
    op.create_table(
        "maturity_levels",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column("level_order", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("icon", sa.String(100), nullable=True),
        sa.Column("color", sa.String(50), nullable=True),
        sa.Column("entity_type", sa.String(50), nullable=False, server_default="all"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("entity_type", "level_order", name="uq_maturity_level_entity_order"),
        sa.UniqueConstraint("entity_type", "name", name="uq_maturity_level_entity_name"),
    )
    op.create_index("ix_maturity_levels_entity_type", "maturity_levels", ["entity_type"])

    # --- maturity_gates ---
    op.create_table(
        "maturity_gates",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column("maturity_level_id", PG_UUID(as_uuid=True),
                   sa.ForeignKey("maturity_levels.id", ondelete="CASCADE"), nullable=False),
        sa.Column("compliance_policy_id", sa.String(),
                   sa.ForeignKey("compliance_policies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("maturity_level_id", "compliance_policy_id",
                            name="uq_maturity_gate_level_policy"),
    )
    op.create_index("ix_maturity_gates_level_id", "maturity_gates", ["maturity_level_id"])
    op.create_index("ix_maturity_gates_policy_id", "maturity_gates", ["compliance_policy_id"])

    # --- maturity_snapshots ---
    op.create_table(
        "maturity_snapshots",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column("entity_type", sa.String(50), nullable=False),
        sa.Column("entity_id", sa.String(), nullable=False),
        sa.Column("achieved_level_order", sa.Integer(), nullable=True),
        sa.Column("achieved_level_name", sa.String(255), nullable=True),
        sa.Column("total_levels", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("gates_passed", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("gates_total", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("gate_results_json", sa.Text(), nullable=True),
        sa.Column("evaluated_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("evaluated_by", sa.String(), nullable=True),
    )
    op.create_index("ix_maturity_snapshots_entity", "maturity_snapshots",
                     ["entity_type", "entity_id"])

    # --- Cached maturity columns on entity tables ---
    for table_name in ("data_products", "data_contracts"):
        op.add_column(table_name, sa.Column("maturity_level_order", sa.Integer(), nullable=True))
        op.add_column(table_name, sa.Column("maturity_evaluated_at", sa.TIMESTAMP(timezone=True), nullable=True))


def downgrade() -> None:
    for table_name in ("data_products", "data_contracts"):
        op.drop_column(table_name, "maturity_evaluated_at")
        op.drop_column(table_name, "maturity_level_order")

    op.drop_table("maturity_snapshots")
    op.drop_table("maturity_gates")
    op.drop_table("maturity_levels")
