"""Routing tests for the concept-by-IRI endpoints.

These cover the query-param variants (``/concepts/by-iri?iri=...``) that were
added because the path-form (``/concepts/{concept_iri:path}``) routes lose
``%2F%2F`` segments to proxy normalisation. Both shapes must work for the
backward-compat migration window.

Targets two route families:

* ``GET /api/semantic-models/concepts/by-iri`` — read-only details from the
  semantic models manager. Falls back to a path-form deprecated alias.
* ``GET/PATCH/DELETE /api/knowledge/concepts/by-iri`` — and the lifecycle
  variants under ``/by-iri/<action>``. Each also has a deprecated path-form
  alias.
"""
from __future__ import annotations

import uuid
from pathlib import Path
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from src.app import app
from src.controller.semantic_models_manager import SemanticModelsManager
from src.common.app_state import set_app_state_manager


# ---------------------------------------------------------------------------
# Fixtures (mirror test_knowledge_routes.py — kept local so this file runs
# standalone even if the other module's fixtures move).
# ---------------------------------------------------------------------------


@pytest.fixture
def semantic_models_manager(db_session: Session, tmp_path: Path):
    data_dir = tmp_path / "sm_data"
    (data_dir / "cache").mkdir(parents=True, exist_ok=True)
    (data_dir / "taxonomies").mkdir(parents=True, exist_ok=True)

    manager = SemanticModelsManager(db=db_session, data_dir=data_dir)

    app.state.semantic_models_manager = manager
    set_app_state_manager("semantic_models_manager", manager)

    class _NoopOSM:
        def sync_asset_types(self, *_args, **_kwargs):
            return {"created": 0, "updated": 0}

    app.state.ontology_schema_manager = _NoopOSM()

    class _NoopAudit:
        def log_action(self, *_args, **_kwargs):
            return None

        def log_event(self, *_args, **_kwargs):
            return None

    app.state.audit_manager = _NoopAudit()

    yield manager

    for attr in ("semantic_models_manager", "ontology_schema_manager", "audit_manager"):
        if hasattr(app.state, attr):
            delattr(app.state, attr)


@pytest.fixture
def make_collection(client: TestClient, semantic_models_manager):
    def _make(label_prefix: str = "Routing Coll") -> dict:
        label = f"{label_prefix} {uuid.uuid4().hex[:8]}"
        r = client.post(
            "/api/knowledge/collections",
            json={
                "label": label,
                "collection_type": "glossary",
                "scope_level": "enterprise",
                "description": "made by concept-iri routing test",
            },
        )
        assert r.status_code == 200, r.text
        return r.json()

    return _make


@pytest.fixture
def make_concept(client: TestClient, make_collection):
    """Create a fresh collection + concept and return the concept body."""

    def _make(label: str = "Routing Term") -> dict:
        collection = make_collection()
        r = client.post(
            "/api/knowledge/concepts",
            json={"collection_iri": collection["iri"], "label": label},
        )
        assert r.status_code == 200, r.text
        return r.json()

    return _make


# ---------------------------------------------------------------------------
# /api/knowledge/concepts/by-iri (the canonical, proxy-safe shape)
# ---------------------------------------------------------------------------


