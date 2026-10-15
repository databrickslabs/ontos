"""add can_adopt_entity_ids to app_roles

Revision ID: b1_add_adopt_entity_ids
Revises: n1_search_documents
Create Date: 2026-10-08 16:57:52.814651

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b1_add_adopt_entity_ids'
down_revision: Union[str, None] = 'n1_search_documents'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add can_adopt_entity_ids boolean column to app_roles (#853 review).

    Per-role privilege that gates adopting an entity's UUID from an imported
    file as the primary key. Defaults to false so existing roles are safe.
    """
    op.add_column(
        'app_roles',
        sa.Column(
            'can_adopt_entity_ids',
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
            comment='Whether this role may adopt entity IDs on import',
        ),
    )


def downgrade() -> None:
    """Drop can_adopt_entity_ids column from app_roles."""
    op.drop_column('app_roles', 'can_adopt_entity_ids')
