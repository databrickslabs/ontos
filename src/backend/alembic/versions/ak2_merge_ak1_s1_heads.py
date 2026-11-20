"""merge ak1_merge_aj1_b2 and s1_workflow_is_customized heads

Joins the Authority Resolution chain with development's chain again after
merging development into the ARF branch.

Revision ID: ak2_merge_ak1_s1
Revises: ak1_merge_aj1_b2, s1_workflow_is_customized
Create Date: 2026-11-12

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ak2_merge_ak1_s1'
down_revision: Union[str, None] = ('ak1_merge_aj1_b2', 's1_workflow_is_customized')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
