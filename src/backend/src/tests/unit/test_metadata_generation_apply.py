"""Unit tests for applying Description Suggestions to UC (Metadata Generation, #1187).

Runs against the in-memory ``db_session`` with the real DataAssetReviewManager;
the workspace client (UC table reads, SQL warehouse) and the workflow trigger
registry are mocked. Covers: closing a review (approval, rejection, undecided
suggestions), the comment statements, the conflict check and force-apply,
not-applicable and failed targets, the Asset mirror and change log, the summary
notification, and the workflow's apply step.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from databricks.sdk.errors import NotFound
from databricks.sdk.service.sql import StatementState

from src.controller.data_asset_reviews_manager import DataAssetReviewManager
from src.controller.metadata_generation_manager import MetadataGenerationManager, _string_literal
from src.db_models.assets import AssetDb, AssetTypeDb
from src.db_models.change_log import ChangeLogDb
from src.db_models.data_asset_reviews import DataAssetReviewRequestDb
from src.db_models.metadata_generation import DescriptionSuggestionDb, MetadataGenerationRunDb
from src.models.metadata_generation import SuggestionDecision, SuggestionDecisionBatch

REQUESTER = "owner@example.com"
REVIEWER = "steward@example.com"
TABLE = "main.sales.orders"


@pytest.fixture(autouse=True)
def rollback_keeps_fixture_data(db_session, monkeypatch):
    """A real Session.rollback() would discard the harness's outer transaction."""
    monkeypatch.setattr(db_session, "rollback", MagicMock())


@pytest.fixture(autouse=True)
def trigger_registry(monkeypatch):
    registry = MagicMock()
    registry.on_request_review.return_value = []
    monkeypatch.setattr("src.common.workflow_triggers.get_trigger_registry", lambda db: registry)
    return registry


def _ok(*_args, **_kwargs):
    return SimpleNamespace(status=SimpleNamespace(state=StatementState.SUCCEEDED, error=None), statement_id="s")


def _failed(message):
    return SimpleNamespace(
        status=SimpleNamespace(state=StatementState.FAILED, error=SimpleNamespace(message=message)), statement_id="s",
    )


class FakeUC:
    """Table comments by FQN; records the comment statements it runs."""

    def __init__(self, tables):
        self.tables_by_name = tables
        self.statements = []
        self.write_result = _ok
        self.tables = SimpleNamespace(get=self._get)
        self.statement_execution = SimpleNamespace(execute_statement=self._execute)

    def _get(self, full_name):
        if full_name not in self.tables_by_name:
            raise NotFound(f"Table {full_name} does not exist")
        table = self.tables_by_name[full_name]
        return SimpleNamespace(
            comment=table.get(None),
            columns=[SimpleNamespace(name=name, comment=comment) for name, comment in table.items() if name],
        )

    def _execute(self, statement, **kwargs):
        self.statements.append(statement)
        return self.write_result(statement)


@pytest.fixture
def uc():
    return FakeUC({TABLE: {None: None, "id": None, "amount": "Old amount"}})


@pytest.fixture
def notifications():
    return MagicMock()


@pytest.fixture
def manager(db_session, notifications, uc):
    reviews = DataAssetReviewManager(db=db_session, ws_client=None, notifications_manager=notifications)
    return MetadataGenerationManager(
        settings=SimpleNamespace(
            LLM_ENDPOINT=None, DATABRICKS_CATALOG="app", DATABRICKS_SCHEMA="app",
            DATABRICKS_WAREHOUSE_ID="wh", DATABRICKS_VOLUME=None,
        ),
        jobs_manager=MagicMock(),
        workspace_client_factory=lambda: uc,
        reviews_manager=reviews,
        notifications_manager=notifications,
        audit_manager=MagicMock(),
    )


def _run(db_session):
    run = MetadataGenerationRunDb(
        user_id=REQUESTER, status="completed", selection=[{"type": "schema", "fqn": "main.sales"}],
        options={}, suggestion_count=0,
    )
    db_session.add(run)
    db_session.flush()
    return run


def _suggestion(db_session, run, column=None, *, base_text=None, table=TABLE):
    suggestion = DescriptionSuggestionDb(
        run_id=run.id, kind="description", object_type="column" if column else "table",
        table_fqn=table, column_name=column, base_text=base_text,
        proposed_text=f"About {column or 'orders'}", status="pending",
    )
    db_session.add(suggestion)
    db_session.flush()
    return suggestion


