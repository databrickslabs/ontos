"""
Smoke tests for endpoints with Databricks-dependent or external-dependency backends.

Strategy: these tests only verify that the endpoint responds without a 500 error.
2xx, 400, 403, 404, 422, and 503 are all acceptable — each indicates the endpoint
is reachable and handled the request intentionally.  Only HTTP 500 is a test
failure, because that means an unhandled exception escaped the backend.

Feature groups covered:
  - Jobs / Workflow runs
  - Master Data Management (MDM)
  - LLM Search
  - Entitlements Sync
  - Industry Ontologies
  - Data Catalog (column dictionary, tables, lineage)
  - Data Asset Reviews (list + minimal create)
  - MCP Tokens
  - Self-Service bootstrap
"""

import pytest

# ---------------------------------------------------------------------------
# Acceptable status code sets used throughout this file
# ---------------------------------------------------------------------------
# The broad set for endpoints that hit Databricks APIs, which may be unavailable
# or require specific configuration.
_OK = frozenset([200, 400, 403, 404, 422, 503])

# Slightly narrower set for endpoints that are purely database-backed (no UC call).
_OK_DB = frozenset([200, 400, 403, 404, 422])


# ===========================================================================
# Jobs / Workflow Runs
# ===========================================================================

class TestJobsSmoke:
    """Smoke tests for GET endpoints under /api/jobs/."""

    @pytest.mark.readonly
    def test_list_job_runs(self, api, url):
        """GET /api/jobs/runs — list recent workflow job runs from the database."""
        resp = api.get(url("/api/jobs/runs"))
        assert resp.status_code not in (500,), (
            f"GET /api/jobs/runs returned 500: {resp.text[:300]}"
        )
        assert resp.status_code in _OK_DB, (
            f"Unexpected status {resp.status_code}: {resp.text[:300]}"
        )

    @pytest.mark.readonly
    def test_list_job_runs_with_limit(self, api, url):
        """GET /api/jobs/runs?limit=5 — query param forwarded correctly."""
        resp = api.get(url("/api/jobs/runs"), params={"limit": 5})
        assert resp.status_code not in (500,), (
            f"GET /api/jobs/runs?limit=5 returned 500: {resp.text[:300]}"
        )

    @pytest.mark.readonly
    def test_workflow_statuses(self, api, url):
        """GET /api/jobs/workflows/status — aggregate status from Databricks."""
        resp = api.get(url("/api/jobs/workflows/status"))
        # May 503 if Databricks Jobs API is unavailable
        assert resp.status_code not in (500,), (
            f"GET /api/jobs/workflows/status returned 500: {resp.text[:300]}"
        )
        assert resp.status_code in _OK, (
            f"Unexpected status {resp.status_code}: {resp.text[:300]}"
        )

    @pytest.mark.readonly
    def test_workflow_statuses_alias(self, api, url):
        """GET /api/jobs/workflows/statuses — alias route, same handler."""
        resp = api.get(url("/api/jobs/workflows/statuses"))
        assert resp.status_code not in (500,), (
            f"GET /api/jobs/workflows/statuses returned 500: {resp.text[:300]}"
        )
        assert resp.status_code in _OK, (
            f"Unexpected status {resp.status_code}: {resp.text[:300]}"
        )

    @pytest.mark.readonly
    def test_job_status_nonexistent_run(self, api, url):
        """GET /api/jobs/{run_id}/status — 404 for a non-existent run is fine."""
        resp = api.get(url("/api/jobs/999999999/status"))
        assert resp.status_code not in (500,), (
            f"GET /api/jobs/999999999/status returned 500: {resp.text[:300]}"
        )
        # Expect 404 from DB lookup or 403 if no permission
        assert resp.status_code in _OK, (
            f"Unexpected status {resp.status_code}: {resp.text[:300]}"
        )

    @pytest.mark.readonly
    def test_workflow_parameter_definitions_nonexistent(self, api, url):
        """GET /api/jobs/workflows/{id}/parameter-definitions — 404 is acceptable."""
        resp = api.get(url("/api/jobs/workflows/nonexistent-workflow/parameter-definitions"))
        assert resp.status_code not in (500,), (
            f"parameter-definitions returned 500: {resp.text[:300]}"
        )
        assert resp.status_code in _OK, (
            f"Unexpected status {resp.status_code}: {resp.text[:300]}"
        )

    @pytest.mark.readonly
    def test_workflow_configuration_nonexistent(self, api, url):
        """GET /api/jobs/workflows/{id}/configuration — 404 is acceptable."""
        resp = api.get(url("/api/jobs/workflows/nonexistent-workflow/configuration"))
        assert resp.status_code not in (500,), (
            f"workflow configuration returned 500: {resp.text[:300]}"
        )
        assert resp.status_code in _OK, (
            f"Unexpected status {resp.status_code}: {resp.text[:300]}"
        )


