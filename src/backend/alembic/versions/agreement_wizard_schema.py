"""Agreement wizard schema: workflow_type, sessions, agreements, completion_action

Revision ID: v4_wizard_completion_act
Revises: u2_create_workflow_tables
Create Date: 2026-02-12

Single migration for approval/agreement wizard feature (squashed from v1–v4):
- Add workflow_type to process_workflows ('process' | 'approval')
- Create agreement_wizard_sessions (with completion_action)
- Create agreements table

Uses revision v4_wizard_completion_act so DBs that already applied the old v1–v4
chain remain at head without re-running.

Chained behind `u2_create_workflow_tables` (instead of `u1688q602tt5` directly)
so older DBs that were stamped before the ProcessWorkflowDb model existed get
`process_workflows` (and its sibling workflow tables) created before this
migration tries to ALTER it. DBs that already applied this migration against
`u1688q602tt5` won't re-run it; the new parent only inserts itself for DBs
that hadn't yet reached `v4_wizard_completion_act`.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'v4_wizard_completion_act'
down_revision: Union[str, None] = 'u2_create_workflow_tables'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. workflow_type on process_workflows
    op.add_column(
        'process_workflows',
        sa.Column('workflow_type', sa.String(50), nullable=False, server_default='process'),
    )

    # 2. agreement_wizard_sessions (with completion_action)
    op.create_table(
        'agreement_wizard_sessions',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('workflow_id', sa.String(), nullable=False),
        sa.Column('entity_type', sa.String(100), nullable=False),
        sa.Column('entity_id', sa.String(255), nullable=False),
        sa.Column('current_step_index', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('step_results', sa.Text(), nullable=True),
        sa.Column('status', sa.String(50), nullable=False, server_default='in_progress'),
        sa.Column('completion_action', sa.String(50), nullable=True),
        sa.Column('created_by', sa.String(255), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['workflow_id'], ['process_workflows.id'], ondelete='CASCADE'),
    )
    op.create_index('ix_agreement_wizard_sessions_workflow_id', 'agreement_wizard_sessions', ['workflow_id'])
    op.create_index('ix_agreement_wizard_sessions_entity_type', 'agreement_wizard_sessions', ['entity_type'])
    op.create_index('ix_agreement_wizard_sessions_entity_id', 'agreement_wizard_sessions', ['entity_id'])

    # 3. agreements
    op.create_table(
        'agreements',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('entity_type', sa.String(100), nullable=False),
        sa.Column('entity_id', sa.String(255), nullable=False),
        sa.Column('workflow_id', sa.String(), nullable=True),
        sa.Column('wizard_session_id', sa.String(), nullable=True),
        sa.Column('step_results', sa.Text(), nullable=True),
        sa.Column('pdf_storage_path', sa.String(1024), nullable=True),
        sa.Column('created_by', sa.String(255), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['workflow_id'], ['process_workflows.id'], ondelete='SET NULL'),
    )
    op.create_index('ix_agreements_entity_type', 'agreements', ['entity_type'])
    op.create_index('ix_agreements_entity_id', 'agreements', ['entity_id'])
    op.create_index('ix_agreements_workflow_id', 'agreements', ['workflow_id'])
    op.create_index('ix_agreements_wizard_session_id', 'agreements', ['wizard_session_id'])


def downgrade() -> None:
    op.drop_index('ix_agreements_wizard_session_id', 'agreements')
    op.drop_index('ix_agreements_workflow_id', 'agreements')
    op.drop_index('ix_agreements_entity_id', 'agreements')
    op.drop_index('ix_agreements_entity_type', 'agreements')
    op.drop_table('agreements')

    op.drop_index('ix_agreement_wizard_sessions_entity_id', 'agreement_wizard_sessions')
    op.drop_index('ix_agreement_wizard_sessions_entity_type', 'agreement_wizard_sessions')
    op.drop_index('ix_agreement_wizard_sessions_workflow_id', 'agreement_wizard_sessions')
    op.drop_table('agreement_wizard_sessions')

    op.drop_column('process_workflows', 'workflow_type')
