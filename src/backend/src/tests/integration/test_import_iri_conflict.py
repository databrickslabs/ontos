"""Integration test for the cross-scheme IRI-conflict import guard.

An IRI denotes ONE concept globally (the concept_version table keys is_current
per IRI across all schemes). Importing the SAME subject IRI into a SECOND
collection would fork one concept identity into two contexts with potentially
divergent status. The import guard refuses that at import time with a clear,
RDF-literate message. Re-uploading INTO THE SAME collection is legitimate
(versioning) and must NOT be blocked, and two DIFFERENT IRIs that happen to
share a local name must NOT collide.

Fixture style mirrors test_knowledge_routes.py / test_import_source_filename.py.
"""
import uuid
from pathlib import Path
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient
from rdflib import Graph
from sqlalchemy.orm import Session

from src.app import app
from src.controller.semantic_models_manager import SemanticModelsManager
from src.common.app_state import set_app_state_manager


# ---------------------------------------------------------------------------
# Fixtures (copied from test_import_source_filename.py)
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

_CUSTOMER_TTL = """@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ex: <http://example.org/onto/> .

ex:Customer a owl:Class ; rdfs:label "Customer" .
"""

# Same IRI as above, but a modified label (a legitimate re-upload / new version).
_CUSTOMER_TTL_V2 = """@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ex: <http://example.org/onto/> .

ex:Customer a owl:Class ; rdfs:label "Customer (revised)" .
"""

# Different namespace, same local name — a distinct IRI, no conflict.
_CUSTOMER_TTL_OTHER_NS = """@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ex2: <http://example.org/other/> .

ex2:Customer a owl:Class ; rdfs:label "Customer" .
"""

_CUSTOMER_IRI = "http://example.org/onto/Customer"
_CUSTOMER_IRI_OTHER = "http://example.org/other/Customer"


def _import(client: TestClient, collection_iri: str, ttl: str, filename: str):
    return client.post(
        f"/api/knowledge/collections/{quote(collection_iri, safe='')}/import",
        files={"file": (filename, ttl, "text/turtle")},
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestImportIriConflict:
    def test_same_iri_into_second_scheme_is_blocked(
        self, client: TestClient, make_collection
    ):
        coll_a = make_collection("Scheme A")
        coll_b = make_collection("Scheme B")

        # First import into A succeeds.
        r_a = _import(client, coll_a["iri"], _CUSTOMER_TTL, "a.ttl")
        assert r_a.status_code == 200, r_a.text
        assert r_a.json().get("mode") == "imported"

        # Same IRI into B (a first import for B, so import_rdf_to_collection path)
        # must be refused as a cross-scheme fork.
        r_b = _import(client, coll_b["iri"], _CUSTOMER_TTL, "b.ttl")
        assert r_b.status_code == 400, r_b.text
        assert "another scheme" in r_b.json()["detail"].lower()
        assert _CUSTOMER_IRI in r_b.json()["detail"]

        # B must NOT have received the concept.
        assert not client.get(
            "/api/knowledge/concepts/by-iri", params={"iri": _CUSTOMER_IRI}
        ).json().get("collection_iri") == coll_b["iri"]

    def test_same_scheme_reupload_not_blocked(
        self, client: TestClient, make_collection, semantic_models_manager
    ):
        coll_a = make_collection("Scheme A ReUpload")

        r1 = _import(client, coll_a["iri"], _CUSTOMER_TTL, "a.ttl")
        assert r1.status_code == 200, r1.text

        # Re-upload a modified version of the SAME file into A: this goes through
        # the diff/preview path and must NOT be blocked as a cross-scheme fork.
        r2 = _import(client, coll_a["iri"], _CUSTOMER_TTL_V2, "a.ttl")
        assert r2.status_code == 200, r2.text
        assert r2.json().get("mode") == "preview", r2.text

        # Helper-level assertion: only-in-A matches are not conflicts.
        g = Graph()
        g.parse(data=_CUSTOMER_TTL_V2, format="turtle")
        assert semantic_models_manager._detect_cross_scheme_iri_conflicts(
            g, target_context=coll_a["iri"]
        ) == []

    def test_distinct_iris_same_local_name_do_not_collide(
        self, client: TestClient, make_collection
    ):
        coll_a = make_collection("Distinct A")
        coll_b = make_collection("Distinct B")

        r_a = _import(client, coll_a["iri"], _CUSTOMER_TTL, "a.ttl")
        assert r_a.status_code == 200, r_a.text

        # Different namespace (ex2:) same local name into B — distinct IRI, so no
        # conflict; import succeeds.
        r_b = _import(client, coll_b["iri"], _CUSTOMER_TTL_OTHER_NS, "b.ttl")
        assert r_b.status_code == 200, r_b.text
        assert r_b.json().get("mode") == "imported", r_b.text