def _reviewed(db_session, manager, targets, *, accept=True, approve=True):
    """A run whose suggestions for ``targets`` (column or None, base text) went through a review."""
    run = _run(db_session)
    suggestions = [_suggestion(db_session, run, column, base_text=base) for column, base in targets]
    result = manager.create_review_for_run(db_session, run, requester_email=REQUESTER, reviewer_email=REVIEWER)
    if accept:
        manager.decide(
            db_session, run,
            SuggestionDecisionBatch(decisions=[SuggestionDecision(id=s.id, decision="accept") for s in suggestions]),
            decided_by=REVIEWER,
        )
    if approve:
        manager.close_review(db_session, result.review_request_id, approved=True)
    for s in suggestions:
        db_session.refresh(s)
    return run, suggestions, result.review_request_id


def _apply(manager, db_session, run, **kwargs):
    return manager.apply_suggestions(db_session, run, applied_by=REVIEWER, **kwargs)


# ----------------------------------------------------------------------
# Writing to UC
# ----------------------------------------------------------------------
def test_apply_writes_table_and_column_comments(db_session, manager, uc):
    run, (table, column), _ = _reviewed(db_session, manager, [(None, None), ("id", None)])

    result = _apply(manager, db_session, run)

    assert (result.applied, result.conflict, result.failed) == (2, 0, 0)
    assert uc.statements == [
        "COMMENT ON TABLE `main`.`sales`.`orders` IS 'About orders'",
        "COMMENT ON COLUMN `main`.`sales`.`orders`.`id` IS 'About id'",
    ]
    for s in (table, column):
        db_session.refresh(s)
        assert (s.status, s.applied_by, s.error) == ("applied", REVIEWER, None)
        assert s.applied_at is not None
    assert column.applied_text == "About id"


def test_the_reviewers_edit_is_what_gets_applied(db_session, manager, uc):
    run = _run(db_session)
    s = _suggestion(db_session, run, "id")
    review = manager.create_review_for_run(db_session, run, requester_email=REQUESTER, reviewer_email=REVIEWER)
    manager.decide(
        db_session, run,
        SuggestionDecisionBatch(decisions=[SuggestionDecision(id=s.id, decision="accept", edited_text="It's the key")]),
        decided_by=REVIEWER,
    )
    manager.close_review(db_session, review.review_request_id, approved=True)

    _apply(manager, db_session, run)

    assert uc.statements == ["COMMENT ON COLUMN `main`.`sales`.`orders`.`id` IS 'It\\'s the key'"]
    db_session.refresh(s)
    assert s.applied_text == "It's the key"


def test_string_literals_escape_quotes_and_backslashes():
    assert _string_literal("a'b\\c") == "'a\\'b\\\\c'"


def test_text_already_in_uc_is_applied_without_a_write(db_session, manager, uc):
    uc.tables_by_name[TABLE]["id"] = "About id"
    run, (s,), _ = _reviewed(db_session, manager, [("id", "About id")])
    # Same text in UC as proposed: nothing to write, but it is applied
    s.proposed_text = "About id"
    db_session.flush()

    assert _apply(manager, db_session, run).applied == 1
    assert uc.statements == []


def test_only_approved_reviews_are_applied(db_session, manager, uc):
    run, (s,), _ = _reviewed(db_session, manager, [("id", None)], approve=False)

    assert _apply(manager, db_session, run).total == 0
    assert uc.statements == []
    db_session.refresh(s)
    assert s.status == "accepted"


def test_rejected_suggestions_are_never_applied(db_session, manager, uc):
    run = _run(db_session)
    s = _suggestion(db_session, run, "id")
    review = manager.create_review_for_run(db_session, run, requester_email=REQUESTER, reviewer_email=REVIEWER)
    manager.decide(
        db_session, run, SuggestionDecisionBatch(decisions=[SuggestionDecision(id=s.id, decision="reject")]),
        decided_by=REVIEWER,
    )
    manager.close_review(db_session, review.review_request_id, approved=True)

    assert _apply(manager, db_session, run).total == 0
    assert uc.statements == []


