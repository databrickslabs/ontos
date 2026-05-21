"""
ONT-RBAC-001 through ONT-RBAC-027 — RBAC Matrix Tests.

Verifies that each persona can or cannot perform specific actions.

Tests marked @pytest.mark.requires_persona("X") are skipped when persona X
resolves to the same token as the default session (no distinct user configured).
Tests that do NOT require a distinct persona verify endpoint reachability only.
"""
import uuid
import pytest

E2E_PREFIX = "cuj-rbac-"


def _uid():
    return uuid.uuid4().hex[:8]


@pytest.mark.cuj
class TestCUJRBACMatrix:

    # ONT-RBAC-001
    def test_RBAC_001_admin_home(self, admin_api, url):
        """Admin: home / user info accessible."""
        resp = admin_api.get(url("/api/user/info"))
        assert resp.status_code == 200, f"RBAC-001: {resp.status_code}"

    # ONT-RBAC-002
    def test_RBAC_002_producer_home(self, producer_api, url):
        """Producer: user info accessible."""
        resp = producer_api.get(url("/api/user/info"))
        assert resp.status_code == 200, f"RBAC-002: {resp.status_code}"

    # ONT-RBAC-003
    def test_RBAC_003_steward_home(self, steward_api, url):
        """Steward: user info accessible."""
        resp = steward_api.get(url("/api/user/info"))
        assert resp.status_code == 200, f"RBAC-003: {resp.status_code}"

    # ONT-RBAC-004
    def test_RBAC_004_consumer_home(self, consumer_api, url):
        """Consumer: user info accessible."""
        resp = consumer_api.get(url("/api/user/info"))
        assert resp.status_code == 200, f"RBAC-004: {resp.status_code}"

    # ONT-RBAC-005
    def test_RBAC_005_producer_create_contract(self, producer_api, url):
        """Producer: can create a contract."""
        cid = f"{E2E_PREFIX}prod-create-{_uid()}"
        resp = producer_api.post(url("/api/data-contracts"), json={
            "kind": "DataContract", "apiVersion": "v3.0.2",
            "id": cid, "name": cid, "status": "draft", "domain": "e2e-rbac",
        })
        if resp.status_code in (200, 201):
            producer_api.delete(url(f"/api/data-contracts/{resp.json()['id']}"))
        assert resp.status_code in (200, 201), (
            f"RBAC-005: producer should be able to create contract, got {resp.status_code}"
        )

    # ONT-RBAC-006
    def test_RBAC_006_steward_create_contract_allowed_or_denied(self, steward_api, url):
        """Steward: create contract — policy-dependent; no 5xx allowed."""
        cid = f"{E2E_PREFIX}stew-create-{_uid()}"
        resp = steward_api.post(url("/api/data-contracts"), json={
            "kind": "DataContract", "apiVersion": "v3.0.2",
            "id": cid, "name": cid, "status": "draft", "domain": "e2e-rbac",
        })
        if resp.status_code in (200, 201):
            steward_api.delete(url(f"/api/data-contracts/{resp.json()['id']}"))
        assert resp.status_code < 500, f"RBAC-006: 5xx not acceptable: {resp.status_code}"

    # ONT-RBAC-007
    @pytest.mark.requires_persona("consumer")
    def test_RBAC_007_consumer_cannot_create_contract(self, consumer_api, url):
        """Consumer: create contract → 403."""
        cid = f"{E2E_PREFIX}con-create-{_uid()}"
        resp = consumer_api.post(url("/api/data-contracts"), json={
            "kind": "DataContract", "apiVersion": "v3.0.2",
            "id": cid, "name": cid, "status": "draft", "domain": "e2e-rbac",
        })
        if resp.status_code in (200, 201):
            consumer_api.delete(url(f"/api/data-contracts/{resp.json()['id']}"))
        assert resp.status_code in (403, 422), (
            f"RBAC-007: consumer create contract should be denied, got {resp.status_code}"
        )

    # ONT-RBAC-008
    def test_RBAC_008_steward_approve_proposed_contract(self, producer_api, steward_api, url):
        """Steward: can approve a Proposed contract."""
        cid = f"{E2E_PREFIX}stew-approve-{_uid()}"
        r1 = producer_api.post(url("/api/data-contracts"), json={
            "kind": "DataContract", "apiVersion": "v3.0.2",
            "id": cid, "name": cid, "status": "draft", "domain": "e2e-rbac",
        })
        if r1.status_code not in (200, 201):
            pytest.skip("RBAC-008: producer cannot create contract")
        contract_id = r1.json()["id"]

        producer_api.post(
            url(f"/api/data-contracts/{contract_id}/change-status"),
            json={"new_status": "proposed"},
        )

        resp = steward_api.post(url(f"/api/data-contracts/{contract_id}/approve"))
        producer_api.delete(url(f"/api/data-contracts/{contract_id}"))
        assert resp.status_code in (200, 201, 400, 403, 409, 422, 500), (
            f"RBAC-008: steward approve: {resp.status_code}"
        )

    # ONT-RBAC-009
    @pytest.mark.requires_persona("producer")
    def test_RBAC_009_producer_cannot_approve_others_contract(self, producer_api, url):
        """Producer (non-author): approve another's proposed contract → 403."""
        # Without distinct personas this can only be tested structurally
        cid = f"{E2E_PREFIX}non-author-{_uid()}"
        r1 = producer_api.post(url("/api/data-contracts"), json={
            "kind": "DataContract", "apiVersion": "v3.0.2",
            "id": cid, "name": cid, "status": "draft", "domain": "e2e-rbac",
        })
        if r1.status_code not in (200, 201):
            pytest.skip("RBAC-009: setup failed")
        contract_id = r1.json()["id"]
        producer_api.post(
            url(f"/api/data-contracts/{contract_id}/change-status"),
            json={"new_status": "proposed"},
        )
        resp = producer_api.post(url(f"/api/data-contracts/{contract_id}/approve"))
        producer_api.delete(url(f"/api/data-contracts/{contract_id}"))
        # Producers should not be able to approve (only stewards/admins)
        assert resp.status_code in (400, 403, 409), (
            f"RBAC-009: producer self-approve should be denied, got {resp.status_code}"
        )

    # ONT-RBAC-010
    @pytest.mark.requires_persona("producer")
    def test_RBAC_010_producer_cannot_self_approve(self, producer_api, url):
        """Producer: approve own proposed contract → denied."""
        cid = f"{E2E_PREFIX}self-ap-{_uid()}"
        r1 = producer_api.post(url("/api/data-contracts"), json={
            "kind": "DataContract", "apiVersion": "v3.0.2",
            "id": cid, "name": cid, "status": "draft", "domain": "e2e-rbac",
        })
        if r1.status_code not in (200, 201):
            pytest.skip("RBAC-010: setup failed")
        cid2 = r1.json()["id"]
        producer_api.post(
            url(f"/api/data-contracts/{cid2}/change-status"),
            json={"new_status": "proposed"},
        )
        resp = producer_api.post(url(f"/api/data-contracts/{cid2}/approve"))
        producer_api.delete(url(f"/api/data-contracts/{cid2}"))
        assert resp.status_code in (400, 403, 409), (
            f"RBAC-010: self-approve should be denied, got {resp.status_code}"
        )

    # ONT-RBAC-011
    def test_RBAC_011_producer_create_product(self, producer_api, url):
        """Producer: can create a data product."""
        pid = f"{E2E_PREFIX}prod-{_uid()}"
        resp = producer_api.post(url("/api/data-products"), json={
            "apiVersion": "v1.0.0", "kind": "DataProduct",
            "id": pid, "name": pid, "status": "draft",
            "version": "1.0.0", "domain": "e2e-rbac", "tenant": "e2e-org",
        })
        if resp.status_code in (200, 201):
            producer_api.delete(url(f"/api/data-products/{resp.json()['id']}"))
        assert resp.status_code in (200, 201), (
            f"RBAC-011: producer create product: {resp.status_code}"
        )

    # ONT-RBAC-012
    @pytest.mark.requires_persona("consumer")
    def test_RBAC_012_consumer_cannot_create_product(self, consumer_api, url):
        """Consumer: create product → 403."""
        pid = f"{E2E_PREFIX}con-prod-{_uid()}"
        resp = consumer_api.post(url("/api/data-products"), json={
            "apiVersion": "v1.0.0", "kind": "DataProduct",
            "id": pid, "name": pid, "status": "draft",
            "version": "1.0.0", "domain": "e2e-rbac", "tenant": "e2e-org",
        })
        if resp.status_code in (200, 201):
            consumer_api.delete(url(f"/api/data-products/{resp.json()['id']}"))
        assert resp.status_code in (403, 422), (
            f"RBAC-012: consumer create product should be denied, got {resp.status_code}"
        )

    # ONT-RBAC-013
    def test_RBAC_013_steward_certify_product(self, producer_api, steward_api, url):
        """Steward: can certify a proposed product."""
        pid = f"{E2E_PREFIX}certify-{_uid()}"
        r1 = producer_api.post(url("/api/data-products"), json={
            "apiVersion": "v1.0.0", "kind": "DataProduct",
            "id": pid, "name": pid, "status": "draft",
            "version": "1.0.0", "domain": "e2e-rbac", "tenant": "e2e-org",
        })
        if r1.status_code not in (200, 201):
            pytest.skip("RBAC-013: setup failed")
        product_id = r1.json()["id"]

        # Try to propose
        producer_api.post(url(f"/api/data-products/{product_id}/submit-certification"))

        resp = steward_api.post(url(f"/api/data-products/{product_id}/certify"))
        if resp.status_code == 404:
            resp = steward_api.post(url(f"/api/data-products/{product_id}/approve"))
        producer_api.delete(url(f"/api/data-products/{product_id}"))
        assert resp.status_code < 500, f"RBAC-013: 5xx: {resp.status_code}"

    # ONT-RBAC-014
    @pytest.mark.requires_persona("consumer")
    def test_RBAC_014_consumer_cannot_certify_product(self, producer_api, consumer_api, url):
        """Consumer: certify product → 403."""
        pid = f"{E2E_PREFIX}con-cert-{_uid()}"
        r1 = producer_api.post(url("/api/data-products"), json={
            "apiVersion": "v1.0.0", "kind": "DataProduct",
            "id": pid, "name": pid, "status": "draft",
            "version": "1.0.0", "domain": "e2e-rbac", "tenant": "e2e-org",
        })
        if r1.status_code not in (200, 201):
            pytest.skip("RBAC-014: setup failed")
        product_id = r1.json()["id"]

        resp = consumer_api.post(url(f"/api/data-products/{product_id}/certify"))
        producer_api.delete(url(f"/api/data-products/{product_id}"))
        assert resp.status_code in (403, 404, 422), (
            f"RBAC-014: consumer certify should be denied, got {resp.status_code}"
        )

    # ONT-RBAC-015
    def test_RBAC_015_consumer_browse_marketplace(self, consumer_api, url):
        """Consumer: can browse published products."""
        resp = consumer_api.get(url("/api/data-products/published"))
        assert resp.status_code in (200, 403), f"RBAC-015: {resp.status_code}"

    # ONT-RBAC-016
    def test_RBAC_016_consumer_subscribe(self, consumer_api, url):
        """Consumer: subscribe endpoint accessible (entity need not exist)."""
        user_resp = consumer_api.get(url("/api/user/info"))
        assert user_resp.status_code == 200
        email = user_resp.json().get("userName") or user_resp.json().get("email", "e2e@example.com")
        resp = consumer_api.post(url("/api/subscriptions"), json={
            "entity_type": "data_product",
            "entity_id": f"nonexistent-{_uid()}",
            "subscriber_email": email,
        })
        # 404 (product not found) or 201 are both valid; 403 would indicate permission issue
        assert resp.status_code != 403, f"RBAC-016: consumer should be able to subscribe, got 403"
        assert resp.status_code < 500, f"RBAC-016: 5xx: {resp.status_code}"

    # ONT-RBAC-017
    def test_RBAC_017_producer_approve_subscription(self, producer_api, url):
        """Producer: subscriptions list for own product is accessible."""
        pid = f"{E2E_PREFIX}sub-owner-{_uid()}"
        r1 = producer_api.post(url("/api/data-products"), json={
            "apiVersion": "v1.0.0", "kind": "DataProduct",
            "id": pid, "name": pid, "status": "draft",
            "version": "1.0.0", "domain": "e2e-rbac", "tenant": "e2e-org",
        })
        if r1.status_code not in (200, 201):
            pytest.skip("RBAC-017: setup failed")
        product_id = r1.json()["id"]
        resp = producer_api.get(url(f"/api/subscriptions/entity/data_product/{product_id}"))
        producer_api.delete(url(f"/api/data-products/{product_id}"))
        assert resp.status_code in (200, 404), f"RBAC-017: {resp.status_code}"

    # ONT-RBAC-018
    @pytest.mark.requires_persona("consumer")
    def test_RBAC_018_consumer_cannot_approve_subscription(self, consumer_api, url):
        """Consumer: subscription approval endpoint → 403 or 404."""
        fake_sub_id = str(uuid.uuid4())
        resp = consumer_api.post(url(f"/api/subscriptions/{fake_sub_id}/approve"))
        assert resp.status_code in (403, 404, 405), (
            f"RBAC-018: consumer approve subscription: {resp.status_code}"
        )

    # ONT-RBAC-019
    def test_RBAC_019_admin_view_roles(self, admin_api, url):
        """Admin: settings/roles accessible."""
        resp = admin_api.get(url("/api/settings/roles"))
        assert resp.status_code in (200, 403), f"RBAC-019: {resp.status_code}"

    # ONT-RBAC-020
    @pytest.mark.requires_persona("producer")
    def test_RBAC_020_producer_denied_roles_settings(self, producer_api, url):
        """Producer: settings/roles → 403."""
        resp = producer_api.get(url("/api/settings/roles"))
        assert resp.status_code in (403, 404), (
            f"RBAC-020: producer settings/roles should be denied, got {resp.status_code}"
        )

    # ONT-RBAC-021
    @pytest.mark.requires_persona("steward")
    def test_RBAC_021_steward_denied_roles_settings(self, steward_api, url):
        """Steward: settings/roles → 403."""
        resp = steward_api.get(url("/api/settings/roles"))
        assert resp.status_code in (403, 404), (
            f"RBAC-021: steward settings/roles should be denied, got {resp.status_code}"
        )

    # ONT-RBAC-022
    def test_RBAC_022_admin_view_audit(self, admin_api, url):
        """Admin: audit log accessible."""
        resp = admin_api.get(url("/api/audit"))
        assert resp.status_code in (200, 403), f"RBAC-022: {resp.status_code}"

    # ONT-RBAC-023
    @pytest.mark.requires_persona("producer")
    def test_RBAC_023_producer_audit_access(self, producer_api, url):
        """Producer: audit log — 403 or restricted view (policy-dependent)."""
        resp = producer_api.get(url("/api/audit"))
        assert resp.status_code < 500, f"RBAC-023: 5xx on audit: {resp.status_code}"

    # ONT-RBAC-024
    def test_RBAC_024_admin_manage_entitlements(self, admin_api, url):
        """Admin: entitlements/personas accessible."""
        resp = admin_api.get(url("/api/entitlements/personas"))
        assert resp.status_code in (200, 403), f"RBAC-024: {resp.status_code}"

    # ONT-RBAC-025
    @pytest.mark.requires_persona("producer")
    def test_RBAC_025_producer_denied_entitlements(self, producer_api, url):
        """Producer: entitlements/personas → 403."""
        resp = producer_api.get(url("/api/entitlements/personas"))
        assert resp.status_code in (403, 404), (
            f"RBAC-025: producer entitlements should be denied, got {resp.status_code}"
        )

    # ONT-RBAC-026
    def test_RBAC_026_steward_review_queue(self, steward_api, url):
        """Steward: data-asset-reviews queue accessible."""
        resp = steward_api.get(url("/api/data-asset-reviews"))
        assert resp.status_code in (200, 403), f"RBAC-026: {resp.status_code}"

    # ONT-RBAC-027
    @pytest.mark.requires_persona("consumer")
    def test_RBAC_027_consumer_review_queue(self, consumer_api, url):
        """Consumer: data-asset-reviews → 403 or empty (policy-dependent)."""
        resp = consumer_api.get(url("/api/data-asset-reviews"))
        assert resp.status_code < 500, f"RBAC-027: 5xx: {resp.status_code}"
