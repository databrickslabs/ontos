"""add the reviewer's comment to description suggestions

Asset Review decisions on Description Suggestions carry a comment (e.g. what
needs clarifying), shown on the Generation Run page (PRD #1184, #1186).

Revision ID: b9_metagen_review_comment
Revises: b8_metadata_generation
Create Date: 2026-10-26 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b9_metagen_review_comment'
down_revision: Union[str, None] = 'b8_metadata_generation'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('metagen_suggestions', sa.Column('review_comment', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('metagen_suggestions', 'review_comment')
