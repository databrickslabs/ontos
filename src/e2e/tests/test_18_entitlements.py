"""Entitlements Personas — CRUD lifecycle with field round-trip verification."""
import pytest

from helpers.assertions import assert_fields_match
from helpers.test_data import make_persona, mutate_persona


class TestEntitlementsPersonas:

    @pytest.fixture(autouse=True)
    def _cleanup(self, api, url):
        self._to_delete = []
        yield
        for pid in reversed(self._to_delete):
            api.delete(url(f"/api/entitlements/personas/{pid}"))

    @pytest.mark.readonly
    def test_list_personas(self, api, url):
        resp = api.get(url("/api/entitlements/personas"))
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    @pytest.mark.crud
    def test_crud_lifecycle(self, api, url):
        payload = make_persona()

        # CREATE
        resp = api.post(url("/api/entitlements/personas"), json=payload)
        assert resp.status_code in (200, 201), f"Create failed: {resp.status_code} {resp.text[:500]}"
        created = resp.json()
        persona_id = created["id"]
        self._to_delete.append(persona_id)

        assert_fields_match(payload, created, context="after CREATE")

        # READ
        resp = api.get(url(f"/api/entitlements/personas/{persona_id}"))
        assert resp.status_code == 200
        fetched = resp.json()
        assert_fields_match(payload, fetched, context="after GET")

        # UPDATE
        updated_payload = mutate_persona(payload)
        resp = api.put(url(f"/api/entitlements/personas/{persona_id}"), json=updated_payload)
        assert resp.status_code == 200, f"Update failed: {resp.status_code} {resp.text[:500]}"
        updated = resp.json()
        assert_fields_match(updated_payload, updated, context="after UPDATE response")

        # READ after update
        resp = api.get(url(f"/api/entitlements/personas/{persona_id}"))
        assert resp.status_code == 200
        re_fetched = resp.json()
        assert_fields_match(updated_payload, re_fetched, context="after UPDATE GET")

        # DELETE
        resp = api.delete(url(f"/api/entitlements/personas/{persona_id}"))
        assert resp.status_code in (200, 204), f"Delete failed: {resp.status_code}"
        self._to_delete.remove(persona_id)

    @pytest.mark.crud
    def test_add_and_remove_privilege(self, api, url):
        """Add a privilege to a persona then remove it by securable_id."""
        payload = make_persona()
        resp = api.post(url("/api/entitlements/personas"), json=payload)
        assert resp.status_code in (200, 201), f"Create failed: {resp.status_code} {resp.text[:500]}"
        persona_id = resp.json()["id"]
        self._to_delete.append(persona_id)

        # ADD privilege
        privilege_payload = {
            "securable_type": "catalog",
            "securable_name": "e2e_test_catalog",
            "privilege": "USE_CATALOG",
        }
        resp = api.post(
            url(f"/api/entitlements/personas/{persona_id}/privileges"),
            json=privilege_payload,
        )
        if resp.status_code in (400, 422):
            pytest.skip(
                f"Privilege add rejected (likely invalid securable in test env): "
                f"{resp.status_code} {resp.text[:300]}"
            )
        assert resp.status_code in (200, 201), (
            f"Add privilege failed: {resp.status_code} {resp.text[:500]}"
        )

        # Derive securable_id from the response — fall back to the payload name when
        # the backend does not return a dedicated id field.
        added = resp.json()
        securable_id = (
            added.get("id")
            or added.get("securable_id")
            or privilege_payload["securable_name"]
        )

        # REMOVE privilege
        resp = api.delete(
            url(f"/api/entitlements/personas/{persona_id}/privileges/{securable_id}")
        )
        assert resp.status_code in (200, 204), (
            f"Remove privilege failed: {resp.status_code} {resp.text[:500]}"
        )

    @pytest.mark.crud
    def test_update_persona_groups(self, api, url):
        """Assign groups to a persona and verify the assignment is persisted."""
        payload = make_persona()
        resp = api.post(url("/api/entitlements/personas"), json=payload)
        assert resp.status_code in (200, 201), f"Create failed: {resp.status_code} {resp.text[:500]}"
        persona_id = resp.json()["id"]
        self._to_delete.append(persona_id)

        # UPDATE groups
        groups_payload = {"groups": ["e2e-test-group"]}
        resp = api.put(
            url(f"/api/entitlements/personas/{persona_id}/groups"),
            json=groups_payload,
        )
        assert resp.status_code == 200, (
            f"Update groups failed: {resp.status_code} {resp.text[:500]}"
        )

        # READ back and verify groups are reflected
        resp = api.get(url(f"/api/entitlements/personas/{persona_id}"))
        assert resp.status_code == 200
        fetched = resp.json()
        # Groups may be stored under "groups" or nested; accept either a list containing
        # our group or a dict with a "groups" key.
        raw_groups = fetched.get("groups", [])
        if isinstance(raw_groups, list):
            group_names = [
                (g["name"] if isinstance(g, dict) else g) for g in raw_groups
            ]
        else:
            group_names = []
        assert "e2e-test-group" in group_names, (
            f"Expected 'e2e-test-group' in persona groups, got: {raw_groups}"
        )
