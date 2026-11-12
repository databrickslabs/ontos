"""Coverage metrics (GET /api/knowledge/coverage) must count only user-authored
schemes. Built-in system sources (bundled ontologies/taxonomies shipped with the
app) were inflating the Enrich "Not yet linked" total. The exclusion reuses
``SemanticModelsManager.get_system_source_names`` (same rule as the Explore
``include_system`` filter).
"""
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from src.app import app
from src.controller.semantic_models_manager import SemanticModelsManager
from src.common.app_state import set_app_state_manager


_BUNDLED_TTL = """@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ex: <http://example.org/bundled#> .

ex:BuiltInThing a owl:Class ; rdfs:label "Built In Thing" .
ex:OtherBuiltInThing a owl:Class ; rdfs:label "Other Built In Thing" .
"""


@pytest.fixture
def smm_with_bundled(db_session: Session, tmp_path: Path):
    """Manager whose data dir ships one bundled taxonomy (a 'system' source)."""
    data_dir = tmp_path / "sm_data_coverage"
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


def test_coverage_counts_user_scheme_and_excludes_system_source(
    client: TestClient, smm_with_bundled
):
    r = client.post("/api/knowledge/collections", json={
        "label": f"Cov {uuid.uuid4().hex[:6]}", "collection_type": "glossary",
        "scope_level": "enterprise", "description": "user scheme next to a bundled one",
    })
    assert r.status_code == 200, r.text
    coll = r.json()["iri"]
    user_bucket = coll.split(":")[-1]
    r = client.post("/api/knowledge/concepts", json={
        "collection_iri": coll, "label": "User Concept", "definition": "authored by a user",
    })
    assert r.status_code == 200, r.text

    # Sanity: the bundled source really is present in the grouped concepts
    # (so the exclusion below is meaningful) and identified as system.
    smm_with_bundled._invalidate_cache()
    assert "bundled-test-ontology" in smm_with_bundled.get_grouped_concepts()
    assert "bundled-test-ontology" in smm_with_bundled.get_system_source_names()

    resp = client.get("/api/knowledge/coverage")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # Response shape unchanged.
    assert set(body.keys()) == {"schemes", "totals"}

    rows = {row["scheme"]: row for row in body["schemes"]}
    assert "bundled-test-ontology" not in rows, list(rows)
    assert user_bucket in rows, list(rows)
    assert rows[user_bucket]["concepts"] == 1

    # Totals only aggregate non-system schemes.
    assert body["totals"]["concepts"] == sum(r["concepts"] for r in body["schemes"])
    system_labels = {"Built In Thing", "Other Built In Thing"}
    grouped = smm_with_bundled.get_grouped_concepts()
    system_count = sum(
        1 for c in grouped.get("bundled-test-ontology", []) if c.label in system_labels
    )
    assert system_count == 2
    all_count = sum(len(v) for v in grouped.values())
    assert body["totals"]["concepts"] == all_count - len(grouped["bundled-test-ontology"])
