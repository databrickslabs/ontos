"""rdf_triples_current view — the current-only read surface (P0-2).

Write-time current/history split: the in-memory hot graph is built from
CURRENT-ONLY triples, and reads carry NO version/is_current predicate. This view
is the granted read surface the PRD P0-1/§4 calls for; the graph-build path
(``_load_triples_from_db_to_graph``) selects from it so the ``is_current`` filter
runs ONCE, at build time, never on reads.

Membership rule (mirrors the P0-1 backfill ownership rule):
- a triple is CURRENT if its owning concept-version has ``is_current = true``, OR
- the triple has NO ``concept_version_id`` (scheme/collection/metadata triples
  that P0-1 left unowned MUST still load — do not drop them).

History triples (owned by a non-current concept-version) are excluded and never
enter the materialized graph.

Postgres-targeted. Reversible: downgrade drops the view.

Revision ID: m2_rdf_triples_current
Revises: m1_concept_versioning
Create Date: 2026-08-12
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'm2_rdf_triples_current'
down_revision: Union[str, None] = 'm1_concept_versioning'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE OR REPLACE VIEW rdf_triples_current AS
        SELECT r.*
        FROM rdf_triples r
        LEFT JOIN concept_version cv ON cv.id = r.concept_version_id
        WHERE r.concept_version_id IS NULL
           OR cv.is_current = true;
    """)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS rdf_triples_current;")
