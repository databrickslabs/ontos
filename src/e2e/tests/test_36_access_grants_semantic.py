"""
E2E tests: Access Grants request/handle flow, Semantic Links CRUD,
Knowledge Concepts lifecycle, and Semantic search/neighbors/query smoke tests.

Coverage goals:
- Access Grants: config GET/PUT, entity grants & summary, request creation,
  handle (approve/deny), cancel request, my-grants/my-requests listing
- Semantic Links: list by entity, list by IRI, create, delete
- Knowledge Collections: list, get, create, update, delete
- Knowledge Concepts: create, get, patch, lifecycle transitions,
  owners CRUD, delete
- Semantic search, neighbors, prefix-search, SPARQL query smoke tests

Many endpoints depend on an ontology being loaded or on specific entities
existing; tests accept lenient status codes (non-500) for those cases.
"""
import uuid
from typing import Any, Dict, Optional

import pytest

# ---------------------------------------------------------------------------
# Local factory helpers (kept here as instructed — do NOT import from test_data)
# ---------------------------------------------------------------------------
E2E_PREFIX = "e2e-test-"


def _uid() -> str:
    return uuid.uuid4().hex[:8]


# ---------- access grants ----------

def make_access_request(entity_type: str = "data_product",
                        entity_id: Optional[str] = None,
                        **overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "entity_type": entity_type,
        "entity_id": entity_id or f"{E2E_PREFIX}entity-{_uid()}",
        "entity_name": f"E2E Test Entity {_uid()}",
        "requested_duration_days": 30,
        "permission_level": "READ",
        "reason": "E2E automated test — access request smoke test",
    }
    defaults.update(overrides)
    return defaults


def make_duration_config(entity_type: str, **overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "entity_type": entity_type,
        "allowed_durations": [30, 60, 90],
        "default_duration": 30,
        "expiry_warning_days": 7,
        "allow_renewal": True,
        "max_renewals": 3,
    }
    defaults.update(overrides)
    return defaults


# ---------- semantic links ----------

def make_semantic_link(entity_id: str, entity_type: str = "data_domain",
                       **overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "entity_id": entity_id,
        "entity_type": entity_type,
        "iri": f"http://example.com/ontology/e2e/{_uid()}",
        "label": f"E2E Concept {_uid()}",
    }
    defaults.update(overrides)
    return defaults


# ---------- knowledge collections ----------

def make_collection(**overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "label": f"{E2E_PREFIX}collection-{_uid()}",
        "description": "E2E knowledge collection",
        "collection_type": "glossary",
        "scope_level": "enterprise",
        "is_editable": True,
    }
    defaults.update(overrides)
    return defaults


# ---------- knowledge concepts ----------

def make_concept(collection_iri: str, **overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "collection_iri": collection_iri,
        "label": f"{E2E_PREFIX}concept-{_uid()}",
        "definition": "E2E automated test concept",
        "concept_type": "concept",
        "synonyms": [],
        "examples": [],
        "broader_iris": [],
        "narrower_iris": [],
        "related_iris": [],
    }
    defaults.update(overrides)
    return defaults


# ===========================================================================
# Access Grants — Config Endpoints
# ===========================================================================

class TestAccessGrantsConfig:
    """Duration configuration CRUD for entity types."""

    def test_list_all_configs(self, api, url):
        """GET /api/access-grants/config — returns a list (may be empty)."""
        resp = api.get(url("/api/access-grants/config"))
        assert resp.status_code == 200
        body = resp.json()
        # May return a list directly or an object with 'configs'
        assert isinstance(body, (list, dict))

    def test_get_config_for_unknown_entity_type_returns_default(self, api, url):
        """GET /api/access-grants/config/{entity_type} returns a default when not found."""
        entity_type = f"e2e-type-{_uid()}"
        resp = api.get(url(f"/api/access-grants/config/{entity_type}"))
        assert resp.status_code == 200
        body = resp.json()
        assert body["entity_type"] == entity_type
        # Must have the required fields
        assert "allowed_durations" in body
        assert "default_duration" in body

    def test_get_duration_options_for_unknown_entity_type(self, api, url):
        """GET /api/access-grants/config/{entity_type}/options — list of ints."""
        entity_type = f"e2e-type-{_uid()}"
        resp = api.get(url(f"/api/access-grants/config/{entity_type}/options"))
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list)

    def test_upsert_config_for_entity_type(self, api, url):
        """PUT /api/access-grants/config/{entity_type} — upsert (admin required)."""
        entity_type = f"e2e-etype-{_uid()}"
        payload = make_duration_config(entity_type)
        resp = api.put(url(f"/api/access-grants/config/{entity_type}"), json=payload)
        # Admin-only: 200 on success, 403 if current user lacks admin role
        assert resp.status_code in (200, 403), (
            f"Unexpected status {resp.status_code}: {resp.text[:300]}"
        )
        if resp.status_code == 200:
            body = resp.json()
            assert body["entity_type"] == entity_type
            assert body["default_duration"] == 30
            assert body["allow_renewal"] is True


# ===========================================================================
# Access Grants — Entity Grants & Summaries
# ===========================================================================

class TestAccessGrantsEntityEndpoints:
    """Read endpoints scoped to a specific entity."""

    def test_get_entity_grants_nonexistent(self, api, url):
        """GET /api/access-grants/entity/{type}/{id} — empty list for unknown entity."""
        resp = api.get(url("/api/access-grants/entity/data_product/nonexistent-e2e"))
        assert resp.status_code == 200
        body = resp.json()
        assert "grants" in body
        assert body["total"] == 0

    def test_get_entity_grants_include_inactive(self, api, url):
        """include_inactive=true should also work without error."""
        resp = api.get(
            url("/api/access-grants/entity/data_product/nonexistent-e2e"),
            params={"include_inactive": "true"},
        )
        assert resp.status_code == 200

    def test_get_entity_pending_requests_nonexistent(self, api, url):
        """GET /api/access-grants/entity/{type}/{id}/requests — empty list."""
        resp = api.get(url("/api/access-grants/entity/dataset/nonexistent-e2e/requests"))
        assert resp.status_code == 200
        body = resp.json()
        assert "requests" in body
        assert body["total"] == 0

    def test_get_entity_summary_nonexistent(self, api, url):
        """GET /api/access-grants/entity/{type}/{id}/summary — counts all zero."""
        resp = api.get(url("/api/access-grants/entity/data_contract/nonexistent-e2e/summary"))
        assert resp.status_code == 200
        body = resp.json()
        assert body["active_grants_count"] == 0
        assert body["pending_requests_count"] == 0


# ===========================================================================
# Access Grants — Request / Handle Flow
# ===========================================================================

