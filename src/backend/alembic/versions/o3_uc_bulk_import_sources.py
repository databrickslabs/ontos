"""record the tables the UC Bulk Import job imported into each product and contract

Revision ID: o3_uc_bulk_import_sources
Revises: o2_step_execution_message
Create Date: 2026-11-19 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'o3_uc_bulk_import_sources'
down_revision: Union[str, None] = 'o2_step_execution_message'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = 'uc_bulk_import_sources'


def _exists(bind) -> bool:
    return _TABLE in sa.inspect(bind).get_table_names()


def upgrade() -> None:
    """A port or schema object deleted from an imported draft stays deleted (#1469).

    The job skips every table it has a row for. Products and contracts imported
    before this revision have no rows; their next ``update`` run records the
    tables they already have. Safe to run when the table already exists (a fresh
    schema created by create_all).
    """
    bind = op.get_bind()
    if _exists(bind):
        return
    op.create_table(
        _TABLE,
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('entity_type', sa.String(), nullable=False),
        sa.Column('version_family_id', sa.String(), nullable=False),
        sa.Column('source_key', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('entity_type', 'version_family_id', 'source_key',
                            name='uq_uc_bulk_import_sources_entity_source'),
    )


def downgrade() -> None:
    bind = op.get_bind()
    if _exists(bind):
        op.drop_table(_TABLE)
