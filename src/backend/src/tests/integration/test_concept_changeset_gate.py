"""ACCEPTANCE gate for P3 — gate a BULK RDF upload behind ONE changeset approval.

One upload == one approval (never one-per-concept). When a ``concept_changeset``
workflow is scoped to the target collection the whole re-upload is HELD behind a
single aggregate DataAssetReview (AssetType CONCEPT_CHANGESET): nothing is
applied, the UploadPreviewDb token stays ALIVE, and the aggregate diff is carried
into the review. Approval applies the whole changeset all-or-nothing (via the
UNCHANGED confirm_upload) and consumes the token; deny/cancel drops the token and
applies nothing. Ungoverned/no-workflow schemes apply directly (today's zero-
friction behavior).

Scenarios:
  1. UNGOVERNED upload applies directly (status 'applied', diff took effect,
     token consumed).
  2. GOVERNED upload is HELD (nothing applied, token survives, EXACTLY ONE
     CONCEPT_CHANGESET review exists — guards the 40-wizards failure).
  3. APPROVE applies exactly once (concepts reflect the diff, token consumed).
  4. REJECT (DENIED) drops it (token deleted, concepts unchanged).

Governance is simulated by monkeypatching the trigger registry so
``on_request_status_change`` returns one execution (governed=True). Installing a
real workflow YAML in the harness is heavier and orthogonal to the gate logic
under test; the monkeypatch exercises the exact ``governed = bool(executions)``
branch. Both managers are registered on app.state + the app_state registry so the
cross-manager reflection callback resolves.
"""
import uuid
from pathlib import Path

import pytest
from rdflib import Graph
from sqlalchemy.orm import Session

from src.app import app
from src.controller.semantic_models_manager import (
    SemanticModelsManager,
    _sanitize_context_name,
)
from src.controller.data_asset_reviews_manager import DataAssetReviewManager
from src.common.app_state import set_app_state_manager
from src.models.data_asset_reviews import (
    AssetType,
    DataAssetReviewRequestUpdateStatus,
    ReviewRequestStatus,
)
from src.models.semantic_models import SemanticModelCreate
from src.repositories.concept_versions_repository import concept_versions_repo
from src.repositories.upload_preview_repository import upload_preview_repo


class _NoopNotifications:
    def create_notification(self, *a, **k):
        return None


@pytest.fixture
def managers(db_session: Session, tmp_path: Path, mock_workspace_client):
    data_dir = tmp_path / "sm_data"
    (data_dir / "cache").mkdir(parents=True, exist_ok=True)
    (data_dir / "taxonomies").mkdir(parents=True, exist_ok=True)

    smm = SemanticModelsManager(db=db_session, data_dir=data_dir)
    dar = DataAssetReviewManager(
        db=db_session,
        ws_client=mock_workspace_client,
        notifications_manager=_NoopNotifications(),
    )

    app.state.semantic_models_manager = smm
    app.state.data_asset_review_manager = dar
    set_app_state_manager("semantic_models_manager", smm)
    set_app_state_manager("data_asset_review_manager", dar)

    class _Noop:
        def sync_asset_types(self, *a, **k):
            return {"created": 0, "updated": 0}

        def log_action(self, *a, **k):
            return None

        def log_event(self, *a, **k):
            return None

    app.state.ontology_schema_manager = _Noop()
    app.state.audit_manager = _Noop()

    yield smm, dar

    for attr in (
        "semantic_models_manager", "data_asset_review_manager",
        "ontology_schema_manager", "audit_manager",
    ):
        if hasattr(app.state, attr):
            delattr(app.state, attr)


# --------------------------------------------------------------------------- #
# Fixture ontologies (mirror test_upload_preview.py).                         #
# --------------------------------------------------------------------------- #
_PREFIXES = """@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .
@prefix ex: <http://example.org/onto#> .
"""

GLOSSARY_V1 = _PREFIXES + """
ex:Customer a skos:Concept ;
    skos:prefLabel "Customer" ;
    skos:definition "A buyer of goods." .

ex:Revenue a skos:Concept ;
    skos:prefLabel "Revenue" ;
    skos:definition "Income from sales." .
"""

# Revenue definition edited (modified); nothing added/removed.
GLOSSARY_MODIFIED = _PREFIXES + """
ex:Customer a skos:Concept ;
    skos:prefLabel "Customer" ;
    skos:definition "A buyer of goods." .

ex:Revenue a skos:Concept ;
    skos:prefLabel "Revenue" ;
    skos:definition "Income from sales, net of returns." .
"""

CUSTOMER = "http://example.org/onto#Customer"
REVENUE = "http://example.org/onto#Revenue"


def _parse(ttl: str) -> Graph:
    g = Graph()
    g.parse(data=ttl, format="turtle")
    return g


def _seed(mgr: SemanticModelsManager, name: str, ttl: str, actor: str = "tester"):
    data = SemanticModelCreate(
        name=name,
        format="skos",
        content_text=ttl,
        original_filename=name,
        content_type="text/turtle",
        size_bytes=len(ttl),
        enabled=True,
    )
    m = mgr.create(data, created_by=actor)
    mgr.rebuild_graph_from_enabled()
    return m


def _context(name: str) -> str:
    return f"urn:semantic-model:{_sanitize_context_name(name)}"


def _unique_name() -> str:
    return f"changeset_{uuid.uuid4().hex[:8]}.ttl"


class _FakeExecution:
    """Stand-in for a WorkflowExecution so governed=bool(executions) is True."""
    reviewer_email = "gov-reviewer@example.com"


