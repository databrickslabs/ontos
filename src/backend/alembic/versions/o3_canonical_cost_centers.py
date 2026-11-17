"""Normalize and constrain cost center values.

Revision ID: o3_canonical_cost_centers
Revises: o2_step_execution_message
Create Date: 2026-11-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "o3_canonical_cost_centers"
down_revision: str | None = "o2_step_execution_message"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONSTRAINT = "ck_cost_items_cost_center"


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text("""
        UPDATE cost_items
        SET cost_center = CASE
            WHEN upper(trim(cost_center)) IN ('INFRASTRUCTURE', 'HR', 'STORAGE', 'MAINTENANCE', 'OTHER')
                THEN upper(trim(cost_center))
            ELSE 'OTHER'
        END,
        custom_center_name = CASE
            WHEN upper(trim(cost_center)) IN ('INFRASTRUCTURE', 'HR', 'STORAGE', 'MAINTENANCE', 'OTHER')
                THEN custom_center_name
            ELSE coalesce(custom_center_name, initcap(trim(cost_center)))
        END
    """)
    )
    op.create_check_constraint(
        _CONSTRAINT,
        "cost_items",
        "cost_center IN ('INFRASTRUCTURE', 'HR', 'STORAGE', 'MAINTENANCE', 'OTHER')",
    )


def downgrade() -> None:
    op.drop_constraint(_CONSTRAINT, "cost_items", type_="check")
