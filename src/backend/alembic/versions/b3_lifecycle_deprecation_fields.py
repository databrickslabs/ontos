"""add deprecation lifecycle fields to data products and data contracts

Revision ID: b3_lifecycle_deprecation_fields
Revises: b2_contract_deploy_default
Create Date: 2026-10-14 03:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3_lifecycle_deprecation_fields'
down_revision: Union[str, None] = 'b2_contract_deploy_default'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLES = {
    'data_products': 'replacement_product_id',
    'data_contracts': 'replacement_contract_id',
}


def upgrade() -> None:
    """Add deprecation_reason, sunset_date, replacement id and deprecated_at.

    All nullable: they are set when an entity moves to ``deprecated`` (see the
    lifecycle tag automation and deprecation PRD).
    """
    for table, replacement_column in _TABLES.items():
        op.add_column(table, sa.Column(
            'deprecation_reason', sa.Text(), nullable=True,
            comment='Why the entity was deprecated',
        ))
        op.add_column(table, sa.Column(
            'sunset_date', sa.Date(), nullable=True,
            comment='Date after which the entity should no longer be used',
        ))
        op.add_column(table, sa.Column(
            replacement_column, sa.String(), nullable=True,
            comment='Entity of the same type that replaces this one',
        ))
        op.add_column(table, sa.Column(
            'deprecated_at', sa.DateTime(timezone=True), nullable=True,
            comment='When the entity was deprecated',
        ))


def downgrade() -> None:
    """Drop the deprecation lifecycle fields."""
    for table, replacement_column in _TABLES.items():
        for column in ('deprecated_at', replacement_column, 'sunset_date', 'deprecation_reason'):
            op.drop_column(table, column)
