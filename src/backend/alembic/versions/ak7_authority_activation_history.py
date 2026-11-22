"""Record when an Authority Relation version was first activated (ARF 1.2.0, #859 review B6, S3)

Revision ID: ak7_authority_activation_history
Revises: ak6_authority_check_ownership
Create Date: 2026-11-22

A version that was ever active is a published snapshot: it can't go back to draft,
and its definition can't be edited in place. Recording the first activation makes
that a fact on the row rather than something inferred from the status.

Adds ``authority_relations.activated_at``. Backfill: versions already active or retired
had been activated, and a needs_review version with a recorded production decision had
been too; they get their ``updated_at`` (the closest record of that time). Drafts, and
needs_review versions with no such evidence, stay NULL.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'ak7_authority_activation_history'
down_revision: Union[str, None] = 'ak6_authority_check_ownership'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def backfill_activated_at(conn) -> int:
    """Set activated_at on versions that had been activated. Returns the rows set.

    Active and retired versions had been activated. A needs_review version had only if it
    shows evidence of it: a recorded production decision (source 'mcp', from a resolve with
    record=true). Dry runs (source 'test') and DNA evidence rows don't count. Drafts, and
    needs_review versions with no such evidence, stay NULL, so they remain editable.
    """
    result = conn.execute(sa.text(
        "UPDATE authority_relations SET activated_at = updated_at "
        "WHERE activated_at IS NULL AND status IN ('active', 'retired')"
    ))
    changed = result.rowcount or 0
    result = conn.execute(sa.text(
        "UPDATE authority_relations SET activated_at = updated_at "
        "WHERE activated_at IS NULL AND status = 'needs_review' "
        "AND id IN (SELECT relation_id FROM authority_decisions WHERE source = 'mcp')"
    ))
    changed += result.rowcount or 0
    return changed


def upgrade() -> None:
    op.add_column('authority_relations', sa.Column('activated_at', sa.DateTime(timezone=True), nullable=True))
    backfill_activated_at(op.get_bind())


def downgrade() -> None:
    op.drop_column('authority_relations', 'activated_at')
