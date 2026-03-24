"""Semantic Models — read-only endpoints."""
import pytest


class TestSemanticModels:

    @pytest.mark.readonly
    def test_list_models(self, api, url):
        resp = api.get(url("/api/semantic-models"))
        assert resp.status_code == 200

    @pytest.mark.readonly
    def test_concepts(self, api, url):
        resp = api.get(url("/api/semantic-models/concepts"))
        assert resp.status_code == 200

    @pytest.mark.readonly
    def test_properties(self, api, url):
        resp = api.get(url("/api/semantic-models/properties"))
        assert resp.status_code == 200

    @pytest.mark.readonly
    def test_stats(self, api, url):
        resp = api.get(url("/api/semantic-models/stats"))
        assert resp.status_code == 200

    @pytest.mark.readonly
    def test_concepts_grouped(self, api, url):
        resp = api.get(url("/api/semantic-models/concepts-grouped"))
        assert resp.status_code == 200

    @pytest.mark.readonly
    def test_properties_grouped(self, api, url):
        resp = api.get(url("/api/semantic-models/properties-grouped"))
        assert resp.status_code == 200

    @pytest.mark.readonly
    def test_knowledge_collections(self, api, url):
        resp = api.get(url("/api/knowledge/collections"))
        assert resp.status_code == 200

    @pytest.mark.readonly
    def test_property_suggestions(self, api, url):
        """GET /api/semantic-models/properties/suggestions — returns list or dict."""
        resp = api.get(
            url("/api/semantic-models/properties/suggestions"),
            params={"q": "test", "limit": 5},
        )
        assert resp.status_code == 200, (
            f"Unexpected status {resp.status_code}: {resp.text[:300]}"
        )
        body = resp.json()
        assert isinstance(body, (list, dict))


class TestSemanticLinks:

    @pytest.mark.readonly
    def test_list_links_for_entity(self, api, url):
        """Smoke-test the semantic links endpoint with a non-existent entity."""
        resp = api.get(url("/api/semantic-links/entity/data_domain/nonexistent"))
        assert resp.status_code in (200, 404)
