"""Repository for Authority Policies (CRUDBase-backed)."""
from typing import Any, Dict, List

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.common.repository import CRUDBase
from src.db_models.authority_policy import AuthorityPolicyDb
from src.db_models.authority_resolution import AuthorityRelationDb


class AuthorityPolicyRepository(CRUDBase[AuthorityPolicyDb, Dict[str, Any], Dict[str, Any]]):
    def __init__(self):
        super().__init__(AuthorityPolicyDb)

    def list_all(self, db: Session) -> List[AuthorityPolicyDb]:
        stmt = select(AuthorityPolicyDb).order_by(AuthorityPolicyDb.updated_at.desc())
        return list(db.execute(stmt).scalars().all())

    def get_family_versions(self, db: Session, *, family_id: str) -> List[AuthorityPolicyDb]:
        """Every version in a family, newest first."""
        stmt = (
            select(AuthorityPolicyDb)
            .where(AuthorityPolicyDb.version_family_id == family_id)
            .order_by(AuthorityPolicyDb.created_at.desc())
        )
        return list(db.execute(stmt).scalars().all())

    def list_children(self, db: Session, *, policy_id: str) -> List[AuthorityPolicyDb]:
        stmt = select(AuthorityPolicyDb).where(AuthorityPolicyDb.parent_policy_id == policy_id)
        return list(db.execute(stmt).scalars().all())

    def list_citing_relations(self, db: Session, *, policy_ids: List[str]) -> List[AuthorityRelationDb]:
        """Authority Relations (any version) that cite one of these policy versions."""
        if not policy_ids:
            return []
        stmt = (
            select(AuthorityRelationDb)
            .where(AuthorityRelationDb.authority_policy_id.in_(policy_ids))
            .order_by(AuthorityRelationDb.updated_at.desc())
        )
        return list(db.execute(stmt).scalars().all())


authority_policy_repo = AuthorityPolicyRepository()