# ===========================================================================
# Master Data Management (MDM)
# ===========================================================================

class TestMdmSmoke:
    """Smoke tests for read-only MDM endpoints."""

    @pytest.mark.readonly
    def test_list_mdm_configs(self, api, url):
        """GET /api/mdm/configs — list all MDM configurations."""
        resp = api.get(url("/api/mdm/configs"))
        assert resp.status_code not in (500,), (
            f"GET /api/mdm/configs returned 500: {resp.text[:300]}"
        )
        assert resp.status_code in _OK_DB, (
            f"Unexpected status {resp.status_code}: {resp.text[:300]}"
        )

    @pytest.mark.readonly
    def test_list_mdm_configs_with_filters(self, api, url):
        """GET /api/mdm/configs with query params — filters forwarded correctly."""
        resp = api.get(url("/api/mdm/configs"), params={"skip": 0, "limit": 10})
        assert resp.status_code not in (500,), (
            f"GET /api/mdm/configs with filters returned 500: {resp.text[:300]}"
        )

    @pytest.mark.readonly
    def test_get_mdm_config_nonexistent(self, api, url):
        """GET /api/mdm/configs/{id} — 404 for unknown config ID."""
        resp = api.get(url("/api/mdm/configs/nonexistent-mdm-id"))
        assert resp.status_code not in (500,), (
            f"GET /api/mdm/configs/nonexistent returned 500: {resp.text[:300]}"
        )
        assert resp.status_code in _OK_DB, (
            f"Unexpected status {resp.status_code}: {resp.text[:300]}"
        )

    @pytest.mark.readonly
    def test_list_mdm_match_runs_nonexistent_config(self, api, url):
        """GET /api/mdm/configs/{id}/runs — 404 for unknown config."""
        resp = api.get(url("/api/mdm/configs/nonexistent-mdm-id/runs"))
        assert resp.status_code not in (500,), (
            f"GET mdm runs for nonexistent config returned 500: {resp.text[:300]}"
        )
        assert resp.status_code in _OK_DB, (
            f"Unexpected status {resp.status_code}: {resp.text[:300]}"
        )

    @pytest.mark.readonly
    def test_get_mdm_run_nonexistent(self, api, url):
        """GET /api/mdm/runs/{id} — 404 for unknown run ID."""
        resp = api.get(url("/api/mdm/runs/nonexistent-run-id"))
        assert resp.status_code not in (500,), (
            f"GET mdm run nonexistent returned 500: {resp.text[:300]}"
        )
        assert resp.status_code in _OK_DB, (
            f"Unexpected status {resp.status_code}: {resp.text[:300]}"
        )


# ===========================================================================
# LLM Search
# ===========================================================================

class TestLlmSearchSmoke:
    """Smoke tests for LLM Search endpoints."""

    @pytest.mark.readonly
    def test_llm_search_status(self, api, url):
        """GET /api/llm-search/status — returns enabled flag and endpoint info."""
        resp = api.get(url("/api/llm-search/status"))
        assert resp.status_code not in (500,), (
            f"GET /api/llm-search/status returned 500: {resp.text[:300]}"
        )
        # 503 is acceptable if the LLM endpoint is unconfigured
        assert resp.status_code in _OK, (
            f"Unexpected status {resp.status_code}: {resp.text[:300]}"
        )

    @pytest.mark.readonly
    def test_llm_search_sessions(self, api, url):
        """GET /api/llm-search/sessions — list sessions for current user."""
        resp = api.get(url("/api/llm-search/sessions"))
        assert resp.status_code not in (500,), (
            f"GET /api/llm-search/sessions returned 500: {resp.text[:300]}"
        )
        assert resp.status_code in _OK, (
            f"Unexpected status {resp.status_code}: {resp.text[:300]}"
        )

    @pytest.mark.readonly
    def test_llm_search_session_nonexistent(self, api, url):
        """GET /api/llm-search/sessions/{id} — 404 for unknown session."""
        resp = api.get(url("/api/llm-search/sessions/nonexistent-session-id"))
        assert resp.status_code not in (500,), (
            f"GET llm-search session nonexistent returned 500: {resp.text[:300]}"
        )
        assert resp.status_code in _OK, (
            f"Unexpected status {resp.status_code}: {resp.text[:300]}"
        )


# ===========================================================================
# Entitlements Sync
# ===========================================================================

