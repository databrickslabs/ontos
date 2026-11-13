"""Add Lifecycle Stage Groups and assign every product, contract and asset to one

Lifecycle stages were hardcoded transition maps (#1208). This adds the tables
``lifecycle_stage_groups`` (one entity type each, one default per type),
``lifecycle_stages`` (key, label, Stage Category, colour, order, initial flag)
and ``lifecycle_stage_transitions`` (from -> to), and the column
``lifecycle_stage_group_id`` on ``data_products``, ``data_contracts`` and
``assets``. ``status`` keeps the stage key, so workflow rules on
``from_status`` / ``to_status`` keep matching.

Seed: one default group per entity type reproducing the transition maps of the
code before this revision (categories: sandbox -> draft; proposed,
under_review, approved -> review). Backfill: every existing row gets its
type's default group. Downgrade drops the column and the tables (the stage keys
stay in ``status``).

Revision ID: t1_lifecycle_stage_groups
Revises: r2_canonical_relationship_types
Create Date: 2026-11-12
"""
import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "t1_lifecycle_stage_groups"
down_revision: Union[str, Sequence[str], None] = "r2_canonical_relationship_types"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ENTITY_TABLES = {
    "data_product": "data_products",
    "data_contract": "data_contracts",
    "asset": "assets",
}

# Frozen copy of src.common.lifecycle_defaults for this revision.
GROUP_IDS = {
    "data_product": "717c78be-b81b-501f-9851-4f1fc7313f17",
    "data_contract": "67dd0305-a4d4-5e3b-92d6-6f1f7955b565",
    "asset": "587296b9-5b92-5880-be60-5a1b2f299ed5",
}
GROUP_NAMES = {
    "data_product": "Default data product lifecycle",
    "data_contract": "Default data contract lifecycle",
    "asset": "Default asset lifecycle",
}
STAGES = {  # key -> (label, category, colour)
    "draft": ("Draft", "draft", "gray"),
    "sandbox": ("Sandbox", "draft", "purple"),
    "proposed": ("Proposed", "review", "blue"),
    "under_review": ("Under Review", "review", "amber"),
    "approved": ("Approved", "review", "teal"),
    "active": ("Active", "active", "green"),
    "deprecated": ("Deprecated", "deprecated", "orange"),
    "retired": ("Retired", "retired", "red"),
}
TRANSITIONS = {
    "data_product": {
        "draft": ["sandbox", "proposed", "deprecated"],
        "sandbox": ["draft", "proposed", "deprecated"],
        "proposed": ["draft", "under_review", "deprecated"],
        "under_review": ["draft", "approved", "deprecated"],
        "approved": ["active", "draft", "deprecated"],
        "active": ["deprecated"],
        "deprecated": ["retired", "active"],
        "retired": [],
    },
    "data_contract": {
        "draft": ["proposed", "deprecated"],
        "proposed": ["draft", "under_review", "approved", "deprecated"],
        "under_review": ["draft", "approved", "deprecated"],
        "approved": ["active", "draft", "deprecated"],
        "active": ["deprecated"],
        "deprecated": ["retired", "active"],
        "retired": [],
    },
    "asset": {
        "draft": ["active", "deprecated"],
        "active": ["deprecated"],
        "deprecated": ["retired", "active"],
        "retired": [],
    },
}


def _stage_id(group_id: str, key: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"urn:ontos:lifecycle-stage:{group_id}:{key}"))


