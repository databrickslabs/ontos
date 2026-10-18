"""search_documents: per-field tsvector columns for BM25

Revision ID: n2_search_field_tsv
Revises: b1_add_adopt_entity_ids
Create Date: 2026-10-18

Adds generated ``title_tsv`` / ``description_tsv`` / ``aux_tsv`` columns (plain
``tsvector``, valid on every engine). The ``lakebase`` search engine builds one
``lakebase_bm25`` index per column at startup (``ensure_search_indexes``); the
``pg`` engine doesn't use them yet. Postgres only; no-op elsewhere.
"""
from typing import Sequence, Union

from alembic import op

TABLE = "search_documents"
# Mirrors FIELD_TSV_COLUMNS in src/db_models/search_documents.py (kept inline so
# this revision doesn't change if the model does).
FIELD_TSV_COLUMNS = {"title": "title_tsv", "description": "description_tsv", "aux_text": "aux_tsv"}

revision: str = "n2_search_field_tsv"
down_revision: Union[str, Sequence[str], None] = "b1_add_adopt_entity_ids"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    # One ALTER TABLE, so the table is rewritten once rather than per column.
    adds = ", ".join(
        f"ADD COLUMN IF NOT EXISTS {col} tsvector "
        f"GENERATED ALWAYS AS (to_tsvector('english', coalesce({src}, ''))) STORED"
        for src, col in FIELD_TSV_COLUMNS.items()
    )
    op.execute(f"ALTER TABLE {TABLE} {adds}")


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(f"ALTER TABLE {TABLE} " + ", ".join(
        f"DROP COLUMN IF EXISTS {col}" for col in FIELD_TSV_COLUMNS.values()
    ))
