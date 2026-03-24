"""Security Features — CRUD lifecycle with field round-trip verification."""
import pytest

from helpers.assertions import assert_fields_match
from helpers.test_data import make_security_feature, mutate_security_feature


class TestSecurityFeatures:

    @pytest.fixture(autouse=True)
    def _cleanup(self, api, url):
        self._to_delete = []
        yield
        for fid in reversed(self._to_delete):
            api.delete(url(f"/api/security-features/{fid}"))

    @pytest.mark.readonly
    def test_list_security_features(self, api, url):
        resp = api.get(url("/api/security-features"))
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    @pytest.mark.crud
    def test_crud_lifecycle(self, api, url):
        payload = make_security_feature()

        # CREATE
        resp = api.post(url("/api/security-features"), json=payload)
        assert resp.status_code in (200, 201), f"Create failed: {resp.status_code} {resp.text[:500]}"
        created = resp.json()
        feat_id = created["id"]
        self._to_delete.append(feat_id)

        assert_fields_match(payload, created, context="after CREATE")

        # READ
        resp = api.get(url(f"/api/security-features/{feat_id}"))
        assert resp.status_code == 200
        fetched = resp.json()
        assert_fields_match(payload, fetched, context="after GET")

        # UPDATE
        updated_payload = mutate_security_feature(payload)
        resp = api.put(url(f"/api/security-features/{feat_id}"), json=updated_payload)
        assert resp.status_code == 200, f"Update failed: {resp.status_code} {resp.text[:500]}"
        updated = resp.json()
        assert_fields_match(updated_payload, updated, context="after UPDATE response")

        # READ after update
        resp = api.get(url(f"/api/security-features/{feat_id}"))
        assert resp.status_code == 200
        re_fetched = resp.json()
        assert_fields_match(updated_payload, re_fetched, context="after UPDATE GET")

        # DELETE
        resp = api.delete(url(f"/api/security-features/{feat_id}"))
        assert resp.status_code in (200, 204), f"Delete failed: {resp.status_code}"
        self._to_delete.remove(feat_id)
