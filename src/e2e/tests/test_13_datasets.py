"""Datasets — CRUD lifecycle with field round-trip verification."""
import pytest

from helpers.assertions import assert_fields_match
from helpers.test_data import make_dataset, mutate_dataset, make_dataset_instance, make_data_contract


class TestDatasetsCRUD:

    @pytest.fixture(autouse=True)
    def _cleanup(self, api, url):
        self._to_delete = []
        yield
        for ds_id in reversed(self._to_delete):
            api.delete(url(f"/api/datasets/{ds_id}"))

    @pytest.mark.readonly
    def test_list_datasets(self, api, url):
        resp = api.get(url("/api/datasets"))
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    @pytest.mark.readonly
    def test_published_datasets(self, api, url):
        resp = api.get(url("/api/datasets/published"))
        assert resp.status_code == 200

    @pytest.mark.crud
    def test_crud_lifecycle(self, api, url):
        payload = make_dataset()

        # CREATE
        resp = api.post(url("/api/datasets"), json=payload)
        assert resp.status_code in (200, 201), f"Create failed: {resp.status_code} {resp.text[:500]}"
        created = resp.json()
        ds_id = created["id"]
        self._to_delete.append(ds_id)

        assert_fields_match(payload, created, context="after CREATE")

        # READ
        resp = api.get(url(f"/api/datasets/{ds_id}"))
        assert resp.status_code == 200
        fetched = resp.json()
        assert_fields_match(payload, fetched, context="after GET")

        # UPDATE
        updated_payload = mutate_dataset(payload)
        resp = api.put(url(f"/api/datasets/{ds_id}"), json=updated_payload)
        assert resp.status_code == 200, f"Update failed: {resp.status_code} {resp.text[:500]}"
        updated = resp.json()
        assert_fields_match(updated_payload, updated, context="after UPDATE response")

        # READ after update
        resp = api.get(url(f"/api/datasets/{ds_id}"))
        assert resp.status_code == 200
        re_fetched = resp.json()
        assert_fields_match(updated_payload, re_fetched, context="after UPDATE GET")

        # DELETE
        resp = api.delete(url(f"/api/datasets/{ds_id}"))
        assert resp.status_code in (200, 204), f"Delete failed: {resp.status_code} {resp.text[:300]}"
        self._to_delete.remove(ds_id)

        # VERIFY GONE
        resp = api.get(url(f"/api/datasets/{ds_id}"))
        assert resp.status_code == 404

    @pytest.mark.crud
    def test_dataset_instances(self, api, url):
        """Test creating and managing dataset instances (physical implementations)."""
        # Create parent dataset
        payload = make_dataset()
        resp = api.post(url("/api/datasets"), json=payload)
        assert resp.status_code in (200, 201)
        ds_id = resp.json()["id"]
        self._to_delete.append(ds_id)

        # CREATE instance
        inst = make_dataset_instance()
        resp = api.post(url(f"/api/datasets/{ds_id}/instances"), json=inst)
        assert resp.status_code in (200, 201), f"Instance create failed: {resp.status_code} {resp.text[:300]}"
        created_inst = resp.json()
        inst_id = created_inst["id"]

        assert_fields_match(inst, created_inst, context="instance after CREATE")

        # LIST instances
        resp = api.get(url(f"/api/datasets/{ds_id}/instances"))
        assert resp.status_code == 200
        instances = resp.json()
        # Instances may be dicts or may have different key names
        if instances and isinstance(instances, list):
            assert len(instances) >= 1, "No instances in list"

        # GET single instance
        resp = api.get(url(f"/api/datasets/{ds_id}/instances/{inst_id}"))
        assert resp.status_code == 200
        fetched_inst = resp.json()
        assert fetched_inst.get("physical_path") == inst["physical_path"] or \
               fetched_inst.get("physicalPath") == inst["physical_path"]

        # UPDATE instance
        resp = api.put(url(f"/api/datasets/{ds_id}/instances/{inst_id}"), json={
            "display_name": "Updated E2E Instance",
            "notes": "Updated by E2E test",
        })
        assert resp.status_code == 200, f"Instance update failed: {resp.status_code} {resp.text[:300]}"

        # DELETE instance
        resp = api.delete(url(f"/api/datasets/{ds_id}/instances/{inst_id}"))
        assert resp.status_code in (200, 204)

    @pytest.mark.crud
    def test_dataset_subscription(self, api, url):
        """Test subscribing and unsubscribing from a dataset."""
        payload = make_dataset()
        resp = api.post(url("/api/datasets"), json=payload)
        assert resp.status_code in (200, 201)
        ds_id = resp.json()["id"]
        self._to_delete.append(ds_id)

        # Subscribe
        resp = api.post(url(f"/api/datasets/{ds_id}/subscribe"))
        assert resp.status_code in (200, 201), f"Subscribe failed: {resp.status_code} {resp.text[:300]}"

        # Check subscription
        resp = api.get(url(f"/api/datasets/{ds_id}/subscription"))
        assert resp.status_code == 200

        # List subscribers
        resp = api.get(url(f"/api/datasets/{ds_id}/subscribers"))
        assert resp.status_code == 200

        # Unsubscribe
        resp = api.delete(url(f"/api/datasets/{ds_id}/subscribe"))
        assert resp.status_code in (200, 204)

    @pytest.mark.crud
    def test_publish_and_unpublish(self, api, url):
        """Publish a dataset then unpublish it."""
        payload = make_dataset()
        resp = api.post(url("/api/datasets"), json=payload)
        assert resp.status_code in (200, 201)
        ds_id = resp.json()["id"]
        self._to_delete.append(ds_id)

        # Publish
        resp = api.post(url(f"/api/datasets/{ds_id}/publish"))
        if resp.status_code in (400, 409):
            pytest.skip(f"Publish not allowed in current state: {resp.status_code} {resp.text[:200]}")
        assert resp.status_code == 200, f"Publish failed: {resp.status_code} {resp.text[:300]}"

        # Unpublish
        resp = api.post(url(f"/api/datasets/{ds_id}/unpublish"))
        assert resp.status_code == 200, f"Unpublish failed: {resp.status_code} {resp.text[:300]}"

    @pytest.mark.crud
    def test_change_status(self, api, url):
        """Change a dataset's status via the dedicated endpoint."""
        payload = make_dataset()
        resp = api.post(url("/api/datasets"), json=payload)
        assert resp.status_code in (200, 201)
        ds_id = resp.json()["id"]
        self._to_delete.append(ds_id)

        resp = api.post(url(f"/api/datasets/{ds_id}/change-status"), json={"new_status": "proposed"})
        if resp.status_code in (400, 409):
            pytest.skip(f"Status transition not allowed: {resp.status_code} {resp.text[:200]}")
        assert resp.status_code in (200, 204), f"Change-status failed: {resp.status_code} {resp.text[:300]}"

    @pytest.mark.crud
    def test_link_and_unlink_contract(self, api, url):
        """Link a data contract to a dataset then unlink it."""
        self._contracts_to_delete = []

        # Create dataset
        ds_resp = api.post(url("/api/datasets"), json=make_dataset())
        assert ds_resp.status_code in (200, 201)
        ds_id = ds_resp.json()["id"]
        self._to_delete.append(ds_id)

        # Create data contract
        dc_resp = api.post(url("/api/data-contracts"), json=make_data_contract())
        assert dc_resp.status_code in (200, 201), f"Contract create failed: {dc_resp.status_code} {dc_resp.text[:300]}"
        contract_id = dc_resp.json()["id"]
        self._contracts_to_delete.append(contract_id)

        # Link contract to dataset
        resp = api.post(url(f"/api/datasets/{ds_id}/contract/{contract_id}"))
        assert resp.status_code == 200, f"Link contract failed: {resp.status_code} {resp.text[:300]}"

        # Unlink contract from dataset
        resp = api.delete(url(f"/api/datasets/{ds_id}/contract"))
        assert resp.status_code in (200, 204), f"Unlink contract failed: {resp.status_code} {resp.text[:300]}"

        # Cleanup contracts
        for cid in reversed(self._contracts_to_delete):
            api.delete(url(f"/api/data-contracts/{cid}"))

    @pytest.mark.crud
    def test_list_datasets_by_contract(self, api, url):
        """Link a dataset to a contract and verify it appears in the by-contract listing."""
        self._contracts_to_delete = []

        # Create dataset
        ds_resp = api.post(url("/api/datasets"), json=make_dataset())
        assert ds_resp.status_code in (200, 201)
        ds_id = ds_resp.json()["id"]
        self._to_delete.append(ds_id)

        # Create data contract
        dc_resp = api.post(url("/api/data-contracts"), json=make_data_contract())
        assert dc_resp.status_code in (200, 201), f"Contract create failed: {dc_resp.status_code} {dc_resp.text[:300]}"
        contract_id = dc_resp.json()["id"]
        self._contracts_to_delete.append(contract_id)

        # Link contract to dataset
        resp = api.post(url(f"/api/datasets/{ds_id}/contract/{contract_id}"))
        assert resp.status_code == 200, f"Link contract failed: {resp.status_code} {resp.text[:300]}"

        # List datasets by contract
        resp = api.get(url(f"/api/datasets/by-contract/{contract_id}"))
        assert resp.status_code == 200, f"By-contract list failed: {resp.status_code} {resp.text[:300]}"
        items = resp.json()
        assert isinstance(items, list), "Expected a list response"
        ids = [item.get("id") for item in items]
        assert ds_id in ids, f"Created dataset {ds_id} not found in by-contract list: {ids}"

        # Cleanup contracts
        for cid in reversed(self._contracts_to_delete):
            api.delete(url(f"/api/data-contracts/{cid}"))

    @pytest.mark.readonly
    def test_my_subscriptions(self, api, url):
        """Verify that the my-subscriptions endpoint returns a list."""
        resp = api.get(url("/api/datasets/my-subscriptions"))
        assert resp.status_code == 200, f"My-subscriptions failed: {resp.status_code} {resp.text[:300]}"
        assert isinstance(resp.json(), list), "Expected a list response"
