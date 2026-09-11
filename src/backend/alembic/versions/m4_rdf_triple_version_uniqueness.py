"""Add concept_version_id to rdf_triples uniqueness (snapshot-per-version).

Publish must FREEZE the prior version's triples: v1 keeps its old field values,
v2 gets a COPY with the new values. Same (subject, predicate, object, lang,
datatype, context) but a different concept_version_id. The original 6-column
``uq_rdf_triple`` (s,p,o,lang,datatype,context) BLOCKS that copy — verified: the
second insert raises UniqueViolation. Without per-version rows the old definition
text is destroyed on publish and P0-4's diff engine has nothing to diff.

Fix: widen ``uq_rdf_triple`` to include ``concept_version_id`` as the 7th column,
using ``UNIQUE NULLS NOT DISTINCT`` (Postgres 15+) so that:
  - two rows differing ONLY by concept_version_id are allowed (per-version snapshot), AND
  - two rows with a NULL concept_version_id are still treated as duplicates
    (NULLS NOT DISTINCT), preserving the ON CONFLICT DO NOTHING dedup that
    rdf_triples_repository relies on for unowned/metadata triples.
Both behaviours verified empirically against Postgres 16 before writing this.

Postgres-targeted (NULLS NOT DISTINCT is PG15+; the project deploys on
Postgres/Lakebase). Reversible: downgrade restores the 6-column constraint (safe
only once per-version duplicate rows are removed — see downgrade note).

Revision ID: m4_rdf_triple_version_uq
Revises: m2_rdf_triples_current
Create Date: 2026-08-12
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'm4_rdf_triple_version_uq'
down_revision: Union[str, None] = 'm2_rdf_triples_current'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COLS_6 = "subject_uri, predicate_uri, object_value, object_language, object_datatype, context_name"
_COLS_7 = _COLS_6 + ", concept_version_id"


def upgrade() -> None:
    # Swap the 6-col constraint for a 7-col NULLS NOT DISTINCT one so per-version
    # snapshots (same triple, different concept_version_id) are allowed while
    # NULL-owned duplicates are still deduped.
    op.execute("ALTER TABLE rdf_triples DROP CONSTRAINT IF EXISTS uq_rdf_triple")
    op.execute(
        f"ALTER TABLE rdf_triples ADD CONSTRAINT uq_rdf_triple "
        f"UNIQUE NULLS NOT DISTINCT ({_COLS_7})"
    )


def downgrade() -> None:
    # Restore the original 6-column constraint. NOTE: if per-version snapshot rows
    # exist (same 6-tuple, different concept_version_id), this will FAIL on the
    # duplicate — that is correct: you cannot collapse snapshots back into the
    # 6-col uniqueness without losing version history. Remove non-current
    # (is_current=false) duplicate rows first if a true downgrade is required.
    op.execute("ALTER TABLE rdf_triples DROP CONSTRAINT IF EXISTS uq_rdf_triple")
    op.execute(
        f"ALTER TABLE rdf_triples ADD CONSTRAINT uq_rdf_triple UNIQUE ({_COLS_6})"
    )
