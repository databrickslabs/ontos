"""Add search_documents table (DB-backed full-text search index)

Backs the ``postgres`` SEARCH_BACKEND: one row per searchable entity (mirrors
``SearchIndexItem``), with a weighted Postgres ``tsvector`` column
(title=A, description=B, aux_text=C) and a GIN index for full-text search.
Mirrors what ``db_models/search_documents.py`` builds via ``create_all()`` on a
fresh database, so the two schema paths converge.

Revision ID: n1_search_documents
Revises: m2_schema_import_runs
Create Date: 2026-09-26
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "n1_search_documents"
down_revision: Union[str, Sequence[str], None] = "m2_schema_import_runs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE = "search_documents"


def _table_exists(conn, name: str) -> bool:
    return conn.execute(
        sa.text("SELECT 1 FROM information_schema.tables WHERE table_name = :n"),
        {"n": name},
    ).scalar() is not None


def upgrade() -> None:
    conn = op.get_bind()
    if _table_exists(conn, TABLE):
        return

    op.create_table(
        TABLE,
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("entity_id", sa.String(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("feature_id", sa.String(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("aux_text", sa.Text(), nullable=True),
        sa.Column("tags", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("extra_data", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("link", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_search_documents_entity_id", TABLE, ["entity_id"])
    op.create_index("ix_search_documents_type", TABLE, ["type"])
    op.create_index("ix_search_documents_feature_id", TABLE, ["feature_id"])

    # Weighted tsvector (title=A, description=B, aux_text=C) + GIN index for FTS.
    op.execute(
        f"ALTER TABLE {TABLE} ADD COLUMN search_tsv tsvector "
        "GENERATED ALWAYS AS ("
        "setweight(to_tsvector('english', coalesce(title, '')), 'A') || "
        "setweight(to_tsvector('english', coalesce(description, '')), 'B') || "
        "setweight(to_tsvector('english', coalesce(aux_text, '')), 'C')"
        ") STORED"
    )
    op.execute(f"CREATE INDEX ix_search_documents_tsv ON {TABLE} USING gin (search_tsv)")


def downgrade() -> None:
    conn = op.get_bind()
    if _table_exists(conn, TABLE):
        op.drop_table(TABLE)
