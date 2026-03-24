"""Costs — entity-scoped CRUD using a data domain as anchor."""
import pytest

from helpers.test_data import make_domain, make_cost_item


class TestCosts:

    @pytest.fixture(autouse=True)
    def _setup_entity(self, api, url):
        """Create a domain to attach cost items to."""
        payload = make_domain()
        resp = api.post(url("/api/data-domains"), json=payload)
        assert resp.status_code in (200, 201)
        self._entity_type = "data_domain"
        self._entity_id = resp.json()["id"]
        self._cost_ids = []
        yield
        for cid in reversed(self._cost_ids):
            api.delete(url(f"/api/cost-items/{cid}"))
        api.delete(url(f"/api/data-domains/{self._entity_id}"))

    @pytest.mark.crud
    def test_cost_item_crud(self, api, url):
        payload = make_cost_item(self._entity_type, self._entity_id)

        # CREATE
        resp = api.post(
            url(f"/api/entities/{self._entity_type}/{self._entity_id}/cost-items"),
            json=payload,
        )
        assert resp.status_code in (200, 201), f"Create failed: {resp.status_code} {resp.text[:300]}"
        created = resp.json()
        cost_id = created.get("id")
        assert cost_id, f"No ID in response: {created}"
        self._cost_ids.append(cost_id)

        # Verify key fields
        assert created.get("title") == payload["title"]
        assert created.get("amount_cents") == payload["amount_cents"] or \
               str(created.get("amount_cents")) == str(payload["amount_cents"])

        # LIST
        resp = api.get(url(f"/api/entities/{self._entity_type}/{self._entity_id}/cost-items"))
        assert resp.status_code == 200
        items = resp.json()
        assert any(i.get("id") == cost_id for i in items), "Cost item not in list"

        # UPDATE
        resp = api.put(url(f"/api/cost-items/{cost_id}"), json={
            "title": "Updated E2E Cost",
            "amount_cents": 9999,
        })
        assert resp.status_code == 200, f"Update failed: {resp.status_code} {resp.text[:300]}"
        updated = resp.json()
        assert updated.get("title") == "Updated E2E Cost"

        # SUMMARY
        resp = api.get(
            url(f"/api/entities/{self._entity_type}/{self._entity_id}/cost-items/summary"),
            params={"month": "2026-01"},
        )
        assert resp.status_code == 200

        # DELETE
        resp = api.delete(url(f"/api/cost-items/{cost_id}"))
        assert resp.status_code in (200, 204)
        self._cost_ids.remove(cost_id)
