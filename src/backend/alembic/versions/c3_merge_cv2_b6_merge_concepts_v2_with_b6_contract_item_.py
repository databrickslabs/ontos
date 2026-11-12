"""merge concepts-v2 with b6 contract item position

Revision ID: c3_merge_cv2_b6
Revises: c2_merge_cv2_b4, b6_contract_item_position
Create Date: 2026-10-23 15:35:42.178935

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3_merge_cv2_b6'
down_revision: Union[str, None] = ('c2_merge_cv2_b4', 'b6_contract_item_position')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