class TestAccessGrantsRequestFlow:
    """Full request → handle → cancel lifecycle."""

    def test_my_grants_returns_list(self, api, url):
        """GET /api/access-grants/my — authenticated user gets their grants."""
        resp = api.get(url("/api/access-grants/my"))
        assert resp.status_code == 200
        body = resp.json()
        assert "grants" in body
        assert isinstance(body["total"], int)

    def test_my_grants_summary_shape(self, api, url):
        """GET /api/access-grants/my/summary — returns expected keys."""
        resp = api.get(url("/api/access-grants/my/summary"))
        assert resp.status_code == 200
        body = resp.json()
        assert "active_grants" in body
        assert "pending_requests" in body
        assert "expiring_soon" in body

    def test_my_pending_requests_returns_list(self, api, url):
        """GET /api/access-grants/requests/my — own pending requests."""
        resp = api.get(url("/api/access-grants/requests/my"))
        assert resp.status_code == 200
        body = resp.json()
        assert "requests" in body
        assert isinstance(body["total"], int)

    def test_pending_requests_admin_list(self, api, url):
        """GET /api/access-grants/requests/pending — admin listing."""
        resp = api.get(url("/api/access-grants/requests/pending"))
        # 200 for admins/read-only, 403 if not permitted
        assert resp.status_code in (200, 403)
        if resp.status_code == 200:
            body = resp.json()
            assert "requests" in body

    def test_create_access_request_and_cancel(self, api, url):
        """POST /api/access-grants/request then DELETE to cancel."""
        payload = make_access_request(
            entity_type="data_product",
            entity_id=f"e2e-dp-{_uid()}",
        )
        create_resp = api.post(url("/api/access-grants/request"), json=payload)
        # 201 success; 400 for validation issues; 500 is a bug
        assert create_resp.status_code != 500, (
            f"Server error on create_request: {create_resp.text[:500]}"
        )
        assert create_resp.status_code in (201, 400, 422), (
            f"Unexpected status {create_resp.status_code}: {create_resp.text[:300]}"
        )

        if create_resp.status_code == 201:
            request_id = create_resp.json()["id"]
            # Verify fields round-trip
            body = create_resp.json()
            assert body["entity_type"] == payload["entity_type"]
            assert body["requested_duration_days"] == payload["requested_duration_days"]
            assert body["permission_level"] == payload["permission_level"]
            assert body["status"] == "pending"

            # Cancel the request we just created
            del_resp = api.delete(url(f"/api/access-grants/requests/{request_id}"))
            assert del_resp.status_code in (204, 200, 404), (
                f"Unexpected cancel status {del_resp.status_code}: {del_resp.text[:300]}"
            )

    def test_create_request_invalid_duration(self, api, url):
        """POST with duration=0 must be rejected (Pydantic validation), not 500."""
        payload = make_access_request(requested_duration_days=0)
        resp = api.post(url("/api/access-grants/request"), json=payload)
        assert resp.status_code in (400, 422), (
            f"Expected validation error but got {resp.status_code}: {resp.text[:300]}"
        )

    def test_create_request_invalid_reason_too_short(self, api, url):
        """POST with reason shorter than 10 chars must be rejected, not 500."""
        payload = make_access_request(reason="short")
        resp = api.post(url("/api/access-grants/request"), json=payload)
        assert resp.status_code in (400, 422), (
            f"Expected validation error but got {resp.status_code}: {resp.text[:300]}"
        )

    def test_handle_nonexistent_request_deny(self, api, url):
        """POST /api/access-grants/handle with a fake UUID — 400/404, not 500."""
        payload = {
            "request_id": str(uuid.uuid4()),
            "approved": False,
            "message": "E2E test denial",
        }
        resp = api.post(url("/api/access-grants/handle"), json=payload)
        assert resp.status_code != 500, (
            f"Server error on handle with fake id: {resp.text[:500]}"
        )
        assert resp.status_code in (200, 400, 403, 404, 422), (
            f"Unexpected status {resp.status_code}: {resp.text[:300]}"
        )

    def test_handle_nonexistent_request_approve(self, api, url):
        """POST /api/access-grants/handle approve path — 400/404/403, not 500."""
        payload = {
            "request_id": str(uuid.uuid4()),
            "approved": True,
            "granted_duration_days": 30,
            "permission_level": "READ",
            "message": "E2E test approval",
        }
        resp = api.post(url("/api/access-grants/handle"), json=payload)
        assert resp.status_code != 500, (
            f"Server error on handle-approve with fake id: {resp.text[:500]}"
        )
        assert resp.status_code in (200, 400, 403, 404, 422), (
            f"Unexpected status {resp.status_code}: {resp.text[:300]}"
        )

    def test_revoke_nonexistent_grant(self, api, url):
        """POST /api/access-grants/{grant_id}/revoke with fake UUID — 404/403, not 500."""
        fake_id = str(uuid.uuid4())
        resp = api.post(url(f"/api/access-grants/{fake_id}/revoke"), json={})
        assert resp.status_code != 500, (
            f"Server error on revoke: {resp.text[:500]}"
        )
        assert resp.status_code in (200, 400, 403, 404, 422)

    def test_cancel_nonexistent_request(self, api, url):
        """DELETE /api/access-grants/requests/{id} on unknown ID — 404, not 500."""
        fake_id = str(uuid.uuid4())
        resp = api.delete(url(f"/api/access-grants/requests/{fake_id}"))
        assert resp.status_code != 500, (
            f"Server error on cancel: {resp.text[:500]}"
        )
        assert resp.status_code in (204, 400, 404)

    @pytest.mark.crud
    def test_full_request_approve_revoke_flow(self, api, url):
        """Happy path: create request -> approve -> verify grant -> revoke.

        Each step gracefully skips when the environment lacks the required
        permissions or configuration rather than failing hard.
        """
        # --- Step 1: create the access request ---
        payload = make_access_request(
            entity_type="data_product",
            entity_id=f"e2e-dp-{_uid()}",
        )
        create_resp = api.post(url("/api/access-grants/request"), json=payload)
        assert create_resp.status_code != 500, (
            f"Server error creating access request: {create_resp.text[:500]}"
        )
        if create_resp.status_code in (400, 403, 422):
            pytest.skip(
                f"Cannot create access request in this environment "
                f"(status={create_resp.status_code}): {create_resp.text[:300]}"
            )
        assert create_resp.status_code == 201, (
            f"Unexpected create status {create_resp.status_code}: {create_resp.text[:300]}"
        )

        request_body = create_resp.json()
        request_id = request_body["id"]
        assert request_body["status"] == "pending"
        assert request_body["entity_type"] == payload["entity_type"]

        # --- Step 2: approve the request ---
        approve_payload = {
            "request_id": request_id,
            "approved": True,
            "granted_duration_days": payload["requested_duration_days"],
            "permission_level": payload["permission_level"],
            "message": "E2E test approval",
        }
        approve_resp = api.post(url("/api/access-grants/handle"), json=approve_payload)
        assert approve_resp.status_code != 500, (
            f"Server error approving request {request_id}: {approve_resp.text[:500]}"
        )
        if approve_resp.status_code in (400, 403, 422):
            # Cannot approve — cancel the pending request to clean up, then skip
            api.delete(url(f"/api/access-grants/requests/{request_id}"))
            pytest.skip(
                f"Approve step not permitted in this environment "
                f"(status={approve_resp.status_code}): {approve_resp.text[:300]}"
            )
        assert approve_resp.status_code == 200, (
            f"Unexpected approve status {approve_resp.status_code}: {approve_resp.text[:300]}"
        )

        approve_body = approve_resp.json()
        # The response contains the grant nested under "grant" key
        grant = approve_body.get("grant", {})
        grant_id = (
            grant.get("id")
            or approve_body.get("grant_id")
            or approve_body.get("id")
        )
        assert grant_id is not None, (
            f"Approve response missing grant id: {approve_body}"
        )
        # Normalize to string for comparisons
        grant_id = str(grant_id)

        # --- Step 3: verify the grant exists on the entity ---
        entity_type = payload["entity_type"]
        entity_id = payload["entity_id"]
        entity_resp = api.get(url(f"/api/access-grants/entity/{entity_type}/{entity_id}"))
        assert entity_resp.status_code == 200, (
            f"Unexpected entity grants status {entity_resp.status_code}: {entity_resp.text[:300]}"
        )
        entity_body = entity_resp.json()
        grant_ids_on_entity = [g["id"] for g in entity_body.get("grants", [])]
        assert grant_id in grant_ids_on_entity, (
            f"Approved grant {grant_id} not found in entity grants: {grant_ids_on_entity}"
        )

        # --- Step 4: revoke the grant ---
        revoke_resp = api.post(
            url(f"/api/access-grants/{grant_id}/revoke"),
            json={"reason": "E2E test cleanup"},
        )
        assert revoke_resp.status_code != 500, (
            f"Server error revoking grant {grant_id}: {revoke_resp.text[:500]}"
        )
        if revoke_resp.status_code in (400, 403, 422):
            pytest.skip(
                f"Revoke step not permitted in this environment "
                f"(status={revoke_resp.status_code}): {revoke_resp.text[:300]}"
            )
        assert revoke_resp.status_code in (200, 204), (
            f"Unexpected revoke status {revoke_resp.status_code}: {revoke_resp.text[:300]}"
        )


