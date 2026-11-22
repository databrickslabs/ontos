"""BFS certification inheritance propagator.

Propagates certification levels downward through entity relationships.
Uses a transitive BFS: DataProduct -> DataContract -> Asset.

The effective certification level is max(own, inherited).
"""

from collections import deque
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy import text

from src.common.ontology_type_names import canonical_type_name
from src.common.logging import get_logger

logger = get_logger(__name__)

# Relationship types that form the inheritance chain (source -> target)
INHERITANCE_RELATIONSHIPS = {
    "hasContract", "hasOutputPort", "hasDataset", "hasAsset",
    "governedBy", "implementedBy", "contains", "hasColumn",
}

# Entity type -> table name mapping
ENTITY_TABLE_MAP = {
    "DataProduct": "data_products",
    "DataContract": "data_contracts",
    "Asset": "assets",
}


def _get_certification_level(db: Session, entity_type: str, entity_id: str) -> Optional[int]:
    """Get the own certification_level for an entity."""
    table = ENTITY_TABLE_MAP.get(entity_type)
    if not table:
        return None
    try:
        result = db.execute(
            text(f"SELECT certification_level FROM {table} WHERE id = :eid"),
            {"eid": entity_id},
        ).fetchone()
        return result[0] if result else None
    except Exception:
        return None


def _set_inherited_level(db: Session, entity_type: str, entity_id: str, level: int) -> None:
    """Set the inherited_certification_level for an entity."""
    table = ENTITY_TABLE_MAP.get(entity_type)
    if not table:
        return
    try:
        db.execute(
            text(f"UPDATE {table} SET inherited_certification_level = :lvl WHERE id = :eid"),
            {"lvl": level, "eid": entity_id},
        )
    except Exception as e:
        logger.warning(f"Could not set inherited level on {entity_type}:{entity_id}: {e}")


def _get_downstream_entities(db: Session, source_type: str, source_id: str) -> list[tuple[str, str]]:
    """Get all downstream entities connected via inheritance relationships."""
    from src.db_models.entity_relationships import EntityRelationshipDb

    rels = (
        db.query(EntityRelationshipDb)
        .filter(
            EntityRelationshipDb.source_type == canonical_type_name(source_type),
            EntityRelationshipDb.source_id == source_id,
            EntityRelationshipDb.relationship_type.in_(INHERITANCE_RELATIONSHIPS),
        )
        .all()
    )
    return [(r.target_type, r.target_id) for r in rels]


def propagate_certification(db: Session, source_type: str, source_id: str) -> int:
    """BFS propagation of certification level from a source entity downward.

    Updates inherited_certification_level on all reachable downstream entities.
    Returns the count of entities updated.
    """
    source_level = _get_certification_level(db, source_type, source_id)
    if not source_level:
        logger.debug(f"No certification level on {source_type}:{source_id}, skipping propagation")
        return 0

    visited = set()
    queue = deque()
    updated_count = 0

    for target_type, target_id in _get_downstream_entities(db, source_type, source_id):
        queue.append((target_type, target_id, source_level))

    while queue:
        entity_type, entity_id, incoming_level = queue.popleft()
        key = (entity_type, entity_id)
        if key in visited:
            continue
        visited.add(key)

        own_level = _get_certification_level(db, entity_type, entity_id) or 0
        effective_inherited = max(incoming_level, own_level)

        _set_inherited_level(db, entity_type, entity_id, incoming_level)
        updated_count += 1

        for child_type, child_id in _get_downstream_entities(db, entity_type, entity_id):
            if (child_type, child_id) not in visited:
                queue.append((child_type, child_id, effective_inherited))

    logger.info(
        f"Certification propagation from {source_type}:{source_id} "
        f"(level={source_level}) updated {updated_count} downstream entities"
    )
    return updated_count


def propagate_all(db: Session) -> int:
    """Propagate certification for all certified entities. Useful for batch recalculation."""
    total = 0
    for entity_type, table_name in ENTITY_TABLE_MAP.items():
        try:
            rows = db.execute(
                text(f"SELECT id FROM {table_name} WHERE certification_level IS NOT NULL")
            ).fetchall()
            for row in rows:
                total += propagate_certification(db, entity_type, str(row[0]))
        except Exception as e:
            logger.warning(f"Error propagating for {entity_type}: {e}")
    return total
