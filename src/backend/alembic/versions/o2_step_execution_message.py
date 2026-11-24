"""keep the message of each workflow step result

Revision ID: o2_step_execution_message
Revises: r2_canonical_relationship_types
Create Date: 2026-11-11 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'o2_step_execution_message'
down_revision: Union[str, None] = 'r2_canonical_relationship_types'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = 'workflow_step_executions'


def _columns(bind) -> set:
    return {c['name'] for c in sa.inspect(bind).get_columns(_TABLE)}


def upgrade() -> None:
    """A step result stores its message, so a resumed run restores it for later steps (#1437).

    Results recorded before this revision have no message. Safe to run when the
    column already exists (a fresh schema created by create_all).
    """
    bind = op.get_bind()
    if 'message' not in _columns(bind):
        op.add_column(_TABLE, sa.Column('message', sa.Text(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    if 'message' in _columns(bind):
        op.drop_column(_TABLE, 'message')
