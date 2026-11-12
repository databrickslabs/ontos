"""
Integration tests for search API endpoints
"""
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session


class TestSearchRoutes:
    """Integration tests for search API endpoints."""

    def test_search_empty_query(self, client: TestClient, db_session: Session):
        """An empty search term is rejected."""
        response = client.get("/api/search?search_term=")
        assert response.status_code == 400

    def test_search_without_query(self, client: TestClient, db_session: Session):
        """The search term is required."""
        response = client.get("/api/search")
        assert response.status_code == 422

    def test_search_with_query(self, client: TestClient, db_session: Session):
        """A search returns a list of index items."""
        response = client.get("/api/search?search_term=test")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_search_case_insensitive(self, client: TestClient, db_session: Session):
        """Upper and lower case terms find the same items."""
        response1 = client.get("/api/search?search_term=TEST")
        response2 = client.get("/api/search?search_term=test")

        assert response1.status_code == 200
        assert response2.status_code == 200
        assert response1.json() == response2.json()
