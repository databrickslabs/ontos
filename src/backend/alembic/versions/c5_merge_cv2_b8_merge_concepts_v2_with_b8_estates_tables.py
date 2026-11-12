"""merge concepts-v2 with b8 estates tables

Revision ID: c5_merge_cv2_b8
Revises: c4_merge_cv2_b7, b8_estates_tables
Create Date: 2026-10-28 17:13:12.746564

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c5_merge_cv2_b8'
down_revision: Union[str, None] = ('c4_merge_cv2_b7', 'b8_estates_tables')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