class TestKnowledgeConceptsByIri:
    def test_get_by_iri_query_param_returns_concept(
        self, client: TestClient, make_concept
    ):
        c = make_concept("Query Param Get")
        r = client.get(
            "/api/knowledge/concepts/by-iri",
            params={"iri": c["iri"]},
        )
        assert r.status_code == 200, r.text
        assert r.json()["iri"] == c["iri"]

    def test_get_by_iri_requires_iri_param(self, client: TestClient, semantic_models_manager):
        r = client.get("/api/knowledge/concepts/by-iri")
        assert r.status_code == 422, r.text  # FastAPI validation error

    def test_get_by_iri_rejects_empty_iri(self, client: TestClient, semantic_models_manager):
        r = client.get("/api/knowledge/concepts/by-iri", params={"iri": ""})
        assert r.status_code == 422, r.text

    def test_get_by_iri_returns_404_for_unknown(
        self, client: TestClient, semantic_models_manager
    ):
        r = client.get(
            "/api/knowledge/concepts/by-iri",
            params={"iri": "urn:does-not-exist"},
        )
        assert r.status_code == 404

    def test_deprecated_path_form_still_works(
        self, client: TestClient, make_concept
    ):
        """Existing bookmarks must keep resolving for the migration window."""
        c = make_concept("Path Form Still Works")
        r = client.get(f"/api/knowledge/concepts/{c['iri']}")
        assert r.status_code == 200, r.text
        assert r.json()["iri"] == c["iri"]

    def test_patch_by_iri_updates_label(self, client: TestClient, make_concept):
        c = make_concept("Patch By IRI Old")
        r = client.patch(
            "/api/knowledge/concepts/by-iri",
            params={"iri": c["iri"]},
            json={"label": "Patch By IRI New"},
        )
        assert r.status_code == 200, r.text
        assert r.json()["label"] == "Patch By IRI New"

    def test_delete_by_iri_removes_draft(self, client: TestClient, make_concept):
        c = make_concept("Delete By IRI")
        r = client.delete(
            "/api/knowledge/concepts/by-iri",
            params={"iri": c["iri"]},
        )
        assert r.status_code == 200, r.text
        # Follow-up GET must 404 on both shapes
        assert client.get(
            "/api/knowledge/concepts/by-iri", params={"iri": c["iri"]}
        ).status_code == 404
        assert client.get(f"/api/knowledge/concepts/{c['iri']}").status_code == 404

    def test_submit_review_by_iri_action(self, client: TestClient, make_concept):
        """Smoke-test one of the lifecycle ``/by-iri/<action>`` endpoints.

        The point of this test is to prove the lifecycle route is wired through
        — not to re-test the manager's state machine (covered elsewhere). A
        fresh draft concept advances to ``under_review`` on submit-review.
        """
        c = make_concept("Submit Review By IRI")
        r = client.post(
            "/api/knowledge/concepts/by-iri/submit-review",
            params={"iri": c["iri"]},
            json={},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        # Endpoint returns ``{review_data, concept}``; concept moves to under_review.
        assert body["concept"]["status"] == "under_review"


# ---------------------------------------------------------------------------
# /api/semantic-models/concepts/by-iri — read-only details endpoint
# ---------------------------------------------------------------------------


class TestSemanticModelsConceptsByIri:
    def test_query_param_route_404_for_unknown_iri(
        self, client: TestClient, semantic_models_manager
    ):
        """The route must be reachable (and respond 404) even when the iri is
        not present in the graph. This guards against route-ordering bugs where
        ``/by-iri`` might be shadowed by ``/{concept_iri:path}``.
        """
        r = client.get(
            "/api/semantic-models/concepts/by-iri",
            params={"iri": "http://example.org/ontology#NotARealConcept"},
        )
        # 404 (concept missing) is the success signal; a 422 / 500 would mean
        # the route is wired wrong.
        assert r.status_code == 404, r.text

    def test_query_param_route_preserves_http_iri(
        self, client: TestClient, semantic_models_manager
    ):
        """Reproducer for the original bug: ``http://...`` IRIs survive
        end-to-end as long as we use the query-string form, even when the path
        contains the ``%2F%2F`` that proxies otherwise collapse.
        """
        iri = "http://ontos.example.org/ontology#Customer"
        # urlencode includes %2F%2F — the route handler must see them as-is.
        r = client.get(
            f"/api/semantic-models/concepts/by-iri?iri={quote(iri, safe='')}"
        )
        # We don't expect a payload (concept doesn't exist), but the request
        # itself must reach the handler intact and 404 instead of 422/500.
        assert r.status_code == 404, r.text

    def test_deprecated_path_form_still_registered(
        self, client: TestClient, semantic_models_manager
    ):
        r = client.get("/api/semantic-models/concepts/urn:not-a-real-iri")
        assert r.status_code == 404, r.text
