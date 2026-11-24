"""add a translatable warning code to compliance runs

A run that finished can still have something to report (a stored rule whose
trailing input was ignored). warning_code and warning_params (JSON) hold it,
so error_code / error_params stay empty on a succeeded run and a query on
``error_code IS NOT NULL`` keeps counting failed runs only.

Revision ID: b10_compliance_run_warning_code
Revises: b9_lifecycle_deprecation_fields
Create Date: 2026-11-09 01:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b10_compliance_run_warning_code'
down_revision: Union[str, None] = 'b9_lifecycle_deprecation_fields'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = 'compliance_runs'


def upgrade() -> None:
    op.add_column(TABLE, sa.Column('warning_code', sa.String(), nullable=True))
    op.add_column(TABLE, sa.Column('warning_params', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column(TABLE, 'warning_params')
    op.drop_column(TABLE, 'warning_code')
