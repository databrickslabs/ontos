"""
Integration tests for the key format of data product responses (#1238).

`DataProduct` has camelCase field names with snake_case aliases (`outputPorts` /
`output_ports`). GET answers with the field names; the write routes used to answer
with the aliases because FastAPI serializes a `response_model` by alias. Every route
that returns a product must use the GET format.
"""
import uuid

import pytest

from src.models.data_products import DataProduct, InputPort, OutputPort


def _alias_only_keys() -> set:
    """Alias spellings that differ from the field name (output_ports, api_version, ...)."""
    names = set()
    for model in (DataProduct, OutputPort, InputPort):
        for name, info in model.model_fields.items():
            if info.alias and info.alias != name:
                names.add(info.alias)
    return names


def _all_keys(value) -> set:
    keys = set()
    if isinstance(value, dict):
        for key, item in value.items():
            keys.add(key)
            keys |= _all_keys(item)
    elif isinstance(value, list):
        for item in value:
            keys |= _all_keys(item)
    return keys


def _assert_get_format(body: dict):
    assert "outputPorts" in body, sorted(body)
    leaked = _all_keys(body) & _alias_only_keys()
    assert not leaked, f"write response uses snake_case alias keys: {sorted(leaked)}"


class TestDataProductResponseFormat:
    @staticmethod
    def _payload(status="draft", contract_id=None):
        port = {"name": "port-a", "version": "1.0.0", "type": "table"}
        if contract_id:
            port["contractId"] = contract_id
        return {
            "id": str(uuid.uuid4()),
            "name": "Format Product",
            "version": "1.0.0",
            "productType": "sourceAligned",
            "status": status,
            "owner": "test@example.com",
            "outputPorts": [port],
            "inputPorts": [{"name": "in-a", "version": "1.0.0", "contractId": "c-1"}],
        }

    @staticmethod
    def _get(client, product_id):
        resp = client.get(f"/api/data-products/{product_id}")
        assert resp.status_code == 200, resp.text
        return resp.json()

    def test_post_returns_get_format(self, client):
        payload = self._payload()
        resp = client.post("/api/data-products", json=payload)
        assert resp.status_code == 201, resp.text
        body = resp.json()
        _assert_get_format(body)
        got = self._get(client, payload["id"])
        assert body["outputPorts"][0]["name"] == got["outputPorts"][0]["name"]
        assert body["inputPorts"][0]["name"] == got["inputPorts"][0]["name"]

    def test_put_returns_get_format(self, client):
        payload = self._payload()
        assert client.post("/api/data-products", json=payload).status_code == 201
        payload["name"] = "Renamed"
        resp = client.put(f"/api/data-products/{payload['id']}", json=payload)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        _assert_get_format(body)
        assert body["name"] == self._get(client, payload["id"])["name"] == "Renamed"

    def test_new_version_returns_get_format(self, client):
        payload = self._payload()
        assert client.post("/api/data-products", json=payload).status_code == 201
        resp = client.post(
            f"/api/data-products/{payload['id']}/versions", json={"new_version": "2.0.0"}
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        _assert_get_format(body)
        assert body["version"] == self._get(client, body["id"])["version"] == "2.0.0"

    def test_new_version_versioning_keys_match_get(self, client):
        """The versioning fields (camelCase ``serialization_alias``) use the GET keys too."""
        payload = self._payload()
        assert client.post("/api/data-products", json=payload).status_code == 201
        resp = client.post(
            f"/api/data-products/{payload['id']}/versions", json={"new_version": "2.0.0"}
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        got = self._get(client, body["id"])
        # snake_case fields whose serialization_alias is camelCase (parentProductId, ...)
        camel = {
            info.serialization_alias for name, info in DataProduct.model_fields.items()
            if '_' in name and info.serialization_alias and info.serialization_alias != name
        }
        assert "parentProductId" in camel
        assert not camel & set(got), "GET is expected to use the field names"
        assert not camel & set(body), f"write response uses {sorted(camel & set(body))}"
        assert body["parent_product_id"] == got["parent_product_id"] == payload["id"]

    def test_clone_for_editing_returns_get_format(self, client):
        payload = self._payload(status="active")
        assert client.post("/api/data-products", json=payload).status_code == 201
        resp = client.post(f"/api/data-products/{payload['id']}/clone-for-editing", json={})
        assert resp.status_code == 200, resp.text
        body = resp.json()
        _assert_get_format(body)
        assert body["id"] != payload["id"]
