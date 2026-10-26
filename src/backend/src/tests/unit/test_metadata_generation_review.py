"""Unit tests for reviewing Description Suggestions (Metadata Generation, #1186).

Runs against the in-memory ``db_session`` with the real DataAssetReviewManager;
the workflow trigger registry and the notifications manager are mocked.
Covers: submitting a run (one Asset Review, one ReviewedAsset per pending
suggestion, back-pointers, workflow trigger, reviewer notification), reviewer
defaults and guards, the reviewers' decisions (incl. edits and clarification),
auto-submit after ingest, and the default review workflow.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import yaml

from src.controller.data_asset_reviews_manager import DataAssetReviewManager
from src.controller.metadata_generation_manager import MetadataGenerationManager
from src.db_models.data_asset_reviews import DataAssetReviewRequestDb, ReviewedAssetDb
from src.db_models.metadata_generation import DescriptionSuggestionDb, MetadataGenerationRunDb
from src.models.metadata_generation import SuggestionDecision, SuggestionDecisionBatch
from src.models.process_workflows import EntityType

REQUESTER = "owner@example.com"
REVIEWER = "steward@example.com"


class SyncExecutor:
    def submit(self, fn, *args, **kwargs):
        fn(*args, **kwargs)


@pytest.fixture(autouse=True)
def rollback_keeps_fixture_data(db_session, monkeypatch):
    """A real Session.rollback() would discard the harness's outer transaction."""
    rollback = MagicMock()
    monkeypatch.setattr(db_session, "rollback", rollback)
    return rollback


@pytest.fixture
def trigger_registry(monkeypatch):
    registry = MagicMock()
    registry.on_request_review.return_value = []
    monkeypatch.setattr("src.common.workflow_triggers.get_trigger_registry", lambda db: registry)
    return registry


@pytest.fixture
def notifications():
    return MagicMock()


@pytest.fixture
def manager(db_session, notifications, trigger_registry):
    reviews = DataAssetReviewManager(db=db_session, ws_client=None, notifications_manager=notifications)
    return MetadataGenerationManager(
        settings=SimpleNamespace(
            LLM_ENDPOINT=None, DATABRICKS_CATALOG="app", DATABRICKS_SCHEMA="app",
            DATABRICKS_WAREHOUSE_ID="wh", DATABRICKS_VOLUME=None,
        ),
        jobs_manager=MagicMock(),
        ingest_executor=SyncExecutor(),
        reviews_manager=reviews,
        notifications_manager=notifications,
    )


def _run(db_session, *, status="completed", options=None, user_id=REQUESTER):
    run = MetadataGenerationRunDb(
        user_id=user_id, status=status, selection=[{"type": "schema", "fqn": "main.sales"}],
        options=options or {}, suggestion_count=0,
    )
    db_session.add(run)
    db_session.flush()
    return run


def _suggestion(db_session, run, column=None, *, status="pending", **kwargs):
    suggestion = DescriptionSuggestionDb(
        run_id=run.id, kind="description", object_type="column" if column else "table",
        table_fqn="main.sales.orders", column_name=column, proposed_text=f"About {column or 'orders'}",
        status=status, **kwargs,
    )
    db_session.add(suggestion)
    db_session.flush()
    return suggestion


def _submitted(db_session, manager, columns=("id", "amount")):
    run = _run(db_session)
    suggestions = [_suggestion(db_session, run, c) for c in columns]
    manager.create_review_for_run(db_session, run, requester_email=REQUESTER, reviewer_email=REVIEWER)
    for s in suggestions:
        db_session.refresh(s)
    return run, suggestions


def _decide(manager, db_session, run, *decisions, by=REVIEWER, is_admin=False):
    batch = SuggestionDecisionBatch(decisions=[SuggestionDecision(**d) for d in decisions])
    return manager.decide(db_session, run, batch, decided_by=by, is_admin=is_admin)


def _asset(db_session, suggestion_or_id):
    asset_id = getattr(suggestion_or_id, "reviewed_asset_id", suggestion_or_id)
    return db_session.get(ReviewedAssetDb, asset_id)


