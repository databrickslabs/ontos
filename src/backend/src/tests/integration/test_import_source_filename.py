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

    def test_reupload_refreshes_source_filename_on_modified_concept(
        self, client: TestClient, semantic_models_manager, make_collection
    ):
        """C2 regression: re-uploading a MODIFIED concept from a NEW file must
        adopt the new filename, not keep the stale one copied into v2.

        publish_concept_version copies the demoted version's triples (incl. the
        OLD ontos:sourceFile) into the new version; the fix threads source_file
        through _extract_changes + _PUBLISH_LITERAL_FIELDS so the new version's
        provenance is rewritten. Without the fix the concept keeps v1.ttl.
        """
        coll = make_collection("Source Filename Reupload", collection_type="ontology")
        collection_iri = coll["iri"]
        iri = "http://example.org/onto/Customer"

        # First import from v1.ttl.
        r1 = client.post(
            f"/api/knowledge/collections/{quote(collection_iri, safe='')}/import",
            files={"file": ("customers_v1.ttl", _SAMPLE_TURTLE, "text/turtle")},
        )
        assert r1.status_code == 200, r1.text
        assert r1.json().get("mode") == "imported"

        # Re-upload from v2.ttl with a CHANGED definition (so the concept lands
        # in the MODIFIED bucket -> publish_concept_version path). Re-upload into
        # a non-empty scheme returns a preview token that must be confirmed.
        modified_ttl = (
            "@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n"
            "@prefix ex: <http://example.org/onto/> .\n\n"
            'ex:Customer a skos:Concept ; skos:prefLabel "Customer" ; '
            'skos:definition "A buyer of goods (revised)." .\n'
        )
        r2 = client.post(
            f"/api/knowledge/collections/{quote(collection_iri, safe='')}/import",
            files={"file": ("customers_v2.ttl", modified_ttl, "text/turtle")},
        )
        assert r2.status_code == 200, r2.text
        body2 = r2.json()
        assert body2.get("mode") == "preview", body2
        token = body2["preview_token"]

        # Confirm the re-upload (applies the versioning event -> Customer v2).
        c = client.post(
            f"/api/semantic-models/uploads/preview/{quote(token, safe='')}/confirm",
        )
        assert c.status_code == 200, c.text

        # The modified concept's provenance must now be the NEW filename.
        detail = client.get("/api/knowledge/concepts/by-iri", params={"iri": iri})
        assert detail.status_code == 200, detail.text
        got = detail.json().get("source_file")
        assert got == "customers_v2.ttl", (
            f"Re-uploaded modified concept should refresh source_file to "
            f"'customers_v2.ttl', got {got!r} (stale provenance = C2 regression)"
        )
