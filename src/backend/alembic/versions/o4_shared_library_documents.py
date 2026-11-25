"""a document uploaded to the shared library is a shared library row

Revision ID: o4_shared_library_documents
Revises: o3_canonical_cost_centers
Create Date: 2026-11-24 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'o4_shared_library_documents'
down_revision: Union[str, None] = 'o3_canonical_cost_centers'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SHARED_ENTITY_ID = '__shared__'


def upgrade() -> None:
    """Set ``is_shared`` on documents uploaded to the shared library.

    ``POST /api/metadata/shared/documents`` stored the record with
    ``entity_id = '__shared__'`` but without ``is_shared`` (the document create
    never copied the flag), and the shared library lists only rows that have
    both, so every uploaded library document was listed nowhere. Such a row is
    told apart by its file in the shared folder (``uploads/__shared__/``): an
    entity upload with the entity id ``__shared__`` stores its file under
    ``uploads/<entity_type>/__shared__/`` and stays the entity's. Notes and
    links are not affected: their shared creates set the flag.
    """
    op.get_bind().execute(
        sa.text(
            "UPDATE document_metadata SET is_shared = true "
            "WHERE is_shared = false AND entity_id = :shared "
            "AND storage_path LIKE :folder"
        ),
        {'shared': _SHARED_ENTITY_ID, 'folder': '%/uploads/__shared__/%'},
    )


def downgrade() -> None:
    """Nothing to restore: the rows were library documents, and older code lists them the same way."""
