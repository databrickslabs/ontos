"""Add Business Role reference to authority participants

Revision ID: af1_authority_participant_roles
Revises: ae1_authority_criteria
Create Date: 2026-09-25

Participants now pick an organizational **Business Role** (Settings feature)
instead of a hardcoded role string. Adds ``business_role_id`` (the Business Role
id) and ``role_category`` (governance|technical|business|operational, which drives
the review questionnaire) to ``authority_affirmations``. ``role`` still holds the
cached role-name label. Additive; nullable; no backfill.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'af1_authority_participant_roles'
down_revision: Union[str, None] = 'ae1_authority_criteria'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('authority_affirmations', sa.Column('business_role_id', sa.String(), nullable=True))
    op.add_column('authority_affirmations', sa.Column('role_category', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('authority_affirmations', 'role_category')
    op.drop_column('authority_affirmations', 'business_role_id')
