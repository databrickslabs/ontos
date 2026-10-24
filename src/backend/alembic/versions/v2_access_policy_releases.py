"""Add Access Policy releases (compiled deployments) and the Grant Ledger

Revision ID: v2_access_policy_releases
Revises: v1_access_policies
Create Date: 2026-10-17
"""
import sqlalchemy as sa
from alembic import op

revision = 'v2_access_policy_releases'
down_revision = 'v1_access_policies'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'access_policy_releases',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('target', sa.String(), nullable=False),
        sa.Column('sequence', sa.Integer(), nullable=False),
        sa.Column('release_kind', sa.String(), nullable=False, server_default='policy'),
        sa.Column('status', sa.String(), nullable=False, server_default='draft'),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('plan', sa.JSON(), nullable=False),
        sa.Column('changes', sa.JSON(), nullable=False),
        sa.Column('issues', sa.JSON(), nullable=False),
        sa.Column('source_policies', sa.JSON(), nullable=False),
        sa.Column('ledger_fingerprint', sa.String(), nullable=True),
        sa.Column('delivery_modes', sa.JSON(), nullable=True),
        sa.Column('delivery_results', sa.JSON(), nullable=True),
        sa.Column('live_diff', sa.JSON(), nullable=True),
        sa.Column('created_by', sa.String(), nullable=True),
        sa.Column('submitted_by', sa.String(), nullable=True),
        sa.Column('approved_by', sa.String(), nullable=True),
        sa.Column('delivered_by', sa.String(), nullable=True),
        sa.Column('delivered_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('applied_by', sa.String(), nullable=True),
        sa.Column('applied_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('target', 'sequence', name='uq_access_policy_release_seq'),
    )
    op.create_index('ix_access_policy_releases_target', 'access_policy_releases', ['target'])
    op.create_index('ix_access_policy_releases_status', 'access_policy_releases', ['status'])

    op.create_table(
        'access_grant_ledger',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('target', sa.String(), nullable=False),
        sa.Column('principal', sa.String(), nullable=False),
        sa.Column('securable_type', sa.String(), nullable=False),
        sa.Column('securable_name', sa.String(), nullable=False),
        sa.Column('privilege', sa.String(), nullable=False),
        sa.Column('implied', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('preexisting', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('expires_at', sa.String(), nullable=True),
        sa.Column('sources', sa.JSON(), nullable=False),
        sa.Column('legal_basis', sa.String(), nullable=True),
        sa.Column('status', sa.String(), nullable=False, server_default='active'),
        sa.Column('granted_release_id', sa.String(),
                  sa.ForeignKey('access_policy_releases.id', ondelete='SET NULL'), nullable=True),
        sa.Column('revoked_release_id', sa.String(),
                  sa.ForeignKey('access_policy_releases.id', ondelete='SET NULL'), nullable=True),
        sa.Column('granted_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    )
    for col in ('target', 'principal', 'securable_name', 'expires_at', 'status'):
        op.create_index(f'ix_access_grant_ledger_{col}', 'access_grant_ledger', [col])


def downgrade() -> None:
    for col in ('target', 'principal', 'securable_name', 'expires_at', 'status'):
        op.drop_index(f'ix_access_grant_ledger_{col}', table_name='access_grant_ledger')
    op.drop_table('access_grant_ledger')
    op.drop_index('ix_access_policy_releases_status', table_name='access_policy_releases')
    op.drop_index('ix_access_policy_releases_target', table_name='access_policy_releases')
    op.drop_table('access_policy_releases')
