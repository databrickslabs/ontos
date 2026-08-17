"""ACCEPTANCE gate for the P2 concept review PING-PONG loop.

The loop, wired to the DataAssetReview system (reused as the review backing
store) via the SemanticModelsManager <-> DataAssetReviewManager callback:

    DRAFT --submit--> UNDER_REVIEW
      APPROVED         -> approved
      CHANGES REQUESTED-> draft (carry reviewer comment) -> edit -> resubmit ...
      DENIED           -> draft (terminal reject, no delete)
    UNDER_REVIEW --owner withdraw--> DRAFT (review CANCELLED)

Ungoverned submit (no workflow scoped to the scheme) is zero-friction: it still
flips the concept to under_review, just without an approval gate.

Both managers are registered on app.state + the app_state registry so the
cross-manager reflection callback resolves.
"""
import uuid
from pathlib import Path
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from src.app import app
from src.controller.semantic_models_manager import SemanticModelsManager
from src.controller.data_asset_reviews_manager import DataAssetReviewManager
from src.common.app_state import set_app_state_manager
from src.models.data_asset_reviews import (
    DataAssetReviewRequestUpdateStatus,
    ReviewRequestStatus,
)


class _NoopNotifications:
    def create_notification(self, *a, **k):
        return None


@pytest.fixture
def managers(db_session: Session, tmp_path: Path, mock_workspace_client):
    data_dir = tmp_path / "sm_data"
    (data_dir / "cache").mkdir(parents=True, exist_ok=True)
    (data_dir / "taxonomies").mkdir(parents=True, exist_ok=True)

    smm = SemanticModelsManager(db=db_session, data_dir=data_dir)
    dar = DataAssetReviewManager(
        db=db_session,
        ws_client=mock_workspace_client,
        notifications_manager=_NoopNotifications(),
    )

    app.state.semantic_models_manager = smm
    app.state.data_asset_review_manager = dar
    set_app_state_manager("semantic_models_manager", smm)
    set_app_state_manager("data_asset_review_manager", dar)

    class _Noop:
        def sync_asset_types(self, *a, **k):
            return {"created": 0, "updated": 0}

        def log_action(self, *a, **k):
            return None

        def log_event(self, *a, **k):
            return None

    app.state.ontology_schema_manager = _Noop()
    app.state.audit_manager = _Noop()

    yield smm, dar

    for attr in (
        "semantic_models_manager", "data_asset_review_manager",
        "ontology_schema_manager", "audit_manager",
    ):
        if hasattr(app.state, attr):
            delattr(app.state, attr)


@pytest.fixture
def make_collection(client: TestClient, managers):
    def _make(prefix="Pong"):
        r = client.post("/api/knowledge/collections", json={
            "label": f"{prefix} {uuid.uuid4().hex[:8]}", "collection_type": "glossary",
            "scope_level": "enterprise", "description": "ping-pong review test",
        })
        assert r.status_code == 200, r.text
        return r.json()

    return _make


def _make_concept(client, coll_iri, label, definition):
    r = client.post("/api/knowledge/concepts", json={
        "collection_iri": coll_iri, "label": label, "definition": definition,
    })
    assert r.status_code == 200, r.text
    b = r.json()
    return b.get("iri") or (b.get("concept") or {}).get("iri")


# ---------------------------------------------------------------------------
# 1. UNGOVERNED submit — no workflow installed
# ---------------------------------------------------------------------------
def test_ungoverned_submit_flips_to_under_review(client, make_collection, managers):
    smm, _ = managers
    coll = make_collection()
    iri = _make_concept(client, coll["iri"], "Customer", "v1 def")

    result = smm.submit_concept_for_review(
        concept_iri=iri, reviewer_email="rev@example.com", submitted_by="own@example.com",
    )
    assert result["governed"] is False
    assert smm.get_concept(iri)["status"] == "under_review"
    assert result["review_request_id"] is not None  # review still opened


# ---------------------------------------------------------------------------
# 2. PING-PONG: changes requested -> draft w/ comment -> edit -> resubmit
# ---------------------------------------------------------------------------
def test_pingpong_changes_requested_then_resubmit(client, make_collection, managers):
    smm, dar = managers
    coll = make_collection()
    iri = _make_concept(client, coll["iri"], "Revenue", "money in")
    q = quote(iri, safe="")

    r1 = smm.submit_concept_for_review(
        concept_iri=iri, reviewer_email="rev@example.com", submitted_by="own@example.com",
    )
    assert smm.get_concept(iri)["status"] == "under_review"
    review_id = r1["review_request_id"]
    assert review_id is not None

    # Reviewer requests changes with a comment -> concept returns to draft.
    dar.update_review_request_status(
        review_id,
        DataAssetReviewRequestUpdateStatus(
            status=ReviewRequestStatus.NEEDS_REVIEW,
            notes="Please tighten the definition.",
        ),
    )
    concept = smm.get_concept(iri)
    assert concept["status"] == "draft"
    # Reviewer comment is retrievable on the concept.
    from rdflib import URIRef
    from src.controller.semantic_models_manager import ONTOS
    comments = [
        str(o) for o in smm._graph.objects(URIRef(iri), ONTOS.reviewComment)
    ]
    assert comments == ["Please tighten the definition."], comments

    # Owner edits the definition (allowed now that it is draft) and resubmits.
    edit = client.patch(
        f"/api/knowledge/concepts/by-iri?iri={q}", json={"definition": "money received"}
    )
    assert edit.status_code == 200, edit.text

    r2 = smm.submit_concept_for_review(
        concept_iri=iri, reviewer_email="rev@example.com", submitted_by="own@example.com",
    )
    assert smm.get_concept(iri)["status"] == "under_review"
    # reset_all default: a fresh review is opened on resubmit.
    assert r2["review_request_id"] is not None
    assert r2["review_request_id"] != review_id


# ---------------------------------------------------------------------------
# 3. APPROVE: under_review -> approved
# ---------------------------------------------------------------------------
def test_approve_transitions_to_approved(client, make_collection, managers):
    smm, dar = managers
    coll = make_collection()
    iri = _make_concept(client, coll["iri"], "Product", "a thing")

    r = smm.submit_concept_for_review(
        concept_iri=iri, reviewer_email="rev@example.com", submitted_by="own@example.com",
    )
    assert smm.get_concept(iri)["status"] == "under_review"

    dar.update_review_request_status(
        r["review_request_id"],
        DataAssetReviewRequestUpdateStatus(status=ReviewRequestStatus.APPROVED),
    )
    assert smm.get_concept(iri)["status"] == "approved"


# ---------------------------------------------------------------------------
# 4. WITHDRAW: under_review -> draft, review CANCELLED
# ---------------------------------------------------------------------------
def test_withdraw_returns_to_draft_and_cancels_review(client, make_collection, managers):
    smm, dar = managers
    coll = make_collection()
    iri = _make_concept(client, coll["iri"], "Order", "a purchase")

    r = smm.submit_concept_for_review(
        concept_iri=iri, reviewer_email="rev@example.com", submitted_by="own@example.com",
    )
    review_id = r["review_request_id"]
    assert smm.get_concept(iri)["status"] == "under_review"

    smm.withdraw_concept_review(concept_iri=iri, withdrawn_by="own@example.com")
    assert smm.get_concept(iri)["status"] == "draft"

    review = dar.get_review_request(review_id)
    assert review.status == ReviewRequestStatus.CANCELLED
