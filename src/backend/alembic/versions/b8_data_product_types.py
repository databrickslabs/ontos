"""add data_product_types table and data_products.product_type_id

Revision ID: b8_data_product_types
Revises: b7_workflow_step_results_kept
Create Date: 2026-10-26 12:00:00.000000

"""

from collections.abc import Sequence
from uuid import uuid4

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

# revision identifiers, used by Alembic.
revision: str = "b8_data_product_types"
down_revision: str | None = "b7_workflow_step_results_kept"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FK = "fk_data_products_product_type_id"
_INDEX = "ix_data_products_product_type_id"

# Kept in step with SEEDED_TYPES in src/repositories/data_product_types_repository.py.
_SEED = [
    {
        "key": "source-aligned",
        "label": "Source-Aligned",
        "description": "Exposes data from a source system with minimal transformation",
        "icon": "database",
        "sort_order": 1,
        "is_default": True,
    },
    {
        "key": "aggregate",
        "label": "Aggregate",
        "description": "Combines several products into a new, reusable view",
        "icon": "layers",
        "sort_order": 2,
        "is_default": False,
    },
    {
        "key": "consumer-aligned",
        "label": "Consumer-Aligned",
        "description": "Shaped for a specific consumer or use case",
        "icon": "users",
        "sort_order": 3,
        "is_default": False,
    },
    {
        "key": "source",
        "label": "Source",
        "description": "Raw source of data entering the platform",
        "icon": "arrow-down-to-line",
        "sort_order": 4,
        "is_default": False,
    },
    {
        "key": "sink",
        "label": "Sink",
        "description": "Final destination of data leaving the platform",
        "icon": "arrow-up-from-line",
        "sort_order": 5,
        "is_default": False,
    },
]


def upgrade() -> None:
    op.create_table(
        "data_product_types",
        sa.Column("id", PG_UUID(as_uuid=True), primary_key=True),
        sa.Column("key", sa.String(100), nullable=False, unique=True),
        sa.Column("label", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("icon", sa.String(100), nullable=True),
        sa.Column("color", sa.String(50), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_imported", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )

    data_product_types = sa.table(
        "data_product_types",
        sa.column("id", PG_UUID(as_uuid=True)),
        sa.column("key", sa.String()),
        sa.column("label", sa.String()),
        sa.column("description", sa.Text()),
        sa.column("icon", sa.String()),
        sa.column("sort_order", sa.Integer()),
        sa.column("is_default", sa.Boolean()),
    )
    op.bulk_insert(data_product_types, [{"id": uuid4(), **row} for row in _SEED])

    op.add_column(
        "data_products", sa.Column("product_type_id", PG_UUID(as_uuid=True), nullable=True)
    )
    op.create_index(_INDEX, "data_products", ["product_type_id"])
    op.create_foreign_key(
        _FK,
        "data_products",
        "data_product_types",
        ["product_type_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(_FK, "data_products", type_="foreignkey")
    op.drop_index(_INDEX, table_name="data_products")
    op.drop_column("data_products", "product_type_id")
    op.drop_table("data_product_types")
