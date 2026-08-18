"""Concept-changeset upload behavior.

SCENARIO D (2026-08-18) — the bulk-upload changeset APPROVAL GATE IS DISABLED.
Per an explicit product decision, ALL file uploads land directly as Draft and
follow the normal per-concept review; a re-upload is never HELD behind an
aggregate changeset approval, even when a ``concept_changeset`` workflow is
scoped to the target collection. ``gate_or_apply_upload`` always applies directly
and returns ``{status:'applied', governed:False}``.

The changeset primitives (``apply_changeset_by_token`` /
``reject_changeset_by_token`` / ``changeset_review_fqn``) are LEFT IN PLACE (a
legacy held review could still reference them), so the two acceptance tests that
exercised the held APPROVE/DENY lifecycle are SKIPPED rather than deleted — un-
skip them (and re-enable the gate in ``gate_or_apply_upload``) if bulk-upload
gating is ever re-opened.

Scenarios:
  1. UNGOVERNED upload applies directly (status 'applied', diff took effect,
     token consumed).
  2. A GOVERNED workflow NO LONGER holds — the upload still applies directly
     (Scenario D: gate disabled).
  3. (SKIPPED — parked) APPROVE applies the held changeset once.
  4. (SKIPPED — parked) REJECT (DENIED) drops the held changeset.

Governance is simulated by monkeypatching the trigger registry so
``on_request_status_change`` returns one execution (would have been
governed=True). Both managers are registered on app.state + the app_state
registry so the cross-manager reflection callback resolves.
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
# 2. Scenario D: a GOVERNED workflow NO LONGER holds — applies directly.      #
# --------------------------------------------------------------------------- #
def test_governed_upload_applies_directly_scenario_d(managers, db_session, monkeypatch):
    """Even with a changeset workflow scoped, the upload applies directly.

    Scenario D (2026-08-18) disabled the hold: ``gate_or_apply_upload`` skips the
    trigger + held-review branch and always applies. This test pins that the
    presence of a (would-be) governing execution does NOT hold the upload.
    """
    smm, dar = managers
    name = _unique_name()
    _seed(smm, name, GLOSSARY_V1)
    ctx = _context(name)

    preview = smm.preview_upload(ctx, _parse(GLOSSARY_MODIFIED))
    token = preview["preview_token"]

    _force_governed(monkeypatch)
    result = smm.gate_or_apply_upload(ctx, token, actor="uploader@example.com")

    # Gate disabled: applies directly, NOT held.
    assert result["status"] == "applied"
    assert result["governed"] is False
    assert result.get("review_request_id") is None

    # The diff took effect: Revenue advanced to v2 with the new definition.
    assert concept_versions_repo.max_version(db_session, REVENUE) == 2
    current = smm.get_concept(REVENUE)
    assert "net of returns" in (current.get("comment") or current.get("definition") or "")

    # Token consumed by the direct apply (no held changeset review left behind).
    assert upload_preview_repo.get(db_session, token) is None


# --------------------------------------------------------------------------- #
# 3. APPROVE applies the held changeset exactly once. (PARKED — gate disabled) #
# --------------------------------------------------------------------------- #
@pytest.mark.skip(reason="Scenario D (2026-08-18): changeset approval gate disabled; "
                         "un-skip if bulk-upload gating is re-opened in gate_or_apply_upload.")
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
# 4. REJECT (DENIED) drops the held changeset. (PARKED — gate disabled)       #
# --------------------------------------------------------------------------- #
@pytest.mark.skip(reason="Scenario D (2026-08-18): changeset approval gate disabled; "
                         "un-skip if bulk-upload gating is re-opened in gate_or_apply_upload.")
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
