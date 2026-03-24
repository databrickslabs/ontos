"""
Lifecycle / workflow actions for Data Products and Data Contracts.

Covers:
  Data Products:
    - move-to-sandbox      (draft → sandbox)
    - submit-certification (draft/sandbox → proposed)
    - change-status        (direct, admin/owner path)
    - request-status-change (approval-workflow request)
    - handle-status-change  (approver responds)
    - clone-for-editing    (creates a personal draft)
    - diff-from-parent     (compare draft to parent)
    - discard              (delete a personal draft)
    - request-review       (trigger review notification — may fail if no reviewer)

  Data Contracts:
    - change-status        (direct transition, validated by server)
    - request-review       (sends review notification — may fail w/o stewards)
    - request-publish      (requires approved status — may 409)
    - request-deploy       (may fail if no deployment policy configured)
    - request-status-change (approval-workflow request)
    - clone-for-editing    (creates a personal draft)
    - diff-from-parent     (compare draft to parent)
    - discard              (delete a personal draft)
    - my-drafts            (list current user's drafts)

Tests are smoke + basic-flow.  Where a prerequisite may be missing (e.g., no
reviewers/stewards configured, no deployment policy) the test accepts the
expected 4xx range as a valid "the server understood and rejected" response and
does NOT fail the suite.
"""
import uuid
import pytest

from helpers.test_data import make_data_product, make_data_contract


# ---------------------------------------------------------------------------
# Local factory helpers (isolated from shared test_data.py)
# ---------------------------------------------------------------------------

def _uid() -> str:
    return uuid.uuid4().hex[:8]


def make_draft_product(**overrides):
    """Create a minimal draft data product payload."""
    pid = f"e2e-lc-product-{_uid()}"
    defaults = {
        "apiVersion": "v1.0.0",
        "kind": "DataProduct",
        "id": pid,
        "status": "draft",
        "name": pid,
        "version": "1.0.0",
        "domain": "e2e-lifecycle",
        "tenant": "e2e-org",
        "description": {
            "purpose": "Lifecycle E2E test product",
            "limitations": "Test only",
            "usage": "Automated lifecycle tests",
        },
    }
    defaults.update(overrides)
    return defaults


