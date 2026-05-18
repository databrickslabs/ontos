"""Add workflow_version column to agreements table

Closes the model/migration gap: AgreementDb.workflow_version was added to
the SQLAlchemy model in PRD #242 work but no Alembic migration was
generated. Fresh deployments hit a 500 in the wizard's _complete_session
because the INSERT references this missing column.

Revision ID: i1_workflow_version
Revises: h3_rename_consumer_principals
Create Date: 2026-05-18
"""
from alembic import op


revision = "i1_workflow_version"
down_revision = "h3_rename_consumer_principals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE agreements ADD COLUMN IF NOT EXISTS workflow_version INTEGER"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE agreements DROP COLUMN IF EXISTS workflow_version")
