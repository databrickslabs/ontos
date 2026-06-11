"""merge aa1_term_mapping, c1_maturity and g3_review_title heads

Revision ID: k1_merge_aa1_c1_g3
Revises: aa1_term_mapping, c1_maturity, g3_review_title
Create Date: 2026-06-11

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'k1_merge_aa1_c1_g3'
down_revision: Union[str, Sequence[str], None] = (
    'aa1_term_mapping',
    'c1_maturity',
    'g3_review_title',
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
