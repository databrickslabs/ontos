"""store the ODCS contract fields that didn't round-trip (#610)

- ``data_contract_schema_properties``: ``physical_name``, ``description`` and
  ``tags`` (JSON array). The import stored a column's ``description`` in
  ``transform_description`` (and dropped ``transformDescription``), so the stored
  values move to ``description`` and ``transform_description`` is emptied.
- ``data_contract_servers``: ``roles_json`` and ``custom_properties_json``
  (the server's ODCS ``roles`` and ``customProperties``, JSON arrays).
- ``stable_id`` (the ODCS ``id``) on ``data_contract_pricing``,
  ``data_contract_role_properties`` and both relationship tables.

Revision ID: r3_odcs_roundtrip_fields
Revises: r2_canonical_relationship_types
Create Date: 2026-11-12 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'r3_odcs_roundtrip_fields'
down_revision: Union[str, None] = 'r2_canonical_relationship_types'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_PROPERTIES = 'data_contract_schema_properties'
_STABLE_ID_TABLES = (
    'data_contract_pricing',
    'data_contract_role_properties',
    'data_contract_schema_object_relationships',
    'data_contract_schema_property_relationships',
)


def upgrade() -> None:
    op.add_column(_PROPERTIES, sa.Column('physical_name', sa.String(), nullable=True))
    op.add_column(_PROPERTIES, sa.Column('description', sa.Text(), nullable=True))
    op.add_column(_PROPERTIES, sa.Column(
        'tags', sa.Text(), nullable=True, comment='ODCS tags of the column (JSON array)'))
    op.execute(
        f"UPDATE {_PROPERTIES} SET description = transform_description, "
        "transform_description = NULL WHERE transform_description IS NOT NULL"
    )

    op.add_column('data_contract_servers', sa.Column(
        'roles_json', sa.Text(), nullable=True, comment='ODCS roles of the server (JSON array)'))
    op.add_column('data_contract_servers', sa.Column(
        'custom_properties_json', sa.Text(), nullable=True,
        comment='ODCS customProperties of the server (JSON array)'))

    for table in _STABLE_ID_TABLES:
        op.add_column(table, sa.Column('stable_id', sa.String(), nullable=True))


def downgrade() -> None:
    for table in _STABLE_ID_TABLES:
        op.drop_column(table, 'stable_id')
    op.drop_column('data_contract_servers', 'custom_properties_json')
    op.drop_column('data_contract_servers', 'roles_json')
    # Back to the old layout: the description in transform_description
    op.execute(
        f"UPDATE {_PROPERTIES} SET transform_description = description "
        "WHERE description IS NOT NULL"
    )
    op.drop_column(_PROPERTIES, 'tags')
    op.drop_column(_PROPERTIES, 'description')
    op.drop_column(_PROPERTIES, 'physical_name')
