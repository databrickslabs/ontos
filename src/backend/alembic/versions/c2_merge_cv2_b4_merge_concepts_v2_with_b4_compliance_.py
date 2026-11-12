"""merge concepts-v2 with b4 compliance run error code

Revision ID: c2_merge_cv2_b4
Revises: c1_merge_cv2_dev, b4_compliance_run_error_code
Create Date: 2026-10-23 10:54:04.278232

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c2_merge_cv2_b4'
down_revision: Union[str, None] = ('c1_merge_cv2_dev', 'b4_compliance_run_error_code')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
