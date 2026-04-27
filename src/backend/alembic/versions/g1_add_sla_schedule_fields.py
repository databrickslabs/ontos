"""Add description, schedule, scheduler to data_contract_sla_properties

ODCS v3.1.0 defines three fields on ServiceLevelAgreementProperty that were
not yet persisted:

- description: human-readable description of the SLA
- scheduler:   name of the scheduling tool (e.g. "cron", "Airflow")
- schedule:    scheduling configuration (e.g. "0 20 * * *")

Reference: https://github.com/bitol-io/open-data-contract-standard/blob/main/schema/odcs-json-schema-v3.1.0.json

Revision ID: g1_sla_schedule_fields
Revises: f1_merge_aa9_e2
Create Date: 2026-04-27
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "g1_sla_schedule_fields"
down_revision: Union[str, None] = "f1_merge_aa9_e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("data_contract_sla_properties", sa.Column("description", sa.Text(), nullable=True))
    op.add_column("data_contract_sla_properties", sa.Column("scheduler", sa.String(), nullable=True))
    op.add_column("data_contract_sla_properties", sa.Column("schedule", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("data_contract_sla_properties", "schedule")
    op.drop_column("data_contract_sla_properties", "scheduler")
    op.drop_column("data_contract_sla_properties", "description")
