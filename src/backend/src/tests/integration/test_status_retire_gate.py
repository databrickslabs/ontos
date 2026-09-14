"""A still-referenced concept must NOT be moved to a terminal state
(deprecated/archived) via the raw status path — that bypassed the retire gate
(reference_count == 0). Moving a referenced concept to those states must raise
ReferenceCountError (the route maps it to 409). Deprecating WITH successors goes
through deprecate_concept; retiring goes through retire_concept — neither is the
raw status walk.
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


def _mk_published_concept(smm) -> str:
    coll = smm.create_collection(
        label=f"Gate {uuid.uuid4().hex[:8]}", collection_type="glossary",
        scope_level="enterprise", description="retire-gate test",
    )
    created = smm.create_concept(collection_iri=coll["iri"], label="Customer", definition="a party")
    iri = created["iri"] if isinstance(created, dict) else created
    assert smm.get_concept(iri), f"concept not found after create: {iri}"
    # Walk to published so 'deprecated' is a valid next transition.
    for s in ("under_review", "approved", "published"):
        smm.update_concept_status(concept_iri=iri, new_status=s, updated_by="t@x.com")
    return iri


def test_deprecate_referenced_concept_refused(smm, monkeypatch):
    iri = _mk_published_concept(smm)
    monkeypatch.setattr(smm, "reference_count", lambda i: 2)  # still referenced
    with pytest.raises(ReferenceCountError):
        smm.update_concept_status(concept_iri=iri, new_status="deprecated", updated_by="t@x.com")


def test_deprecate_unreferenced_concept_allowed(smm, monkeypatch):
    iri = _mk_published_concept(smm)
    monkeypatch.setattr(smm, "reference_count", lambda i: 0)  # nothing references it
    out = smm.update_concept_status(concept_iri=iri, new_status="deprecated", updated_by="t@x.com")
    assert out and out.get("status") == "deprecated"


def test_archived_referenced_concept_refused(smm, monkeypatch):
    iri = _mk_published_concept(smm)
    # Move to deprecated first (0 refs), then a new reference appears before archive.
    monkeypatch.setattr(smm, "reference_count", lambda i: 0)
    smm.update_concept_status(concept_iri=iri, new_status="deprecated", updated_by="t@x.com")
    monkeypatch.setattr(smm, "reference_count", lambda i: 1)
    with pytest.raises(ReferenceCountError):
        smm.update_concept_status(concept_iri=iri, new_status="archived", updated_by="t@x.com")