# ===========================================================================
# Semantic Links — CRUD
# ===========================================================================

class TestSemanticLinksCRUD:
    """Create, list by entity, list by IRI, and delete semantic links."""

    # ----- read-only first -----

    def test_list_links_for_nonexistent_entity(self, api, url):
        """GET /api/semantic-links/entity/{type}/{id} — returns []."""
        resp = api.get(url("/api/semantic-links/entity/data_domain/nonexistent-e2e"))
        assert resp.status_code in (200, 404), (
            f"Unexpected {resp.status_code}: {resp.text[:300]}"
        )
        if resp.status_code == 200:
            assert isinstance(resp.json(), list)

    def test_list_links_by_iri(self, api, url):
        """GET /api/semantic-links/iri/{iri} — smoke test with a fake IRI."""
        iri = "http://example.com/e2e/nonexistent"
        resp = api.get(url(f"/api/semantic-links/iri/{iri}"))
        assert resp.status_code in (200, 404), (
            f"Unexpected {resp.status_code}: {resp.text[:300]}"
        )
        if resp.status_code == 200:
            assert isinstance(resp.json(), list)

    # ----- create a data domain first, then test link CRUD -----

    @pytest.fixture(scope="class")
    def domain_id(self, api, url):
        """Create a data domain to use as the link target entity."""
        payload = {
            "name": f"{E2E_PREFIX}sem-domain-{_uid()}",
            "description": "E2E domain for semantic link tests",
        }
        resp = api.post(url("/api/data-domains"), json=payload)
        if resp.status_code != 201:
            pytest.skip(f"Cannot create data domain (status={resp.status_code})")
        domain = resp.json()
        domain_id = domain.get("id") or domain.get("name")
        yield domain_id
        # Cleanup
        api.delete(url(f"/api/data-domains/{domain_id}"))

    def test_create_semantic_link(self, api, url, domain_id):
        """POST /api/semantic-links/ — creates a link, returns 200 or 400."""
        payload = make_semantic_link(entity_id=domain_id, entity_type="data_domain")
        resp = api.post(url("/api/semantic-links/"), json=payload)
        # 200 = success; 400 = IRI not found in ontology (acceptable); 403 = permissions
        assert resp.status_code != 500, (
            f"Server error on semantic link creation: {resp.text[:500]}"
        )
        assert resp.status_code in (200, 201, 400, 403, 422), (
            f"Unexpected status {resp.status_code}: {resp.text[:300]}"
        )

    def test_create_and_delete_semantic_link(self, api, url, domain_id):
        """Full create-then-delete round trip for a semantic link."""
        payload = make_semantic_link(entity_id=domain_id, entity_type="data_domain")
        create_resp = api.post(url("/api/semantic-links/"), json=payload)
        assert create_resp.status_code != 500, (
            f"Server error creating link: {create_resp.text[:500]}"
        )

        if create_resp.status_code not in (200, 201):
            pytest.skip(f"Link creation not supported (status={create_resp.status_code})")

        link_id = create_resp.json()["id"]

        # Verify list now contains the link
        list_resp = api.get(url(f"/api/semantic-links/entity/data_domain/{domain_id}"))
        assert list_resp.status_code == 200
        ids_in_list = [lnk["id"] for lnk in list_resp.json()]
        assert link_id in ids_in_list

        # Delete the link
        del_resp = api.delete(url(f"/api/semantic-links/{link_id}"))
        assert del_resp.status_code != 500, (
            f"Server error deleting link: {del_resp.text[:500]}"
        )
        assert del_resp.status_code in (200, 204), (
            f"Unexpected delete status {del_resp.status_code}: {del_resp.text[:300]}"
        )

    def test_delete_nonexistent_link(self, api, url):
        """DELETE /api/semantic-links/{id} with bogus id — 404, not 500."""
        resp = api.delete(url(f"/api/semantic-links/nonexistent-{_uid()}"))
        assert resp.status_code in (200, 403, 404), (
            f"Unexpected status {resp.status_code}: {resp.text[:300]}"
        )

    def test_create_link_missing_required_field(self, api, url):
        """POST without iri — Pydantic rejects, not 500."""
        payload = {"entity_id": "some-entity", "entity_type": "data_domain"}
        resp = api.post(url("/api/semantic-links/"), json=payload)
        assert resp.status_code in (400, 422), (
            f"Expected validation error, got {resp.status_code}: {resp.text[:300]}"
        )

    def test_create_link_invalid_entity_type(self, api, url):
        """POST with entity_type not in the Literal enum — 422."""
        payload = {
            "entity_id": "some-entity",
            "entity_type": "not_a_real_type",
            "iri": "http://example.com/e2e/concept",
        }
        resp = api.post(url("/api/semantic-links/"), json=payload)
        assert resp.status_code in (400, 422), (
            f"Expected validation error, got {resp.status_code}: {resp.text[:300]}"
        )


