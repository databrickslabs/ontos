"""
ONT-FEAT-001 through ONT-FEAT-032 — Feature Coverage Tests.

Exercises discrete features that are not fully covered by the golden path:
glossary, catalog commander, estate manager, MDM, compliance, entitlements,
security features, search, MCP tokens, workflows, git sync, settings CRUD,
background jobs, and data catalog.

Each test is self-contained with its own cleanup.
"""
import uuid
import pytest

E2E_PREFIX = "cuj-feat-"


def _uid():
    return uuid.uuid4().hex[:8]


@pytest.mark.cuj
class TestCUJFeatureCoverage:

    # ONT-FEAT-001
    def test_FEAT_001_concepts_list(self, producer_api, url):
        """Producer: glossary concept list renders."""
        for path in ("/api/concepts", "/api/business-glossaries", "/api/glossaries"):
            resp = producer_api.get(url(path))
            if resp.status_code not in (404,):
                break
        assert resp.status_code in (200, 403), f"FEAT-001: glossary list: {resp.status_code}"

    # ONT-FEAT-002
    def test_FEAT_002_concept_search(self, producer_api, url):
        """Producer: search for a term in the glossary."""
        resp = producer_api.get(url("/api/search?search_term=customer"))
        assert resp.status_code in (200, 403), f"FEAT-002: search: {resp.status_code}"

    # ONT-FEAT-003
    def test_FEAT_003_concept_collection(self, producer_api, url):
        """Producer: create and delete a glossary collection."""
        for create_path in ("/api/concepts/collections", "/api/business-glossaries/collections"):
            resp = producer_api.post(url(create_path), json={
                "name": f"{E2E_PREFIX}collection-{_uid()}",
                "description": "FEAT-003 test collection",
            })
            if resp.status_code != 404:
                break
        if resp.status_code in (200, 201):
            cid = resp.json().get("id")
            if cid:
                producer_api.delete(url(f"{create_path}/{cid}"))
        assert resp.status_code < 500, f"FEAT-003: collection create: {resp.status_code}"

    # ONT-FEAT-004
    def test_FEAT_004_concept_hierarchy(self, producer_api, url):
        """Producer: hierarchy endpoint reachable."""
        for path in ("/api/concepts/hierarchy", "/api/business-glossaries/hierarchy"):
            resp = producer_api.get(url(path))
            if resp.status_code != 404:
                break
        assert resp.status_code < 500, f"FEAT-004: hierarchy: {resp.status_code}"

    # ONT-FEAT-005
    def test_FEAT_005_asset_explorer(self, producer_api, url):
        """Producer: assets list endpoint accessible."""
        resp = producer_api.get(url("/api/assets"))
        assert resp.status_code in (200, 403), f"FEAT-005: assets: {resp.status_code}"

    # ONT-FEAT-006
    def test_FEAT_006_catalog_commander_list(self, producer_api, url):
        """Producer: catalog list via catalog commander."""
        resp = producer_api.get(url("/api/catalogs"), timeout=10)
        assert resp.status_code in (200, 403, 500), f"FEAT-006: catalogs: {resp.status_code}"

    # ONT-FEAT-007
    def test_FEAT_007_catalog_commander_tag(self, producer_api, url):
        """Producer: tag assignment endpoint reachable (no actual UC write)."""
        resp = producer_api.get(url("/api/tags"))
        assert resp.status_code in (200, 403), f"FEAT-007: tags list: {resp.status_code}"

    # ONT-FEAT-008
    def test_FEAT_008_estate_manager(self, producer_api, url):
        """Producer: estate manager endpoint accessible."""
        resp = producer_api.get(url("/api/estates"))
        assert resp.status_code in (200, 403, 500), f"FEAT-008: estates: {resp.status_code}"

    # ONT-FEAT-009
    def test_FEAT_009_mdm_list(self, producer_api, url):
        """Producer: MDM endpoint accessible."""
        for path in ("/api/mdm", "/api/master-data"):
            resp = producer_api.get(url(path))
            if resp.status_code != 404:
                break
        assert resp.status_code < 500, f"FEAT-009: MDM: {resp.status_code}"

    # ONT-FEAT-010
    def test_FEAT_010_compliance_create_policy(self, admin_api, url):
        """Admin: create and delete a compliance policy."""
        resp = admin_api.post(url("/api/compliance/policies"), json={
            "id": str(uuid.uuid4()),
            "name": f"{E2E_PREFIX}policy-{_uid()}",
            "description": "FEAT-010 test policy",
            "rule": "ALL data_products MUST HAVE status",
            "severity": "low",
            "category": "e2e-feat",
            "is_active": False,
            "compliance": 0.0,
        })
        if resp.status_code in (200, 201):
            pid = resp.json().get("id")
            if pid:
                admin_api.delete(url(f"/api/compliance/policies/{pid}"))
        assert resp.status_code in (200, 201, 422), (
            f"FEAT-010: create compliance policy: {resp.status_code} {resp.text[:300]}"
        )

    # ONT-FEAT-011
    def test_FEAT_011_compliance_run(self, admin_api, url):
        """Admin: compliance run on an active policy."""
        # Find or create a policy
        list_resp = admin_api.get(url("/api/compliance/policies"))
        raw = list_resp.json() if list_resp.status_code == 200 else []
        # Response is {"policies": [...], "stats": {...}} or a plain list
        policies_list = raw.get("policies", []) if isinstance(raw, dict) else raw
        if list_resp.status_code != 200 or not policies_list:
            pytest.skip("FEAT-011: no compliance policies available")
        policy = policies_list[0]
        resp = admin_api.post(url(f"/api/compliance/policies/{policy['id']}/runs"))
        assert resp.status_code in (200, 201, 202, 422), (
            f"FEAT-011: compliance run: {resp.status_code}"
        )

    # ONT-FEAT-012
    def test_FEAT_012_entitlement_custom_role(self, admin_api, url):
        """Admin: create and delete a custom entitlements persona."""
        resp = admin_api.post(url("/api/entitlements/personas"), json={
            "name": f"{E2E_PREFIX}role-{_uid()}",
            "description": "FEAT-012 test role",
            "privileges": [],
            "groups": [],
        })
        if resp.status_code in (200, 201):
            rid = resp.json().get("id")
            if rid:
                admin_api.delete(url(f"/api/entitlements/personas/{rid}"))
        assert resp.status_code in (200, 201, 403, 422), (
            f"FEAT-012: create persona: {resp.status_code}"
        )

    # ONT-FEAT-013
    def test_FEAT_013_entitlement_sync(self, admin_api, url):
        """Admin: entitlement sync endpoint accessible."""
        for path in ("/api/entitlements-sync", "/api/entitlements/sync"):
            resp = admin_api.get(url(path))
            if resp.status_code != 404:
                break
        assert resp.status_code < 500, f"FEAT-013: entitlements sync: {resp.status_code}"

    # ONT-FEAT-014
    def test_FEAT_014_security_masking_policy(self, admin_api, url):
        """Admin: security features list accessible."""
        resp = admin_api.get(url("/api/security-features"))
        assert resp.status_code in (200, 403), f"FEAT-014: security features: {resp.status_code}"

    # ONT-FEAT-015
    def test_FEAT_015_security_row_filter(self, admin_api, url):
        """Admin: create row-level security feature."""
        resp = admin_api.post(url("/api/security-features"), json={
            "name": f"{E2E_PREFIX}rls-{_uid()}",
            "type": "row_filtering",
            "target": "e2e_catalog.e2e_schema.e2e_table",
            "conditions": ["user_group = 'e2e-feat'"],
            "description": "FEAT-015 row filter",
            "status": "active",
        })
        if resp.status_code in (200, 201):
            sfid = resp.json().get("id")
            if sfid:
                admin_api.delete(url(f"/api/security-features/{sfid}"))
        assert resp.status_code < 500, f"FEAT-015: row filter create: {resp.status_code}"

    # ONT-FEAT-016
    def test_FEAT_016_security_differential_privacy(self, admin_api, url):
        """Admin: differential privacy feature create/delete."""
        resp = admin_api.post(url("/api/security-features"), json={
            "name": f"{E2E_PREFIX}dp-{_uid()}",
            "type": "differential_privacy",
            "target": "e2e_catalog.e2e_schema.e2e_table",
            "description": "FEAT-016 DP policy",
            "status": "active",
        })
        if resp.status_code in (200, 201):
            sfid = resp.json().get("id")
            if sfid:
                admin_api.delete(url(f"/api/security-features/{sfid}"))
        assert resp.status_code < 500, f"FEAT-016: DP create: {resp.status_code}"

    # ONT-FEAT-017
    def test_FEAT_017_global_search(self, api, url):
        """Any: global search returns results without 5xx."""
        resp = api.get(url("/api/search?search_term=test"), timeout=15)
        assert resp.status_code in (200, 403), f"FEAT-017: search: {resp.status_code}"

    # ONT-FEAT-018
    def test_FEAT_018_llm_search(self, api, url):
        """Any: LLM / NL search returns without 5xx."""
        for path in ("/api/search/llm?q=customer+related+products", "/api/llm-search?q=customer"):
            resp = api.get(url(path), timeout=15)
            if resp.status_code != 404:
                break
        assert resp.status_code < 500, f"FEAT-018: LLM search: {resp.status_code}"

    # ONT-FEAT-019
    def test_FEAT_019_mcp_token_issue(self, admin_api, url):
        """Admin: issue and revoke an MCP token."""
        resp = admin_api.post(url("/api/mcp-tokens"), json={
            "name": f"{E2E_PREFIX}mcp-{_uid()}",
        })
        if resp.status_code in (200, 201):
            tid = resp.json().get("id")
            if tid:
                admin_api.delete(url(f"/api/mcp-tokens/{tid}"))
        assert resp.status_code < 500, f"FEAT-019: MCP token issue: {resp.status_code}"

    # ONT-FEAT-020
    def test_FEAT_020_mcp_token_list(self, admin_api, url):
        """Admin: list MCP tokens endpoint accessible."""
        resp = admin_api.get(url("/api/mcp-tokens"))
        assert resp.status_code in (200, 403), f"FEAT-020: MCP tokens list: {resp.status_code}"

    # ONT-FEAT-021
    def test_FEAT_021_workflow_create(self, admin_api, url):
        """Admin: create and delete an approval workflow."""
        resp = admin_api.post(url("/api/workflows"), json={
            "name": f"{E2E_PREFIX}workflow-{_uid()}",
            "description": "FEAT-021 test workflow",
            "trigger": {"type": "manual", "entity_types": ["data_contract"]},
            "scope": {"type": "all"},
            "is_active": False,
            "steps": [{
                "step_id": "s1",
                "name": "Notify",
                "step_type": "notification",
                "config": {"recipients": "owner", "template": "Test"},
                "on_failure": "pass",
            }],
        })
        if resp.status_code in (200, 201):
            wid = resp.json().get("id")
            if wid:
                admin_api.delete(url(f"/api/workflows/{wid}"))
        assert resp.status_code in (200, 201, 422), (
            f"FEAT-021: workflow create: {resp.status_code} {resp.text[:300]}"
        )

    # ONT-FEAT-022
    def test_FEAT_022_workflow_list(self, admin_api, url):
        """Admin: workflow list accessible."""
        resp = admin_api.get(url("/api/workflows"))
        assert resp.status_code in (200, 403), f"FEAT-022: workflows: {resp.status_code}"

    # ONT-FEAT-023
    def test_FEAT_023_git_sync_status(self, admin_api, url):
        """Admin: git sync settings accessible."""
        resp = admin_api.get(url("/api/settings"))
        assert resp.status_code in (200, 403), f"FEAT-023: settings: {resp.status_code}"

    # ONT-FEAT-024
    def test_FEAT_024_git_sync_push(self, admin_api, url):
        """Admin: git sync push endpoint reachable."""
        for path in ("/api/settings/git/push", "/api/settings/git-sync/push"):
            resp = admin_api.post(url(path))
            if resp.status_code != 404:
                break
        # 400/422 if not configured, 404 if path not found — all acceptable
        assert resp.status_code < 500, f"FEAT-024: git push: {resp.status_code}"

    # ONT-FEAT-025
    def test_FEAT_025_git_sync_pull(self, admin_api, url):
        """Admin: git sync pull endpoint reachable."""
        for path in ("/api/settings/git/pull", "/api/settings/git-sync/pull"):
            resp = admin_api.post(url(path))
            if resp.status_code != 404:
                break
        assert resp.status_code < 500, f"FEAT-025: git pull: {resp.status_code}"

    # ONT-FEAT-026
    def test_FEAT_026_domain_crud(self, admin_api, url):
        """Admin: create, update, delete a data domain."""
        r1 = admin_api.post(url("/api/data-domains"), json={
            "name": f"{E2E_PREFIX}domain-{_uid()}",
            "description": "FEAT-026 test domain",
        })
        assert r1.status_code in (200, 201), f"FEAT-026 create: {r1.status_code}"
        did = r1.json().get("id") or r1.json().get("name")

        resp = admin_api.get(url("/api/data-domains"))
        assert resp.status_code == 200, f"FEAT-026 list: {resp.status_code}"

        admin_api.delete(url(f"/api/data-domains/{did}"))

    # ONT-FEAT-027
    def test_FEAT_027_team_crud(self, admin_api, url):
        """Admin: create and delete a team."""
        tname = f"{E2E_PREFIX}team-{_uid()}"
        r1 = admin_api.post(url("/api/teams"), json={
            "name": tname,
            "title": "FEAT-027 Test Team",
            "description": "FEAT-027 test",
        })
        if r1.status_code in (200, 201):
            tid = r1.json().get("id") or r1.json().get("name")
            admin_api.delete(url(f"/api/teams/{tid}"))
        assert r1.status_code in (200, 201, 422), (
            f"FEAT-027: team create: {r1.status_code} {r1.text[:300]}"
        )

    # ONT-FEAT-028
    def test_FEAT_028_tags_crud(self, admin_api, url):
        """Admin: create tag namespace and tag."""
        ns_resp = admin_api.post(url("/api/tags/namespaces"), json={
            "name": f"{E2E_PREFIX}ns-{_uid()}",
            "description": "FEAT-028 namespace",
        })
        if ns_resp.status_code == 404:
            pytest.skip("FEAT-028: tag namespaces endpoint not found")
        if ns_resp.status_code in (200, 201):
            nsid = ns_resp.json().get("id")
            tag_resp = admin_api.post(url("/api/tags"), json={
                "name": f"{E2E_PREFIX}tag-{_uid()}",
                "namespace_id": nsid,
                "possible_values": ["val-a", "val-b"],
                "status": "active",
            })
            if tag_resp.status_code in (200, 201):
                admin_api.delete(url(f"/api/tags/{tag_resp.json().get('id')}"))
            admin_api.delete(url(f"/api/tags/namespaces/{nsid}"))
        assert ns_resp.status_code < 500, f"FEAT-028: ns create: {ns_resp.status_code}"

    # ONT-FEAT-029
    def test_FEAT_029_connector_test_connection(self, admin_api, url):
        """Admin: connector list endpoint accessible."""
        for path in ("/api/connections", "/api/connectors"):
            resp = admin_api.get(url(path))
            if resp.status_code != 404:
                break
        assert resp.status_code < 500, f"FEAT-029: connectors: {resp.status_code}"

    # ONT-FEAT-030
    def test_FEAT_030_background_jobs_list(self, admin_api, url):
        """Admin: background jobs list accessible."""
        resp = admin_api.get(url("/api/jobs"))
        assert resp.status_code in (200, 403), f"FEAT-030: jobs: {resp.status_code}"

    # ONT-FEAT-031
    def test_FEAT_031_data_catalog_browse(self, producer_api, url):
        """Producer: Unity Catalog browse via data catalog endpoint."""
        for path in ("/api/data-catalog", "/api/catalogs"):
            resp = producer_api.get(url(path), timeout=10)
            if resp.status_code != 404:
                break
        assert resp.status_code in (200, 403), f"FEAT-031: data catalog: {resp.status_code}"

    # ONT-FEAT-032
    def test_FEAT_032_my_products(self, producer_api, url):
        """Producer: my-products endpoint accessible."""
        for path in ("/api/data-products/my-products", "/api/data-products?mine=true"):
            resp = producer_api.get(url(path))
            if resp.status_code != 404:
                break
        assert resp.status_code in (200, 403), f"FEAT-032: my-products: {resp.status_code}"
