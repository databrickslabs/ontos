"""Tags — namespace + tag CRUD lifecycle with field round-trip verification."""
import pytest

from helpers.assertions import assert_fields_match
from helpers.test_data import make_tag_namespace, make_tag, mutate_tag


class TestTagNamespacesCRUD:

    @pytest.fixture(autouse=True)
    def _cleanup(self, api, url):
        self._ns_to_delete = []
        yield
        for ns_id in reversed(self._ns_to_delete):
            api.delete(url(f"/api/tags/namespaces/{ns_id}"))

    @pytest.mark.readonly
    def test_list_namespaces(self, api, url):
        resp = api.get(url("/api/tags/namespaces"))
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    @pytest.mark.crud
    def test_namespace_crud(self, api, url):
        payload = make_tag_namespace()

        # CREATE
        resp = api.post(url("/api/tags/namespaces"), json=payload)
        assert resp.status_code in (200, 201), f"Create failed: {resp.status_code} {resp.text[:300]}"
        created = resp.json()
        ns_id = created["id"]
        self._ns_to_delete.append(ns_id)

        assert_fields_match(payload, created, context="namespace CREATE")

        # READ
        resp = api.get(url(f"/api/tags/namespaces/{ns_id}"))
        assert resp.status_code == 200
        assert_fields_match(payload, resp.json(), context="namespace GET")

        # UPDATE
        update = {"name": payload["name"], "description": "Updated namespace"}
        resp = api.put(url(f"/api/tags/namespaces/{ns_id}"), json=update)
        assert resp.status_code == 200

        resp = api.get(url(f"/api/tags/namespaces/{ns_id}"))
        assert resp.json()["description"] == "Updated namespace"

        # DELETE
        resp = api.delete(url(f"/api/tags/namespaces/{ns_id}"))
        assert resp.status_code in (200, 204)
        self._ns_to_delete.remove(ns_id)


class TestTagsCRUD:

    @pytest.fixture(autouse=True)
    def _cleanup(self, api, url):
        self._tags_to_delete = []
        self._ns_to_delete = []
        yield
        for tag_id in reversed(self._tags_to_delete):
            api.delete(url(f"/api/tags/{tag_id}"))
        for ns_id in reversed(self._ns_to_delete):
            api.delete(url(f"/api/tags/namespaces/{ns_id}"))

    @pytest.mark.readonly
    def test_list_tags(self, api, url):
        resp = api.get(url("/api/tags"))
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    @pytest.mark.crud
    def test_tag_crud_with_all_fields(self, api, url):
        # Create namespace first
        ns_payload = make_tag_namespace()
        resp = api.post(url("/api/tags/namespaces"), json=ns_payload)
        assert resp.status_code in (200, 201)
        ns_id = resp.json()["id"]
        self._ns_to_delete.append(ns_id)

        # CREATE tag
        tag_payload = make_tag(namespace_id=ns_id)
        resp = api.post(url("/api/tags"), json=tag_payload)
        assert resp.status_code in (200, 201), f"Create failed: {resp.status_code} {resp.text[:300]}"
        created = resp.json()
        tag_id = created["id"]
        self._tags_to_delete.append(tag_id)

        assert_fields_match(
            tag_payload, created,
            ignore={"namespace_id", "namespace_name"},
            context="tag CREATE",
        )

        # READ
        resp = api.get(url(f"/api/tags/{tag_id}"))
        assert resp.status_code == 200
        fetched = resp.json()
        assert_fields_match(
            tag_payload, fetched,
            ignore={"namespace_id", "namespace_name"},
            context="tag GET",
        )

        # Verify possible_values round-tripped
        assert fetched.get("possible_values") == tag_payload["possible_values"], \
            f"possible_values mismatch: sent={tag_payload['possible_values']}, got={fetched.get('possible_values')}"

        # UPDATE
        updated_payload = mutate_tag(tag_payload)
        resp = api.put(url(f"/api/tags/{tag_id}"), json=updated_payload)
        assert resp.status_code == 200, f"Update failed: {resp.status_code} {resp.text[:300]}"

        # READ after update
        resp = api.get(url(f"/api/tags/{tag_id}"))
        assert resp.status_code == 200
        re_fetched = resp.json()
        assert re_fetched["description"] == updated_payload["description"]
        assert re_fetched.get("possible_values") == updated_payload["possible_values"]
        assert re_fetched.get("version") == updated_payload["version"]

        # DELETE
        resp = api.delete(url(f"/api/tags/{tag_id}"))
        assert resp.status_code in (200, 204)
        self._tags_to_delete.remove(tag_id)
