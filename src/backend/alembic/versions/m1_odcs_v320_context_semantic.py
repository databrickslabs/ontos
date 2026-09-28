"""ODCS v3.2.0 support: context block (RFC-0038) + property semanticType

Adds first-class tables for the v3.2.0 context block (AI/semantic guidance)
attached to either a contract root or a schema object, with child tables for
verifiedStatements and constraints. Also adds a ``semantic_type`` column to
schema properties (ODCS semanticType: column|measure|dimension).

Vector (RFC-0042) and map (RFC-0030) logicalTypeOptions need no schema change —
they ride on the existing ``logical_type_options_json`` column.

Revision ID: m1_odcs_v320
Revises: l1_entity_domain_associations
Create Date: 2026-09-20
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "m1_odcs_v320"
down_revision: Union[str, Sequence[str], None] = "l1_entity_domain_associations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- context block tables (RFC-0038) ---

    op.create_table(
        "data_contract_contexts",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("contract_id", sa.String(), sa.ForeignKey("data_contracts.id", ondelete="CASCADE"), nullable=True, unique=True, index=True),
        sa.Column("schema_object_id", sa.String(), sa.ForeignKey("data_contract_schema_objects.id", ondelete="CASCADE"), nullable=True, unique=True, index=True),
        sa.Column("instructions", sa.Text(), nullable=True),
    )

    op.create_table(
        "data_contract_context_verified_statements",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("context_id", sa.String(), sa.ForeignKey("data_contract_contexts.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("stable_id", sa.String(), nullable=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tags_json", sa.Text(), nullable=True),
        sa.Column("authoritative_definitions_json", sa.Text(), nullable=True),
        sa.Column("custom_properties_json", sa.Text(), nullable=True),
    )

    op.create_table(
        "data_contract_context_constraints",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("context_id", sa.String(), sa.ForeignKey("data_contract_contexts.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("stable_id", sa.String(), nullable=True),
        sa.Column("constraint", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tags_json", sa.Text(), nullable=True),
        sa.Column("authoritative_definitions_json", sa.Text(), nullable=True),
        sa.Column("custom_properties_json", sa.Text(), nullable=True),
    )

    # --- property semanticType ---

    op.add_column(
        "data_contract_schema_properties",
        sa.Column("semantic_type", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("data_contract_schema_properties", "semantic_type")
    op.drop_table("data_contract_context_constraints")
    op.drop_table("data_contract_context_verified_statements")
    op.drop_table("data_contract_contexts")
