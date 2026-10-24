"""Regression: concepts-grouped must list EVERY concept in a scheme, including
ones that have been versioned (published to v2).

Live bug (cbv2b, 2026-08-14): a scheme with 4 concepts (one published to v2)
showed only 1-2 in Explore. Root cause was NOT data loss — every concept was
present in the store and reachable by-iri + via a UNION-graph SPARQL query — but
``_compute_all_concepts`` enumerated PER-CONTEXT via ``context.query(...)``, and
rdflib's per-context query over a ConjunctiveGraph member graph silently dropped
rows for the UNION/OPTIONAL/BIND pattern. Switched enumeration to direct
``context.subjects(RDF.type, ...)`` triple-pattern lookups.

This test reproduces the scenario through the real routes + manager and asserts
the grouped listing (what Explore renders) returns all concepts.
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


@pytest.fixture
def smm(db_session: Session, tmp_path: Path):
    data_dir = tmp_path / "sm_data"
    (data_dir / "cache").mkdir(parents=True, exist_ok=True)
    (data_dir / "taxonomies").mkdir(parents=True, exist_ok=True)
    m = SemanticModelsManager(db=db_session, data_dir=data_dir)
    app.state.semantic_models_manager = m
    set_app_state_manager("semantic_models_manager", m)

    class _Noop:
        def sync_asset_types(self, *a, **k):
            return {"created": 0, "updated": 0}

        def log_action(self, *a, **k):
            return None

        def log_event(self, *a, **k):
            return None

    app.state.ontology_schema_manager = _Noop()
    app.state.audit_manager = _Noop()
    yield m
    for attr in ("semantic_models_manager", "ontology_schema_manager", "audit_manager"):
        if hasattr(app.state, attr):
            delattr(app.state, attr)


def _make_concept(client, coll_iri, label, definition):
    r = client.post("/api/knowledge/concepts", json={
        "collection_iri": coll_iri, "label": label, "definition": definition,
    })
    assert r.status_code == 200, r.text
    b = r.json()
    return b.get("iri") or (b.get("concept") or {}).get("iri")


def test_grouped_lists_all_concepts_including_versioned(client: TestClient, smm, db_session):
    r = client.post("/api/knowledge/collections", json={
        "label": f"Enum {uuid.uuid4().hex[:6]}", "collection_type": "glossary",
        "scope_level": "enterprise", "description": "enumeration regression",
    })
    coll = r.json()["iri"]
    from src.controller.semantic_models_manager import _sanitize_context_name
    suffix = coll.split(":")[-1]  # source bucket key used by get_grouped_concepts

    # Three concepts; publish the first to v2 (the versioned case that vanished).
    iri_a = _make_concept(client, coll, "Customer", "a party we sell to")
    iri_b = _make_concept(client, coll, "Prospect", "a potential customer")
    iri_c = _make_concept(client, coll, "Active Customer", "a currently-active customer")

    r = client.post("/api/semantic-models/concepts/version/publish",
                    json={"iri": iri_a, "changes": {"definition": "a party that has purchased"}})
    assert r.status_code == 200 and r.json().get("new_version") == 2, r.text

    # Force a fresh recompute from the graph (mirrors the cold 'computing live' path).
    smm._invalidate_cache()

    grouped = smm.get_grouped_concepts()
    bucket = grouped.get(suffix, [])
    labels = sorted(c.label for c in bucket)
    assert labels == ["Active Customer", "Customer", "Prospect"], (
        f"grouped listing dropped concepts: got {labels} for bucket {suffix!r}; "
        f"all buckets={ {k: [c.label for c in v] for k,v in grouped.items() if suffix in k} }"
    )

    # And via the actual route the UI calls.
    resp = client.get("/api/semantic-models/concepts-grouped")
    assert resp.status_code == 200, resp.text
    gc = resp.json().get("grouped_concepts", {})
    route_labels = sorted(c.get("label") for c in gc.get(suffix, []))
    assert route_labels == ["Active Customer", "Customer", "Prospect"], route_labels


_BUNDLED_TTL = """@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ex: <http://example.org/bundled#> .

ex:BuiltInThing a owl:Class ; rdfs:label "Built In Thing" .
ex:builtInProp a owl:DatatypeProperty ; rdfs:label "built in prop" .
"""


@pytest.fixture
def smm_with_bundled(db_session: Session, tmp_path: Path):
    """Manager whose data dir ships one bundled taxonomy (a 'system' source)."""
    data_dir = tmp_path / "sm_data_bundled"
    (data_dir / "cache").mkdir(parents=True, exist_ok=True)
    (data_dir / "taxonomies").mkdir(parents=True, exist_ok=True)
    (data_dir / "taxonomies" / "bundled-test-ontology.ttl").write_text(_BUNDLED_TTL)
    m = SemanticModelsManager(db=db_session, data_dir=data_dir)
    app.state.semantic_models_manager = m
    set_app_state_manager("semantic_models_manager", m)

    class _Noop:
        def sync_asset_types(self, *a, **k):
            return {"created": 0, "updated": 0}

        def log_action(self, *a, **k):
            return None

        def log_event(self, *a, **k):
            return None

    app.state.ontology_schema_manager = _Noop()
    app.state.audit_manager = _Noop()
    yield m
    for attr in ("semantic_models_manager", "ontology_schema_manager", "audit_manager"):
        if hasattr(app.state, attr):
            delattr(app.state, attr)


def test_grouped_excludes_system_sources_unless_requested(client: TestClient, smm_with_bundled):
    r = client.post("/api/knowledge/collections", json={
        "label": f"User {uuid.uuid4().hex[:6]}", "collection_type": "taxonomy",
        "scope_level": "enterprise", "description": "user scheme next to a bundled one",
    })
    assert r.status_code == 200, r.text
    coll = r.json()["iri"]
    user_bucket = coll.split(":")[-1]
    _make_concept(client, coll, "User Concept", "authored by a user")

    assert "bundled-test-ontology" in smm_with_bundled.get_system_source_names()
    # A user taxonomy shares the urn:taxonomy: prefix but is NOT system.
    assert user_bucket not in smm_with_bundled.get_system_source_names()

    # Default: bundled source hidden, user source kept.
    resp = client.get("/api/semantic-models/concepts-grouped")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    gc = body["grouped_concepts"]
    assert "bundled-test-ontology" not in gc, list(gc.keys())
    assert [c["label"] for c in gc.get(user_bucket, [])] == ["User Concept"]
    assert "bundled-test-ontology" in body["system_sources"]

    # Opt in: bundled source included.
    gc_all = client.get(
        "/api/semantic-models/concepts-grouped", params={"include_system": "true"}
    ).json()["grouped_concepts"]
    assert "Built In Thing" in [c["label"] for c in gc_all.get("bundled-test-ontology", [])]
    assert user_bucket in gc_all

    # Properties follow the same rule.
    props = client.get("/api/semantic-models/properties-grouped").json()["grouped_properties"]
    assert "bundled-test-ontology" not in props
    props_all = client.get(
        "/api/semantic-models/properties-grouped", params={"include_system": "true"}
    ).json()["grouped_properties"]
    assert "bundled-test-ontology" in props_all
