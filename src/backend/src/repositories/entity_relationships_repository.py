"""Repository for the cross-tier entity relationship table."""

from typing import Iterable, List, Optional, Set
from uuid import UUID

from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import or_

from src.common.repository import CRUDBase
from src.db_models.entity_relationships import EntityRelationshipDb
from src.models.entity_relationships import EntityRelationshipCreate
from src.common.logging import get_logger

logger = get_logger(__name__)


class EntityRelationshipRepository(CRUDBase[EntityRelationshipDb, EntityRelationshipCreate, EntityRelationshipCreate]):
    def __init__(self):
        super().__init__(EntityRelationshipDb)
        logger.info("EntityRelationshipRepository initialized.")

    @staticmethod
    def _to_uuid(value: object) -> Optional[UUID]:
        """Best-effort conversion of an entity_relationship target_id to UUID.

        Returns None when the target_id is not UUID-shaped (asset IDs always are,
        but some legacy rows may store synthetic IDs).
        """
        if value is None:
            return None
        if isinstance(value, UUID):
            return value
        try:
            return UUID(str(value))
        except (ValueError, TypeError, AttributeError):
            return None

    def get_asset_ids_linked_to_products(
        self,
        db: Session,
        *,
        product_ids: Iterable[str],
        port_ids: Optional[Iterable[str]] = None,
    ) -> Set[UUID]:
        """Return the set of asset UUIDs linked to the given DPs / OutputPorts via
        ``entity_relationships``.

        Considers outgoing relationships where source is DataProduct/OutputPort.
        Asset-tier target IDs are stored as UUIDs (string form) in target_id.
        """
        pid_list = [str(p) for p in product_ids]
        port_list = [str(p) for p in (port_ids or [])]
        if not pid_list and not port_list:
            return set()

        try:
            clauses = []
            if pid_list:
                clauses.append(
                    (self.model.source_type == "DataProduct")
                    & self.model.source_id.in_(pid_list)
                )
            if port_list:
                clauses.append(
                    (self.model.source_type == "OutputPort")
                    & self.model.source_id.in_(port_list)
                )

            rows = (
                db.query(self.model.target_id)
                .filter(or_(*clauses))
                .all()
            )
            result: Set[UUID] = set()
            for (target_id,) in rows:
                uid = self._to_uuid(target_id)
                if uid is not None:
                    result.add(uid)
            return result
        except SQLAlchemyError:
            logger.exception("Failed to resolve DP-linked asset IDs")
            return set()

    def get_by_source(
        self, db: Session, *, source_type: str, source_id: str
    ) -> List[EntityRelationshipDb]:
        try:
            return (
                db.query(self.model)
                .filter(
                    self.model.source_type == source_type,
                    self.model.source_id == source_id,
                )
                .order_by(self.model.relationship_type, self.model.created_at)
                .all()
            )
        except SQLAlchemyError as e:
            logger.error(f"DB error fetching relationships by source {source_type}:{source_id}: {e}", exc_info=True)
            db.rollback()
            raise

    def get_by_target(
        self, db: Session, *, target_type: str, target_id: str
    ) -> List[EntityRelationshipDb]:
        try:
            return (
                db.query(self.model)
                .filter(
                    self.model.target_type == target_type,
                    self.model.target_id == target_id,
                )
                .order_by(self.model.relationship_type, self.model.created_at)
                .all()
            )
        except SQLAlchemyError as e:
            logger.error(f"DB error fetching relationships by target {target_type}:{target_id}: {e}", exc_info=True)
            db.rollback()
            raise

    def get_by_source_and_type(
        self, db: Session, *, source_type: str, source_id: str, relationship_type: str
    ) -> List[EntityRelationshipDb]:
        try:
            return (
                db.query(self.model)
                .filter(
                    self.model.source_type == source_type,
                    self.model.source_id == source_id,
                    self.model.relationship_type == relationship_type,
                )
                .order_by(self.model.created_at)
                .all()
            )
        except SQLAlchemyError as e:
            logger.error(f"DB error fetching by source+type: {e}", exc_info=True)
            db.rollback()
            raise

    def get_by_target_and_type(
        self, db: Session, *, target_type: str, target_id: str, relationship_type: str
    ) -> List[EntityRelationshipDb]:
        try:
            return (
                db.query(self.model)
                .filter(
                    self.model.target_type == target_type,
                    self.model.target_id == target_id,
                    self.model.relationship_type == relationship_type,
                )
                .order_by(self.model.created_at)
                .all()
            )
        except SQLAlchemyError as e:
            logger.error(f"DB error fetching by target+type: {e}", exc_info=True)
            db.rollback()
            raise

    def get_for_entity(
        self, db: Session, *, entity_type: str, entity_id: str
    ) -> List[EntityRelationshipDb]:
        """All relationships where the entity is source or target."""
        try:
            return (
                db.query(self.model)
                .filter(
                    or_(
                        (self.model.source_type == entity_type) & (self.model.source_id == entity_id),
                        (self.model.target_type == entity_type) & (self.model.target_id == entity_id),
                    )
                )
                .order_by(self.model.relationship_type, self.model.created_at)
                .all()
            )
        except SQLAlchemyError as e:
            logger.error(f"DB error fetching relationships for entity {entity_type}:{entity_id}: {e}", exc_info=True)
            db.rollback()
            raise

    def find_existing(
        self, db: Session, *,
        source_type: str, source_id: str,
        target_type: str, target_id: str,
        relationship_type: str,
    ) -> Optional[EntityRelationshipDb]:
        try:
            return (
                db.query(self.model)
                .filter(
                    self.model.source_type == source_type,
                    self.model.source_id == source_id,
                    self.model.target_type == target_type,
                    self.model.target_id == target_id,
                    self.model.relationship_type == relationship_type,
                )
                .first()
            )
        except SQLAlchemyError as e:
            logger.error(f"DB error checking existing relationship: {e}", exc_info=True)
            db.rollback()
            raise

    def query_filtered(
        self, db: Session, *,
        source_type: Optional[str] = None, source_id: Optional[str] = None,
        target_type: Optional[str] = None, target_id: Optional[str] = None,
        relationship_type: Optional[str] = None,
        skip: int = 0, limit: int = 100,
    ) -> List[EntityRelationshipDb]:
        try:
            q = db.query(self.model)
            if source_type:
                q = q.filter(self.model.source_type == source_type)
            if source_id:
                q = q.filter(self.model.source_id == source_id)
            if target_type:
                q = q.filter(self.model.target_type == target_type)
            if target_id:
                q = q.filter(self.model.target_id == target_id)
            if relationship_type:
                q = q.filter(self.model.relationship_type == relationship_type)
            return q.order_by(self.model.created_at.desc()).offset(skip).limit(limit).all()
        except SQLAlchemyError as e:
            logger.error(f"DB error querying relationships: {e}", exc_info=True)
            db.rollback()
            raise


entity_relationship_repo = EntityRelationshipRepository()