class TestEntitlementsSyncSmoke:
    """Smoke tests for Entitlements Sync endpoints.

    This feature requires ADMIN-level permission, so 403 is the expected
    response for most test credentials.
    """

    @pytest.mark.readonly
    def test_list_entitlements_sync_configs(self, api, url):
        """GET /api/entitlements-sync/configs — list all sync configurations."""
        resp = api.get(url("/api/entitlements-sync/configs"))
        assert resp.status_code not in (500,), (
            f"GET /api/entitlements-sync/configs returned 500: {resp.text[:300]}"
        )
        # ADMIN-only: 403 is very likely for non-admin test credentials
        assert resp.status_code in _OK, (
            f"Unexpected status {resp.status_code}: {resp.text[:300]}"
        )

    @pytest.mark.readonly
    def test_get_entitlements_sync_config_nonexistent(self, api, url):
        """GET /api/entitlements-sync/configs/{id} — 404 or 403."""
        resp = api.get(url("/api/entitlements-sync/configs/nonexistent-id"))
        assert resp.status_code not in (500,), (
            f"GET entitlements-sync config nonexistent returned 500: {resp.text[:300]}"
        )
        assert resp.status_code in _OK, (
            f"Unexpected status {resp.status_code}: {resp.text[:300]}"
        )

    @pytest.mark.readonly
    def test_get_entitlements_sync_connections(self, api, url):
        """GET /api/entitlements-sync/connections — lists UC connections (Databricks call)."""
        resp = api.get(url("/api/entitlements-sync/connections"))
        assert resp.status_code not in (500,), (
            f"GET /api/entitlements-sync/connections returned 500: {resp.text[:300]}"
        )
        assert resp.status_code in _OK, (
            f"Unexpected status {resp.status_code}: {resp.text[:300]}"
        )

    @pytest.mark.readonly
    def test_get_entitlements_sync_catalogs(self, api, url):
        """GET /api/entitlements-sync/catalogs — lists UC catalogs (Databricks call)."""
        resp = api.get(url("/api/entitlements-sync/catalogs"))
        assert resp.status_code not in (500,), (
            f"GET /api/entitlements-sync/catalogs returned 500: {resp.text[:300]}"
        )
        assert resp.status_code in _OK, (
            f"Unexpected status {resp.status_code}: {resp.text[:300]}"
        )


# ===========================================================================
# Industry Ontologies
# ===========================================================================

class TestIndustryOntologiesSmoke:
    """Smoke tests for Industry Ontology Library endpoints."""

    @pytest.mark.readonly
    def test_list_verticals(self, api, url):
        """GET /api/industry-ontologies/verticals — list available industry verticals."""
        resp = api.get(url("/api/industry-ontologies/verticals"))
        assert resp.status_code not in (500,), (
            f"GET /api/industry-ontologies/verticals returned 500: {resp.text[:300]}"
        )
        assert resp.status_code in _OK, (
            f"Unexpected status {resp.status_code}: {resp.text[:300]}"
        )

    @pytest.mark.readonly
    def test_list_all_ontologies(self, api, url):
        """GET /api/industry-ontologies/ontologies — list all ontologies."""
        resp = api.get(url("/api/industry-ontologies/ontologies"))
        assert resp.status_code not in (500,), (
            f"GET /api/industry-ontologies/ontologies returned 500: {resp.text[:300]}"
        )
        assert resp.status_code in _OK, (
            f"Unexpected status {resp.status_code}: {resp.text[:300]}"
        )

    @pytest.mark.readonly
    def test_list_recommendations(self, api, url):
        """GET /api/industry-ontologies/recommendations — recommended foundational ontologies."""
        resp = api.get(url("/api/industry-ontologies/recommendations"))
        assert resp.status_code not in (500,), (
            f"GET /api/industry-ontologies/recommendations returned 500: {resp.text[:300]}"
        )
        assert resp.status_code in _OK, (
            f"Unexpected status {resp.status_code}: {resp.text[:300]}"
        )

    @pytest.mark.readonly
    def test_list_ontologies_in_nonexistent_vertical(self, api, url):
        """GET /api/industry-ontologies/verticals/{id}/ontologies — 404 for unknown vertical."""
        resp = api.get(url("/api/industry-ontologies/verticals/nonexistent-vertical/ontologies"))
        assert resp.status_code not in (500,), (
            f"GET ontologies for nonexistent vertical returned 500: {resp.text[:300]}"
        )
        assert resp.status_code in _OK, (
            f"Unexpected status {resp.status_code}: {resp.text[:300]}"
        )

    @pytest.mark.readonly
    def test_ontology_modules_nonexistent(self, api, url):
        """GET /api/industry-ontologies/verticals/{v}/ontologies/{o}/modules — 404 expected."""
        resp = api.get(
            url("/api/industry-ontologies/verticals/nonexistent-v/ontologies/nonexistent-o/modules")
        )
        assert resp.status_code not in (500,), (
            f"GET ontology modules for nonexistent ids returned 500: {resp.text[:300]}"
        )
        assert resp.status_code in _OK, (
            f"Unexpected status {resp.status_code}: {resp.text[:300]}"
        )


