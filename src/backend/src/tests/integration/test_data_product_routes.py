"""
Integration tests for Data Product API Routes

Tests end-to-end API functionality including:
- HTTP request/response handling
- Authorization and permissions
- Audit logging
- Database persistence
- Manager integration
"""
import pytest
import json
import uuid
from fastapi.testclient import TestClient

from src.models.data_products import DataProduct


class TestDataProductRoutes:
    """Integration test suite for /api/data-products endpoints"""

    @pytest.fixture
    def sample_product_data(self):
        """Sample data product payload for API requests."""
        return {
            "id": str(uuid.uuid4()),
            "name": "API Test Product",
            "description": {"purpose": "Test product via API"},
            "version": "1.0.0",
            "productType": "sourceAligned",
            "owner": "test@example.com",
            "tags": ["api-test"],
        }

    # =================================================================
    # GET /api/data-products - List Products
    # =================================================================

    def test_list_products_success(self, client, db_session, sample_product_data):
        """Test GET /api/data-products returns all products."""
        # Arrange - Create test products
        client.post("/api/data-products", json=sample_product_data)

        # Act
        response = client.get("/api/data-products")

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) > 0

    def test_list_products_empty(self, client):
        """Test listing products when none exist."""
        # Act
        response = client.get("/api/data-products")

        # Assert
        assert response.status_code == 200
        assert response.json() == []

    def test_list_products_requires_permission(self, client, mock_test_user):
        """Test that listing requires READ_ONLY permission."""
        # Arrange - Remove all permissions
        mock_test_user.groups = []

        # Act
        response = client.get("/api/data-products")

        # Assert
        assert response.status_code == 403

    # =================================================================
    # POST /api/data-products - Create Product
    # =================================================================

    def test_create_product_success(
        self, client, db_session, sample_product_data, verify_audit_log
    ):
        """Test POST /api/data-products creates new product."""
        # Act
        response = client.post("/api/data-products", json=sample_product_data)

        # Assert
        assert response.status_code == 201
        data = response.json()
        assert data["id"] == sample_product_data["id"]
        assert data["name"] == sample_product_data["name"]
        assert data["status"] == "draft"  # Default status

        # Verify audit log
        verify_audit_log("data-products", "CREATE", success=True)

    def test_create_product_without_id_generates_one(
        self, client, sample_product_data
    ):
        """Test that missing ID is auto-generated."""
        # Arrange
        del sample_product_data["id"]

        # Act
        response = client.post("/api/data-products", json=sample_product_data)

        # Assert
        assert response.status_code == 201
        data = response.json()
        assert "id" in data
        assert data["id"] is not None

    def test_create_product_validation_error(self, client):
        """Test that invalid data returns 422 validation error."""
        # Arrange
        invalid_data = {
            "name": "",  # Empty name
            "version": "1.0.0"
        }

        # Act
        response = client.post("/api/data-products", json=invalid_data)

        # Assert
        assert response.status_code == 422

    def test_create_product_duplicate_id(self, client, sample_product_data):
        """Test that duplicate ID returns 409 conflict."""
        # Arrange - Create first product
        client.post("/api/data-products", json=sample_product_data)

        # Act - Try to create duplicate
        response = client.post("/api/data-products", json=sample_product_data)

        # Assert
        assert response.status_code == 409
        assert "already exists" in response.json()["detail"]

    def test_create_product_requires_write_permission(
        self, client, mock_test_user, sample_product_data
    ):
        """Test that creation requires READ_WRITE permission."""
        # Arrange - Remove admin permissions
        mock_test_user.groups = []

        # Act
        response = client.post("/api/data-products", json=sample_product_data)

        # Assert
        assert response.status_code == 403

    # =================================================================
    # GET /api/data-products/{product_id} - Get Single Product
    # =================================================================

    def test_get_product_by_id_success(self, client, sample_product_data):
        """Test GET /api/data-products/{id} returns specific product."""
        # Arrange
        create_response = client.post("/api/data-products", json=sample_product_data)
        product_id = create_response.json()["id"]

        # Act
        response = client.get(f"/api/data-products/{product_id}")

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == product_id
        assert data["name"] == sample_product_data["name"]

    def test_get_product_by_id_not_found(self, client):
        """Test GET with non-existent ID returns 404."""
        # Act
        response = client.get("/api/data-products/nonexistent-id")

        # Assert
        assert response.status_code == 404

    # =================================================================
    # PUT /api/data-products/{product_id} - Update Product
    # =================================================================

    def test_update_product_success(
        self, client, db_session, sample_product_data, verify_audit_log
    ):
        """Test PUT /api/data-products/{id} updates product."""
        # Arrange - Create product
        create_response = client.post("/api/data-products", json=sample_product_data)
        product_id = create_response.json()["id"]

        update_data = sample_product_data.copy()
        update_data["name"] = "Updated Product Name"

        # Act
        response = client.put(f"/api/data-products/{product_id}", json=update_data)

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Updated Product Name"

        # Verify audit log
        verify_audit_log("data-products", "UPDATE", success=True)

    def test_update_product_not_found(self, client, sample_product_data):
        """Test updating non-existent product returns 404."""
        # Arrange
        sample_product_data["id"] = "nonexistent-id"

        # Act
        response = client.put(
            "/api/data-products/nonexistent-id",
            json=sample_product_data
        )

        # Assert
        assert response.status_code == 404

    def test_update_product_id_mismatch(self, client, sample_product_data):
        """Test that path ID must match body ID."""
        # Arrange
        create_response = client.post("/api/data-products", json=sample_product_data)
        product_id = create_response.json()["id"]

        update_data = sample_product_data.copy()
        update_data["id"] = "different-id"

        # Act
        response = client.put(f"/api/data-products/{product_id}", json=update_data)

        # Assert
        assert response.status_code == 400
        assert "mismatch" in response.json()["detail"].lower()

    def test_update_product_requires_write_permission(
        self, client, mock_test_user, sample_product_data
    ):
        """Test that update requires READ_WRITE permission."""
        # Arrange
        create_response = client.post("/api/data-products", json=sample_product_data)
        product_id = create_response.json()["id"]

        # Remove permissions
        mock_test_user.groups = []

        # Act
        response = client.put(
            f"/api/data-products/{product_id}",
            json=sample_product_data
        )

        # Assert
        assert response.status_code == 403

    # =================================================================
    # DELETE /api/data-products/{product_id} - Delete Product
    # =================================================================

    def test_delete_product_success(
        self, client, db_session, sample_product_data, verify_audit_log
    ):
        """Test DELETE /api/data-products/{id} removes product."""
        # Arrange
        create_response = client.post("/api/data-products", json=sample_product_data)
        product_id = create_response.json()["id"]

        # Act
        response = client.delete(f"/api/data-products/{product_id}")

        # Assert
        assert response.status_code == 204

        # Verify deletion
        get_response = client.get(f"/api/data-products/{product_id}")
        assert get_response.status_code == 404

        # Verify audit log
        verify_audit_log("data-products", "DELETE", success=True)

    def test_delete_product_not_found(self, client):
        """Test deleting non-existent product returns 404."""
        # Act
        response = client.delete("/api/data-products/nonexistent-id")

        # Assert
        assert response.status_code == 404

    def test_delete_product_requires_admin_permission(
        self, client, mock_test_user, sample_product_data
    ):
        """Test that deletion requires ADMIN permission."""
        # Arrange
        create_response = client.post("/api/data-products", json=sample_product_data)
        product_id = create_response.json()["id"]

        # Remove admin permission
        mock_test_user.groups = ["non_admin_group"]

        # Act
        response = client.delete(f"/api/data-products/{product_id}")

        # Assert
        assert response.status_code == 403

    # =================================================================
    # Lifecycle Endpoints
    # =================================================================

    def test_submit_certification_success(
        self, client, sample_product_data, verify_audit_log
    ):
        """Test POST /api/data-products/{id}/submit-certification."""
        # Arrange
        sample_product_data["status"] = "draft"
        create_response = client.post("/api/data-products", json=sample_product_data)
        product_id = create_response.json()["id"]

        # Act
        response = client.post(
            f"/api/data-products/{product_id}/submit-certification"
        )

        # Assert
        assert response.status_code == 200
        # Verify audit log
        verify_audit_log("data-products", "SUBMIT_CERTIFICATION", success=True)

    def test_request_certify_without_deliverable_fails(
        self, client, sample_product_data
    ):
        """ONT-CUJ-019 / ONT-NEG-008: requesting certification on a product
        with zero deliverables (output ports) must be blocked (409)."""
        sample_product_data["status"] = "draft"
        create_response = client.post("/api/data-products", json=sample_product_data)
        product_id = create_response.json()["id"]

        response = client.post(
            f"/api/data-products/{product_id}/request-certify",
            json={"certification_level": "gold"},
        )

        assert response.status_code == 409
        assert "deliverable" in response.json()["detail"].lower()

    def test_request_certify_with_deliverable_succeeds(
        self, client, sample_product_data
    ):
        """A product with at least one deliverable is accepted for
        certification (202)."""
        sample_product_data["status"] = "draft"
        sample_product_data["outputPorts"] = [{
            "name": "test-output",
            "version": "1.0.0",
            "contractId": "test-contract",
        }]
        create_response = client.post("/api/data-products", json=sample_product_data)
        product_id = create_response.json()["id"]

        response = client.post(
            f"/api/data-products/{product_id}/request-certify",
            json={"certification_level": "gold"},
        )

        assert response.status_code == 202

    def test_publish_product_success(self, client, sample_product_data):
        """Test POST /api/data-products/{id}/publish."""
        # Arrange
        sample_product_data["status"] = "proposed"
        sample_product_data["outputPorts"] = [{
            "name": "test-output",
            "version": "1.0.0",
            "contractId": "test-contract"
        }]
        create_response = client.post("/api/data-products", json=sample_product_data)
        product_id = create_response.json()["id"]

        # Act
        response = client.post(f"/api/data-products/{product_id}/publish")

        # Assert
        assert response.status_code == 200
        assert response.json()["status"] == "active"

    def test_publish_product_without_contracts_fails(
        self, client, sample_product_data
    ):
        """Test that publishing without contracts returns 400."""
        # Arrange
        sample_product_data["status"] = "proposed"
        create_response = client.post("/api/data-products", json=sample_product_data)
        product_id = create_response.json()["id"]

        # Act
        response = client.post(f"/api/data-products/{product_id}/publish")

        # Assert
        assert response.status_code == 400

    def test_deprecate_product_success(self, client, sample_product_data):
        """Test POST /api/data-products/{id}/deprecate."""
        # Arrange
        sample_product_data["status"] = "active"
        create_response = client.post("/api/data-products", json=sample_product_data)
        product_id = create_response.json()["id"]

        # Act
        response = client.post(f"/api/data-products/{product_id}/deprecate")

        # Assert
        assert response.status_code == 200
        assert response.json()["status"] == "deprecated"

    # =================================================================
    # Utility Endpoints
    # =================================================================

    def test_get_statuses(self, client):
        """Test GET /api/data-products/statuses returns all status values."""
        # Act
        response = client.get("/api/data-products/statuses")

        # Assert
        assert response.status_code == 200
        statuses = response.json()
        assert isinstance(statuses, list)
        assert "draft" in statuses
        assert "active" in statuses

    def test_get_types(self, client):
        """Test GET /api/data-products/types returns product types."""
        # Act
        response = client.get("/api/data-products/types")

        # Assert
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_get_owners(self, client, sample_product_data):
        """Test GET /api/data-products/owners returns distinct owners."""
        # Arrange - Create products with different owners
        for owner in ["owner1@test.com", "owner2@test.com"]:
            data = sample_product_data.copy()
            data["id"] = str(uuid.uuid4())
            data["owner"] = owner
            client.post("/api/data-products", json=data)

        # Act
        response = client.get("/api/data-products/owners")

        # Assert
        assert response.status_code == 200
        owners = response.json()
        assert "owner1@test.com" in owners
        assert "owner2@test.com" in owners

    def test_get_published_products(self, client, db_session):
        """GET /api/data-products/published returns products with publication_scope != none."""
        from src.db_models.data_products import DataProductDb

        for i, status in enumerate(["draft", "active", "active"]):
            data = {
                "id": str(uuid.uuid4()),
                "name": f"Product {i}",
                "version": "1.0.0",
                "productType": "sourceAligned",
                "status": status,
            }
            resp = client.post("/api/data-products", json=data)
            assert resp.status_code == 201
            if status == "active":
                pid = resp.json()["id"]
                row = db_session.get(DataProductDb, pid)
                row.publication_scope = "domain" if i == 1 else "organization"
                db_session.commit()

        response = client.get("/api/data-products/published")

        assert response.status_code == 200
        products = response.json()
        assert len(products) == 2
        scopes = {p.get("publication_scope") for p in products}
        assert scopes == {"domain", "organization"}

    def test_get_published_products_scope_query(self, client, db_session):
        """Optional scope query filters published products."""
        from src.db_models.data_products import DataProductDb

        for name, scope in [("ScopedA", "domain"), ("ScopedB", "external")]:
            data = {
                "id": str(uuid.uuid4()),
                "name": name,
                "version": "1.0.0",
                "productType": "sourceAligned",
                "status": "active",
            }
            resp = client.post("/api/data-products", json=data)
            assert resp.status_code == 201
            pid = resp.json()["id"]
            row = db_session.get(DataProductDb, pid)
            row.publication_scope = scope
            db_session.commit()

        r = client.get("/api/data-products/published?scope=domain")
        assert r.status_code == 200
        assert len(r.json()) == 1
        assert r.json()[0]["name"] == "ScopedA"

    # =================================================================
    # Contract Integration Endpoints
    # =================================================================

    def test_get_contracts_for_product(self, client, sample_product_data):
        """Test GET /api/data-products/{id}/contracts."""
        # Arrange
        sample_product_data["outputPorts"] = [
            {"name": "output1", "version": "1.0.0", "contractId": "contract-1"},
            {"name": "output2", "version": "1.0.0", "contractId": "contract-2"},
        ]
        create_response = client.post("/api/data-products", json=sample_product_data)
        product_id = create_response.json()["id"]

        # Act
        response = client.get(f"/api/data-products/{product_id}/contracts")

        # Assert
        assert response.status_code == 200
        contract_ids = response.json()
        assert "contract-1" in contract_ids
        assert "contract-2" in contract_ids

    # =================================================================
    # Error Scenarios
    # =================================================================

    def test_invalid_json_returns_400(self, client):
        """Test that malformed JSON returns 400."""
        # Act
        response = client.post(
            "/api/data-products",
            data="invalid json{",
            headers={"Content-Type": "application/json"}
        )

        # Assert
        assert response.status_code in [400, 422]

    def test_server_error_returns_500(self, client, sample_product_data, monkeypatch):
        """Test that unexpected errors return 500."""
        # This would require mocking the manager to raise an unexpected exception
        # Placeholder for more sophisticated error testing
        pass
