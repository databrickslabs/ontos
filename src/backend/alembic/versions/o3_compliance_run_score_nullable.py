"""a compliance run without a score stores NULL

Revision ID: o3_compliance_run_score_nullable
Revises: t1_lifecycle_stage_groups
Create Date: 2026-11-19 06:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'o3_compliance_run_score_nullable'
down_revision: Union[str, None] = 't1_lifecycle_stage_groups'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = 'compliance_runs'

# A run has no score when it failed or evaluated no entity (all not evaluated,
# or none matched); such runs stored 0.0 before this revision
_UNSCORED = (
    "status = 'failed' OR (COALESCE(success_count, 0) + COALESCE(failure_count, 0)) = 0"
)


def upgrade() -> None:
    """``compliance_runs.score`` is nullable, and the runs without a score hold NULL.

    Before this revision a run that failed or evaluated nothing stored 0.0, so it
    read as 0 % compliance. Runs still running keep their value (they have none yet).
    """
    with op.batch_alter_table(_TABLE) as batch:
        batch.alter_column('score', existing_type=sa.Float(), nullable=True)
    op.execute(
        f"UPDATE {_TABLE} SET score = NULL "
        f"WHERE status IN ('succeeded', 'failed') AND ({_UNSCORED})"
    )


def downgrade() -> None:
    """Back to NOT NULL: a run without a score stores 0.0 again."""
    op.execute(f"UPDATE {_TABLE} SET score = 0.0 WHERE score IS NULL")
    with op.batch_alter_table(_TABLE) as batch:
        batch.alter_column('score', existing_type=sa.Float(), nullable=False)
