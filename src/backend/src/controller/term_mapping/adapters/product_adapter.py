"""Adapter for Data Products.

Data Products are terminal targets — there's no sub-entity to map (ports
reference contracts/assets that have their own targets via the other
adapters). One TargetEntity per DataProductDb row.
"""
from __future__ import annotations

from typing import Iterable, List, Optional

from sqlalchemy.orm import Session

from src.db_models.data_products import DataProductDb
from src.models.term_mappings import RunTargetFilter

from ..types import TargetEntity


class ProductAdapter:
    entity_types: List[str] = ["data_product"]

    def list_targets(self, db: Session, filters: RunTargetFilter) -> Iterable[TargetEntity]:
        wanted_types = set(filters.entity_types or self.entity_types)
        if "data_product" not in wanted_types:
            return

        q = db.query(DataProductDb)
        if filters.product_ids:
            q = q.filter(DataProductDb.id.in_(filters.product_ids))
        if filters.domain_ids:
            from src.repositories.entity_domain_association_repository import entity_domain_repo
            matching_ids = entity_domain_repo.find_entity_ids_by_domains(
                db, domain_ids=list(filters.domain_ids), entity_type="data_product"
            )
            q = q.filter(DataProductDb.id.in_(matching_ids))

        if filters.limit:
            q = q.limit(filters.limit)

        # Look up the latest info record for the display name. The DataProductInfoDb
        # rows are versioned per-product; for our purposes the product name on
        # DataProductDb itself is good enough (kept in sync by DataProductsManager).
        for product in q.all():
            yield self._build(db, product)

    def get_target(self, db: Session, entity_id: str) -> Optional[TargetEntity]:
        product = db.query(DataProductDb).filter(DataProductDb.id == entity_id).first()
        return self._build(db, product) if product else None

    def _build(self, db: Session, product: DataProductDb) -> TargetEntity:
        # Domain moved to the entity_domain_associations junction (#520); surface the
        # primary domain name for the target's display metadata.
        from src.repositories.entity_domain_association_repository import entity_domain_repo
        assigned = entity_domain_repo.get_domains_for_entity(
            db, entity_type="data_product", entity_id=str(product.id)
        )
        primary_domain = next((a.domain_name for a in assigned if a.is_primary), None)
        return TargetEntity(
            entity_type="data_product",
            entity_id=str(product.id),
            name=product.name or str(product.id),
            label=product.name or str(product.id),
            extras={
                "version": product.version,
                "status": product.status,
                "domain": primary_domain,
            },
        )
