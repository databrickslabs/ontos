"""merge concepts-v2 and development heads

Revision ID: c1_merge_cv2_dev
Revises: 1aab20df8f2c, b3_property_custom_props
Create Date: 2026-10-19 14:30:57.554891

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c1_merge_cv2_dev'
down_revision: Union[str, None] = ('1aab20df8f2c', 'b3_property_custom_props')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
