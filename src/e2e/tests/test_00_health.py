"""Smoke tests — verify app is reachable and basic endpoints respond."""
import pytest


class TestHealth:

    @pytest.mark.smoke
    def test_health_endpoint(self, api, url):
        resp = api.get(url("/api/settings/health"))
        assert resp.status_code == 200

    @pytest.mark.smoke
    def test_features_endpoint(self, api, url):
        resp = api.get(url("/api/settings/features"))
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, (list, dict))

    @pytest.mark.smoke
    def test_user_info(self, api, url):
        resp = api.get(url("/api/user/info"))
        assert resp.status_code == 200
        body = resp.json()
        # Should have at least a username or email
        assert body.get("userName") or body.get("email") or body.get("displayName")

    @pytest.mark.smoke
    def test_user_permissions(self, api, url):
        resp = api.get(url("/api/user/permissions"))
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, (list, dict))

    @pytest.mark.smoke
    def test_user_actual_permissions(self, api, url):
        resp = api.get(url("/api/user/actual-permissions"))
        assert resp.status_code == 200
