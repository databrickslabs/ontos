"""Archive BusinessTerm assets as Legacy Business Term before the class leaves the ontology

BusinessTerm duplicated OntologyConcept / hasSemanticConcept. Its assets are moved to a
built-in, retired asset type 'Legacy Business Term': not offered in pickers or create,
still readable. The sync that drops the BusinessTerm type would otherwise cascade-delete
its assets (#970), so this runs first (alembic runs before the ontology sync at startup).

Moved assets keep their ids, so their tags, owners, metadata, semantic links and
relationships stay attached. Their entity_relationships rows carry the type name
'BusinessTerm' and are renamed to 'LegacyBusinessTerm', the name the asset page asks for.
Installs without BusinessTerm assets get no moved assets; the ontology sync creates the
(empty, hidden) legacy type on every install.

Revision ID: u5_legacy_business_term
Revises: r2_canonical_relationship_types
Create Date: 2026-11-12
"""
import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "u5_legacy_business_term"
down_revision: Union[str, Sequence[str], None] = "r2_canonical_relationship_types"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

BUSINESS_TERM = "Business Term"
LEGACY = "Legacy Business Term"
OLD_LOCAL_NAME = "BusinessTerm"
NEW_LOCAL_NAME = "LegacyBusinessTerm"
LEGACY_DESCRIPTION = "Business terms archived when BusinessTerm left the ontology (#970)."

ONTOS_NS = "http://ontos.app/ontology#"
ONTOLOGY_CONTEXT = "urn:taxonomy:ontos-ontology"
# Terms the shipped ontology no longer defines. Bundled taxonomies are imported into
# rdf_triples with ON CONFLICT DO NOTHING, so removing them from the TTL alone would
# leave the stored triples (and the BusinessTerm class) in the graph.
REMOVED_ONTOLOGY_TERMS = [
    ONTOS_NS + "BusinessTerm",
    ONTOS_NS + "hasTerm",
    ONTOS_NS + "relatesTo",
    ONTOS_NS + "termDefinition",
    ONTOS_NS + "synonyms",
    ONTOS_NS + "examples",
]


def _prune_removed_ontology_terms(conn) -> None:
    if not sa.inspect(conn).has_table("rdf_triples"):
        return
    for term in REMOVED_ONTOLOGY_TERMS:
        conn.execute(sa.text(
            "DELETE FROM rdf_triples WHERE context_name = :ctx "
            "AND (subject_uri = :term OR object_value = :term)"
        ), {"ctx": ONTOLOGY_CONTEXT, "term": term})


def upgrade() -> None:
    conn = op.get_bind()
    _prune_removed_ontology_terms(conn)
    term_type = conn.execute(
        sa.text("SELECT id FROM asset_types WHERE name = :name"), {"name": BUSINESS_TERM}
    ).first()
    if term_type is None:
        return

    asset_ids = [str(r[0]) for r in conn.execute(
        sa.text("SELECT id FROM assets WHERE asset_type_id = :type_id"), {"type_id": str(term_type.id)}
    ).fetchall()]
    if not asset_ids:
        return  # nothing to keep; the sync removes the empty type

    legacy = conn.execute(
        sa.text("SELECT id FROM asset_types WHERE name = :name"), {"name": LEGACY}
    ).first()
    if legacy is None:
        legacy_id = str(uuid.uuid4())
        conn.execute(sa.text(
            "INSERT INTO asset_types (id, name, description, category, icon, required_fields, "
            "optional_fields, allowed_relationships, is_system, status, created_by, created_at, updated_at) "
            "SELECT :new_id, :name, :description, 'system', 'Archive', required_fields, optional_fields, "
            "allowed_relationships, TRUE, 'retired', 'system@migration', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP "
            "FROM asset_types WHERE id = :term_id"
        ), {"new_id": legacy_id, "name": LEGACY, "description": LEGACY_DESCRIPTION,
            "term_id": str(term_type.id)})
    else:
        legacy_id = str(legacy.id)

    conn.execute(
        sa.text("UPDATE assets SET asset_type_id = :new_id WHERE asset_type_id = :old_id"),
        {"new_id": legacy_id, "old_id": str(term_type.id)},
    )
    conn.execute(sa.text(
        "UPDATE entity_relationships SET source_type = :new WHERE source_type = :old "
        "AND source_id IN (SELECT CAST(id AS TEXT) FROM assets WHERE asset_type_id = :legacy_id)"
    ), {"new": NEW_LOCAL_NAME, "old": OLD_LOCAL_NAME, "legacy_id": legacy_id})
    conn.execute(sa.text(
        "UPDATE entity_relationships SET target_type = :new WHERE target_type = :old "
        "AND target_id IN (SELECT CAST(id AS TEXT) FROM assets WHERE asset_type_id = :legacy_id)"
    ), {"new": NEW_LOCAL_NAME, "old": OLD_LOCAL_NAME, "legacy_id": legacy_id})


def downgrade() -> None:
    # Assets stay in the legacy type; reverting the type name would re-expose them to pickers.
    pass
