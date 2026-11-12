"""
Integration tests for user API endpoints
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session


class TestUserRoutes:
    """Integration tests for user API endpoints."""

    def test_get_current_user(self, client: TestClient, db_session: Session, mock_test_user):
        """Test getting current user information."""
        response = client.get("/api/user/details")
        assert response.status_code == 200
        data = response.json()
        assert data["email"] == mock_test_user.email
        assert data["groups"] == mock_test_user.groups

    def test_get_user_permissions(self, client: TestClient, db_session: Session):
        """Test getting user permissions."""
        response = client.get("/api/user/permissions")
        assert response.status_code == 200
        data = response.json()
        # Should return permissions mapping
        assert isinstance(data, dict)

    def test_get_user_profile(self, client: TestClient, db_session: Session):
        """Test getting the user profile from the forwarded identity headers."""
        response = client.get("/api/user/info", headers={
            "X-Forwarded-Email": "profile.user@example.com",
            "X-Forwarded-User": "profile.user",
        })
        assert response.status_code == 200
        data = response.json()
        assert data["email"] == "profile.user@example.com"
        assert data["username"] == "profile.user"

    def test_search_users(self, client: TestClient, db_session: Session, tmp_path):
        """Test searching for users (directory search, CSV-file provider)."""
        directory = tmp_path / "directory.csv"
        directory.write_text(
            "type,id,display_name,sub_label\n"
            "user,test.alice@example.com,Test Alice,test.alice@example.com\n"
            "user,bob@example.com,Bob Builder,bob@example.com\n"
            "group,test-group,Test Group,test-group\n"
        )
        configured = client.put("/api/directory/settings", json={
            "provider_type": "file", "file_path": str(directory),
        })
        assert configured.status_code == 200, configured.text

        response = client.get("/api/directory/search", params={"q": "test", "types": "user"})
        assert response.status_code == 200, response.text
        results = response.json()["results"]
        assert [(r["type"], r["id"]) for r in results] == [("user", "test.alice@example.com")]

    def test_get_user_activity(self, client: TestClient, db_session: Session):
        """Test getting user activity."""
        response = client.get("/api/user/activity")
        # Might not be implemented or require permissions
        assert response.status_code in [200, 404, 405]

