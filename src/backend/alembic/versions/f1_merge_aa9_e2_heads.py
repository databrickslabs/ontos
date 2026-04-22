"""merge aa9_is_approver and e2_semantic_display_name heads

Revision ID: f1_merge_aa9_e2
Revises: aa9_is_approver, e2_semantic_display_name
Create Date: 2026-04-22

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f1_merge_aa9_e2'
down_revision: Union[str, None] = ('aa9_is_approver', 'e2_semantic_display_name')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
