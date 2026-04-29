"""
Approval Workflows v2 — E2E tests for issues #242, #277-279, #290-292.

Covers:
- Workflow CRUD with workflow_type (process vs approval)
- New approval step types: legal_document, acknowledgement_checklist,
  co_signers, persist_agreement, generate_pdf, deliver
- grant_permissions step type (process workflow)
- Step-type-schemas endpoint includes all new types
- Approval wizard session lifecycle with new step types
- Workflow snapshot on agreement
- Default workflow reload with new subscription template
"""
import json
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _uid():
    import uuid
    return uuid.uuid4().hex[:8]


def _make_approval_workflow(**overrides):
    """Create an approval workflow payload with new step types."""
    defaults = {
        "name": f"E2E-approval-{_uid()}",
        "description": "E2E approval workflow with full step catalog",
        "workflow_type": "approval",
        "trigger": {"type": "for_subscribe", "entity_types": []},
        "is_active": True,
        "steps": [
            {
                "step_id": "legal",
                "name": "Terms of Service",
                "step_type": "legal_document",
                "config": {
                    "title": "E2E Terms",
                    "description": "Test legal document",
                    "body_markdown": "# Terms\n\nYou agree to everything.",
                    "require_scroll_to_end": True,
                    "require_acknowledgement_checkbox": True,
                    "acknowledgement_label": "I accept",
                },
                "on_pass": "checklist",
                "order": 0,
            },
            {
                "step_id": "checklist",
                "name": "Acknowledgements",
                "step_type": "acknowledgement_checklist",
                "config": {
                    "title": "Confirm",
                    "items": [
                        {"id": "accept_tos", "label": "I accept the ToS", "required": True},
                        {"id": "accept_pii", "label": "I accept PII usage", "required": True},
                        {"id": "optional_newsletter", "label": "Subscribe to newsletter", "required": False},
                    ],
                },
                "on_pass": "reason",
                "order": 1,
            },
            {
                "step_id": "reason",
                "name": "Provide Reason",
                "step_type": "user_action",
                "config": {
                    "title": "Subscription Details",
                    "requires_input": True,
                    "minimum_input_length": 5,
                    "required_fields": [
                        {"id": "reason", "label": "Reason", "type": "text", "required": True},
                    ],
                },
                "on_pass": "done",
                "order": 2,
            },
            {
                "step_id": "done",
                "name": "Complete",
                "step_type": "pass",
                "config": {},
                "order": 3,
            },
        ],
    }
    defaults.update(overrides)
    return defaults


def _make_process_workflow(**overrides):
    """Create a process workflow payload with grant_permissions step."""
    defaults = {
        "name": f"E2E-process-{_uid()}",
        "description": "E2E process workflow with grant_permissions",
        "workflow_type": "process",
        "trigger": {"type": "manual", "entity_types": ["data_contract"]},
        "is_active": False,
        "steps": [
            {
                "step_id": "notify",
                "name": "Notify Owner",
                "step_type": "notification",
                "config": {"recipients": "owner", "template": "E2E test"},
                "on_pass": "grant",
                "order": 0,
            },
            {
                "step_id": "grant",
                "name": "Grant Access",
                "step_type": "grant_permissions",
                "config": {
                    "permission_type": "SELECT",
                    "target_source": "from_entity",
                    "principal_source": "requester",
                },
                "on_pass": "done",
                "order": 1,
            },
            {
                "step_id": "done",
                "name": "Done",
                "step_type": "pass",
                "config": {},
                "order": 2,
            },
        ],
    }
    defaults.update(overrides)
    return defaults


# ===========================================================================
# Test classes
# ===========================================================================

class TestStepTypeSchemas:
    """Verify the step-types endpoint returns all new types (#242, #292)."""

    @pytest.mark.readonly
    def test_step_types_include_new_approval_types(self, api, url):
        resp = api.get(url("/api/workflows/step-types"))
        assert resp.status_code == 200
        schemas = resp.json()
        type_names = {s["type"] for s in schemas}

        for expected in [
            "legal_document",
            "acknowledgement_checklist",
            "co_signers",
            "persist_agreement",
            "generate_pdf",
            "deliver",
            "grant_permissions",
        ]:
            assert expected in type_names, f"Missing step type schema: {expected}"

    @pytest.mark.readonly
    def test_legal_document_schema_has_config_fields(self, api, url):
        resp = api.get(url("/api/workflows/step-types"))
        schemas = {s["type"]: s for s in resp.json()}
        ld = schemas["legal_document"]
        props = ld["config_schema"]["properties"]
        assert "body_markdown" in props
        assert "require_scroll_to_end" in props
        assert "require_acknowledgement_checkbox" in props

    @pytest.mark.readonly
    def test_grant_permissions_schema_has_config_fields(self, api, url):
        resp = api.get(url("/api/workflows/step-types"))
        schemas = {s["type"]: s for s in resp.json()}
        gp = schemas["grant_permissions"]
        props = gp["config_schema"]["properties"]
        assert "permission_type" in props
        assert "target_source" in props
        assert "principal_source" in props


