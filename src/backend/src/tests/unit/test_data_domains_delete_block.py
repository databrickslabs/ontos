"""Unit tests for the multi-domain (#520) domain-deletion guard.

A domain that is the PRIMARY domain for any entity (or for a descendant that would be
cascade-deleted with it) cannot be deleted — the primary feeds single-value integrations.
Domains that are only ever *additional* can be deleted, and their association rows are
cleaned up (the junction FK has no ON DELETE CASCADE).
"""
import pytest
from sqlalchemy.orm import Session

from src.common.errors import ConflictError, NotFoundError
from src.controller.data_domains_manager import DataDomainManager
from src.models.data_domains import DataDomainCreate
from src.repositories.data_domain_repository import data_domain_repo
from src.repositories.entity_domain_association_repository import entity_domain_repo


@pytest.fixture
def manager():
    return DataDomainManager(repository=data_domain_repo)


def _make_domain(db: Session, name: str, parent_id=None) -> str:
    d = data_domain_repo.create(db=db, obj_in=DataDomainCreate(name=name, parent_id=parent_id))
    db.commit()
    return d.id


def _assign(db: Session, entity_type: str, entity_id: str, domain_ids, primary=None):
    entity_domain_repo.set_domains_for_entity(
        db, entity_type=entity_type, entity_id=entity_id,
        domain_ids=domain_ids, primary_domain_id=primary, assigned_by="tester",
    )
    db.commit()


class TestDeletionImpact:
    def test_deletable_when_no_assignments(self, db_session, manager):
        did = _make_domain(db_session, "Sales")
        impact = manager.get_domain_deletion_impact(db_session, did)
        assert impact["deletable"] is True
        assert impact["primary_assignments"] == []

    def test_deletable_when_only_additional(self, db_session, manager):
        primary = _make_domain(db_session, "Sales")
        extra = _make_domain(db_session, "Marketing")
        # 'extra' is only an ADDITIONAL domain for the product.
        _assign(db_session, "data_product", "p1", [primary, extra], primary=primary)
        impact = manager.get_domain_deletion_impact(db_session, extra)
        assert impact["deletable"] is True
        assert impact["assignment_counts"]["data_product"]["additional"] == 1
        assert impact["assignment_counts"]["data_product"]["primary"] == 0

    def test_not_deletable_when_primary(self, db_session, manager):
        primary = _make_domain(db_session, "Sales")
        _assign(db_session, "data_product", "p1", [primary], primary=primary)
        impact = manager.get_domain_deletion_impact(db_session, primary)
        assert impact["deletable"] is False
        assert impact["primary_assignments"] == [{"entity_type": "data_product", "entity_id": "p1"}]

    def test_missing_domain_raises(self, db_session, manager):
        with pytest.raises(NotFoundError):
            manager.get_domain_deletion_impact(db_session, "does-not-exist")


class TestDeleteBlock:
    def test_delete_blocked_when_primary(self, db_session, manager):
        did = _make_domain(db_session, "Sales")
        _assign(db_session, "data_contract", "c1", [did], primary=did)
        with pytest.raises(ConflictError) as exc:
            manager.delete_domain(db_session, did, current_user_id="tester")
        detail = exc.value.detail
        assert isinstance(detail, dict)
        assert detail["code"] == "domain_primary_in_use"
        assert {"entity_type": "data_contract", "entity_id": "c1"} in detail["primary_assignments"]
        # The domain must still exist (nothing mutated).
        assert data_domain_repo.get(db_session, did) is not None

    def test_delete_succeeds_and_cleans_additional_rows(self, db_session, manager):
        primary = _make_domain(db_session, "Sales")
        extra = _make_domain(db_session, "Marketing")
        _assign(db_session, "data_product", "p1", [primary, extra], primary=primary)

        result = manager.delete_domain(db_session, extra, current_user_id="tester")
        db_session.commit()
        assert result is not None
        # The domain is gone and its (additional) association row was removed.
        assert data_domain_repo.get(db_session, extra) is None
        remaining = entity_domain_repo.get_domains_for_entity(
            db_session, entity_type="data_product", entity_id="p1"
        )
        assert [d.domain_id for d in remaining] == [primary]

    def test_delete_blocked_when_descendant_is_primary(self, db_session, manager):
        parent = _make_domain(db_session, "Commerce")
        child = _make_domain(db_session, "Sales", parent_id=parent)
        # The child (which cascade-deletes with the parent) is primary for a team.
        _assign(db_session, "team", "t1", [child], primary=child)
        with pytest.raises(ConflictError) as exc:
            manager.delete_domain(db_session, parent, current_user_id="tester")
        assert exc.value.detail["code"] == "domain_primary_in_use"
        assert {"entity_type": "team", "entity_id": "t1"} in exc.value.detail["primary_assignments"]
