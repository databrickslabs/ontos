"""User endpoints — all read-only, safe to run anytime."""
import pytest


class TestUserEndpoints:

    @pytest.mark.readonly
    def test_user_details(self, api, url):
        resp = api.get(url("/api/user/details"))
        assert resp.status_code == 200

    @pytest.mark.readonly
    def test_user_actual_role(self, api, url):
        resp = api.get(url("/api/user/actual-role"))
        assert resp.status_code == 200

    @pytest.mark.readonly
    def test_user_role_override(self, api, url):
        resp = api.get(url("/api/user/role-override"))
        assert resp.status_code == 200

    @pytest.mark.readonly
    def test_user_requestable_roles(self, api, url):
        resp = api.get(url("/api/user/requestable-roles"))
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    @pytest.mark.readonly
    def test_user_deployment_policy(self, api, url):
        resp = api.get(url("/api/user/deployment-policy"))
        assert resp.status_code == 200


class TestUserActions:

    @pytest.mark.readonly
    def test_user_teams(self, api, url):
        resp = api.get(url("/api/user/teams"))
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    @pytest.mark.readonly
    def test_user_projects(self, api, url):
        resp = api.get(url("/api/user/projects"))
        assert resp.status_code == 200
        data = resp.json()
        # Response is a dict with "projects" list and "current_project_id"
        if isinstance(data, dict):
            assert "projects" in data
            assert isinstance(data["projects"], list)
        else:
            assert isinstance(data, list)