# ----------------------------------------------------------------------
# Conflicts
# ----------------------------------------------------------------------
def test_changed_uc_description_is_a_conflict_and_not_written(db_session, manager, uc):
    # Generated against "Old amount"; someone changed it in UC since
    uc.tables_by_name[TABLE]["amount"] = "Changed by a human"
    run, (s,), _ = _reviewed(db_session, manager, [("amount", "Old amount")])

    result = _apply(manager, db_session, run)

    assert (result.applied, result.conflict) == (0, 1)
    assert uc.statements == []
    db_session.refresh(s)
    assert s.status == "conflict"
    assert "changed" in s.error


def test_unchanged_base_text_is_no_conflict(db_session, manager, uc):
    run, _, _ = _reviewed(db_session, manager, [("amount", "Old amount")])
    assert _apply(manager, db_session, run).applied == 1


def test_force_applies_conflicts_and_logs_it(db_session, manager, uc):
    uc.tables_by_name[TABLE]["amount"] = "Changed by a human"
    run, (s,), _ = _reviewed(db_session, manager, [("amount", "Old amount")])
    _apply(manager, db_session, run)

    result = _apply(manager, db_session, run, force=True)

    assert result.applied == 1
    assert uc.statements == ["COMMENT ON COLUMN `main`.`sales`.`orders`.`amount` IS 'About amount'"]
    db_session.refresh(s)
    assert s.status == "applied"
    entry = db_session.query(ChangeLogDb).filter_by(entity_type="metadata_generation_run", entity_id=run.id).one()
    assert '"forced": true' in entry.details_json
    assert '"before": "Changed by a human"' in entry.details_json


# ----------------------------------------------------------------------
# Not applicable / failed
# ----------------------------------------------------------------------
def test_missing_table_or_column_is_not_applicable(db_session, manager, uc):
    run = _run(db_session)
    gone_table = _suggestion(db_session, run, "id", table="main.sales.gone")
    gone_column = _suggestion(db_session, run, "dropped")
    review = manager.create_review_for_run(db_session, run, requester_email=REQUESTER, reviewer_email=REVIEWER)
    manager.decide(
        db_session, run,
        SuggestionDecisionBatch(decisions=[SuggestionDecision(id=s.id, decision="accept") for s in (gone_table, gone_column)]),
        decided_by=REVIEWER,
    )
    manager.close_review(db_session, review.review_request_id, approved=True)

    result = _apply(manager, db_session, run)

    assert result.not_applicable == 2
    for s in (gone_table, gone_column):
        db_session.refresh(s)
        assert s.status == "not_applicable"
    assert uc.statements == []


def test_a_write_the_app_may_not_do_is_not_applicable(db_session, manager, uc):
    uc.write_result = lambda statement: _failed("[INSUFFICIENT_PERMISSIONS] User does not have MODIFY on Table")
    run, (s,), _ = _reviewed(db_session, manager, [("id", None)])

    assert _apply(manager, db_session, run).not_applicable == 1
    db_session.refresh(s)
    assert s.status == "not_applicable"


def test_a_failed_write_stays_accepted_and_is_retried(db_session, manager, uc):
    uc.write_result = lambda statement: _failed("warehouse is stopped")
    run, (s,), _ = _reviewed(db_session, manager, [("id", None)])

    result = _apply(manager, db_session, run)
    assert (result.failed, result.applied) == (1, 0)
    assert result.errors == ["main.sales.orders.id: Failed to write the description"]
    db_session.refresh(s)
    assert s.status == "accepted" and s.error

    uc.write_result = _ok
    assert _apply(manager, db_session, run).applied == 1


def test_unreadable_tables_and_bad_names_are_classified(db_session, manager, uc):
    from databricks.sdk.errors import PermissionDenied

    def get(full_name):
        if full_name == "main.sales.secret":
            raise PermissionDenied("no access")
        if full_name == "main.sales.flaky":
            raise RuntimeError("UC unavailable")
        return FakeUC._get(uc, full_name)

    uc.tables = SimpleNamespace(get=get)
    run = _run(db_session)
    secret = _suggestion(db_session, run, "id", table="main.sales.secret")
    flaky = _suggestion(db_session, run, "id", table="main.sales.flaky")
    bad_name = _suggestion(db_session, run, "id", table="main.orders")
    review = manager.create_review_for_run(db_session, run, requester_email=REQUESTER, reviewer_email=REVIEWER)
    manager.decide(
        db_session, run,
        SuggestionDecisionBatch(decisions=[SuggestionDecision(id=s.id, decision="accept") for s in (secret, flaky, bad_name)]),
        decided_by=REVIEWER,
    )
    manager.close_review(db_session, review.review_request_id, approved=True)

    result = _apply(manager, db_session, run)

    assert (result.not_applicable, result.failed, result.applied) == (2, 1, 0)
    for s in (secret, flaky, bad_name):
        db_session.refresh(s)
    assert secret.status == "not_applicable"
    assert bad_name.status == "not_applicable"
    # A transient read failure stays retryable
    assert flaky.status == "accepted" and flaky.error == "Failed to read the current description"
    assert uc.statements == []


