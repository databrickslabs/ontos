"""Gap-coverage tests for the concept-versioning engine.

Complements test_concept_versioning.py with the cases the E2E test plan
(`.claude/notes/ontos_versioning_e2e_test_plan.md`, "Gaps worth adding") flagged
as not yet covered programmatically:

- Row 3-F  — the served hot graph is built current-only: history triples exist in
             the store but NEVER enter the graph (read-isolation at the repo/build
             layer, not just via the concept-detail read).
- Row 18-P — Simple/Advanced contract invariant: every versioning read carries a
             human ``label`` so the Simple view never has to resolve a raw IRI.
- Row 11-N — negative import path: malformed RDF is rejected (400) and the target
             scheme's existing triples are left untouched (no partial apply).

Same local fixtures as test_concept_versioning.py (no shared integration conftest).
"""
import io
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
# Fixtures — mirror test_concept_versioning.py (per-file, no shared conftest).
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
    def _make(label_prefix: str = "Gap Coll", collection_type: str = "glossary",
              description: str = "made by gap test"):
        label = f"{label_prefix} {uuid.uuid4().hex[:8]}"
        r = client.post("/api/knowledge/collections", json={
            "label": label,
            "collection_type": collection_type,
            "scope_level": "enterprise",
            "description": description,
        })
        assert r.status_code == 200, r.text
        return r.json()

    return _make


def _make_concept(client: TestClient, collection_iri: str, label: str, definition: str) -> str:
    r = client.post("/api/knowledge/concepts", json={
        "collection_iri": collection_iri,
        "label": label,
        "definition": definition,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    iri = body.get("iri") or (body.get("concept") or {}).get("iri")
    assert iri, f"could not resolve created concept IRI from {body}"
    return iri


def _publish(client: TestClient, iri: str, definition: str) -> None:
    r = client.post("/api/semantic-models/concepts/version/publish", json={
        "iri": iri, "changes": {"definition": definition},
    })
    assert r.status_code == 200, r.text


# ---------------------------------------------------------------------------
# Row 3-F — served graph is current-only; history never enters it.
# ---------------------------------------------------------------------------


class TestServedGraphExcludesHistory:
    def test_list_current_drops_history_keeps_unowned(
        self, client: TestClient, make_collection, semantic_models_manager, db_session
    ):
        """After a publish, the repo's list_current (the ONLY reader that builds
        the served hot graph) must exclude the superseded version's triples while
        keeping unowned metadata triples. This is read-isolation at the build
        layer — the guarantee the whole 'reads carry no version predicate' rests
        on, tested independently of the concept-detail read path."""
        from src.repositories.rdf_triples_repository import rdf_triples_repo

        coll = make_collection("Gap GraphIso")
        iri = _make_concept(client, coll["iri"], "Churn", "v1 definition text")
        _publish(client, iri, "v2 definition text")

        current = rdf_triples_repo.list_current(db_session)
        current_objs = {str(t.object_value) for t in current}
        # The current definition is in the served set; the superseded one is not.
        assert "v2 definition text" in current_objs
        assert "v1 definition text" not in current_objs

        # Unowned metadata (the collection/scheme itself) still loads — the
        # LEFT JOIN keeps concept_version_id IS NULL rows.
        current_subjects = {str(t.subject_uri) for t in current}
        assert coll["iri"] in current_subjects, (
            "collection/scheme metadata (unowned triples) must still load into the graph"
        )

    def test_rebuilt_graph_has_no_history_triple(
        self, client: TestClient, make_collection, semantic_models_manager
    ):
        """Rebuild the in-memory graph from current-only and confirm the old
        definition literal is absent from the served graph entirely."""
        coll = make_collection("Gap GraphRebuild")
        iri = _make_concept(client, coll["iri"], "Margin", "old margin definition")
        _publish(client, iri, "new margin definition")

        semantic_models_manager.rebuild_graph_from_enabled()
        graph = semantic_models_manager._graph
        all_literals = {str(o) for _, _, o in graph}
        assert "new margin definition" in all_literals
        assert "old margin definition" not in all_literals, (
            "superseded (history) triple leaked into the served graph"
        )


# ---------------------------------------------------------------------------
# Row 18-P — Simple/Advanced contract: version reads always carry a label.
# ---------------------------------------------------------------------------


class TestSimpleViewLabelInvariant:
    def test_version_info_always_has_label(
        self, client: TestClient, make_collection
    ):
        """The Simple view must never resolve a raw IRI, so the version-info
        payload MUST carry a human `label` (and version rows exist)."""
        coll = make_collection("Gap Label")
        iri = _make_concept(client, coll["iri"], "Revenue", "money in")
        _publish(client, iri, "money in, recognized")

        r = client.get(
            f"/api/semantic-models/concepts/version?iri={quote(iri, safe='')}"
        )
        assert r.status_code == 200, r.text
        info = r.json()
        assert info.get("label"), f"version-info must carry a label, got {info!r}"
        assert info["label"] != iri, "label should be the human name, not the IRI"
        assert len(info.get("versions", [])) == 2

    def test_publish_response_has_label(self, client: TestClient, make_collection):
        """Publish response carries label + integer version (Advanced) — Simple
        view uses the label, hides the integer; the payload must supply both."""
        coll = make_collection("Gap PubLabel")
        iri = _make_concept(client, coll["iri"], "Cost Center", "a cost bucket")
        r = client.post("/api/semantic-models/concepts/version/publish", json={
            "iri": iri, "changes": {"definition": "a cost allocation bucket"},
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body.get("label"), f"publish response must carry a label: {body!r}"
        assert body.get("new_version") == 2


# ---------------------------------------------------------------------------
# Row 11-N — malformed import is rejected and leaves the store untouched.
# ---------------------------------------------------------------------------


class TestMalformedImportRejected:
    def test_bad_rdf_returns_400_and_leaves_store_intact(
        self, client: TestClient, make_collection
    ):
        """Uploading malformed RDF into a collection must fail with 400 and NOT
        partially apply — the collection's concept_count is unchanged."""
        coll = make_collection("Gap BadImport")
        # Seed one real concept so we can prove the store is untouched.
        _make_concept(client, coll["iri"], "Seed", "a seed concept")

        before = client.get(f"/api/knowledge/collections/{quote(coll['iri'], safe='')}")
        assert before.status_code == 200, before.text
        count_before = before.json().get("concept_count")

        # Undefined `ex:` prefix on a terminated statement — a hard parse error
        # that survives the truncated-turtle cleanup (mirrors versioning_invalid.ttl).
        bad = (
            "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n\n"
            'ex:Customer a rdfs:Class ;\n    rdfs:label "Customer"@en .\n'
        )
        files = {"file": ("bad.ttl", io.BytesIO(bad.encode()), "text/turtle")}
        r = client.post(
            f"/api/knowledge/collections/{quote(coll['iri'], safe='')}/import",
            files=files,
        )
        assert r.status_code == 400, f"malformed import must 400, got {r.status_code}: {r.text}"

        after = client.get(f"/api/knowledge/collections/{quote(coll['iri'], safe='')}")
        assert after.status_code == 200, after.text
        assert after.json().get("concept_count") == count_before, (
            "a rejected import must not change the collection's concept_count"
        )
