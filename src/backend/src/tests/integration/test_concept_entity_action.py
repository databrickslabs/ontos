"""ACCEPTANCE gate for wiring the workflow ENTITY_ACTION executor to concept
curation (Phase 1: vocabulary + act-on-concept, NO trigger firing).

Covers:
  1. The workflow ``EntityType`` enum knows the three concept entity types.
  2. ``EntityActionStepHandler`` publishes a new concept version via the
     SemanticModelsManager singleton (concepts are RDF triples keyed by IRI,
     not repo rows).
  3. ``EntityActionStepHandler`` drives a concept status transition
     (draft -> under_review) via the same singleton.
"""
import uuid
from pathlib import Path
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from src.app import app
from src.controller.semantic_models_manager import SemanticModelsManager
from src.common.app_state import set_app_state_manager
from src.common.workflow_executor import EntityActionStepHandler, StepContext


@pytest.fixture
def semantic_models_manager(db_session: Session, tmp_path: Path):
    data_dir = tmp_path / "sm_data"
    (data_dir / "cache").mkdir(parents=True, exist_ok=True)
    (data_dir / "taxonomies").mkdir(parents=True, exist_ok=True)
    manager = SemanticModelsManager(db=db_session, data_dir=data_dir)
    app.state.semantic_models_manager = manager
    set_app_state_manager("semantic_models_manager", manager)

    class _Noop:
        def sync_asset_types(self, *a, **k):
            return {"created": 0, "updated": 0}

        def log_action(self, *a, **k):
            return None

        def log_event(self, *a, **k):
            return None

    app.state.ontology_schema_manager = _Noop()
    app.state.audit_manager = _Noop()
    yield manager
    for attr in ("semantic_models_manager", "ontology_schema_manager", "audit_manager"):
        if hasattr(app.state, attr):
            delattr(app.state, attr)


@pytest.fixture
def make_collection(client: TestClient, semantic_models_manager):
    def _make(prefix="ConcAct"):
        r = client.post("/api/knowledge/collections", json={
            "label": f"{prefix} {uuid.uuid4().hex[:8]}", "collection_type": "glossary",
            "scope_level": "enterprise", "description": "concept entity_action test",
        })
        assert r.status_code == 200, r.text
        return r.json()

    return _make


def _make_concept(client, coll_iri, label, definition):
    r = client.post("/api/knowledge/concepts", json={
        "collection_iri": coll_iri, "label": label, "definition": definition,
    })
    assert r.status_code == 200, r.text
    b = r.json()
    return b.get("iri") or (b.get("concept") or {}).get("iri")


def _ctx(iri, entity):
    """Build a minimal StepContext for a concept entity_action step."""
    return StepContext(
        entity=entity,
        entity_type='ontology_concept',
        entity_id=iri,
        entity_name='test concept',
        user_email='tester@example.com',
        trigger_context=None,
        execution_id='exec-' + uuid.uuid4().hex[:8],
        workflow_id='wf-' + uuid.uuid4().hex[:8],
        workflow_name='concept-action-test',
        step_results={},
    )


def test_entity_type_enum_has_concept_members():
    from src.models.process_workflows import EntityType
    assert EntityType('ontology_concept') is EntityType.ONTOLOGY_CONCEPT
    assert EntityType('ontology_collection') is EntityType.ONTOLOGY_COLLECTION
    assert EntityType('concept_changeset') is EntityType.CONCEPT_CHANGESET


def test_publish_version_action(client, make_collection, semantic_models_manager, db_session):
    coll = make_collection()
    iri = _make_concept(client, coll["iri"], "Customer", "v1 def")
    q = quote(iri, safe="")

    handler = EntityActionStepHandler(db=db_session, config={'action': 'publish_version'})
    ctx = _ctx(iri, {'changes': {'definition': 'v2 def'}})
    result = handler.execute(ctx)

    assert result.passed is True, result.error

    info = client.get(f"/api/semantic-models/concepts/version?iri={q}").json()
    assert info.get("current_version") == 2, info

    # Authoritative: the served graph carries exactly the published definition
    # (get_concept maps SKOS.definition onto the 'comment' field).
    from rdflib import URIRef
    from rdflib.namespace import SKOS
    defs = [str(o) for o in semantic_models_manager._graph.objects(URIRef(iri), SKOS.definition)]
    assert defs == ["v2 def"], defs
    assert semantic_models_manager.get_concept(iri).get("comment") == "v2 def"


def test_set_status_action(client, make_collection, semantic_models_manager, db_session):
    coll = make_collection()
    iri = _make_concept(client, coll["iri"], "Revenue", "money in")

    handler = EntityActionStepHandler(
        db=db_session, config={'action': 'set_status', 'target_status': 'under_review'}
    )
    result = handler.execute(_ctx(iri, {}))

    assert result.passed is True, result.error
    assert semantic_models_manager.get_concept(iri).get("status") == "under_review"