def test_a_failing_change_log_keeps_the_suggestion_applied(db_session, manager, uc, monkeypatch):
    run, (s,), _ = _reviewed(db_session, manager, [("id", None)])

    def boom(*args, **kwargs):
        raise RuntimeError("change log down")

    monkeypatch.setattr("src.controller.change_log_manager.change_log_manager.log_change_with_details", boom)

    result = _apply(manager, db_session, run)

    assert result.applied == 1
    db_session.refresh(s)
    assert s.status == "applied"
    db_session.rollback.assert_called()


# ----------------------------------------------------------------------
# Mirror, change log, notification
# ----------------------------------------------------------------------
def test_applied_text_is_mirrored_into_matching_assets(db_session, manager, uc):
    asset_type = AssetTypeDb(id=uuid.uuid4(), name=f"Column-{uuid.uuid4()}")
    db_session.add(asset_type)
    db_session.flush()
    column_asset = AssetDb(id=uuid.uuid4(), name="id", asset_type_id=asset_type.id, location="Main.Sales.Orders.ID")
    other = AssetDb(id=uuid.uuid4(), name="amount", asset_type_id=asset_type.id, location="main.sales.orders.amount",
                    description="keep")
    db_session.add_all([column_asset, other])
    db_session.flush()
    run, _, _ = _reviewed(db_session, manager, [("id", None)])

    _apply(manager, db_session, run)

    db_session.refresh(column_asset)
    db_session.refresh(other)
    assert column_asset.description == "About id"
    assert other.description == "keep"
    entry = db_session.query(ChangeLogDb).filter_by(entity_type="asset", entity_id=str(column_asset.id)).one()
    assert entry.action == "description_applied"
    assert f'"approved_by": "{REVIEWER}"' in entry.details_json


def test_the_owner_gets_a_summary(db_session, manager, uc, notifications):
    uc.tables_by_name[TABLE]["amount"] = "Changed"
    run, _, _ = _reviewed(db_session, manager, [("id", None), ("amount", "Old amount")])
    notifications.reset_mock()

    _apply(manager, db_session, run)

    notification = notifications.create_notification.call_args.args[0]
    assert notification.recipient == REQUESTER
    assert notification.link == f"/metadata-generation/runs/{run.id}"
    assert notification.type == "warning"
    params = notification.data["i18n"]["params"]
    assert (params["applied"], params["conflict"]) == ("1", "1")


# ----------------------------------------------------------------------
# Closing the review
# ----------------------------------------------------------------------
def test_a_rejected_review_applies_nothing_and_releases_undecided(db_session, manager, uc):
    run = _run(db_session)
    accepted, undecided = _suggestion(db_session, run, "id"), _suggestion(db_session, run, "amount")
    review = manager.create_review_for_run(db_session, run, requester_email=REQUESTER, reviewer_email=REVIEWER)
    manager.decide(
        db_session, run, SuggestionDecisionBatch(decisions=[SuggestionDecision(id=accepted.id, decision="accept")]),
        decided_by=REVIEWER,
    )

    manager.close_review(db_session, review.review_request_id, approved=False)

    assert db_session.get(DataAssetReviewRequestDb, review.review_request_id).status == "denied"
    assert _apply(manager, db_session, run).total == 0
    db_session.refresh(undecided)
    assert (undecided.status, undecided.review_request_id) == ("pending", None)
    # ...so it can go into a new review
    assert manager.create_review_for_run(
        db_session, run, requester_email=REQUESTER, reviewer_email=REVIEWER,
    ).suggestion_count == 1


def test_a_closed_review_takes_no_more_decisions(db_session, manager):
    run, (s,), _ = _reviewed(db_session, manager, [("id", None)])
    result = manager.decide(
        db_session, run, SuggestionDecisionBatch(decisions=[SuggestionDecision(id=s.id, decision="reject")]),
        decided_by=REVIEWER,
    )
    assert (result.rejected, result.skipped) == (0, 1)
    assert "closed" in result.errors[0]


