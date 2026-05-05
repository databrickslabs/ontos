"""Approvals queue — read-only tests."""
import pytest


class TestApprovals:

    @pytest.mark.readonly
    def test_get_approval_queue(self, api, url):
        resp = api.get(url("/api/approvals/queue"))
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, (list, dict))
