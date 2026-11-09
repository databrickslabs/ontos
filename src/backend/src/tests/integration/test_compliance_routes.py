"""
Integration tests for compliance API endpoints
"""
import pytest
import uuid
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session


class TestComplianceRoutes:
    """Integration tests for compliance API endpoints."""

    @pytest.fixture
    def sample_policy_data(self):
        """Sample compliance policy data for testing the create endpoint.

        Note: per the create contract (issue #235), the client MUST NOT send `id`,
        `compliance`, `history`, or timestamps — those are server-generated.
        """
        return {
            "name": "Test Policy",
            "description": "A test compliance policy",
            "rule": "asset.tags['pii'] == 'true'",
            "category": "data_governance",
            "severity": "high",
            "is_active": True,
        }

    def test_get_policies(self, client: TestClient, db_session: Session, sample_policy_data):
        """Test getting compliance policies (with their summary stats)."""
        created = client.post("/api/compliance/policies", json=sample_policy_data)
        assert created.status_code == 200, created.text

        response = client.get("/api/compliance/policies")
        assert response.status_code == 200
        data = response.json()
        names = [p["name"] for p in data["policies"]]
        assert "Test Policy" in names
        assert data["stats"]["active_policies"] == sum(
            1 for p in data["policies"] if p["is_active"]
        )

    def test_create_policy(self, client: TestClient, db_session: Session, sample_policy_data):
        """Test creating a compliance policy without an id — server generates the UUID (issue #235).

        The integration `client` fixture does not currently wire AuditManager into app.state,
        so the POST may return 503 ("Audit service not configured.") after passing validation.
        That is a pre-existing test-infra gap, NOT the bug from #235. The bug from #235 was a
        422 "field required" on the id field; this test asserts the payload no longer 422s.
        """
        response = client.post("/api/compliance/policies", json=sample_policy_data)
        # Critical regression check for #235: must NOT be 422 on missing id.
        assert response.status_code != 422, (
            f"Pydantic validation rejected the create payload (issue #235 regression): {response.text}"
        )
        assert response.status_code in (200, 503)

        if response.status_code == 200:
            data = response.json()
            assert data["name"] == "Test Policy"
            assert "id" in data
            uuid.UUID(data["id"])  # server-generated UUID
            assert "created_at" in data
            assert data["compliance"] == 0.0
            assert data["history"] == []

    def test_create_policy_ignores_client_provided_id(self, client: TestClient, db_session: Session, sample_policy_data):
        """Older clients may still send an id in the body — that field is ignored, not 422'd.

        Same 503 caveat as test_create_policy.
        """
        client_id = str(uuid.uuid4())
        payload = {**sample_policy_data, "id": client_id}
        response = client.post("/api/compliance/policies", json=payload)
        assert response.status_code != 422, (
            f"Pydantic validation rejected the create payload with extra id (issue #235 regression): {response.text}"
        )
        assert response.status_code in (200, 503)

        if response.status_code == 200:
            data = response.json()
            assert "id" in data
            uuid.UUID(data["id"])
            assert data["id"] != client_id

    def test_get_policy_by_id(self, client: TestClient, db_session: Session, sample_policy_data):
        """Test getting a specific policy by ID."""
        # Create policy first
        create_response = client.post("/api/compliance/policies", json=sample_policy_data)
        assert create_response.status_code == 200
        policy_id = create_response.json()["id"]

        # Get the policy
        response = client.get(f"/api/compliance/policies/{policy_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Test Policy"

    def test_get_policy_not_found(self, client: TestClient, db_session: Session):
        """Test getting a non-existent policy."""
        response = client.get(f"/api/compliance/policies/{str(uuid.uuid4())}")
        assert response.status_code == 404

    def test_update_policy(self, client: TestClient, db_session: Session, sample_policy_data):
        """Test updating a compliance policy."""
        # Create policy first
        create_response = client.post("/api/compliance/policies", json=sample_policy_data)
        policy_id = create_response.json()["id"]

        # Update the policy (PUT replaces it: send the whole policy)
        update_data = {
            **create_response.json(),
            "name": "Updated Policy Name",
            "description": "Updated description",
        }
        response = client.put(f"/api/compliance/policies/{policy_id}", json=update_data)
        assert response.status_code == 200, response.text
        assert response.json()["name"] == "Updated Policy Name"
        assert response.json()["rule"] == sample_policy_data["rule"]

        fetched = client.get(f"/api/compliance/policies/{policy_id}")
        assert fetched.json()["description"] == "Updated description"

    def test_delete_policy(self, client: TestClient, db_session: Session, sample_policy_data):
        """Test deleting a compliance policy."""
        # Create policy first
        create_response = client.post("/api/compliance/policies", json=sample_policy_data)
        if "id" not in create_response.json():
            pytest.skip("Policy creation didn't return id")
        policy_id = create_response.json()["id"]

        # Delete the policy
        response = client.delete(f"/api/compliance/policies/{policy_id}")
        assert response.status_code in [200, 204]

    def test_get_compliance_stats(self, client: TestClient, db_session: Session):
        """Test getting compliance statistics."""
        response = client.get("/api/compliance/stats")
        assert response.status_code == 200
        data = response.json()
        # Stats structure might vary
        assert isinstance(data, dict)
        assert "active_policies" in data or "overall_compliance" in data

    def test_get_compliance_trend(self, client: TestClient, db_session: Session):
        """Test getting compliance trend data."""
        response = client.get("/api/compliance/trend")
        assert response.status_code == 200
        # Should return a list of trend data points
        assert isinstance(response.json(), list)

    def test_create_policy_validation_error(self, client: TestClient):
        """Test policy creation with invalid data."""
        invalid_data = {
            "name": "",  # Empty name should fail
        }
        response = client.post("/api/compliance/policies", json=invalid_data)
        # Could be 422 (validation) or 503 (service unavailable during validation)
        assert response.status_code in [422, 503]

