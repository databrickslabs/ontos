"""Regression: the term-mapping run dialog must offer concept schemes authored
on the Explore/Define page (KnowledgeCollections: urn:glossary / urn:ontology),
not only uploaded RDF sources (urn:semantic-model).

Bug (2026-08-17): the "New Term Mapping Run" dialog read the semantic_models
table and reported "No customer ontologies are loaded yet" whenever the user's
ontology lived as a collection rather than an uploaded file — blocking Suggest
matches even though the engine itself accepts any concept scheme. The dialog now
reads GET /api/term-mappings/contexts, which lists every selectable scheme in the
graph. This test pins that a glossary + its concepts show up there.
"""
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from src.app import app
from src.controller.semantic_models_manager import SemanticModelsManager
from src.controller.term_mapping_manager import TermMappingManager
from src.common.app_state import set_app_state_manager


@pytest.fixture
def managers(db_session: Session, tmp_path: Path):
    data_dir = tmp_path / "sm_data"
    (data_dir / "cache").mkdir(parents=True, exist_ok=True)
    (data_dir / "taxonomies").mkdir(parents=True, exist_ok=True)
    smm = SemanticModelsManager(db=db_session, data_dir=data_dir)
    tmm = TermMappingManager(semantic_models_manager=smm)
    app.state.semantic_models_manager = smm
    app.state.term_mapping_manager = tmm
    set_app_state_manager("semantic_models_manager", smm)

    class _Noop:
        def sync_asset_types(self, *a, **k):
            return {"created": 0, "updated": 0}

        def log_action(self, *a, **k):
            return None

        def log_event(self, *a, **k):
            return None

    app.state.ontology_schema_manager = _Noop()
    app.state.audit_manager = _Noop()
    yield smm, tmm
    for attr in (
        "semantic_models_manager", "term_mapping_manager",
        "ontology_schema_manager", "audit_manager",
    ):
        if hasattr(app.state, attr):
            delattr(app.state, attr)


def test_authored_glossary_is_a_selectable_mapping_context(client: TestClient, managers, db_session):
    smm, tmm = managers
    # Author a glossary scheme + a concept via the SAME API the Explore/Define
    # page uses (NOT an uploaded semantic_models row).
    r = client.post("/api/knowledge/collections", json={
        "label": f"E2E Author {uuid.uuid4().hex[:6]}", "collection_type": "glossary",
        "scope_level": "enterprise", "description": "authored on Explore",
    })
    assert r.status_code == 200, r.text
    coll_iri = r.json()["iri"]
    r = client.post("/api/knowledge/concepts", json={
        "collection_iri": coll_iri, "label": "Customer", "definition": "a party we do business with",
    })
    assert r.status_code == 200, r.text

    # Manager-level: the authored glossary context is selectable.
    contexts = tmm.list_selectable_contexts()
    by_ctx = {c["context"]: c for c in contexts}
    assert coll_iri in by_ctx, f"authored glossary {coll_iri} not selectable; got {list(by_ctx)}"
    assert by_ctx[coll_iri]["concept_count"] >= 1
    assert by_ctx[coll_iri]["label"]  # friendly label, not empty

    # Route-level: the dialog's endpoint returns it too.
    resp = client.get("/api/term-mappings/contexts")
    assert resp.status_code == 200, resp.text
    route_ctxs = {c["context"] for c in resp.json()}
    assert coll_iri in route_ctxs

    # And the internal indexes are NOT offered (would be noise).
    assert "urn:meta:sources" not in route_ctxs
    assert "urn:semantic-links" not in route_ctxs
