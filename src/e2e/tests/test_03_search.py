"""Search endpoint tests."""
import pytest


class TestSearch:

    @pytest.mark.readonly
    def test_search_returns_200(self, api, url):
        resp = api.get(url("/api/search"), params={"search_term": "test"})
        assert resp.status_code == 200, f"Search failed: {resp.status_code} {resp.text[:200]}"

    @pytest.mark.readonly
    def test_search_empty_query(self, api, url):
        resp = api.get(url("/api/search"), params={"search_term": ""})
        assert resp.status_code in (200, 400, 422)
