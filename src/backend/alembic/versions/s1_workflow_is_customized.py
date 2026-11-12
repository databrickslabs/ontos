"""Add process_workflows.is_customized

Revision ID: s1_workflow_is_customized
Revises: o1_merge_r1_c7
Create Date: 2026-11-11

"Reload All Defaults" keeps default workflows a user changed. That needs a marker
that no system writer overwrites: ``updated_by`` is an audit column that startup
routines also stamp, and it's empty for users without an email.

Backfill (best effort): a default counts as customized if a user last updated it
(``updated_by`` is set and isn't the loader's ``system``). Rows only toggled by a
user are included too. That errs on keeping them, and an admin can still reset
them with the "also reset edited" option.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 's1_workflow_is_customized'
down_revision: Union[str, None] = 'o1_merge_r1_c7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'process_workflows',
        sa.Column('is_customized', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.execute(sa.text(
        "UPDATE process_workflows SET is_customized = TRUE "
        "WHERE is_default = TRUE AND updated_by IS NOT NULL AND updated_by NOT IN ('', 'system')"
    ))


def downgrade() -> None:
    op.drop_column('process_workflows', 'is_customized')
