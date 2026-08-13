"""Add compliance templates tables (definition, fields, values)

Revision ID: p1_compliance_templates
Revises: l1_entity_domain_associations
Create Date: 2026-08-13

Introduces the Compliance Templates feature: an admin-defined, typed, grouped
governance-field schema bound to an entity type, plus per-entity filled-in
values stored polymorphically. Three tables:

- compliance_templates        — template definition; at most one active per
  (entity_type, scope_type, scope_id) via a partial unique index.
- compliance_template_fields  — typed fields; groups denormalized onto the field.
- compliance_template_values  — per-entity values, polymorphic + unique per field.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from alembic import op

revision: str = "p1_compliance_templates"
down_revision: str | None = "l1_entity_domain_associations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "compliance_templates",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("entity_type", sa.String(100), nullable=False),
        sa.Column("scope_type", sa.String(50), nullable=False, server_default="all"),
        sa.Column("scope_id", sa.String(255), nullable=False, server_default=""),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_compliance_templates_entity_type", "compliance_templates", ["entity_type"])
    op.create_index("ix_compliance_templates_is_active", "compliance_templates", ["is_active"])
    # At most one ACTIVE template per (entity_type, scope_type, scope_id).
    op.create_index(
        "uq_compliance_template_active_scope",
        "compliance_templates",
        ["entity_type", "scope_type", "scope_id"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )

    op.create_table(
        "compliance_template_fields",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column("template_id", PG_UUID(as_uuid=True), sa.ForeignKey("compliance_templates.id", ondelete="CASCADE"), nullable=False),
        sa.Column("group_title", sa.String(255), nullable=False, server_default=""),
        sa.Column("group_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("key", sa.String(255), nullable=False),
        sa.Column("label", sa.String(255), nullable=False),
        sa.Column("reference_id", sa.String(255), nullable=False),
        sa.Column("value_type", sa.String(50), nullable=False),
        sa.Column("possible_values", sa.JSON(), nullable=True),
        sa.Column("default_value", sa.JSON(), nullable=True),
        sa.Column("hint_text", sa.Text(), nullable=True),
        sa.Column("is_mandatory", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("field_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("constraints", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("template_id", "reference_id", name="uq_compliance_field_reference_id"),
        sa.UniqueConstraint("template_id", "key", name="uq_compliance_field_key"),
    )
    op.create_index("ix_compliance_template_fields_template_id", "compliance_template_fields", ["template_id"])

    op.create_table(
        "compliance_template_values",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column("field_id", PG_UUID(as_uuid=True), sa.ForeignKey("compliance_template_fields.id", ondelete="CASCADE"), nullable=False),
        sa.Column("entity_type", sa.String(100), nullable=False),
        sa.Column("entity_id", sa.String(255), nullable=False),
        sa.Column("value", sa.JSON(), nullable=True),
        sa.Column("filled_by", sa.String(), nullable=True),
        sa.Column("filled_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("field_id", "entity_type", "entity_id", name="uq_compliance_value_field_entity"),
    )
    op.create_index("ix_compliance_template_values_field_id", "compliance_template_values", ["field_id"])
    op.create_index("ix_compliance_template_values_entity_type", "compliance_template_values", ["entity_type"])
    op.create_index("ix_compliance_template_values_entity_id", "compliance_template_values", ["entity_id"])


def downgrade() -> None:
    op.drop_table("compliance_template_values")
    op.drop_table("compliance_template_fields")
    op.drop_index("uq_compliance_template_active_scope", table_name="compliance_templates")
    op.drop_index("ix_compliance_templates_is_active", table_name="compliance_templates")
    op.drop_index("ix_compliance_templates_entity_type", table_name="compliance_templates")
    op.drop_table("compliance_templates")
