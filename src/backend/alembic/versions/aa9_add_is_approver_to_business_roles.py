"""Add is_approver column to business_roles

Revision ID: aa9_is_approver
Revises: z8_fix_nulls
Create Date: 2026-04-20
"""
from alembic import op
import sqlalchemy as sa

revision = 'aa9_is_approver'
down_revision = 'z8_fix_nulls'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('business_roles', sa.Column('is_approver', sa.Boolean(), nullable=False, server_default=sa.text('false')))
    op.create_index(op.f('ix_business_roles_is_approver'), 'business_roles', ['is_approver'])


def downgrade() -> None:
    op.drop_index(op.f('ix_business_roles_is_approver'), table_name='business_roles')
    op.drop_column('business_roles', 'is_approver')