# ===========================================================================
# Data Catalog
# ===========================================================================

class TestDataCatalogSmoke:
    """Smoke tests for Data Catalog endpoints.

    These endpoints rely on Unity Catalog and the Databricks SDK, so 503 is
    possible if the workspace connection is unavailable or not configured.
    """

    @pytest.mark.readonly
    def test_get_all_columns(self, api, url):
        """GET /api/data-catalog/columns — data dictionary from registered datasets."""
        resp = api.get(url("/api/data-catalog/columns"))
        assert resp.status_code not in (500,), (
            f"GET /api/data-catalog/columns returned 500: {resp.text[:300]}"
        )
        assert resp.status_code in _OK, (
            f"Unexpected status {resp.status_code}: {resp.text[:300]}"
        )

    @pytest.mark.readonly
    def test_get_columns_with_catalog_filter(self, api, url):
        """GET /api/data-catalog/columns?catalog=... — catalog filter is forwarded."""
        resp = api.get(url("/api/data-catalog/columns"), params={"catalog": "nonexistent_catalog"})
        assert resp.status_code not in (500,), (
            f"GET /api/data-catalog/columns with catalog filter returned 500: {resp.text[:300]}"
        )
        assert resp.status_code in _OK, (
            f"Unexpected status {resp.status_code}: {resp.text[:300]}"
        )

    @pytest.mark.readonly
    def test_search_columns(self, api, url):
        """GET /api/data-catalog/columns/search?q=id — column search across registered assets."""
        resp = api.get(url("/api/data-catalog/columns/search"), params={"q": "id"})
        assert resp.status_code not in (500,), (
            f"GET /api/data-catalog/columns/search returned 500: {resp.text[:300]}"
        )
        assert resp.status_code in _OK, (
            f"Unexpected status {resp.status_code}: {resp.text[:300]}"
        )

    @pytest.mark.readonly
    def test_search_columns_missing_query(self, api, url):
        """GET /api/data-catalog/columns/search without ?q — 422 expected."""
        resp = api.get(url("/api/data-catalog/columns/search"))
        assert resp.status_code not in (500,), (
            f"GET /api/data-catalog/columns/search (no q) returned 500: {resp.text[:300]}"
        )
        # Missing required query param should produce 422 Unprocessable Entity
        assert resp.status_code in (422, 400, 403), (
            f"Expected 422/400/403, got {resp.status_code}: {resp.text[:300]}"
        )

    @pytest.mark.readonly
    def test_get_table_list(self, api, url):
        """GET /api/data-catalog/tables — list registered tables."""
        resp = api.get(url("/api/data-catalog/tables"))
        assert resp.status_code not in (500,), (
            f"GET /api/data-catalog/tables returned 500: {resp.text[:300]}"
        )
        assert resp.status_code in _OK, (
            f"Unexpected status {resp.status_code}: {resp.text[:300]}"
        )

    @pytest.mark.readonly
    def test_get_table_details_nonexistent(self, api, url):
        """GET /api/data-catalog/tables/{fqn} — 404 for unknown table."""
        resp = api.get(url("/api/data-catalog/tables/nonexistent.schema.table"))
        assert resp.status_code not in (500,), (
            f"GET table details for nonexistent table returned 500: {resp.text[:300]}"
        )
        assert resp.status_code in _OK, (
            f"Unexpected status {resp.status_code}: {resp.text[:300]}"
        )

    @pytest.mark.readonly
    def test_get_table_lineage_nonexistent(self, api, url):
        """GET /api/data-catalog/tables/{fqn}/lineage — 404 or empty graph."""
        resp = api.get(url("/api/data-catalog/tables/nonexistent.schema.table/lineage"))
        assert resp.status_code not in (500,), (
            f"GET table lineage for nonexistent table returned 500: {resp.text[:300]}"
        )
        assert resp.status_code in _OK, (
            f"Unexpected status {resp.status_code}: {resp.text[:300]}"
        )

    @pytest.mark.readonly
    def test_get_table_impact_nonexistent(self, api, url):
        """GET /api/data-catalog/tables/{fqn}/impact — 404 or empty analysis."""
        resp = api.get(url("/api/data-catalog/tables/nonexistent.schema.table/impact"))
        assert resp.status_code not in (500,), (
            f"GET table impact for nonexistent table returned 500: {resp.text[:300]}"
        )
        assert resp.status_code in _OK, (
            f"Unexpected status {resp.status_code}: {resp.text[:300]}"
        )


