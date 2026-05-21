"""Create process_workflows and related workflow tables if missing.

Older databases that were stamped at the baseline (`3135632d55e1`) BEFORE
the ProcessWorkflowDb model existed never received these tables. The
fresh-DB path in `init_db()` only calls `Base.metadata.create_all()` when
there is no `alembic_version` row, so existing instances skip table
creation entirely and rely on Alembic migrations for all schema changes.

`v4_wizard_completion_act` then assumes `process_workflows` exists and
runs `ALTER TABLE process_workflows ADD COLUMN workflow_type ...`, which
fails on those older DBs with a missing-table error.

This migration closes that gap by creating the four workflow tables
idempotently (CREATE TABLE IF NOT EXISTS) so that:
  - On fresh DBs: never runs (stamped at head).
  - On old DBs missing the tables: creates them, then v4 can ALTER.
  - On DBs that somehow already have them: no-op.

Note: `workflow_type` is intentionally OMITTED here because the next
migration (`v4_wizard_completion_act`) adds it. Keeping that separation
preserves the existing migration semantics for any DB that already
applied parts of the chain.

Revision ID: u2_create_workflow_tables
Revises: u1688q602tt5
Create Date: 2026-05-21
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'u2_create_workflow_tables'
down_revision: Union[str, None] = 'u1688q602tt5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. process_workflows
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS process_workflows (
            id VARCHAR NOT NULL,
            name VARCHAR(255) NOT NULL,
            description TEXT,
            trigger_config TEXT NOT NULL,
            scope_config TEXT,
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            is_default BOOLEAN NOT NULL DEFAULT FALSE,
            version INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            created_by VARCHAR(255),
            updated_by VARCHAR(255),
            CONSTRAINT process_workflows_pkey PRIMARY KEY (id)
        )
        """
    )

    # 2. workflow_steps
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS workflow_steps (
            id VARCHAR NOT NULL,
            workflow_id VARCHAR NOT NULL,
            step_id VARCHAR(100) NOT NULL,
            name VARCHAR(255),
            step_type VARCHAR(50) NOT NULL,
            config TEXT,
            on_pass VARCHAR(100),
            on_fail VARCHAR(100),
            "order" INTEGER NOT NULL DEFAULT 0,
            position TEXT,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            CONSTRAINT workflow_steps_pkey PRIMARY KEY (id),
            CONSTRAINT workflow_steps_workflow_id_fkey
                FOREIGN KEY (workflow_id)
                REFERENCES process_workflows (id)
                ON DELETE CASCADE
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_workflow_steps_workflow_id "
        "ON workflow_steps (workflow_id)"
    )

    # 3. workflow_executions
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS workflow_executions (
            id VARCHAR NOT NULL,
            workflow_id VARCHAR NOT NULL,
            trigger_context TEXT,
            status VARCHAR(50) NOT NULL DEFAULT 'pending',
            current_step_id VARCHAR(100),
            success_count INTEGER NOT NULL DEFAULT 0,
            failure_count INTEGER NOT NULL DEFAULT 0,
            error_message TEXT,
            started_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            finished_at TIMESTAMP WITH TIME ZONE,
            triggered_by VARCHAR(255),
            CONSTRAINT workflow_executions_pkey PRIMARY KEY (id),
            CONSTRAINT workflow_executions_workflow_id_fkey
                FOREIGN KEY (workflow_id)
                REFERENCES process_workflows (id)
                ON DELETE CASCADE
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_workflow_executions_workflow_id "
        "ON workflow_executions (workflow_id)"
    )

    # 4. workflow_step_executions
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS workflow_step_executions (
            id VARCHAR NOT NULL,
            execution_id VARCHAR NOT NULL,
            step_id VARCHAR NOT NULL,
            status VARCHAR(50) NOT NULL DEFAULT 'pending',
            passed BOOLEAN,
            result_data TEXT,
            error_message TEXT,
            duration_ms DOUBLE PRECISION,
            started_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            finished_at TIMESTAMP WITH TIME ZONE,
            CONSTRAINT workflow_step_executions_pkey PRIMARY KEY (id),
            CONSTRAINT workflow_step_executions_execution_id_fkey
                FOREIGN KEY (execution_id)
                REFERENCES workflow_executions (id)
                ON DELETE CASCADE,
            CONSTRAINT workflow_step_executions_step_id_fkey
                FOREIGN KEY (step_id)
                REFERENCES workflow_steps (id)
                ON DELETE CASCADE
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_workflow_step_executions_execution_id "
        "ON workflow_step_executions (execution_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_workflow_step_executions_step_id "
        "ON workflow_step_executions (step_id)"
    )


def downgrade() -> None:
    # Drop in reverse dependency order. Use IF EXISTS to stay idempotent
    # for DBs where these tables predate this migration.
    op.execute("DROP INDEX IF EXISTS ix_workflow_step_executions_step_id")
    op.execute("DROP INDEX IF EXISTS ix_workflow_step_executions_execution_id")
    op.execute("DROP TABLE IF EXISTS workflow_step_executions")

    op.execute("DROP INDEX IF EXISTS ix_workflow_executions_workflow_id")
    op.execute("DROP TABLE IF EXISTS workflow_executions")

    op.execute("DROP INDEX IF EXISTS ix_workflow_steps_workflow_id")
    op.execute("DROP TABLE IF EXISTS workflow_steps")

    op.execute("DROP TABLE IF EXISTS process_workflows")
