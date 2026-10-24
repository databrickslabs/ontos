"""Add Access Policies (W3C ODRL): policies, policy index, audiences, asset collections

Revision ID: v1_access_policies
Revises: b7_workflow_step_results_kept
Create Date: 2026-10-17
"""
import sqlalchemy as sa
from alembic import op

revision = 'v1_access_policies'
down_revision = 'b7_workflow_step_results_kept'
branch_labels = None
depends_on = None


def _governed_columns(table: str):
    return [
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
        sa.Column('parent_id', sa.String(), sa.ForeignKey(f'{table}.id', ondelete='SET NULL'), nullable=True),
    ]


def _governed_indexes(table: str):
    for col in ('uid', 'name', 'status', 'version_family_id', 'draft_owner_id', 'owner_team_id', 'project_id', 'parent_id'):
        op.create_index(f'ix_{table}_{col}', table, [col])


_TABLES = ('access_policies', 'access_audiences', 'access_asset_collections')


def upgrade() -> None:
    op.create_table(
        'access_policies',
        *_governed_columns('access_policies'),
        sa.Column('policy_type', sa.String(), nullable=False, server_default='Set'),
        sa.Column('conflict', sa.String(), nullable=False, server_default='prohibit'),
        sa.Column('inherit_from', sa.JSON(), nullable=True),
        sa.Column('body', sa.JSON(), nullable=False),
    )
    for table in ('access_audiences', 'access_asset_collections'):
        op.create_table(
            table,
            *_governed_columns(table),
            sa.Column('members', sa.JSON(), nullable=False),
            sa.Column('refinement', sa.JSON(), nullable=False),
        )
    for table in _TABLES:
        _governed_indexes(table)

    op.create_table(
        'access_policy_index',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('policy_id', sa.String(), sa.ForeignKey('access_policies.id', ondelete='CASCADE'), nullable=False),
        sa.Column('rule_kind', sa.String(), nullable=False),
        sa.Column('role', sa.String(), nullable=False),
        sa.Column('value', sa.String(), nullable=False),
        sa.UniqueConstraint('policy_id', 'rule_kind', 'role', 'value', name='uq_access_policy_index'),
    )
    op.create_index('ix_access_policy_index_policy_id', 'access_policy_index', ['policy_id'])
    op.create_index('ix_access_policy_index_value', 'access_policy_index', ['value'])


def downgrade() -> None:
    op.drop_index('ix_access_policy_index_value', table_name='access_policy_index')
    op.drop_index('ix_access_policy_index_policy_id', table_name='access_policy_index')
    op.drop_table('access_policy_index')
    for table in reversed(_TABLES):
        for col in ('uid', 'name', 'status', 'version_family_id', 'draft_owner_id', 'owner_team_id', 'project_id', 'parent_id'):
            op.drop_index(f'ix_{table}_{col}', table_name=table)
        op.drop_table(table)