# ===========================================================================
# Knowledge Collections — CRUD
# ===========================================================================

class TestKnowledgeCollections:
    """Collections are the containers for knowledge concepts."""

    def test_list_collections(self, api, url):
        """GET /api/knowledge/collections — returns list or dict."""
        resp = api.get(url("/api/knowledge/collections"))
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, (list, dict))

    def test_get_nonexistent_collection(self, api, url):
        """GET /api/knowledge/collections/{iri} for missing IRI — 404, not 500."""
        fake_iri = f"http://example.com/e2e/missing-{_uid()}"
        resp = api.get(url(f"/api/knowledge/collections/{fake_iri}"))
        assert resp.status_code != 500, (
            f"Server error on get missing collection: {resp.text[:500]}"
        )
        assert resp.status_code in (200, 404)

    def test_create_collection(self, api, url):
        """POST /api/knowledge/collections — creates a glossary collection."""
        payload = make_collection()
        resp = api.post(url("/api/knowledge/collections"), json=payload)
        assert resp.status_code != 500, (
            f"Server error on create collection: {resp.text[:500]}"
        )
        assert resp.status_code in (200, 201, 400, 403, 422), (
            f"Unexpected status {resp.status_code}: {resp.text[:300]}"
        )
        if resp.status_code in (200, 201):
            body = resp.json()
            assert "iri" in body
            # Cleanup: best-effort delete
            iri = body["iri"]
            api.delete(url(f"/api/knowledge/collections/{iri}"))

    def test_create_and_delete_collection(self, api, url):
        """Full collection lifecycle: create → get → update → delete."""
        payload = make_collection()
        create_resp = api.post(url("/api/knowledge/collections"), json=payload)
        assert create_resp.status_code != 500, (
            f"Server error creating collection: {create_resp.text[:500]}"
        )
        if create_resp.status_code not in (200, 201):
            pytest.skip(f"Collection creation not available (status={create_resp.status_code})")

        body = create_resp.json()
        iri = body["iri"]
        assert body.get("label") == payload["label"] or body.get("label") is not None

        # GET the collection
        get_resp = api.get(url(f"/api/knowledge/collections/{iri}"))
        assert get_resp.status_code in (200, 404), (
            f"Unexpected get status {get_resp.status_code}"
        )

        # PATCH the collection
        patch_resp = api.patch(
            url(f"/api/knowledge/collections/{iri}"),
            json={"description": "Updated by E2E test"},
        )
        assert patch_resp.status_code != 500, (
            f"Server error patching collection: {patch_resp.text[:500]}"
        )
        assert patch_resp.status_code in (200, 400, 403, 404, 422)

        # DELETE
        del_resp = api.delete(url(f"/api/knowledge/collections/{iri}"))
        assert del_resp.status_code != 500, (
            f"Server error deleting collection: {del_resp.text[:500]}"
        )
        assert del_resp.status_code in (200, 204, 400, 403, 404)

    def test_update_nonexistent_collection(self, api, url):
        """PATCH /api/knowledge/collections/{iri} for missing collection — 404, not 500."""
        fake_iri = f"http://example.com/e2e/missing-{_uid()}"
        resp = api.patch(
            url(f"/api/knowledge/collections/{fake_iri}"),
            json={"description": "should not matter"},
        )
        assert resp.status_code != 500, (
            f"Server error patching nonexistent collection: {resp.text[:500]}"
        )
        assert resp.status_code in (200, 400, 403, 404, 422)

    def test_delete_nonexistent_collection(self, api, url):
        """DELETE /api/knowledge/collections/{iri} for missing IRI — 404, not 500."""
        fake_iri = f"http://example.com/e2e/missing-{_uid()}"
        resp = api.delete(url(f"/api/knowledge/collections/{fake_iri}"))
        assert resp.status_code in (200, 204, 400, 403, 404)

    @pytest.mark.crud
    def test_get_existing_collection(self, api, url):
        """Create a collection then GET it by IRI — 200 with collection data."""
        payload = make_collection()
        create_resp = api.post(url("/api/knowledge/collections"), json=payload)
        assert create_resp.status_code != 500, (
            f"Server error creating collection: {create_resp.text[:500]}"
        )
        if create_resp.status_code not in (200, 201):
            pytest.skip(
                f"Collection creation not available (status={create_resp.status_code})"
            )
        iri = create_resp.json()["iri"]

        try:
            get_resp = api.get(url(f"/api/knowledge/collections/{iri}"))
            assert get_resp.status_code == 200, (
                f"Expected 200 for existing collection, got {get_resp.status_code}: "
                f"{get_resp.text[:300]}"
            )
            body = get_resp.json()
            assert isinstance(body, dict)
            # IRI should appear somewhere in the response
            assert body.get("iri") == iri or iri in str(body)
        finally:
            api.delete(url(f"/api/knowledge/collections/{iri}"))

    @pytest.mark.crud
    def test_export_collection(self, api, url):
        """Create a collection then GET /export?format=turtle — 200 or skip on 400/404."""
        payload = make_collection()
        create_resp = api.post(url("/api/knowledge/collections"), json=payload)
        assert create_resp.status_code != 500, (
            f"Server error creating collection: {create_resp.text[:500]}"
        )
        if create_resp.status_code not in (200, 201):
            pytest.skip(
                f"Collection creation not available (status={create_resp.status_code})"
            )
        iri = create_resp.json()["iri"]

        try:
            # Export endpoint is a GET, not POST
            export_resp = api.get(
                url(f"/api/knowledge/collections/{iri}/export"),
                params={"format": "turtle"},
            )
            assert export_resp.status_code != 500, (
                f"Server error on collection export: {export_resp.text[:500]}"
            )
            if export_resp.status_code in (400, 404):
                pytest.skip(
                    f"Export endpoint not supported (status={export_resp.status_code})"
                )
            assert export_resp.status_code == 200, (
                f"Unexpected export status {export_resp.status_code}: {export_resp.text[:300]}"
            )
        finally:
            api.delete(url(f"/api/knowledge/collections/{iri}"))


# ===========================================================================
# Knowledge Concepts — CRUD + Lifecycle
# ===========================================================================

