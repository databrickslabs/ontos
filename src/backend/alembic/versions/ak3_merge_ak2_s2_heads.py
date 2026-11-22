"""merge ak2_merge_ak1_s1 and s2_document_markdown_import heads

Joins the Authority Resolution chain with development's chain again after
merging development into the ARF branch (2026-11-22).

Revision ID: ak3_merge_ak2_s2
Revises: ak2_merge_ak1_s1, s2_document_markdown_import
Create Date: 2026-11-22

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ak3_merge_ak2_s2'
down_revision: Union[str, None] = ('ak2_merge_ak1_s1', 's2_document_markdown_import')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
