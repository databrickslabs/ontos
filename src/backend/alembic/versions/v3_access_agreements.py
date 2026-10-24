"""Link Access Policy Agreements to the Access Grants they record

Revision ID: v3_access_agreements
Revises: v2_access_policy_releases
Create Date: 2026-10-24
"""
import sqlalchemy as sa
from alembic import op

revision = 'v3_access_agreements'
down_revision = 'v2_access_policy_releases'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('access_policies', sa.Column('access_grant_id', sa.String(), nullable=True))
    op.create_index('ix_access_policies_access_grant_id', 'access_policies', ['access_grant_id'])


def downgrade() -> None:
    op.drop_index('ix_access_policies_access_grant_id', table_name='access_policies')
    op.drop_column('access_policies', 'access_grant_id')
