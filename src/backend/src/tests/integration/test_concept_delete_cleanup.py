"""Deleting a concept or a collection removes their notes, links, documents and cost items (#1431)."""
import uuid
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from src.app import app
from src.common.app_state import set_app_state_manager
from src.controller.semantic_models_manager import SemanticModelsManager
from src.db_models.costs import CostItemDb
from src.db_models.metadata import LinkMetadataDb, RichTextMetadataDb


@pytest.fixture
def semantic_models_manager(db_session: Session, tmp_path: Path, monkeypatch):
    data_dir = tmp_path / "sm_data"
    (data_dir / "cache").mkdir(parents=True, exist_ok=True)
    (data_dir / "taxonomies").mkdir(parents=True, exist_ok=True)
    manager = SemanticModelsManager(db=db_session, data_dir=data_dir)
    app.state.semantic_models_manager = manager
    set_app_state_manager("semantic_models_manager", manager)

    class _Noop:
        def sync_asset_types(self, *a, **k):
            return {"created": 0, "updated": 0}

        def log_action(self, *a, **k):
            return None

        def log_event(self, *a, **k):
            return None

    app.state.ontology_schema_manager = _Noop()
    app.state.audit_manager = _Noop()
    from src.controller import metadata_manager as mm
    monkeypatch.setattr(mm.MetadataManager, "delete_document_files_after_commit",
                        lambda self, db, paths, ws=None: None)
    yield manager
    for attr in ("semantic_models_manager", "ontology_schema_manager", "audit_manager"):
        if hasattr(app.state, attr):
            delattr(app.state, attr)


def _collection(client: TestClient) -> str:
    r = client.post("/api/knowledge/collections", json={
        "label": f"Cleanup {uuid.uuid4().hex[:8]}", "collection_type": "glossary",
        "scope_level": "enterprise", "description": "delete cleanup test",
    })
    assert r.status_code == 200, r.text
    return r.json()["iri"]


def _concept(client: TestClient, coll_iri: str, label: str) -> str:
    r = client.post("/api/knowledge/concepts", json={
        "collection_iri": coll_iri, "label": label, "definition": "d",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    return body.get("iri") or (body.get("concept") or {}).get("iri")


def _seed(db: Session, entity_type: str, entity_id: str) -> None:
    db.add(RichTextMetadataDb(entity_type=entity_type, entity_id=entity_id, title="n", content_markdown="c"))
    db.add(LinkMetadataDb(entity_type=entity_type, entity_id=entity_id, title="l", url="https://example.com"))
    db.add(CostItemDb(entity_type=entity_type, entity_id=entity_id, cost_center="STORAGE",
                      amount_cents=1, currency="USD", start_month=date(2026, 10, 1)))
    db.commit()


def _count(db: Session, entity_type: str, entity_id: str) -> int:
    return sum(
        db.query(m).filter(m.entity_type == entity_type, m.entity_id == entity_id).count()
        for m in (RichTextMetadataDb, LinkMetadataDb, CostItemDb)
    )


def test_delete_concept_removes_its_metadata(client, semantic_models_manager, db_session):
    coll = _collection(client)
    keep = _concept(client, coll, "Keep")
    gone = _concept(client, coll, "Gone")
    _seed(db_session, "concept", gone)
    _seed(db_session, "concept", keep)

    assert semantic_models_manager.delete_concept(gone, deleted_by="tester") is True

    assert _count(db_session, "concept", gone) == 0
    assert _count(db_session, "concept", keep) == 3


def test_delete_collection_removes_its_and_its_concepts_metadata(client, semantic_models_manager, db_session):
    coll = _collection(client)
    concept = _concept(client, coll, "Member")
    other_coll = _collection(client)
    other = _concept(client, other_coll, "Elsewhere")
    _seed(db_session, "collection", coll)
    _seed(db_session, "concept", concept)
    _seed(db_session, "concept", other)

    assert semantic_models_manager.delete_collection(coll, deleted_by="tester") is True

    assert _count(db_session, "collection", coll) == 0
    assert _count(db_session, "concept", concept) == 0
    assert _count(db_session, "concept", other) == 3