# ===========================================================================
# Data Asset Reviews
# ===========================================================================

class TestDataAssetReviewsSmoke:
    """Smoke tests for Data Asset Reviews endpoints."""

    @pytest.mark.readonly
    def test_list_review_requests(self, api, url):
        """GET /api/data-asset-reviews — list all review requests."""
        resp = api.get(url("/api/data-asset-reviews"))
        assert resp.status_code not in (500,), (
            f"GET /api/data-asset-reviews returned 500: {resp.text[:300]}"
        )
        assert resp.status_code in _OK_DB, (
            f"Unexpected status {resp.status_code}: {resp.text[:300]}"
        )

    @pytest.mark.readonly
    def test_list_review_requests_with_pagination(self, api, url):
        """GET /api/data-asset-reviews?skip=0&limit=5 — pagination params forwarded."""
        resp = api.get(url("/api/data-asset-reviews"), params={"skip": 0, "limit": 5})
        assert resp.status_code not in (500,), (
            f"GET /api/data-asset-reviews with pagination returned 500: {resp.text[:300]}"
        )

    @pytest.mark.readonly
    def test_get_review_request_nonexistent(self, api, url):
        """GET /api/data-asset-reviews/{id} — 404 for unknown ID."""
        resp = api.get(url("/api/data-asset-reviews/nonexistent-review-id"))
        assert resp.status_code in (200, 400, 403, 404, 422), (
            f"Unexpected status {resp.status_code}: {resp.text[:300]}"
        )

    def test_create_review_request_minimal(self, api, url):
        """POST /api/data-asset-reviews — minimal payload; any non-500 is acceptable.

        We send a real-looking but synthetic payload.  The endpoint may reject it
        with 400/422 (invalid asset FQN, unknown emails, etc.) — that is fine.
        The only failure is an unhandled 500.
        """
        payload = {
            "requester_email": "e2e-requester@example.com",
            "reviewer_email": "e2e-reviewer@example.com",
            "asset_fqns": ["e2e_catalog.e2e_schema.e2e_smoke_table"],
            "notes": "E2E smoke test — created by test_34_external_deps",
        }
        resp = api.post(url("/api/data-asset-reviews"), json=payload)
        # 201 if created, 400/422 if rejected, 403 if permission denied
        assert resp.status_code in (201, 400, 403, 422), (
            f"Unexpected status {resp.status_code}: {resp.text[:300]}"
        )

    @pytest.mark.readonly
    def test_get_review_asset_definition_nonexistent_request(self, api, url):
        """GET /api/data-asset-reviews/{rid}/assets/{aid}/definition — 404 expected."""
        resp = api.get(
            url("/api/data-asset-reviews/nonexistent-request/assets/nonexistent-asset/definition")
        )
        assert resp.status_code not in (500,), (
            f"GET asset definition for nonexistent request returned 500: {resp.text[:300]}"
        )
        assert resp.status_code in _OK_DB, (
            f"Unexpected status {resp.status_code}: {resp.text[:300]}"
        )

    @pytest.mark.readonly
    def test_get_review_asset_preview_nonexistent_request(self, api, url):
        """GET /api/data-asset-reviews/{rid}/assets/{aid}/preview — 404 expected."""
        resp = api.get(
            url("/api/data-asset-reviews/nonexistent-request/assets/nonexistent-asset/preview")
        )
        assert resp.status_code not in (500,), (
            f"GET asset preview for nonexistent request returned 500: {resp.text[:300]}"
        )
        assert resp.status_code in _OK_DB, (
            f"Unexpected status {resp.status_code}: {resp.text[:300]}"
        )


# ===========================================================================
# MCP Tokens
# ===========================================================================

