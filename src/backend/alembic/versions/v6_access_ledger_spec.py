"""Grant Ledger: keep the definition of tracked UC ABAC policies

Revision ID: v6_access_ledger_spec
Revises: v5_access_policy_duties
Create Date: 2026-10-24
"""
import sqlalchemy as sa
from alembic import op

revision = 'v6_access_ledger_spec'
down_revision = 'v5_access_policy_duties'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('access_grant_ledger', sa.Column('spec', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('access_grant_ledger', 'spec')
