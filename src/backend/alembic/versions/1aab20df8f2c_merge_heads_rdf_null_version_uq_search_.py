"""merge heads: rdf-null-version-uq + search-documents

Revision ID: 1aab20df8f2c
Revises: m5_rdf_triple_null_version_uq, n1_search_documents
Create Date: 2026-09-30 10:39:15.433347

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1aab20df8f2c'
down_revision: Union[str, None] = ('m5_rdf_triple_null_version_uq', 'n1_search_documents')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
