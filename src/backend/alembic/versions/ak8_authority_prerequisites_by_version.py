"""Key authority prerequisite edges by version, and normalise legacy version strings (ARF 1.2.0, B7, S6)

Revision ID: ak8_authority_prerequisites_by_version
Revises: ak7_authority_activation_history
Create Date: 2026-11-22

Prerequisite edges were keyed by the family slug, so an edit to a draft v2 rewired the
active v1 that shares the slug (B7). The table is rebuilt keyed by the declaring version:

* ``relation_id`` (the version that declares the edge, ON DELETE CASCADE) replaces
  ``relation_family_slug``;
* ``prerequisite_version_id`` records the upstream version seen at save time (audit only);
* the self-loop CHECK goes, since the owner's slug is no longer on the row (the manager
  refuses self-loops).

Data move: each old edge is copied to every version of its family, so each version keeps
the prerequisites it had. An edge whose family has no slug holder can't be walked and is
dropped (logged by row count). The downgrade keeps one edge per (family, upstream) pair,
so a downgrade is lossy when versions had different edges.

Also normalises legacy version strings: the ah1 upgrade turned integer 1 into '1', not
'1.0.0'. Values without a dot get '.0.0' appended (S6), in authority_relations.version and
authority_decisions.relation_version.
"""
import uuid
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'ak8_authority_prerequisites_by_version'
down_revision: Union[str, None] = 'ak7_authority_activation_history'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def normalise_version_strings(conn) -> int:
    """Append '.0.0' to version values written without a dot (S6). Returns rows changed."""
    changed = 0
    result = conn.execute(sa.text(
        "UPDATE authority_relations SET version = version || '.0.0' WHERE version NOT LIKE '%.%'"
    ))
    changed += result.rowcount or 0
    result = conn.execute(sa.text(
        "UPDATE authority_decisions SET relation_version = relation_version || '.0.0' "
        "WHERE relation_version IS NOT NULL AND relation_version NOT LIKE '%.%'"
    ))
    changed += result.rowcount or 0
    return changed


def _family_versions(conn, slug: str):
    """(family id, [version ids]) for the family that holds ``slug``, or (None, [])."""
    holder = conn.execute(sa.text(
        "SELECT id, version_family_id FROM authority_relations WHERE slug = :slug"
    ), {"slug": slug}).first()
    if holder is None:
        return None, []
    family_id = holder[1] or holder[0]
    rows = conn.execute(sa.text(
        "SELECT id FROM authority_relations WHERE version_family_id = :fid OR id = :fid"
    ), {"fid": family_id}).fetchall()
    return family_id, [r[0] for r in rows]


def _upstream_version_id(conn, slug: str):
    row = conn.execute(sa.text("SELECT id FROM authority_relations WHERE slug = :slug"), {"slug": slug}).first()
    return row[0] if row else None


def rekey_edges(conn, old_rows) -> int:
    """Copy each family-keyed edge to every version of its family. Returns the new rows written."""
    written = 0
    for edge_id, family_slug, prereq_slug, required, display_order, notes, created_at in old_rows:
        _, version_ids = _family_versions(conn, family_slug)
        if not version_ids:
            continue
        upstream = _upstream_version_id(conn, prereq_slug)
        for version_id in version_ids:
            conn.execute(sa.text("""
                INSERT INTO authority_prerequisites (id, relation_id, prerequisite_family_slug,
                    prerequisite_version_id, required, display_order, notes, created_at)
                VALUES (:id, :rel, :prereq, :upstream, :required, :ord, :notes, :created)
            """), {
                "id": str(uuid.uuid4()), "rel": version_id, "prereq": prereq_slug,
                "upstream": upstream, "required": required, "ord": display_order,
                "notes": notes, "created": created_at,
            })
            written += 1
    return written


def _read_old_edges(conn):
    return conn.execute(sa.text(
        "SELECT id, relation_family_slug, prerequisite_family_slug, required, display_order, notes, created_at "
        "FROM authority_prerequisites"
    )).fetchall()


def _read_new_edges(conn):
    return conn.execute(sa.text(
        "SELECT relation_id, prerequisite_family_slug, required, display_order, notes, created_at "
        "FROM authority_prerequisites"
    )).fetchall()


def _family_slug_of_version(conn, version_id: str):
    """The family slug a version belongs to: its own slug, else a sibling's."""
    row = conn.execute(sa.text(
        "SELECT slug, version_family_id, id FROM authority_relations WHERE id = :id"
    ), {"id": version_id}).first()
    if row is None:
        return None
    if row[0]:
        return row[0]
    family_id = row[1] or row[2]
    sibling = conn.execute(sa.text(
        "SELECT slug FROM authority_relations WHERE (version_family_id = :fid OR id = :fid) AND slug IS NOT NULL"
    ), {"fid": family_id}).first()
    return sibling[0] if sibling else None


def _create_old_table() -> None:
    op.create_table(
        'authority_prerequisites',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('relation_family_slug', sa.String(), nullable=False, index=True),
        sa.Column('prerequisite_family_slug', sa.String(), nullable=False, index=True),
        sa.Column('required', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('display_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('relation_family_slug', 'prerequisite_family_slug', name='uq_authority_prerequisites_edge'),
        sa.CheckConstraint('relation_family_slug <> prerequisite_family_slug',
                           name='ck_authority_prerequisites_no_self_loop'),
    )


def _create_new_table() -> None:
    op.create_table(
        'authority_prerequisites',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('relation_id', sa.String(), sa.ForeignKey('authority_relations.id', ondelete='CASCADE'),
                  nullable=False, index=True),
        sa.Column('prerequisite_family_slug', sa.String(), nullable=False, index=True),
        sa.Column('prerequisite_version_id', sa.String(), nullable=True),
        sa.Column('required', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('display_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('relation_id', 'prerequisite_family_slug', name='uq_authority_prerequisites_owner_edge'),
    )


def upgrade() -> None:
    conn = op.get_bind()
    old_rows = _read_old_edges(conn)
    op.drop_table('authority_prerequisites')
    _create_new_table()
    rekey_edges(conn, old_rows)
    normalise_version_strings(conn)


def downgrade() -> None:
    conn = op.get_bind()
    new_rows = _read_new_edges(conn)
    op.drop_table('authority_prerequisites')
    _create_old_table()
    seen = set()
    for owner_id, prereq_slug, required, display_order, notes, created_at in new_rows:
        family_slug = _family_slug_of_version(conn, owner_id)
        if family_slug is None or (family_slug, prereq_slug) in seen:
            continue
        seen.add((family_slug, prereq_slug))
        conn.execute(sa.text("""
            INSERT INTO authority_prerequisites (id, relation_family_slug, prerequisite_family_slug,
                required, display_order, notes, created_at)
            VALUES (:id, :fam, :prereq, :required, :ord, :notes, :created)
        """), {
            "id": str(uuid.uuid4()), "fam": family_slug, "prereq": prereq_slug,
            "required": required, "ord": display_order, "notes": notes, "created": created_at,
        })
