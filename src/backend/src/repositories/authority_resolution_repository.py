"""Repositories for the Authority Resolution feature (CRUDBase-backed)."""
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.common.repository import CRUDBase
from src.db_models.authority_resolution import (
    AuthorityRelationDb,
    AuthorityAffirmationDb,
    AuthorityCriterionDb,
    AuthorityDecisionDb,
    AuthorityDnaRunDb,
)


class AuthorityRelationRepository(CRUDBase[AuthorityRelationDb, Dict[str, Any], Dict[str, Any]]):
    def __init__(self):
        super().__init__(AuthorityRelationDb)

    def list_all(self, db: Session) -> List[AuthorityRelationDb]:
        stmt = select(AuthorityRelationDb).order_by(AuthorityRelationDb.updated_at.desc())
        return list(db.execute(stmt).scalars().all())

    def list_by_ids(self, db: Session, ids: List[str]) -> List[AuthorityRelationDb]:
        if not ids:
            return []
        stmt = (
            select(AuthorityRelationDb)
            .where(AuthorityRelationDb.id.in_(ids))
            .order_by(AuthorityRelationDb.updated_at.desc())
        )
        return list(db.execute(stmt).scalars().all())

    def get_by_slug(self, db: Session, slug: str) -> Optional[AuthorityRelationDb]:
        stmt = select(AuthorityRelationDb).where(AuthorityRelationDb.slug == slug)
        return db.execute(stmt).scalars().first()


class AuthorityAffirmationRepository(CRUDBase[AuthorityAffirmationDb, Dict[str, Any], Dict[str, Any]]):
    def __init__(self):
        super().__init__(AuthorityAffirmationDb)

    def list_for_relation(self, db: Session, *, relation_id: str) -> List[AuthorityAffirmationDb]:
        stmt = (
            select(AuthorityAffirmationDb)
            .where(AuthorityAffirmationDb.relation_id == relation_id)
            .order_by(AuthorityAffirmationDb.sort_order.asc())
        )
        return list(db.execute(stmt).scalars().all())

    def delete_for_relation(self, db: Session, *, relation_id: str) -> int:
        deleted = (
            db.query(AuthorityAffirmationDb)
            .filter(AuthorityAffirmationDb.relation_id == relation_id)
            .delete(synchronize_session=False)
        )
        return deleted


class AuthorityCriterionRepository(CRUDBase[AuthorityCriterionDb, Dict[str, Any], Dict[str, Any]]):
    def __init__(self):
        super().__init__(AuthorityCriterionDb)

    def list_for_relation(self, db: Session, *, relation_id: str) -> List[AuthorityCriterionDb]:
        stmt = (
            select(AuthorityCriterionDb)
            .where(AuthorityCriterionDb.relation_id == relation_id)
            .order_by(AuthorityCriterionDb.display_order.asc())
        )
        return list(db.execute(stmt).scalars().all())

    def delete_for_relation(self, db: Session, *, relation_id: str) -> int:
        return (
            db.query(AuthorityCriterionDb)
            .filter(AuthorityCriterionDb.relation_id == relation_id)
            .delete(synchronize_session=False)
        )


class AuthorityDnaRunRepository(CRUDBase[AuthorityDnaRunDb, Dict[str, Any], Dict[str, Any]]):
    def __init__(self):
        super().__init__(AuthorityDnaRunDb)

    def list_for_relation(self, db: Session, *, relation_id: str, limit: int = 50) -> List[AuthorityDnaRunDb]:
        stmt = (
            select(AuthorityDnaRunDb)
            .where(AuthorityDnaRunDb.relation_id == relation_id)
            .order_by(AuthorityDnaRunDb.started_at.desc())
            .limit(limit)
        )
        return list(db.execute(stmt).scalars().all())


class AuthorityDecisionRepository(CRUDBase[AuthorityDecisionDb, Dict[str, Any], Dict[str, Any]]):
    def __init__(self):
        super().__init__(AuthorityDecisionDb)

    def list_for_relation(
        self, db: Session, *, relation_id: str, source: Optional[str] = None, limit: int = 200
    ) -> List[AuthorityDecisionDb]:
        stmt = select(AuthorityDecisionDb).where(AuthorityDecisionDb.relation_id == relation_id)
        if source:
            stmt = stmt.where(AuthorityDecisionDb.source == source)
        stmt = stmt.order_by(AuthorityDecisionDb.created_at.desc()).limit(limit)
        return list(db.execute(stmt).scalars().all())


authority_relation_repo = AuthorityRelationRepository()
authority_affirmation_repo = AuthorityAffirmationRepository()
authority_criterion_repo = AuthorityCriterionRepository()
authority_dna_run_repo = AuthorityDnaRunRepository()
authority_decision_repo = AuthorityDecisionRepository()
