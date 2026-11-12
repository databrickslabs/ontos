"""keep the order of a contract's columns and custom properties

Revision ID: b6_contract_item_position
Revises: b5_lifecycle_status_cleanup
Create Date: 2026-10-19 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b6_contract_item_position'
down_revision: Union[str, None] = 'b5_lifecycle_status_cleanup'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# table -> the column its rows are ordered within
_TABLES = {
    'data_contract_schema_properties': 'object_id',
    'data_contract_schema_property_custom_properties': 'property_id',
    'data_contract_schema_object_custom_properties': 'schema_object_id',
}


def upgrade() -> None:
    """Add ``position`` (0-based, within the parent) and fill it with the order
    the rows are read in today (their physical order)."""
    for table, parent in _TABLES.items():
        op.add_column(table, sa.Column(
            'position', sa.Integer(), nullable=True,
            comment='Order within its parent, as in the ODCS document',
        ))
        op.execute(f"""
            UPDATE {table} AS t SET position = o.rn
            FROM (
                SELECT id, ROW_NUMBER() OVER (PARTITION BY {parent} ORDER BY ctid) - 1 AS rn
                FROM {table}
            ) AS o
            WHERE t.id = o.id
        """)


def downgrade() -> None:
    for table in _TABLES:
        op.drop_column(table, 'position')
