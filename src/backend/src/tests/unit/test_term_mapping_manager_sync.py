"""Unit tests for TermMappingManager's AR-sync + per-row apply logic.

We mock the SQLAlchemy session, the suggestion repository, and the
DataAssetReviewManager. The contract under test is the orchestration logic
in ``decide()``:

  accept → suggestion status flips, semantic-links.add is called, the
           linked ReviewedAsset is bumped to APPROVED, the run's
           applied_link_ids is grown.
  reject → status flips, AR row goes to REJECTED, no link is created.
  clarify → status flips to needs_clarification, AR row goes to
            NEEDS_CLARIFICATION.

These tests run with no DB, no real engines, and no semantic-models
manager — purely manager wiring + state transitions.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.controller.term_mapping_manager import TermMappingManager
from src.db_models.term_mappings import (
    RUN_STATUS_SUGGESTED,
    SUG_STATUS_ACCEPTED,
    SUG_STATUS_APPLIED,
    SUG_STATUS_NEEDS_CLARIFICATION,
    SUG_STATUS_PENDING,
    SUG_STATUS_REJECTED,
)
from src.models.data_asset_reviews import ReviewedAssetStatus
from src.models.term_mappings import (
    SuggestionDecision,
    SuggestionDecisionBatch,
)


def _make_suggestion(suggestion_id: str = None, *, with_review: bool = True):
    # Use data_contract_property because semantic_links.EntityType Literal
    # doesn't yet include 'asset' (separate follow-up; out of scope here).
    return SimpleNamespace(
        id=suggestion_id or str(uuid.uuid4()),
        run_id=uuid.uuid4(),
        source_entity_type="data_contract_property",
        source_entity_id="contract-1#schema-a#customer_id",
        source_label="customer_id",
        suggestion_kind="attribute_assignment",
        target_concept_iri="urn:semantic-model:retail#Customer.identifier",
        target_concept_label="identifier",
        confidence=0.95,
        reason="exact name match",
        auto_apply=True,
        engine="heuristic",
        engine_metadata=None,
        status=SUG_STATUS_PENDING,
        decided_by=None,
        decided_at=None,
        custom_iri=None,
        applied_link_id=None,
        warnings=None,
        review_request_id=uuid.uuid4() if with_review else None,
        reviewed_asset_id=uuid.uuid4() if with_review else None,
    )


def _make_run(suggestion):
    return SimpleNamespace(
        id=suggestion.run_id,
        stats={},
        applied_link_ids=[],
        status=RUN_STATUS_SUGGESTED,
        ontology_contexts=[],
        include_shipped=[],
        target_filter={},
        engines=["heuristic"],
        comment=None,
        error=None,
        created_by="alice@example.com",
        created_at=datetime.now(timezone.utc),
        started_at=None,
        finished_at=None,
        applied_at=None,
        undone_at=None,
    )


@pytest.fixture
def fixtures():
    sug = _make_suggestion()
    run = _make_run(sug)
    reviews = MagicMock()
    smm = MagicMock()
    mgr = TermMappingManager(semantic_models_manager=smm, reviews_manager=reviews)
    return SimpleNamespace(sug=sug, run=run, reviews=reviews, mgr=mgr)


def _patch_repos_and_sml(monkeypatch, *, sug, run, link_id=None, fail_link=False):
    """Patch the module-level repos and SemanticLinksManager constructor."""
    monkeypatch.setattr(
        "src.controller.term_mapping_manager.mapping_suggestion_repo.get",
        lambda _db, _id: sug,
    )
    monkeypatch.setattr(
        "src.controller.term_mapping_manager.mapping_run_repo.get",
        lambda _db, _id: run,
    )
    # _refresh_run_stats also calls list_for_run; return our single suggestion.
    monkeypatch.setattr(
        "src.controller.term_mapping_manager.mapping_suggestion_repo.list_for_run",
        lambda _db, _rid, status=None, limit=None: [sug],
    )

    class _FakeSml:
        def __init__(self, *_, **__): pass

        def add(self, payload, created_by=None):
            if fail_link:
                raise RuntimeError("boom")
            return SimpleNamespace(id=link_id or uuid.uuid4())

    monkeypatch.setattr(
        "src.controller.term_mapping_manager.SemanticLinksManager",
        _FakeSml,
    )


def test_accept_applies_link_and_syncs_ar_to_approved(monkeypatch, fixtures):
    sug, run, reviews, mgr = fixtures.sug, fixtures.run, fixtures.reviews, fixtures.mgr
    link_id = uuid.uuid4()
    _patch_repos_and_sml(monkeypatch, sug=sug, run=run, link_id=link_id)

    db = MagicMock()
    result = mgr.decide(
        db,
        batch=SuggestionDecisionBatch(decisions=[SuggestionDecision(id=sug.id, decision="accept")]),
        decided_by="alice@example.com",
    )

    assert result.accepted == 1
    assert result.rejected == 0
    assert sug.status == SUG_STATUS_APPLIED
    assert sug.applied_link_id == link_id
    assert str(link_id) in run.applied_link_ids
    reviews.update_asset_status_by_id.assert_called_once_with(
        str(sug.reviewed_asset_id), ReviewedAssetStatus.APPROVED, db=db
    )


def test_accept_with_link_failure_stays_at_accepted(monkeypatch, fixtures):
    """If the per-row apply explodes, the suggestion remains ACCEPTED so a
    later bulk Apply can sweep it up. AR row still goes APPROVED — the
    reviewer's *intent* was approve, so the queue should reflect that."""
    sug, run, reviews, mgr = fixtures.sug, fixtures.run, fixtures.reviews, fixtures.mgr
    _patch_repos_and_sml(monkeypatch, sug=sug, run=run, fail_link=True)

    result = mgr.decide(
        MagicMock(),
        batch=SuggestionDecisionBatch(decisions=[SuggestionDecision(id=sug.id, decision="accept")]),
        decided_by="alice@example.com",
    )

    assert result.accepted == 1
    assert sug.status == SUG_STATUS_ACCEPTED  # not APPLIED
    assert sug.applied_link_id is None
    assert any("apply_failed" in w for w in (sug.warnings or []))
    assert len(result.errors) == 1
    reviews.update_asset_status_by_id.assert_called_once()
    # AR status should still be APPROVED — bulk Apply will reconcile later.
    args, kwargs = reviews.update_asset_status_by_id.call_args
    assert ReviewedAssetStatus.APPROVED in args


