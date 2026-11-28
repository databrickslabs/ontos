"""add model_import_runs for staged erwin model imports

Revision ID: ad1_model_import_runs
Revises: t2_delivery_outbox
Create Date: 2026-11-27 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ad1_model_import_runs'
down_revision: Union[str, None] = 't2_delivery_outbox'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = 'model_import_runs'


def upgrade() -> None:
    """Staged model imports (PRD #1718). Safe on a fresh schema built by create_all."""
    bind = op.get_bind()
    if _TABLE in sa.inspect(bind).get_table_names():
        return
    op.create_table(
        _TABLE,
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False, server_default='previewed'),
        sa.Column('progress_message', sa.String(), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('source_kind', sa.String(), nullable=False, server_default='file_xml'),
        sa.Column('source_filename', sa.String(), nullable=True),
        sa.Column('source_sha256', sa.String(length=64), nullable=True),
        sa.Column('source_size_bytes', sa.Integer(), nullable=True),
        sa.Column('source_model_id', sa.String(), nullable=True),
        sa.Column('source_model_name', sa.String(), nullable=True),
        sa.Column('source_model_version', sa.String(), nullable=True),
        sa.Column('model_ir', sa.LargeBinary(), nullable=True),
        sa.Column('options', sa.JSON(), nullable=True),
        sa.Column('preview', sa.JSON(), nullable=True),
        sa.Column('confirm_token', sa.String(), nullable=True),
        sa.Column('result', sa.JSON(), nullable=True),
        sa.Column('notification_id', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_model_import_runs_user_id', _TABLE, ['user_id'])
    op.create_index('ix_model_import_runs_source_sha256', _TABLE, ['source_sha256'])
    op.create_index('ix_model_import_runs_source_model_id', _TABLE, ['source_model_id'])
    op.create_index('ix_model_import_runs_user_created', _TABLE, ['user_id', 'created_at'])
    op.create_index('ix_model_import_runs_model_status', _TABLE, ['source_model_id', 'status'])
    # At most one running import per model.
    op.create_index(
        'uq_model_import_runs_running_model', _TABLE, ['source_model_id'], unique=True,
        postgresql_where=sa.text("status = 'running'"),
    )


def downgrade() -> None:
    bind = op.get_bind()
    if _TABLE not in sa.inspect(bind).get_table_names():
        return
    # Dropping the table drops its indexes too (whichever of them exist).
    op.drop_table(_TABLE)
