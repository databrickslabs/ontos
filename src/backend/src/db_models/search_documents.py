"""ORM model for the DB-backed search index (``search_documents``).

Backs the ``postgres`` ``SEARCH_BACKEND``: one row per searchable entity,
mirroring ``SearchIndexItem``. Full-text search runs over a Postgres weighted
``tsvector`` column with a GIN index. Both the ``tsvector`` column and the GIN
index are **Postgres-only** and attached via a dialect-guarded ``after_create``
DDL, so the table is still creatable on SQLite (the in-memory test harness),
where full-text search is simply never exercised.

The same DDL is mirrored in Alembic migration ``n1_add_search_documents`` for
databases that upgrade via migrations rather than ``create_all()``. On a fresh
database the app uses ``create_all() + stamp`` (see ``common/database.py``), so
the ``after_create`` hook is what builds the ``tsvector``/GIN there.
"""
from sqlalchemy import JSON, Column, DDL, String, Text, TIMESTAMP, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

from src.common.database import Base

# JSONB on Postgres, JSON on SQLite (test harness) — both round-trip list/dict.
_JSON = JSONB().with_variant(JSON(), "sqlite")

SEARCH_DOCUMENTS_TABLE = "search_documents"

# Weighted full-text vector: title=A (highest), description=B, aux_text=C.
# aux_text carries tags + domain(s) + owner + linked concept labels so those are
# searchable at a lower weight than the title/description.
_ADD_TSV_COLUMN = (
    f"ALTER TABLE {SEARCH_DOCUMENTS_TABLE} ADD COLUMN IF NOT EXISTS search_tsv tsvector "
    "GENERATED ALWAYS AS ("
    "setweight(to_tsvector('english', coalesce(title, '')), 'A') || "
    "setweight(to_tsvector('english', coalesce(description, '')), 'B') || "
    "setweight(to_tsvector('english', coalesce(aux_text, '')), 'C')"
    ") STORED"
)
_CREATE_TSV_INDEX = (
    f"CREATE INDEX IF NOT EXISTS ix_search_documents_tsv "
    f"ON {SEARCH_DOCUMENTS_TABLE} USING gin (search_tsv)"
)


class SearchDocumentDb(Base):
    __tablename__ = SEARCH_DOCUMENTS_TABLE

    # id mirrors SearchIndexItem.id, e.g. "product::<uuid>".
    id = Column(String, primary_key=True)
    # Bare entity id (id without the "type::" prefix) for follow-up get_* calls.
    entity_id = Column(String, nullable=False, index=True)
    type = Column(String, nullable=False, index=True)          # e.g. "data-product"
    feature_id = Column(String, nullable=False, index=True)    # for permission filtering
    title = Column(Text, nullable=False)
    description = Column(Text, nullable=True)
    # tags + domains + owner + concept labels, concatenated (feeds tsvector weight C).
    aux_text = Column(Text, nullable=True)
    tags = Column(_JSON, nullable=False, default=list)
    extra_data = Column(_JSON, nullable=False, default=dict)
    link = Column(Text, nullable=True)
    updated_at = Column(
        TIMESTAMP(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


# Attach the Postgres-only tsvector column + GIN index when the table is created
# via create_all() (fresh-database boot). Skipped on SQLite so tests still build
# the table. Existing databases get the same objects from the n1 Alembic migration.
event.listen(
    SearchDocumentDb.__table__,
    "after_create",
    DDL(_ADD_TSV_COLUMN).execute_if(dialect="postgresql"),
)
event.listen(
    SearchDocumentDb.__table__,
    "after_create",
    DDL(_CREATE_TSV_INDEX).execute_if(dialect="postgresql"),
)
