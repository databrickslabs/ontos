"""Integration tests for the reference-reconciliation worklist (P1-6).

Exercises split (1->N) + merge (N->1) reconciliation through the real REST
routes + a real SemanticModelsManager on the shared test DB, mirroring
test_concept_versioning.py (there is no shared integration conftest, so this
file defines its OWN client-backed fixtures).

Covers the API contract §5b Accept bullets:
  - the references endpoint itemizes asset refs + concept refs + successors, and
    its ``count`` equals reference_count(iri) (same set the retire gate counts);
  - repointing the only ref off a deprecated concept drops its reference-count to
    0 so retire then succeeds (tombstone);
  - merging 2 sources -> 1 target leaves both sources deprecated with
    isReplacedBy->target and 0 remaining asset refs, and the target gains them;
  - no reference is silently dropped: every repoint is remove+add, so the target
    ends holding the link.
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
# Fixtures — local, mirroring test_concept_versioning.py.
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
    def _make(label_prefix: str = "Recon Coll", collection_type: str = "glossary",
              description: str = "made by reconciliation test"):
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


def _make_concept(
    client: TestClient, collection_iri: str, label: str, definition: str,
    broader_iris: list | None = None,
) -> str:
    payload = {
        "collection_iri": collection_iri,
        "label": label,
        "definition": definition,
    }
    if broader_iris:
        payload["broader_iris"] = broader_iris
    r = client.post("/api/knowledge/concepts", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    iri = body.get("iri") or (body.get("concept") or {}).get("iri")
    assert iri, f"could not resolve created concept IRI from {body}"
    return iri


def _add_link(client: TestClient, iri: str, entity_type: str = "uc_table") -> str:
    entity_id = f"main.recon.tbl_{uuid.uuid4().hex[:6]}"
    r = client.post("/api/semantic-links/", json={
        "entity_id": entity_id,
        "entity_type": entity_type,
        "iri": iri,
    })
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _references(client: TestClient, iri: str) -> dict:
    r = client.get(f"/api/semantic-models/concepts/references?iri={quote(iri, safe='')}")
    assert r.status_code == 200, r.text
    return r.json()


def _reference_count(client: TestClient, iri: str) -> int:
    r = client.get(f"/api/semantic-models/concepts/reference-count?iri={quote(iri, safe='')}")
    assert r.status_code == 200, r.text
    return r.json()["count"]


class TestListReferences:
    def test_references_itemizes_and_count_matches_reference_count(
        self, client: TestClient, make_collection
    ):
        coll = make_collection("Recon List")
        target = _make_concept(client, coll["iri"], "Customer", "a buyer")
        succ = _make_concept(client, coll["iri"], "Active Customer", "a current buyer")

        # An asset ref on the concept.
        link_id = _add_link(client, target)

        # Deprecate WITH a successor so the response carries a successor entry.
        dep = client.post("/api/semantic-models/concepts/deprecate", json={
            "iri": target, "replaced_by": [succ],
        })
        assert dep.status_code == 200, dep.text

        refs = _references(client, target)
        assert refs["iri"] == target
        assert refs["label"]  # human label, never a raw IRI for Simple view
        # asset ref itemized
        assert any(a["link_id"] == link_id for a in refs["asset_refs"]), refs
        # successor recorded by deprecate
        assert any(s["iri"] == succ for s in refs["successors"]), refs
        assert all(s["label"] for s in refs["successors"])
        # count == reference_count (same set the retire gate counts)
        assert refs["count"] == _reference_count(client, target)
        assert refs["count"] == len(refs["asset_refs"]) + len(refs["concept_refs"])

    def test_concept_refs_itemized(self, client: TestClient, make_collection):
        """A concept pointing at the target via broader shows up in concept_refs
        and is included in count."""
        coll = make_collection("Recon ConceptRef")
        parent = _make_concept(client, coll["iri"], "Party", "an actor")
        # child --broader--> parent (set at creation)
        child = _make_concept(
            client, coll["iri"], "Customer", "a buyer", broader_iris=[parent]
        )

        refs = _references(client, parent)
        assert any(c["iri"] == child for c in refs["concept_refs"]), refs
        assert all(c["label"] and c["predicate"] for c in refs["concept_refs"])
        assert refs["count"] == _reference_count(client, parent)


class TestRepoint:
    def test_repoint_drops_ref_and_enables_retire(self, client: TestClient, make_collection):
        """Repoint the only ref off a deprecated concept -> reference-count hits 0
        and retire succeeds (tombstone). No ref silently dropped: target holds it."""
        coll = make_collection("Recon Repoint")
        old = _make_concept(client, coll["iri"], "Cust", "a buyer")
        new = _make_concept(client, coll["iri"], "Active Cust", "a current buyer")

        link_id = _add_link(client, old)
        assert _reference_count(client, old) == 1

        # Deprecate old with new as successor (the worklist entry-point).
        client.post("/api/semantic-models/concepts/deprecate", json={
            "iri": old, "replaced_by": [new],
        }).raise_for_status()

        # Repoint the one ref old -> new.
        rp = client.post("/api/semantic-models/concepts/references/repoint", json={
            "link_id": link_id, "from_iri": old, "to_iri": new,
        })
        assert rp.status_code == 200, rp.text
        body = rp.json()
        assert body["to_iri"] == new
        assert body["to_label"]

        # Old now has 0 refs; new has the ref (nothing dropped).
        assert _reference_count(client, old) == 0
        new_refs = _references(client, new)
        assert len(new_refs["asset_refs"]) == 1, new_refs
        old_refs = _references(client, old)
        assert len(old_refs["asset_refs"]) == 0, old_refs

        # Retire now succeeds (tombstone).
        retired = client.post("/api/semantic-models/concepts/retire", json={"iri": old})
        assert retired.status_code == 200, retired.text
        assert retired.json()["status"] == "retired"

    def test_repoint_validates_from_iri(self, client: TestClient, make_collection):
        """A link that does not point at from_iri yields 404."""
        coll = make_collection("Recon RepointGuard")
        a = _make_concept(client, coll["iri"], "A", "a")
        b = _make_concept(client, coll["iri"], "B", "b")
        c = _make_concept(client, coll["iri"], "C", "c")
        link_id = _add_link(client, a)  # points at A, not B

        r = client.post("/api/semantic-models/concepts/references/repoint", json={
            "link_id": link_id, "from_iri": b, "to_iri": c,
        })
        assert r.status_code == 404, r.text

    def test_repoint_same_iri_is_noop(self, client: TestClient, make_collection):
        coll = make_collection("Recon RepointNoop")
        a = _make_concept(client, coll["iri"], "A", "a")
        link_id = _add_link(client, a)

        r = client.post("/api/semantic-models/concepts/references/repoint", json={
            "link_id": link_id, "from_iri": a, "to_iri": a,
        })
        assert r.status_code == 200, r.text
        assert r.json()["link_id"] == link_id
        assert _reference_count(client, a) == 1


class TestMerge:
    def test_merge_two_sources_into_one(self, client: TestClient, make_collection):
        """Merge 2 sources -> 1 target: both sources deprecated with
        isReplacedBy->target and 0 remaining asset refs; target gains them."""
        coll = make_collection("Recon Merge")
        s1 = _make_concept(client, coll["iri"], "Client", "a buyer (variant 1)")
        s2 = _make_concept(client, coll["iri"], "Buyer", "a buyer (variant 2)")
        target = _make_concept(client, coll["iri"], "Customer", "the canonical buyer")

        l1 = _add_link(client, s1)
        l2 = _add_link(client, s2)
        assert _reference_count(client, s1) == 1
        assert _reference_count(client, s2) == 1

        m = client.post("/api/semantic-models/concepts/merge", json={
            "source_iris": [s1, s2], "target_iri": target, "repoint_refs": True,
        })
        assert m.status_code == 200, m.text
        body = m.json()
        assert body["target_iri"] == target
        merged = {e["source_iri"]: e["refs_repointed"] for e in body["merged"]}
        assert merged.get(s1) == 1 and merged.get(s2) == 1, body

        # Both sources: 0 asset refs remaining, deprecated, isReplacedBy->target.
        for s in (s1, s2):
            assert len(_references(client, s)["asset_refs"]) == 0
            # Concept-level status (ONTOS.status triple) is 'deprecated'. This is a
            # different axis than the version-row lifecycle (active/superseded), so
            # read it from the concept detail, not the version endpoint.
            detail = client.get(
                f"/api/semantic-models/concepts/by-iri?iri={quote(s, safe='')}"
            ).json()
            detail_status = detail.get("status") or (detail.get("concept") or {}).get("status")
            assert detail_status == "deprecated", detail
            # isReplacedBy->target lineage is recorded (version endpoint surfaces it).
            info = client.get(
                f"/api/semantic-models/concepts/version?iri={quote(s, safe='')}"
            ).json()
            assert target in (info.get("replaced_by_iris") or []), info

        # Target gained both refs (nothing dropped).
        target_refs = _references(client, target)
        target_link_iris = {a["link_id"] for a in target_refs["asset_refs"]}
        assert len(target_refs["asset_refs"]) == 2, target_refs
        # the two new links (repoint = remove+add mints fresh ids) both present
        assert len(target_link_iris) == 2