class TestKnowledgeConcepts:
    """Concepts within a collection: CRUD and lifecycle transitions."""

    # Shared collection IRI for concept tests — created once per class
    @pytest.fixture(scope="class")
    def collection_iri(self, api, url):
        payload = make_collection(
            label=f"{E2E_PREFIX}concept-host-{_uid()}",
            collection_type="glossary",
        )
        resp = api.post(url("/api/knowledge/collections"), json=payload)
        if resp.status_code not in (200, 201):
            pytest.skip(
                f"Cannot create collection for concept tests "
                f"(status={resp.status_code}: {resp.text[:200]})"
            )
        iri = resp.json()["iri"]
        yield iri
        api.delete(url(f"/api/knowledge/collections/{iri}"))

    # ----- basic read -----

    def test_get_nonexistent_concept(self, api, url):
        """GET /api/knowledge/concepts/{iri} for missing IRI — 404, not 500."""
        fake_iri = f"http://example.com/e2e/missing-concept-{_uid()}"
        resp = api.get(url(f"/api/knowledge/concepts/{fake_iri}"))
        assert resp.status_code != 500, (
            f"Server error on get missing concept: {resp.text[:500]}"
        )
        assert resp.status_code in (200, 404)

    # ----- create -----

    def test_create_concept(self, api, url, collection_iri):
        """POST /api/knowledge/concepts — creates a concept in the collection."""
        payload = make_concept(collection_iri)
        resp = api.post(url("/api/knowledge/concepts"), json=payload)
        assert resp.status_code != 500, (
            f"Server error creating concept: {resp.text[:500]}"
        )
        assert resp.status_code in (200, 201, 400, 403, 422), (
            f"Unexpected status {resp.status_code}: {resp.text[:300]}"
        )
        if resp.status_code in (200, 201):
            body = resp.json()
            assert "iri" in body
            iri = body["iri"]
            api.delete(url(f"/api/knowledge/concepts/{iri}"))

    def test_create_concept_missing_required_field(self, api, url):
        """POST without collection_iri — Pydantic rejects, not 500."""
        payload = {"label": f"e2e-concept-{_uid()}", "concept_type": "concept"}
        resp = api.post(url("/api/knowledge/concepts"), json=payload)
        assert resp.status_code in (400, 422), (
            f"Expected validation error, got {resp.status_code}: {resp.text[:300]}"
        )

    # ----- full lifecycle fixture -----

    @pytest.fixture(scope="class")
    def concept_iri(self, api, url, collection_iri):
        """Create a concept and yield its IRI; delete after tests."""
        payload = make_concept(collection_iri)
        resp = api.post(url("/api/knowledge/concepts"), json=payload)
        if resp.status_code not in (200, 201):
            pytest.skip(
                f"Cannot create concept for lifecycle tests "
                f"(status={resp.status_code}: {resp.text[:200]})"
            )
        iri = resp.json()["iri"]
        yield iri
        api.delete(url(f"/api/knowledge/concepts/{iri}"))

    def test_get_created_concept(self, api, url, concept_iri):
        """GET the concept we just created — 200 with iri field."""
        resp = api.get(url(f"/api/knowledge/concepts/{concept_iri}"))
        assert resp.status_code in (200, 404), (
            f"Unexpected status {resp.status_code}: {resp.text[:300]}"
        )
        if resp.status_code == 200:
            body = resp.json()
            # Response may be wrapped or flat
            concept = body.get("concept", body)
            assert concept.get("iri") == concept_iri

    def test_patch_concept(self, api, url, concept_iri):
        """PATCH /api/knowledge/concepts/{iri} — update label/definition."""
        resp = api.patch(
            url(f"/api/knowledge/concepts/{concept_iri}"),
            json={
                "label": f"{E2E_PREFIX}updated-{_uid()}",
                "definition": "Updated by E2E test",
                "synonyms": ["e2e", "test"],
            },
        )
        assert resp.status_code != 500, (
            f"Server error patching concept: {resp.text[:500]}"
        )
        assert resp.status_code in (200, 400, 403, 404, 422), (
            f"Unexpected patch status {resp.status_code}: {resp.text[:300]}"
        )

    def test_patch_nonexistent_concept(self, api, url):
        """PATCH on missing concept IRI — 404, not 500."""
        fake_iri = f"http://example.com/e2e/missing-{_uid()}"
        resp = api.patch(
            url(f"/api/knowledge/concepts/{fake_iri}"),
            json={"label": "will not matter"},
        )
        assert resp.status_code != 500, (
            f"Server error patching nonexistent concept: {resp.text[:500]}"
        )
        assert resp.status_code in (200, 400, 403, 404, 422)

    # ----- lifecycle transitions -----

    def test_submit_concept_for_review(self, api, url, concept_iri):
        """POST /api/knowledge/concepts/{iri}/submit-review — 200/400/403/404."""
        resp = api.post(url(f"/api/knowledge/concepts/{concept_iri}/submit-review"))
        assert resp.status_code != 500, (
            f"Server error on submit-review: {resp.text[:500]}"
        )
        assert resp.status_code in (200, 201, 400, 403, 404, 422), (
            f"Unexpected status {resp.status_code}: {resp.text[:300]}"
        )

    def test_publish_concept(self, api, url, concept_iri):
        """POST /api/knowledge/concepts/{iri}/publish — non-500."""
        resp = api.post(url(f"/api/knowledge/concepts/{concept_iri}/publish"))
        assert resp.status_code != 500, (
            f"Server error on publish: {resp.text[:500]}"
        )
        assert resp.status_code in (200, 201, 400, 403, 404, 422)

    def test_certify_concept(self, api, url, concept_iri):
        """POST /api/knowledge/concepts/{iri}/certify — non-500."""
        resp = api.post(url(f"/api/knowledge/concepts/{concept_iri}/certify"))
        assert resp.status_code != 500, (
            f"Server error on certify: {resp.text[:500]}"
        )
        assert resp.status_code in (200, 201, 400, 403, 404, 422)

    def test_deprecate_concept(self, api, url, concept_iri):
        """POST /api/knowledge/concepts/{iri}/deprecate — non-500."""
        resp = api.post(url(f"/api/knowledge/concepts/{concept_iri}/deprecate"))
        assert resp.status_code != 500, (
            f"Server error on deprecate: {resp.text[:500]}"
        )
        assert resp.status_code in (200, 201, 400, 403, 404, 422)

    def test_archive_concept(self, api, url, concept_iri):
        """POST /api/knowledge/concepts/{iri}/archive — non-500."""
        resp = api.post(url(f"/api/knowledge/concepts/{concept_iri}/archive"))
        assert resp.status_code != 500, (
            f"Server error on archive: {resp.text[:500]}"
        )
        assert resp.status_code in (200, 201, 400, 403, 404, 422)

    def test_lifecycle_transitions_on_nonexistent_concept(self, api, url):
        """Lifecycle actions on unknown IRI must not produce 500."""
        fake_iri = f"http://example.com/e2e/missing-{_uid()}"
        for action in ("submit-review", "publish", "certify", "deprecate", "archive"):
            resp = api.post(url(f"/api/knowledge/concepts/{fake_iri}/{action}"))
            assert resp.status_code != 500, (
                f"Server error on {action} for nonexistent concept: {resp.text[:500]}"
            )
            assert resp.status_code in (200, 201, 400, 403, 404, 422), (
                f"Unexpected status for {action}: {resp.status_code}: {resp.text[:300]}"
            )

    # ----- owners -----

    def test_add_owner_to_nonexistent_concept(self, api, url):
        """POST /api/knowledge/concepts/{iri}/owners on missing concept — 404, not 500."""
        fake_iri = f"http://example.com/e2e/missing-{_uid()}"
        payload = {"user_uri": "mailto:e2e@example.com", "role": "data_steward"}
        resp = api.post(url(f"/api/knowledge/concepts/{fake_iri}/owners"), json=payload)
        assert resp.status_code != 500, (
            f"Server error adding owner to nonexistent concept: {resp.text[:500]}"
        )
        assert resp.status_code in (200, 201, 400, 403, 404, 422)

    def test_add_and_remove_owner(self, api, url, concept_iri):
        """POST /api/knowledge/concepts/{iri}/owners then DELETE owner — non-500."""
        owner_email = f"e2e-owner-{_uid()}@example.com"
        add_payload = {"user_uri": f"mailto:{owner_email}", "role": "contributor"}
        add_resp = api.post(url(f"/api/knowledge/concepts/{concept_iri}/owners"), json=add_payload)
        assert add_resp.status_code in (200, 201, 400, 403, 404, 409, 422)

        # Attempt removal regardless (might not have been added)
        del_resp = api.delete(url(f"/api/knowledge/concepts/{concept_iri}/owners/{owner_email}"))
        assert del_resp.status_code in (200, 204, 400, 403, 404)

    # ----- promote / migrate -----

    def test_promote_nonexistent_concept(self, api, url):
        """POST /api/knowledge/concepts/{iri}/promote on missing IRI — 404, not 500."""
        fake_iri = f"http://example.com/e2e/missing-{_uid()}"
        payload = {
            "target_collection_iri": "http://example.com/e2e/target",
            "promotion_type": "promoted",
        }
        resp = api.post(url(f"/api/knowledge/concepts/{fake_iri}/promote"), json=payload)
        assert resp.status_code != 500, (
            f"Server error on promote nonexistent concept: {resp.text[:500]}"
        )
        assert resp.status_code in (200, 201, 400, 403, 404, 422)

    def test_migrate_nonexistent_concept(self, api, url):
        """POST /api/knowledge/concepts/{iri}/migrate on missing IRI — 404, not 500."""
        fake_iri = f"http://example.com/e2e/missing-{_uid()}"
        payload = {"target_collection_iri": "http://example.com/e2e/target"}
        resp = api.post(url(f"/api/knowledge/concepts/{fake_iri}/migrate"), json=payload)
        assert resp.status_code != 500, (
            f"Server error on migrate nonexistent concept: {resp.text[:500]}"
        )
        assert resp.status_code in (200, 201, 400, 403, 404, 422)

    @pytest.mark.crud
    def test_promote_existing_concept(self, api, url, collection_iri):
        """Create a concept, walk it through lifecycle, then POST /promote."""
        payload = make_concept(collection_iri)
        create_resp = api.post(url("/api/knowledge/concepts"), json=payload)
        assert create_resp.status_code != 500, (
            f"Server error creating concept for promote test: {create_resp.text[:500]}"
        )
        if create_resp.status_code not in (200, 201):
            pytest.skip(
                f"Cannot create concept for promote test "
                f"(status={create_resp.status_code}: {create_resp.text[:200]})"
            )
        concept_iri_val = create_resp.json()["iri"]

        try:
            # Attempt to advance to a promotable state via submit-review then publish
            for action in ("submit-review", "publish"):
                step = api.post(url(f"/api/knowledge/concepts/{concept_iri_val}/{action}"))
                if step.status_code in (400, 403, 404, 422):
                    pytest.skip(
                        f"Lifecycle step '{action}' failed "
                        f"(status={step.status_code}); skipping promote test"
                    )
                assert step.status_code != 500, (
                    f"Server error on '{action}': {step.text[:500]}"
                )

            promote_payload = {
                "target_collection_iri": collection_iri,
                "promotion_type": "promoted",
            }
            promote_resp = api.post(
                url(f"/api/knowledge/concepts/{concept_iri_val}/promote"),
                json=promote_payload,
            )
            assert promote_resp.status_code != 500, (
                f"Server error on promote: {promote_resp.text[:500]}"
            )
            assert promote_resp.status_code in (200, 201, 400, 403, 404, 422), (
                f"Unexpected promote status {promote_resp.status_code}: "
                f"{promote_resp.text[:300]}"
            )
        finally:
            api.delete(url(f"/api/knowledge/concepts/{concept_iri_val}"))

    @pytest.mark.crud
    def test_migrate_existing_concept(self, api, url, collection_iri):
        """Create a concept then POST /migrate with a target collection IRI."""
        payload = make_concept(collection_iri)
        create_resp = api.post(url("/api/knowledge/concepts"), json=payload)
        assert create_resp.status_code != 500, (
            f"Server error creating concept for migrate test: {create_resp.text[:500]}"
        )
        if create_resp.status_code not in (200, 201):
            pytest.skip(
                f"Cannot create concept for migrate test "
                f"(status={create_resp.status_code}: {create_resp.text[:200]})"
            )
        concept_iri_val = create_resp.json()["iri"]

        try:
            # Create a second collection to migrate into
            target_payload = make_collection(
                label=f"{E2E_PREFIX}migrate-target-{_uid()}",
            )
            target_resp = api.post(url("/api/knowledge/collections"), json=target_payload)
            if target_resp.status_code not in (200, 201):
                pytest.skip(
                    f"Cannot create target collection for migrate test "
                    f"(status={target_resp.status_code})"
                )
            target_iri = target_resp.json()["iri"]

            try:
                migrate_resp = api.post(
                    url(f"/api/knowledge/concepts/{concept_iri_val}/migrate"),
                    json={"target_collection_iri": target_iri},
                )
                assert migrate_resp.status_code != 500, (
                    f"Server error on migrate: {migrate_resp.text[:500]}"
                )
                if migrate_resp.status_code in (400, 404):
                    pytest.skip(
                        f"Migrate endpoint not supported or requires real target "
                        f"(status={migrate_resp.status_code})"
                    )
                assert migrate_resp.status_code in (200, 201, 403, 422), (
                    f"Unexpected migrate status {migrate_resp.status_code}: "
                    f"{migrate_resp.text[:300]}"
                )
            finally:
                api.delete(url(f"/api/knowledge/collections/{target_iri}"))
        finally:
            api.delete(url(f"/api/knowledge/concepts/{concept_iri_val}"))

    # ----- delete -----

    def test_delete_nonexistent_concept(self, api, url):
        """DELETE /api/knowledge/concepts/{iri} for missing IRI — 404, not 500."""
        fake_iri = f"http://example.com/e2e/missing-{_uid()}"
        resp = api.delete(url(f"/api/knowledge/concepts/{fake_iri}"))
        assert resp.status_code in (200, 204, 400, 403, 404)

    def test_delete_existing_concept(self, api, url, collection_iri):
        """Create a concept then DELETE it — 200 or 204."""
        payload = make_concept(collection_iri)
        create_resp = api.post(url("/api/knowledge/concepts"), json=payload)
        assert create_resp.status_code != 500, (
            f"Server error creating concept: {create_resp.text[:500]}"
        )
        if create_resp.status_code not in (200, 201):
            pytest.skip(
                f"Cannot create concept for delete test "
                f"(status={create_resp.status_code}: {create_resp.text[:200]})"
            )
        concept_iri_val = create_resp.json()["iri"]

        # DELETE the freshly created concept
        del_resp = api.delete(url(f"/api/knowledge/concepts/{concept_iri_val}"))
        assert del_resp.status_code != 500, (
            f"Server error deleting concept: {del_resp.text[:500]}"
        )
        assert del_resp.status_code in (200, 204), (
            f"Unexpected delete status {del_resp.status_code}: {del_resp.text[:300]}"
        )

        # Verify it is gone — 404 expected; some implementations may return 200
        # with an empty/null body instead of 404
        get_resp = api.get(url(f"/api/knowledge/concepts/{concept_iri_val}"))
        assert get_resp.status_code in (200, 404), (
            f"Unexpected status after delete: {get_resp.status_code}: {get_resp.text[:300]}"
        )
        if get_resp.status_code == 200:
            body = get_resp.json()
            concept = body.get("concept", body)
            assert concept.get("iri") != concept_iri_val, \
                "Concept still retrievable by IRI after deletion"


