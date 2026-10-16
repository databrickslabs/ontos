"""add property-level custom properties to data contract schemas

ODCS allows customProperties on schema properties (columns) too. Contracts and
schema objects had a table for them, properties didn't, so they were dropped
on import (#609).

Revision ID: b3_property_custom_props
Revises: b2_contract_deploy_default
Create Date: 2026-10-16 22:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b3_property_custom_props'
down_revision: Union[str, None] = 'b2_contract_deploy_default'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = 'data_contract_schema_property_custom_properties'


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('property_id', sa.String(), nullable=False),
        sa.Column('stable_id', sa.String(), nullable=True),
        sa.Column('property', sa.String(), nullable=False),
        sa.Column('value', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ['property_id'], ['data_contract_schema_properties.id'], ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(f'ix_{TABLE}_property_id', TABLE, ['property_id'])


def downgrade() -> None:
    op.drop_index(f'ix_{TABLE}_property_id', table_name=TABLE)
    op.drop_table(TABLE)
