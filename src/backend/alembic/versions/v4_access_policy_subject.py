"""Access Policies: the entity a policy is about (e.g. a Data Product's Offer)

Revision ID: v4_access_policy_subject
Revises: v3_access_agreements
Create Date: 2026-10-24
"""
import sqlalchemy as sa
from alembic import op

revision = 'v4_access_policy_subject'
down_revision = 'v3_access_agreements'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('access_policies', sa.Column('subject_entity_type', sa.String(), nullable=True))
    op.add_column('access_policies', sa.Column('subject_entity_id', sa.String(), nullable=True))
    op.create_index('ix_access_policies_subject_entity_type', 'access_policies', ['subject_entity_type'])
    op.create_index('ix_access_policies_subject_entity_id', 'access_policies', ['subject_entity_id'])


def downgrade() -> None:
    op.drop_index('ix_access_policies_subject_entity_id', table_name='access_policies')
    op.drop_index('ix_access_policies_subject_entity_type', table_name='access_policies')
    op.drop_column('access_policies', 'subject_entity_id')
    op.drop_column('access_policies', 'subject_entity_type')
