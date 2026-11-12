"""Metric View assets and the measure links the KPI consistency views read (#1263)."""
from typing import Iterable, List

from sqlalchemy import func
from sqlalchemy.orm import Session

from src.db_models.assets import AssetDb, AssetTypeDb
from src.db_models.semantic_links import EntitySemanticLinkDb
from src.models.assets import METRIC_VIEW_ASSET_TYPE

# Ids per IN (...) query
_CHUNK = 500


class MetricViewFingerprintsRepository:
    def list_metric_view_assets(self, db: Session) -> List[AssetDb]:
        """Every asset of the Metric View type (fingerprints are in their ``properties``)."""
        return (
            db.query(AssetDb)
            .join(AssetTypeDb, AssetDb.asset_type_id == AssetTypeDb.id)
            .filter(AssetTypeDb.name == METRIC_VIEW_ASSET_TYPE)
            .order_by(AssetDb.location, AssetDb.id)
            .all()
        )

    def list_column_links_for_entities(
        self, db: Session, entity_ids: Iterable[str],
    ) -> List[EntitySemanticLinkDb]:
        """The ``uc_column`` links of any of ``entity_ids``, ignoring case (UC names).

        A metric view field is ``catalog.schema.view.field``.
        """
        ids = sorted({e.lower() for e in entity_ids})
        links: List[EntitySemanticLinkDb] = []
        for start in range(0, len(ids), _CHUNK):
            links.extend(db.query(EntitySemanticLinkDb).filter(
                EntitySemanticLinkDb.entity_type == 'uc_column',
                func.lower(EntitySemanticLinkDb.entity_id).in_(ids[start:start + _CHUNK]),
            ).all())
        return links

    def list_column_links_for_iri(self, db: Session, iri: str) -> List[EntitySemanticLinkDb]:
        return db.query(EntitySemanticLinkDb).filter(
            EntitySemanticLinkDb.entity_type == 'uc_column',
            EntitySemanticLinkDb.iri == iri,
        ).all()

    def list_column_links_for_entity(
        self, db: Session, entity_id: str,
    ) -> List[EntitySemanticLinkDb]:
        """The ``uc_column`` links of ``entity_id``, ignoring case (UC names)."""
        return db.query(EntitySemanticLinkDb).filter(
            EntitySemanticLinkDb.entity_type == 'uc_column',
            func.lower(EntitySemanticLinkDb.entity_id) == entity_id.lower(),
        ).all()


metric_view_fingerprints_repo = MetricViewFingerprintsRepository()
