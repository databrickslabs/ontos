"""Access Grants — read-only config and listing endpoints."""
import pytest


class TestAccessGrants:

    @pytest.mark.readonly
    def test_get_config(self, api, url):
        resp = api.get(url("/api/access-grants/config"))
        assert resp.status_code == 200

    @pytest.mark.readonly
    def test_get_my_grants(self, api, url):
        resp = api.get(url("/api/access-grants/my"))
        assert resp.status_code == 200

    @pytest.mark.readonly
    def test_get_my_grants_summary(self, api, url):
        resp = api.get(url("/api/access-grants/my/summary"))
        assert resp.status_code == 200

    @pytest.mark.readonly
    def test_get_my_requests(self, api, url):
        resp = api.get(url("/api/access-grants/requests/my"))
        assert resp.status_code == 200

    @pytest.mark.readonly
    def test_get_pending_requests(self, api, url):
        resp = api.get(url("/api/access-grants/requests/pending"))
        assert resp.status_code == 200
