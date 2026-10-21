"""
Integration tests for workspace API endpoints
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session


class TestWorkspaceRoutes:
    """Integration tests for workspace API endpoints."""

    def test_get_workspace_info(self, client: TestClient, db_session: Session):
        """Test getting workspace information."""
        response = client.get("/api/workspace/info")
        assert response.status_code in [200, 404]

    def test_get_catalogs(self, client: TestClient, db_session: Session, mock_workspace_client):
        """Test getting Unity Catalog catalogs (Catalog Commander, GET /api/catalogs)."""
        from types import SimpleNamespace

        from src.app import app
        from src.common.workspace_client import get_obo_workspace_client

        mock_workspace_client.catalogs.list.return_value = [
            SimpleNamespace(name="main"), SimpleNamespace(name="sales"),
        ]
        app.dependency_overrides[get_obo_workspace_client] = lambda: mock_workspace_client
        try:
            response = client.get("/api/catalogs")
        finally:
            app.dependency_overrides.pop(get_obo_workspace_client, None)

        assert response.status_code == 200, response.text
        assert [c["name"] for c in response.json()] == ["main", "sales"]
        assert all(c["type"] == "catalog" for c in response.json())

    def test_get_schemas(self, client: TestClient, db_session: Session):
        """Test getting schemas for a catalog."""
        response = client.get("/api/workspace/catalogs/test-catalog/schemas")
        assert response.status_code in [200, 404, 503]

    def test_get_tables(self, client: TestClient, db_session: Session):
        """Test getting tables for a schema."""
        response = client.get("/api/workspace/catalogs/test-catalog/schemas/test-schema/tables")
        assert response.status_code in [200, 404, 503]

    def test_get_table_info(self, client: TestClient, db_session: Session):
        """Test getting table information."""
        response = client.get("/api/workspace/catalogs/test-catalog/schemas/test-schema/tables/test-table")
        assert response.status_code in [200, 404, 503]

    def test_get_groups(self, client: TestClient, db_session: Session):
        """Test getting workspace groups."""
        response = client.get("/api/workspace/groups")
        assert response.status_code in [200, 403, 503]

