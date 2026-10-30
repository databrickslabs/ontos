"""PROBE: does the ownership re-stamp in update_concept_status destroy the
frozen snapshot of a prior version when you deprecate AFTER publishing?

publish v1->v2 freezes v1's rows (owned by v1.id, is_current=false). deprecate
goes through update_concept_status, which now re-stamps ALL subject rows in the
context to the CURRENT version. If that re-stamp is not scoped away from the
frozen prior-version rows, it moves v1's snapshot onto v2 and 'version 1' loses
its old definition.
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


def test_snapshot_survives_deprecate_after_publish(client: TestClient, smm, db_session):
    r = client.post("/api/knowledge/collections", json={
        "label": f"Snap {uuid.uuid4().hex[:6]}", "collection_type": "glossary",
        "scope_level": "enterprise", "description": "x",
    })
    coll = r.json()["iri"]
    r = client.post("/api/knowledge/concepts", json={
        "collection_iri": coll, "label": "Customer", "definition": "ORIGINAL v1 def",
    })
    iri = r.json().get("iri") or r.json().get("concept", {}).get("iri")
    q = quote(iri, safe="")

    # publish -> v2, freezing v1's "ORIGINAL v1 def"
    r = client.post("/api/semantic-models/concepts/version/publish",
                    json={"iri": iri, "changes": {"definition": "v2 def"}})
    assert r.status_code == 200 and r.json()["new_version"] == 2, r.text

    # v1 snapshot BEFORE the status walk
    d1 = client.get(f"/api/semantic-models/concepts/version/detail?iri={q}&version=1")
    assert d1.status_code == 200, d1.text
    before = d1.json()

    # Status walk AFTER the version publish (each hop goes through
    # update_concept_status, which re-stamps ALL context rows to current=v2).
    assert client.post(f"/api/knowledge/concepts/by-iri/submit-review?iri={q}", json={}).status_code == 200
    assert client.post(f"/api/knowledge/concepts/by-iri/approve?iri={q}").status_code == 200
    r = client.post(f"/api/knowledge/concepts/by-iri/publish?iri={q}")
    assert r.status_code == 200, r.text

    # v1 snapshot AFTER deprecate — MUST be unchanged (still ORIGINAL v1 def)
    d1b = client.get(f"/api/semantic-models/concepts/version/detail?iri={q}&version=1")
    assert d1b.status_code == 200, d1b.text
    after = d1b.json()
    # dump for visibility
    print("V1 BEFORE:", before)
    print("V1 AFTER :", after)
    # the old definition text must survive on version 1
    import json
    assert "ORIGINAL v1 def" in json.dumps(after), (
        f"v1 snapshot was clobbered by deprecate re-stamp: {after}"
    )
