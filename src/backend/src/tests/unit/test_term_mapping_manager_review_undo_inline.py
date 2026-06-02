"""Unit tests covering the un-tested edges of TermMappingManager.

Companion to test_term_mapping_manager_sync.py (which covers ``decide()``).
These three method families have no DB or HTTP plumbing in them, so they
mock cleanly and are worth fast unit coverage:

* create_review_for_run — spawns an AR from pending suggestions, wires
  back-pointers, and now also fires a steward confirmation notification.
* undo_run — reverts an applied run: removes semantic links, flips
  suggestion status, marks run undone, resets stats.
* suggest_inline — non-persistent helper for the concept picker. Two
  resolution paths: persisted target via adapter.get_target, or
  synthetic target from request hints.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import List
from unittest.mock import MagicMock

import pytest

from src.controller.term_mapping_manager import TermMappingManager
from src.db_models.term_mappings import (
    RUN_STATUS_APPLIED,
    RUN_STATUS_SUGGESTED,
    RUN_STATUS_UNDONE,
    SUG_STATUS_ACCEPTED,
    SUG_STATUS_APPLIED,
    SUG_STATUS_PENDING,
)
from src.models.term_mappings import (
    GenerateReviewRequest,
    InlineSuggestRequest,
)


# ---------- shared fixtures ----------


def _make_suggestion(*, status=SUG_STATUS_PENDING, with_review_link=False, sid=None):
    return SimpleNamespace(
        id=sid or str(uuid.uuid4()),
        run_id=uuid.uuid4(),
        source_entity_type="asset",
        source_entity_id="col-1",
        source_label="customer_id",
        suggestion_kind="attribute_assignment",
        target_concept_iri="urn:semantic-model:retail#Customer.identifier",
        target_concept_label="identifier",
        confidence=0.95,
        reason="exact match",
        auto_apply=False,
        engine="heuristic",
        engine_metadata=None,
        status=status,
        decided_by=None,
        decided_at=None,
        custom_iri=None,
        applied_link_id=None,
        warnings=None,
        review_request_id=uuid.uuid4() if with_review_link else None,
        reviewed_asset_id=uuid.uuid4() if with_review_link else None,
    )


def _make_run(*, status=RUN_STATUS_SUGGESTED, applied_link_ids=None, run_id=None):
    return SimpleNamespace(
        id=run_id or uuid.uuid4(),
        stats={},
        applied_link_ids=list(applied_link_ids or []),
        status=status,
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


# ============================================================
# create_review_for_run
# ============================================================


def _patch_review_repos(monkeypatch, *, run, candidates):
    monkeypatch.setattr(
        "src.controller.term_mapping_manager.mapping_run_repo.get",
        lambda _db, _id: run,
    )
    monkeypatch.setattr(
        "src.controller.term_mapping_manager.mapping_suggestion_repo.list_for_run",
        lambda _db, _rid, status=None, limit=None: list(candidates),
    )


def test_create_review_for_run_spawns_ar_and_wires_backpointers(monkeypatch):
    """Happy path: pending suggestions get bundled into an AR, the AR's
    ReviewedAsset ids are written back onto each suggestion, and the
    steward gets a confirmation notification."""
    run = _make_run()
    sugs = [_make_suggestion() for _ in range(3)]
    for s in sugs:
        s.run_id = run.id
    _patch_review_repos(monkeypatch, run=run, candidates=sugs)

    reviews = MagicMock()
    fake_review_id = str(uuid.uuid4())
    fake_asset_ids = [str(uuid.uuid4()) for _ in sugs]
    reviews.create_review_request.return_value = SimpleNamespace(
        id=fake_review_id,
        assets=[SimpleNamespace(id=aid) for aid in fake_asset_ids],
    )
    notifications = MagicMock()

    mgr = TermMappingManager(
        semantic_models_manager=MagicMock(),
        reviews_manager=reviews,
        notifications_manager=notifications,
    )

    resp = mgr.create_review_for_run(
        MagicMock(),
        run_id=str(run.id),
        payload=GenerateReviewRequest(
            reviewer_email="reviewer@example.com",
            notes="please review",
        ),
        requester_email="alice@example.com",
    )

    # AR was created with all three suggestions as ReviewedAssets.
    reviews.create_review_request.assert_called_once()
    request_data = reviews.create_review_request.call_args.kwargs["request_data"]
    assert request_data.reviewer_email == "reviewer@example.com"
    assert request_data.requester_email == "alice@example.com"
    assert len(request_data.asset_fqns) == 3
    # FQNs follow the term-mapping://run/sug convention so the AR detail
    # view can deep-link back to the run + suggestion.
    for fqn, sug in zip(request_data.asset_fqns, sugs):
        assert fqn == f"term-mapping://{run.id}/{sug.id}"

    # Each suggestion got bound to its corresponding ReviewedAsset.
    for sug, expected_aid in zip(sugs, fake_asset_ids):
        assert str(sug.reviewed_asset_id) == expected_aid
        assert str(sug.review_request_id) == fake_review_id

    # Steward confirmation notification was sent.
    notifications.create_notification.assert_called_once()
    notif = notifications.create_notification.call_args.args[0]
    assert notif.recipient == "alice@example.com"
    assert "Term-mapping" in notif.title
    assert notif.link == f"/data-asset-reviews/{fake_review_id}"

    assert str(resp.run_id) == str(run.id)
    assert resp.review_request_id == fake_review_id
    assert resp.suggestion_count == 3


def test_create_review_for_run_uses_payload_requester_when_provided(monkeypatch):
    run = _make_run()
    sug = _make_suggestion()
    sug.run_id = run.id
    _patch_review_repos(monkeypatch, run=run, candidates=[sug])

    reviews = MagicMock()
    reviews.create_review_request.return_value = SimpleNamespace(
        id=str(uuid.uuid4()),
        assets=[SimpleNamespace(id=str(uuid.uuid4()))],
    )
    mgr = TermMappingManager(
        semantic_models_manager=MagicMock(),
        reviews_manager=reviews,
        notifications_manager=MagicMock(),
    )

    mgr.create_review_for_run(
        MagicMock(),
        run_id=str(run.id),
        payload=GenerateReviewRequest(
            reviewer_email="reviewer@example.com",
            requester_email="explicit@example.com",
        ),
        # Caller-context email is the fallback only.
        requester_email="caller@example.com",
    )

    request_data = reviews.create_review_request.call_args.kwargs["request_data"]
    assert request_data.requester_email == "explicit@example.com"


def test_create_review_for_run_skips_already_reviewed_suggestions(monkeypatch):
    """Suggestions that are already bound to a previous AR mustn't be
    bundled into a new one — otherwise a steward could end up with the
    same row living in two review queues."""
    run = _make_run()
    already_reviewed = _make_suggestion(with_review_link=True)
    fresh = _make_suggestion()
    for s in (already_reviewed, fresh):
        s.run_id = run.id
    _patch_review_repos(monkeypatch, run=run, candidates=[already_reviewed, fresh])

    reviews = MagicMock()
    reviews.create_review_request.return_value = SimpleNamespace(
        id=str(uuid.uuid4()),
        assets=[SimpleNamespace(id=str(uuid.uuid4()))],
    )
    mgr = TermMappingManager(
        semantic_models_manager=MagicMock(),
        reviews_manager=reviews,
        notifications_manager=MagicMock(),
    )

    resp = mgr.create_review_for_run(
        MagicMock(),
        run_id=str(run.id),
        payload=GenerateReviewRequest(reviewer_email="reviewer@example.com"),
        requester_email="alice@example.com",
    )

    assert resp.suggestion_count == 1
    request_data = reviews.create_review_request.call_args.kwargs["request_data"]
    assert len(request_data.asset_fqns) == 1
    assert request_data.asset_fqns[0].endswith(f"/{fresh.id}")


def test_create_review_for_run_raises_when_no_eligible_candidates(monkeypatch):
    run = _make_run()
    _patch_review_repos(monkeypatch, run=run, candidates=[])

    mgr = TermMappingManager(
        semantic_models_manager=MagicMock(),
        reviews_manager=MagicMock(),
    )

    with pytest.raises(ValueError, match="No suggestions eligible"):
        mgr.create_review_for_run(
            MagicMock(),
            run_id=str(run.id),
            payload=GenerateReviewRequest(reviewer_email="reviewer@example.com"),
            requester_email="alice@example.com",
        )


def test_create_review_for_run_raises_when_reviews_manager_missing():
    mgr = TermMappingManager(semantic_models_manager=MagicMock())
    with pytest.raises(ValueError, match="Reviews manager not configured"):
        mgr.create_review_for_run(
            MagicMock(),
            run_id="any",
            payload=GenerateReviewRequest(reviewer_email="reviewer@example.com"),
            requester_email="alice@example.com",
        )


def test_create_review_for_run_notification_failure_does_not_block_spawn(monkeypatch):
    """A flaky notifications backend must not roll back an already-created
    AR. The user gets back a successful response; the missing notification
    is logged."""
    run = _make_run()
    sug = _make_suggestion()
    sug.run_id = run.id
    _patch_review_repos(monkeypatch, run=run, candidates=[sug])

    reviews = MagicMock()
    fake_review_id = str(uuid.uuid4())
    reviews.create_review_request.return_value = SimpleNamespace(
        id=fake_review_id,
        assets=[SimpleNamespace(id=str(uuid.uuid4()))],
    )
    notifications = MagicMock()
    notifications.create_notification.side_effect = RuntimeError("notif down")

    mgr = TermMappingManager(
        semantic_models_manager=MagicMock(),
        reviews_manager=reviews,
        notifications_manager=notifications,
    )

    resp = mgr.create_review_for_run(
        MagicMock(),
        run_id=str(run.id),
        payload=GenerateReviewRequest(reviewer_email="reviewer@example.com"),
        requester_email="alice@example.com",
    )

    assert resp.review_request_id == fake_review_id
    notifications.create_notification.assert_called_once()


# ============================================================
# undo_run
# ============================================================


def test_undo_run_happy_path(monkeypatch):
    """Reverts links, flips applied suggestions back to accepted, marks
    the run undone, and clears the stale links_created counter."""
    link_ids = [str(uuid.uuid4()), str(uuid.uuid4())]
    run = _make_run(status=RUN_STATUS_APPLIED, applied_link_ids=link_ids)
    run.stats = {"links_created": 2, "links_skipped": 0}
    sug_a = _make_suggestion(status=SUG_STATUS_APPLIED)
    sug_b = _make_suggestion(status=SUG_STATUS_APPLIED)
    for s in (sug_a, sug_b):
        s.run_id = run.id
        s.applied_link_id = uuid.uuid4()

    monkeypatch.setattr(
        "src.controller.term_mapping_manager.mapping_run_repo.get",
        lambda _db, _id: run,
    )
    monkeypatch.setattr(
        "src.controller.term_mapping_manager.mapping_suggestion_repo.list_for_run",
        lambda _db, _rid, status=None, limit=None: [sug_a, sug_b],
    )

    # SQLAlchemy query → filter → all chain that undo_run uses to find
    # applied suggestions.
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = [sug_a, sug_b]

    class _FakeSml:
        def __init__(self, *_, **__): pass

        def remove(self, link_id, removed_by=None):
            return True

    monkeypatch.setattr(
        "src.controller.term_mapping_manager.SemanticLinksManager", _FakeSml
    )

    mgr = TermMappingManager(semantic_models_manager=MagicMock())
    result = mgr.undo_run(db, run_id=str(run.id), undone_by="bob@example.com")

    assert result.links_removed == 2
    assert result.suggestions_reverted == 2
    assert result.errors == []
    assert run.status == RUN_STATUS_UNDONE
    assert run.applied_link_ids == []
    assert run.stats["links_created"] == 0
    assert run.stats["links_skipped"] == 0
    for s in (sug_a, sug_b):
        assert s.status == SUG_STATUS_ACCEPTED
        assert s.applied_link_id is None


def test_undo_run_rejects_non_applied_status(monkeypatch):
    """Can only undo an applied run. Calling undo on a suggested run
    raises rather than silently erasing state."""
    run = _make_run(status=RUN_STATUS_SUGGESTED)
    monkeypatch.setattr(
        "src.controller.term_mapping_manager.mapping_run_repo.get",
        lambda _db, _id: run,
    )
    mgr = TermMappingManager(semantic_models_manager=MagicMock())
    with pytest.raises(ValueError, match="can only undo an 'applied' run"):
        mgr.undo_run(MagicMock(), run_id=str(run.id), undone_by="bob@example.com")


def test_undo_run_records_link_removal_failures(monkeypatch):
    """If one link removal blows up, the run still proceeds — the error
    is recorded in the result so the steward can investigate."""
    link_ids = [str(uuid.uuid4()), str(uuid.uuid4())]
    run = _make_run(status=RUN_STATUS_APPLIED, applied_link_ids=link_ids)
    monkeypatch.setattr(
        "src.controller.term_mapping_manager.mapping_run_repo.get",
        lambda _db, _id: run,
    )
    monkeypatch.setattr(
        "src.controller.term_mapping_manager.mapping_suggestion_repo.list_for_run",
        lambda _db, _rid, status=None, limit=None: [],
    )
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = []

    failing_link = link_ids[0]

    class _FakeSml:
        def __init__(self, *_, **__): pass

        def remove(self, link_id, removed_by=None):
            if link_id == failing_link:
                raise RuntimeError("boom")
            return True

    monkeypatch.setattr(
        "src.controller.term_mapping_manager.SemanticLinksManager", _FakeSml
    )

    mgr = TermMappingManager(semantic_models_manager=MagicMock())
    result = mgr.undo_run(db, run_id=str(run.id), undone_by="bob@example.com")

    assert result.links_removed == 1
    assert any(failing_link in err for err in result.errors)
    assert run.status == RUN_STATUS_UNDONE


def test_undo_run_records_missing_link(monkeypatch):
    """A link that's already gone (remove returns False) is also an
    error worth surfacing so the steward knows their queue is drifted
    relative to the DB."""
    link_id = str(uuid.uuid4())
    run = _make_run(status=RUN_STATUS_APPLIED, applied_link_ids=[link_id])
    monkeypatch.setattr(
        "src.controller.term_mapping_manager.mapping_run_repo.get",
        lambda _db, _id: run,
    )
    monkeypatch.setattr(
        "src.controller.term_mapping_manager.mapping_suggestion_repo.list_for_run",
        lambda _db, _rid, status=None, limit=None: [],
    )
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = []

    class _FakeSml:
        def __init__(self, *_, **__): pass

        def remove(self, link_id, removed_by=None):
            return False

    monkeypatch.setattr(
        "src.controller.term_mapping_manager.SemanticLinksManager", _FakeSml
    )

    mgr = TermMappingManager(semantic_models_manager=MagicMock())
    result = mgr.undo_run(db, run_id=str(run.id), undone_by="bob@example.com")

    assert result.links_removed == 0
    assert any("already missing" in err for err in result.errors)


# ============================================================
# suggest_inline
# ============================================================


def _make_concept_candidate(*, iri: str, label: str, source: str = "urn:demo"):
    from src.controller.term_mapping.types import ConceptCandidate
    return ConceptCandidate(
        iri=iri,
        label=label,
        comment="",
        source_context=source,
        parent_iris=[],
        is_class=True,
    )


def _make_target(*, name: str, entity_type: str = "asset", entity_id: str = "col-1"):
    from src.controller.term_mapping.types import TargetEntity
    return TargetEntity(
        entity_type=entity_type,
        entity_id=entity_id,
        name=name,
        label=name,
        type_label="string",
    )


def _stub_inline_pipeline(monkeypatch, *, candidates, target):
    """Patch ConceptSource + HeuristicSuggester + adapters used by
    suggest_inline so we can exercise the full method without touching
    rdflib or the real adapter implementations."""
    monkeypatch.setattr(
        "src.controller.term_mapping_manager.resolve_inline_default_contexts",
        lambda _smm: ["urn:demo"],
    )

    class _FakeConceptSource:
        def __init__(self, *_, **__): pass
        def classes(self): return list(candidates)
        def properties(self): return []

    monkeypatch.setattr(
        "src.controller.term_mapping_manager.ConceptSource", _FakeConceptSource
    )

    class _FakeAdapter:
        entity_types = ("asset",)
        def get_target(self, _db, _entity_id):
            return target

    monkeypatch.setattr(
        "src.controller.term_mapping_manager.all_adapters",
        lambda: [_FakeAdapter()],
    )


def test_suggest_inline_returns_ranked_suggestions_for_persisted_target(monkeypatch):
    """Adapter resolves a real persisted target; engine returns matches
    sorted by confidence; suggest_inline caps to limit."""
    candidates = [
        _make_concept_candidate(iri="urn:demo#Customer", label="Customer"),
        _make_concept_candidate(iri="urn:demo#Order", label="Order"),
    ]
    target = _make_target(name="customer_id")
    _stub_inline_pipeline(monkeypatch, candidates=candidates, target=target)

    mgr = TermMappingManager(semantic_models_manager=MagicMock())
    resp = mgr.suggest_inline(
        MagicMock(),
        payload=InlineSuggestRequest(
            source_entity_type="asset",
            source_entity_id="col-1",
            limit=5,
        ),
    )

    assert resp.source_entity_type == "asset"
    assert resp.source_entity_id == "col-1"
    assert resp.suggestions, "expected at least one suggestion"
    # Customer should rank above Order on a name like 'customer_id'.
    top = resp.suggestions[0]
    assert top.target_concept_label == "Customer"
    confidences = [s.confidence for s in resp.suggestions]
    assert confidences == sorted(confidences, reverse=True)


def test_suggest_inline_caps_to_limit(monkeypatch):
    candidates = [
        _make_concept_candidate(iri=f"urn:demo#C{i}", label=f"customer_id_{i}")
        for i in range(10)
    ]
    target = _make_target(name="customer_id")
    _stub_inline_pipeline(monkeypatch, candidates=candidates, target=target)

    mgr = TermMappingManager(semantic_models_manager=MagicMock())
    resp = mgr.suggest_inline(
        MagicMock(),
        payload=InlineSuggestRequest(
            source_entity_type="asset",
            source_entity_id="col-1",
            limit=3,
        ),
    )
    assert len(resp.suggestions) <= 3


def test_suggest_inline_falls_back_to_synthetic_target_when_adapter_misses(monkeypatch):
    """When the entity isn't persisted yet (draft form), the adapter's
    get_target returns None — suggest_inline must build a synthetic
    TargetEntity from the request hints and feed it to the engine, rather
    than short-circuiting to empty.

    We assert the orchestration handed a target to the engine; the
    heuristic's confidence threshold itself is exercised in
    test_term_mapping_heuristic.py."""
    from src.controller.term_mapping.types import SuggestionDraft, TargetEntity

    candidates = [
        _make_concept_candidate(iri="urn:demo#Customer", label="Customer"),
    ]
    # Adapter matches the entity_type but returns None for the lookup,
    # forcing the synthetic-target fallback path.
    _stub_inline_pipeline(monkeypatch, candidates=candidates, target=None)

    seen_targets: List[TargetEntity] = []

    class _RecordingEngine:
        def __init__(self, *_, **__): pass

        def suggest(self, targets):
            seen_targets.extend(targets)
            return [
                SuggestionDraft(
                    source_entity_type=targets[0].entity_type,
                    source_entity_id=targets[0].entity_id,
                    source_label=targets[0].name,
                    suggestion_kind="attribute_assignment",
                    target_concept_iri="urn:demo#Customer",
                    target_concept_label="Customer",
                    confidence=0.8,
                    reason="synthetic match",
                )
            ]

    monkeypatch.setattr(
        "src.controller.term_mapping_manager.HeuristicSuggester", _RecordingEngine
    )

    mgr = TermMappingManager(semantic_models_manager=MagicMock())
    resp = mgr.suggest_inline(
        MagicMock(),
        payload=InlineSuggestRequest(
            source_entity_type="asset",
            source_entity_id="draft-property",
            name="customer_email",
            type_label="string",
            parent_name="customers",
            limit=5,
        ),
    )

    assert len(seen_targets) == 1
    synthetic = seen_targets[0]
    # Hints flowed through to the TargetEntity passed to the engine.
    assert synthetic.name == "customer_email"
    assert synthetic.type_label == "string"
    assert synthetic.parent_name == "customers"
    assert resp.suggestions, "synthetic-target path should still suggest"
    assert resp.suggestions[0].target_concept_label == "Customer"


def test_suggest_inline_returns_empty_when_no_target_and_no_hints(monkeypatch):
    """No persisted target AND no synthetic-target hints → empty result.
    Picker shows just the regular concept list in that case."""
    _stub_inline_pipeline(monkeypatch, candidates=[], target=None)

    mgr = TermMappingManager(semantic_models_manager=MagicMock())
    resp = mgr.suggest_inline(
        MagicMock(),
        payload=InlineSuggestRequest(
            source_entity_type="asset",
            source_entity_id="nope",
        ),
    )
    assert resp.suggestions == []


def test_suggest_inline_drops_new_concept_sentinels(monkeypatch):
    """Engine drafts whose target IRI starts with NEW: are 'propose a
    new concept' placeholders, not real candidates. They mustn't leak
    into the inline picker tier."""
    from src.controller.term_mapping.types import SuggestionDraft

    target = _make_target(name="customer_id")
    _stub_inline_pipeline(monkeypatch, candidates=[], target=target)

    fake_drafts = [
        SuggestionDraft(
            source_entity_type="asset",
            source_entity_id="col-1",
            source_label="customer_id",
            suggestion_kind="attribute_assignment",
            target_concept_iri="NEW:customer_id",
            target_concept_label="customer_id",
            confidence=0.9,
            reason="no-op",
        ),
        SuggestionDraft(
            source_entity_type="asset",
            source_entity_id="col-1",
            source_label="customer_id",
            suggestion_kind="attribute_assignment",
            target_concept_iri="urn:demo#Customer",
            target_concept_label="Customer",
            confidence=0.85,
            reason="real match",
        ),
    ]

    class _FakeEngine:
        def __init__(self, *_, **__): pass
        def suggest(self, _targets: List): return fake_drafts

    monkeypatch.setattr(
        "src.controller.term_mapping_manager.HeuristicSuggester", _FakeEngine
    )

    mgr = TermMappingManager(semantic_models_manager=MagicMock())
    resp = mgr.suggest_inline(
        MagicMock(),
        payload=InlineSuggestRequest(
            source_entity_type="asset",
            source_entity_id="col-1",
            limit=5,
        ),
    )
    iris = [s.target_concept_iri for s in resp.suggestions]
    assert all(not iri.startswith("NEW:") for iri in iris)
    assert "urn:demo#Customer" in iris


def test_suggest_inline_strips_blocked_contexts(monkeypatch):
    """Even if a caller passes an internal/blocked context (e.g. by
    constructing the request by hand), it must be stripped — the inline
    suggester should never look up matches against the internal Ontos
    taxonomy."""
    candidates = [_make_concept_candidate(iri="urn:demo#Customer", label="Customer")]
    target = _make_target(name="customer_id")
    _stub_inline_pipeline(monkeypatch, candidates=candidates, target=target)

    seen_contexts: List[List[str]] = []

    class _RecordingConceptSource:
        def __init__(self, _smm, contexts):
            seen_contexts.append(list(contexts))
        def classes(self): return list(candidates)
        def properties(self): return []

    monkeypatch.setattr(
        "src.controller.term_mapping_manager.ConceptSource",
        _RecordingConceptSource,
    )

    mgr = TermMappingManager(semantic_models_manager=MagicMock())
    mgr.suggest_inline(
        MagicMock(),
        payload=InlineSuggestRequest(
            source_entity_type="asset",
            source_entity_id="col-1",
            ontology_contexts=[
                "urn:demo",
                "urn:semantic-links",   # blocked
                "urn:taxonomy:ontos-ontology",  # blocked
            ],
            limit=5,
        ),
    )
    assert seen_contexts, "ConceptSource should have been constructed"
    final = seen_contexts[0]
    assert "urn:demo" in final
    assert "urn:semantic-links" not in final
    assert "urn:taxonomy:ontos-ontology" not in final
