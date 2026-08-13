"""Integration tests for the concept-versioning engine (P0-1/2/3/6/8).

Exercises the versioning lifecycle through the real REST routes + a real
SemanticModelsManager on the shared test DB, mirroring test_knowledge_routes.py
(client + make_collection fixtures). These commit the guarantees that were
previously only proven by an out-of-tree E2E script, so CI and reviewers can
see them:

- publish mints v2, keeps the IRI stable, and SNAPSHOTS v1 (old definition text
  survives) — the core "what was the previous definition" promise;
- the prior version is marked ``superseded`` (not ``deprecated``);
- a normal read returns the CURRENT version and does NOT leak history
  (write-time current/history split, P0-2);
- the reference-count retire GATE refuses (409) while referenced and succeeds
  (tombstone) at zero refs (P0-6);
- deprecate-with-successor records the isReplacedBy link (2B split);
- the partial unique index rejects a second is_current row for one IRI (P0-1).

Note: the test harness builds the schema via ``Base.metadata.create_all`` on
SQLite, and ConceptVersionDb declares the partial index with both
``postgresql_where`` and ``sqlite_where`` so the single-current invariant holds
here too. Postgres-only migration DDL (the rdf_triples_current VIEW) is not
exercised; the served-graph build uses the ORM ``list_current`` which mirrors it.
"""
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from src.app import app
from src.controller.semantic_models_manager import SemanticModelsManager
from src.common.app_state import set_app_state_manager


# ---------------------------------------------------------------------------
# Fixtures — local, mirroring test_knowledge_routes.py (the integration suite
# defines these per-file; there is no shared integration conftest).
# ---------------------------------------------------------------------------


@pytest.fixture
def semantic_models_manager(db_session: Session, tmp_path: Path):
    """SemanticModelsManager on the test session + tmp data dir, published on
    app.state so the route dependencies resolve."""
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
    """Factory that creates a fresh, uniquely-named editable collection."""

    def _make(label_prefix: str = "Ver Coll", collection_type: str = "glossary",
              description: str = "made by versioning test"):
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
    """Create a concept and return its IRI."""
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


def _version_info(client: TestClient, iri: str):
    from urllib.parse import quote
    r = client.get(f"/api/semantic-models/concepts/version?iri={quote(iri, safe='')}")
    assert r.status_code == 200, r.text
    return r.json()


def _version_detail(client: TestClient, iri: str, version: int):
    from urllib.parse import quote
    r = client.get(
        f"/api/semantic-models/concepts/version/detail?iri={quote(iri, safe='')}&version={version}"
    )
    assert r.status_code == 200, r.text
    return r.json()


def _definition(detail: dict) -> str:
    c = detail.get("concept", detail)
    return c.get("definition") or c.get("comment") or ""


class TestConceptVersionPublish:
    def test_create_mints_v1(self, client: TestClient, make_collection):
        coll = make_collection("Ver Create")
        iri = _make_concept(client, coll["iri"], "Customer", "a buyer")

        info = _version_info(client, iri)
        assert info["current_version"] == 1
        assert len(info["versions"]) == 1
        assert info["versions"][0]["is_current"] is True

    def test_publish_bumps_version_keeps_iri(self, client: TestClient, make_collection):
        coll = make_collection("Ver Publish")
        iri = _make_concept(client, coll["iri"], "Revenue", "v1 definition")

        r = client.post("/api/semantic-models/concepts/version/publish", json={
            "iri": iri,
            "changes": {"definition": "v2 definition"},
            "change_note": "tighten",
        })
        assert r.status_code == 200, r.text
        pub = r.json()
        assert pub["new_version"] == 2
        assert pub["is_current"] is True
        assert pub["iri"] == iri  # IRI is stable across versions
        assert pub.get("label")  # label present for the Simple view
        # Publish patches the graph synchronously; no graph_refreshed field.
        assert "graph_refreshed" not in pub

    def test_prior_version_is_superseded(self, client: TestClient, make_collection):
        coll = make_collection("Ver Superseded")
        iri = _make_concept(client, coll["iri"], "Margin", "v1")
        client.post("/api/semantic-models/concepts/version/publish", json={
            "iri": iri, "changes": {"definition": "v2"},
        }).raise_for_status()

        info = _version_info(client, iri)
        assert len(info["versions"]) == 2
        current = next(v for v in info["versions"] if v["is_current"])
        prior = next(v for v in info["versions"] if not v["is_current"])
        assert current["version"] == 2
        # Prior version is 'superseded' — NOT 'deprecated' (which means stop
        # using the concept). The concept itself stays active.
        assert prior["status"] == "superseded", info["versions"]

    def test_snapshot_preserves_old_definition(self, client: TestClient, make_collection):
        """The core promise: after a publish, the PREVIOUS version's definition
        text is still retrievable (v1 triples are frozen, not overwritten)."""
        coll = make_collection("Ver Snapshot")
        iri = _make_concept(client, coll["iri"], "OPEX", "v1 definition")
        client.post("/api/semantic-models/concepts/version/publish", json={
            "iri": iri, "changes": {"definition": "v2 definition (edited)"},
        }).raise_for_status()

        v1 = _version_detail(client, iri, 1)
        v2 = _version_detail(client, iri, 2)
        assert "v1 definition" in _definition(v1), _definition(v1)
        assert "v2 definition (edited)" in _definition(v2), _definition(v2)
        assert _definition(v1) != _definition(v2)


