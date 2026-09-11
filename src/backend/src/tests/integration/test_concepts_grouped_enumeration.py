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
