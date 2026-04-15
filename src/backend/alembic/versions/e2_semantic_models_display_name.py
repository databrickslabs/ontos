"""Add display_name to semantic_models for user-facing RDF source titles.

Revision ID: e2_semantic_display_name
Revises: d1_odcs_v310
Create Date: 2026-04-14
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e2_semantic_display_name"
down_revision: Union[str, None] = "d1_odcs_v310"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "semantic_models",
        sa.Column("display_name", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("semantic_models", "display_name")
