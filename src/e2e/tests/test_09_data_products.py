"""Data Products — CRUD lifecycle with full field round-trip verification."""
import pytest

from helpers.assertions import assert_fields_match
from helpers.test_data import make_data_product, mutate_data_product


class TestDataProductsCRUD:

    @pytest.fixture(autouse=True)
    def _cleanup(self, api, url):
        self._to_delete = []
        yield
        for product_id in reversed(self._to_delete):
            api.delete(url(f"/api/data-products/{product_id}"))

    @pytest.mark.readonly
    def test_list_products(self, api, url):
        resp = api.get(url("/api/data-products"))
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    @pytest.mark.readonly
    def test_get_statuses(self, api, url):
        resp = api.get(url("/api/data-products/statuses"))
        assert resp.status_code == 200

    @pytest.mark.readonly
    def test_get_types(self, api, url):
        resp = api.get(url("/api/data-products/types"))
        assert resp.status_code == 200

    @pytest.mark.readonly
    def test_get_published(self, api, url):
        resp = api.get(url("/api/data-products/published"))
        assert resp.status_code == 200

    @pytest.mark.crud
    def test_crud_lifecycle(self, api, url):
        payload = make_data_product()

        # CREATE
        resp = api.post(url("/api/data-products"), json=payload)
        assert resp.status_code in (200, 201), f"Create failed: {resp.status_code} {resp.text[:500]}"
        created = resp.json()
        product_id = created["id"]
        self._to_delete.append(product_id)

        assert_fields_match(payload, created, context="after CREATE")

        # READ
        resp = api.get(url(f"/api/data-products/{product_id}"))
        assert resp.status_code == 200
        fetched = resp.json()
        assert_fields_match(payload, fetched, context="after GET")

        # UPDATE every mutable field
        updated_payload = mutate_data_product(payload)
        updated_payload["id"] = product_id
        resp = api.put(url(f"/api/data-products/{product_id}"), json=updated_payload)
        assert resp.status_code == 200, f"Update failed: {resp.status_code} {resp.text[:500]}"
        updated = resp.json()
        assert_fields_match(updated_payload, updated, context="after UPDATE response")

        # READ after update
        resp = api.get(url(f"/api/data-products/{product_id}"))
        assert resp.status_code == 200
        re_fetched = resp.json()
        assert_fields_match(updated_payload, re_fetched, context="after UPDATE GET")

        # DELETE
        resp = api.delete(url(f"/api/data-products/{product_id}"))
        assert resp.status_code in (200, 204)
        self._to_delete.remove(product_id)

        resp = api.get(url(f"/api/data-products/{product_id}"))
        assert resp.status_code == 404

    @pytest.mark.crud
    def test_description_roundtrip(self, api, url):
        """Verify structured description fields survive create → read."""
        payload = make_data_product(description={
            "purpose": "Test purpose text",
            "limitations": "Test limitations text",
            "usage": "Test usage text",
        })
        resp = api.post(url("/api/data-products"), json=payload)
        assert resp.status_code in (200, 201)
        product_id = resp.json()["id"]
        self._to_delete.append(product_id)

        resp = api.get(url(f"/api/data-products/{product_id}"))
        desc = resp.json().get("description", {})
        assert desc.get("purpose") == "Test purpose text", f"purpose: {desc.get('purpose')}"
        assert desc.get("limitations") == "Test limitations text", f"limitations: {desc.get('limitations')}"
        assert desc.get("usage") == "Test usage text", f"usage: {desc.get('usage')}"

    @pytest.mark.crud
    def test_custom_properties_roundtrip(self, api, url):
        """Verify customProperties survive create → read."""
        props = [
            {"property": "testProp1", "value": "string-value", "description": "A string prop"},
            {"property": "testProp2", "value": 42, "description": "A numeric prop"},
        ]
        payload = make_data_product(customProperties=props)
        resp = api.post(url("/api/data-products"), json=payload)
        assert resp.status_code in (200, 201)
        product_id = resp.json()["id"]
        self._to_delete.append(product_id)

        resp = api.get(url(f"/api/data-products/{product_id}"))
        recv_props = resp.json().get("customProperties", [])
        assert len(recv_props) == 2, f"Expected 2 customProperties, got {len(recv_props)}"
        for i, sent in enumerate(props):
            found = next((p for p in recv_props if p.get("property") == sent["property"]), None)
            assert found, f"customProperty '{sent['property']}' not found in response"
            assert str(found.get("value")) == str(sent["value"]), \
                f"customProperty '{sent['property']}' value: sent={sent['value']}, got={found.get('value')}"

    @pytest.mark.crud
    def test_max_level_inheritance_roundtrip(self, api, url):
        """Verify max_level_inheritance persists."""
        payload = make_data_product(max_level_inheritance=42)
        resp = api.post(url("/api/data-products"), json=payload)
        assert resp.status_code in (200, 201)
        product_id = resp.json()["id"]
        self._to_delete.append(product_id)

        resp = api.get(url(f"/api/data-products/{product_id}"))
        assert resp.json().get("max_level_inheritance") == 42
