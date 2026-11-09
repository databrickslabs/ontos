"""Reviewer decisions on a concept are mirrored into its comment timeline.

When a reviewer approves / requests changes / denies a concept, an entity
comment (the same comments store the data-product CommentSidebar reads) is
written keyed ``entity_type='ontology_concept'``, ``entity_id=<concept IRI>``,
authored by the reviewer: ``"Approved: <comment>"`` / ``"Changes requested:
<comment>"`` / ``"Rejected: <comment>"``, or the bare decision without a
comment. A comment-write failure must not fail the decision.
"""
import uuid
from pathlib import Path
from unittest.mock import patch
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from src.app import app
from src.common.app_state import set_app_state_manager
from src.controller.semantic_models_manager import SemanticModelsManager
from src.db_models.comments import CommentDb

ENTITY_TYPE = "ontology_concept"


@pytest.fixture
def smm(db_session: Session, tmp_path: Path, mock_workspace_client):
    data_dir = tmp_path / "sm_data"
    (data_dir / "cache").mkdir(parents=True, exist_ok=True)
    (data_dir / "taxonomies").mkdir(parents=True, exist_ok=True)
    manager = SemanticModelsManager(db=db_session, data_dir=data_dir)
    app.state.semantic_models_manager = manager
    set_app_state_manager("semantic_models_manager", manager)
    yield manager
    if hasattr(app.state, "semantic_models_manager"):
        delattr(app.state, "semantic_models_manager")


def _make_under_review_concept(client: TestClient, smm, label: str) -> str:
    coll = client.post("/api/knowledge/collections", json={
        "label": f"RDC {uuid.uuid4().hex[:8]}", "collection_type": "glossary",
        "scope_level": "enterprise", "description": "review decision comments",
    })
    assert coll.status_code == 200, coll.text
    r = client.post("/api/knowledge/concepts", json={
        "collection_iri": coll.json()["iri"], "label": label, "definition": "a thing",
    })
    assert r.status_code == 200, r.text
    b = r.json()
    iri = b.get("iri") or (b.get("concept") or {}).get("iri")
    smm.update_concept_status(concept_iri=iri, new_status="under_review", updated_by="own@x.com")
    assert smm.get_concept(iri)["status"] == "under_review"
    return iri


def _comments(db: Session, iri: str):
    return (
        db.query(CommentDb)
        .filter(CommentDb.entity_type == ENTITY_TYPE, CommentDb.entity_id == iri)
        .all()
    )


def test_review_request_changes_route_with_comment_creates_comment(client, smm, db_session):
    iri = _make_under_review_concept(client, smm, "Customer")
    r = client.post(
        f"/api/knowledge/concepts/by-iri/request-changes?iri={quote(iri, safe='')}",
        json={"comments": "Include prospects."},
    )
    assert r.status_code == 200, r.text
    assert smm.get_concept(iri)["status"] == "draft"

    rows = _comments(db_session, iri)
    assert len(rows) == 1
    assert rows[0].comment == "Changes requested: Include prospects."
    assert rows[0].created_by  # authored by the reviewer (current user)
    assert rows[0].project_id is None


def test_review_approve_route_with_comment_creates_comment(client, smm, db_session):
    iri = _make_under_review_concept(client, smm, "Order")
    r = client.post(
        f"/api/knowledge/concepts/by-iri/approve?iri={quote(iri, safe='')}",
        json={"comments": "Looks good."},
    )
    assert r.status_code == 200, r.text
    assert smm.get_concept(iri)["status"] == "approved"
    rows = _comments(db_session, iri)
    assert [c.comment for c in rows] == ["Approved: Looks good."]


def test_review_approve_route_without_body_records_bare_decision(client, smm, db_session):
    iri = _make_under_review_concept(client, smm, "Invoice")
    r = client.post(f"/api/knowledge/concepts/by-iri/approve?iri={quote(iri, safe='')}")
    assert r.status_code == 200, r.text
    assert [c.comment for c in _comments(db_session, iri)] == ["Approved"]


def test_review_decision_manager_paths_author_and_text(client, smm, db_session):
    # approved via the reviewer-callback path (DataAssetReview / workflow)
    a = _make_under_review_concept(client, smm, "Supplier")
    smm.apply_review_decision(
        concept_iri=a, decision="approved", decided_by="rev@example.com", comments=None,
    )
    rows = _comments(db_session, a)
    assert [(c.comment, c.created_by) for c in rows] == [("Approved", "rev@example.com")]

    # denied with a comment
    d = _make_under_review_concept(client, smm, "Vendor")
    smm.apply_review_decision(
        concept_iri=d, decision="denied", decided_by="rev@example.com", comments="Duplicate of Supplier.",
    )
    assert [c.comment for c in _comments(db_session, d)] == ["Rejected: Duplicate of Supplier."]

    # Idempotent repeat send-back without a comment does not double-post.
    smm.apply_review_decision(
        concept_iri=d, decision="denied", decided_by="rev@example.com", comments=None,
    )
    assert len(_comments(db_session, d)) == 1


def test_review_decision_comment_failure_does_not_fail_decision(client, smm, db_session):
    iri = _make_under_review_concept(client, smm, "Margin")
    with patch(
        "src.controller.comments_manager.CommentsManager.create_comment",
        side_effect=RuntimeError("boom"),
    ):
        result = smm.apply_review_decision(
            concept_iri=iri, decision="changes_requested",
            decided_by="rev@example.com", comments="Add a unit.",
        )
    assert result["concept"]["status"] == "draft"
    assert smm.get_concept(iri)["review_comment"] == "Add a unit."
    assert _comments(db_session, iri) == []
