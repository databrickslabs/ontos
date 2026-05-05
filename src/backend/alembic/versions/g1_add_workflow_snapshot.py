"""Add workflow_snapshot and workflow_name to agreement_wizard_sessions and agreements.

Captures an immutable JSON snapshot of the workflow definition at session creation time,
so historical agreements reflect what the signer actually saw (PRD #242, user stories #12-14, #23).

Revision ID: g1_workflow_snapshot
Revises: f1_merge_aa9_e2, v4_wizard_completion_act
Create Date: 2026-04-24
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "g1_workflow_snapshot"
# Merges the f1 head (aa9 + e2) with the v4 wizard-schema head — g1 needs the
# `agreement_wizard_sessions` / `agreements` tables introduced by v4 to add
# its `workflow_snapshot` and `workflow_name` columns. Both parents are real
# revisions in this repo (verified at revise-time).
down_revision: Union[str, Sequence[str], None] = ("f1_merge_aa9_e2", "v4_wizard_completion_act")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Use ADD COLUMN IF NOT EXISTS for safety (idempotent re-runs).
    op.execute("ALTER TABLE agreement_wizard_sessions ADD COLUMN IF NOT EXISTS workflow_snapshot TEXT")
    op.execute("ALTER TABLE agreement_wizard_sessions ADD COLUMN IF NOT EXISTS workflow_name VARCHAR(255)")
    op.execute("ALTER TABLE agreements ADD COLUMN IF NOT EXISTS workflow_snapshot TEXT")
    op.execute("ALTER TABLE agreements ADD COLUMN IF NOT EXISTS workflow_name VARCHAR(255)")


def downgrade() -> None:
    op.drop_column("agreements", "workflow_name")
    op.drop_column("agreements", "workflow_snapshot")
    op.drop_column("agreement_wizard_sessions", "workflow_name")
    op.drop_column("agreement_wizard_sessions", "workflow_snapshot")
