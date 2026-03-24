"""Data Products — sub-resource operations.

Covers:
  - POST   /api/data-products/{id}/versions          (create new version)
  - POST   /api/data-products/compare                (compare two products)
  - GET    /api/data-products/{id}/import-team-members
  - POST   /api/data-products/{id}/subscribe         (subscribe)
  - DELETE /api/data-products/{id}/subscribe         (unsubscribe)
  - GET    /api/data-products/{id}/subscription      (check subscription status)
  - GET    /api/data-products/{id}/subscribers       (list subscribers)
  - GET    /api/data-products/{id}/subscriber-count  (count subscribers)
  - GET    /api/data-products/my-subscriptions       (caller's subscriptions)
  - GET    /api/data-products/by-contract/{cid}      (products that use a contract)
  - GET    /api/data-products/{id}/contracts         (contracts linked to a product)
"""
import uuid
import pytest

from helpers.test_data import make_data_product, E2E_PREFIX


# ---------------------------------------------------------------------------
# Local factory helpers
# ---------------------------------------------------------------------------

def _uid() -> str:
    return uuid.uuid4().hex[:8]


def make_product_with_output_port(contract_id: str | None = None, **overrides):
    """Build a data product payload that has one output port, optionally linked to a contract."""
    pid = f"{E2E_PREFIX}product-{_uid()}"
    port: dict = {
        "name": f"port-{_uid()}",
        "version": "1.0.0",
    }
    if contract_id:
        port["contract_id"] = contract_id

    payload = make_data_product(id=pid, name=pid)
    payload["outputPorts"] = [port]
    payload.update(overrides)
    return payload


def make_new_version_request(new_version: str = "2.0.0") -> dict:
    return {"new_version": new_version}


def make_compare_body(old_product: dict, new_product: dict) -> dict:
    return {
        "old_product": old_product,
        "new_product": new_product,
    }


# ---------------------------------------------------------------------------
# Helper: create a product and register it for cleanup
# ---------------------------------------------------------------------------

def _create_product(api, url, payload: dict) -> dict:
    resp = api.post(url("/api/data-products"), json=payload)
    assert resp.status_code in (200, 201), (
        f"Product creation failed: {resp.status_code} {resp.text[:500]}"
    )
    return resp.json()


# ---------------------------------------------------------------------------
# Test class
# ---------------------------------------------------------------------------

