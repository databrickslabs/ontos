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

    def test_search_unknown_type_is_a_coded_400(self, client: TestClient, db_session: Session):
        """An unknown ``types`` value is rejected with a code, not exception text."""
        response = client.get("/api/search?search_term=test&types=not-a-type")
        assert response.status_code == 400
        detail = response.json()["detail"]
        assert detail["code"] == "search_unknown_type"
        assert detail["params"] == {"types": ["not-a-type"]}

    def test_search_known_type_filters_results(self, client: TestClient, db_session: Session):
        """A known ``types`` value returns only items of that type."""
        response = client.get("/api/search?search_term=test&types=data-product")
        assert response.status_code == 200
        assert all(i["type"] == "data-product" for i in response.json())
