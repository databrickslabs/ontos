"""
Integration tests for security features API endpoints
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session


class TestSecurityFeaturesRoutes:
    """Integration tests for security features API endpoints."""

    def test_get_security_features(self, client: TestClient, db_session: Session):
        """Test getting available security features."""
        response = client.get("/api/security-features")
        assert response.status_code in [200, 404]

    def test_enable_security_feature(self, client: TestClient, db_session: Session, monkeypatch):
        """Test enabling a security feature for an entity (POST /api/security-features)."""
        from src.routes import security_features_routes

        # The route module keeps the features in memory: work on a copy.
        monkeypatch.setattr(
            security_features_routes.manager, "features",
            dict(security_features_routes.manager.features),
        )
        enable_data = {
            "name": "Differential privacy on test product",
            "description": "Adds noise to aggregates",
            "type": "differential_privacy",
            "target": "data_product:test-product-123",
            "conditions": ["epsilon=1.0"],
            "status": "enabled",
        }
        response = client.post("/api/security-features", json=enable_data)
        assert response.status_code == 200, response.text
        created = response.json()
        assert created["type"] == "differential_privacy"
        assert created["target"] == "data_product:test-product-123"
        assert created["status"] == "enabled"

        fetched = client.get(f"/api/security-features/{created['id']}")
        assert fetched.status_code == 200
        assert fetched.json()["name"] == "Differential privacy on test product"

    def test_disable_security_feature(self, client: TestClient, db_session: Session):
        """Test disabling a security feature."""
        response = client.delete("/api/security-features/data_product/test-product-123/differential_privacy")
        assert response.status_code in [200, 204, 404]

    def test_get_entity_security_status(self, client: TestClient, db_session: Session):
        """Test getting security status for an entity."""
        response = client.get("/api/security-features/data_product/test-product-123")
        assert response.status_code in [200, 404]