def test_reject_syncs_ar_to_rejected(monkeypatch, fixtures):
    sug, run, reviews, mgr = fixtures.sug, fixtures.run, fixtures.reviews, fixtures.mgr
    _patch_repos_and_sml(monkeypatch, sug=sug, run=run)

    result = mgr.decide(
        MagicMock(),
        batch=SuggestionDecisionBatch(decisions=[SuggestionDecision(id=sug.id, decision="reject")]),
        decided_by="alice@example.com",
    )

    assert result.rejected == 1
    assert sug.status == SUG_STATUS_REJECTED
    assert sug.applied_link_id is None
    reviews.update_asset_status_by_id.assert_called_once_with(
        str(sug.reviewed_asset_id), ReviewedAssetStatus.REJECTED, db=ANY
    )


def test_clarify_syncs_ar_to_needs_clarification(monkeypatch, fixtures):
    sug, run, reviews, mgr = fixtures.sug, fixtures.run, fixtures.reviews, fixtures.mgr
    _patch_repos_and_sml(monkeypatch, sug=sug, run=run)

    result = mgr.decide(
        MagicMock(),
        batch=SuggestionDecisionBatch(decisions=[SuggestionDecision(id=sug.id, decision="clarify")]),
        decided_by="alice@example.com",
    )

    # 'clarify' is bucketed under skipped in the result (no accepted/rejected
    # counter for it), but the suggestion + AR are both moved.
    assert result.skipped == 1
    assert sug.status == SUG_STATUS_NEEDS_CLARIFICATION
    reviews.update_asset_status_by_id.assert_called_once_with(
        str(sug.reviewed_asset_id), ReviewedAssetStatus.NEEDS_CLARIFICATION, db=ANY
    )


def test_decide_without_review_back_pointer_skips_ar_sync(monkeypatch, fixtures):
    """A suggestion that isn't bound to a ReviewedAsset (e.g. someone decides
    via the workbench rather than a review) shouldn't touch the AR manager."""
    sug = _make_suggestion(with_review=False)
    run = _make_run(sug)
    reviews = MagicMock()
    smm = MagicMock()
    mgr = TermMappingManager(semantic_models_manager=smm, reviews_manager=reviews)
    _patch_repos_and_sml(monkeypatch, sug=sug, run=run)

    mgr.decide(
        MagicMock(),
        batch=SuggestionDecisionBatch(decisions=[SuggestionDecision(id=sug.id, decision="reject")]),
        decided_by="alice@example.com",
    )

    assert sug.status == SUG_STATUS_REJECTED
    reviews.update_asset_status_by_id.assert_not_called()


def test_ar_sync_failure_does_not_revert_decision(monkeypatch, fixtures):
    """A flaky AR sync mustn't roll the suggestion back. The decision is the
    source of truth; sync is best-effort."""
    sug, run, reviews, mgr = fixtures.sug, fixtures.run, fixtures.reviews, fixtures.mgr
    _patch_repos_and_sml(monkeypatch, sug=sug, run=run)
    reviews.update_asset_status_by_id.side_effect = RuntimeError("network glitch")

    mgr.decide(
        MagicMock(),
        batch=SuggestionDecisionBatch(decisions=[SuggestionDecision(id=sug.id, decision="reject")]),
        decided_by="alice@example.com",
    )
    assert sug.status == SUG_STATUS_REJECTED


# Helper sentinel used in argument matchers above (ANY-style).
class _Any:
    def __eq__(self, _other): return True
ANY = _Any()