class TestMcpTokensSmoke:
    """Smoke tests for MCP Token management endpoints.

    Requires settings READ_WRITE permission — 403 is the common case for
    non-admin credentials.
    """

    @pytest.mark.readonly
    def test_list_mcp_tokens(self, api, url):
        """GET /api/mcp-tokens — list all MCP API tokens."""
        resp = api.get(url("/api/mcp-tokens"))
        assert resp.status_code not in (500,), (
            f"GET /api/mcp-tokens returned 500: {resp.text[:300]}"
        )
        # Admin-only: 403 is expected for non-admin test credentials
        assert resp.status_code in _OK_DB, (
            f"Unexpected status {resp.status_code}: {resp.text[:300]}"
        )

    @pytest.mark.readonly
    def test_list_mcp_tokens_include_inactive(self, api, url):
        """GET /api/mcp-tokens?include_inactive=true — inactive tokens included."""
        resp = api.get(url("/api/mcp-tokens"), params={"include_inactive": "true"})
        assert resp.status_code not in (500,), (
            f"GET /api/mcp-tokens?include_inactive=true returned 500: {resp.text[:300]}"
        )

    @pytest.mark.readonly
    def test_get_mcp_token_nonexistent(self, api, url):
        """GET /api/mcp-tokens/{id} — 404 for a random UUID."""
        import uuid
        fake_id = str(uuid.uuid4())
        resp = api.get(url(f"/api/mcp-tokens/{fake_id}"))
        assert resp.status_code not in (500,), (
            f"GET mcp-token with random UUID returned 500: {resp.text[:300]}"
        )
        assert resp.status_code in _OK_DB, (
            f"Unexpected status {resp.status_code}: {resp.text[:300]}"
        )


# ===========================================================================
# Self-Service
# ===========================================================================

class TestSelfServiceSmoke:
    """Smoke tests for Self-Service endpoints.

    The bootstrap endpoint is a POST but it is idempotent — it creates or
    retrieves the user's personal team/project and returns defaults.
    It may fail with 403 if the user lacks data-contracts READ_WRITE,
    or 500 only if something truly breaks.
    """

    def test_self_service_bootstrap(self, api, url):
        """POST /api/self-service/bootstrap — idempotent; creates user team/project."""
        resp = api.post(url("/api/self-service/bootstrap"))
        # 200 on success, 403 if no permission, 503 if DB not configured
        assert resp.status_code in (200, 403, 422, 503), (
            f"Unexpected status {resp.status_code}: {resp.text[:300]}"
        )


# ===========================================================================
# MDM Config CRUD — happy-path
# ===========================================================================

class TestMdmCrud:
    """Happy-path CRUD tests for MDM configurations.

    MDM requires Zingg.ai infrastructure and specific UC tables, so create
    will often fail with 400/422 in environments without that setup.  The
    tests skip gracefully in those cases rather than marking as failures.
    """

    @pytest.mark.crud
    def test_mdm_config_crud(self, api, url):
        """POST → GET → PUT → DELETE for an MDM config."""
        import uuid

        name = f"e2e-mdm-{uuid.uuid4().hex[:8]}"
        payload = {
            "name": name,
            "description": "E2E MDM config",
            "source_table": "e2e_catalog.e2e_schema.e2e_table",
            "key_columns": ["id"],
            "match_columns": ["name"],
        }

        # Create
        resp = api.post(url("/api/mdm/configs"), json=payload)
        assert resp.status_code not in (500,), (
            f"POST /api/mdm/configs returned 500: {resp.text[:300]}"
        )
        if resp.status_code in (400, 422, 403, 503):
            pytest.skip(
                f"POST /api/mdm/configs rejected with {resp.status_code} — "
                "no MDM infrastructure available"
            )
        assert resp.status_code in (200, 201), (
            f"Unexpected create status {resp.status_code}: {resp.text[:300]}"
        )

        data = resp.json()
        config_id = data.get("id") or data.get("config_id")
        assert config_id, f"Response missing id field: {data}"

        try:
            # Read back
            get_resp = api.get(url(f"/api/mdm/configs/{config_id}"))
            assert get_resp.status_code == 200, (
                f"GET /api/mdm/configs/{config_id} returned {get_resp.status_code}"
            )

            # Update
            update_payload = {**payload, "description": "E2E MDM config — updated"}
            put_resp = api.put(url(f"/api/mdm/configs/{config_id}"), json=update_payload)
            assert put_resp.status_code not in (500,), (
                f"PUT /api/mdm/configs/{config_id} returned 500: {put_resp.text[:300]}"
            )
            assert put_resp.status_code in (200, 204), (
                f"Unexpected update status {put_resp.status_code}: {put_resp.text[:300]}"
            )
        finally:
            # Always attempt cleanup
            del_resp = api.delete(url(f"/api/mdm/configs/{config_id}"))
            assert del_resp.status_code not in (500,), (
                f"DELETE /api/mdm/configs/{config_id} returned 500: {del_resp.text[:300]}"
            )
            assert del_resp.status_code in (200, 204), (
                f"Unexpected delete status {del_resp.status_code}: {del_resp.text[:300]}"
            )


# ===========================================================================
# MCP Tokens CRUD — happy-path
# ===========================================================================

