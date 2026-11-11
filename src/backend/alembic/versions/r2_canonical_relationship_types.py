"""Store entity relationship types as ontology local names

``entity_relationships.source_type`` / ``target_type`` held whichever spelling the
writer used: the ontology local name ('LogicalEntity', 'MetricView') or the class
label, which is also the asset type name ('Logical Entity', 'Metric View'). Lookups
compare the strings exactly, so links written with labels (API clients, the schema
importer and asset retyping) didn't show on the asset pages, which ask for local
names. New rows are normalized by the model (#956/#957/#959); this rewrites the
stored ones the same way (whitespace removed, the Ontos namespace stripped from
IRIs; other IRIs unchanged). A row that becomes a duplicate of a row already
stored with the local name is dropped, keeping the oldest.

Revision ID: r2_canonical_relationship_types
Revises: r1_role_hidden_nav_features
Create Date: 2026-11-11
"""
from typing import Sequence, Union

from alembic import op


revision: str = "r2_canonical_relationship_types"
down_revision: Union[str, Sequence[str], None] = "r1_role_hidden_nav_features"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ONTOS_NS = "http://ontos.app/ontology#"


def _canonical(column: str) -> str:
    """SQL for canonical_type_name() (src/common/ontology_type_names.py)."""
    return (
        f"CASE WHEN {column} LIKE '{ONTOS_NS}%' THEN substr({column}, {len(ONTOS_NS) + 1}) "
        f"WHEN {column} LIKE 'http://%' OR {column} LIKE 'https://%' THEN {column} "
        f"ELSE regexp_replace({column}, '\\s+', '', 'g') END"
    )


def upgrade() -> None:
    src = _canonical("source_type")
    tgt = _canonical("target_type")
    needs_rewrite = f"(source_type <> {src} OR target_type <> {tgt})"
    # Drop rows that would collide with another row once both are normalized
    # (the unique constraint covers the type columns); keep the oldest.
    op.execute(f"""
        DELETE FROM entity_relationships
        WHERE id IN (
            SELECT id FROM (
                SELECT id,
                       row_number() OVER (
                           PARTITION BY {src}, source_id, {tgt}, target_id, relationship_type
                           ORDER BY created_at, id
                       ) AS rn
                FROM entity_relationships
            ) ranked
            WHERE rn > 1
        )
    """)
    op.execute(f"""
        UPDATE entity_relationships
        SET source_type = {src}, target_type = {tgt}
        WHERE {needs_rewrite}
    """)


def downgrade() -> None:
    # The original spellings are not kept; local names stay valid for every reader.
    pass
