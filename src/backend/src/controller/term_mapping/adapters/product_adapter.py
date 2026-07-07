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
        products = q.all()
        # Batch-load primary domains for all products in one query (avoids N+1) — domain
        # moved to the entity_domain_associations junction (#520).
        primary_by_id = self._primary_domains(db, [str(p.id) for p in products])
        for product in products:
            yield self._build(product, primary_by_id.get(str(product.id)))

    def get_target(self, db: Session, entity_id: str) -> Optional[TargetEntity]:
        product = db.query(DataProductDb).filter(DataProductDb.id == entity_id).first()
        if not product:
            return None
        primary_by_id = self._primary_domains(db, [str(product.id)])
        return self._build(product, primary_by_id.get(str(product.id)))

    @staticmethod
    def _primary_domains(db: Session, product_ids: List[str]) -> dict:
        """Batch map of product_id -> primary domain name from the junction table."""
        from src.repositories.entity_domain_association_repository import entity_domain_repo
        domains_map = entity_domain_repo.get_domains_for_entities(
            db, entity_type="data_product", entity_ids=product_ids
        )
        return {
            eid: next((a.domain_name for a in assigned if a.is_primary), None)
            for eid, assigned in domains_map.items()
        }

    def _build(self, product: DataProductDb, primary_domain: Optional[str]) -> TargetEntity:
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
