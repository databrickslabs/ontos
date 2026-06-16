"""Adapter for Assets (and their Columns) — the polymorphic Asset model.

Columns are first-class AssetDb rows linked to their parent Table/View via
EntityRelationshipDb(relationship_type="hasColumn"). For term-mapping we list
target Assets by asset-type name; the default focus is Columns since that's
where the bulk of vocabulary attachment lives.
"""
from __future__ import annotations

from typing import Iterable, List, Optional

from sqlalchemy.orm import Session
from sqlalchemy import text

from src.common.logging import get_logger
from src.db_models.assets import AssetDb, AssetTypeDb
from src.db_models.entity_relationships import EntityRelationshipDb
from src.models.term_mappings import RunTargetFilter

from ..types import TargetEntity

logger = get_logger(__name__)

# Sub-entity types we treat as attribute candidates (vs container types).
_SUB_ENTITY_TYPE_NAMES = {"Column", "Logical Attribute"}


class AssetAdapter:
    entity_types: List[str] = ["asset"]

    def list_targets(self, db: Session, filters: RunTargetFilter) -> Iterable[TargetEntity]:
        # Default to Columns when caller did not specify asset_type_names —
        # mapping concepts to entire tables/datasets is supported but rarely
        # what stewards reach for first.
        asset_type_names: Optional[List[str]] = filters.asset_type_names

        q = (
            db.query(AssetDb, AssetTypeDb)
            .join(AssetTypeDb, AssetDb.asset_type_id == AssetTypeDb.id)
        )

        if asset_type_names:
            q = q.filter(AssetTypeDb.name.in_(asset_type_names))
        else:
            q = q.filter(AssetTypeDb.name == "Column")

        if filters.domain_ids:
            q = q.filter(AssetDb.domain_id.in_(filters.domain_ids))

        if filters.limit:
            q = q.limit(filters.limit)

        # Parent lookup: for Columns, find the hasColumn relationship pointing
        # AT this asset (target). Bulk-resolve to keep this O(1 query) instead
        # of N.
        asset_rows = list(q.all())
        target_ids = [str(a.id) for a, _ in asset_rows]
        parents = _bulk_resolve_parents(db, target_ids) if target_ids else {}

        for asset, asset_type in asset_rows:
            yield self._build(asset, asset_type, parents.get(str(asset.id)))

    def get_target(self, db: Session, entity_id: str) -> Optional[TargetEntity]:
        row = (
            db.query(AssetDb, AssetTypeDb)
            .join(AssetTypeDb, AssetDb.asset_type_id == AssetTypeDb.id)
            .filter(AssetDb.id == entity_id)
            .first()
        )
        if row is None:
            return None
        asset, asset_type = row
        parents = _bulk_resolve_parents(db, [str(asset.id)])
        return self._build(asset, asset_type, parents.get(str(asset.id)))

    def _build(self, asset: AssetDb, asset_type: AssetTypeDb, parent: Optional[dict]) -> TargetEntity:
        asset_id = str(asset.id)
        is_sub_entity = asset_type.name in _SUB_ENTITY_TYPE_NAMES
        props = asset.properties or {}
        parent_label = parent.get("name") if parent else None
        return TargetEntity(
            entity_type="asset",
            entity_id=asset_id,
            name=asset.name,
            label=asset.name,
            type_label=str(props.get("columnDataType") or props.get("dataType") or ""),
            parent_entity_type="asset" if is_sub_entity and parent else None,
            parent_entity_id=parent.get("id") if (is_sub_entity and parent) else None,
            parent_name=parent_label if is_sub_entity else None,
            is_pk=bool(props.get("isPrimaryKey")),
            is_fk=bool(props.get("isForeignKey")),
            extras={
                "asset_type_name": asset_type.name,
                "platform": asset.platform,
                "location": asset.location,
                "classification": props.get("classification"),
            },
        )


def _bulk_resolve_parents(db: Session, target_asset_ids: List[str]) -> dict:
    """Map child asset id → {id, name} of its hasColumn parent (if any).

    Uses a single SQL query instead of iterating EntityRelationshipDb +
    AssetDb joins per row.
    """
    if not target_asset_ids:
        return {}
    try:
        rows = db.execute(
            text(
                """
                SELECT er.target_id::text AS child_id,
                       a.id::text AS parent_id,
                       a.name AS parent_name
                FROM entity_relationships er
                JOIN assets a ON a.id::text = er.source_id
                WHERE er.relationship_type = 'hasColumn'
                  AND er.target_id IN :ids
                """
            ).bindparams().params(ids=tuple(target_asset_ids))
        ).fetchall()
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("Failed to bulk-resolve parents for asset adapter: %s", e)
        return {}
    return {row.child_id: {"id": row.parent_id, "name": row.parent_name} for row in rows}
