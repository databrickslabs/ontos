"""keep the results of a step removed from a workflow

Revision ID: b7_workflow_step_results_kept
Revises: b6_contract_item_position
Create Date: 2026-10-19 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7_workflow_step_results_kept'
down_revision: Union[str, None] = 'b6_contract_item_position'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = 'workflow_step_executions'
_FK = 'workflow_step_executions_step_id_fkey'


def _step_id_fks(bind) -> list:
    return [
        fk for fk in sa.inspect(bind).get_foreign_keys(_TABLE)
        if fk.get('constrained_columns') == ['step_id']
    ]


def _columns(bind) -> set:
    return {c['name'] for c in sa.inspect(bind).get_columns(_TABLE)}


def upgrade() -> None:
    """A step result keeps the step's ``step_id`` and name, and outlives the step.

    ``step_id`` (the step's row id) becomes nullable with ``ON DELETE SET NULL``;
    ``step_key`` and ``step_name`` are filled from the current steps. Safe to run
    on a database that already has part of it.
    """
    bind = op.get_bind()
    columns = _columns(bind)
    if 'step_key' not in columns:
        op.add_column(_TABLE, sa.Column(
            'step_key', sa.String(100), nullable=True,
            comment="The step's step_id within its workflow, kept if the step is removed",
        ))
    if 'step_name' not in columns:
        op.add_column(_TABLE, sa.Column(
            'step_name', sa.String(255), nullable=True,
            comment="The step's name when it ran, kept if the step is removed",
        ))
    op.execute(f"""
        UPDATE {_TABLE} AS se SET step_key = s.step_id, step_name = s.name
        FROM workflow_steps AS s
        WHERE se.step_id = s.id AND se.step_key IS NULL
    """)

    for fk in _step_id_fks(bind):
        if (fk.get('options') or {}).get('ondelete', '').upper() != 'SET NULL':
            op.drop_constraint(fk['name'], _TABLE, type_='foreignkey')
    if not any(
        (fk.get('options') or {}).get('ondelete', '').upper() == 'SET NULL'
        for fk in _step_id_fks(bind)
    ):
        op.create_foreign_key(
            _FK, _TABLE, 'workflow_steps', ['step_id'], ['id'], ondelete='SET NULL',
        )
    op.alter_column(_TABLE, 'step_id', existing_type=sa.String(), nullable=True)


def downgrade() -> None:
    """Back to ``NOT NULL`` with ``ON DELETE CASCADE``.

    The results of removed steps (``step_id`` is null) can't be kept: they are
    deleted.
    """
    bind = op.get_bind()
    op.execute(f"DELETE FROM {_TABLE} WHERE step_id IS NULL")
    for fk in _step_id_fks(bind):
        op.drop_constraint(fk['name'], _TABLE, type_='foreignkey')
    op.create_foreign_key(
        _FK, _TABLE, 'workflow_steps', ['step_id'], ['id'], ondelete='CASCADE',
    )
    op.alter_column(_TABLE, 'step_id', existing_type=sa.String(), nullable=False)
    columns = _columns(bind)
    for column in ('step_name', 'step_key'):
        if column in columns:
            op.drop_column(_TABLE, column)