# ----------------------------------------------------------------------
# Submit
# ----------------------------------------------------------------------
def test_submit_puts_each_pending_suggestion_in_one_review(db_session, manager, trigger_registry, notifications):
    run = _run(db_session)
    pending = [_suggestion(db_session, run, "id"), _suggestion(db_session, run, "amount")]
    superseded = _suggestion(db_session, run, "old", status="superseded")

    result = manager.create_review_for_run(db_session, run, requester_email=REQUESTER, reviewer_email=REVIEWER)

    assert result.suggestion_count == 2
    review = db_session.get(DataAssetReviewRequestDb, result.review_request_id)
    assert (review.requester_email, review.reviewer_email) == (REQUESTER, REVIEWER)
    assert review.title == "Descriptions for main.sales"
    for s in pending:
        db_session.refresh(s)
        assert s.review_request_id == review.id
        asset = _asset(db_session, s)
        assert asset.asset_fqn == f"metagen://{run.id}/{s.id}"
        assert asset.asset_type == "metadata_suggestion"
    db_session.refresh(superseded)
    assert superseded.review_request_id is None

    # Our workflow runs instead of the generic data asset review workflow
    trigger_registry.on_request_review.assert_called_once()
    kwargs = trigger_registry.on_request_review.call_args.kwargs
    assert kwargs["entity_type"] == EntityType.METADATA_GENERATION_RUN
    assert kwargs["entity_id"] == run.id
    assert kwargs["entity_data"]["reviewer_email"] == REVIEWER
    assert kwargs["entity_data"]["review_request_id"] == review.id
    assert kwargs["user_email"] == REQUESTER

    notification = notifications.create_notification.call_args.args[0]
    assert notification.recipient == REVIEWER
    assert notification.link == f"/data-asset-reviews/{review.id}"
    assert notification.data["i18n"]["params"] == {"requester": REQUESTER, "count": "2", "selection": "main.sales"}


def test_resubmitting_only_takes_suggestions_not_yet_in_review(db_session, manager):
    run, _ = _submitted(db_session, manager)
    with pytest.raises(ValueError, match="No pending suggestions"):
        manager.create_review_for_run(db_session, run, requester_email=REQUESTER, reviewer_email=REVIEWER)

    later = _suggestion(db_session, run, "later")
    result = manager.create_review_for_run(db_session, run, requester_email=REQUESTER, reviewer_email=REVIEWER)
    assert result.suggestion_count == 1
    db_session.refresh(later)
    assert later.review_request_id == result.review_request_id


def test_reviewer_defaults_to_a_data_steward(db_session, manager, monkeypatch):
    calls = []

    def resolve(db, role, requester):
        calls.append((role, requester))
        return REVIEWER

    monkeypatch.setattr("src.common.workflow_executor.resolve_reviewer_email", resolve)
    run = _run(db_session)
    _suggestion(db_session, run, "id")

    result = manager.create_review_for_run(db_session, run, requester_email=REQUESTER)
    assert result.reviewer_email == REVIEWER
    assert calls == [("DataSteward", REQUESTER)]


def test_submit_fails_when_no_reviewer_can_be_found(db_session, manager, monkeypatch):
    monkeypatch.setattr("src.common.workflow_executor.resolve_reviewer_email", lambda *a: None)
    run = _run(db_session)
    _suggestion(db_session, run, "id")
    with pytest.raises(ValueError, match="pick a reviewer"):
        manager.create_review_for_run(db_session, run, requester_email=REQUESTER)


def test_requester_cannot_review_their_own_run(db_session, manager):
    run = _run(db_session)
    _suggestion(db_session, run, "id")
    with pytest.raises(ValueError, match="your own"):
        manager.create_review_for_run(db_session, run, requester_email=REQUESTER, reviewer_email=REQUESTER.upper())
    assert db_session.query(DataAssetReviewRequestDb).count() == 0


def test_only_completed_runs_can_be_submitted(db_session, manager):
    run = _run(db_session, status="running")
    with pytest.raises(ValueError, match="completed"):
        manager.create_review_for_run(db_session, run, requester_email=REQUESTER, reviewer_email=REVIEWER)


def test_workflow_trigger_failure_does_not_undo_the_review(db_session, manager, trigger_registry):
    trigger_registry.on_request_review.side_effect = RuntimeError("boom")
    run, suggestions = _submitted(db_session, manager, columns=("id",))
    assert suggestions[0].review_request_id is not None