def test_closing_twice_keeps_the_first_outcome(db_session, manager):
    _, _, review_id = _reviewed(db_session, manager, [("id", None)])
    manager.close_review(db_session, review_id, approved=False)
    assert db_session.get(DataAssetReviewRequestDb, review_id).status == "approved"


def test_review_summary_counts_applicable(db_session, manager):
    run, _, _ = _reviewed(db_session, manager, [("id", None), ("amount", "Old amount")])
    assert manager.review_summary(db_session, run.id)[2] == 2


# ----------------------------------------------------------------------
# Workflow
# ----------------------------------------------------------------------
def _step_context(run, review_id, approver=REVIEWER):
    from src.common.workflow_executor import StepContext

    return StepContext(
        entity={"review_request_id": review_id}, entity_type="metadata_generation_run", entity_id=run.id,
        entity_name="Descriptions", user_email=approver, trigger_context=None, execution_id="x",
        workflow_id="w", workflow_name="Metadata Generation Review", step_results={},
    )


def test_workflow_apply_step_approves_the_review_and_applies(db_session, manager, uc, monkeypatch):
    from src.common.workflow_executor import EntityActionStepHandler

    monkeypatch.setattr("src.common.app_state._managers_registry", {"metadata_generation_manager": manager})
    run, (s,), review_id = _reviewed(db_session, manager, [("id", None)], approve=False)

    step = {"action": "apply_metadata_suggestions"}
    result = EntityActionStepHandler(db_session, step).execute(_step_context(run, review_id))

    assert result.passed, result.error
    assert result.data["applied"] == 1
    assert db_session.get(DataAssetReviewRequestDb, review_id).status == "approved"
    db_session.refresh(s)
    assert (s.status, s.applied_by) == ("applied", REVIEWER)
    manager._audit.log_action.assert_called_once()
    assert manager._audit.log_action.call_args.kwargs["details"]["source"] == "workflow"


def test_workflow_apply_step_fails_when_writes_failed(db_session, manager, uc, monkeypatch):
    from src.common.workflow_executor import EntityActionStepHandler

    monkeypatch.setattr("src.common.app_state._managers_registry", {"metadata_generation_manager": manager})
    uc.write_result = lambda statement: _failed("warehouse is stopped")
    run, (s,), review_id = _reviewed(db_session, manager, [("id", None)], approve=False)

    step = {"action": "apply_metadata_suggestions"}
    result = EntityActionStepHandler(db_session, step).execute(_step_context(run, review_id))

    # The workflow takes its failure path, which points the requester to the retry
    assert not result.passed
    assert result.data["failed"] == 1
    db_session.refresh(s)
    assert s.status == "accepted"


def test_workflow_apply_step_fails_without_its_review(db_session, manager, monkeypatch):
    from src.common.workflow_executor import EntityActionStepHandler

    monkeypatch.setattr("src.common.app_state._managers_registry", {"metadata_generation_manager": manager})
    run = _run(db_session)
    step = {"action": "apply_metadata_suggestions"}
    assert not EntityActionStepHandler(db_session, step).execute(_step_context(run, None)).passed


def test_workflow_completion_closes_a_rejected_review(db_session, manager, monkeypatch):
    from src.common.workflow_executor import WorkflowExecutor
    from src.models.process_workflows import TriggerContext, TriggerType

    monkeypatch.setattr("src.common.app_state._managers_registry", {"metadata_generation_manager": manager})
    run, _, review_id = _reviewed(db_session, manager, [("id", None)], approve=False)
    executor = WorkflowExecutor.__new__(WorkflowExecutor)
    executor._db = db_session
    workflow = SimpleNamespace(name="Metadata Generation Review", trigger=SimpleNamespace(type="on_request_review"))
    context = TriggerContext(
        entity_type="metadata_generation_run", entity_id=run.id, trigger_type=TriggerType.ON_REQUEST_REVIEW,
        entity_data={"review_request_id": review_id},
    )

    executor._handle_workflow_completion(context, workflow, succeeded=False, responded_by=REVIEWER, approved=False)

    assert db_session.get(DataAssetReviewRequestDb, review_id).status == "denied"
