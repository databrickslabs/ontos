"""Unit tests for inbound domain import from UC governed tags (nebw #3)."""
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import Session

from src.controller.data_domains_manager import DataDomainManager
from src.repositories.data_domain_repository import DataDomainRepository
from src.controller.domain_uc_sync_manager import DomainUcSyncManager
from src.db_models.data_domains import DataDomain


def _domains_manager():
    return DataDomainManager(repository=DataDomainRepository())


@pytest.fixture(autouse=True)
def _isolate_domains(db_session: Session):
    """Purge domains after each test (create_domain_internal may commit)."""
    yield
    try:
        db_session.rollback()
        db_session.query(DataDomain).delete(synchronize_session=False)
        db_session.commit()
    except Exception:
        db_session.rollback()


class _FakeReviews:
    def __init__(self):
        self.created = []

    def create_review_request(self, request, db=None):
        import uuid as _uuid
        rid = str(_uuid.uuid4())
        self.created.append((rid, request.title, request.notes))
        return SimpleNamespace(id=rid)


class TestComputeProposals:
    def test_new_top_level_and_subdomain(self, db_session):
        mgr = DomainUcSyncManager(_domains_manager())
        proposals = mgr.compute_proposals(db_session, ["Finance", "Finance/Payments"])
        by_name = {p.name: p for p in proposals}
        assert by_name["Finance"].action == "create"
        assert by_name["Payments"].parent_name == "Finance"
        # Parent ordered before subdomain.
        names = [p.name for p in proposals]
        assert names.index("Finance") < names.index("Payments")

    def test_auto_inserts_missing_parent(self, db_session):
        mgr = DomainUcSyncManager(_domains_manager())
        # Only the subdomain path is tagged; parent must be synthesized.
        proposals = mgr.compute_proposals(db_session, ["Finance/Payments"])
        names = [p.name for p in proposals]
        assert "Finance" in names
        assert names.index("Finance") < names.index("Payments")

    def test_existing_domain_marked_exists(self, db_session):
        dm = _domains_manager()
        from src.models.data_domains import DataDomainCreate
        dm.create_domain_internal(db_session, DataDomainCreate(name="Finance"), current_user_id="t", perform_commit=False)
        db_session.flush()
        mgr = DomainUcSyncManager(dm)
        proposals = mgr.compute_proposals(db_session, ["Finance"])
        assert proposals[0].action == "exists"

    def test_dedupes_repeated_values(self, db_session):
        mgr = DomainUcSyncManager(_domains_manager())
        proposals = mgr.compute_proposals(db_session, ["Sales", "Sales", "Sales"])
        assert len([p for p in proposals if p.name == "Sales"]) == 1


class TestReviewGating:
    def test_creates_review_for_new_domains(self, db_session):
        reviews = _FakeReviews()
        mgr = DomainUcSyncManager(_domains_manager(), asset_reviews_manager=reviews)
        rid = mgr.create_import_review(
            db_session, ["Finance", "Finance/Payments"],
            reviewer_email="steward@example.com", requester_email="sys@example.com",
        )
        assert rid is not None
        assert len(reviews.created) == 1

    def test_no_review_when_nothing_new(self, db_session):
        dm = _domains_manager()
        from src.models.data_domains import DataDomainCreate
        dm.create_domain_internal(db_session, DataDomainCreate(name="Finance"), current_user_id="t", perform_commit=False)
        db_session.flush()
        reviews = _FakeReviews()
        mgr = DomainUcSyncManager(dm, asset_reviews_manager=reviews)
        rid = mgr.create_import_review(
            db_session, ["Finance"],
            reviewer_email="s@example.com", requester_email="sys@example.com",
        )
        assert rid is None
        assert reviews.created == []


class TestApplyImport:
    def test_apply_creates_parent_then_subdomain(self, db_session):
        dm = _domains_manager()
        mgr = DomainUcSyncManager(dm)
        result = mgr.apply_import(db_session, ["Finance/Payments"], current_user="tester")
        assert set(result["created"]) == {"Finance", "Payments"}
        db_session.flush()
        payments = dm.repository.get_by_name(db_session, name="Payments")
        finance = dm.repository.get_by_name(db_session, name="Finance")
        assert payments is not None and finance is not None
        assert payments.parent_id == finance.id

    def test_apply_is_idempotent(self, db_session):
        dm = _domains_manager()
        mgr = DomainUcSyncManager(dm)
        mgr.apply_import(db_session, ["Sales"], current_user="tester")
        db_session.flush()
        result = mgr.apply_import(db_session, ["Sales"], current_user="tester")
        assert result["created"] == []
        assert "Sales" in result["skipped"]