# ----------------------------------------------------------------------
# Decisions
# ----------------------------------------------------------------------
def test_accept_with_an_edit_keeps_the_edit_and_approves_the_asset(db_session, manager):
    run, (first, second) = _submitted(db_session, manager)

    result = _decide(
        manager, db_session, run,
        {"id": first.id, "decision": "accept", "edited_text": "  Order id  ", "comment": "tightened"},
        {"id": second.id, "decision": "accept", "edited_text": second.proposed_text},
    )

    assert (result.accepted, result.skipped, result.errors) == (2, 0, [])
    db_session.refresh(first)
    db_session.refresh(second)
    assert (first.status, first.edited_text, first.review_comment) == ("accepted", "Order id", "tightened")
    assert first.decided_by == REVIEWER and first.decided_at is not None
    assert second.edited_text is None  # unchanged text is no edit
    assert _asset(db_session, first).status == "approved"
    assert _asset(db_session, first).comments == "tightened"


def test_reject_closes_the_suggestion_and_can_be_revised(db_session, manager):
    run, (first, _) = _submitted(db_session, manager)

    _decide(manager, db_session, run, {"id": first.id, "decision": "reject"})
    db_session.refresh(first)
    assert first.status == "rejected"
    assert _asset(db_session, first).status == "rejected"

    _decide(manager, db_session, run, {"id": first.id, "decision": "accept"})
    db_session.refresh(first)
    assert first.status == "accepted"
    assert _asset(db_session, first).status == "approved"


def test_clarify_returns_the_suggestion_to_pending_outside_the_review(db_session, manager):
    run, (first, _) = _submitted(db_session, manager)
    asset_id = first.reviewed_asset_id

    result = _decide(manager, db_session, run, {"id": first.id, "decision": "clarify", "comment": "Which amount?"})

    assert result.clarify == 1
    db_session.refresh(first)
    assert first.status == "pending"
    assert (first.review_request_id, first.reviewed_asset_id) == (None, None)
    assert first.review_comment == "Which amount?"
    asset = _asset(db_session, asset_id)
    assert (asset.status, asset.comments) == ("needs_clarification", "Which amount?")
    # ...so it can go into a new review
    again = manager.create_review_for_run(db_session, run, requester_email=REQUESTER, reviewer_email=REVIEWER)
    assert again.suggestion_count == 1


def test_only_the_assigned_reviewer_or_an_admin_decides(db_session, manager):
    run, (first, second) = _submitted(db_session, manager)

    result = _decide(manager, db_session, run, {"id": first.id, "decision": "accept"}, by="someone@example.com")
    assert (result.accepted, result.skipped) == (0, 1)
    db_session.refresh(first)
    assert first.status == "pending"

    result = _decide(manager, db_session, run, {"id": second.id, "decision": "reject"}, by="admin@example.com", is_admin=True)
    assert result.rejected == 1


def test_reviewer_match_ignores_case(db_session, manager):
    run, (first, _) = _submitted(db_session, manager)
    assert _decide(manager, db_session, run, {"id": first.id, "decision": "accept"}, by=REVIEWER.upper()).accepted == 1


def test_decisions_for_other_runs_or_outside_a_review_are_skipped(db_session, manager):
    run, (first, _) = _submitted(db_session, manager)
    other_run = _run(db_session)
    not_in_review = _suggestion(db_session, run, "loose")
    applied = _suggestion(db_session, run, "done", status="applied", review_request_id=first.review_request_id)

    result = _decide(
        manager, db_session, other_run, {"id": first.id, "decision": "accept"},
    )
    assert (result.accepted, result.skipped) == (0, 1)
    result = _decide(
        manager, db_session, run,
        {"id": not_in_review.id, "decision": "accept"},
        {"id": applied.id, "decision": "reject"},
        {"id": "missing", "decision": "accept"},
    )
    assert (result.accepted, result.rejected, result.skipped) == (0, 0, 3)
    db_session.refresh(applied)
    assert applied.status == "applied"


# ----------------------------------------------------------------------
# Auto-submit
# ----------------------------------------------------------------------
def _ingest(manager, db_session, run, rows):
    manager._fetch_results = lambda run_id, on_page=None: rows
    return manager.ingest_results(db_session, run)


def _row(column):
    return {"object_type": "column", "table_fqn": "main.sales.orders", "column_name": column,
            "base_text": None, "proposed_text": f"About {column}"}


def test_auto_submit_puts_a_fresh_run_up_for_review(db_session, manager):
    run = _run(db_session, status="running", options={"auto_submit": True, "reviewer_email": REVIEWER})

    assert _ingest(manager, db_session, run, [_row("id"), _row("amount")]) == 2

    suggestions = db_session.query(DescriptionSuggestionDb).filter_by(run_id=run.id).all()
    assert {s.review_request_id for s in suggestions} != {None}
    assert len({s.review_request_id for s in suggestions}) == 1
    assert db_session.get(DataAssetReviewRequestDb, suggestions[0].review_request_id).reviewer_email == REVIEWER


