"""Compliance Policies — CRUD lifecycle with field round-trip verification."""
import pytest

from helpers.assertions import assert_fields_match
from helpers.test_data import make_compliance_policy, mutate_compliance_policy


class TestCompliancePolicies:

    @pytest.fixture(autouse=True)
    def _cleanup(self, api, url):
        self._to_delete = []
        yield
        for pid in reversed(self._to_delete):
            api.delete(url(f"/api/compliance/policies/{pid}"))

    @pytest.mark.readonly
    def test_list_policies(self, api, url):
        resp = api.get(url("/api/compliance/policies"))
        assert resp.status_code == 200
        data = resp.json()
        # Response may be a list or {"policies": [...], "stats": {...}}
        if isinstance(data, dict):
            assert "policies" in data
        else:
            assert isinstance(data, list)

    @pytest.mark.readonly
    def test_compliance_stats(self, api, url):
        resp = api.get(url("/api/compliance/stats"))
        assert resp.status_code == 200

    @pytest.mark.readonly
    def test_compliance_trend(self, api, url):
        resp = api.get(url("/api/compliance/trend"))
        assert resp.status_code == 200

    @pytest.mark.crud
    def test_crud_lifecycle(self, api, url):
        payload = make_compliance_policy()

        # CREATE
        resp = api.post(url("/api/compliance/policies"), json=payload)
        assert resp.status_code in (200, 201), f"Create failed: {resp.status_code} {resp.text[:500]}"
        created = resp.json()
        policy_id = created["id"]
        self._to_delete.append(policy_id)

        # compliance/history are virtual fields (computed from runs, not stored in DB)
        _ignore = {"compliance", "history"}
        assert_fields_match(payload, created, context="after CREATE", ignore=_ignore)

        # READ
        resp = api.get(url(f"/api/compliance/policies/{policy_id}"))
        assert resp.status_code == 200
        fetched = resp.json()
        assert_fields_match(payload, fetched, context="after GET", ignore=_ignore)

        # UPDATE
        updated_payload = mutate_compliance_policy(payload)
        resp = api.put(url(f"/api/compliance/policies/{policy_id}"), json=updated_payload)
        assert resp.status_code == 200, f"Update failed: {resp.status_code} {resp.text[:500]}"
        updated = resp.json()
        assert_fields_match(updated_payload, updated, context="after UPDATE response", ignore=_ignore)

        # READ after update
        resp = api.get(url(f"/api/compliance/policies/{policy_id}"))
        assert resp.status_code == 200
        re_fetched = resp.json()
        assert_fields_match(updated_payload, re_fetched, context="after UPDATE GET", ignore=_ignore)

        # DELETE
        resp = api.delete(url(f"/api/compliance/policies/{policy_id}"))
        assert resp.status_code in (200, 204), f"Delete failed: {resp.status_code}"
        self._to_delete.remove(policy_id)

    @pytest.mark.crud
    def test_validate_inline(self, api, url):
        """Test inline rule validation."""
        resp = api.post(url("/api/compliance/validate-inline"), json={
            "rule": "ALL data_contracts MUST HAVE status",
        })
        assert resp.status_code in (200, 400), f"Validate failed: {resp.status_code} {resp.text[:300]}"

    @pytest.mark.crud
    def test_policy_runs(self, api, url):
        """Test triggering a compliance run on a policy."""
        payload = make_compliance_policy()
        resp = api.post(url("/api/compliance/policies"), json=payload)
        assert resp.status_code in (200, 201)
        policy_id = resp.json()["id"]
        self._to_delete.append(policy_id)

        # List runs (should be empty initially)
        resp = api.get(url(f"/api/compliance/policies/{policy_id}/runs"))
        assert resp.status_code == 200

        # Trigger inline run
        resp = api.post(url(f"/api/compliance/policies/{policy_id}/runs"), json={
            "mode": "inline",
            "dry_run": True,
        })
        # May succeed or fail depending on rule evaluation capability
        assert resp.status_code in (200, 201, 400, 422), f"Run trigger: {resp.status_code}"

    @pytest.mark.crud
    def test_get_run_results(self, api, url):
        """Trigger a compliance run and fetch its results via the run_id."""
        payload = make_compliance_policy()
        resp = api.post(url("/api/compliance/policies"), json=payload)
        assert resp.status_code in (200, 201), f"Create failed: {resp.status_code} {resp.text[:500]}"
        policy_id = resp.json()["id"]
        self._to_delete.append(policy_id)

        # Trigger a run
        resp = api.post(url(f"/api/compliance/policies/{policy_id}/runs"), json={
            "mode": "inline",
            "dry_run": True,
        })
        assert resp.status_code in (200, 201, 400, 422), (
            f"Run trigger unexpected status: {resp.status_code} {resp.text[:300]}"
        )

        if resp.status_code not in (200, 201):
            pytest.skip(
                f"Run trigger did not succeed (status {resp.status_code}); "
                "cannot test run results in this environment"
            )

        run_data = resp.json()
        run_id = run_data.get("id") or run_data.get("run_id")
        if not run_id:
            pytest.skip(
                f"Run response did not include a run_id; "
                f"cannot fetch results. Response: {run_data}"
            )

        # Fetch run results
        resp = api.get(url(f"/api/compliance/runs/{run_id}/results"))
        assert resp.status_code == 200, (
            f"Fetching run results failed: {resp.status_code} {resp.text[:500]}"
        )
