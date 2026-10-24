"""
Integration tests for costs API endpoints
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from src.models.costs import CostItemCreate
from src.repositories.costs_repository import cost_items_repo


def _cost_items_url(entity_type: str, entity_id: str) -> str:
    return f"/api/entities/{entity_type}/{entity_id}/cost-items"


class TestCostsRoutes:
    """Integration tests for costs API endpoints."""

    @pytest.fixture
    def sample_cost_data(self):
        """Sample cost item data for testing."""
        return {
            "entity_type": "data_product",
            "entity_id": "test-product-123",
            "title": "Monthly Storage Cost",
            "description": "Storage costs for data product",
            "cost_center": "INFRASTRUCTURE",
            "amount_cents": 150000,  # $1500.00
            "currency": "USD",
            "start_month": "2024-01-01",
        }

    @pytest.fixture
    def created_cost(self, db_session: Session, sample_cost_data):
        """A cost item stored through the repository.

        Not through POST: that route's audit entry fails to serialise (#1051) and,
        in this harness, the failed audit write rolls back the test's data.
        """
        item = cost_items_repo.create(db_session, obj_in=CostItemCreate(**sample_cost_data))
        db_session.flush()
        return {"id": str(item.id)}

    def test_create_cost_item_is_audited(
        self, client: TestClient, sample_cost_data, verify_audit_log
    ):
        """Creating a cost item writes a successful CREATE entry to the audit trail."""
        response = client.post(
            _cost_items_url("data_product", "test-product-123"), json=sample_cost_data
        )
        assert response.status_code == 201
        verify_audit_log("costs", "CREATE", success=True)

    def test_get_costs_for_entity(self, client: TestClient, created_cost):
        """Test getting costs for an entity."""
        response = client.get(_cost_items_url("data_product", "test-product-123"))
        assert response.status_code == 200
        data = response.json()
        assert [item["id"] for item in data] == [created_cost["id"]]

        other = client.get(_cost_items_url("data_product", "another-product"))
        assert other.status_code == 200
        assert other.json() == []

    def test_create_cost_item(self, client: TestClient, db_session: Session, sample_cost_data):
        """Test creating a cost item."""
        response = client.post(
            _cost_items_url("data_product", "test-product-123"), json=sample_cost_data
        )
        assert response.status_code == 201
        data = response.json()
        assert "id" in data
        assert data["amount_cents"] == 150000
        assert data["cost_center"] == "INFRASTRUCTURE"

    def test_update_cost_item(self, client: TestClient, created_cost):
        """Test updating a cost item."""
        update_data = {
            "amount_cents": 200000,
            "description": "Updated description",
        }
        response = client.put(f"/api/cost-items/{created_cost['id']}", json=update_data)
        assert response.status_code == 200
        assert response.json()["amount_cents"] == 200000
        assert response.json()["description"] == "Updated description"

    def test_delete_cost_item(self, client: TestClient, created_cost):
        """Test deleting a cost item."""
        response = client.delete(f"/api/cost-items/{created_cost['id']}")
        assert response.status_code == 204

        remaining = client.get(_cost_items_url("data_product", "test-product-123"))
        assert remaining.json() == []

    def test_get_cost_summary(self, client: TestClient, created_cost):
        """Test getting cost summary for entity."""
        response = client.get(
            _cost_items_url("data_product", "test-product-123") + "/summary?month=2024-01"
        )
        assert response.status_code == 200
        summary = response.json()
        assert summary["month"] == "2024-01"
        assert summary["total_cents"] == 150000
        assert summary["items_count"] == 1
        assert summary["by_center"] == {"INFRASTRUCTURE": 150000}

    def test_create_cost_validation_error(self, client: TestClient):
        """Test cost creation with invalid data."""
        invalid_data = {
            "amount_cents": "not_a_number",
        }
        response = client.post(
            _cost_items_url("data_product", "test-product-123"), json=invalid_data
        )
        assert response.status_code == 422
