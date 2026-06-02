"""Repositories for the term-mapping feature."""
from __future__ import annotations

from typing import List, Optional, Sequence
from uuid import UUID

from sqlalchemy import desc, func
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from src.common.logging import get_logger
from src.common.repository import CRUDBase
from src.db_models.term_mappings import (
    MappingApplyRunDb,
    MappingSuggestionDb,
    SUG_STATUS_PENDING,
    SUG_STATUS_REJECTED,
    SUG_STATUS_ACCEPTED,
)
from src.models.term_mappings import RunCreate, RunRead  # update model unused

logger = get_logger(__name__)


def _coerce_uuid(value) -> UUID:
    if isinstance(value, UUID):
        return value
    return UUID(str(value))


class MappingRunRepository(CRUDBase[MappingApplyRunDb, RunCreate, RunRead]):
    def list_recent(self, db: Session, *, limit: int = 50) -> List[MappingApplyRunDb]:
        try:
            return (
                db.query(self.model)
                .order_by(desc(self.model.created_at))
                .limit(limit)
                .all()
            )
        except SQLAlchemyError as e:
            logger.error(f"list_recent runs failed: {e}", exc_info=True)
            db.rollback()
            raise


class MappingSuggestionRepository(CRUDBase[MappingSuggestionDb, MappingSuggestionDb, MappingSuggestionDb]):
    """Suggestion queue. Uses the model itself as the create/update schema —
    the manager constructs db_objs directly for bulk inserts, which is faster
    than per-row Pydantic validation on the suggester hot path."""

    def list_for_run(
        self,
        db: Session,
        run_id,
        *,
        status: Optional[str] = None,
        source_entity_type: Optional[str] = None,
        source_entity_id: Optional[str] = None,
        limit: int = 500,
        offset: int = 0,
    ) -> List[MappingSuggestionDb]:
        try:
            q = db.query(self.model).filter(self.model.run_id == _coerce_uuid(run_id))
            if status:
                q = q.filter(self.model.status == status)
            if source_entity_type:
                q = q.filter(self.model.source_entity_type == source_entity_type)
            if source_entity_id:
                q = q.filter(self.model.source_entity_id == source_entity_id)
            return q.order_by(self.model.source_entity_type, self.model.source_entity_id).offset(offset).limit(limit).all()
        except SQLAlchemyError as e:
            logger.error(f"list_for_run failed: {e}", exc_info=True)
            db.rollback()
            raise

    def list_for_entity(
        self,
        db: Session,
        *,
        entity_type: str,
        entity_id: str,
        statuses: Optional[Sequence[str]] = None,
    ) -> List[MappingSuggestionDb]:
        try:
            q = db.query(self.model).filter(
                self.model.source_entity_type == entity_type,
                self.model.source_entity_id == entity_id,
            )
            if statuses:
                q = q.filter(self.model.status.in_(list(statuses)))
            return q.order_by(desc(self.model.created_at)).all()
        except SQLAlchemyError as e:
            logger.error(f"list_for_entity failed: {e}", exc_info=True)
            db.rollback()
            raise

    def count_pending_for_entity(
        self,
        db: Session,
        *,
        entity_type: str,
        entity_id: str,
    ) -> int:
        try:
            return (
                db.query(func.count(self.model.id))
                .filter(
                    self.model.source_entity_type == entity_type,
                    self.model.source_entity_id == entity_id,
                    self.model.status == SUG_STATUS_PENDING,
                )
                .scalar()
                or 0
            )
        except SQLAlchemyError as e:
            logger.error(f"count_pending_for_entity failed: {e}", exc_info=True)
            db.rollback()
            raise

    def count_auto_apply_for_entity(
        self,
        db: Session,
        *,
        entity_type: str,
        entity_id: str,
    ) -> int:
        try:
            return (
                db.query(func.count(self.model.id))
                .filter(
                    self.model.source_entity_type == entity_type,
                    self.model.source_entity_id == entity_id,
                    self.model.status == SUG_STATUS_PENDING,
                    self.model.auto_apply.is_(True),
                )
                .scalar()
                or 0
            )
        except SQLAlchemyError as e:
            logger.error(f"count_auto_apply_for_entity failed: {e}", exc_info=True)
            db.rollback()
            raise

    def is_pair_already_decided(
        self,
        db: Session,
        *,
        source_entity_type: str,
        source_entity_id: str,
        target_concept_iri: str,
    ) -> bool:
        """Has this (source, target_iri) pair been rejected before? Used by
        the heuristic engine to skip pairs the steward already rejected so
        they don't reappear on every run."""
        try:
            existing = (
                db.query(self.model.id)
                .filter(
                    self.model.source_entity_type == source_entity_type,
                    self.model.source_entity_id == source_entity_id,
                    self.model.target_concept_iri == target_concept_iri,
                    self.model.status == SUG_STATUS_REJECTED,
                )
                .first()
            )
            return existing is not None
        except SQLAlchemyError as e:
            logger.error(f"is_pair_already_decided failed: {e}", exc_info=True)
            db.rollback()
            raise

    def bulk_insert(self, db: Session, rows: List[MappingSuggestionDb]) -> int:
        if not rows:
            return 0
        try:
            db.add_all(rows)
            db.flush()
            return len(rows)
        except SQLAlchemyError as e:
            logger.error(f"bulk_insert suggestions failed: {e}", exc_info=True)
            db.rollback()
            raise


mapping_run_repo = MappingRunRepository(model=MappingApplyRunDb)
mapping_suggestion_repo = MappingSuggestionRepository(model=MappingSuggestionDb)