class TestReadIsolation:
    def test_current_read_does_not_leak_history(self, client: TestClient, make_collection):
        """A normal concept read returns the CURRENT version and never the
        frozen prior-version text (write-time current/history split, P0-2)."""
        from urllib.parse import quote
        coll = make_collection("Ver ReadIso")
        iri = _make_concept(client, coll["iri"], "Churn", "v1 definition")
        client.post("/api/semantic-models/concepts/version/publish", json={
            "iri": iri, "changes": {"definition": "v2 definition (edited)"},
        }).raise_for_status()

        r = client.get(f"/api/semantic-models/concepts/by-iri?iri={quote(iri, safe='')}")
        assert r.status_code == 200, r.text
        current_def = _definition(r.json())
        assert "v2 definition (edited)" in current_def
        assert "v1 definition" not in current_def


class TestSafeTransition:
    def test_retire_gate_refuses_while_referenced(
        self, client: TestClient, make_collection, db_session
    ):
        """Retire is refused (409) while the concept is referenced, and succeeds
        (tombstone) once the reference is removed (P0-6)."""
        from urllib.parse import quote
        from src.repositories.semantic_links_repository import entity_semantic_links_repo

        coll = make_collection("Ver RetireGate")
        iri = _make_concept(client, coll["iri"], "Segment", "a grouping")
        q = quote(iri, safe="")

        rc = client.get(f"/api/semantic-models/concepts/reference-count?iri={q}")
        assert rc.status_code == 200 and rc.json()["count"] == 0

        # Create a real reference -> retire must be refused.
        link = client.post("/api/semantic-links/", json={
            "entity_id": f"main.e2e.tbl_{uuid.uuid4().hex[:6]}",
            "entity_type": "uc_table",
            "iri": iri,
        })
        assert link.status_code == 200, link.text
        link_id = link.json()["id"]

        assert client.get(
            f"/api/semantic-models/concepts/reference-count?iri={q}"
        ).json()["count"] > 0
        blocked = client.post("/api/semantic-models/concepts/retire", json={"iri": iri})
        assert blocked.status_code == 409, blocked.text

        # Remove the reference (via the repo the gate reads — avoids coupling the
        # test to the delete route's change-log side effects) -> retire succeeds.
        entity_semantic_links_repo.remove(db_session, id=uuid.UUID(link_id))
        db_session.commit()
        assert client.get(
            f"/api/semantic-models/concepts/reference-count?iri={q}"
        ).json()["count"] == 0
        retired = client.post("/api/semantic-models/concepts/retire", json={"iri": iri})
        assert retired.status_code == 200, retired.text
        assert retired.json()["status"] == "retired"
        # Tombstone, not hard delete: still resolvable.
        assert client.get(
            f"/api/semantic-models/concepts/version?iri={q}"
        ).status_code == 200

    def test_deprecate_with_successor_records_replaced_by(self, client: TestClient, make_collection):
        """A 2B split: deprecate old with a named successor records isReplacedBy."""
        coll = make_collection("Ver Split")
        old_iri = _make_concept(client, coll["iri"], "Customer", "a buyer")
        succ_iri = _make_concept(client, coll["iri"], "Active Customer", "a current buyer")

        dep = client.post("/api/semantic-models/concepts/deprecate", json={
            "iri": old_iri, "replaced_by": [succ_iri],
        })
        assert dep.status_code == 200, dep.text
        assert dep.json()["status"] == "deprecated"

        info = _version_info(client, old_iri)
        assert succ_iri in (info.get("replaced_by_iris") or []), info


class TestSingleCurrentInvariant:
    def test_second_current_row_is_rejected(self, client: TestClient, db_session):
        """The partial unique index allows only one is_current=true row per IRI.

        Declared with both postgresql_where and sqlite_where so the invariant is
        enforced (and testable) on the SQLite test DB, not only Postgres.
        """
        from sqlalchemy.exc import IntegrityError
        from src.db_models.concept_versions import ConceptVersionDb

        iri = f"urn:glossary:test/{uuid.uuid4().hex[:8]}"
        db_session.add(ConceptVersionDb(iri=iri, version=1, is_current=True, status="active"))
        db_session.commit()

        # A second is_current row for the same IRI must be rejected.
        db_session.add(ConceptVersionDb(iri=iri, version=2, is_current=True, status="active"))
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

        # A second NON-current version for the same IRI is allowed.
        db_session.add(ConceptVersionDb(iri=iri, version=2, is_current=False, status="superseded"))
        db_session.commit()
