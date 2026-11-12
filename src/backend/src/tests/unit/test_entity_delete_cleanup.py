"""Deleting an entity removes what is stored for it in the polymorphic tables (#1431).

Notes, links, documents, attachments and cost items are keyed by
``(entity_type, entity_id)``. Only the asset delete removed them; every other
kind left them behind, so an entity created later with the same id (an
imported product or contract keeping its id, a concept IRI) showed the old
metadata. Shared library records are not the deleted entity's and stay.
"""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import uuid
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from src.controller.compliance_manager import ComplianceManager
from src.controller.data_contracts_manager import DataContractsManager
from src.controller.data_domains_manager import DataDomainManager
from src.controller.data_products_manager import DataProductsManager
from src.controller.entity_data_cleanup import remove_entity_data
from src.controller.metadata_manager import SHARED_ENTITY_ID
from src.db_models.compliance import CompliancePolicyDb
from src.db_models.costs import CostItemDb
from src.db_models.data_contracts import DataContractDb
from src.db_models.data_products import DataProductDb
from src.db_models.metadata import (
    DocumentMetadataDb,
    LinkMetadataDb,
    MetadataAttachmentDb,
    RichTextMetadataDb,
)
from src.models.data_domains import DataDomainCreate
from src.repositories.data_domain_repository import data_domain_repo

KINDS = (RichTextMetadataDb, LinkMetadataDb, DocumentMetadataDb, MetadataAttachmentDb, CostItemDb)


def _seed(db: Session, entity_type: str, entity_id: str, shared_note_id: str) -> None:
    """One row of each kind for the entity, plus an attachment of a shared note."""
    db.add(RichTextMetadataDb(entity_type=entity_type, entity_id=entity_id, title="n", content_markdown="c"))
    db.add(LinkMetadataDb(entity_type=entity_type, entity_id=entity_id, title="l", url="https://example.com"))
    db.add(DocumentMetadataDb(
        entity_type=entity_type, entity_id=entity_id, title="d",
        original_filename="f.txt", storage_path=f"/Volumes/x/uploads/{entity_type}/{entity_id}/f.txt",
    ))
    db.add(MetadataAttachmentDb(
        entity_type=entity_type, entity_id=entity_id, asset_type="rich_text", asset_id=shared_note_id,
    ))
    db.add(CostItemDb(
        entity_type=entity_type, entity_id=entity_id, cost_center="STORAGE",
        amount_cents=100, currency="USD", start_month=date(2026, 10, 1),
    ))
    db.commit()


def _count(db: Session, entity_type: str, entity_id: str) -> int:
    return sum(
        db.query(model).filter(model.entity_type == entity_type, model.entity_id == entity_id).count()
        for model in KINDS
    )


@pytest.fixture
def shared_note(db_session):
    note = RichTextMetadataDb(
        entity_type="data_domain", entity_id=SHARED_ENTITY_ID, title="shared",
        content_markdown="c", is_shared=True,
    )
    db_session.add(note)
    db_session.commit()
    return note


@pytest.fixture
def no_file_deletes(monkeypatch):
    """Record the document paths queued for deletion instead of touching a volume."""
    queued = []
    from src.controller import metadata_manager as mm

    monkeypatch.setattr(
        mm.MetadataManager, "delete_document_files_after_commit",
        lambda self, db, paths, ws=None: queued.extend(paths),
    )
    return queued


def _assert_cleaned(db, entity_type, entity_id, shared_note, queued):
    assert _count(db, entity_type, entity_id) == 0
    assert db.get(RichTextMetadataDb, shared_note.id) is not None, "shared library note must stay"
    assert queued == [f"/Volumes/x/uploads/{entity_type}/{entity_id}/f.txt"]


