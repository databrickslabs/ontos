"""Integration test for the additive multi-file merge import contract.

Merging several files into ONE concept scheme must be ADDITIVE: every file's
concepts land as Draft and NOTHING is deprecated. Before the fix, files 2..N hit
a non-empty scheme and went through the re-upload diff/version path, which diffed
the incoming file against the WHOLE scheme and deprecated every concept not in
that file — dropping the earlier files' concepts.

The fix adds an ``additive=true`` query param to
``POST /knowledge/collections/{iri}/import`` that skips the diff/preview branch
and appends the file's concepts as new Draft concepts even into a non-empty
scheme. This test asserts that importing a 2nd DIFFERENT file with additive=true
leaves the FIRST file's concept as ``draft`` (NOT deprecated) and adds the 2nd as
``draft``.

Fixture style mirrors test_import_source_filename.py.
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

    def _make(label_prefix: str = "Test Coll", collection_type: str = "ontology",
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


# Two files carrying DIFFERENT concepts (the sales/billing merge scenario).
_FILE_ONE = """@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix ex: <http://example.org/onto/> .

ex:Customer a skos:Concept ; skos:prefLabel "Customer" .
"""

_FILE_TWO = """@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix ex: <http://example.org/onto/> .

ex:Invoice a skos:Concept ; skos:prefLabel "Invoice" .
"""


class TestImportAdditiveMerge:
    def test_additive_second_file_keeps_first_files_concept_as_draft(
        self, client: TestClient, make_collection
    ):
        coll = make_collection("Additive Merge")
        collection_iri = coll["iri"]
        import_url = (
            f"/api/knowledge/collections/{quote(collection_iri, safe='')}/import"
        )

        customer_iri = "http://example.org/onto/Customer"
        invoice_iri = "http://example.org/onto/Invoice"

        # File 1 into the empty scheme: plain draft import.
        r1 = client.post(
            import_url,
            files={"file": ("sales.ttl", _FILE_ONE, "text/turtle")},
        )
        assert r1.status_code == 200, r1.text
        assert r1.json().get("mode") == "imported", r1.json()

        # File 2 (a DIFFERENT concept) into the now NON-EMPTY scheme WITH
        # additive=true. Must be a plain draft append (mode 'imported'), NOT a
        # diff/preview that would deprecate the Customer concept.
        r2 = client.post(
            f"{import_url}?additive=true",
            files={"file": ("billing.ttl", _FILE_TWO, "text/turtle")},
        )
        assert r2.status_code == 200, r2.text
        body2 = r2.json()
        assert body2.get("mode") == "imported", (
            f"additive=true must bypass the diff/preview path, got {body2}"
        )

        # The FIRST file's concept must survive additively as draft — NOT
        # deprecated (the bug left sales/billing concepts deprecated).
        c1 = client.get("/api/knowledge/concepts/by-iri", params={"iri": customer_iri})
        assert c1.status_code == 200, c1.text
        status1 = c1.json().get("status")
        assert status1 == "draft", (
            f"First file's concept must remain draft after an additive merge, "
            f"got status={status1!r}"
        )

        # The SECOND file's concept is also added as draft.
        c2 = client.get("/api/knowledge/concepts/by-iri", params={"iri": invoice_iri})
        assert c2.status_code == 200, c2.text
        status2 = c2.json().get("status")
        assert status2 == "draft", (
            f"Second file's concept should land as draft, got status={status2!r}"
        )

    def test_non_additive_reupload_still_diffs(
        self, client: TestClient, make_collection
    ):
        """Guard: WITHOUT additive, a second upload into a non-empty scheme keeps
        the re-upload diff/preview behavior (the genuine re-version case)."""
        coll = make_collection("Reupload Diff Preserved")
        collection_iri = coll["iri"]
        import_url = (
            f"/api/knowledge/collections/{quote(collection_iri, safe='')}/import"
        )

        r1 = client.post(
            import_url,
            files={"file": ("v1.ttl", _FILE_ONE, "text/turtle")},
        )
        assert r1.status_code == 200, r1.text
        assert r1.json().get("mode") == "imported"

        # No additive flag: a second upload must return a preview (diff path).
        r2 = client.post(
            import_url,
            files={"file": ("v2.ttl", _FILE_TWO, "text/turtle")},
        )
        assert r2.status_code == 200, r2.text
        assert r2.json().get("mode") == "preview", (
            f"non-additive re-upload into a non-empty scheme must diff/preview, "
            f"got {r2.json()}"
        )
