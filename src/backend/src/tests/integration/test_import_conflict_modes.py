"""Integration test for cross-scheme IRI-conflict import MODES (F5).

An IRI denotes ONE concept globally. A cross-scheme conflict (the same subject
IRI asserted into a SECOND scheme) is no longer a dead-end: ``conflict_mode``
turns it into a choice.

  - 'block'  (DEFAULT): raise as today (the old test_import_iri_conflict guard).
  - 'skip'   : import only the non-conflicting subjects into the target; leave
               the conflicting IRIs owned by their existing scheme, untouched.
  - 'update' : do NOT fork the conflicting IRI into the target; apply the file's
               values to the concept in its EXISTING (home) scheme as a versioned
               update (publish_concept_version).

A detection endpoint lets the UI PRE-CHECK before importing.

Fixture style mirrors test_import_iri_conflict.py.
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


# ---------------------------------------------------------------------------
# Fixtures (copied from test_import_iri_conflict.py)
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
    def _make(label_prefix: str = "Test Coll", collection_type: str = "glossary",
              description: str = "made by test"):
        label = f"{label_prefix} {uuid.uuid4().hex[:8]}"
        payload = {
            "label": label,
            "collection_type": collection_type,
            "scope_level": "enterprise",
            "description": description,
        }
        r = client.post("/api/knowledge/collections", json=payload)
        assert r.status_code == 200, r.text
        return r.json()

    return _make


# ---------------------------------------------------------------------------
# Sample turtle documents
# ---------------------------------------------------------------------------

_CUSTOMER_IRI = "http://example.org/onto/Customer"
_PROSPECT_IRI = "http://example.org/onto/Prospect"

# ex:Customer with an ORIGINAL definition (goes into scheme A).
_CUSTOMER_TTL_OLD = """@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ex: <http://example.org/onto/> .

ex:Customer a owl:Class ; rdfs:label "Customer" ; rdfs:comment "old" .
"""

# Same IRI + a NEW definition (the conflicting re-upload targeting scheme B).
_CUSTOMER_TTL_NEW = """@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ex: <http://example.org/onto/> .

ex:Customer a owl:Class ; rdfs:label "Customer" ; rdfs:comment "new" .
"""

# A conflicting ex:Customer PLUS a brand-new ex:Prospect (for the skip case).
_CUSTOMER_PLUS_PROSPECT_TTL = """@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ex: <http://example.org/onto/> .

ex:Customer a owl:Class ; rdfs:label "Customer" ; rdfs:comment "new" .
ex:Prospect a owl:Class ; rdfs:label "Prospect" ; rdfs:comment "a lead" .
"""


def _import(client: TestClient, collection_iri: str, ttl: str, filename: str,
            conflict_mode: str = None):
    url = f"/api/knowledge/collections/{quote(collection_iri, safe='')}/import"
    if conflict_mode:
        url += f"?conflict_mode={conflict_mode}"
    return client.post(url, files={"file": (filename, ttl, "text/turtle")})


def _detect(client: TestClient, collection_iri: str, ttl: str, filename: str):
    url = f"/api/knowledge/collections/{quote(collection_iri, safe='')}/import/conflicts"
    return client.post(url, files={"file": (filename, ttl, "text/turtle")})


def _concept_by_iri(client: TestClient, iri: str) -> dict:
    return client.get("/api/knowledge/concepts/by-iri", params={"iri": iri}).json()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestImportConflictModes:
    def test_detect_endpoint_reports_cross_scheme_conflict(
        self, client: TestClient, make_collection
    ):
        coll_a = make_collection("Scheme A Detect")
        coll_b = make_collection("Scheme B Detect")

        r_a = _import(client, coll_a["iri"], _CUSTOMER_TTL_OLD, "a.ttl")
        assert r_a.status_code == 200, r_a.text

        r = _detect(client, coll_b["iri"], _CUSTOMER_TTL_NEW, "b.ttl")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["count"] == 1, body
        conflict = body["conflicts"][0]
        assert conflict["iri"] == _CUSTOMER_IRI
        assert conflict["existing_context"] == coll_a["iri"]

    def test_block_is_default_and_refuses(
        self, client: TestClient, make_collection
    ):
        coll_a = make_collection("Scheme A Block")
        coll_b = make_collection("Scheme B Block")

        assert _import(client, coll_a["iri"], _CUSTOMER_TTL_OLD, "a.ttl").status_code == 200

        # No mode -> block (today's behavior) -> 400, B unchanged.
        r_b = _import(client, coll_b["iri"], _CUSTOMER_TTL_NEW, "b.ttl")
        assert r_b.status_code == 400, r_b.text
        assert "another scheme" in r_b.json()["detail"].lower()

        assert _concept_by_iri(client, _CUSTOMER_IRI).get("source_context") == coll_a["iri"]

    def test_skip_imports_only_non_conflicting(
        self, client: TestClient, make_collection
    ):
        coll_a = make_collection("Scheme A Skip")
        coll_b = make_collection("Scheme B Skip")

        assert _import(client, coll_a["iri"], _CUSTOMER_TTL_OLD, "a.ttl").status_code == 200

        # skip: ex:Customer (conflict) dropped, ex:Prospect (new) imported into B.
        r_b = _import(
            client, coll_b["iri"], _CUSTOMER_PLUS_PROSPECT_TTL, "b.ttl",
            conflict_mode="skip",
        )
        assert r_b.status_code == 200, r_b.text
        assert r_b.json().get("mode") == "imported", r_b.text

        # Prospect landed in B.
        assert _concept_by_iri(client, _PROSPECT_IRI).get("source_context") == coll_b["iri"]
        # Customer still lives in A only, definition unchanged.
        cust = _concept_by_iri(client, _CUSTOMER_IRI)
        assert cust.get("source_context") == coll_a["iri"]
        assert cust.get("comment") == "old"

    def test_update_versions_concept_in_existing_scheme(
        self, client: TestClient, make_collection
    ):
        coll_a = make_collection("Scheme A Update")
        coll_b = make_collection("Scheme B Update")

        assert _import(client, coll_a["iri"], _CUSTOMER_TTL_OLD, "a.ttl").status_code == 200
        assert _concept_by_iri(client, _CUSTOMER_IRI).get("comment") == "old"

        # update: ex:Customer NOT forked into B; instead versioned in A with 'new'.
        r_b = _import(
            client, coll_b["iri"], _CUSTOMER_TTL_NEW, "b.ttl",
            conflict_mode="update",
        )
        assert r_b.status_code == 200, r_b.text

        cust = _concept_by_iri(client, _CUSTOMER_IRI)
        assert cust.get("source_context") == coll_a["iri"]
        assert cust.get("comment") == "new", cust
