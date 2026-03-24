"""Data Domains — full CRUD lifecycle with field round-trip verification."""
import pytest

from helpers.assertions import assert_fields_match
from helpers.test_data import make_domain, mutate_domain


class TestDataDomainsCRUD:

    @pytest.fixture(autouse=True)
    def _cleanup(self, api, url):
        self._to_delete = []
        yield
        for domain_id in reversed(self._to_delete):
            api.delete(url(f"/api/data-domains/{domain_id}"))

    @pytest.mark.readonly
    def test_list_returns_200(self, api, url):
        resp = api.get(url("/api/data-domains"))
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    @pytest.mark.crud
    def test_crud_lifecycle(self, api, url):
        payload = make_domain()

        # CREATE
        resp = api.post(url("/api/data-domains"), json=payload)
        assert resp.status_code in (200, 201), f"Create failed: {resp.status_code} {resp.text[:300]}"
        created = resp.json()
        domain_id = created["id"]
        self._to_delete.append(domain_id)

        # Verify CREATE response
        assert_fields_match(payload, created, context="after CREATE")

        # READ back
        resp = api.get(url(f"/api/data-domains/{domain_id}"))
        assert resp.status_code == 200
        fetched = resp.json()
        assert_fields_match(payload, fetched, context="after GET")

        # UPDATE every mutable field
        updated_payload = mutate_domain(payload)
        resp = api.put(url(f"/api/data-domains/{domain_id}"), json=updated_payload)
        assert resp.status_code == 200, f"Update failed: {resp.status_code} {resp.text[:300]}"
        updated = resp.json()
        assert_fields_match(updated_payload, updated, context="after UPDATE response")

        # READ after update
        resp = api.get(url(f"/api/data-domains/{domain_id}"))
        assert resp.status_code == 200
        re_fetched = resp.json()
        assert_fields_match(updated_payload, re_fetched, context="after UPDATE GET")

        # DELETE
        resp = api.delete(url(f"/api/data-domains/{domain_id}"))
        assert resp.status_code in (200, 204), f"Delete failed: {resp.status_code}"
        self._to_delete.remove(domain_id)

        # VERIFY GONE
        resp = api.get(url(f"/api/data-domains/{domain_id}"))
        assert resp.status_code == 404

    @pytest.mark.crud
    def test_create_with_parent(self, api, url):
        """Test hierarchical domains — parent/child relationship."""
        parent = make_domain(name="e2e-test-parent-domain")
        resp = api.post(url("/api/data-domains"), json=parent)
        assert resp.status_code in (200, 201)
        parent_id = resp.json()["id"]
        self._to_delete.append(parent_id)

        child = make_domain(parent_id=parent_id)
        resp = api.post(url("/api/data-domains"), json=child)
        assert resp.status_code in (200, 201)
        child_data = resp.json()
        child_id = child_data["id"]
        self._to_delete.append(child_id)

        assert str(child_data.get("parent_id")) == str(parent_id)

        # Re-read child to verify parent_id persists
        resp = api.get(url(f"/api/data-domains/{child_id}"))
        assert resp.status_code == 200
        assert str(resp.json().get("parent_id")) == str(parent_id)
