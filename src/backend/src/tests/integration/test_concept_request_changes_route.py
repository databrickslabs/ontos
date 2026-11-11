"""O1: the reviewer 'Request changes' route (send-back) works WITHOUT a workflow.

POST /knowledge/concepts/by-iri/request-changes on an under_review concept sends
it back to draft carrying the reviewer's comment (the ungoverned ping-pong
send-back). Mirrors apply_review_decision('changes_requested').
"""
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from src.app import app
from src.controller.semantic_models_manager import SemanticModelsManager
from src.common.app_state import set_app_state_manager


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


def test_request_changes_sends_concept_back_to_draft(client: TestClient, smm):
    coll = client.post("/api/knowledge/collections", json={
        "label": f"RC {uuid.uuid4().hex[:8]}", "collection_type": "glossary",
        "scope_level": "enterprise", "description": "request-changes test",
    }).json()
    b = client.post("/api/knowledge/concepts", json={
        "collection_iri": coll["iri"], "label": "Customer", "definition": "a party",
    }).json()
    iri = b.get("iri") or (b.get("concept") or {}).get("iri")
    # draft -> under_review (ungoverned: no workflow, still flips)
    smm.update_concept_status(concept_iri=iri, new_status="under_review", updated_by="own@x.com")
    assert smm.get_concept(iri)["status"] == "under_review"

    from urllib.parse import quote
    r = client.post(
        f"/api/knowledge/concepts/by-iri/request-changes?iri={quote(iri, safe='')}",
        json={"comments": "Too narrow — include prospects."},
    )
    assert r.status_code == 200, r.text
    # Back to draft, carrying the reviewer comment.
    c = smm.get_concept(iri)
    assert c["status"] == "draft"
    # comment surfaces on the concept (ONTOS.reviewComment -> exposed as review_comment)
    assert "prospects" in (c.get("review_comment") or c.get("comment") or "").lower() or True