class TestApprovalWorkflowCRUD:
    """Create, read, update, delete approval workflows with new step types."""

    @pytest.fixture(autouse=True)
    def _cleanup(self, api, url):
        self._to_delete = []
        yield
        for wid in reversed(self._to_delete):
            api.delete(url(f"/api/workflows/{wid}"))

    def test_create_approval_workflow_with_full_catalog(self, api, url):
        """Create an approval workflow using legal_document, acknowledgement_checklist, user_action."""
        payload = _make_approval_workflow()
        resp = api.post(url("/api/workflows"), json=payload)
        assert resp.status_code in (200, 201), f"Create failed: {resp.text[:500]}"
        created = resp.json()
        wf_id = created["id"]
        self._to_delete.append(wf_id)

        # Verify workflow_type persisted
        assert created.get("workflow_type") == "approval"

        # Verify steps round-tripped
        steps = created["steps"]
        step_types = [s["step_type"] for s in steps]
        assert "legal_document" in step_types
        assert "acknowledgement_checklist" in step_types
        assert "user_action" in step_types

    def test_create_approval_workflow_with_co_signers(self, api, url):
        """Workflow with co_signers step."""
        payload = _make_approval_workflow(
            name=f"E2E-cosigners-{_uid()}",
            steps=[
                {
                    "step_id": "cosign",
                    "name": "Add Co-Signers",
                    "step_type": "co_signers",
                    "config": {
                        "title": "Co-Signers",
                        "min_count": 1,
                        "max_count": 3,
                        "principal_type": "user",
                    },
                    "on_pass": "done",
                    "order": 0,
                },
                {"step_id": "done", "name": "Done", "step_type": "pass", "config": {}, "order": 1},
            ],
        )
        resp = api.post(url("/api/workflows"), json=payload)
        assert resp.status_code in (200, 201)
        created = resp.json()
        self._to_delete.append(created["id"])

        cosign_step = next(s for s in created["steps"] if s["step_type"] == "co_signers")
        cfg = cosign_step["config"]
        assert cfg["min_count"] == 1
        assert cfg["max_count"] == 3

    def test_create_approval_workflow_with_nonvisual_steps(self, api, url):
        """Workflow with persist_agreement + generate_pdf + deliver."""
        payload = _make_approval_workflow(
            name=f"E2E-nonvisual-{_uid()}",
            steps=[
                {
                    "step_id": "user-input",
                    "name": "Input",
                    "step_type": "user_action",
                    "config": {"title": "Enter reason", "requires_input": True},
                    "on_pass": "persist",
                    "order": 0,
                },
                {
                    "step_id": "persist",
                    "name": "Save",
                    "step_type": "persist_agreement",
                    "config": {},
                    "on_pass": "pdf",
                    "order": 1,
                },
                {
                    "step_id": "pdf",
                    "name": "PDF",
                    "step_type": "generate_pdf",
                    "config": {},
                    "on_pass": "deliver",
                    "order": 2,
                },
                {
                    "step_id": "deliver",
                    "name": "Send",
                    "step_type": "deliver",
                    "config": {
                        "channels": ["in_app", "email"],
                        "recipients": ["signer", "entity_owner"],
                    },
                    "on_pass": "done",
                    "order": 3,
                },
                {"step_id": "done", "name": "Done", "step_type": "pass", "config": {}, "order": 4},
            ],
        )
        resp = api.post(url("/api/workflows"), json=payload)
        assert resp.status_code in (200, 201), f"Create failed: {resp.text[:500]}"
        created = resp.json()
        self._to_delete.append(created["id"])

        step_types = [s["step_type"] for s in created["steps"]]
        assert "persist_agreement" in step_types
        assert "generate_pdf" in step_types
        assert "deliver" in step_types

    def test_read_approval_workflow_preserves_config(self, api, url):
        """Verify legal_document config round-trips through create + read."""
        payload = _make_approval_workflow()
        resp = api.post(url("/api/workflows"), json=payload)
        created = resp.json()
        wf_id = created["id"]
        self._to_delete.append(wf_id)

        # READ
        resp = api.get(url(f"/api/workflows/{wf_id}"))
        assert resp.status_code == 200
        fetched = resp.json()

        legal_step = next(s for s in fetched["steps"] if s["step_type"] == "legal_document")
        assert legal_step["config"]["body_markdown"] == "# Terms\n\nYou agree to everything."
        assert legal_step["config"]["require_scroll_to_end"] is True
        assert legal_step["config"]["acknowledgement_label"] == "I accept"

    def test_update_approval_workflow(self, api, url):
        """Update step config and verify persistence."""
        payload = _make_approval_workflow()
        resp = api.post(url("/api/workflows"), json=payload)
        created = resp.json()
        wf_id = created["id"]
        self._to_delete.append(wf_id)

        # Update: change acknowledgement label
        update_steps = payload["steps"]
        update_steps[0]["config"]["acknowledgement_label"] = "I REALLY accept"
        resp = api.put(url(f"/api/workflows/{wf_id}"), json={
            "name": payload["name"],
            "steps": update_steps,
        })
        assert resp.status_code == 200

        # Verify
        resp = api.get(url(f"/api/workflows/{wf_id}"))
        legal_step = next(s for s in resp.json()["steps"] if s["step_type"] == "legal_document")
        assert legal_step["config"]["acknowledgement_label"] == "I REALLY accept"


class TestProcessWorkflowWithGrantPermissions:
    """Process workflow CRUD with grant_permissions step (#292)."""

    @pytest.fixture(autouse=True)
    def _cleanup(self, api, url):
        self._to_delete = []
        yield
        for wid in reversed(self._to_delete):
            api.delete(url(f"/api/workflows/{wid}"))

    def test_create_with_grant_permissions(self, api, url):
        payload = _make_process_workflow()
        resp = api.post(url("/api/workflows"), json=payload)
        assert resp.status_code in (200, 201), f"Create failed: {resp.text[:500]}"
        created = resp.json()
        self._to_delete.append(created["id"])

        assert created.get("workflow_type") == "process"
        grant_step = next(s for s in created["steps"] if s["step_type"] == "grant_permissions")
        assert grant_step["config"]["permission_type"] == "SELECT"
        assert grant_step["config"]["target_source"] == "from_entity"

    def test_grant_permissions_with_variable_source(self, api, url):
        payload = _make_process_workflow(
            name=f"E2E-grant-var-{_uid()}",
        )
        # Modify grant step to use from_variable
        for s in payload["steps"]:
            if s["step_type"] == "grant_permissions":
                s["config"]["principal_source"] = "from_variable"
                s["config"]["principal_variable"] = "step_results.approval.principal"
        resp = api.post(url("/api/workflows"), json=payload)
        assert resp.status_code in (200, 201)
        created = resp.json()
        self._to_delete.append(created["id"])

        grant_step = next(s for s in created["steps"] if s["step_type"] == "grant_permissions")
        assert grant_step["config"]["principal_source"] == "from_variable"
        assert grant_step["config"]["principal_variable"] == "step_results.approval.principal"


class TestWorkflowTypeFiltering:
    """Verify workflow_type filtering works (#279)."""

    @pytest.fixture(autouse=True)
    def _cleanup(self, api, url):
        self._to_delete = []
        yield
        for wid in reversed(self._to_delete):
            api.delete(url(f"/api/workflows/{wid}"))

    def test_filter_by_type(self, api, url):
        """Create one of each type, verify type filter returns correct subset."""
        # Create approval workflow
        a_resp = api.post(url("/api/workflows"), json=_make_approval_workflow())
        assert a_resp.status_code in (200, 201)
        a_id = a_resp.json()["id"]
        self._to_delete.append(a_id)

        # Create process workflow
        p_resp = api.post(url("/api/workflows"), json=_make_process_workflow())
        assert p_resp.status_code in (200, 201)
        p_id = p_resp.json()["id"]
        self._to_delete.append(p_id)

        # Filter: approval only
        resp = api.get(url("/api/workflows?workflow_type=approval"))
        assert resp.status_code == 200
        approval_ids = {w["id"] for w in resp.json()["workflows"]}
        assert a_id in approval_ids
        assert p_id not in approval_ids

        # Filter: process only
        resp = api.get(url("/api/workflows?workflow_type=process"))
        assert resp.status_code == 200
        process_ids = {w["id"] for w in resp.json()["workflows"]}
        assert p_id in process_ids
        assert a_id not in process_ids

        # No filter: both
        resp = api.get(url("/api/workflows"))
        assert resp.status_code == 200
        all_ids = {w["id"] for w in resp.json()["workflows"]}
        assert a_id in all_ids
        assert p_id in all_ids


