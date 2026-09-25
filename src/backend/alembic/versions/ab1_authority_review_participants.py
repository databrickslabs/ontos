"""Add reviewer/approver participant facets to authority_affirmations

Revision ID: ab1_authority_review
Revises: aa1_authority_resolution
Create Date: 2026-09-23

Extends the AR participant table so a principal can be an approver (affirmation
gate), a reviewer (interviewee in the review process), or both — and captures
each reviewer's review status, elicited answers, and linked Asset Review request.
All columns are nullable/defaulted; no backfill (existing rows are approvers).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'ab1_authority_review'
down_revision: Union[str, None] = 'aa1_authority_resolution'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('authority_affirmations', sa.Column('is_approver', sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column('authority_affirmations', sa.Column('is_reviewer', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('authority_affirmations', sa.Column('review_status', sa.String(), nullable=False, server_default='na'))
    op.add_column('authority_affirmations', sa.Column('review_answers', sa.JSON(), nullable=True))
    op.add_column('authority_affirmations', sa.Column('review_request_id', sa.String(), nullable=True))
    op.create_index('ix_authority_affirmations_review_request', 'authority_affirmations', ['review_request_id'])


def downgrade() -> None:
    op.drop_index('ix_authority_affirmations_review_request', table_name='authority_affirmations')
    op.drop_column('authority_affirmations', 'review_request_id')
    op.drop_column('authority_affirmations', 'review_answers')
    op.drop_column('authority_affirmations', 'review_status')
    op.drop_column('authority_affirmations', 'is_reviewer')
    op.drop_column('authority_affirmations', 'is_approver')