class TestHelper:
    def test_removes_every_kind_and_reports_counts(self, db_session, shared_note, no_file_deletes):
        _seed(db_session, "data_product", "p1", str(shared_note.id))
        _seed(db_session, "data_product", "p2", str(shared_note.id))

        removed = remove_entity_data(db_session, entity_type="data_product", entity_id="p1")
        db_session.commit()

        assert removed == {
            "rich_texts": 1, "links": 1, "documents": 1, "attachments": 1, "cost_items": 1,
        }
        _assert_cleaned(db_session, "data_product", "p1", shared_note, no_file_deletes)
        assert _count(db_session, "data_product", "p2") == 5, "other entities keep theirs"


class TestDeletePaths:
    def test_product_delete(self, db_session, shared_note, no_file_deletes):
        pid = str(uuid.uuid4())
        db_session.add(DataProductDb(id=pid, status="draft", name="P"))
        db_session.commit()
        _seed(db_session, "data_product", pid, str(shared_note.id))

        assert DataProductsManager(db=db_session).delete_product(pid, user="u") is True

        _assert_cleaned(db_session, "data_product", pid, shared_note, no_file_deletes)

    def test_draft_discard(self, db_session, shared_note, no_file_deletes):
        pid = str(uuid.uuid4())
        db_session.add(DataProductDb(id=pid, status="draft", name="Draft", draft_owner_id="u"))
        db_session.commit()
        _seed(db_session, "data_product", pid, str(shared_note.id))

        assert DataProductsManager(db=db_session).discard_personal_draft(db_session, pid, "u") is True

        _assert_cleaned(db_session, "data_product", pid, shared_note, no_file_deletes)

    def test_contract_delete(self, db_session, shared_note, no_file_deletes):
        cid = str(uuid.uuid4())
        db_session.add(DataContractDb(id=cid, name="C", version="1.0.0", status="draft", created_by="u"))
        db_session.commit()
        _seed(db_session, "data_contract", cid, str(shared_note.id))

        DataContractsManager(data_dir=Path("/tmp")).delete_contract_from_db(db_session, cid, current_user="u")
        db_session.commit()

        _assert_cleaned(db_session, "data_contract", cid, shared_note, no_file_deletes)

    def test_domain_delete_cleans_cascaded_children(self, db_session, shared_note, no_file_deletes):
        parent = data_domain_repo.create(db=db_session, obj_in=DataDomainCreate(name="Parent"))
        db_session.commit()
        child = data_domain_repo.create(db=db_session, obj_in=DataDomainCreate(name="Child", parent_id=parent.id))
        db_session.commit()
        for did in (str(parent.id), str(child.id)):
            _seed(db_session, "data_domain", did, str(shared_note.id))

        DataDomainManager(repository=data_domain_repo).delete_domain(db_session, parent.id, "u")
        db_session.commit()

        for did in (str(parent.id), str(child.id)):
            assert _count(db_session, "data_domain", did) == 0
        assert db_session.get(RichTextMetadataDb, shared_note.id) is not None
        assert len(no_file_deletes) == 2

    def test_compliance_policy_delete(self, db_session, shared_note, no_file_deletes):
        pol = CompliancePolicyDb(id=str(uuid.uuid4()), name="Pol", rule="MATCH (o:Object) ASSERT true")
        db_session.add(pol)
        db_session.commit()
        _seed(db_session, "compliance_policy", pol.id, str(shared_note.id))

        assert ComplianceManager().delete_policy(db_session, pol.id, current_user="u") is True

        _assert_cleaned(db_session, "compliance_policy", pol.id, shared_note, no_file_deletes)

    def test_cleanup_does_not_commit(self, db_session, shared_note, no_file_deletes):
        """The rows go with the delete's transaction: rolled back, they are all still there."""
        _seed(db_session, "data_product", "p9", str(shared_note.id))

        savepoint = db_session.begin_nested()
        remove_entity_data(db_session, entity_type="data_product", entity_id="p9")
        assert _count(db_session, "data_product", "p9") == 0
        savepoint.rollback()

        assert _count(db_session, "data_product", "p9") == 5
