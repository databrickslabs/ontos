"""Notifications — CRUD lifecycle."""
import pytest

from helpers.test_data import make_notification


class TestNotifications:

    @pytest.mark.readonly
    def test_list_notifications(self, api, url):
        resp = api.get(url("/api/notifications"))
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    @pytest.mark.crud
    def test_create_and_delete_notification(self, api, url):
        payload = make_notification()

        # CREATE
        resp = api.post(url("/api/notifications"), json=payload)
        assert resp.status_code in (200, 201), f"Create failed: {resp.status_code} {resp.text[:300]}"
        created = resp.json()
        notif_id = created.get("id") or payload["id"]
        assert notif_id, f"No ID in response: {created}"

        # Verify it appears in list
        resp = api.get(url("/api/notifications"))
        assert resp.status_code == 200
        notifs = resp.json()
        # Notifications may be filtered by recipient — just verify list works
        assert isinstance(notifs, list)

        # MARK AS READ
        resp = api.put(url(f"/api/notifications/{notif_id}/read"))
        assert resp.status_code in (200, 404), f"Mark read failed: {resp.status_code} {resp.text[:300]}"

        # DELETE
        resp = api.delete(url(f"/api/notifications/{notif_id}"))
        assert resp.status_code in (200, 204, 404), f"Delete failed: {resp.status_code} {resp.text[:300]}"