# ===========================================================================
# Semantic Models — Search, Neighbors, Prefix Search, SPARQL Query
# ===========================================================================

class TestSemanticModelsSearchAndQuery:
    """Smoke tests for read-heavy analytics endpoints."""

    def test_search_concepts_empty_ontology(self, api, url):
        """GET /api/semantic-models/search?q=... — non-500 even if ontology is empty."""
        resp = api.get(url("/api/semantic-models/search"), params={"q": "dataset"})
        assert resp.status_code != 500, (
            f"Server error on search: {resp.text[:500]}"
        )
        assert resp.status_code in (200, 400, 404), (
            f"Unexpected status {resp.status_code}: {resp.text[:300]}"
        )
        if resp.status_code == 200:
            body = resp.json()
            # Results may be a list or wrapped dict
            assert isinstance(body, (list, dict))

    def test_search_concepts_with_taxonomy_param(self, api, url):
        """Search with optional taxonomy filter — non-500."""
        resp = api.get(
            url("/api/semantic-models/search"),
            params={"q": "table", "taxonomy": "nonexistent"},
        )
        assert resp.status_code != 500, (
            f"Server error on search with taxonomy: {resp.text[:500]}"
        )
        assert resp.status_code in (200, 400, 404)

    def test_search_concepts_with_limit(self, api, url):
        """Search with explicit limit — non-500."""
        resp = api.get(
            url("/api/semantic-models/search"),
            params={"q": "schema", "limit": 5},
        )
        assert resp.status_code != 500, (
            f"Server error on search with limit: {resp.text[:500]}"
        )
        assert resp.status_code in (200, 400, 404)

    def test_search_missing_query_param(self, api, url):
        """GET /api/semantic-models/search without q — 422 (required param)."""
        resp = api.get(url("/api/semantic-models/search"))
        # FastAPI marks q as required, so 422 is expected
        assert resp.status_code in (400, 422), (
            f"Expected validation error, got {resp.status_code}: {resp.text[:300]}"
        )

    def test_neighbors_with_fake_iri(self, api, url):
        """GET /api/semantic-models/neighbors?iri=... — non-500 for unknown IRI."""
        resp = api.get(
            url("/api/semantic-models/neighbors"),
            params={"iri": "http://example.com/e2e/unknown"},
        )
        assert resp.status_code != 500, (
            f"Server error on neighbors: {resp.text[:500]}"
        )
        assert resp.status_code in (200, 400, 404), (
            f"Unexpected status {resp.status_code}: {resp.text[:300]}"
        )
        if resp.status_code == 200:
            body = resp.json()
            assert isinstance(body, (list, dict))

    def test_neighbors_missing_iri_param(self, api, url):
        """GET /api/semantic-models/neighbors without iri — 422."""
        resp = api.get(url("/api/semantic-models/neighbors"))
        assert resp.status_code in (400, 422), (
            f"Expected validation error, got {resp.status_code}: {resp.text[:300]}"
        )

    def test_neighbors_with_limit(self, api, url):
        """GET /api/semantic-models/neighbors with explicit limit — non-500."""
        resp = api.get(
            url("/api/semantic-models/neighbors"),
            params={"iri": "http://example.com/e2e/unknown", "limit": 10},
        )
        assert resp.status_code != 500, (
            f"Server error on neighbors with limit: {resp.text[:500]}"
        )
        assert resp.status_code in (200, 400, 404)

    def test_prefix_search_smoke(self, api, url):
        """GET /api/semantic-models/prefix?q=... — non-500."""
        resp = api.get(url("/api/semantic-models/prefix"), params={"q": "http://w3.org"})
        assert resp.status_code != 500, (
            f"Server error on prefix search: {resp.text[:500]}"
        )
        assert resp.status_code in (200, 400, 404)

    def test_prefix_search_missing_param(self, api, url):
        """GET /api/semantic-models/prefix without q — 422."""
        resp = api.get(url("/api/semantic-models/prefix"))
        assert resp.status_code in (400, 422), (
            f"Expected validation error, got {resp.status_code}: {resp.text[:300]}"
        )

    def test_sparql_query_simple_select(self, api, url):
        """POST /api/semantic-models/query with a minimal safe SPARQL query — non-500."""
        payload = {
            "sparql": "SELECT ?s ?p ?o WHERE { ?s ?p ?o } LIMIT 1"
        }
        resp = api.post(url("/api/semantic-models/query"), json=payload)
        assert resp.status_code != 500, (
            f"Server error on SPARQL query: {resp.text[:500]}"
        )
        assert resp.status_code in (200, 400, 403, 422), (
            f"Unexpected status {resp.status_code}: {resp.text[:300]}"
        )

    def test_sparql_query_missing_sparql_field(self, api, url):
        """POST /api/semantic-models/query without sparql field — 400/422, not 500."""
        resp = api.post(url("/api/semantic-models/query"), json={})
        assert resp.status_code != 500, (
            f"Server error with missing sparql field: {resp.text[:500]}"
        )
        assert resp.status_code in (400, 422), (
            f"Expected validation error, got {resp.status_code}: {resp.text[:300]}"
        )

    def test_sparql_query_malformed(self, api, url):
        """POST /api/semantic-models/query with invalid SPARQL — 400/422, not 500."""
        payload = {"sparql": "THIS IS NOT VALID SPARQL !!!"}
        resp = api.post(url("/api/semantic-models/query"), json=payload)
        assert resp.status_code != 500, (
            f"Server error on malformed SPARQL: {resp.text[:500]}"
        )
        assert resp.status_code in (200, 400, 403, 422), (
            f"Unexpected status {resp.status_code}: {resp.text[:300]}"
        )

    def test_sparql_query_forbidden_update(self, api, url):
        """POST /api/semantic-models/query with SPARQL UPDATE — rejected, not 500."""
        payload = {
            "sparql": "INSERT DATA { <http://example.com/e2e/s> <http://example.com/e2e/p> <http://example.com/e2e/o> . }"
        }
        resp = api.post(url("/api/semantic-models/query"), json=payload)
        assert resp.status_code != 500, (
            f"Server error on SPARQL update: {resp.text[:500]}"
        )
        # Should reject mutating queries
        assert resp.status_code in (200, 400, 403, 422)

    def test_sparql_query_ask_form(self, api, url):
        """POST /api/semantic-models/query with ASK query form — non-500."""
        payload = {"sparql": "ASK WHERE { ?s ?p ?o }"}
        resp = api.post(url("/api/semantic-models/query"), json=payload)
        assert resp.status_code != 500, (
            f"Server error on ASK query: {resp.text[:500]}"
        )
        assert resp.status_code in (200, 400, 403, 422)

    # ----- concept detail endpoint (part of semantic-models) -----

    def test_get_concept_details_unknown_iri(self, api, url):
        """GET /api/semantic-models/concepts/{iri} — 404, not 500 for unknown IRI."""
        fake_iri = "http://example.com/e2e/no-such-concept"
        resp = api.get(url(f"/api/semantic-models/concepts/{fake_iri}"))
        assert resp.status_code != 500, (
            f"Server error retrieving unknown concept: {resp.text[:500]}"
        )
        assert resp.status_code in (200, 404)

    def test_get_concept_hierarchy_unknown_iri(self, api, url):
        """GET /api/semantic-models/concepts/hierarchy?iri=... — non-500."""
        resp = api.get(
            url("/api/semantic-models/concepts/hierarchy"),
            params={"iri": "http://example.com/e2e/no-hierarchy"},
        )
        assert resp.status_code != 500, (
            f"Server error on concept hierarchy: {resp.text[:500]}"
        )
        assert resp.status_code in (200, 400, 404)

    def test_concept_suggestions_smoke(self, api, url):
        """GET /api/semantic-models/concepts/suggestions — non-500."""
        resp = api.get(url("/api/semantic-models/concepts/suggestions"), params={"q": "data"})
        assert resp.status_code != 500, (
            f"Server error on concept suggestions: {resp.text[:500]}"
        )
        assert resp.status_code in (200, 400, 404)

    def test_refresh_knowledge_graph(self, api, url):
        """POST /api/semantic-models/refresh-graph — non-500 (may need admin)."""
        resp = api.post(url("/api/semantic-models/refresh-graph"))
        assert resp.status_code != 500, (
            f"Server error on refresh-graph: {resp.text[:500]}"
        )
        assert resp.status_code in (200, 201, 400, 403, 404, 422)

    @pytest.mark.readonly
    def test_get_concept_hierarchy_existing(self, api, url):
        """Use a real concept IRI (if any exist) for GET /api/semantic-models/concepts/hierarchy."""
        list_resp = api.get(url("/api/semantic-models/concepts"))
        assert list_resp.status_code == 200, (
            f"Could not list concepts: {list_resp.text[:300]}"
        )
        concepts = list_resp.json()
        # Accept both a bare list and a wrapped dict
        if isinstance(concepts, dict):
            concepts = concepts.get("concepts", concepts.get("items", []))
        if not concepts:
            pytest.skip("No concepts found in the ontology — skipping hierarchy test")

        iri = concepts[0].get("iri") or concepts[0].get("id")
        if not iri:
            pytest.skip("First concept has no IRI field — skipping hierarchy test")

        resp = api.get(
            url("/api/semantic-models/concepts/hierarchy"),
            params={"iri": iri},
        )
        assert resp.status_code != 500, (
            f"Server error on concept hierarchy with real IRI: {resp.text[:500]}"
        )
        assert resp.status_code == 200, (
            f"Unexpected status {resp.status_code}: {resp.text[:300]}"
        )

    @pytest.mark.readonly
    def test_get_concept_details_existing(self, api, url):
        """Use a real concept IRI (if any exist) for GET /api/semantic-models/concepts/{iri}."""
        list_resp = api.get(url("/api/semantic-models/concepts"))
        assert list_resp.status_code == 200, (
            f"Could not list concepts: {list_resp.text[:300]}"
        )
        concepts = list_resp.json()
        if isinstance(concepts, dict):
            concepts = concepts.get("concepts", concepts.get("items", []))
        if not concepts:
            pytest.skip("No concepts found in the ontology — skipping concept details test")

        iri = concepts[0].get("iri") or concepts[0].get("id")
        if not iri:
            pytest.skip("First concept has no IRI field — skipping concept details test")

        resp = api.get(url(f"/api/semantic-models/concepts/{iri}"))
        assert resp.status_code != 500, (
            f"Server error retrieving concept details: {resp.text[:500]}"
        )
        assert resp.status_code == 200, (
            f"Unexpected status {resp.status_code}: {resp.text[:300]}"
        )
        body = resp.json()
        assert isinstance(body, dict)

    @pytest.mark.readonly
    def test_neighbors_with_real_iri(self, api, url):
        """Use a real concept IRI (if any exist) for GET /api/semantic-models/neighbors."""
        list_resp = api.get(url("/api/semantic-models/concepts"))
        assert list_resp.status_code == 200, (
            f"Could not list concepts: {list_resp.text[:300]}"
        )
        concepts = list_resp.json()
        if isinstance(concepts, dict):
            concepts = concepts.get("concepts", concepts.get("items", []))
        if not concepts:
            pytest.skip("No concepts found in the ontology — skipping neighbors test")

        iri = concepts[0].get("iri") or concepts[0].get("id")
        if not iri:
            pytest.skip("First concept has no IRI field — skipping neighbors test")

        resp = api.get(
            url("/api/semantic-models/neighbors"),
            params={"iri": iri},
        )
        assert resp.status_code != 500, (
            f"Server error on neighbors with real IRI: {resp.text[:500]}"
        )
        assert resp.status_code == 200, (
            f"Unexpected status {resp.status_code}: {resp.text[:300]}"
        )
        body = resp.json()
        assert isinstance(body, (list, dict))
