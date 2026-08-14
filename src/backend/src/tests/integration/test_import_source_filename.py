"""Integration test for import source-filename provenance.

When a .ttl/.rdf file is imported into a concept collection, each imported
concept must record the ORIGIN FILENAME (via an ``ontos:sourceFile`` provenance
triple) so the concept read model / detail UI can show "Imported from
<filename>" instead of only the scheme label.

Fixture style mirrors test_knowledge_routes.py: a per-test
SemanticModelsManager is published on app.state so route dependencies resolve,
and a `make_collection` factory creates fresh, uniquely-named collections.
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
# Fixtures (copied from test_knowledge_routes.py)
# ---------------------------------------------------------------------------


@pytest.fixture
def semantic_models_manager(db_session: Session, tmp_path: Path):
    """Build a SemanticModelsManager backed by the test session + tmp data dir."""
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
    """Factory that creates a fresh, uniquely-named collection and returns it."""

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
# Test
# ---------------------------------------------------------------------------


_SAMPLE_TURTLE = """@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix ex: <http://example.org/onto/> .

ex:Customer a skos:Concept ; skos:prefLabel "Customer" .
"""


class TestImportSourceFilename:
    def test_first_import_records_source_filename(
        self, client: TestClient, make_collection
    ):
        # Empty editable collection.
        coll = make_collection("Source Filename")
        collection_iri = coll["iri"]

        # POST a turtle file with a known filename into the import endpoint.
        filename = "my_ontology_v2.ttl"
        r = client.post(
            f"/api/knowledge/collections/{quote(collection_iri, safe='')}/import",
            files={"file": (filename, _SAMPLE_TURTLE, "text/turtle")},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("mode") == "imported", body

        # Fetch the imported concept and assert the origin filename is surfaced.
        iri = "http://example.org/onto/Customer"
        detail = client.get(
            "/api/knowledge/concepts/by-iri", params={"iri": iri}
        )
        assert detail.status_code == 200, detail.text
        concept = detail.json()
        assert concept.get("source_file") == filename, (
            f"Imported concept should record source_file={filename!r}, "
            f"got {concept.get('source_file')!r}"
        )
