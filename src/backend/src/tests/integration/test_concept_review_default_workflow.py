"""The default "Concept Reviewer Approval (Default)" workflow governs concept submits.

Before it shipped, ``submit_concept_for_review`` fired
``on_request_status_change`` for ``ontology_concept`` but no default workflow
matched, so submits were ungoverned and the reviewer was never notified.

Covers:
  * default_workflows.yaml seeds the workflow by name and skips it on reload
    (existing installs pick it up on the next startup, no duplicates);
  * the seeded definition passes ``WorkflowsManager.validate_workflow``;
  * submit with a reviewer -> governed=True + an actionable approval
    notification addressed to that reviewer;
  * submit without a reviewer -> still governed, approval falls back to the
    Admin role.
"""
import json
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from src.app import app
from src.common.app_state import set_app_state_manager
from src.controller.semantic_models_manager import SemanticModelsManager
from src.controller.workflows_manager import WorkflowsManager
from src.db_models.notifications import NotificationDb
from src.models.process_workflows import ProcessWorkflowCreate

WORKFLOW_NAME = "Concept Reviewer Approval (Default)"


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


def _seeded_workflow(db_session: Session):
    mgr = WorkflowsManager(db=db_session)
    mgr.load_from_yaml()
    matches = [w for w in mgr.list_workflows() if w.name == WORKFLOW_NAME]
    assert len(matches) == 1, [w.name for w in mgr.list_workflows()]
    return mgr, matches[0]


def _make_draft_concept(client: TestClient, label: str) -> str:
    r = client.post("/api/knowledge/collections", json={
        "label": f"Review WF {uuid.uuid4().hex[:8]}", "collection_type": "glossary",
        "scope_level": "enterprise", "description": "default concept review workflow test",
    })
    assert r.status_code == 200, r.text
    coll = r.json()
    r = client.post("/api/knowledge/concepts", json={
        "collection_iri": coll["iri"], "label": label, "definition": "def",
    })
    assert r.status_code == 200, r.text
    b = r.json()
    return b.get("iri") or (b.get("concept") or {}).get("iri")


def _payload(n) -> dict:
    p = n.action_payload or {}
    return json.loads(p) if isinstance(p, str) else p


def _approval_notifications(db_session: Session, concept_iri: str):
    rows = db_session.query(NotificationDb).filter(
        NotificationDb.action_type == "workflow_approval"
    ).all()
    return [
        n for n in rows
        if _payload(n).get("entity_id") == concept_iri
        and _payload(n).get("workflow_name") == WORKFLOW_NAME
    ]


def test_default_yaml_seeds_concept_review_once_and_validates(db_session):
    mgr, wf = _seeded_workflow(db_session)

    assert wf.is_active is True
    assert wf.is_default is True
    assert wf.trigger.type.value == "on_request_status_change"
    assert [e.value for e in wf.trigger.entity_types] == ["ontology_concept"]
    assert wf.trigger.from_status == "draft"
    assert wf.trigger.to_status == "under_review"

    # Reload (= next startup on an existing install): skipped, not duplicated.
    again = mgr.load_from_yaml()
    assert again["created"] == 0
    assert len([w for w in mgr.list_workflows() if w.name == WORKFLOW_NAME]) == 1

    # The seeded definition passes the workflow validator.
    result = mgr.validate_workflow(ProcessWorkflowCreate.model_validate(wf.model_dump()))
    assert result.valid, result.errors
    assert not result.warnings, result.warnings


def test_submit_with_reviewer_is_governed_and_notifies_reviewer(client, smm, db_session):
    _seeded_workflow(db_session)
    iri = _make_draft_concept(client, "Customer")

    out = smm.submit_concept_for_review(
        concept_iri=iri,
        reviewer_email="reviewer@example.com",
        submitted_by="author@example.com",
    )

    assert out["governed"] is True
    assert smm.get_concept(iri)["status"] == "under_review"
    notes = _approval_notifications(db_session, iri)
    assert [n.recipient for n in notes] == ["reviewer@example.com"]
    assert _payload(notes[0])["requester_email"] == "author@example.com"


def test_submit_without_reviewer_falls_back_to_admin_role(client, smm, db_session):
    _seeded_workflow(db_session)
    iri = _make_draft_concept(client, "Revenue")

    out = smm.submit_concept_for_review(
        concept_iri=iri,
        reviewer_email=None,
        submitted_by="author@example.com",
    )

    assert out["governed"] is True
    notes = _approval_notifications(db_session, iri)
    assert len(notes) == 1
    assert notes[0].recipient == "Admin"


def test_governed_submit_skips_parallel_data_asset_review(client, smm, db_session):
    """With a reviewer, a governed submit must not also open a DataAssetReview
    (that fires a second approval to DataSteward via the default review workflow)."""
    _seeded_workflow(db_session)
    iri = _make_draft_concept(client, "Margin")

    out = smm.submit_concept_for_review(
        concept_iri=iri,
        reviewer_email="reviewer@example.com",
        submitted_by="author@example.com",
    )

    assert out["governed"] is True
    assert out["review_request_id"] is None


def test_unresolvable_approver_falls_back_to_admin(client, smm, db_session):
    """An approver spec that resolves to nobody (e.g. a business role or owner not
    assigned on the entity) used to dead-end the
    approval ("Could not resolve any approvers") with nobody notified."""
    mgr, _ = _seeded_workflow(db_session)
    name = f"Unresolvable approver review {uuid.uuid4().hex[:6]}"
    mgr.create_workflow(ProcessWorkflowCreate.model_validate({
        "name": name,
        "trigger": {
            "type": "on_request_status_change",
            "entity_types": ["ontology_concept"],
            "from_status": "draft",
            "to_status": "under_review",
        },
        "scope": {"type": "all"},
        "is_active": True,
        "steps": [
            {"step_id": "approve", "name": "Approve", "step_type": "approval",
             "config": {"approvers": "owner"}, "on_pass": "done"},
            {"step_id": "done", "name": "Done", "step_type": "pass"},
        ],
    }))
    iri = _make_draft_concept(client, "Churn")

    smm.submit_concept_for_review(
        concept_iri=iri, reviewer_email=None, submitted_by="author@example.com",
    )

    rows = db_session.query(NotificationDb).filter(
        NotificationDb.action_type == "workflow_approval"
    ).all()
    notes = [
        n for n in rows
        if _payload(n).get("entity_id") == iri and _payload(n).get("workflow_name") == name
    ]
    assert [n.recipient for n in notes] == ["Admin"]
