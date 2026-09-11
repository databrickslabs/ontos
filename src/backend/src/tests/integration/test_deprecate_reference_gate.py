"""The deprecate DIALOG path (deprecate_concept, not the raw status walk) must
also honour the reference gate (CV2-UI-08). A still-REFERENCED concept can only
be deprecated when successor IRIs are supplied (the sanctioned 2B meaning-split
remap) or the references are cleared first; otherwise ReferenceCountError (the
route maps it to 409). The re-upload/versioning path (bypass_editable_gate=True)
is an explicit file-author tombstone and skips the gate even while referenced.
"""
import uuid
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from src.controller.semantic_models_manager import SemanticModelsManager, ReferenceCountError


@pytest.fixture
def smm(db_session: Session, tmp_path: Path, mock_workspace_client):
    data_dir = tmp_path / "sm_data"
    (data_dir / "cache").mkdir(parents=True, exist_ok=True)
    (data_dir / "taxonomies").mkdir(parents=True, exist_ok=True)
    return SemanticModelsManager(db=db_session, data_dir=data_dir)


def _mk_published_concept(smm, label="Customer") -> str:
    coll = smm.create_collection(
        label=f"Gate {uuid.uuid4().hex[:8]}", collection_type="glossary",
        scope_level="enterprise", description="deprecate-gate test",
    )
    created = smm.create_concept(collection_iri=coll["iri"], label=label, definition="a party")
    iri = created["iri"] if isinstance(created, dict) else created
    assert smm.get_concept(iri), f"concept not found after create: {iri}"
    for s in ("under_review", "approved", "published"):
        smm.update_concept_status(concept_iri=iri, new_status=s, updated_by="t@x.com")
    return iri


def test_deprecate_referenced_no_successor_refused(smm, monkeypatch):
    """(a) referenced, no successors -> ReferenceCountError."""
    iri = _mk_published_concept(smm)
    monkeypatch.setattr(smm, "reference_count", lambda i: 6)  # still referenced
    with pytest.raises(ReferenceCountError):
        smm.deprecate_concept(concept_iri=iri, deprecated_by="t@x.com")


def test_deprecate_referenced_with_successor_allowed(smm, monkeypatch):
    """(b) referenced, WITH a successor IRI -> succeeds and writes isReplacedBy."""
    iri = _mk_published_concept(smm)
    successor = _mk_published_concept(smm, label="CustomerV2")
    monkeypatch.setattr(smm, "reference_count", lambda i: 6)  # still referenced
    out = smm.deprecate_concept(
        concept_iri=iri, replaced_by=[successor], deprecated_by="t@x.com",
    )
    assert out and out.get("status") == "deprecated"
    assert successor in (out.get("replaced_by") or [])
    # isReplacedBy lineage link written forward.
    from rdflib import URIRef
    from src.controller.semantic_models_manager import DCT
    assert (URIRef(iri), DCT.isReplacedBy, URIRef(successor)) in smm._graph


def test_deprecate_unreferenced_no_successor_allowed(smm, monkeypatch):
    """(c) unreferenced, no successors -> succeeds."""
    iri = _mk_published_concept(smm)
    monkeypatch.setattr(smm, "reference_count", lambda i: 0)
    out = smm.deprecate_concept(concept_iri=iri, deprecated_by="t@x.com")
    assert out and out.get("status") == "deprecated"


def test_deprecate_referenced_via_reupload_bypass_allowed(smm, monkeypatch):
    """(d) re-upload path (bypass_editable_gate=True) deprecates a referenced
    concept without raising -- an explicit file-author tombstone."""
    iri = _mk_published_concept(smm)
    monkeypatch.setattr(smm, "reference_count", lambda i: 6)  # still referenced
    out = smm.deprecate_concept(
        concept_iri=iri, deprecated_by="t@x.com", bypass_editable_gate=True,
    )
    assert out and out.get("status") == "deprecated"
