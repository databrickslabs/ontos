"""Estates — CRUD lifecycle with field round-trip verification."""
import pytest

from helpers.assertions import assert_fields_match
from helpers.test_data import make_estate, mutate_estate


class TestEstates:

    @pytest.fixture(autouse=True)
    def _cleanup(self, api, url):
        self._to_delete = []
        yield
        for eid in reversed(self._to_delete):
            api.delete(url(f"/api/estates/{eid}"))

    @pytest.mark.readonly
    def test_list_estates(self, api, url):
        resp = api.get(url("/api/estates"))
        if resp.status_code == 500:
            pytest.skip("workspace client unavailable in local dev")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    @pytest.mark.crud
    def test_create_estate(self, api, url):
        """Test estate creation."""
        payload = make_estate()

        # CREATE
        resp = api.post(url("/api/estates"), json=payload)
        if resp.status_code == 500:
            pytest.skip("workspace client unavailable in local dev")
        assert resp.status_code in (200, 201), f"Create failed: {resp.status_code} {resp.text[:500]}"
        created = resp.json()
        estate_id = created["id"]
        self._to_delete.append(estate_id)

        assert_fields_match(payload, created, context="after CREATE",
                           ignore={"export_policies", "import_policies"})

    @pytest.mark.crud
    def test_full_crud_lifecycle(self, api, url):
        """Create estate, GET by id, UPDATE via PUT, DELETE, verify gone.

        Estates are stored in the database (#146), so GET after CREATE finds it.
        """
        payload = make_estate()

        # CREATE
        resp = api.post(url("/api/estates"), json=payload)
        if resp.status_code == 500:
            pytest.skip("workspace client unavailable in local dev")
        assert resp.status_code in (200, 201), f"Create failed: {resp.status_code} {resp.text[:500]}"
        created = resp.json()
        estate_id = created["id"]
        self._to_delete.append(estate_id)

        # GET by id
        resp = api.get(url(f"/api/estates/{estate_id}"))
        assert resp.status_code == 200, f"GET failed: {resp.status_code} {resp.text[:300]}"
        fetched = resp.json()
        assert_fields_match(payload, fetched, context="after GET", ignore={"export_policies", "import_policies"})

        # UPDATE via PUT
        updated_payload = mutate_estate(payload)
        resp = api.put(url(f"/api/estates/{estate_id}"), json=updated_payload)
        assert resp.status_code == 200, f"Update failed: {resp.status_code} {resp.text[:300]}"
        updated = resp.json()
        assert_fields_match(updated_payload, updated, context="after UPDATE", ignore={"export_policies", "import_policies"})

        # DELETE
        resp = api.delete(url(f"/api/estates/{estate_id}"))
        assert resp.status_code in (200, 204), f"Delete failed: {resp.status_code} {resp.text[:300]}"
        self._to_delete.remove(estate_id)

        # VERIFY GONE
        resp = api.get(url(f"/api/estates/{estate_id}"))
        assert resp.status_code == 404, \
            f"Expected 404 after delete, got {resp.status_code}"

    @pytest.mark.crud
    def test_policies_round_trip_and_name_is_unique(self, api, url):
        """Export and import policies are stored separately; a second estate with the same
        name is refused with a coded 409."""
        payload = make_estate(
            export_policies=[{
                "name": "Active products", "resource_type": "data_product", "is_enabled": True,
                "rules": [{"filter_type": "status", "operator": "equals", "filter_value": "active"}],
            }],
            import_policies=[{"name": "Terms", "resource_type": "business_term", "rules": []}],
        )
        resp = api.post(url("/api/estates"), json=payload)
        if resp.status_code == 500:
            pytest.skip("workspace client unavailable in local dev")
        assert resp.status_code in (200, 201), resp.text[:300]
        estate_id = resp.json()["id"]
        self._to_delete.append(estate_id)

        fetched = api.get(url(f"/api/estates/{estate_id}")).json()
        assert [(p["name"], p["resource_type"]) for p in fetched["export_policies"]] == [
            ("Active products", "data_product")]
        assert fetched["export_policies"][0]["rules"][0]["filter_value"] == "active"
        assert [(p["name"], p["resource_type"]) for p in fetched["import_policies"]] == [
            ("Terms", "business_term")]

        dup = api.post(url("/api/estates"), json=make_estate(name=payload["name"]))
        assert dup.status_code == 409, dup.text[:300]
        assert dup.json()["detail"]["code"] == "estate_name_conflict"
