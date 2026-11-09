"""Repository for polymorphic entity↔domain assignments.

This is the deep module for multi-domain assignment. It encapsulates:

* replace-all semantics for an entity's domains (``set_domains_for_entity``),
* the at-most-one-primary-per-entity invariant,
* batch reads for list endpoints (``get_domains_for_entities`` — avoids N+1),
* inverse "any-of" lookups (``find_entity_ids_by_domain`` / ``find_entity_ids_by_domains``),
* the domain-deletion blocking check (``get_entities_with_primary_domain``).

Its interface mirrors ``EntityTagAssociationRepository.set_tags_for_entity``.
"""
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from src.common.logging import get_logger
from src.common.repository import CRUDBase
from src.db_models.data_domains import DataDomain
from src.db_models.domain_associations import EntityDomainAssociationDb
from src.models.domain_associations import AssignedDomain
from pydantic import BaseModel

logger = get_logger(__name__)


class EntityDomainAssociationRepository(CRUDBase[EntityDomainAssociationDb, BaseModel, BaseModel]):
    # ------------------------------------------------------------------ reads

    def get_associations_for_entity(
        self, db: Session, *, entity_type: str, entity_id: str
    ) -> List[EntityDomainAssociationDb]:
        return (
            db.query(EntityDomainAssociationDb)
            .filter(
                EntityDomainAssociationDb.entity_type == entity_type,
                EntityDomainAssociationDb.entity_id == entity_id,
            )
            .all()
        )

    def get_domains_for_entity(
        self, db: Session, *, entity_type: str, entity_id: str
    ) -> List[AssignedDomain]:
        """Return the entity's assigned domains (primary first), with domain names."""
        rows = (
            db.query(
                EntityDomainAssociationDb.domain_id,
                DataDomain.name.label("domain_name"),
                EntityDomainAssociationDb.is_primary,
                EntityDomainAssociationDb.assigned_by,
                EntityDomainAssociationDb.assigned_at,
            )
            .join(DataDomain, DataDomain.id == EntityDomainAssociationDb.domain_id)
            .filter(
                EntityDomainAssociationDb.entity_type == entity_type,
                EntityDomainAssociationDb.entity_id == entity_id,
            )
            .all()
        )
        assigned = [
            AssignedDomain(
                domain_id=r.domain_id,
                domain_name=r.domain_name,
                is_primary=bool(r.is_primary),
                assigned_by=r.assigned_by,
                assigned_at=r.assigned_at,
            )
            for r in rows
        ]
        # Primary first, then by name for stable ordering.
        assigned.sort(key=lambda d: (not d.is_primary, (d.domain_name or "").lower()))
        return assigned

    def get_domains_for_entities(
        self, db: Session, *, entity_type: str, entity_ids: List[str]
    ) -> Dict[str, List[AssignedDomain]]:
        """Batch-load domains for many entities. Returns {entity_id: [AssignedDomain, ...]}."""
        if not entity_ids:
            return {}
        rows = (
            db.query(
                EntityDomainAssociationDb.entity_id,
                EntityDomainAssociationDb.domain_id,
                DataDomain.name.label("domain_name"),
                EntityDomainAssociationDb.is_primary,
                EntityDomainAssociationDb.assigned_by,
                EntityDomainAssociationDb.assigned_at,
            )
            .join(DataDomain, DataDomain.id == EntityDomainAssociationDb.domain_id)
            .filter(
                EntityDomainAssociationDb.entity_type == entity_type,
                EntityDomainAssociationDb.entity_id.in_(entity_ids),
            )
            .all()
        )
        result: Dict[str, List[AssignedDomain]] = {eid: [] for eid in entity_ids}
        for r in rows:
            result.setdefault(r.entity_id, []).append(
                AssignedDomain(
                    domain_id=r.domain_id,
                    domain_name=r.domain_name,
                    is_primary=bool(r.is_primary),
                    assigned_by=r.assigned_by,
                    assigned_at=r.assigned_at,
                )
            )
        for eid in result:
            result[eid].sort(key=lambda d: (not d.is_primary, (d.domain_name or "").lower()))
        return result

    def get_primary_domain_id(
        self, db: Session, *, entity_type: str, entity_id: str
    ) -> Optional[str]:
        row = (
            db.query(EntityDomainAssociationDb.domain_id)
            .filter(
                EntityDomainAssociationDb.entity_type == entity_type,
                EntityDomainAssociationDb.entity_id == entity_id,
                EntityDomainAssociationDb.is_primary.is_(True),
            )
            .first()
        )
        return row.domain_id if row else None

    # ---------------------------------------------------------------- inverse

    def find_entity_ids_by_domain(
        self, db: Session, *, domain_id: str, entity_type: str, primary_only: bool = False
    ) -> List[str]:
        return self.find_entity_ids_by_domains(
            db, domain_ids=[domain_id], entity_type=entity_type, primary_only=primary_only
        )

    def find_entity_ids_by_domains(
        self, db: Session, *, domain_ids: List[str], entity_type: str, primary_only: bool = False
    ) -> List[str]:
        """Entity IDs assigned to ANY of the given domains (any-of semantics)."""
        if not domain_ids:
            return []
        query = (
            db.query(EntityDomainAssociationDb.entity_id)
            .filter(
                EntityDomainAssociationDb.entity_type == entity_type,
                EntityDomainAssociationDb.domain_id.in_(domain_ids),
            )
        )
        if primary_only:
            query = query.filter(EntityDomainAssociationDb.is_primary.is_(True))
        return [row.entity_id for row in query.distinct().all()]

    def find_entity_ids_with_any_domain(self, db: Session, *, entity_type: str) -> List[str]:
        """Entity IDs that have at least one domain assignment."""
        rows = (
            db.query(EntityDomainAssociationDb.entity_id)
            .filter(EntityDomainAssociationDb.entity_type == entity_type)
            .distinct()
            .all()
        )
        return [row.entity_id for row in rows]

    # ------------------------------------------------------- deletion support

    def get_entities_with_primary_domain(
        self, db: Session, *, domain_id: str, entity_type: Optional[str] = None
    ) -> List[Tuple[str, str]]:
        """Return (entity_type, entity_id) for every entity that has this domain as PRIMARY.

        Used to block domain deletion (a domain in use as a primary cannot be deleted).
        """
        query = db.query(
            EntityDomainAssociationDb.entity_type, EntityDomainAssociationDb.entity_id
        ).filter(
            EntityDomainAssociationDb.domain_id == domain_id,
            EntityDomainAssociationDb.is_primary.is_(True),
        )
        if entity_type:
            query = query.filter(EntityDomainAssociationDb.entity_type == entity_type)
        return [(row.entity_type, row.entity_id) for row in query.all()]

    def get_assignment_counts_for_domain(self, db: Session, *, domain_id: str) -> Dict[str, Dict[str, int]]:
        """Per-entity-type counts of primary vs additional assignments for a domain.

        Returns {entity_type: {"primary": n, "additional": m}}.
        """
        rows = (
            db.query(EntityDomainAssociationDb.entity_type, EntityDomainAssociationDb.is_primary)
            .filter(EntityDomainAssociationDb.domain_id == domain_id)
            .all()
        )
        counts: Dict[str, Dict[str, int]] = {}
        for entity_type, is_primary in rows:
            bucket = counts.setdefault(entity_type, {"primary": 0, "additional": 0})
            bucket["primary" if is_primary else "additional"] += 1
        return counts

    def remove_all_for_domain(self, db: Session, *, domain_id: str) -> int:
        """Delete every association row for a domain (used when deleting a domain that is
        only ever an additional domain). Returns the number of rows removed."""
        deleted = (
            db.query(EntityDomainAssociationDb)
            .filter(EntityDomainAssociationDb.domain_id == domain_id)
            .delete(synchronize_session=False)
        )
        return deleted

    def remove_all_for_entity(self, db: Session, *, entity_type: str, entity_id: str) -> int:
        """Delete every domain association for an entity (used when the entity is deleted)."""
        deleted = (
            db.query(EntityDomainAssociationDb)
            .filter(
                EntityDomainAssociationDb.entity_type == entity_type,
                EntityDomainAssociationDb.entity_id == entity_id,
            )
            .delete(synchronize_session=False)
        )
        return deleted

    # ------------------------------------------------------------- write path

    def set_domains_for_entity(
        self,
        db: Session,
        *,
        entity_type: str,
        entity_id: str,
        domain_ids: List[str],
        primary_domain_id: Optional[str] = None,
        assigned_by: Optional[str] = None,
        validate_exist: bool = True,
    ) -> List[AssignedDomain]:
        """Replace all of an entity's domain assignments with the provided set.

        Enforces the at-most-one-primary invariant: when ``domain_ids`` is non-empty
        exactly one association is primary (defaults to the first id when
        ``primary_domain_id`` is not supplied); when empty the entity is left unassigned.
        Idempotent and safe against the partial-unique primary index (never leaves two
        primaries visible at a flush).
        """
        # De-duplicate while preserving order.
        seen = set()
        ordered_ids: List[str] = []
        for did in domain_ids:
            if did not in seen:
                seen.add(did)
                ordered_ids.append(did)

        # Resolve/validate the primary.
        if not ordered_ids:
            primary = None
        elif primary_domain_id is not None:
            if primary_domain_id not in seen:
                raise ValueError("primary_domain_id must be one of domain_ids")
            primary = primary_domain_id
        else:
            primary = ordered_ids[0]

        # Optionally validate domains exist (raise on unknown to keep the API contract strict).
        if validate_exist and ordered_ids:
            existing = {
                row.id
                for row in db.query(DataDomain.id).filter(DataDomain.id.in_(ordered_ids)).all()
            }
            missing = [d for d in ordered_ids if d not in existing]
            if missing:
                raise ValueError(f"Unknown data domain id(s): {', '.join(missing)}")

        current = {a.domain_id: a for a in self.get_associations_for_entity(
            db, entity_type=entity_type, entity_id=entity_id
        )}

        # 1. Delete associations that are no longer wanted.
        for did, assoc in list(current.items()):
            if did not in seen:
                db.delete(assoc)
                del current[did]

        # 2. Upsert every wanted association with is_primary=False first, so no two rows
        #    are primary at the coming flush (protects the partial unique index).
        for did in ordered_ids:
            assoc = current.get(did)
            if assoc is None:
                assoc = EntityDomainAssociationDb(
                    entity_type=entity_type,
                    entity_id=entity_id,
                    domain_id=did,
                    is_primary=False,
                    assigned_by=assigned_by,
                )
                db.add(assoc)
                current[did] = assoc
            else:
                assoc.is_primary = False
        db.flush()

        # 3. Promote the single primary.
        if primary is not None:
            current[primary].is_primary = True
            db.flush()

        return self.get_domains_for_entity(db, entity_type=entity_type, entity_id=entity_id)


# Module-level singleton (mirrors tags_repository)
entity_domain_repo = EntityDomainAssociationRepository(EntityDomainAssociationDb)
