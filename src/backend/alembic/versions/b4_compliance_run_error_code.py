"""add a translatable error code to compliance runs

A failed run stored its error as text only, so the UI couldn't translate the
errors the app writes itself. error_code and error_params (JSON) hold a stable
code and its parameters; error_message stays the English fallback.

Revision ID: b4_compliance_run_error_code
Revises: b3_property_custom_props
Create Date: 2026-10-17 01:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b4_compliance_run_error_code'
down_revision: Union[str, None] = 'b3_property_custom_props'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = 'compliance_runs'


def upgrade() -> None:
    op.add_column(TABLE, sa.Column('error_code', sa.String(), nullable=True))
    op.add_column(TABLE, sa.Column('error_params', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column(TABLE, 'error_params')
    op.drop_column(TABLE, 'error_code')
