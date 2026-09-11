"""ACCEPTANCE gate: prevent non-admins from bypassing concept review approval
when a governing workflow exists.

The direct status routes (``/knowledge/concepts/by-iri/approve`` and
``.../publish``) let any ``semantic-models:READ_WRITE`` user flip a concept's
status. When a concept is ``under_review`` AND a governing ProcessWorkflow
exists (trigger ``ON_REQUEST_STATUS_CHANGE`` for ``ONTOLOGY_CONCEPT``), a
NON-admin must instead go through the review decision. An Ontos admin may
override. Ungoverned concepts stay zero-friction.

Cases:
  (a) non-admin + governed + under_review->approved  => 403
  (b) admin     + governed                            => allowed (not 403)
  (c) non-admin + ungoverned                          => allowed (not 403)

We monkeypatch the NON-firing existence check
(``WorkflowsManager.get_workflows_for_trigger``) and the admin check
(``AuthorizationManager.is_user_ontos_admin``) rather than seeding real
workflows/roles, mirroring the isolation style of the sibling review tests.
"""
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from src.app import app
from src.controller.semantic_models_manager import SemanticModelsManager
from src.common.app_state import set_app_state_manager
import src.routes.semantic_models_routes as sm_routes


@pytest.fixture
def smm(db_session: Session, tmp_path: Path, mock_workspace_client):
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

    yield manager

    for attr in ("semantic_models_manager", "ontology_schema_manager", "audit_manager"):
        if hasattr(app.state, attr):
            delattr(app.state, attr)


def _make_collection(client: TestClient):
    r = client.post("/api/knowledge/collections", json={
        "label": f"Gate {uuid.uuid4().hex[:8]}", "collection_type": "glossary",
        "scope_level": "enterprise", "description": "bypass gate test",
    })
    assert r.status_code == 200, r.text
    return r.json()


def _make_under_review_concept(client, smm, label):
    coll = _make_collection(client)
    r = client.post("/api/knowledge/concepts", json={
        "collection_iri": coll["iri"], "label": label, "definition": "def",
    })
    assert r.status_code == 200, r.text
    b = r.json()
    iri = b.get("iri") or (b.get("concept") or {}).get("iri")
    # Move to under_review directly (ungoverned submit still flips status).
    smm.update_concept_status(concept_iri=iri, new_status="under_review", updated_by="own@example.com")
    assert smm.get_concept(iri)["status"] == "under_review"
    return iri


def _set_governed(monkeypatch, governed: bool):
    monkeypatch.setattr(
        sm_routes.WorkflowsManager,
        "get_workflows_for_trigger",
        lambda self, *a, **k: (["a-governing-workflow"] if governed else []),
    )


def _set_admin(monkeypatch, is_admin: bool):
    monkeypatch.setattr(
        sm_routes.AuthorizationManager,
        "is_user_ontos_admin",
        lambda self, groups: is_admin,
    )


# ---------------------------------------------------------------------------
# (a) non-admin + governed + under_review -> approved => 403
# ---------------------------------------------------------------------------
def test_non_admin_governed_approve_blocked(client, smm, monkeypatch):
    iri = _make_under_review_concept(client, smm, "Customer")
    _set_governed(monkeypatch, True)
    _set_admin(monkeypatch, False)

    r = client.post("/api/knowledge/concepts/by-iri/approve", params={"iri": iri})
    assert r.status_code == 403, r.text
    assert "approval workflow" in r.json()["detail"]
    # Concept stays under_review — the flip was blocked.
    assert smm.get_concept(iri)["status"] == "under_review"


# ---------------------------------------------------------------------------
# (b) admin + governed => allowed (override)
# ---------------------------------------------------------------------------
def test_admin_governed_approve_allowed(client, smm, monkeypatch):
    iri = _make_under_review_concept(client, smm, "Revenue")
    _set_governed(monkeypatch, True)
    _set_admin(monkeypatch, True)

    r = client.post("/api/knowledge/concepts/by-iri/approve", params={"iri": iri})
    assert r.status_code == 200, r.text
    assert smm.get_concept(iri)["status"] == "approved"


# ---------------------------------------------------------------------------
# (c) non-admin + ungoverned => allowed (zero-friction)
# ---------------------------------------------------------------------------
def test_non_admin_ungoverned_approve_allowed(client, smm, monkeypatch):
    iri = _make_under_review_concept(client, smm, "Product")
    _set_governed(monkeypatch, False)
    _set_admin(monkeypatch, False)

    r = client.post("/api/knowledge/concepts/by-iri/approve", params={"iri": iri})
    assert r.status_code == 200, r.text
    assert smm.get_concept(iri)["status"] == "approved"