def _force_governed(monkeypatch):
    """Make the CONCEPT_CHANGESET trigger return one execution (governed=True)."""
    import src.common.workflow_triggers as wt

    class _FakeRegistry:
        def on_request_status_change(self, *a, **k):
            return [_FakeExecution()]

    monkeypatch.setattr(wt, "get_trigger_registry", lambda db: _FakeRegistry())


# --------------------------------------------------------------------------- #
# 1. UNGOVERNED upload applies directly.                                      #
# --------------------------------------------------------------------------- #
def test_ungoverned_upload_applies_directly(managers, db_session):
    smm, _ = managers
    name = _unique_name()
    _seed(smm, name, GLOSSARY_V1)
    ctx = _context(name)

    preview = smm.preview_upload(ctx, _parse(GLOSSARY_MODIFIED))
    token = preview["preview_token"]
    assert preview["summary"]["modified"] == 1, preview

    # No changeset workflow installed -> ungoverned -> apply directly.
    result = smm.gate_or_apply_upload(ctx, token, actor="tester")

    assert result["status"] == "applied"
    assert result["governed"] is False
    assert result["summary"]["modified"] == 1

    # The diff took effect: Revenue advanced to v2 with the new definition.
    assert concept_versions_repo.max_version(db_session, REVENUE) == 2
    current = smm.get_concept(REVENUE)
    assert "net of returns" in (current.get("comment") or current.get("definition") or "")

    # Token consumed.
    assert upload_preview_repo.get(db_session, token) is None


# --------------------------------------------------------------------------- #
# 2. GOVERNED upload is HELD — nothing applied, token survives, ONE review.   #
# --------------------------------------------------------------------------- #
def test_governed_upload_is_held(managers, db_session, monkeypatch):
    smm, dar = managers
    name = _unique_name()
    _seed(smm, name, GLOSSARY_V1)
    ctx = _context(name)

    preview = smm.preview_upload(ctx, _parse(GLOSSARY_MODIFIED))
    token = preview["preview_token"]

    _force_governed(monkeypatch)
    result = smm.gate_or_apply_upload(ctx, token, actor="uploader@example.com")

    assert result["status"] == "held"
    assert result["governed"] is True
    assert result["review_request_id"] is not None

    # NOTHING applied: no version minted (seed leaves concepts unversioned),
    # definition unchanged.
    assert concept_versions_repo.max_version(db_session, REVENUE) == 0
    current = smm.get_concept(REVENUE)
    assert "net of returns" not in (current.get("comment") or current.get("definition") or "")

    # Token still ALIVE (held, not consumed).
    assert upload_preview_repo.get(db_session, token) is not None

    # EXACTLY ONE CONCEPT_CHANGESET review exists (guards the 40-wizards failure).
    review = dar.get_review_request(result["review_request_id"])
    assert review is not None
    assert len(review.assets) == 1
    assert review.assets[0].asset_type == AssetType.CONCEPT_CHANGESET
    assert review.assets[0].asset_fqn == f"concept-changeset://{token}"


# --------------------------------------------------------------------------- #
# 3. APPROVE applies the held changeset exactly once.                         #
# --------------------------------------------------------------------------- #
def test_approve_applies_changeset_once(managers, db_session, monkeypatch):
    smm, dar = managers
    name = _unique_name()
    _seed(smm, name, GLOSSARY_V1)
    ctx = _context(name)

    preview = smm.preview_upload(ctx, _parse(GLOSSARY_MODIFIED))
    token = preview["preview_token"]

    _force_governed(monkeypatch)
    result = smm.gate_or_apply_upload(ctx, token, actor="uploader@example.com")
    review_id = result["review_request_id"]
    assert result["status"] == "held"

    # Drive the review to APPROVED -> the changeset applies.
    dar.update_review_request_status(
        review_id,
        DataAssetReviewRequestUpdateStatus(status=ReviewRequestStatus.APPROVED),
    )

    # Applied exactly once: Revenue at v2 with the new definition.
    assert concept_versions_repo.max_version(db_session, REVENUE) == 2
    current = smm.get_concept(REVENUE)
    assert "net of returns" in (current.get("comment") or current.get("definition") or "")

    # Token consumed by the apply -> a second apply is impossible (single-use).
    assert upload_preview_repo.get(db_session, token) is None
    with pytest.raises(ValueError):
        smm.apply_changeset_by_token(token, actor="uploader@example.com")


# --------------------------------------------------------------------------- #
# 4. REJECT (DENIED) drops the held changeset — nothing applied.              #
# --------------------------------------------------------------------------- #
def test_deny_drops_changeset(managers, db_session, monkeypatch):
    smm, dar = managers
    name = _unique_name()
    _seed(smm, name, GLOSSARY_V1)
    ctx = _context(name)

    preview = smm.preview_upload(ctx, _parse(GLOSSARY_MODIFIED))
    token = preview["preview_token"]

    _force_governed(monkeypatch)
    result = smm.gate_or_apply_upload(ctx, token, actor="uploader@example.com")
    review_id = result["review_request_id"]
    assert result["status"] == "held"

    # Drive the review to DENIED -> the held upload is dropped.
    dar.update_review_request_status(
        review_id,
        DataAssetReviewRequestUpdateStatus(
            status=ReviewRequestStatus.DENIED, notes="Reject this bulk change."
        ),
    )

    # Token deleted, nothing applied: no version minted, definition unchanged.
    assert upload_preview_repo.get(db_session, token) is None
    assert concept_versions_repo.max_version(db_session, REVENUE) == 0
    current = smm.get_concept(REVENUE)
    assert "net of returns" not in (current.get("comment") or current.get("definition") or "")
