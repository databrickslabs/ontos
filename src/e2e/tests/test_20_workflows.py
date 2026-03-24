"""Workflows — CRUD lifecycle with field round-trip verification."""
import pytest

from helpers.assertions import assert_fields_match
from helpers.test_data import make_workflow, mutate_workflow


class TestWorkflows:

    @pytest.fixture(autouse=True)
    def _cleanup(self, api, url):
        self._to_delete = []
        yield
        for wid in reversed(self._to_delete):
            api.delete(url(f"/api/workflows/{wid}"))

    @pytest.mark.readonly
    def test_list_workflows(self, api, url):
        resp = api.get(url("/api/workflows"))
        assert resp.status_code == 200
        data = resp.json()
        # Response may be a list or {"total": N, "workflows": [...]}
        if isinstance(data, dict):
            assert "workflows" in data
        else:
            assert isinstance(data, list)

    @pytest.mark.readonly
    def test_step_types(self, api, url):
        resp = api.get(url("/api/workflows/step-types"))
        assert resp.status_code == 200

    @pytest.mark.readonly
    def test_list_executions(self, api, url):
        resp = api.get(url("/api/workflows/executions"))
        assert resp.status_code == 200

    @pytest.mark.crud
    def test_crud_lifecycle(self, api, url):
        payload = make_workflow()

        # CREATE
        resp = api.post(url("/api/workflows"), json=payload)
        assert resp.status_code in (200, 201), f"Create failed: {resp.status_code} {resp.text[:500]}"
        created = resp.json()
        wf_id = created["id"]
        self._to_delete.append(wf_id)

        assert_fields_match(payload, created, context="after CREATE",
                           ignore={"steps"})  # steps get server-side IDs

        # READ
        resp = api.get(url(f"/api/workflows/{wf_id}"))
        assert resp.status_code == 200
        fetched = resp.json()
        assert fetched["name"] == payload["name"]
        assert fetched["description"] == payload["description"]

        # UPDATE
        updated_payload = mutate_workflow(payload)
        resp = api.put(url(f"/api/workflows/{wf_id}"), json=updated_payload)
        assert resp.status_code == 200, f"Update failed: {resp.status_code} {resp.text[:500]}"
        updated = resp.json()
        assert updated["name"] == updated_payload["name"]

        # READ after update
        resp = api.get(url(f"/api/workflows/{wf_id}"))
        assert resp.status_code == 200
        re_fetched = resp.json()
        assert re_fetched["name"] == updated_payload["name"]
        assert re_fetched["description"] == updated_payload["description"]

        # DELETE
        resp = api.delete(url(f"/api/workflows/{wf_id}"))
        assert resp.status_code in (200, 204), f"Delete failed: {resp.status_code}"
        self._to_delete.remove(wf_id)

    @pytest.mark.crud
    def test_toggle_active(self, api, url):
        """Test toggling workflow active state."""
        payload = make_workflow(is_active=False)
        resp = api.post(url("/api/workflows"), json=payload)
        assert resp.status_code in (200, 201)
        wf_id = resp.json()["id"]
        self._to_delete.append(wf_id)

        # Toggle to active
        resp = api.post(url(f"/api/workflows/{wf_id}/toggle-active"), params={"is_active": True})
        assert resp.status_code == 200, f"Toggle failed: {resp.status_code} {resp.text[:300]}"

        # Verify
        resp = api.get(url(f"/api/workflows/{wf_id}"))
        assert resp.status_code == 200
        assert resp.json().get("is_active") is True

    @pytest.mark.crud
    def test_duplicate(self, api, url):
        """Test duplicating a workflow."""
        payload = make_workflow()
        resp = api.post(url("/api/workflows"), json=payload)
        assert resp.status_code in (200, 201)
        wf_id = resp.json()["id"]
        self._to_delete.append(wf_id)

        # Duplicate
        new_name = f"e2e-test-dup-{payload['name']}"
        resp = api.post(url(f"/api/workflows/{wf_id}/duplicate"), params={"new_name": new_name})
        assert resp.status_code in (200, 201), f"Duplicate failed: {resp.status_code} {resp.text[:300]}"
        dup = resp.json()
        self._to_delete.append(dup["id"])
        assert dup["name"] == new_name

    @pytest.mark.crud
    def test_validate_workflow(self, api, url):
        """POST /api/workflows/validate with a valid payload returns 200."""
        payload = make_workflow()
        resp = api.post(url("/api/workflows/validate"), json=payload)
        assert resp.status_code == 200, f"Validate failed: {resp.status_code} {resp.text[:300]}"
        data = resp.json()
        # Response should at minimum indicate validity
        assert "valid" in data

    @pytest.mark.readonly
    def test_list_compliance_policies(self, api, url):
        """GET /api/workflows/compliance-policies returns 200 and a list."""
        resp = api.get(url("/api/workflows/compliance-policies"))
        assert resp.status_code == 200, f"List compliance policies failed: {resp.status_code} {resp.text[:300]}"
        data = resp.json()
        assert isinstance(data, list)

    @pytest.mark.readonly
    def test_list_workflow_roles(self, api, url):
        """GET /api/workflows/roles returns 200 and a list."""
        resp = api.get(url("/api/workflows/roles"))
        assert resp.status_code == 200, f"List workflow roles failed: {resp.status_code} {resp.text[:300]}"
        data = resp.json()
        assert isinstance(data, list)

    @pytest.mark.readonly
    def test_list_http_connections(self, api, url):
        """GET /api/workflows/http-connections returns 200 and a list."""
        resp = api.get(url("/api/workflows/http-connections"))
        assert resp.status_code == 200, f"List HTTP connections failed: {resp.status_code} {resp.text[:300]}"
        data = resp.json()
        assert isinstance(data, list)

    @pytest.mark.crud
    def test_execute_workflow(self, api, url):
        """Create an active workflow, execute it, and capture execution_id."""
        payload = make_workflow(is_active=False)
        resp = api.post(url("/api/workflows"), json=payload)
        assert resp.status_code in (200, 201), f"Create failed: {resp.status_code} {resp.text[:300]}"
        wf_id = resp.json()["id"]
        self._to_delete.append(wf_id)

        # Activate the workflow
        resp = api.post(url(f"/api/workflows/{wf_id}/toggle-active"), params={"is_active": True})
        assert resp.status_code == 200, f"Toggle failed: {resp.status_code} {resp.text[:300]}"

        # Execute using query params (entity is fake — tolerate 400/422)
        resp = api.post(
            url(f"/api/workflows/{wf_id}/execute"),
            params={"entity_type": "data_contract", "entity_id": "e2e-fake-id"},
        )
        if resp.status_code in (400, 422):
            pytest.skip(f"Execute rejected fake entity (expected): {resp.status_code} {resp.text[:200]}")
        assert resp.status_code == 200, f"Execute failed: {resp.status_code} {resp.text[:300]}"
        data = resp.json()
        assert "id" in data  # execution_id present in response

    @pytest.mark.readonly
    def test_get_execution_details(self, api, url):
        """Pick an existing execution and GET its details."""
        # Fetch the executions list first
        resp = api.get(url("/api/workflows/executions"))
        assert resp.status_code == 200
        data = resp.json()

        # Response may be {"executions": [...], "total": N} or a plain list
        if isinstance(data, dict):
            executions = data.get("executions", [])
        else:
            executions = data

        if not executions:
            pytest.skip("No workflow executions exist; skipping execution detail test")

        execution_id = executions[0]["id"]
        resp = api.get(url(f"/api/workflows/executions/{execution_id}"))
        assert resp.status_code == 200, f"Get execution details failed: {resp.status_code} {resp.text[:300]}"
        detail = resp.json()
        assert "id" in detail

    @pytest.mark.crud
    def test_get_referenced_policies(self, api, url):
        """Create a workflow with a policy_check step, verify referenced-policies endpoint."""
        payload = make_workflow(
            steps=[
                {
                    "step_id": "step-policy",
                    "name": "E2E Policy Check Step",
                    "step_type": "policy_check",
                    "config": {
                        # Use a non-existent policy_id — endpoint still returns 200 with empty list
                        "policy_id": "e2e-nonexistent-policy-id",
                    },
                    "on_failure": "pass",
                }
            ]
        )
        resp = api.post(url("/api/workflows"), json=payload)
        assert resp.status_code in (200, 201), f"Create failed: {resp.status_code} {resp.text[:300]}"
        wf_id = resp.json()["id"]
        self._to_delete.append(wf_id)

        resp = api.get(url(f"/api/workflows/{wf_id}/referenced-policies"))
        assert resp.status_code == 200, f"Referenced policies failed: {resp.status_code} {resp.text[:300]}"
        data = resp.json()
        assert "workflow_id" in data
        assert "policies" in data
        assert isinstance(data["policies"], list)
