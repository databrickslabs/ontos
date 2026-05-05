"""Miscellaneous read-only endpoints — smoke tests for features that need external deps."""
import pytest


class TestMiscReadOnly:

    @pytest.mark.readonly
    def test_settings_features(self, api, url):
        resp = api.get(url("/api/settings/features"))
        assert resp.status_code == 200

    @pytest.mark.readonly
    def test_settings_roles(self, api, url):
        resp = api.get(url("/api/settings/roles"))
        assert resp.status_code == 200

    @pytest.mark.readonly
    def test_settings_roles_summary(self, api, url):
        resp = api.get(url("/api/settings/roles/summary"))
        assert resp.status_code == 200

    @pytest.mark.readonly
    def test_settings_health(self, api, url):
        resp = api.get(url("/api/settings/health"))
        assert resp.status_code == 200  # Health endpoint always returns 200 with status details

    @pytest.mark.readonly
    def test_settings_ui_customization(self, api, url):
        resp = api.get(url("/api/settings/ui-customization"))
        assert resp.status_code == 200

    @pytest.mark.readonly
    def test_settings_search_config(self, api, url):
        resp = api.get(url("/api/settings/search-config"))
        assert resp.status_code == 200

    @pytest.mark.readonly
    def test_database_schema(self, api, url):
        resp = api.get(url("/api/database-schema"))
        assert resp.status_code == 200

    @pytest.mark.readonly
    def test_user_docs(self, api, url):
        resp = api.get(url("/api/user-docs"))
        assert resp.status_code == 200

    @pytest.mark.readonly
    def test_user_guide(self, api, url):
        resp = api.get(url("/api/user-guide"))
        assert resp.status_code == 200

    @pytest.mark.readonly
    def test_user_actual_permissions(self, api, url):
        resp = api.get(url("/api/user/actual-permissions"))
        assert resp.status_code == 200

    @pytest.mark.readonly
    def test_user_actual_role(self, api, url):
        resp = api.get(url("/api/user/actual-role"))
        assert resp.status_code == 200

    @pytest.mark.readonly
    def test_user_requestable_roles(self, api, url):
        resp = api.get(url("/api/user/requestable-roles"))
        assert resp.status_code == 200

    @pytest.mark.readonly
    def test_user_deployment_policy(self, api, url):
        resp = api.get(url("/api/user/deployment-policy"))
        assert resp.status_code == 200

    @pytest.mark.readonly
    def test_user_projects(self, api, url):
        resp = api.get(url("/api/user/projects"))
        assert resp.status_code == 200

    @pytest.mark.readonly
    def test_data_products_owners(self, api, url):
        resp = api.get(url("/api/data-products/owners"))
        assert resp.status_code == 200

    @pytest.mark.readonly
    def test_data_products_my_subscriptions(self, api, url):
        resp = api.get(url("/api/data-products/my-subscriptions"))
        assert resp.status_code == 200

    @pytest.mark.readonly
    def test_datasets_my_subscriptions(self, api, url):
        resp = api.get(url("/api/datasets/my-subscriptions"))
        assert resp.status_code == 200

    @pytest.mark.readonly
    def test_data_contracts_my_drafts(self, api, url):
        resp = api.get(url("/api/data-contracts/my-drafts"))
        assert resp.status_code in (200, 404)  # Endpoint may not exist

    @pytest.mark.readonly
    def test_settings_git_status(self, api, url):
        resp = api.get(url("/api/settings/git/status"))
        assert resp.status_code in (200, 404, 503)  # May fail if git not configured

    @pytest.mark.readonly
    def test_settings_delivery_status(self, api, url):
        resp = api.get(url("/api/settings/delivery/status"))
        assert resp.status_code == 200

    @pytest.mark.readonly
    def test_settings_delivery_pending(self, api, url):
        resp = api.get(url("/api/settings/delivery/pending"))
        assert resp.status_code == 200

    @pytest.mark.readonly
    def test_mcp_health(self, api, url):
        resp = api.get(url("/api/mcp/health"))
        assert resp.status_code in (200, 404, 503)

    @pytest.mark.readonly
    def test_workspace_search(self, api, url):
        resp = api.get(url("/api/workspace/assets/search"), params={"query": "test"})
        assert resp.status_code in (200, 400, 422)

    @pytest.mark.readonly
    def test_llm_search_status(self, api, url):
        resp = api.get(url("/api/llm-search/status"))
        assert resp.status_code in (200, 404, 503)

    @pytest.mark.readonly
    def test_settings_compliance_mapping(self, api, url):
        resp = api.get(url("/api/settings/compliance-mapping"))
        assert resp.status_code == 200
