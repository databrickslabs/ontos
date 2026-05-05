"""Change Log — read and create entries."""
import pytest

from helpers.test_data import make_change_log_entry


class TestChangeLog:

    @pytest.mark.readonly
    def test_list_change_log(self, api, url):
        resp = api.get(url("/api/change-log"))
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, (list, dict))

    @pytest.mark.crud
    def test_create_change_log_entry(self, api, url):
        payload = make_change_log_entry()

        resp = api.post(url("/api/change-log"), json=payload)
        assert resp.status_code in (200, 201), f"Create failed: {resp.status_code} {resp.text[:300]}"
        created = resp.json()
        # Response may only return the id
        assert created.get("id"), f"No ID in response: {created}"

    @pytest.mark.readonly
    def test_change_log_filter_by_entity_type(self, api, url):
        resp = api.get(url("/api/change-log"), params={"entity_type": "data_product"})
        assert resp.status_code == 200
