"""Repositories for Access Policies (CRUDBase-backed)."""
from typing import Any, Dict, Iterable, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.common.repository import CRUDBase
from src.db_models.access_policies import (
    AccessAssetCollectionDb,
    AccessAudienceDb,
    AccessPolicyDb,
    AccessPolicyIndexDb,
)


class GovernedEntityRepository(CRUDBase[Any, Dict[str, Any], Dict[str, Any]]):
    """Shared queries for the version-family governed entities."""

    def list_all(self, db: Session) -> List[Any]:
        stmt = select(self.model).order_by(self.model.updated_at.desc())
        return list(db.execute(stmt).scalars().all())

    def list_by_ids(self, db: Session, ids: Iterable[str]) -> List[Any]:
        ids = list(ids)
        if not ids:
            return []
        stmt = select(self.model).where(self.model.id.in_(ids)).order_by(self.model.updated_at.desc())
        return list(db.execute(stmt).scalars().all())

    def get_family_versions(self, db: Session, *, family_id: str) -> List[Any]:
        """Every version in a family, newest first."""
        stmt = (
            select(self.model)
            .where(self.model.version_family_id == family_id)
            .order_by(self.model.created_at.desc())
        )
        return list(db.execute(stmt).scalars().all())

    def get_family_by_uid(self, db: Session, uid: str) -> List[Any]:
        stmt = select(self.model).where(self.model.uid == uid).order_by(self.model.created_at.desc())
        return list(db.execute(stmt).scalars().all())

    def get_active_by_uid(self, db: Session, uid: str) -> Optional[Any]:
        stmt = select(self.model).where(self.model.uid == uid, self.model.status == "active")
        return db.execute(stmt).scalars().first()


class AccessPolicyIndexRepository(CRUDBase[AccessPolicyIndexDb, Dict[str, Any], Dict[str, Any]]):
    def __init__(self):
        super().__init__(AccessPolicyIndexDb)

    def replace_for_policy(self, db: Session, policy_id: str, terms: Iterable[Tuple[str, str, str]]) -> None:
        db.query(AccessPolicyIndexDb).filter(AccessPolicyIndexDb.policy_id == policy_id).delete(
            synchronize_session=False)
        for kind, role, value in terms:
            db.add(AccessPolicyIndexDb(policy_id=policy_id, rule_kind=kind, role=role, value=value))
        db.flush()

    def policy_ids_for_value(self, db: Session, value: str) -> List[str]:
        stmt = select(AccessPolicyIndexDb.policy_id).where(AccessPolicyIndexDb.value == value).distinct()
        return [r[0] for r in db.execute(stmt).all()]


access_policy_repo = GovernedEntityRepository(AccessPolicyDb)
access_audience_repo = GovernedEntityRepository(AccessAudienceDb)
access_asset_collection_repo = GovernedEntityRepository(AccessAssetCollectionDb)
access_policy_index_repo = AccessPolicyIndexRepository()

_BY_KIND = {
    "policy": access_policy_repo,
    "audience": access_audience_repo,
    "asset_collection": access_asset_collection_repo,
}


def repo_for(kind: str) -> GovernedEntityRepository:
    return _BY_KIND[kind]
