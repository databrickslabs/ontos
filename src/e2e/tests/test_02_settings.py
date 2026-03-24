"""Settings endpoints — read-only tests."""
import uuid

import pytest


class TestSettingsRead:

    @pytest.mark.readonly
    def test_get_settings(self, api, url):
        resp = api.get(url("/api/settings"))
        assert resp.status_code == 200

    @pytest.mark.readonly
    def test_get_llm_settings(self, api, url):
        resp = api.get(url("/api/settings/llm"))
        assert resp.status_code == 200

    @pytest.mark.readonly
    def test_get_ui_customization(self, api, url):
        resp = api.get(url("/api/settings/ui-customization"))
        assert resp.status_code == 200

    @pytest.mark.readonly
    def test_get_roles(self, api, url):
        resp = api.get(url("/api/settings/roles"))
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    @pytest.mark.readonly
    def test_get_roles_summary(self, api, url):
        resp = api.get(url("/api/settings/roles/summary"))
        assert resp.status_code == 200

    @pytest.mark.readonly
    def test_get_features(self, api, url):
        resp = api.get(url("/api/settings/features"))
        assert resp.status_code == 200

    @pytest.mark.readonly
    def test_get_search_config(self, api, url):
        resp = api.get(url("/api/settings/search-config"))
        assert resp.status_code == 200

    @pytest.mark.readonly
    def test_get_compliance_mapping(self, api, url):
        resp = api.get(url("/api/settings/compliance-mapping"))
        assert resp.status_code == 200

    @pytest.mark.readonly
    def test_get_database_schema(self, api, url):
        resp = api.get(url("/api/database-schema"))
        assert resp.status_code == 200


class TestSettingsWrite:

    @pytest.fixture(autouse=True)
    def _cleanup(self, api, url):
        self._created_role_id = None
        self._api = api
        self._url = url
        yield
        if self._created_role_id is not None:
            self._api.delete(self._url(f"/api/settings/roles/{self._created_role_id}"))

    @pytest.mark.crud
    def test_role_crud_lifecycle(self, api, url):
        role_name = f"e2e-test-role-{uuid.uuid4().hex[:8]}"
        payload = {
            "name": role_name,
            "description": "E2E test role",
            "features": {},
        }

        # Create
        resp = api.post(url("/api/settings/roles"), json=payload)
        assert resp.status_code == 201, resp.text
        role = resp.json()
        role_id = role["id"]
        self._created_role_id = role_id

        # Verify it appears in the list
        resp = api.get(url("/api/settings/roles"))
        assert resp.status_code == 200
        ids = [r["id"] for r in resp.json()]
        assert role_id in ids

        # Update
        updated_payload = {**payload, "id": role_id, "description": "E2E test role — updated"}
        resp = api.put(url(f"/api/settings/roles/{role_id}"), json=updated_payload)
        assert resp.status_code == 200, resp.text
        assert resp.json()["description"] == "E2E test role — updated"

        # Delete
        resp = api.delete(url(f"/api/settings/roles/{role_id}"))
        assert resp.status_code in (200, 204), resp.text
        self._created_role_id = None  # Already deleted; skip cleanup

    @pytest.mark.crud
    def test_update_compliance_mapping(self, api, url):
        # Capture current state
        resp = api.get(url("/api/settings/compliance-mapping"))
        assert resp.status_code == 200, resp.text
        current = resp.json()

        # Round-trip PUT with the same data
        resp = api.put(url("/api/settings/compliance-mapping"), json=current)
        assert resp.status_code == 200, resp.text

    @pytest.mark.crud
    def test_update_search_config(self, api, url):
        # Capture current state
        resp = api.get(url("/api/settings/search-config"))
        assert resp.status_code == 200, resp.text
        current = resp.json()

        # Round-trip PUT with the same data
        resp = api.put(url("/api/settings/search-config"), json=current)
        assert resp.status_code == 200, resp.text

    @pytest.mark.crud
    def test_rebuild_search_index(self, api, url):
        resp = api.post(url("/api/settings/search-config/rebuild-index"))
        assert resp.status_code in (200, 202), resp.text
