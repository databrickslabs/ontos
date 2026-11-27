"""add delivery_outbox: changes still to deliver and their last outcome

One row per change and active delivery mode, written in the change's transaction
(#1688). The workflow scheduler's thread delivers the pending rows, with bounded
retries; delivered rows are deleted after the retention period.

Revision ID: t2_delivery_outbox
Revises: t1_contract_tag_backfill
Create Date: 2026-11-24 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 't2_delivery_outbox'
down_revision: Union[str, None] = 't1_contract_tag_backfill'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = 'delivery_outbox'
_INDEXES = (
    ('ix_delivery_outbox_status_next_attempt', ['status', 'next_attempt_at']),
    ('ix_delivery_outbox_entity', ['entity_type', 'entity_id']),
)


def _has_table(bind) -> bool:
    return _TABLE in sa.inspect(bind).get_table_names()


def _index_names(bind) -> set:
    return {index['name'] for index in sa.inspect(bind).get_indexes(_TABLE)}


def upgrade() -> None:
    """Safe to run again: the table and each index are created only when missing
    (a schema created by ``create_all``, or a retried upgrade)."""
    bind = op.get_bind()
    if not _has_table(bind):
        op.create_table(
            _TABLE,
            sa.Column('id', sa.String(), nullable=False),
            sa.Column('entity_type', sa.String(length=64), nullable=False),
            sa.Column('entity_id', sa.String(), nullable=False),
            sa.Column('change_type', sa.String(length=64), nullable=False),
            sa.Column('mode', sa.String(length=32), nullable=False),
            sa.Column('status', sa.String(length=16), nullable=False),
            sa.Column('code', sa.String(length=128), nullable=True),
            sa.Column('params', sa.JSON(), nullable=True),
            sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('next_attempt_at', sa.TIMESTAMP(timezone=True), nullable=True),
            sa.Column('last_attempt_at', sa.TIMESTAMP(timezone=True), nullable=True),
            sa.Column('delivered_at', sa.TIMESTAMP(timezone=True), nullable=True),
            sa.Column('queued_by', sa.String(), nullable=True),
            sa.Column('created_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(),
                      nullable=False),
            sa.Column('updated_at', sa.TIMESTAMP(timezone=True), server_default=sa.func.now(),
                      nullable=False),
            sa.PrimaryKeyConstraint('id'),
        )
    existing = _index_names(bind)
    for name, columns in _INDEXES:
        if name not in existing:
            op.create_index(name, _TABLE, columns)


def downgrade() -> None:
    bind = op.get_bind()
    if not _has_table(bind):
        return
    existing = _index_names(bind)
    for name, _ in reversed(_INDEXES):
        if name in existing:
            op.drop_index(name, table_name=_TABLE)
    op.drop_table(_TABLE)