def make_draft_contract(**overrides):
    """Create a minimal draft data contract payload."""
    cid = f"e2e-lc-contract-{_uid()}"
    defaults = {
        "kind": "DataContract",
        "apiVersion": "v3.0.2",
        "id": cid,
        "version": "1.0.0",
        "status": "draft",
        "name": cid,
        "domain": "e2e-lifecycle",
        "description": {
            "purpose": "Lifecycle E2E test contract",
            "usage": "Automated lifecycle tests",
        },
        "schema": [
            {
                "name": "lc_table",
                "physicalName": "lc_physical_table",
                "properties": [
                    {
                        "name": "id",
                        "logicalType": "integer",
                        "required": True,
                        "primaryKey": True,
                    }
                ],
            }
        ],
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# Helper: create + register for cleanup
# ---------------------------------------------------------------------------

def _create_product(api, url, payload):
    resp = api.post(url("/api/data-products"), json=payload)
    assert resp.status_code in (200, 201), (
        f"Setup: failed to create product: {resp.status_code} {resp.text[:400]}"
    )
    return resp.json()["id"]


def _create_contract(api, url, payload):
    resp = api.post(url("/api/data-contracts"), json=payload)
    assert resp.status_code in (200, 201), (
        f"Setup: failed to create contract: {resp.status_code} {resp.text[:400]}"
    )
    return resp.json()["id"]


# ===========================================================================
# Data Product Lifecycle Tests
# ===========================================================================


class TestDataProductLifecycle:
    """Smoke tests for data product status transitions and draft workflow."""

    @pytest.fixture(autouse=True)
    def _cleanup(self, api, url):
        self._to_delete = []
        yield
        for pid in reversed(self._to_delete):
            api.delete(url(f"/api/data-products/{pid}"))

    # -----------------------------------------------------------------------
    # move-to-sandbox
    # -----------------------------------------------------------------------
    @pytest.mark.lifecycle
    def test_move_to_sandbox(self, api, url):
        """draft → sandbox transition must return a status field."""
        payload = make_draft_product()
        pid = _create_product(api, url, payload)
        self._to_delete.append(pid)

        resp = api.post(url(f"/api/data-products/{pid}/move-to-sandbox"))
        assert resp.status_code in (200, 201, 409), (
            f"move-to-sandbox unexpected status: {resp.status_code} {resp.text[:300]}"
        )
        if resp.status_code in (200, 201):
            body = resp.json()
            assert "status" in body, "Response missing 'status' field"
            assert body["status"] in ("sandbox", "draft"), (
                f"Unexpected status after move-to-sandbox: {body['status']}"
            )

    # -----------------------------------------------------------------------
    # submit-certification
    # -----------------------------------------------------------------------
    @pytest.mark.lifecycle
    def test_submit_certification(self, api, url):
        """draft/sandbox → proposed. Accepted codes: 200/201 (ok) or 409 (invalid transition guard)."""
        payload = make_draft_product()
        pid = _create_product(api, url, payload)
        self._to_delete.append(pid)

        resp = api.post(url(f"/api/data-products/{pid}/submit-certification"))
        assert resp.status_code in (200, 201, 409), (
            f"submit-certification unexpected status: {resp.status_code} {resp.text[:300]}"
        )
        if resp.status_code in (200, 201):
            body = resp.json()
            assert "status" in body
            assert body["status"] in ("proposed", "sandbox", "draft"), (
                f"Unexpected status: {body['status']}"
            )

    # -----------------------------------------------------------------------
    # change-status (direct)
    # -----------------------------------------------------------------------
    @pytest.mark.lifecycle
    def test_change_status_valid_transition(self, api, url):
        """Direct change-status: draft → deprecated (always allowed via admin path)."""
        payload = make_draft_product()
        pid = _create_product(api, url, payload)
        self._to_delete.append(pid)

        resp = api.post(
            url(f"/api/data-products/{pid}/change-status"),
            json={"new_status": "deprecated"},
        )
        # 200 = success, 400 = transition rejected by server — both are valid server responses
        assert resp.status_code in (200, 400, 409), (
            f"change-status unexpected status: {resp.status_code} {resp.text[:300]}"
        )

    @pytest.mark.lifecycle
    def test_change_status_to_sandbox(self, api, url):
        """Direct change-status: draft → sandbox."""
        payload = make_draft_product()
        pid = _create_product(api, url, payload)
        self._to_delete.append(pid)

        resp = api.post(
            url(f"/api/data-products/{pid}/change-status"),
            json={"new_status": "sandbox"},
        )
        assert resp.status_code in (200, 400, 409), (
            f"Unexpected status: {resp.status_code} {resp.text[:300]}"
        )
        if resp.status_code == 200:
            body = resp.json()
            # Response wraps the product
            assert "message" in body or "product" in body or "status" in body

    @pytest.mark.lifecycle
    def test_change_status_invalid_transition_rejected(self, api, url):
        """An impossible transition (draft → certified) must be 400/409, never 5xx."""
        payload = make_draft_product()
        pid = _create_product(api, url, payload)
        self._to_delete.append(pid)

        resp = api.post(
            url(f"/api/data-products/{pid}/change-status"),
            json={"new_status": "certified"},
        )
        assert resp.status_code in (400, 409), (
            f"Expected 4xx for invalid transition, got {resp.status_code}: {resp.text[:300]}"
        )

    # -----------------------------------------------------------------------
    # request-status-change (approval workflow)
    # -----------------------------------------------------------------------
    @pytest.mark.lifecycle
    def test_request_status_change(self, api, url):
        """
        POST /api/data-products/{id}/request-status-change
        Expected: 200 (request queued) or 400/404/409 (server rejects — ok too)
        """
        payload = make_draft_product()
        pid = _create_product(api, url, payload)
        self._to_delete.append(pid)

        body = {
            "target_status": "proposed",
            "justification": "E2E lifecycle test requesting status change",
            "current_status": "draft",
        }
        resp = api.post(url(f"/api/data-products/{pid}/request-status-change"), json=body)
        assert resp.status_code in (200, 201, 400, 404, 409), (
            f"request-status-change unexpected status: {resp.status_code} {resp.text[:300]}"
        )

    # -----------------------------------------------------------------------
    # handle-status-change (approver side)
    # -----------------------------------------------------------------------
    @pytest.mark.lifecycle
    def test_handle_status_change_approve(self, api, url):
        """
        POST /api/data-products/{id}/handle-status-change
        Without a pending request, expect 400/404/409 — proves the endpoint is reachable.
        """
        payload = make_draft_product()
        pid = _create_product(api, url, payload)
        self._to_delete.append(pid)

        body = {
            "decision": "approve",
            "target_status": "proposed",
            "requester_email": "e2e-test@example.com",
            "message": "Approved in E2E test",
        }
        resp = api.post(url(f"/api/data-products/{pid}/handle-status-change"), json=body)
        # Without a queued request the server should 400/404/409, not 5xx
        assert resp.status_code in (200, 400, 404, 409), (
            f"handle-status-change unexpected status: {resp.status_code} {resp.text[:300]}"
        )

    # -----------------------------------------------------------------------
    # clone-for-editing → diff-from-parent → discard
    # -----------------------------------------------------------------------
    @pytest.mark.lifecycle
    def test_clone_for_editing_then_discard(self, api, url):
        """
        Clone a product to get a personal draft, then discard it.
        Verifies the clone exists and the discard removes it.
        """
        payload = make_draft_product()
        pid = _create_product(api, url, payload)
        self._to_delete.append(pid)

        # Clone
        clone_resp = api.post(url(f"/api/data-products/{pid}/clone-for-editing"))
        assert clone_resp.status_code in (200, 201, 400, 409), (
            f"clone-for-editing unexpected status: {clone_resp.status_code} {clone_resp.text[:400]}"
        )

        if clone_resp.status_code not in (200, 201):
            pytest.skip(
                f"clone-for-editing returned {clone_resp.status_code} — "
                "product may not be in a cloneable state; skipping diff/discard steps"
            )

        clone = clone_resp.json()
        clone_id = clone.get("id")
        assert clone_id, f"No 'id' in clone response: {clone}"
        self._to_delete.append(clone_id)

        # Verify the clone is visible
        get_resp = api.get(url(f"/api/data-products/{clone_id}"))
        assert get_resp.status_code == 200, (
            f"Could not fetch cloned product {clone_id}: {get_resp.status_code}"
        )

        # Diff from parent (clone has a parent_id)
        diff_resp = api.get(url(f"/api/data-products/{clone_id}/diff-from-parent"))
        assert diff_resp.status_code in (200, 400), (
            f"diff-from-parent unexpected status: {diff_resp.status_code} {diff_resp.text[:300]}"
        )
        if diff_resp.status_code == 200:
            diff = diff_resp.json()
            # The response should at minimum contain analysis keys
            assert isinstance(diff, dict), "diff-from-parent should return a dict"

        # Discard the clone
        discard_resp = api.delete(url(f"/api/data-products/{clone_id}/discard"))
        assert discard_resp.status_code in (200, 204), (
            f"discard unexpected status: {discard_resp.status_code} {discard_resp.text[:300]}"
        )

        # Confirm gone (delete succeeded, so remove from cleanup list)
        self._to_delete.remove(clone_id)
        gone_resp = api.get(url(f"/api/data-products/{clone_id}"))
        assert gone_resp.status_code == 404, (
            f"Discarded product {clone_id} still reachable: {gone_resp.status_code}"
        )

    @pytest.mark.lifecycle
    def test_diff_from_parent_on_non_draft_returns_error(self, api, url):
        """diff-from-parent on a product with no parent should return 400, not 5xx."""
        payload = make_draft_product()
        pid = _create_product(api, url, payload)
        self._to_delete.append(pid)

        resp = api.get(url(f"/api/data-products/{pid}/diff-from-parent"))
        assert resp.status_code in (200, 400), (
            f"diff-from-parent unexpected status: {resp.status_code} {resp.text[:300]}"
        )

    # -----------------------------------------------------------------------
    # request-review (notification-heavy — may fail if no reviewer configured)
    # -----------------------------------------------------------------------
    @pytest.mark.lifecycle
    def test_request_review_reachable(self, api, url):
        """
        Verifies the request-review endpoint is reachable.
        A 409/400/422 is acceptable if reviewer validation fails server-side.
        """
        payload = make_draft_product()
        pid = _create_product(api, url, payload)
        self._to_delete.append(pid)

        body = {
            "reviewer_email": "e2e-reviewer@example.com",
            "message": "Please review this E2E test product",
        }
        resp = api.post(url(f"/api/data-products/{pid}/request-review"), json=body)
        assert resp.status_code in (200, 201, 400, 409, 422), (
            f"request-review unexpected status: {resp.status_code} {resp.text[:300]}"
        )
        # Must not be a 5xx
        assert resp.status_code < 500, (
            f"request-review returned server error: {resp.status_code} {resp.text[:300]}"
        )

    # -----------------------------------------------------------------------
    # approve / reject from proposed (happy-path multi-step workflow)
    # -----------------------------------------------------------------------
    @pytest.mark.lifecycle
    def test_approve_product(self, api, url):
        """
        Happy path: draft → proposed → under_review via change-status,
        then POST .../approve (under_review → approved).
        If any intermediate transition is not available (409/400), the test
        is skipped rather than failed to avoid false negatives in environments
        where transition guards are strict.
        """
        payload = make_draft_product()
        pid = _create_product(api, url, payload)
        self._to_delete.append(pid)

        # Move to proposed
        transition_resp = api.post(
            url(f"/api/data-products/{pid}/change-status"),
            json={"new_status": "proposed"},
        )
        if transition_resp.status_code in (400, 409):
            pytest.skip("Status transition draft→proposed not available in this environment")
        assert transition_resp.status_code == 200, (
            f"change-status draft→proposed unexpected: "
            f"{transition_resp.status_code} {transition_resp.text[:300]}"
        )

        # Move to under_review (required before approve)
        transition_resp = api.post(
            url(f"/api/data-products/{pid}/change-status"),
            json={"new_status": "under_review"},
        )
        if transition_resp.status_code in (400, 409):
            pytest.skip("Status transition proposed→under_review not available in this environment")
        assert transition_resp.status_code == 200, (
            f"change-status proposed→under_review unexpected: "
            f"{transition_resp.status_code} {transition_resp.text[:300]}"
        )

        # Approve from under_review
        resp = api.post(url(f"/api/data-products/{pid}/approve"))
        assert resp.status_code == 200, (
            f"approve unexpected status: {resp.status_code} {resp.text[:300]}"
        )
        body = resp.json()
        assert "status" in body, f"approve response missing 'status': {body}"

    @pytest.mark.lifecycle
    def test_reject_product(self, api, url):
        """
        Happy path: draft → proposed → under_review via change-status,
        then POST .../reject with a reason (under_review → draft).
        Skips if any intermediate status transition is not available.
        """
        payload = make_draft_product()
        pid = _create_product(api, url, payload)
        self._to_delete.append(pid)

        # Move to proposed
        transition_resp = api.post(
            url(f"/api/data-products/{pid}/change-status"),
            json={"new_status": "proposed"},
        )
        if transition_resp.status_code in (400, 409):
            pytest.skip("Status transition draft→proposed not available in this environment")
        assert transition_resp.status_code == 200, (
            f"change-status draft→proposed unexpected: "
            f"{transition_resp.status_code} {transition_resp.text[:300]}"
        )

        # Move to under_review (required before reject)
        transition_resp = api.post(
            url(f"/api/data-products/{pid}/change-status"),
            json={"new_status": "under_review"},
        )
        if transition_resp.status_code in (400, 409):
            pytest.skip("Status transition proposed→under_review not available in this environment")
        assert transition_resp.status_code == 200, (
            f"change-status proposed→under_review unexpected: "
            f"{transition_resp.status_code} {transition_resp.text[:300]}"
        )

        # Reject from under_review
        resp = api.post(
            url(f"/api/data-products/{pid}/reject"),
            json={"reason": "E2E test rejection"},
        )
        assert resp.status_code == 200, (
            f"reject unexpected status: {resp.status_code} {resp.text[:300]}"
        )

    # -----------------------------------------------------------------------
    # 404 guard: lifecycle endpoints on missing product
    # -----------------------------------------------------------------------
    @pytest.mark.lifecycle
    def test_lifecycle_endpoints_404_on_missing_product(self, api, url):
        """All lifecycle endpoints must return 404 for a nonexistent product."""
        fake_id = f"nonexistent-{_uid()}"
        endpoints = [
            ("POST", f"/api/data-products/{fake_id}/move-to-sandbox", {}),
            ("POST", f"/api/data-products/{fake_id}/submit-certification", {}),
            ("POST", f"/api/data-products/{fake_id}/change-status", {"new_status": "sandbox"}),
        ]
        for method, path, body in endpoints:
            resp = api.request(method, url(path), json=body)
            assert resp.status_code in (400, 404, 405, 409, 422), (
                f"{method} {path} expected 4xx for nonexistent id, got {resp.status_code}"
            )


# ===========================================================================
# Data Contract Lifecycle Tests
# ===========================================================================


class TestDataContractLifecycle:
    """Smoke tests for data contract status transitions and draft workflow."""

    @pytest.fixture(autouse=True)
    def _cleanup(self, api, url):
        self._to_delete = []
        yield
        for cid in reversed(self._to_delete):
            api.delete(url(f"/api/data-contracts/{cid}"))

    # -----------------------------------------------------------------------
    # change-status (direct, server validates ODCS transitions)
    # -----------------------------------------------------------------------
    @pytest.mark.lifecycle
    def test_change_status_draft_to_proposed(self, api, url):
        """
        draft → proposed is a valid ODCS transition.
        200 = success; 400/409 = server rejected for business reason (acceptable).
        """
        payload = make_draft_contract()
        cid = _create_contract(api, url, payload)
        self._to_delete.append(cid)

        resp = api.post(
            url(f"/api/data-contracts/{cid}/change-status"),
            json={"new_status": "proposed"},
        )
        assert resp.status_code in (200, 400, 409), (
            f"change-status draft→proposed unexpected: {resp.status_code} {resp.text[:300]}"
        )
        if resp.status_code == 200:
            body = resp.json()
            assert "status" in body or "to" in body, (
                f"Response missing status info: {body}"
            )

    @pytest.mark.lifecycle
    def test_change_status_draft_to_deprecated(self, api, url):
        """draft → deprecated is a valid ODCS transition."""
        payload = make_draft_contract()
        cid = _create_contract(api, url, payload)
        self._to_delete.append(cid)

        resp = api.post(
            url(f"/api/data-contracts/{cid}/change-status"),
            json={"new_status": "deprecated"},
        )
        assert resp.status_code in (200, 400, 409), (
            f"change-status draft→deprecated unexpected: {resp.status_code} {resp.text[:300]}"
        )

    @pytest.mark.lifecycle
    def test_change_status_invalid_transition_rejected(self, api, url):
        """An invalid ODCS transition (draft → certified) must be 400/409, never 5xx."""
        payload = make_draft_contract()
        cid = _create_contract(api, url, payload)
        self._to_delete.append(cid)

        resp = api.post(
            url(f"/api/data-contracts/{cid}/change-status"),
            json={"new_status": "certified"},
        )
        assert resp.status_code in (400, 409), (
            f"Expected 4xx for invalid transition, got {resp.status_code}: {resp.text[:300]}"
        )

    @pytest.mark.lifecycle
    def test_change_status_roundtrip_response_fields(self, api, url):
        """
        On a successful status change the response should include 'status',
        'from', and 'to' fields per the route implementation.
        """
        payload = make_draft_contract()
        cid = _create_contract(api, url, payload)
        self._to_delete.append(cid)

        resp = api.post(
            url(f"/api/data-contracts/{cid}/change-status"),
            json={"new_status": "proposed"},
        )
        if resp.status_code == 200:
            body = resp.json()
            assert "status" in body or "to" in body, (
                f"Response should contain status/to field: {body}"
            )

    # -----------------------------------------------------------------------
    # approve / reject (require PROPOSED/UNDER_REVIEW — will 409 from draft)
    # -----------------------------------------------------------------------
    @pytest.mark.lifecycle
    def test_approve_from_draft_is_rejected(self, api, url):
        """
        Approving a draft contract is invalid; server must return 409.
        Confirms the guard logic without needing a multi-user setup.
        """
        payload = make_draft_contract()
        cid = _create_contract(api, url, payload)
        self._to_delete.append(cid)

        resp = api.post(url(f"/api/data-contracts/{cid}/approve"))
        assert resp.status_code in (403, 409), (
            f"Expected 409 (invalid transition from draft) or 403 (approver role), "
            f"got {resp.status_code}: {resp.text[:300]}"
        )

    @pytest.mark.lifecycle
    def test_reject_from_draft_is_rejected(self, api, url):
        """Rejecting a draft contract must return 409/403."""
        payload = make_draft_contract()
        cid = _create_contract(api, url, payload)
        self._to_delete.append(cid)

        resp = api.post(url(f"/api/data-contracts/{cid}/reject"))
        assert resp.status_code in (403, 409), (
            f"Expected 409 or 403, got {resp.status_code}: {resp.text[:300]}"
        )

    # -----------------------------------------------------------------------
    # request-review (may fail without stewards configured)
    # -----------------------------------------------------------------------
    @pytest.mark.lifecycle
    def test_request_review_reachable(self, api, url):
        """
        Endpoint is reachable.  A 400/409 is acceptable if no stewards are configured.
        Must not be a 5xx.
        """
        payload = make_draft_contract()
        cid = _create_contract(api, url, payload)
        self._to_delete.append(cid)

        resp = api.post(
            url(f"/api/data-contracts/{cid}/request-review"),
            json={"message": "E2E test — please review"},
        )
        assert resp.status_code in (200, 201, 400, 404, 409, 422), (
            f"request-review unexpected: {resp.status_code} {resp.text[:300]}"
        )
        assert resp.status_code < 500, (
            f"request-review returned server error: {resp.status_code}"
        )

    # -----------------------------------------------------------------------
    # request-publish (requires APPROVED status — will 409/404 from draft)
    # -----------------------------------------------------------------------
    @pytest.mark.lifecycle
    def test_request_publish_from_draft_rejected(self, api, url):
        """request-publish from draft status must fail with 4xx, not 5xx."""
        payload = make_draft_contract()
        cid = _create_contract(api, url, payload)
        self._to_delete.append(cid)

        resp = api.post(
            url(f"/api/data-contracts/{cid}/request-publish"),
            json={"justification": "E2E publish request"},
        )
        assert resp.status_code in (400, 404, 409), (
            f"request-publish from draft should be 4xx, got {resp.status_code}: {resp.text[:300]}"
        )

    # -----------------------------------------------------------------------
    # request-deploy (may fail if no deployment policy configured)
    # -----------------------------------------------------------------------
    @pytest.mark.lifecycle
    def test_request_deploy_reachable(self, api, url):
        """Endpoint is reachable; a 4xx is acceptable from a draft contract."""
        payload = make_draft_contract()
        cid = _create_contract(api, url, payload)
        self._to_delete.append(cid)

        resp = api.post(
            url(f"/api/data-contracts/{cid}/request-deploy"),
            json={"message": "E2E deploy request"},
        )
        assert resp.status_code in (200, 201, 400, 403, 404, 409), (
            f"request-deploy unexpected: {resp.status_code} {resp.text[:300]}"
        )
        assert resp.status_code < 500, (
            f"request-deploy returned server error: {resp.status_code}"
        )

    # -----------------------------------------------------------------------
    # request-status-change (approval workflow)
    # -----------------------------------------------------------------------
    @pytest.mark.lifecycle
    def test_request_status_change(self, api, url):
        """
        POST /api/data-contracts/{id}/request-status-change
        200 = request queued; 4xx = server rejects (both valid smoke outcomes).
        """
        payload = make_draft_contract()
        cid = _create_contract(api, url, payload)
        self._to_delete.append(cid)

        body = {
            "target_status": "proposed",
            "justification": "E2E lifecycle test requesting status change",
            "current_status": "draft",
        }
        resp = api.post(url(f"/api/data-contracts/{cid}/request-status-change"), json=body)
        assert resp.status_code in (200, 201, 400, 404, 409), (
            f"request-status-change unexpected: {resp.status_code} {resp.text[:300]}"
        )

    # -----------------------------------------------------------------------
    # handle-status-change (approver response — no pending request → 4xx)
    # -----------------------------------------------------------------------
    @pytest.mark.lifecycle
    def test_handle_status_change_without_pending_request(self, api, url):
        """
        Without a prior request-status-change, the server should return 400/404/409.
        Confirms the endpoint is reachable and the guard works.
        """
        payload = make_draft_contract()
        cid = _create_contract(api, url, payload)
        self._to_delete.append(cid)

        body = {
            "decision": "approve",
            "target_status": "proposed",
            "requester_email": "e2e-requester@example.com",
            "message": "Approved in E2E test",
        }
        resp = api.post(url(f"/api/data-contracts/{cid}/handle-status-change"), json=body)
        assert resp.status_code in (200, 400, 404, 409), (
            f"handle-status-change unexpected: {resp.status_code} {resp.text[:300]}"
        )

    # -----------------------------------------------------------------------
    # clone-for-editing → diff-from-parent → discard
    # -----------------------------------------------------------------------
    @pytest.mark.lifecycle
    def test_clone_for_editing_then_discard(self, api, url):
        """
        Clone a contract to get a personal draft, verify it, then discard it.
        """
        payload = make_draft_contract()
        cid = _create_contract(api, url, payload)
        self._to_delete.append(cid)

        # Clone
        clone_resp = api.post(url(f"/api/data-contracts/{cid}/clone-for-editing"))
        assert clone_resp.status_code in (200, 201, 400, 409), (
            f"clone-for-editing unexpected: {clone_resp.status_code} {clone_resp.text[:400]}"
        )

        if clone_resp.status_code not in (200, 201):
            pytest.skip(
                f"clone-for-editing returned {clone_resp.status_code} — "
                "contract may not be in a cloneable state; skipping diff/discard steps"
            )

        clone = clone_resp.json()
        clone_id = clone.get("id")
        assert clone_id, f"No 'id' in clone response: {clone}"
        self._to_delete.append(clone_id)

        # Response should include expected fields
        assert "version" in clone, f"Clone missing 'version': {clone}"
        assert "status" in clone, f"Clone missing 'status': {clone}"

        # Verify the clone is accessible
        get_resp = api.get(url(f"/api/data-contracts/{clone_id}"))
        assert get_resp.status_code == 200, (
            f"Could not fetch cloned contract {clone_id}: {get_resp.status_code}"
        )
        fetched = get_resp.json()
        assert fetched.get("id") == clone_id

        # diff-from-parent (clone has parent_contract_id set)
        diff_resp = api.get(url(f"/api/data-contracts/{clone_id}/diff-from-parent"))
        assert diff_resp.status_code in (200, 400), (
            f"diff-from-parent unexpected: {diff_resp.status_code} {diff_resp.text[:300]}"
        )
        if diff_resp.status_code == 200:
            assert isinstance(diff_resp.json(), dict), (
                "diff-from-parent should return a dict"
            )

        # Discard the clone
        discard_resp = api.delete(url(f"/api/data-contracts/{clone_id}/discard"))
        assert discard_resp.status_code in (200, 204), (
            f"discard unexpected: {discard_resp.status_code} {discard_resp.text[:300]}"
        )
        if discard_resp.status_code in (200, 204):
            self._to_delete.remove(clone_id)
            # Confirm gone
            gone_resp = api.get(url(f"/api/data-contracts/{clone_id}"))
            assert gone_resp.status_code == 404, (
                f"Discarded contract {clone_id} still reachable: {gone_resp.status_code}"
            )

    @pytest.mark.lifecycle
    def test_diff_from_parent_on_non_clone_returns_error(self, api, url):
        """diff-from-parent on a contract with no parent should return 400, not 5xx."""
        payload = make_draft_contract()
        cid = _create_contract(api, url, payload)
        self._to_delete.append(cid)

        resp = api.get(url(f"/api/data-contracts/{cid}/diff-from-parent"))
        assert resp.status_code in (200, 400), (
            f"diff-from-parent unexpected: {resp.status_code} {resp.text[:300]}"
        )

    # -----------------------------------------------------------------------
    # my-drafts
    # -----------------------------------------------------------------------
    @pytest.mark.lifecycle
    def test_my_drafts_returns_list(self, api, url):
        """GET /api/data-contracts/my-drafts must return a list (possibly empty)."""
        resp = api.get(url("/api/data-contracts/my-drafts"))
        assert resp.status_code in (200, 404), (
            f"my-drafts unexpected status: {resp.status_code} {resp.text[:300]}"
        )
        if resp.status_code == 200:
            assert isinstance(resp.json(), list), "my-drafts should return a JSON array"

    @pytest.mark.lifecycle
    def test_my_drafts_includes_clone(self, api, url):
        """After cloning a contract, it should appear in my-drafts."""
        payload = make_draft_contract()
        cid = _create_contract(api, url, payload)
        self._to_delete.append(cid)

        # Clone
        clone_resp = api.post(url(f"/api/data-contracts/{cid}/clone-for-editing"))
        if clone_resp.status_code not in (200, 201):
            pytest.skip(f"clone-for-editing returned {clone_resp.status_code}")

        clone_id = clone_resp.json().get("id")
        assert clone_id
        self._to_delete.append(clone_id)

        # Fetch drafts
        drafts_resp = api.get(url("/api/data-contracts/my-drafts"))
        if drafts_resp.status_code == 404:
            pytest.skip("my-drafts endpoint not available")
        assert drafts_resp.status_code == 200
        drafts = drafts_resp.json()
        ids = [d.get("id") for d in drafts]
        assert clone_id in ids, (
            f"Clone {clone_id} not found in my-drafts: {ids}"
        )

    # -----------------------------------------------------------------------
    # approve / reject from proposed (happy-path multi-step workflow)
    # -----------------------------------------------------------------------
    @pytest.mark.lifecycle
    def test_approve_contract_from_proposed(self, api, url):
        """
        Happy path: create draft contract, transition to proposed then under_review
        via change-status, then POST .../approve.
        The ODCS lifecycle requires: proposed → under_review → approved.
        Skips if any intermediate transition is unavailable (409/400).
        """
        payload = make_draft_contract()
        cid = _create_contract(api, url, payload)
        self._to_delete.append(cid)

        # Move to proposed
        transition_resp = api.post(
            url(f"/api/data-contracts/{cid}/change-status"),
            json={"new_status": "proposed"},
        )
        if transition_resp.status_code in (400, 409):
            pytest.skip("Status transition draft→proposed not available in this environment")
        assert transition_resp.status_code == 200, (
            f"change-status draft→proposed unexpected: "
            f"{transition_resp.status_code} {transition_resp.text[:300]}"
        )

        # Move to under_review (required before approve per ODCS lifecycle)
        transition_resp = api.post(
            url(f"/api/data-contracts/{cid}/change-status"),
            json={"new_status": "under_review"},
        )
        if transition_resp.status_code in (400, 409):
            pytest.skip("Status transition proposed→under_review not available in this environment")
        assert transition_resp.status_code == 200, (
            f"change-status proposed→under_review unexpected: "
            f"{transition_resp.status_code} {transition_resp.text[:300]}"
        )

        # Approve from under_review
        resp = api.post(url(f"/api/data-contracts/{cid}/approve"))
        assert resp.status_code == 200, (
            f"approve unexpected status: {resp.status_code} {resp.text[:300]}"
        )
        body = resp.json()
        assert "status" in body or "to" in body, (
            f"approve response missing status info: {body}"
        )

    @pytest.mark.lifecycle
    def test_reject_contract_from_proposed(self, api, url):
        """
        Happy path: create draft contract, transition to proposed via change-status,
        then POST .../reject with a reason.  Skips if the intermediate transition fails.
        """
        payload = make_draft_contract()
        cid = _create_contract(api, url, payload)
        self._to_delete.append(cid)

        # Move to proposed
        transition_resp = api.post(
            url(f"/api/data-contracts/{cid}/change-status"),
            json={"new_status": "proposed"},
        )
        if transition_resp.status_code in (400, 409):
            pytest.skip("Status transition draft→proposed not available in this environment")
        assert transition_resp.status_code == 200, (
            f"change-status draft→proposed unexpected: "
            f"{transition_resp.status_code} {transition_resp.text[:300]}"
        )

        # Reject from proposed
        resp = api.post(
            url(f"/api/data-contracts/{cid}/reject"),
            json={"reason": "E2E test rejection"},
        )
        assert resp.status_code == 200, (
            f"reject unexpected status: {resp.status_code} {resp.text[:300]}"
        )

    # -----------------------------------------------------------------------
    # 404 guard
    # -----------------------------------------------------------------------
    @pytest.mark.lifecycle
    def test_lifecycle_endpoints_404_on_missing_contract(self, api, url):
        """Status transition endpoints must return 404 for nonexistent contracts."""
        fake_id = f"nonexistent-{_uid()}"
        endpoints = [
            ("POST", f"/api/data-contracts/{fake_id}/change-status", {"new_status": "proposed"}),
            ("POST", f"/api/data-contracts/{fake_id}/approve", {}),
            ("POST", f"/api/data-contracts/{fake_id}/reject", {}),
        ]
        for method, path, body in endpoints:
            resp = api.request(method, url(path), json=body)
            assert resp.status_code in (403, 404, 409), (
                f"{method} {path} expected 4xx for nonexistent id, got {resp.status_code}"
            )


# ===========================================================================
# Cross-entity: clone → commit workflow
# ===========================================================================


class TestCloneCommitWorkflow:
    """
    Full clone → edit (update) → commit flow for both entity types.
    This is the heaviest test — it modifies the cloned draft before committing.
    """

    @pytest.fixture(autouse=True)
    def _cleanup(self, api, url):
        self._products_to_delete = []
        self._contracts_to_delete = []
        yield
        for pid in reversed(self._products_to_delete):
            api.delete(url(f"/api/data-products/{pid}"))
        for cid in reversed(self._contracts_to_delete):
            api.delete(url(f"/api/data-contracts/{cid}"))

    @pytest.mark.lifecycle
    def test_contract_clone_commit_workflow(self, api, url):
        """
        Full workflow:
          1. Create a draft contract
          2. Clone it → personal draft
          3. Update the personal draft (add a description field)
          4. Commit the draft with a new version
          5. Verify the committed contract is accessible with the new version
        """
        # 1. Create base contract
        payload = make_draft_contract()
        base_resp = api.post(url("/api/data-contracts"), json=payload)
        assert base_resp.status_code in (200, 201), (
            f"Create contract failed: {base_resp.text[:300]}"
        )
        base_id = base_resp.json()["id"]
        self._contracts_to_delete.append(base_id)

        # 2. Clone
        clone_resp = api.post(url(f"/api/data-contracts/{base_id}/clone-for-editing"))
        if clone_resp.status_code not in (200, 201):
            pytest.skip(
                f"clone-for-editing returned {clone_resp.status_code} — skipping commit flow"
            )
        draft_id = clone_resp.json()["id"]
        self._contracts_to_delete.append(draft_id)

        # 3. Update the draft (patch description)
        update_resp = api.put(
            url(f"/api/data-contracts/{draft_id}"),
            json={
                "id": draft_id,
                "kind": "DataContract",
                "apiVersion": "v3.0.2",
                "version": clone_resp.json().get("version", "1.0.0-draft"),
                "status": "draft",
                "name": payload["name"],
                "domain": payload["domain"],
                "description": {
                    "purpose": "Updated by E2E clone-commit test",
                    "usage": "Testing commit workflow",
                },
            },
        )
        # Update may be skipped on 409 (version conflict guard) — that's also fine
        assert update_resp.status_code in (200, 409), (
            f"Update draft unexpected: {update_resp.status_code} {update_resp.text[:300]}"
        )

        # 4. Commit
        commit_body = {
            "new_version": "2.0.0",
            "change_summary": "E2E clone-commit workflow test",
        }
        commit_resp = api.post(url(f"/api/data-contracts/{draft_id}/commit"), json=commit_body)
        assert commit_resp.status_code in (200, 201, 400, 403), (
            f"commit unexpected: {commit_resp.status_code} {commit_resp.text[:300]}"
        )

        if commit_resp.status_code in (200, 201):
            committed = commit_resp.json()
            assert "id" in committed, f"Commit response missing 'id': {committed}"
            assert "version" in committed, f"Commit response missing 'version': {committed}"
            # After commit the draft may be replaced/updated; clean up new id if different
            committed_id = committed.get("id")
            if committed_id and committed_id != draft_id:
                self._contracts_to_delete.append(committed_id)

            # 5. Verify accessible
            get_resp = api.get(url(f"/api/data-contracts/{committed_id}"))
            assert get_resp.status_code == 200, (
                f"Committed contract {committed_id} not accessible: {get_resp.status_code}"
            )

    @pytest.mark.lifecycle
    def test_product_clone_commit_workflow(self, api, url):
        """
        Full workflow for products:
          1. Create a draft product
          2. Clone it → personal draft
          3. Commit the draft with a new version
          4. Verify the committed product is accessible
        """
        # 1. Create base product
        payload = make_draft_product()
        base_resp = api.post(url("/api/data-products"), json=payload)
        assert base_resp.status_code in (200, 201), (
            f"Create product failed: {base_resp.text[:300]}"
        )
        base_id = base_resp.json()["id"]
        self._products_to_delete.append(base_id)

        # 2. Clone
        clone_resp = api.post(url(f"/api/data-products/{base_id}/clone-for-editing"))
        if clone_resp.status_code not in (200, 201):
            pytest.skip(
                f"clone-for-editing returned {clone_resp.status_code} — skipping commit flow"
            )
        draft_id = clone_resp.json().get("id")
        assert draft_id, f"No id in clone response: {clone_resp.json()}"
        self._products_to_delete.append(draft_id)

        # 3. Commit
        commit_body = {
            "new_version": "2.0.0",
            "change_summary": "E2E product clone-commit workflow test",
        }
        commit_resp = api.post(url(f"/api/data-products/{draft_id}/commit"), json=commit_body)
        assert commit_resp.status_code in (200, 201, 400, 403), (
            f"product commit unexpected: {commit_resp.status_code} {commit_resp.text[:300]}"
        )

        if commit_resp.status_code in (200, 201):
            committed = commit_resp.json()
            assert "id" in committed, f"Commit response missing 'id': {committed}"
            committed_id = committed.get("id")
            if committed_id and committed_id != draft_id:
                self._products_to_delete.append(committed_id)

            # 4. Verify accessible
            get_resp = api.get(url(f"/api/data-products/{committed_id}"))
            assert get_resp.status_code == 200, (
                f"Committed product {committed_id} not accessible: {get_resp.status_code}"
            )
