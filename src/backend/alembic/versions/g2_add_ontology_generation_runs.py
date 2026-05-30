"""add_ontology_generation_runs

Revision ID: g2_ontology_gen_runs
Revises: j1_add_version_family_id
Create Date: 2026-05-28

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON

revision: str = 'g2_ontology_gen_runs'
down_revision: Union[str, None] = 'j1_add_version_family_id'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'ontology_generation_runs',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False, server_default='pending'),
        sa.Column('progress_message', sa.String(), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('connection_id', sa.String(), nullable=True),
        sa.Column('connection_name', sa.String(), nullable=True),
        sa.Column('selected_paths', JSON(), nullable=True),
        sa.Column('guidelines', sa.Text(), nullable=True),
        sa.Column('base_uri', sa.String(), nullable=True),
        sa.Column('options', JSON(), nullable=True),
        sa.Column('steps', JSON(), nullable=True),
        sa.Column('result', JSON(), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('completed_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_ontology_generation_runs_user_id', 'ontology_generation_runs', ['user_id'])
    op.create_index('ix_ontology_runs_user_status', 'ontology_generation_runs', ['user_id', 'status'])
    op.create_index('ix_ontology_runs_user_created', 'ontology_generation_runs', ['user_id', 'created_at'])


def downgrade() -> None:
    op.drop_index('ix_ontology_runs_user_created', table_name='ontology_generation_runs')
    op.drop_index('ix_ontology_runs_user_status', table_name='ontology_generation_runs')
    op.drop_index('ix_ontology_generation_runs_user_id', table_name='ontology_generation_runs')
    op.drop_table('ontology_generation_runs')
