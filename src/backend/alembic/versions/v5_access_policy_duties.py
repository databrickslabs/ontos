"""Access Policies: duties fulfilled on an Agreement

Revision ID: v5_access_policy_duties
Revises: v4_access_policy_subject
Create Date: 2026-10-24
"""
import sqlalchemy as sa
from alembic import op

revision = 'v5_access_policy_duties'
down_revision = 'v4_access_policy_subject'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('access_policies', sa.Column('fulfilled_duties', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('access_policies', 'fulfilled_duties')
