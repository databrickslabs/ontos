"""
Integration tests for notifications API endpoints
"""
import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session


def _notify(client: TestClient, title: str, recipient: str = "test@example.com") -> dict:
    """Create a notification for a recipient through the API."""
    response = client.post("/api/notifications", json={
        "id": str(uuid.uuid4()),
        "type": "info",
        "title": title,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "recipient": recipient,
    })
    assert response.status_code == 200, response.text
    return response.json()


class TestNotificationsRoutes:
    """Integration tests for notifications API endpoints."""

    def test_get_notifications(self, client: TestClient, db_session: Session):
        """Test getting notifications for current user."""
        response = client.get("/api/notifications")
        assert response.status_code == 200
        data = response.json()
        # Should return notifications structure
        assert isinstance(data, (list, dict))

    def test_get_unread_notifications(self, client: TestClient, db_session: Session):
        """Test getting unread notifications."""
        response = client.get("/api/notifications?unread_only=true")
        assert response.status_code == 200

    def test_mark_notification_as_read(self, client: TestClient, db_session: Session):
        """Test marking notification as read."""
        # Get notifications first
        get_response = client.get("/api/notifications")
        if get_response.status_code == 200:
            notifications = get_response.json()
            if isinstance(notifications, list) and len(notifications) > 0:
                notification_id = notifications[0].get("id")
                if notification_id:
                    # Mark as read
                    response = client.put(f"/api/notifications/{notification_id}/read")
                    assert response.status_code in [200, 204]

    def test_mark_all_as_read(self, client: TestClient, db_session: Session):
        """Marking each of the user's notifications read leaves none unread.

        The API has no bulk "mark all" route; the UI marks them one by one.
        """
        created = [_notify(client, f"Mark me {i}") for i in range(2)]

        for notification in created:
            response = client.put(f"/api/notifications/{notification['id']}/read")
            assert response.status_code == 200
            assert response.json()["read"] is True

        mine = {n["id"]: n for n in client.get("/api/notifications").json()}
        assert all(mine[n["id"]]["read"] for n in created)

    def test_get_notification_count(self, client: TestClient, db_session: Session):
        """The unread count is the number of unread notifications in the user's list.

        The API has no count route; it is derived from GET /api/notifications.
        """
        created = [_notify(client, f"Count me {i}") for i in range(3)]
        _notify(client, "Not for me", recipient="someone.else@example.com")
        client.put(f"/api/notifications/{created[0]['id']}/read").raise_for_status()

        response = client.get("/api/notifications")
        assert response.status_code == 200
        ours = [n for n in response.json() if n["title"].startswith(("Count me", "Not for me"))]
        assert sorted(n["title"] for n in ours) == ["Count me 0", "Count me 1", "Count me 2"]
        assert sum(1 for n in ours if not n["read"]) == 2

    def test_delete_notification(self, client: TestClient, db_session: Session):
        """Test deleting a notification."""
        # Get notifications first
        get_response = client.get("/api/notifications")
        if get_response.status_code == 200:
            notifications = get_response.json()
            if isinstance(notifications, list) and len(notifications) > 0:
                notification_id = notifications[0].get("id")
                if notification_id:
                    # Delete notification
                    response = client.delete(f"/api/notifications/{notification_id}")
                    assert response.status_code in [200, 204]

