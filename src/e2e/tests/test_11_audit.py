"""Audit log — read-only tests."""
import pytest


class TestAudit:

    @pytest.mark.readonly
    def test_get_audit_log(self, api, url):
        resp = api.get(url("/api/audit"))
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, (list, dict))
