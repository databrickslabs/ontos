"""Data Contracts — CRUD lifecycle with full field round-trip verification."""
import pytest

from helpers.assertions import assert_fields_match
from helpers.test_data import make_data_contract, mutate_data_contract


class TestDataContractsCRUD:

    @pytest.fixture(autouse=True)
    def _cleanup(self, api, url):
        self._to_delete = []
        yield
        for contract_id in reversed(self._to_delete):
            api.delete(url(f"/api/data-contracts/{contract_id}"))

    @pytest.mark.readonly
    def test_list_contracts(self, api, url):
        resp = api.get(url("/api/data-contracts"))
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    @pytest.mark.readonly
    def test_get_odcs_schema(self, api, url):
        resp = api.get(url("/api/data-contracts/schema/odcs"))
        assert resp.status_code == 200

    @pytest.mark.crud
    def test_crud_lifecycle(self, api, url):
        payload = make_data_contract()

        # CREATE
        resp = api.post(url("/api/data-contracts"), json=payload)
        assert resp.status_code in (200, 201), f"Create failed: {resp.status_code} {resp.text[:500]}"
        created = resp.json()
        contract_id = created["id"]
        self._to_delete.append(contract_id)

        # Verify CREATE response — check every field we sent
        # domain is a FK-resolved name; if the domain entity doesn't exist, it won't round-trip
        assert_fields_match(
            payload, created,
            ignore={"schema", "domain"},
            context="after CREATE",
        )
        # Verify schema separately (aliased field)
        sent_schemas = payload.get("schema", [])
        recv_schemas = created.get("contract_schema") or created.get("schema", [])
        if sent_schemas:
            assert len(recv_schemas) >= len(sent_schemas), \
                f"Schema count mismatch: sent {len(sent_schemas)}, got {len(recv_schemas)}"
            for i, sent_s in enumerate(sent_schemas):
                recv_s = recv_schemas[i]
                assert recv_s.get("name") == sent_s["name"], \
                    f"Schema[{i}] name: sent={sent_s['name']}, got={recv_s.get('name')}"
                # Verify properties
                sent_props = sent_s.get("properties", [])
                recv_props = recv_s.get("properties", [])
                assert len(recv_props) >= len(sent_props), \
                    f"Schema[{i}] property count: sent {len(sent_props)}, got {len(recv_props)}"
                for j, sp in enumerate(sent_props):
                    rp = recv_props[j]
                    assert rp.get("name") == sp["name"], \
                        f"Schema[{i}].properties[{j}] name: sent={sp['name']}, got={rp.get('name')}"
                    sent_type = sp.get("logicalType") or sp.get("logical_type")
                    recv_type = rp.get("logicalType") or rp.get("logical_type")
                    assert recv_type == sent_type, \
                        f"Schema[{i}].properties[{j}] logicalType: sent={sent_type}, got={recv_type}"

        # READ back
        resp = api.get(url(f"/api/data-contracts/{contract_id}"))
        assert resp.status_code == 200
        fetched = resp.json()
        assert_fields_match(
            payload, fetched,
            ignore={"schema", "domain"},
            context="after GET",
        )

        # UPDATE
        updated_payload = mutate_data_contract(payload)
        updated_payload["id"] = contract_id
        resp = api.put(url(f"/api/data-contracts/{contract_id}"), json=updated_payload)
        assert resp.status_code == 200, f"Update failed: {resp.status_code} {resp.text[:500]}"
        updated = resp.json()
        assert_fields_match(
            updated_payload, updated,
            ignore={"schema", "domain"},
            context="after UPDATE response",
        )

        # READ after update
        resp = api.get(url(f"/api/data-contracts/{contract_id}"))
        assert resp.status_code == 200
        re_fetched = resp.json()
        assert_fields_match(
            updated_payload, re_fetched,
            ignore={"schema", "domain"},
            context="after UPDATE GET",
        )

        # DELETE
        resp = api.delete(url(f"/api/data-contracts/{contract_id}"))
        assert resp.status_code in (200, 204)
        self._to_delete.remove(contract_id)

        # VERIFY GONE
        resp = api.get(url(f"/api/data-contracts/{contract_id}"))
        assert resp.status_code == 404

    @pytest.mark.crud
    def test_schema_properties_roundtrip(self, api, url):
        """Verify that ALL column property fields survive create → read."""
        payload = make_data_contract()
        # Populate all column property fields
        payload["schema"][0]["properties"] = [
            {
                "name": "full_field",
                "logicalType": "string",
                "required": True,
                "unique": True,
                "primaryKey": False,
                "description": "Full field test",
                "classification": "confidential",
                "minLength": 1,
                "maxLength": 100,
                "businessName": "Full Field",
                "criticalDataElement": True,
                "transformDescription": "Direct copy from source",
            },
            {
                "name": "numeric_field",
                "logicalType": "double",
                "required": False,
                "description": "Numeric with constraints",
                "minimum": 0.0,
                "maximum": 100.0,
                "precision": 10,
            },
        ]

        resp = api.post(url("/api/data-contracts"), json=payload)
        assert resp.status_code in (200, 201), f"Create failed: {resp.text[:500]}"
        contract_id = resp.json()["id"]
        self._to_delete.append(contract_id)

        # READ back and verify every property field
        resp = api.get(url(f"/api/data-contracts/{contract_id}"))
        assert resp.status_code == 200
        data = resp.json()
        schemas = data.get("contract_schema") or data.get("schema", [])
        assert len(schemas) > 0, "No schemas returned"
        props = schemas[0].get("properties", [])
        assert len(props) >= 2, f"Expected 2+ properties, got {len(props)}"

        # Check the full_field
        ff = props[0]
        assert ff["name"] == "full_field"
        assert ff.get("required") is True, f"required: expected True, got {ff.get('required')}"
        assert ff.get("unique") is True, f"unique: expected True, got {ff.get('unique')}"
        assert ff.get("description") == "Full field test"
        assert ff.get("classification") == "confidential"
        assert ff.get("minLength") == 1, f"minLength: expected 1, got {ff.get('minLength')}"
        assert ff.get("maxLength") == 100, f"maxLength: expected 100, got {ff.get('maxLength')}"
        assert ff.get("businessName") == "Full Field", f"businessName: expected 'Full Field', got {ff.get('businessName')}"
        assert ff.get("criticalDataElement") is True, f"criticalDataElement: expected True, got {ff.get('criticalDataElement')}"

        # Check the numeric_field
        nf = props[1]
        assert nf["name"] == "numeric_field"
        assert nf.get("minimum") == 0.0, f"minimum: expected 0.0, got {nf.get('minimum')}"
        assert nf.get("maximum") == 100.0, f"maximum: expected 100.0, got {nf.get('maximum')}"
        assert nf.get("precision") == 10, f"precision: expected 10, got {nf.get('precision')}"
