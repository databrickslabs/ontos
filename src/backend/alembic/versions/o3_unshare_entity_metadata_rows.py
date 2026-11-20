"""a note, link or document stored on an entity is not a shared library row

Revision ID: o3_unshare_entity_metadata_rows
Revises: o2_step_execution_message
Create Date: 2026-11-19 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'o3_unshare_entity_metadata_rows'
down_revision: Union[str, None] = 'o2_step_execution_message'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLES = ('rich_text_metadata', 'link_metadata', 'document_metadata')
_SHARED_ENTITY_ID = '__shared__'


def upgrade() -> None:
    """Clear ``is_shared`` on rows that belong to an entity (#1342).

    Before the per-entity create routes ignored ``is_shared``, a body with
    ``"is_shared": true`` stored the entity's row flagged as shared. The shared
    library now lists only rows with ``entity_id = '__shared__'``, and the
    entity's own lists skip flagged rows, so such a row was shown nowhere. With
    the flag cleared it is listed on its entity again, under that entity's
    access rules. Attachments that point at it are kept.
    """
    bind = op.get_bind()
    for table in _TABLES:
        bind.execute(
            sa.text(
                f"UPDATE {table} SET is_shared = false "
                "WHERE is_shared = true AND entity_id <> :shared"
            ),
            {'shared': _SHARED_ENTITY_ID},
        )


def downgrade() -> None:
    """Nothing to restore: which rows had the flag isn't kept, and they were the entity's."""
