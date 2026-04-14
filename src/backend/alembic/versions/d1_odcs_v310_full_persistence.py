"""ODCS v3.1.0 full persistence: relationships, team metadata, stable IDs

Adds new tables for schema-level and property-level relationships (foreign
keys), team object metadata, and a stable_id column on all ODCS entity
tables to support round-trip of the v3.1.0 StableId field.  Also adds
a name column to team members.

Revision ID: d1_odcs_v310
Revises: c1_drop_datasets
Create Date: 2026-03-30
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d1_odcs_v310"
down_revision: Union[str, None] = "c1_drop_datasets"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Tables that get a new nullable stable_id column
_STABLE_ID_TABLES = [
    "data_contract_servers",
    "data_contract_schema_objects",
    "data_contract_schema_properties",
    "data_contract_support",
    "data_contract_quality_checks",
    "data_contract_authoritative_definitions",
    "data_contract_custom_properties",
    "data_contract_roles",
    "data_contract_sla_properties",
    "data_contract_team",
    "data_contract_schema_object_authoritative_definitions",
    "data_contract_schema_object_custom_properties",
    "data_contract_schema_property_authoritative_definitions",
]


def upgrade() -> None:
    # --- New tables ---

    op.create_table(
        "data_contract_schema_object_relationships",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("schema_object_id", sa.String(), sa.ForeignKey("data_contract_schema_objects.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("relationship_type", sa.String(), nullable=False, server_default="foreignKey"),
        sa.Column("from_value", sa.Text(), nullable=False),
        sa.Column("to_value", sa.Text(), nullable=False),
        sa.Column("custom_properties_json", sa.Text(), nullable=True),
    )

    op.create_table(
        "data_contract_schema_property_relationships",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("property_id", sa.String(), sa.ForeignKey("data_contract_schema_properties.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("relationship_type", sa.String(), nullable=False, server_default="foreignKey"),
        sa.Column("to_value", sa.Text(), nullable=False),
        sa.Column("custom_properties_json", sa.Text(), nullable=True),
    )

    op.create_table(
        "data_contract_team_metadata",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("contract_id", sa.String(), sa.ForeignKey("data_contracts.id", ondelete="CASCADE"), nullable=False, unique=True, index=True),
        sa.Column("stable_id", sa.String(), nullable=True),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("tags_json", sa.Text(), nullable=True),
        sa.Column("custom_properties_json", sa.Text(), nullable=True),
        sa.Column("authoritative_definitions_json", sa.Text(), nullable=True),
    )

    # --- stable_id on existing tables ---

    for table in _STABLE_ID_TABLES:
        op.add_column(table, sa.Column("stable_id", sa.String(), nullable=True))

    # --- name on team members ---

    op.add_column("data_contract_team", sa.Column("name", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("data_contract_team", "name")

    for table in _STABLE_ID_TABLES:
        op.drop_column(table, "stable_id")

    op.drop_table("data_contract_team_metadata")
    op.drop_table("data_contract_schema_property_relationships")
    op.drop_table("data_contract_schema_object_relationships")