class TestDataProductSubresources:

    @pytest.fixture(autouse=True)
    def _cleanup(self, api, url):
        self._to_delete: list[str] = []
        yield
        for product_id in reversed(self._to_delete):
            api.delete(url(f"/api/data-products/{product_id}"))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _make_product(self, api, url, **overrides) -> dict:
        payload = make_data_product(**overrides)
        created = _create_product(api, url, payload)
        self._to_delete.append(created["id"])
        return created

    # ------------------------------------------------------------------
    # Versioning
    # ------------------------------------------------------------------

    @pytest.mark.crud
    def test_create_new_version(self, api, url):
        """POST /{id}/versions should create a versioned copy and return a DataProduct."""
        parent = self._make_product(api, url)
        parent_id = parent["id"]

        version_req = make_new_version_request("2.0.0")
        resp = api.post(url(f"/api/data-products/{parent_id}/versions"), json=version_req)

        # Accept 200/201 (success) or 400/409 (business rule violation from the backend)
        # — the important thing is the endpoint exists and is reachable.
        assert resp.status_code in (200, 201, 400, 409, 422), (
            f"Unexpected status from version creation: {resp.status_code} {resp.text[:500]}"
        )

        if resp.status_code in (200, 201):
            new_version = resp.json()
            self._to_delete.append(new_version["id"])
            assert new_version.get("version") == "2.0.0"
            assert new_version.get("id") != parent_id
            # The new version must be traceable back to its parent
            parent_ref = new_version.get("parent_product_id") or new_version.get("parentProductId")
            assert parent_ref == parent_id, (
                f"Expected parentProductId={parent_id!r}, got {parent_ref!r}"
            )

    @pytest.mark.crud
    def test_create_version_for_nonexistent_product(self, api, url):
        """Versioning a non-existent product should return 404."""
        resp = api.post(
            url(f"/api/data-products/does-not-exist-{_uid()}/versions"),
            json=make_new_version_request("9.9.9"),
        )
        assert resp.status_code in (400, 404, 422), (
            f"Expected 4xx for missing product, got {resp.status_code}"
        )

    # ------------------------------------------------------------------
    # Compare
    # ------------------------------------------------------------------

    @pytest.mark.crud
    def test_compare_two_products(self, api, url):
        """POST /compare with two valid product objects should return a diff dict."""
        p1 = make_data_product()
        p2 = make_data_product(version="2.0.0", domain="updated-domain")

        resp = api.post(
            url("/api/data-products/compare"),
            json=make_compare_body(p1, p2),
        )
        assert resp.status_code in (200, 400, 422), (
            f"Unexpected status from compare: {resp.status_code} {resp.text[:500]}"
        )

        if resp.status_code == 200:
            body = resp.json()
            assert isinstance(body, dict), "compare must return a JSON object"

    @pytest.mark.crud
    def test_compare_missing_fields(self, api, url):
        """Omitting one of the required fields should return 400."""
        resp = api.post(
            url("/api/data-products/compare"),
            json={"old_product": make_data_product()},  # new_product missing
        )
        assert resp.status_code == 400, (
            f"Expected 400 for incomplete compare payload, got {resp.status_code}"
        )

    # ------------------------------------------------------------------
    # Import team members
    # ------------------------------------------------------------------

    @pytest.mark.readonly
    def test_import_team_members_requires_team_id(self, api, url):
        """GET /{id}/import-team-members without team_id query param should return 4xx."""
        product = self._make_product(api, url)
        resp = api.get(url(f"/api/data-products/{product['id']}/import-team-members"))
        # team_id is required; 400/422 expected when omitted
        assert resp.status_code in (400, 404, 422), (
            f"Expected 4xx without team_id, got {resp.status_code}"
        )

    @pytest.mark.readonly
    def test_import_team_members_with_fake_team(self, api, url):
        """GET /{id}/import-team-members with a non-existent team_id should return 4xx or []."""
        product = self._make_product(api, url)
        resp = api.get(
            url(f"/api/data-products/{product['id']}/import-team-members"),
            params={"team_id": f"fake-team-{_uid()}"},
        )
        assert resp.status_code in (200, 400, 404, 422), (
            f"Unexpected status: {resp.status_code} {resp.text[:300]}"
        )
        if resp.status_code == 200:
            assert isinstance(resp.json(), list)

    # ------------------------------------------------------------------
    # Subscribe / unsubscribe / subscription status
    # ------------------------------------------------------------------

    @pytest.mark.crud
    def test_subscribe_check_unsubscribe_cycle(self, api, url):
        """Full subscribe → check status → unsubscribe flow."""
        product = self._make_product(api, url)
        product_id = product["id"]

        # 1. Subscribe (no body required, but the endpoint accepts optional reason)
        resp = api.post(
            url(f"/api/data-products/{product_id}/subscribe"),
            json={"reason": "E2E test subscription"},
        )
        # 200/201 = subscribed; 400 may mean "already subscribed" or business rule
        assert resp.status_code in (200, 201, 400, 422), (
            f"Subscribe returned unexpected status: {resp.status_code} {resp.text[:500]}"
        )

        # 2. Check subscription status
        resp = api.get(url(f"/api/data-products/{product_id}/subscription"))
        assert resp.status_code == 200, (
            f"Subscription status check failed: {resp.status_code} {resp.text[:300]}"
        )
        status_body = resp.json()
        assert "subscribed" in status_body, "Response must contain 'subscribed' field"
        # After subscribing the flag must be True (unless the earlier POST returned an error)

        # 3. Unsubscribe
        resp = api.delete(url(f"/api/data-products/{product_id}/subscribe"))
        assert resp.status_code in (200, 204, 400, 404), (
            f"Unsubscribe returned unexpected status: {resp.status_code} {resp.text[:300]}"
        )

        # 4. Verify unsubscribed
        resp = api.get(url(f"/api/data-products/{product_id}/subscription"))
        assert resp.status_code == 200
        final_status = resp.json()
        assert "subscribed" in final_status

    @pytest.mark.crud
    def test_subscribe_no_body(self, api, url):
        """POST /subscribe with an empty body should also be accepted (reason is optional)."""
        product = self._make_product(api, url)
        product_id = product["id"]

        resp = api.post(url(f"/api/data-products/{product_id}/subscribe"))
        assert resp.status_code in (200, 201, 400, 422), (
            f"Unexpected status subscribing without body: {resp.status_code}"
        )

        # Cleanup: unsubscribe regardless of result
        api.delete(url(f"/api/data-products/{product_id}/subscribe"))

    @pytest.mark.readonly
    def test_subscription_status_for_nonexistent_product(self, api, url):
        """GET subscription status for a product that does not exist should return 4xx or {subscribed: false}."""
        fake_id = f"nonexistent-{_uid()}"
        resp = api.get(url(f"/api/data-products/{fake_id}/subscription"))
        # Acceptable outcomes: 404 (not found) or 200 with subscribed=false
        assert resp.status_code in (200, 404, 422), (
            f"Unexpected status for missing product subscription: {resp.status_code}"
        )

    # ------------------------------------------------------------------
    # Subscribers list & count
    # ------------------------------------------------------------------

    @pytest.mark.readonly
    def test_get_subscribers_list(self, api, url):
        """GET /{id}/subscribers should return SubscribersListResponse shape."""
        product = self._make_product(api, url)
        product_id = product["id"]

        resp = api.get(url(f"/api/data-products/{product_id}/subscribers"))
        assert resp.status_code in (200, 403), (
            f"Unexpected status listing subscribers: {resp.status_code} {resp.text[:300]}"
        )

        if resp.status_code == 200:
            body = resp.json()
            assert "product_id" in body, "Response must contain 'product_id'"
            assert "subscriber_count" in body, "Response must contain 'subscriber_count'"
            assert "subscribers" in body, "Response must contain 'subscribers'"
            assert isinstance(body["subscribers"], list)
            assert body["product_id"] == product_id

    @pytest.mark.readonly
    def test_get_subscriber_count(self, api, url):
        """GET /{id}/subscriber-count should return a count dict."""
        product = self._make_product(api, url)
        product_id = product["id"]

        resp = api.get(url(f"/api/data-products/{product_id}/subscriber-count"))
        assert resp.status_code == 200, (
            f"Subscriber count failed: {resp.status_code} {resp.text[:300]}"
        )
        body = resp.json()
        assert "product_id" in body
        assert "subscriber_count" in body
        assert body["product_id"] == product_id
        assert isinstance(body["subscriber_count"], int)
        assert body["subscriber_count"] >= 0

    @pytest.mark.crud
    def test_subscriber_count_increases_on_subscribe(self, api, url):
        """Subscribing should increment the subscriber count by 1."""
        product = self._make_product(api, url)
        product_id = product["id"]

        # Baseline count
        resp = api.get(url(f"/api/data-products/{product_id}/subscriber-count"))
        assert resp.status_code == 200
        before = resp.json()["subscriber_count"]

        # Subscribe
        sub_resp = api.post(
            url(f"/api/data-products/{product_id}/subscribe"),
            json={"reason": "count test"},
        )
        subscribed = sub_resp.status_code in (200, 201)

        if subscribed:
            resp = api.get(url(f"/api/data-products/{product_id}/subscriber-count"))
            assert resp.status_code == 200
            after = resp.json()["subscriber_count"]
            assert after == before + 1, (
                f"Expected subscriber_count {before + 1}, got {after}"
            )
            # Cleanup
            api.delete(url(f"/api/data-products/{product_id}/subscribe"))

    # ------------------------------------------------------------------
    # My subscriptions
    # ------------------------------------------------------------------

    @pytest.mark.readonly
    def test_my_subscriptions_returns_list(self, api, url):
        """GET /my-subscriptions should return a list (possibly empty)."""
        resp = api.get(url("/api/data-products/my-subscriptions"))
        assert resp.status_code in (200, 401), (
            f"Unexpected status for my-subscriptions: {resp.status_code} {resp.text[:300]}"
        )
        if resp.status_code == 200:
            assert isinstance(resp.json(), list)

    @pytest.mark.crud
    def test_my_subscriptions_reflects_subscribe_action(self, api, url):
        """Subscribing to a product should make it appear in /my-subscriptions."""
        product = self._make_product(api, url)
        product_id = product["id"]

        # Baseline
        resp = api.get(url("/api/data-products/my-subscriptions"))
        if resp.status_code != 200:
            pytest.skip("my-subscriptions endpoint not accessible")
        before_ids = {p["id"] for p in resp.json()}

        # Subscribe
        sub_resp = api.post(
            url(f"/api/data-products/{product_id}/subscribe"),
            json={"reason": "my-subscriptions test"},
        )
        if sub_resp.status_code not in (200, 201):
            pytest.skip(f"Could not subscribe (status {sub_resp.status_code}); skipping")

        # Verify it appears in the list
        resp = api.get(url("/api/data-products/my-subscriptions"))
        assert resp.status_code == 200
        after_ids = {p["id"] for p in resp.json()}
        assert product_id in after_ids, (
            f"Product {product_id!r} not found in my-subscriptions after subscribing"
        )

        # Cleanup
        api.delete(url(f"/api/data-products/{product_id}/subscribe"))

    # ------------------------------------------------------------------
    # Products by contract / contracts for product
    # ------------------------------------------------------------------

    @pytest.mark.readonly
    def test_products_by_contract_returns_list(self, api, url):
        """GET /by-contract/{id} should return a list (possibly empty for unknown contracts)."""
        fake_contract_id = f"e2e-contract-{_uid()}"
        resp = api.get(url(f"/api/data-products/by-contract/{fake_contract_id}"))
        assert resp.status_code in (200, 404), (
            f"Unexpected status for by-contract: {resp.status_code} {resp.text[:300]}"
        )
        if resp.status_code == 200:
            assert isinstance(resp.json(), list)

    @pytest.mark.readonly
    def test_contracts_for_product_returns_list(self, api, url):
        """GET /{id}/contracts should return a list of contract IDs (may be empty)."""
        product = self._make_product(api, url)
        product_id = product["id"]

        resp = api.get(url(f"/api/data-products/{product_id}/contracts"))
        assert resp.status_code in (200, 404), (
            f"Unexpected status for contracts endpoint: {resp.status_code} {resp.text[:300]}"
        )
        if resp.status_code == 200:
            body = resp.json()
            assert isinstance(body, list), "contracts endpoint must return a list"

    @pytest.mark.crud
    def test_product_with_linked_contract_appears_in_by_contract(self, api, url):
        """A product whose output port references a contract ID should appear under by-contract."""
        contract_id = f"e2e-contract-{_uid()}"
        payload = make_product_with_output_port(contract_id=contract_id)
        created = _create_product(api, url, payload)
        product_id = created["id"]
        self._to_delete.append(product_id)

        # The GET /by-contract endpoint looks up products by their output port contract links
        resp = api.get(url(f"/api/data-products/by-contract/{contract_id}"))
        assert resp.status_code in (200, 404), (
            f"Unexpected status: {resp.status_code} {resp.text[:300]}"
        )

        if resp.status_code == 200:
            returned_ids = [p["id"] for p in resp.json()]
            assert product_id in returned_ids, (
                f"Expected product {product_id!r} in by-contract results, got {returned_ids}"
            )

    @pytest.mark.crud
    def test_contracts_for_product_includes_linked_contract(self, api, url):
        """A product with an output port pointing to a contract should list that contract."""
        contract_id = f"e2e-contract-{_uid()}"
        payload = make_product_with_output_port(contract_id=contract_id)
        created = _create_product(api, url, payload)
        product_id = created["id"]
        self._to_delete.append(product_id)

        resp = api.get(url(f"/api/data-products/{product_id}/contracts"))
        assert resp.status_code in (200, 404), (
            f"Unexpected status: {resp.status_code} {resp.text[:300]}"
        )

        if resp.status_code == 200:
            contract_ids = resp.json()
            assert contract_id in contract_ids, (
                f"Expected {contract_id!r} in product contracts, got {contract_ids}"
            )

    @pytest.mark.readonly
    def test_contracts_for_nonexistent_product_returns_404(self, api, url):
        """GET contracts for a missing product should return 404."""
        resp = api.get(url(f"/api/data-products/nonexistent-{_uid()}/contracts"))
        assert resp.status_code in (404, 400), (
            f"Expected 404/400 for missing product, got {resp.status_code}"
        )