def upgrade() -> None:
    groups = op.create_table(
        "lifecycle_stage_groups",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("entity_type", sa.String(50), nullable=False),
        sa.Column("is_default_for_type", sa.Boolean(), nullable=False,
                  server_default=sa.false()),
        sa.Column("created_by", sa.String(255), nullable=True),
        sa.Column("updated_by", sa.String(255), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.Column("updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.UniqueConstraint("entity_type", "name", name="uq_lifecycle_stage_groups_type_name"),
    )
    op.create_index("ix_lifecycle_stage_groups_entity_type", "lifecycle_stage_groups",
                    ["entity_type"])
    op.create_index("uq_lifecycle_stage_groups_default", "lifecycle_stage_groups",
                    ["entity_type"], unique=True,
                    postgresql_where=sa.text("is_default_for_type"),
                    sqlite_where=sa.text("is_default_for_type"))
    stages = op.create_table(
        "lifecycle_stages",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("group_id", sa.String(),
                  sa.ForeignKey("lifecycle_stage_groups.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("label", sa.String(255), nullable=False),
        sa.Column("category", sa.String(20), nullable=False),
        sa.Column("color", sa.String(32), nullable=True),
        sa.Column("order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_initial", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.UniqueConstraint("group_id", "key", name="uq_lifecycle_stages_group_key"),
    )
    op.create_index("ix_lifecycle_stages_group_id", "lifecycle_stages", ["group_id"])
    transitions = op.create_table(
        "lifecycle_stage_transitions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("group_id", sa.String(),
                  sa.ForeignKey("lifecycle_stage_groups.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("from_stage_id", sa.String(),
                  sa.ForeignKey("lifecycle_stages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("to_stage_id", sa.String(),
                  sa.ForeignKey("lifecycle_stages.id", ondelete="CASCADE"), nullable=False),
        sa.UniqueConstraint("from_stage_id", "to_stage_id",
                            name="uq_lifecycle_stage_transitions"),
    )
    op.create_index("ix_lifecycle_stage_transitions_group_id", "lifecycle_stage_transitions",
                    ["group_id"])

    group_rows, stage_rows, transition_rows = [], [], []
    for entity_type, transition_map in TRANSITIONS.items():
        group_id = GROUP_IDS[entity_type]
        group_rows.append({
            "id": group_id, "name": GROUP_NAMES[entity_type],
            "description": "Seeded lifecycle; reproduces the built-in transitions.",
            "entity_type": entity_type, "is_default_for_type": True,
            "created_by": "system", "updated_by": "system",
        })
        for order, key in enumerate(transition_map):
            label, category, color = STAGES[key]
            stage_rows.append({
                "id": _stage_id(group_id, key), "group_id": group_id, "key": key,
                "label": label, "category": category, "color": color, "order": order,
                "is_initial": order == 0,
            })
        for src, targets in transition_map.items():
            for dst in targets:
                transition_rows.append({
                    "id": str(uuid.uuid5(uuid.NAMESPACE_URL,
                                         f"urn:ontos:lifecycle-transition:{group_id}:{src}:{dst}")),
                    "group_id": group_id,
                    "from_stage_id": _stage_id(group_id, src),
                    "to_stage_id": _stage_id(group_id, dst),
                })
    op.bulk_insert(groups, group_rows)
    op.bulk_insert(stages, stage_rows)
    op.bulk_insert(transitions, transition_rows)

    for entity_type, table in ENTITY_TABLES.items():
        # Batch mode: plain ALTERs on Postgres, a table copy on SQLite (tests)
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column("lifecycle_stage_group_id", sa.String(), nullable=True))
            batch.create_foreign_key(
                f"fk_{table}_lifecycle_stage_group", "lifecycle_stage_groups",
                ["lifecycle_stage_group_id"], ["id"], ondelete="RESTRICT",
            )
            batch.create_index(f"ix_{table}_lifecycle_stage_group_id",
                               ["lifecycle_stage_group_id"])
        op.execute(
            sa.text(
                f"UPDATE {table} SET lifecycle_stage_group_id = :group_id "
                "WHERE lifecycle_stage_group_id IS NULL"
            ).bindparams(group_id=GROUP_IDS[entity_type])
        )


def downgrade() -> None:
    for table in reversed(list(ENTITY_TABLES.values())):
        with op.batch_alter_table(table) as batch:
            batch.drop_index(f"ix_{table}_lifecycle_stage_group_id")
            batch.drop_constraint(f"fk_{table}_lifecycle_stage_group", type_="foreignkey")
            batch.drop_column("lifecycle_stage_group_id")
    op.drop_index("ix_lifecycle_stage_transitions_group_id",
                  table_name="lifecycle_stage_transitions")
    op.drop_table("lifecycle_stage_transitions")
    op.drop_index("ix_lifecycle_stages_group_id", table_name="lifecycle_stages")
    op.drop_table("lifecycle_stages")
    op.drop_index("uq_lifecycle_stage_groups_default", table_name="lifecycle_stage_groups")
    op.drop_index("ix_lifecycle_stage_groups_entity_type", table_name="lifecycle_stage_groups")
    op.drop_table("lifecycle_stage_groups")
