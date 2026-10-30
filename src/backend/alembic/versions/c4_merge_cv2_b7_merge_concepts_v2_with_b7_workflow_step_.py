"""merge concepts-v2 with b7 workflow step results kept

Revision ID: c4_merge_cv2_b7
Revises: c3_merge_cv2_b6, b7_workflow_step_results_kept
Create Date: 2026-10-26 10:00:24.591340

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4_merge_cv2_b7'
down_revision: Union[str, None] = ('c3_merge_cv2_b6', 'b7_workflow_step_results_kept')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