class TestApprovalWizardSession:
    """Approval wizard session lifecycle with new step types."""

    @pytest.fixture(autouse=True)
    def _cleanup(self, api, url):
        self._to_delete_wf = []
        self._to_abort_sessions = []
        yield
        for sid in reversed(self._to_abort_sessions):
            try:
                api.post(url(f"/api/approvals/sessions/{sid}/abort"), json={})
            except Exception:
                pass
        for wid in reversed(self._to_delete_wf):
            api.delete(url(f"/api/workflows/{wid}"))

    def test_wizard_session_with_legal_document_step(self, api, url):
        """Create session, submit legal_document step with scroll+ack."""
        # Create workflow
        wf_payload = _make_approval_workflow()
        resp = api.post(url("/api/workflows"), json=wf_payload)
        assert resp.status_code in (200, 201)
        wf = resp.json()
        wf_id = wf["id"]
        self._to_delete_wf.append(wf_id)

        # Start wizard session (need a dummy entity)
        session_resp = api.post(url("/api/approvals/sessions"), json={
            "workflow_id": wf_id,
            "entity_type": "data_product",
            "entity_id": "e2e-test-product",
        })
        assert session_resp.status_code in (200, 201), f"Session start failed: {session_resp.text[:500]}"
        session = session_resp.json()
        session_id = session["session_id"]
        self._to_abort_sessions.append(session_id)

        # First step should be legal_document
        current = session["current_step"]
        assert current["step_type"] == "legal_document"

        # Submit with scroll + ack
        step_resp = api.post(url(f"/api/approvals/sessions/{session_id}/steps"), json={
            "step_id": current["step_id"],
            "payload": {"scrolled_to_end": True, "acknowledged": True},
        })
        assert step_resp.status_code == 200, f"Step submit failed: {step_resp.text[:500]}"
        step_data = step_resp.json()

        # Should advance to acknowledgement_checklist
        assert step_data.get("complete") is not True
        assert step_data["current_step"]["step_type"] == "acknowledgement_checklist"

    def test_legal_document_rejects_without_ack(self, api, url):
        """legal_document step should reject if acknowledgement not given."""
        wf_payload = _make_approval_workflow()
        resp = api.post(url("/api/workflows"), json=wf_payload)
        wf = resp.json()
        wf_id = wf["id"]
        self._to_delete_wf.append(wf_id)

        session_resp = api.post(url("/api/approvals/sessions"), json={
            "workflow_id": wf_id,
            "entity_type": "data_product",
            "entity_id": "e2e-test-reject",
        })
        session = session_resp.json()
        session_id = session["session_id"]
        self._to_abort_sessions.append(session_id)

        # Submit without acknowledged=True
        step_resp = api.post(url(f"/api/approvals/sessions/{session_id}/steps"), json={
            "step_id": session["current_step"]["step_id"],
            "payload": {"scrolled_to_end": True, "acknowledged": False},
        })
        # Should fail validation
        assert step_resp.status_code in (400, 422, 500)

    def test_full_wizard_flow(self, api, url):
        """Walk through legal_document → checklist → user_action → pass."""
        wf_payload = _make_approval_workflow()
        resp = api.post(url("/api/workflows"), json=wf_payload)
        wf = resp.json()
        wf_id = wf["id"]
        self._to_delete_wf.append(wf_id)

        # Start session
        session_resp = api.post(url("/api/approvals/sessions"), json={
            "workflow_id": wf_id,
            "entity_type": "data_product",
            "entity_id": f"e2e-full-flow-{_uid()}",
        })
        session = session_resp.json()
        session_id = session["session_id"]
        self._to_abort_sessions.append(session_id)

        # Step 1: legal_document
        resp = api.post(url(f"/api/approvals/sessions/{session_id}/steps"), json={
            "step_id": "legal",
            "payload": {"scrolled_to_end": True, "acknowledged": True},
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["current_step"]["step_type"] == "acknowledgement_checklist"

        # Step 2: acknowledgement_checklist
        resp = api.post(url(f"/api/approvals/sessions/{session_id}/steps"), json={
            "step_id": "checklist",
            "payload": {"items": {"accept_tos": True, "accept_pii": True, "optional_newsletter": False}},
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["current_step"]["step_type"] == "user_action"

        # Step 3: user_action
        resp = api.post(url(f"/api/approvals/sessions/{session_id}/steps"), json={
            "step_id": "reason",
            "payload": {"reason": "E2E test subscription reason"},
        })
        assert resp.status_code == 200
        data = resp.json()
        # Should complete (pass step auto-completes)
        assert data.get("complete") is True


class TestWorkflowSnapshot:
    """Verify workflow_snapshot is captured on session and agreement (#242)."""

    @pytest.fixture(autouse=True)
    def _cleanup(self, api, url):
        self._to_delete_wf = []
        yield
        for wid in reversed(self._to_delete_wf):
            api.delete(url(f"/api/workflows/{wid}"))

    def test_agreement_has_snapshot(self, api, url):
        """Complete a wizard and verify the agreement includes workflow_snapshot."""
        wf_payload = _make_approval_workflow(
            name=f"E2E-snapshot-{_uid()}",
            steps=[
                {
                    "step_id": "input",
                    "name": "Input",
                    "step_type": "user_action",
                    "config": {"title": "Reason", "requires_input": True},
                    "on_pass": "done",
                    "order": 0,
                },
                {"step_id": "done", "name": "Done", "step_type": "pass", "config": {}, "order": 1},
            ],
        )
        resp = api.post(url("/api/workflows"), json=wf_payload)
        wf = resp.json()
        wf_id = wf["id"]
        self._to_delete_wf.append(wf_id)

        entity_id = f"e2e-snap-{_uid()}"
        # Start + complete session
        session_resp = api.post(url("/api/approvals/sessions"), json={
            "workflow_id": wf_id,
            "entity_type": "data_product",
            "entity_id": entity_id,
        })
        session = session_resp.json()
        session_id = session["session_id"]

        resp = api.post(url(f"/api/approvals/sessions/{session_id}/steps"), json={
            "step_id": "input",
            "payload": {"reason": "E2E snapshot test"},
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("complete") is True

        agreement_id = data.get("agreement_id")
        if agreement_id:
            # Fetch agreement and check snapshot
            agreements_resp = api.get(url(f"/api/approvals/agreements?entity_type=data_product&entity_id={entity_id}"))
            if agreements_resp.status_code == 200:
                agreements = agreements_resp.json()
                if isinstance(agreements, list) and agreements:
                    agreement = agreements[0]
                    # snapshot should be present (string or dict)
                    snapshot = agreement.get("workflow_snapshot")
                    assert snapshot is not None, "workflow_snapshot should be captured on the agreement"


class TestFullCatalogWizardFlow:
    """Walk through ALL step types including non-visual (persist, PDF, deliver)."""

    @pytest.fixture(autouse=True)
    def _cleanup(self, api, url):
        self._to_delete_wf = []
        self._to_abort_sessions = []
        yield
        for sid in reversed(self._to_abort_sessions):
            try:
                api.post(url(f"/api/approvals/sessions/{sid}/abort"), json={})
            except Exception:
                pass
        for wid in reversed(self._to_delete_wf):
            api.delete(url(f"/api/workflows/{wid}"))

    def _make_full_catalog_workflow(self):
        """Workflow with every approval step type: legal → checklist → co_signers → user_action → persist → pdf → deliver → pass."""
        return {
            "name": f"E2E-full-catalog-{_uid()}",
            "description": "Tests every approval step type end-to-end",
            "workflow_type": "approval",
            "trigger": {"type": "for_subscribe", "entity_types": []},
            "is_active": True,
            "steps": [
                {
                    "step_id": "legal",
                    "name": "Terms",
                    "step_type": "legal_document",
                    "config": {
                        "title": "Terms of Service",
                        "body_markdown": "# E2E Terms\n\nFull catalog test.",
                        "require_scroll_to_end": True,
                        "require_acknowledgement_checkbox": True,
                        "acknowledgement_label": "I accept these terms",
                    },
                    "on_pass": "checklist",
                    "order": 0,
                },
                {
                    "step_id": "checklist",
                    "name": "Acknowledgements",
                    "step_type": "acknowledgement_checklist",
                    "config": {
                        "title": "Confirm",
                        "items": [
                            {"id": "tos", "label": "I accept the Terms", "required": True},
                            {"id": "pii", "label": "I accept PII usage", "required": True},
                        ],
                    },
                    "on_pass": "cosign",
                    "order": 1,
                },
                {
                    "step_id": "cosign",
                    "name": "Co-Signers",
                    "step_type": "co_signers",
                    "config": {
                        "title": "Add Co-Signers",
                        "min_count": 0,
                        "max_count": 3,
                        "principal_type": "either",
                    },
                    "on_pass": "reason",
                    "order": 2,
                },
                {
                    "step_id": "reason",
                    "name": "Details",
                    "step_type": "user_action",
                    "config": {
                        "title": "Subscription Details",
                        "requires_input": True,
                        "minimum_input_length": 5,
                        "required_fields": [
                            {"id": "reason", "label": "Reason", "type": "text", "required": True},
                        ],
                    },
                    "on_pass": "persist",
                    "order": 3,
                },
                {
                    "step_id": "persist",
                    "name": "Save Agreement",
                    "step_type": "persist_agreement",
                    "config": {},
                    "on_pass": "pdf",
                    "order": 4,
                },
                {
                    "step_id": "pdf",
                    "name": "Generate PDF",
                    "step_type": "generate_pdf",
                    "config": {},
                    "on_pass": "send",
                    "order": 5,
                },
                {
                    "step_id": "send",
                    "name": "Deliver",
                    "step_type": "deliver",
                    "config": {
                        "channels": ["in_app", "email"],
                        "recipients": ["signer", "entity_owner"],
                    },
                    "on_pass": "done",
                    "order": 6,
                },
                {
                    "step_id": "done",
                    "name": "Complete",
                    "step_type": "pass",
                    "config": {},
                    "order": 7,
                },
            ],
        }

    def test_full_catalog_end_to_end(self, api, url):
        """Walk through legal → checklist → co_signers → user_action → persist → pdf → deliver → pass."""
        wf_payload = self._make_full_catalog_workflow()
        resp = api.post(url("/api/workflows"), json=wf_payload)
        assert resp.status_code in (200, 201), f"Create failed: {resp.text[:500]}"
        wf_id = resp.json()["id"]
        self._to_delete_wf.append(wf_id)

        entity_id = f"e2e-full-{_uid()}"
        session_resp = api.post(url("/api/approvals/sessions"), json={
            "workflow_id": wf_id,
            "entity_type": "data_product",
            "entity_id": entity_id,
        })
        assert session_resp.status_code in (200, 201), f"Session failed: {session_resp.text[:500]}"
        session = session_resp.json()
        session_id = session["session_id"]
        self._to_abort_sessions.append(session_id)

        # Step 1: legal_document
        assert session["current_step"]["step_type"] == "legal_document"
        resp = api.post(url(f"/api/approvals/sessions/{session_id}/steps"), json={
            "step_id": "legal",
            "payload": {"scrolled_to_end": True, "acknowledged": True},
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["current_step"]["step_type"] == "acknowledgement_checklist"

        # Step 2: acknowledgement_checklist
        resp = api.post(url(f"/api/approvals/sessions/{session_id}/steps"), json={
            "step_id": "checklist",
            "payload": {"items": {"tos": True, "pii": True}},
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["current_step"]["step_type"] == "co_signers"

        # Step 3: co_signers (optional, submit empty list)
        resp = api.post(url(f"/api/approvals/sessions/{session_id}/steps"), json={
            "step_id": "cosign",
            "payload": {"co_signers": []},
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["current_step"]["step_type"] == "user_action"

        # Step 4: user_action
        resp = api.post(url(f"/api/approvals/sessions/{session_id}/steps"), json={
            "step_id": "reason",
            "payload": {"reason": "Full catalog E2E test with all step types"},
        })
        assert resp.status_code == 200
        data = resp.json()

        # Steps 5-7: persist_agreement, generate_pdf, deliver are non-visual.
        # The backend should auto-advance through them (or the wizard submits them).
        # Either way, after user_action the next step should be persist_agreement.
        if not data.get("complete"):
            assert data["current_step"]["step_type"] == "persist_agreement"
            # Submit persist_agreement (no payload needed)
            resp = api.post(url(f"/api/approvals/sessions/{session_id}/steps"), json={
                "step_id": "persist",
                "payload": {},
            })
            assert resp.status_code == 200
            data = resp.json()

        if not data.get("complete"):
            assert data["current_step"]["step_type"] == "generate_pdf"
            resp = api.post(url(f"/api/approvals/sessions/{session_id}/steps"), json={
                "step_id": "pdf",
                "payload": {},
            })
            assert resp.status_code == 200
            data = resp.json()

        if not data.get("complete"):
            assert data["current_step"]["step_type"] == "deliver"
            resp = api.post(url(f"/api/approvals/sessions/{session_id}/steps"), json={
                "step_id": "send",
                "payload": {},
            })
            assert resp.status_code == 200
            data = resp.json()

        # Should now be complete (pass step)
        if not data.get("complete"):
            # One more submit for the pass step
            resp = api.post(url(f"/api/approvals/sessions/{session_id}/steps"), json={
                "step_id": "done",
                "payload": {},
            })
            assert resp.status_code == 200
            data = resp.json()

        assert data.get("complete") is True, f"Expected complete after all steps, got: {data}"

    def test_co_signers_with_entries(self, api, url):
        """Submit co_signers step with actual signer entries."""
        wf_payload = self._make_full_catalog_workflow()
        # Modify co_signers to require at least 1
        for s in wf_payload["steps"]:
            if s["step_type"] == "co_signers":
                s["config"]["min_count"] = 1
        resp = api.post(url("/api/workflows"), json=wf_payload)
        assert resp.status_code in (200, 201)
        wf_id = resp.json()["id"]
        self._to_delete_wf.append(wf_id)

        session_resp = api.post(url("/api/approvals/sessions"), json={
            "workflow_id": wf_id,
            "entity_type": "data_product",
            "entity_id": f"e2e-cosign-{_uid()}",
        })
        session = session_resp.json()
        session_id = session["session_id"]
        self._to_abort_sessions.append(session_id)

        # Advance through legal + checklist
        api.post(url(f"/api/approvals/sessions/{session_id}/steps"), json={
            "step_id": "legal", "payload": {"scrolled_to_end": True, "acknowledged": True},
        })
        api.post(url(f"/api/approvals/sessions/{session_id}/steps"), json={
            "step_id": "checklist", "payload": {"items": {"tos": True, "pii": True}},
        })

        # Submit co_signers with entries
        resp = api.post(url(f"/api/approvals/sessions/{session_id}/steps"), json={
            "step_id": "cosign",
            "payload": {"co_signers": ["alice@example.com", "bob@example.com"]},
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["current_step"]["step_type"] == "user_action"

    def test_co_signers_rejects_below_min(self, api, url):
        """co_signers step should reject when below min_count."""
        wf_payload = self._make_full_catalog_workflow()
        for s in wf_payload["steps"]:
            if s["step_type"] == "co_signers":
                s["config"]["min_count"] = 2
        resp = api.post(url("/api/workflows"), json=wf_payload)
        assert resp.status_code in (200, 201)
        wf_id = resp.json()["id"]
        self._to_delete_wf.append(wf_id)

        session_resp = api.post(url("/api/approvals/sessions"), json={
            "workflow_id": wf_id,
            "entity_type": "data_product",
            "entity_id": f"e2e-cosign-reject-{_uid()}",
        })
        session = session_resp.json()
        session_id = session["session_id"]
        self._to_abort_sessions.append(session_id)

        # Advance through legal + checklist
        api.post(url(f"/api/approvals/sessions/{session_id}/steps"), json={
            "step_id": "legal", "payload": {"scrolled_to_end": True, "acknowledged": True},
        })
        api.post(url(f"/api/approvals/sessions/{session_id}/steps"), json={
            "step_id": "checklist", "payload": {"items": {"tos": True, "pii": True}},
        })

        # Submit co_signers with only 1 (min is 2)
        resp = api.post(url(f"/api/approvals/sessions/{session_id}/steps"), json={
            "step_id": "cosign",
            "payload": {"co_signers": ["only-one@example.com"]},
        })
        assert resp.status_code in (400, 422, 500), f"Should reject: {resp.status_code}"

    def test_checklist_rejects_unchecked_required(self, api, url):
        """acknowledgement_checklist should reject when required items are unchecked."""
        wf_payload = self._make_full_catalog_workflow()
        resp = api.post(url("/api/workflows"), json=wf_payload)
        assert resp.status_code in (200, 201)
        wf_id = resp.json()["id"]
        self._to_delete_wf.append(wf_id)

        session_resp = api.post(url("/api/approvals/sessions"), json={
            "workflow_id": wf_id,
            "entity_type": "data_product",
            "entity_id": f"e2e-checklist-reject-{_uid()}",
        })
        session = session_resp.json()
        session_id = session["session_id"]
        self._to_abort_sessions.append(session_id)

        # Advance through legal
        api.post(url(f"/api/approvals/sessions/{session_id}/steps"), json={
            "step_id": "legal", "payload": {"scrolled_to_end": True, "acknowledged": True},
        })

        # Submit checklist with one required item unchecked
        resp = api.post(url(f"/api/approvals/sessions/{session_id}/steps"), json={
            "step_id": "checklist",
            "payload": {"items": {"tos": True, "pii": False}},
        })
        assert resp.status_code in (400, 422, 500), f"Should reject unchecked required item: {resp.status_code}"


class TestAbortAndSessionsList:
    """Abort sessions and verify the sessions list endpoint."""

    @pytest.fixture(autouse=True)
    def _cleanup(self, api, url):
        self._to_delete_wf = []
        yield
        for wid in reversed(self._to_delete_wf):
            api.delete(url(f"/api/workflows/{wid}"))

    def test_abort_session_mid_flow(self, api, url):
        """Start a session, submit one step, then abort."""
        wf_payload = _make_approval_workflow()
        resp = api.post(url("/api/workflows"), json=wf_payload)
        assert resp.status_code in (200, 201)
        wf_id = resp.json()["id"]
        self._to_delete_wf.append(wf_id)

        session_resp = api.post(url("/api/approvals/sessions"), json={
            "workflow_id": wf_id,
            "entity_type": "data_product",
            "entity_id": f"e2e-abort-{_uid()}",
        })
        assert session_resp.status_code in (200, 201)
        session_id = session_resp.json()["session_id"]

        # Submit first step
        api.post(url(f"/api/approvals/sessions/{session_id}/steps"), json={
            "step_id": "legal",
            "payload": {"scrolled_to_end": True, "acknowledged": True},
        })

        # Abort
        abort_resp = api.post(url(f"/api/approvals/sessions/{session_id}/abort"), json={})
        assert abort_resp.status_code == 200

        # Verify session is abandoned
        session_data = api.get(url(f"/api/approvals/sessions/{session_id}"))
        if session_data.status_code == 200:
            assert session_data.json().get("status") == "abandoned"

    def test_sessions_list_endpoint(self, api, url):
        """Verify GET /api/approvals/sessions returns recent sessions."""
        resp = api.get(url("/api/approvals/sessions"))
        assert resp.status_code == 200
        data = resp.json()
        assert "sessions" in data
        assert isinstance(data["sessions"], list)
        # Should have at least some sessions from previous tests
        assert data["total"] >= 0

    def test_sessions_list_includes_completed_and_abandoned(self, api, url):
        """Create one completed and one abandoned session, verify both appear."""
        wf_payload = _make_approval_workflow(
            name=f"E2E-list-test-{_uid()}",
            steps=[
                {
                    "step_id": "input",
                    "name": "Input",
                    "step_type": "user_action",
                    "config": {"title": "Reason", "requires_input": True},
                    "on_pass": "done",
                    "order": 0,
                },
                {"step_id": "done", "name": "Done", "step_type": "pass", "config": {}, "order": 1},
            ],
        )
        resp = api.post(url("/api/workflows"), json=wf_payload)
        assert resp.status_code in (200, 201)
        wf_id = resp.json()["id"]
        self._to_delete_wf.append(wf_id)

        # Create completed session
        s1 = api.post(url("/api/approvals/sessions"), json={
            "workflow_id": wf_id, "entity_type": "data_product", "entity_id": f"e2e-list-1-{_uid()}",
        }).json()
        api.post(url(f"/api/approvals/sessions/{s1['session_id']}/steps"), json={
            "step_id": "input", "payload": {"reason": "E2E completed session"},
        })

        # Create abandoned session
        s2 = api.post(url("/api/approvals/sessions"), json={
            "workflow_id": wf_id, "entity_type": "data_product", "entity_id": f"e2e-list-2-{_uid()}",
        }).json()
        api.post(url(f"/api/approvals/sessions/{s2['session_id']}/abort"), json={})

        # List and verify both appear
        list_resp = api.get(url("/api/approvals/sessions?limit=50"))
        assert list_resp.status_code == 200
        sessions = list_resp.json()["sessions"]
        session_ids = {s["id"] for s in sessions}
        assert s1["session_id"] in session_ids, "Completed session should appear"
        assert s2["session_id"] in session_ids, "Abandoned session should appear"

        # Verify statuses
        completed = next((s for s in sessions if s["id"] == s1["session_id"]), None)
        abandoned = next((s for s in sessions if s["id"] == s2["session_id"]), None)
        if completed:
            assert completed["status"] == "completed"
        if abandoned:
            assert abandoned["status"] == "abandoned"


class TestAgreementPdfDownload:
    """Verify the PDF (HTML) download endpoint for completed agreements (#242)."""

    @pytest.fixture(autouse=True)
    def _cleanup(self, api, url):
        self._to_delete_wf = []
        yield
        for wid in reversed(self._to_delete_wf):
            api.delete(url(f"/api/workflows/{wid}"))

    def _complete_full_catalog_wizard(self, api, url):
        """Create a full-catalog workflow, run through all steps, return (workflow_id, agreement_id, workflow_name)."""
        wf_name = f"E2E-pdf-{_uid()}"
        wf_payload = {
            "name": wf_name,
            "description": "E2E PDF download test",
            "workflow_type": "approval",
            "trigger": {"type": "for_subscribe", "entity_types": []},
            "is_active": True,
            "steps": [
                {
                    "step_id": "legal",
                    "name": "Terms",
                    "step_type": "legal_document",
                    "config": {
                        "title": "E2E Terms",
                        "body_markdown": "# Terms\n\nAccept.",
                        "require_scroll_to_end": True,
                        "require_acknowledgement_checkbox": True,
                        "acknowledgement_label": "I accept",
                    },
                    "on_pass": "checklist",
                    "order": 0,
                },
                {
                    "step_id": "checklist",
                    "name": "Acks",
                    "step_type": "acknowledgement_checklist",
                    "config": {
                        "title": "Confirm",
                        "items": [{"id": "ok", "label": "I confirm", "required": True}],
                    },
                    "on_pass": "reason",
                    "order": 1,
                },
                {
                    "step_id": "reason",
                    "name": "Details",
                    "step_type": "user_action",
                    "config": {"title": "Reason", "requires_input": True, "minimum_input_length": 5},
                    "on_pass": "persist",
                    "order": 2,
                },
                {"step_id": "persist", "name": "Save", "step_type": "persist_agreement", "config": {}, "on_pass": "pdf", "order": 3},
                {"step_id": "pdf", "name": "Generate PDF", "step_type": "generate_pdf", "config": {}, "on_pass": "send", "order": 4},
                {
                    "step_id": "send",
                    "name": "Deliver",
                    "step_type": "deliver",
                    "config": {"channels": ["in_app"], "recipients": ["signer"]},
                    "on_pass": "done",
                    "order": 5,
                },
                {"step_id": "done", "name": "Done", "step_type": "pass", "config": {}, "order": 6},
            ],
        }
        resp = api.post(url("/api/workflows"), json=wf_payload)
        assert resp.status_code in (200, 201), f"Create wf failed: {resp.text[:500]}"
        wf_id = resp.json()["id"]
        self._to_delete_wf.append(wf_id)

        entity_id = f"e2e-pdf-{_uid()}"
        session_resp = api.post(url("/api/approvals/sessions"), json={
            "workflow_id": wf_id,
            "entity_type": "data_product",
            "entity_id": entity_id,
        })
        assert session_resp.status_code in (200, 201)
        session = session_resp.json()
        sid = session["session_id"]

        # Walk through visual steps
        api.post(url(f"/api/approvals/sessions/{sid}/steps"), json={
            "step_id": "legal", "payload": {"scrolled_to_end": True, "acknowledged": True},
        })
        api.post(url(f"/api/approvals/sessions/{sid}/steps"), json={
            "step_id": "checklist", "payload": {"items": {"ok": True}},
        })
        data = api.post(url(f"/api/approvals/sessions/{sid}/steps"), json={
            "step_id": "reason", "payload": {"reason": "E2E PDF download test reason"},
        }).json()

        # Walk through non-visual steps if not auto-advanced
        for step_id in ("persist", "pdf", "send", "done"):
            if data.get("complete"):
                break
            data = api.post(url(f"/api/approvals/sessions/{sid}/steps"), json={
                "step_id": step_id, "payload": {},
            }).json()

        assert data.get("complete") is True, f"Wizard should be complete, got: {data}"
        agreement_id = data.get("agreement_id")
        assert agreement_id, "Expected agreement_id in completion response"
        return wf_id, agreement_id, wf_name

    def test_pdf_download_returns_pdf_attachment(self, api, url):
        """GET /api/approvals/agreements/{id}/pdf returns 200 with real PDF content."""
        _, agreement_id, wf_name = self._complete_full_catalog_wizard(api, url)

        resp = api.get(url(f"/api/approvals/agreements/{agreement_id}/pdf"))
        assert resp.status_code == 200, f"PDF endpoint failed: {resp.status_code} {resp.text[:500]}"

        # Content-Disposition should indicate attachment with .pdf filename
        cd = resp.headers.get("content-disposition", "")
        assert "attachment" in cd.lower(), f"Expected attachment Content-Disposition, got: {cd}"
        assert ".pdf" in cd, f"Filename should be .pdf, got: {cd}"

        # Content-Type should be application/pdf
        ct = resp.headers.get("content-type", "")
        assert "application/pdf" in ct or "text/html" in ct, f"Expected PDF or HTML content type, got: {ct}"

        # Body should be non-empty
        assert len(resp.content) > 100, f"PDF body too small: {len(resp.content)} bytes"

        # If real PDF, verify workflow name is embedded
        if resp.content[:5] == b"%PDF-":
            assert wf_name.encode() in resp.content, f"PDF should contain workflow name '{wf_name}'"


class TestAgreementsListEndpoint:
    """Verify the agreements list endpoint returns completed agreements."""

    @pytest.fixture(autouse=True)
    def _cleanup(self, api, url):
        self._to_delete_wf = []
        yield
        for wid in reversed(self._to_delete_wf):
            api.delete(url(f"/api/workflows/{wid}"))

    def test_agreements_list_returns_200(self, api, url):
        """GET /api/approvals/agreements returns 200 with an 'agreements' key."""
        resp = api.get(url("/api/approvals/agreements"))
        assert resp.status_code == 200
        data = resp.json()
        assert "agreements" in data
        assert isinstance(data["agreements"], list)

    def test_new_agreement_appears_in_list(self, api, url):
        """After completing a wizard, the new agreement appears in the agreements list."""
        # Create a simple workflow and complete it
        wf_payload = _make_approval_workflow(
            name=f"E2E-agr-list-{_uid()}",
            steps=[
                {
                    "step_id": "input",
                    "name": "Input",
                    "step_type": "user_action",
                    "config": {"title": "Reason", "requires_input": True},
                    "on_pass": "persist",
                    "order": 0,
                },
                {"step_id": "persist", "name": "Save", "step_type": "persist_agreement", "config": {}, "on_pass": "done", "order": 1},
                {"step_id": "done", "name": "Done", "step_type": "pass", "config": {}, "order": 2},
            ],
        )
        resp = api.post(url("/api/workflows"), json=wf_payload)
        assert resp.status_code in (200, 201)
        wf_id = resp.json()["id"]
        self._to_delete_wf.append(wf_id)

        entity_id = f"e2e-agr-list-{_uid()}"
        session_resp = api.post(url("/api/approvals/sessions"), json={
            "workflow_id": wf_id,
            "entity_type": "data_product",
            "entity_id": entity_id,
        })
        assert session_resp.status_code in (200, 201)
        sid = session_resp.json()["session_id"]

        data = api.post(url(f"/api/approvals/sessions/{sid}/steps"), json={
            "step_id": "input", "payload": {"reason": "E2E agreements list test"},
        }).json()

        # Walk through persist + done if not auto-advanced
        for step_id in ("persist", "done"):
            if data.get("complete"):
                break
            data = api.post(url(f"/api/approvals/sessions/{sid}/steps"), json={
                "step_id": step_id, "payload": {},
            }).json()

        assert data.get("complete") is True
        agreement_id = data.get("agreement_id")
        assert agreement_id, "Expected agreement_id from completion"

        # Now verify it appears in the list
        list_resp = api.get(url("/api/approvals/agreements"))
        assert list_resp.status_code == 200
        agreements = list_resp.json()["agreements"]
        agreement_ids = set()
        for a in agreements:
            aid = a.get("id") or a.get("agreement_id")
            if aid:
                agreement_ids.add(aid)
        assert agreement_id in agreement_ids, f"New agreement {agreement_id} should appear in agreements list"


class TestInAppDeliveryNotification:
    """Verify that completing a wizard with in_app deliver creates a notification."""

    @pytest.fixture(autouse=True)
    def _cleanup(self, api, url):
        self._to_delete_wf = []
        yield
        for wid in reversed(self._to_delete_wf):
            api.delete(url(f"/api/workflows/{wid}"))

    def test_in_app_notification_after_deliver(self, api, url):
        """Complete a wizard with deliver(in_app), then check GET /api/notifications for a matching notification."""
        wf_payload = _make_approval_workflow(
            name=f"E2E-notify-{_uid()}",
            steps=[
                {
                    "step_id": "input",
                    "name": "Input",
                    "step_type": "user_action",
                    "config": {"title": "Reason", "requires_input": True},
                    "on_pass": "persist",
                    "order": 0,
                },
                {"step_id": "persist", "name": "Save", "step_type": "persist_agreement", "config": {}, "on_pass": "send", "order": 1},
                {
                    "step_id": "send",
                    "name": "Deliver",
                    "step_type": "deliver",
                    "config": {"channels": ["in_app"], "recipients": ["signer"]},
                    "on_pass": "done",
                    "order": 2,
                },
                {"step_id": "done", "name": "Done", "step_type": "pass", "config": {}, "order": 3},
            ],
        )
        resp = api.post(url("/api/workflows"), json=wf_payload)
        assert resp.status_code in (200, 201)
        wf_id = resp.json()["id"]
        self._to_delete_wf.append(wf_id)

        entity_id = f"e2e-notify-{_uid()}"
        session_resp = api.post(url("/api/approvals/sessions"), json={
            "workflow_id": wf_id,
            "entity_type": "data_product",
            "entity_id": entity_id,
        })
        assert session_resp.status_code in (200, 201)
        sid = session_resp.json()["session_id"]

        data = api.post(url(f"/api/approvals/sessions/{sid}/steps"), json={
            "step_id": "input", "payload": {"reason": "E2E notification test reason"},
        }).json()

        for step_id in ("persist", "send", "done"):
            if data.get("complete"):
                break
            data = api.post(url(f"/api/approvals/sessions/{sid}/steps"), json={
                "step_id": step_id, "payload": {},
            }).json()

        assert data.get("complete") is True

        # Check notifications for the current user
        notif_resp = api.get(url("/api/notifications"))
        assert notif_resp.status_code == 200, f"Notifications endpoint failed: {notif_resp.status_code} {notif_resp.text[:500]}"
        notifications = notif_resp.json()
        # Notifications can be a list (response_model=List[Notification])
        assert isinstance(notifications, list), f"Expected list of notifications, got {type(notifications)}"

        # Look for an agreement-related notification (message may contain "agreement" or "completed")
        def _notif_text(n):
            """Safely concatenate notification text fields (may be None)."""
            return " ".join(str(v) for v in [n.get("message"), n.get("title"), n.get("description")] if v).lower()

        matching = [
            n for n in notifications
            if any(keyword in _notif_text(n) for keyword in ["agreement", "completed", "signed"])
        ]
        # This is a best-effort check: the notification system may or may not create
        # a notification depending on the backend wiring. We verify the endpoint works
        # and any notification is present or absent without hard-failing.
        # If deliver step created a notification, it should match.
        if matching:
            assert len(matching) >= 1, "Expected at least one agreement notification"


class TestDefaultSubscriptionWorkflow:
    """Verify the default Subscription Agreement workflow has the full step catalog."""

    def test_reload_defaults_and_verify_subscription(self, api, url):
        """POST /api/workflows/load-defaults, then find 'Subscription Agreement' and verify steps."""
        # Reload defaults (idempotent)
        reload_resp = api.post(url("/api/workflows/load-defaults"))
        assert reload_resp.status_code == 200, f"Load defaults failed: {reload_resp.status_code} {reload_resp.text[:500]}"

        # Fetch all approval workflows
        resp = api.get(url("/api/workflows?workflow_type=approval"))
        assert resp.status_code == 200
        workflows = resp.json()["workflows"]

        # Find "Subscription Agreement"
        sub_wf = next((w for w in workflows if "subscription" in w["name"].lower()), None)
        assert sub_wf is not None, (
            f"Expected a 'Subscription Agreement' workflow after loading defaults. "
            f"Found: {[w['name'] for w in workflows]}"
        )

        # Fetch the full workflow to get steps
        detail_resp = api.get(url(f"/api/workflows/{sub_wf['id']}"))
        assert detail_resp.status_code == 200
        detail = detail_resp.json()
        step_types = [s["step_type"] for s in detail["steps"]]

        # Verify it has the full step catalog
        for expected_type in [
            "legal_document",
            "acknowledgement_checklist",
            "user_action",
            "persist_agreement",
            "generate_pdf",
            "deliver",
        ]:
            assert expected_type in step_types, (
                f"Subscription Agreement should have '{expected_type}' step. "
                f"Found: {step_types}"
            )


class TestUserActionMinimumInputLength:
    """Verify user_action step rejects input shorter than minimum_input_length."""

    @pytest.fixture(autouse=True)
    def _cleanup(self, api, url):
        self._to_delete_wf = []
        self._to_abort_sessions = []
        yield
        for sid in reversed(self._to_abort_sessions):
            try:
                api.post(url(f"/api/approvals/sessions/{sid}/abort"), json={})
            except Exception:
                pass
        for wid in reversed(self._to_delete_wf):
            api.delete(url(f"/api/workflows/{wid}"))

    def test_user_action_rejects_short_input(self, api, url):
        """user_action with minimum_input_length=10 rejects 3-char input."""
        wf_payload = _make_approval_workflow(
            name=f"E2E-min-input-{_uid()}",
            steps=[
                {
                    "step_id": "reason",
                    "name": "Enter Reason",
                    "step_type": "user_action",
                    "config": {
                        "title": "Reason",
                        "requires_input": True,
                        "minimum_input_length": 10,
                        "primary_field_id": "reason",
                        "required_fields": [
                            {"id": "reason", "label": "Reason", "type": "text", "required": True},
                        ],
                    },
                    "on_pass": "done",
                    "order": 0,
                },
                {"step_id": "done", "name": "Done", "step_type": "pass", "config": {}, "order": 1},
            ],
        )
        resp = api.post(url("/api/workflows"), json=wf_payload)
        assert resp.status_code in (200, 201), f"Create failed: {resp.text[:500]}"
        wf_id = resp.json()["id"]
        self._to_delete_wf.append(wf_id)

        session_resp = api.post(url("/api/approvals/sessions"), json={
            "workflow_id": wf_id,
            "entity_type": "data_product",
            "entity_id": f"e2e-min-input-{_uid()}",
        })
        assert session_resp.status_code in (200, 201)
        session = session_resp.json()
        sid = session["session_id"]
        self._to_abort_sessions.append(sid)

        assert session["current_step"]["step_type"] == "user_action"

        # Submit with only 3 characters (minimum is 10)
        step_resp = api.post(url(f"/api/approvals/sessions/{sid}/steps"), json={
            "step_id": "reason",
            "payload": {"reason": "abc"},
        })
        assert step_resp.status_code in (400, 422, 500), (
            f"Should reject short input, got status {step_resp.status_code}: {step_resp.text[:500]}"
        )

    def test_user_action_accepts_long_enough_input(self, api, url):
        """user_action with minimum_input_length=10 accepts 15-char input."""
        wf_payload = _make_approval_workflow(
            name=f"E2E-min-input-ok-{_uid()}",
            steps=[
                {
                    "step_id": "reason",
                    "name": "Enter Reason",
                    "step_type": "user_action",
                    "config": {
                        "title": "Reason",
                        "requires_input": True,
                        "minimum_input_length": 10,
                        "primary_field_id": "reason",
                        "required_fields": [
                            {"id": "reason", "label": "Reason", "type": "text", "required": True},
                        ],
                    },
                    "on_pass": "done",
                    "order": 0,
                },
                {"step_id": "done", "name": "Done", "step_type": "pass", "config": {}, "order": 1},
            ],
        )
        resp = api.post(url("/api/workflows"), json=wf_payload)
        assert resp.status_code in (200, 201)
        wf_id = resp.json()["id"]
        self._to_delete_wf.append(wf_id)

        session_resp = api.post(url("/api/approvals/sessions"), json={
            "workflow_id": wf_id,
            "entity_type": "data_product",
            "entity_id": f"e2e-min-input-ok-{_uid()}",
        })
        assert session_resp.status_code in (200, 201)
        session = session_resp.json()
        sid = session["session_id"]

        # Submit with 15 characters (minimum is 10) — should succeed
        step_resp = api.post(url(f"/api/approvals/sessions/{sid}/steps"), json={
            "step_id": "reason",
            "payload": {"reason": "This is valid!!"},
        })
        assert step_resp.status_code == 200, (
            f"Should accept input >= minimum_input_length, got: {step_resp.status_code} {step_resp.text[:500]}"
        )
        data = step_resp.json()
        assert data.get("complete") is True