class TestMcpTokensCrud:
    """Happy-path create-and-delete tests for MCP API tokens.

    Requires SETTINGS READ_WRITE permission.  403 triggers a skip rather
    than a failure so non-admin test credentials don't break the suite.
    """

    @pytest.mark.crud
    def test_mcp_token_create_and_delete(self, api, url):
        """POST /api/mcp-tokens then DELETE /api/mcp-tokens/{id}."""
        import uuid

        payload = {
            "name": f"e2e-token-{uuid.uuid4().hex[:8]}",
            "description": "E2E test token",
        }

        # Create
        resp = api.post(url("/api/mcp-tokens"), json=payload)
        assert resp.status_code not in (500,), (
            f"POST /api/mcp-tokens returned 500: {resp.text[:300]}"
        )
        if resp.status_code in (400, 403, 422):
            pytest.skip(
                f"POST /api/mcp-tokens rejected with {resp.status_code} — "
                "insufficient permissions or invalid payload"
            )
        assert resp.status_code in (200, 201), (
            f"Unexpected create status {resp.status_code}: {resp.text[:300]}"
        )

        data = resp.json()
        token_id = data.get("id") or data.get("token_id")
        assert token_id, f"Response missing id field: {data}"

        # Delete
        del_resp = api.delete(url(f"/api/mcp-tokens/{token_id}"))
        assert del_resp.status_code not in (500,), (
            f"DELETE /api/mcp-tokens/{token_id} returned 500: {del_resp.text[:300]}"
        )
        assert del_resp.status_code in (200, 204), (
            f"Unexpected delete status {del_resp.status_code}: {del_resp.text[:300]}"
        )


# ===========================================================================
# Data Asset Reviews CRUD — happy-path
# ===========================================================================

class TestDataAssetReviewsCrud:
    """Happy-path create-and-delete tests for Data Asset Reviews.

    Many environments will reject the synthetic asset FQN with 400/403/422.
    Those cases skip rather than fail so the suite stays green without real UC
    assets being present.
    """

    @pytest.mark.crud
    def test_create_and_delete_review_request(self, api, url):
        """POST /api/data-asset-reviews then DELETE /api/data-asset-reviews/{id}."""
        payload = {
            "asset_fqns": ["e2e_catalog.e2e_schema.e2e_table"],
            "review_type": "standard",
            "description": "E2E test review",
        }

        # Create
        resp = api.post(url("/api/data-asset-reviews"), json=payload)
        assert resp.status_code not in (500,), (
            f"POST /api/data-asset-reviews returned 500: {resp.text[:300]}"
        )
        if resp.status_code in (400, 403, 422):
            pytest.skip(
                f"POST /api/data-asset-reviews rejected with {resp.status_code} — "
                "no valid UC asset or insufficient permission"
            )
        assert resp.status_code == 201, (
            f"Unexpected create status {resp.status_code}: {resp.text[:300]}"
        )

        data = resp.json()
        request_id = data.get("id") or data.get("request_id")
        assert request_id, f"Response missing id field: {data}"

        # Delete
        del_resp = api.delete(url(f"/api/data-asset-reviews/{request_id}"))
        assert del_resp.status_code not in (500,), (
            f"DELETE /api/data-asset-reviews/{request_id} returned 500: {del_resp.text[:300]}"
        )
        assert del_resp.status_code in (200, 204), (
            f"Unexpected delete status {del_resp.status_code}: {del_resp.text[:300]}"
        )


# ===========================================================================
# Entitlements Sync Config CRUD — happy-path
# ===========================================================================

class TestEntitlementsSyncCrud:
    """Happy-path CRUD tests for Entitlements Sync configurations.

    This feature is ADMIN-only.  403 is the expected result in most test
    environments and causes a skip.
    """

    @pytest.mark.crud
    def test_entitlements_sync_config_crud(self, api, url):
        """POST → PUT → DELETE for an entitlements sync config."""
        import uuid

        name = f"e2e-sync-{uuid.uuid4().hex[:8]}"
        payload = {
            "name": name,
            "catalog_name": "e2e_catalog",
            "sync_type": "full",
        }

        # Create
        resp = api.post(url("/api/entitlements-sync/configs"), json=payload)
        assert resp.status_code not in (500,), (
            f"POST /api/entitlements-sync/configs returned 500: {resp.text[:300]}"
        )
        if resp.status_code in (400, 403, 422, 503):
            pytest.skip(
                f"POST /api/entitlements-sync/configs rejected with {resp.status_code} — "
                "insufficient permissions or feature not configured"
            )
        assert resp.status_code in (200, 201), (
            f"Unexpected create status {resp.status_code}: {resp.text[:300]}"
        )

        data = resp.json()
        config_id = data.get("id") or data.get("config_id")
        assert config_id, f"Response missing id field: {data}"

        try:
            # Update — add a description
            update_payload = {**payload, "description": "E2E entitlements sync — updated"}
            put_resp = api.put(
                url(f"/api/entitlements-sync/configs/{config_id}"), json=update_payload
            )
            assert put_resp.status_code not in (500,), (
                f"PUT /api/entitlements-sync/configs/{config_id} returned 500: "
                f"{put_resp.text[:300]}"
            )
            assert put_resp.status_code in (200, 204), (
                f"Unexpected update status {put_resp.status_code}: {put_resp.text[:300]}"
            )
        finally:
            # Always attempt cleanup
            del_resp = api.delete(url(f"/api/entitlements-sync/configs/{config_id}"))
            assert del_resp.status_code not in (500,), (
                f"DELETE /api/entitlements-sync/configs/{config_id} returned 500: "
                f"{del_resp.text[:300]}"
            )
            assert del_resp.status_code in (200, 204), (
                f"Unexpected delete status {del_resp.status_code}: {del_resp.text[:300]}"
            )


