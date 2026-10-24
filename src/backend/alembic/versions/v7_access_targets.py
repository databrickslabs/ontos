"""Access Targets: governed compile + delivery targets for Access Policies

Revision ID: v7_access_targets
Revises: v6_access_ledger_spec
Create Date: 2026-10-24
"""
import sqlalchemy as sa
from alembic import op

revision = 'v7_access_targets'
down_revision = 'v6_access_ledger_spec'
branch_labels = None
depends_on = None

_TABLE = 'access_targets'


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('uid', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('status', sa.String(), nullable=False, server_default='draft'),
        sa.Column('version', sa.String(), nullable=False, server_default='1.0.0'),
        sa.Column('version_family_id', sa.String(), nullable=False),
        sa.Column('change_summary', sa.Text(), nullable=True),
        sa.Column('draft_owner_id', sa.String(), nullable=True),
        sa.Column('maturity_level_order', sa.Integer(), nullable=True),
        sa.Column('maturity_evaluated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_by', sa.String(), nullable=True),
        sa.Column('updated_by', sa.String(), nullable=True),
        sa.Column('submitted_by', sa.String(), nullable=True),
        sa.Column('approved_by', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('owner_team_id', sa.String(), sa.ForeignKey('teams.id', ondelete='SET NULL'), nullable=True),
        sa.Column('project_id', sa.String(), sa.ForeignKey('projects.id', ondelete='SET NULL'), nullable=True),
        sa.Column('parent_id', sa.String(), sa.ForeignKey(f'{_TABLE}.id', ondelete='SET NULL'), nullable=True),
        sa.Column('key', sa.String(), nullable=False),
        sa.Column('system', sa.String(), nullable=False),
        sa.Column('connection', sa.JSON(), nullable=False),
        sa.Column('scope', sa.JSON(), nullable=False),
        sa.Column('delivery_modes', sa.JSON(), nullable=False),
        sa.Column('reconcile_schedule', sa.String(), nullable=True),
        sa.Column('drift_policy', sa.String(), nullable=False, server_default='report'),
    )
    for col in ('uid', 'name', 'status', 'version_family_id', 'draft_owner_id', 'owner_team_id', 'project_id',
                'parent_id', 'key'):
        op.create_index(f'ix_{_TABLE}_{col}', _TABLE, [col])


def downgrade() -> None:
    op.drop_table(_TABLE)
