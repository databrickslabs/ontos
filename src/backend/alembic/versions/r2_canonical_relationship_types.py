"""Store entity relationship types as ontology local names

``entity_relationships.source_type`` / ``target_type`` held whichever spelling the
writer used: the ontology local name ('LogicalEntity', 'MetricView') or the class
label, which is also the asset type name ('Logical Entity', 'Metric View'). Lookups
compare the strings exactly, so links written with labels (API clients, the schema
importer and asset retyping) didn't show on the asset pages, which ask for local
names. New rows are normalized by the model (#956/#957/#959); this rewrites the
stored ones the same way (whitespace removed, the Ontos namespace stripped from
IRIs; other IRIs unchanged). Rows that become the same link (the unique key covers
the type columns) are merged: the oldest is kept, the others are deleted.

Revision ID: r2_canonical_relationship_types
Revises: o1_merge_r1_c7
Create Date: 2026-11-11
"""
import re
from collections import defaultdict
from typing import Optional, Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "r2_canonical_relationship_types"
down_revision: Union[str, Sequence[str], None] = "o1_merge_r1_c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ONTOS_NS = "http://ontos.app/ontology#"
_WHITESPACE = re.compile(r"\s+")


def _canonical(value: Optional[str]) -> Optional[str]:
    """Copy of src.common.ontology_type_names.canonical_type_name, frozen for this revision."""
    if value is None:
        return None
    value = value.strip()
    if value.startswith(ONTOS_NS):
        return value[len(ONTOS_NS):]
    if value.startswith(("http://", "https://")):
        return value
    return _WHITESPACE.sub("", value)


def upgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(sa.text(
        "SELECT id, source_type, source_id, target_type, target_id, relationship_type, created_at "
        "FROM entity_relationships"
    )).fetchall()

    groups = defaultdict(list)
    for row in rows:
        key = (_canonical(row.source_type), row.source_id, _canonical(row.target_type),
               row.target_id, row.relationship_type)
        groups[key].append(row)

    for (source_type, _sid, target_type, _tid, _rel), members in groups.items():
        if len(members) == 1 and (members[0].source_type, members[0].target_type) == (source_type, target_type):
            continue  # already canonical, no duplicate
        members.sort(key=lambda r: (r.created_at is None, r.created_at, str(r.id)))
        keep, *drop = members
        for row in drop:
            conn.execute(sa.text("DELETE FROM entity_relationships WHERE id = :id"), {"id": row.id})
        if (keep.source_type, keep.target_type) != (source_type, target_type):
            conn.execute(
                sa.text("UPDATE entity_relationships SET source_type = :s, target_type = :t WHERE id = :id"),
                {"s": source_type, "t": target_type, "id": keep.id},
            )


def downgrade() -> None:
    # The original spellings are not kept; local names stay valid for every reader.
    pass