# ===========================================================================
# Industry Ontology Actions — happy-path
# ===========================================================================

class TestIndustryOntologyActions:
    """Happy-path tests for mutating Industry Ontology actions (cache, reload).

    These are action endpoints with no persistent side-effects, so they are
    safe to call in any environment.
    """

    @pytest.mark.crud
    def test_clear_ontology_cache(self, api, url):
        """DELETE /api/industry-ontologies/cache — clears the in-memory ontology cache."""
        resp = api.delete(url("/api/industry-ontologies/cache"))
        assert resp.status_code not in (500,), (
            f"DELETE /api/industry-ontologies/cache returned 500: {resp.text[:300]}"
        )
        assert resp.status_code in (200, 204), (
            f"Unexpected status {resp.status_code}: {resp.text[:300]}"
        )

    @pytest.mark.crud
    def test_reload_ontologies(self, api, url):
        """POST /api/industry-ontologies/reload — triggers an ontology reload."""
        resp = api.post(url("/api/industry-ontologies/reload"))
        assert resp.status_code not in (500,), (
            f"POST /api/industry-ontologies/reload returned 500: {resp.text[:300]}"
        )
        assert resp.status_code == 200, (
            f"Unexpected status {resp.status_code}: {resp.text[:300]}"
        )


# ===========================================================================
# Data Catalog Extended — detail drill-down
# ===========================================================================

class TestDataCatalogExtended:
    """Extended Data Catalog tests that drill into a real table if one is available.

    The list endpoint is called first; if it returns actual results the test
    fetches details for the first entry.  If the catalog is empty or
    unreachable the test skips.
    """

    @pytest.mark.readonly
    def test_get_table_list_with_details(self, api, url):
        """GET /api/data-catalog/tables, then GET detail for the first real table."""
        list_resp = api.get(url("/api/data-catalog/tables"))
        assert list_resp.status_code not in (500,), (
            f"GET /api/data-catalog/tables returned 500: {list_resp.text[:300]}"
        )
        assert list_resp.status_code in _OK, (
            f"Unexpected list status {list_resp.status_code}: {list_resp.text[:300]}"
        )

        if list_resp.status_code != 200:
            pytest.skip(
                f"GET /api/data-catalog/tables returned {list_resp.status_code} — "
                "cannot drill into table details"
            )

        tables = list_resp.json()
        # Normalise: response may be a list or a dict with a nested list
        if isinstance(tables, dict):
            tables = tables.get("tables") or tables.get("items") or tables.get("data") or []

        if not tables:
            pytest.skip("No tables returned by /api/data-catalog/tables — skipping detail test")

        # Pick the first entry; FQN may be a top-level field or nested catalog/schema/name
        first = tables[0]
        if isinstance(first, str):
            # Response is a flat list of FQN strings
            fqn = first
            parts = fqn.split(".")
        else:
            fqn = first.get("full_name") or first.get("fqn") or first.get("name")
            parts = fqn.split(".") if fqn else []

        if len(parts) != 3:
            pytest.skip(
                f"Cannot determine three-part FQN from first table entry: {first!r}"
            )

        catalog, schema, table = parts

        detail_resp = api.get(url(f"/api/data-catalog/tables/{catalog}/{schema}/{table}"))
        assert detail_resp.status_code not in (500,), (
            f"GET /api/data-catalog/tables/{catalog}/{schema}/{table} returned 500: "
            f"{detail_resp.text[:300]}"
        )
        assert detail_resp.status_code == 200, (
            f"Unexpected detail status {detail_resp.status_code}: {detail_resp.text[:300]}"
        )