def test_failed_auto_submit_leaves_the_run_completed(db_session, manager, monkeypatch):
    monkeypatch.setattr("src.common.workflow_executor.resolve_reviewer_email", lambda *a: None)
    run = _run(db_session, status="running", options={"auto_submit": True})

    _ingest(manager, db_session, run, [_row("id")])

    db_session.refresh(run)
    assert run.status == "completed"
    assert db_session.query(DescriptionSuggestionDb).filter_by(run_id=run.id).one().review_request_id is None


def test_without_auto_submit_nothing_is_submitted(db_session, manager, trigger_registry):
    run = _run(db_session, status="running")
    _ingest(manager, db_session, run, [_row("id")])
    trigger_registry.on_request_review.assert_not_called()


# ----------------------------------------------------------------------
# Workflow
# ----------------------------------------------------------------------
def test_default_review_workflow_targets_generation_runs_and_the_reviewer():
    from pathlib import Path

    path = Path(__file__).parents[2] / "data" / "default_workflows.yaml"
    workflows = {w["id"]: w for w in yaml.safe_load(path.read_text())["workflows"]}
    workflow = workflows["metadata-generation-review"]
    assert workflow["trigger"] == {"type": "on_request_review", "entity_types": ["metadata_generation_run"]}
    approval = next(s for s in workflow["steps"] if s["type"] == "approval")
    assert approval["config"]["approvers"] == "reviewer"
    # Approval applies the accepted descriptions; a rejection applies nothing
    steps = {s["id"]: s for s in workflow["steps"]}
    apply_step = steps[approval["on_pass"]]
    assert (apply_step["type"], apply_step["config"]["action"]) == ("entity_action", "apply_metadata_suggestions")
    assert not any(s["type"] == "entity_action" for s in workflow["steps"] if s["id"] == approval["on_fail"])
    # Ontos creates the review itself: the workflow must not create another
    assert not any(s["type"] == "create_asset_review" for s in workflow["steps"])


def test_reviewer_token_resolves_to_the_requests_reviewer(db_session):
    from src.common.workflow_executor import _resolve_role_to_users

    context = SimpleNamespace(trigger_context=SimpleNamespace(entity_data={"reviewer_email": REVIEWER}), entity={})
    assert _resolve_role_to_users(db_session, "reviewer", context) == [(REVIEWER, None)]
    empty = SimpleNamespace(trigger_context=None, entity={})
    assert _resolve_role_to_users(db_session, "reviewer", empty) == []


def test_review_summary_counts_unsubmitted_and_lists_reviews(db_session, manager):
    run, (first, _) = _submitted(db_session, manager)
    _suggestion(db_session, run, "later")
    _suggestion(db_session, run, "gone", status="superseded")

    unsubmitted, reviews, applicable = manager.review_summary(db_session, run.id)
    assert unsubmitted == 1
    assert reviews == [first.review_request_id]
    assert applicable == 0  # nothing accepted in an approved review


def _steward_role(db_session, members):
    """A 'Data Steward' app role whose group has ``members`` (user id -> email)."""
    import uuid
    from src.db_models.settings import AppRoleDb

    db_session.add(AppRoleDb(id=str(uuid.uuid4()), name="Data Steward", assigned_groups='["data-stewards"]'))
    db_session.flush()
    group = SimpleNamespace(members=[SimpleNamespace(value=uid) for uid in members])
    return SimpleNamespace(
        groups=SimpleNamespace(list=lambda **_: [group]),
        users=SimpleNamespace(get=lambda uid: SimpleNamespace(user_name=members[uid])),
    )


def test_resolve_reviewer_email_picks_a_steward_other_than_the_requester(db_session):
    from unittest.mock import patch
    from src.common.workflow_executor import resolve_reviewer_email

    ws = _steward_role(db_session, {"u1": REQUESTER, "u2": REVIEWER})
    with patch("src.common.workspace_client.get_workspace_client", return_value=ws):
        assert resolve_reviewer_email(db_session, "DataSteward", REQUESTER) == REVIEWER


def test_resolve_reviewer_email_is_none_when_only_the_requester_could_review(db_session):
    from unittest.mock import patch
    from src.common.workflow_executor import resolve_reviewer_email

    ws = _steward_role(db_session, {"u1": REQUESTER})
    with patch("src.common.workspace_client.get_workspace_client", return_value=ws):
        assert resolve_reviewer_email(db_session, "DataSteward", REQUESTER) is None
