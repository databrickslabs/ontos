"""Unit tests for MetadataGenerationManager (Generation Runs + ingest).

Runs against the in-memory ``db_session``; the Jobs API and the SQL warehouse
are mocked. Covers: launching the job, the active-run limit, status refresh
from the Jobs API, idempotent ingest with fill-gaps filtering, supersession of
older pending suggestions, cancel and delete rules.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from databricks.sdk.service.sql import StatementState

from src.common.errors import ConflictError
from src.controller.metadata_generation_manager import (
    WORKFLOW_ID,
    ActiveRunLimitError,
    MetadataGenerationManager,
    selection_to_table_names,
)
from src.db_models.metadata_generation import DescriptionSuggestionDb
from src.db_models.workflow_installations import WorkflowInstallationDb
from src.models.metadata_generation import SelectionItem, StartRunRequest

RESULT_COLUMNS = ["object_type", "table_fqn", "column_name", "base_text", "proposed_text"]


def _settings():
    return SimpleNamespace(
        LLM_ENDPOINT="my-endpoint",
        DATABRICKS_CATALOG="app_ontos",
        DATABRICKS_SCHEMA="app_ontos",
        DATABRICKS_WAREHOUSE_ID="wh-1",
        DATABRICKS_VOLUME=None,
    )


def _ws_returning(rows):
    """Workspace client whose statement execution returns ``rows`` in one chunk."""
    ws = MagicMock()
    ws.statement_execution.execute_statement.return_value = SimpleNamespace(
        statement_id="st-1",
        status=SimpleNamespace(state=StatementState.SUCCEEDED, error=None),
        manifest=SimpleNamespace(
            schema=SimpleNamespace(columns=[SimpleNamespace(name=c) for c in RESULT_COLUMNS]),
            total_chunk_count=1,
        ),
        result=SimpleNamespace(data_array=rows),
    )
    return ws


def _jobs(job_run_id=111):
    jobs = MagicMock()
    jobs.run_job.return_value = job_run_id
    jobs.get_job_parameter_names.return_value = None  # definition unknown: launch
    return jobs


class SyncExecutor:
    """Runs submitted work immediately, so background ingests are deterministic."""

    def submit(self, fn, *args, **kwargs):
        fn(*args, **kwargs)


def _manager(jobs=None, ws=None):
    return MetadataGenerationManager(
        settings=_settings(),
        jobs_manager=jobs or _jobs(),
        # A bare mock lists no tables, so the table limit passes
        workspace_client_factory=lambda: ws if ws is not None else MagicMock(),
        ingest_executor=SyncExecutor(),
    )


@pytest.fixture(autouse=True)
def all_tables_writable(monkeypatch):
    """The pre-flight writability check is covered in test_metadata_generation_settings.py."""
    monkeypatch.setattr(MetadataGenerationManager, "_unwritable_tables", lambda self, fqns, **kwargs: {})


@pytest.fixture(autouse=True)
def rollback_keeps_fixture_data(db_session, monkeypatch):
    """A real Session.rollback() would discard the harness's outer transaction
    (and every row the test created); record calls instead."""
    rollback = MagicMock()
    monkeypatch.setattr(db_session, "rollback", rollback)
    return rollback


@pytest.fixture(autouse=True)
def background_session(db_session, monkeypatch):
    """Background ingests open their own session; hand them the test session."""
    session = MagicMock(wraps=db_session)
    session.close = MagicMock()
    monkeypatch.setattr("src.common.database.get_session_factory", lambda: (lambda: session))
    return session


def _created_ago(db_session, run, minutes):
    """Order runs explicitly (SQLite's second-resolution timestamps would tie)."""
    from datetime import datetime, timedelta, timezone

    db_session.query(type(run)).filter_by(id=run.id).update(
        {"created_at": datetime.now(timezone.utc) - timedelta(minutes=minutes)}, synchronize_session=False
    )
    db_session.commit()
    db_session.refresh(run)


def _backdate(db_session, run, **delta):
    from datetime import datetime, timedelta, timezone

    db_session.query(type(run)).filter_by(id=run.id).update(
        {"updated_at": datetime.now(timezone.utc) - timedelta(**delta)}, synchronize_session=False
    )
    db_session.commit()
    db_session.refresh(run)


def _request(**kwargs):
    return StartRunRequest(selection=[SelectionItem(type="schema", fqn="main.sales")], **kwargs)


@pytest.fixture
def installation(db_session):
    inst = WorkflowInstallationDb(workflow_id=WORKFLOW_ID, name="Metadata Generation", job_id=42)
    db_session.add(inst)
    db_session.flush()
    return inst


def test_selection_to_table_names_validates_depth():
    assert selection_to_table_names([
        {"type": "catalog", "fqn": "main"},
        {"type": "schema", "fqn": "main.sales"},
        {"type": "table", "fqn": "main.sales.orders"},
    ]) == ["main", "main.sales", "main.sales.orders"]
    with pytest.raises(ValueError):
        selection_to_table_names([{"type": "table", "fqn": "main.sales"}])


def test_registers_poller_handler():
    jobs = _jobs()
    manager = _manager(jobs=jobs)
    jobs.register_run_terminated_handler.assert_called_once_with(WORKFLOW_ID, manager.handle_job_terminated)
    jobs.register_poll_cycle_handler.assert_called_once_with(manager.sweep_active_runs)


def test_start_run_launches_job_with_app_schema_and_default_model(db_session, installation):
    jobs = _jobs(job_run_id=777)
    run = _manager(jobs=jobs).start_run(db_session, user_id="a@x.com", request=_request(comment_style="concise"))

    assert run.status == "running"
    assert run.job_run_id == "777"
    assert run.options["model"] == "my-endpoint"
    assert run.options["allow_data"] is False
    params = jobs.run_job.call_args.kwargs["job_parameters"]
    assert params["ontos_run_id"] == run.id
    assert params["table_names"] == "main.sales"
    assert params["output_catalog"] == "app_ontos"
    assert params["comment_style"] == "concise"
    assert params["allow_data"] == "false"
    assert jobs.run_job.call_args.kwargs["job_id"] == 42


def test_start_run_requires_installed_job(db_session):
    with pytest.raises(ConflictError):
        _manager().start_run(db_session, user_id="a@x.com", request=_request())


def test_start_run_limits_active_runs_per_user(db_session, installation):
    manager = _manager()
    manager.start_run(db_session, user_id="a@x.com", request=_request())
    with pytest.raises(ActiveRunLimitError):
        manager.start_run(db_session, user_id="a@x.com", request=_request())
    # Another user is not blocked (on objects no active run covers)
    other = StartRunRequest(selection=[SelectionItem(type="schema", fqn="main.hr")])
    manager.start_run(db_session, user_id="b@x.com", request=other)


def test_start_run_marks_run_failed_when_job_launch_fails(db_session, installation):
    jobs = _jobs()
    jobs.run_job.side_effect = RuntimeError("boom")
    manager = _manager(jobs=jobs)
    with pytest.raises(RuntimeError):
        manager.start_run(db_session, user_id="a@x.com", request=_request())
    run = manager.list_runs(db_session, "a@x.com")[0]
    assert run.status == "failed"
    assert run.error == "Failed to start the background job"


def test_refresh_ingests_on_success_with_fill_gaps_filter(db_session, installation):
    ws = _ws_returning([
        ["table", "main.sales.orders", None, None, "Customer orders."],
        ["column", "main.sales.orders", "id", None, "Order id."],
        # Already described: skipped unless regenerate_existing
        ["column", "main.sales.orders", "amount", "Total amount", "Order amount."],
        # Empty proposal: skipped
        ["column", "main.sales.orders", "note", None, "  "],
    ])
    jobs = _jobs()
    manager = _manager(jobs=jobs, ws=ws)
    run = manager.start_run(db_session, user_id="a@x.com", request=_request())

    jobs.get_job_status.return_value = {"life_cycle_state": "RUNNING", "result_state": None}
    assert manager.refresh_run(db_session, run).status == "running"

    jobs.get_job_status.return_value = {"life_cycle_state": "TERMINATED", "result_state": "SUCCESS"}
    run = manager.refresh_run(db_session, run)

    assert run.status == "completed"
    assert run.suggestion_count == 2
    suggestions = manager.list_suggestions(db_session, run.id)
    assert [(s.object_type, s.column_name) for s in suggestions] == [("table", None), ("column", "id")]
    assert all(s.status == "pending" for s in suggestions)
    sql_kwargs = ws.statement_execution.execute_statement.call_args.kwargs
    assert "`app_ontos`.`app_ontos`.`metagen_results`" in sql_kwargs["statement"]
    assert sql_kwargs["parameters"][0].value == run.id


def test_regenerate_existing_keeps_described_objects(db_session, installation):
    ws = _ws_returning([["column", "main.sales.orders", "amount", "Total amount", "Order amount."]])
    jobs = _jobs()
    manager = _manager(jobs=jobs, ws=ws)
    run = manager.start_run(db_session, user_id="a@x.com", request=_request(regenerate_existing=True))
    manager.ingest_results(db_session, run)

    [sug] = manager.list_suggestions(db_session, run.id)
    assert sug.base_text == "Total amount"
    assert sug.proposed_text == "Order amount."


def test_ingest_is_idempotent(db_session, installation):
    ws = _ws_returning([["table", "main.sales.orders", None, None, "Customer orders."]])
    manager = _manager(ws=ws)
    run = manager.start_run(db_session, user_id="a@x.com", request=_request())
    manager.ingest_results(db_session, run)
    manager.ingest_results(db_session, run)

    assert manager.count_suggestions(db_session, run.id) == 1
    assert ws.statement_execution.execute_statement.call_count == 1


def test_newer_run_supersedes_older_pending_suggestions(db_session, installation):
    rows = [["table", "main.sales.orders", None, None, "Customer orders."]]
    manager = _manager(ws=_ws_returning(rows))
    first = manager.start_run(db_session, user_id="a@x.com", request=_request())
    _created_ago(db_session, first, minutes=10)
    manager.ingest_results(db_session, first)
    second = manager.start_run(db_session, user_id="a@x.com", request=_request())
    manager.ingest_results(db_session, second)

    assert manager.counts(db_session, first.id) == {"superseded": 1}
    assert manager.counts(db_session, second.id) == {"pending": 1}


def test_poller_handler_marks_failed_and_cancelled(db_session, installation):
    jobs = _jobs(job_run_id=900)
    manager = _manager(jobs=jobs)
    run = manager.start_run(db_session, user_id="a@x.com", request=_request())
    manager.handle_job_terminated(db_session, 900, "FAILED")
    assert run.status == "failed"
    assert "FAILED" in run.error

    jobs.run_job.return_value = 901
    run2 = manager.start_run(db_session, user_id="a@x.com", request=_request())
    manager.handle_job_terminated(db_session, 901, "CANCELED")
    assert run2.status == "cancelled"
    # Unknown job runs are ignored
    manager.handle_job_terminated(db_session, 12345, "SUCCESS")


def test_ingest_failure_marks_run_failed(db_session, installation):
    ws = MagicMock()
    ws.statement_execution.execute_statement.side_effect = RuntimeError("warehouse down")
    manager = _manager(ws=ws)
    run = manager.start_run(db_session, user_id="a@x.com", request=_request())

    # Transient failures leave the successful run retryable...
    for attempt in (1, 2):
        manager.ingest_results(db_session, run)
        assert (run.status, run.ingest_attempts, run.error) == ("running", attempt, None)
        manager.ingest_results(db_session, run)  # within the retry delay: skipped
        assert run.ingest_attempts == attempt
        _backdate(db_session, run, minutes=5)
    # ...until the attempts are used up
    manager.ingest_results(db_session, run)
    assert run.status == "failed"
    assert run.error == "Failed to read the generated descriptions"
    assert ws.statement_execution.execute_statement.call_count == 3


def test_ingest_retry_succeeds_after_transient_failure(db_session, installation):
    ws = _ws_returning([["table", "main.sales.orders", None, None, "Orders."]])
    good = ws.statement_execution.execute_statement.return_value
    ws.statement_execution.execute_statement.side_effect = [RuntimeError("warehouse throttled"), good]
    jobs = _jobs()
    manager = _manager(jobs=jobs, ws=ws)
    run = manager.start_run(db_session, user_id="a@x.com", request=_request())
    jobs.get_job_status.return_value = {"life_cycle_state": "TERMINATED", "result_state": "SUCCESS"}

    manager.refresh_run(db_session, run)
    assert run.status == "running"
    manager.refresh_run(db_session, run)  # too soon: backing off
    assert ws.statement_execution.execute_statement.call_count == 1
    _backdate(db_session, run, minutes=2)
    manager.refresh_run(db_session, run)  # the next poll after the delay retries
    assert (run.status, run.suggestion_count) == ("completed", 1)


def test_cancel_and_delete_rules(db_session, installation):
    jobs = _jobs(job_run_id=555)
    manager = _manager(jobs=jobs, ws=_ws_returning([["table", "main.sales.orders", None, None, "Orders."]]))
    run = manager.start_run(db_session, user_id="a@x.com", request=_request())

    with pytest.raises(ValueError):
        manager.delete_run(db_session, run)

    manager.cancel_run(db_session, run)
    jobs.cancel_run.assert_called_once_with(555)
    assert run.status == "cancelled"
    with pytest.raises(ValueError):
        manager.cancel_run(db_session, run)

    manager.delete_run(db_session, run)
    assert manager.get_run(db_session, run.id) is None


def test_delete_blocked_while_suggestions_in_open_review(db_session, installation):
    manager = _manager(ws=_ws_returning([["table", "main.sales.orders", None, None, "Orders."]]))
    run = manager.start_run(db_session, user_id="a@x.com", request=_request())
    manager.ingest_results(db_session, run)
    sug = db_session.query(DescriptionSuggestionDb).filter_by(run_id=run.id).one()
    sug.review_request_id = "review-1"
    db_session.flush()

    with pytest.raises(ValueError, match="open review"):
        manager.delete_run(db_session, run)


def test_jobs_manager_run_terminated_handler_dispatch():
    from src.controller.jobs_manager import JobsManager

    jobs = JobsManager(db=MagicMock(), ws_client=MagicMock())
    handler = MagicMock()
    jobs.register_run_terminated_handler(WORKFLOW_ID, handler)
    db = MagicMock()

    jobs._notify_run_terminated(WORKFLOW_ID, 5, "SUCCESS", db)
    handler.assert_called_once_with(db, 5, "SUCCESS")

    # Other workflows are ignored; a failing handler is contained
    jobs._notify_run_terminated("other", 6, "SUCCESS", db)
    handler.side_effect = RuntimeError("boom")
    jobs._notify_run_terminated(WORKFLOW_ID, 7, "FAILED", db)
    db.rollback.assert_called_once()


def test_start_run_rejects_malformed_selection_before_job_check(db_session):
    bad = StartRunRequest(selection=[SelectionItem(type="table", fqn="main.sales")])
    with pytest.raises(ValueError, match="not a valid table"):
        _manager().start_run(db_session, user_id="a@x.com", request=bad)


def test_output_schema_follows_app_volume(db_session, installation):
    jobs = _jobs()
    manager = _manager(jobs=jobs)
    manager._settings.DATABRICKS_VOLUME = "/Volumes/prod_cat/prod_schema/app_files"
    manager.start_run(db_session, user_id="a@x.com", request=_request())
    params = jobs.run_job.call_args.kwargs["job_parameters"]
    assert (params["output_catalog"], params["output_schema"]) == ("prod_cat", "prod_schema")


def test_output_schema_ignores_local_volume_path(db_session, installation):
    jobs = _jobs()
    manager = _manager(jobs=jobs)
    manager._settings.DATABRICKS_VOLUME = "/tmp/ontos-volume"
    manager.start_run(db_session, user_id="a@x.com", request=_request())
    params = jobs.run_job.call_args.kwargs["job_parameters"]
    assert (params["output_catalog"], params["output_schema"]) == ("app_ontos", "app_ontos")


def _statement(state, rows=None, chunks=1, error=None):
    return SimpleNamespace(
        statement_id="st-1",
        status=SimpleNamespace(state=state, error=SimpleNamespace(message=error) if error else None),
        manifest=SimpleNamespace(
            schema=SimpleNamespace(columns=[SimpleNamespace(name=c) for c in RESULT_COLUMNS]),
            total_chunk_count=chunks,
        ),
        result=SimpleNamespace(data_array=rows or []),
    )


def test_ingest_skips_when_another_worker_holds_the_claim(db_session, installation):
    ws = _ws_returning([["table", "main.sales.orders", None, None, "Orders."]])
    manager = _manager(ws=ws)
    run = manager.start_run(db_session, user_id="a@x.com", request=_request())
    run.status = "ingesting"  # claimed by the other poller moments ago
    db_session.commit()

    assert manager.ingest_results(db_session, run) == 0
    ws.statement_execution.execute_statement.assert_not_called()
    assert run.status == "ingesting"


def test_stale_ingest_claim_is_taken_over(db_session, installation):
    from datetime import datetime, timedelta, timezone

    ws = _ws_returning([["table", "main.sales.orders", None, None, "Orders."]])
    manager = _manager(ws=ws)
    run = manager.start_run(db_session, user_id="a@x.com", request=_request())
    run.status = "ingesting"
    db_session.commit()
    db_session.query(type(run)).filter_by(id=run.id).update(
        {"updated_at": datetime.now(timezone.utc) - timedelta(hours=1)}, synchronize_session=False
    )
    db_session.commit()

    assert manager.ingest_results(db_session, run) == 1
    assert run.status == "completed"


def test_start_run_rejects_selection_overlapping_an_active_run(db_session, installation):
    manager = _manager()
    manager.start_run(db_session, user_id="a@x.com", request=_request())  # main.sales
    overlapping = StartRunRequest(selection=[SelectionItem(type="table", fqn="main.sales.orders")])
    with pytest.raises(ConflictError, match="main.sales"):
        manager.start_run(db_session, user_id="b@x.com", request=overlapping)
    # A disjoint selection is fine; a name sharing only a prefix is not an overlap
    disjoint = StartRunRequest(selection=[SelectionItem(type="schema", fqn="main.sales_eu")])
    manager.start_run(db_session, user_id="b@x.com", request=disjoint)


def test_selections_overlap():
    from src.controller.metadata_generation_manager import selections_overlap

    assert selections_overlap("main", "main.sales.orders")
    assert selections_overlap("Main.Sales", "main.sales")
    assert not selections_overlap("main.sales", "main.sales_eu")
    assert not selections_overlap("main.sales.orders", "main.sales.order")


def test_fetch_results_polls_until_succeeded(db_session, installation, monkeypatch):
    monkeypatch.setattr("src.controller.metadata_generation_manager.time.sleep", lambda s: None)
    ws = MagicMock()
    ws.statement_execution.execute_statement.return_value = _statement(StatementState.PENDING)
    ws.statement_execution.get_statement.side_effect = [
        _statement(StatementState.RUNNING),
        _statement(StatementState.SUCCEEDED, rows=[["table", "main.sales.orders", None, None, "Orders."]]),
    ]
    manager = _manager(ws=ws)
    run = manager.start_run(db_session, user_id="a@x.com", request=_request())

    assert manager.ingest_results(db_session, run) == 1
    assert ws.statement_execution.get_statement.call_count == 2


def test_fetch_results_failed_statement_fails_run(db_session, installation):
    ws = MagicMock()
    ws.statement_execution.execute_statement.return_value = _statement(StatementState.FAILED, error="TABLE_OR_VIEW_NOT_FOUND")
    manager = _manager(ws=ws)
    run = manager.start_run(db_session, user_id="a@x.com", request=_request())

    manager.ingest_results(db_session, run)
    assert (run.status, run.ingest_attempts) == ("running", 1)  # retried on the next refresh
    assert manager.count_suggestions(db_session, run.id) == 0


def test_fetch_results_reads_all_chunks(db_session, installation):
    ws = MagicMock()
    ws.statement_execution.execute_statement.return_value = _statement(
        StatementState.SUCCEEDED, rows=[["table", "main.sales.orders", None, None, "Orders."]], chunks=3,
    )
    ws.statement_execution.get_statement_result_chunk_n.side_effect = [
        SimpleNamespace(data_array=[["column", "main.sales.orders", "id", None, "Order id."]]),
        SimpleNamespace(data_array=[["column", "main.sales.orders", "amount", None, "Amount."]]),
    ]
    manager = _manager(ws=ws)
    run = manager.start_run(db_session, user_id="a@x.com", request=_request())

    assert manager.ingest_results(db_session, run) == 3
    indexes = [c.args[1] for c in ws.statement_execution.get_statement_result_chunk_n.call_args_list]
    assert indexes == [1, 2]


def test_refresh_fails_skipped_run_with_life_cycle_state(db_session, installation):
    jobs = _jobs()
    manager = _manager(jobs=jobs)
    run = manager.start_run(db_session, user_id="a@x.com", request=_request())
    jobs.get_job_status.return_value = {"life_cycle_state": "SKIPPED", "result_state": None}

    manager.refresh_run(db_session, run)
    assert run.status == "failed"
    assert "SKIPPED" in run.error


def test_store_failure_rolls_back_partial_suggestions(db_session, installation, monkeypatch):
    ws = _ws_returning([
        ["table", "main.sales.orders", None, None, "Orders."],
        ["column", "main.sales.orders", "id", None, "Order id."],
    ])
    manager = _manager(ws=ws)
    run = manager.start_run(db_session, user_id="a@x.com", request=_request())
    # Row left behind by an interrupted earlier attempt
    db_session.add(DescriptionSuggestionDb(
        run_id=run.id, object_type="table", table_fqn="main.sales.orders", proposed_text="Earlier.",
    ))
    db_session.commit()

    def boom(*args, **kwargs):
        raise RuntimeError("db hiccup")

    # Fails after the old rows were deleted and the new ones added
    monkeypatch.setattr(
        "src.controller.metadata_generation_manager.metagen_suggestions_repo.supersede_pending_for_targets", boom,
    )
    assert manager.ingest_results(db_session, run) == 0

    assert (run.status, run.ingest_attempts) == ("running", 1)
    rows = manager.list_suggestions(db_session, run.id)
    assert [r.proposed_text for r in rows] == ["Earlier."]  # nothing half-written, nothing lost
    assert manager.list_runs(db_session, "a@x.com")[0].id == run.id  # session still usable


def test_start_run_recovers_abandoned_ingest_before_applying_limits(db_session, installation):
    from datetime import datetime, timedelta, timezone

    ws = _ws_returning([["table", "main.sales.orders", None, None, "Orders."]])
    jobs = _jobs()
    manager = _manager(jobs=jobs, ws=ws)
    stuck = manager.start_run(db_session, user_id="a@x.com", request=_request())
    # The worker that claimed the ingest died an hour ago; the poller already notified
    stuck.status = "ingesting"
    db_session.commit()
    db_session.query(type(stuck)).filter_by(id=stuck.id).update(
        {"updated_at": datetime.now(timezone.utc) - timedelta(hours=1)}, synchronize_session=False
    )
    db_session.commit()
    jobs.get_job_status.return_value = {"life_cycle_state": "TERMINATED", "result_state": "SUCCESS"}

    # Same user, same objects: neither the per-user limit nor the overlap check blocks
    manager.start_run(db_session, user_id="a@x.com", request=_request())
    db_session.refresh(stuck)
    assert stuck.status == "completed"
    assert stuck.suggestion_count == 1


def test_ingest_reads_results_from_app_volume_schema(db_session, installation):
    ws = _ws_returning([["table", "main.sales.orders", None, None, "Orders."]])
    manager = _manager(ws=ws)
    manager._settings.DATABRICKS_VOLUME = "/Volumes/prod_cat/prod_schema/app_files"
    run = manager.start_run(db_session, user_id="a@x.com", request=_request())
    manager.ingest_results(db_session, run)

    statement = ws.statement_execution.execute_statement.call_args.kwargs["statement"]
    assert "`prod_cat`.`prod_schema`.`metagen_results`" in statement


def test_refresh_can_defer_ingest(db_session, installation):
    ws = _ws_returning([["table", "main.sales.orders", None, None, "Orders."]])
    jobs = _jobs()
    manager = _manager(jobs=jobs, ws=ws)
    run = manager.start_run(db_session, user_id="a@x.com", request=_request())
    jobs.get_job_status.return_value = {"life_cycle_state": "TERMINATED", "result_state": "SUCCESS"}
    deferred = []

    manager.refresh_run(db_session, run, defer_ingest=deferred.append)
    assert deferred == [run.id]
    assert run.status == "running"
    ws.statement_execution.execute_statement.assert_not_called()

    # Failures are still finished inline
    jobs.get_job_status.return_value = {"life_cycle_state": "TERMINATED", "result_state": "FAILED"}
    manager.refresh_run(db_session, run, defer_ingest=deferred.append)
    assert run.status == "failed" and deferred == [run.id]


def test_refresh_skips_jobs_api_while_ingest_claim_is_fresh(db_session, installation):
    jobs = _jobs()
    manager = _manager(jobs=jobs)
    run = manager.start_run(db_session, user_id="a@x.com", request=_request())
    run.status = "ingesting"
    db_session.commit()

    manager.refresh_run(db_session, run)
    jobs.get_job_status.assert_not_called()


def test_ingest_run_by_id_uses_its_own_session(db_session, installation, monkeypatch):
    ws = _ws_returning([["table", "main.sales.orders", None, None, "Orders."]])
    manager = _manager(ws=ws)
    run = manager.start_run(db_session, user_id="a@x.com", request=_request())
    session = MagicMock(wraps=db_session)
    session.close = MagicMock()
    monkeypatch.setattr("src.common.database.get_session_factory", lambda: (lambda: session))

    manager.ingest_run_by_id(run.id)
    assert run.status == "completed"
    session.close.assert_called_once()


def test_suggestions_in_review_are_not_superseded(db_session, installation):
    rows = [["table", "main.sales.orders", None, None, "Orders."]]
    manager = _manager(ws=_ws_returning(rows))
    first = manager.start_run(db_session, user_id="a@x.com", request=_request())
    manager.ingest_results(db_session, first)
    db_session.query(DescriptionSuggestionDb).filter_by(run_id=first.id).update({"review_request_id": "r1"})
    db_session.commit()

    second = manager.start_run(db_session, user_id="a@x.com", request=_request())
    manager.ingest_results(db_session, second)
    assert manager.counts(db_session, first.id) == {"pending": 1}


def test_supersede_matches_columns_exactly(db_session, installation):
    first_rows = [["column", "main.sales.orders", "id", None, "Order id."]]
    manager = _manager(ws=_ws_returning(first_rows))
    first = manager.start_run(db_session, user_id="a@x.com", request=_request())
    manager.ingest_results(db_session, first)

    manager._ws_factory = lambda: _ws_returning([["column", "main.sales.orders", "amount", None, "Amount."]])
    second = manager.start_run(db_session, user_id="a@x.com", request=_request())
    manager.ingest_results(db_session, second)
    assert manager.counts(db_session, first.id) == {"pending": 1}


def test_refresh_polls_jobs_api_when_ingest_claim_is_stale(db_session, installation):
    from datetime import datetime, timedelta, timezone

    ws = _ws_returning([["table", "main.sales.orders", None, None, "Orders."]])
    jobs = _jobs()
    manager = _manager(jobs=jobs, ws=ws)
    run = manager.start_run(db_session, user_id="a@x.com", request=_request())
    run.status = "ingesting"
    db_session.commit()
    db_session.query(type(run)).filter_by(id=run.id).update(
        {"updated_at": datetime.now(timezone.utc) - timedelta(hours=1)}, synchronize_session=False
    )
    db_session.commit()
    db_session.refresh(run)
    jobs.get_job_status.return_value = {"life_cycle_state": "TERMINATED", "result_state": "SUCCESS"}

    manager.refresh_run(db_session, run)
    jobs.get_job_status.assert_called_once()
    assert run.status == "completed"


@pytest.mark.parametrize("case", ["ingest_raises", "run_missing"])
def test_ingest_run_by_id_always_closes_its_session(db_session, installation, monkeypatch, case):
    manager = _manager()
    run = manager.start_run(db_session, user_id="a@x.com", request=_request())
    session = MagicMock(wraps=db_session)
    session.close = MagicMock()
    monkeypatch.setattr("src.common.database.get_session_factory", lambda: (lambda: session))
    ingest = MagicMock(side_effect=RuntimeError("boom"))
    monkeypatch.setattr(manager, "ingest_results", ingest)

    manager.ingest_run_by_id(run.id if case == "ingest_raises" else "missing")  # never raises
    session.close.assert_called_once()
    assert ingest.called is (case == "ingest_raises")


def test_start_run_defers_finished_runs_and_does_not_count_them(db_session, installation):
    ws = _ws_returning([["table", "main.sales.orders", None, None, "Orders."]])
    jobs = _jobs()
    manager = _manager(jobs=jobs, ws=ws)
    finished = manager.start_run(db_session, user_id="a@x.com", request=_request())
    jobs.get_job_status.return_value = {"life_cycle_state": "TERMINATED", "result_state": "SUCCESS"}
    deferred = []

    # Same user, same objects: the finished run doesn't block, and isn't ingested inline
    manager.start_run(db_session, user_id="a@x.com", request=_request(), defer_ingest=deferred.append)
    assert deferred == [finished.id]
    ws.statement_execution.execute_statement.assert_not_called()


def test_orphaned_pending_run_is_failed_after_timeout(db_session, installation):
    from datetime import datetime, timedelta, timezone

    jobs = _jobs()
    jobs.run_job.side_effect = SystemExit  # process died between commit and launch
    manager = _manager(jobs=jobs)
    with pytest.raises(SystemExit):
        manager.start_run(db_session, user_id="a@x.com", request=_request())
    orphan = manager.list_runs(db_session, "a@x.com")[0]
    assert (orphan.status, orphan.job_run_id) == ("pending", None)

    # Fresh: still pending (the launch may be in progress)
    manager.refresh_run(db_session, orphan)
    assert orphan.status == "pending"

    db_session.query(type(orphan)).filter_by(id=orphan.id).update(
        {"created_at": datetime.now(timezone.utc) - timedelta(hours=1)}, synchronize_session=False
    )
    db_session.commit()
    db_session.refresh(orphan)
    jobs.run_job.side_effect = None
    jobs.run_job.return_value = 5
    # The next start finds and fails the orphan instead of being blocked by it
    manager.start_run(db_session, user_id="a@x.com", request=_request())
    db_session.refresh(orphan)
    assert orphan.status == "failed"
    assert orphan.error == "The background job was never started"


def test_failed_refresh_rolls_back_before_start_continues(db_session, installation, monkeypatch):
    manager = _manager()
    manager.start_run(db_session, user_id="a@x.com", request=_request())
    # Not wrapping the real rollback: under the test harness it would undo the fixture's data
    rollback = MagicMock()
    monkeypatch.setattr(db_session, "rollback", rollback)
    monkeypatch.setattr(manager, "refresh_run", MagicMock(side_effect=RuntimeError("jobs api down")))

    other = StartRunRequest(selection=[SelectionItem(type="schema", fqn="main.hr")])
    manager.start_run(db_session, user_id="b@x.com", request=other)
    rollback.assert_called_once()


def test_poll_cycle_sweep_retries_a_failed_ingest(db_session, installation):
    ws = _ws_returning([["table", "main.sales.orders", None, None, "Orders."]])
    good = ws.statement_execution.execute_statement.return_value
    ws.statement_execution.execute_statement.side_effect = [RuntimeError("warehouse throttled"), good]
    jobs = _jobs(job_run_id=321)
    manager = _manager(jobs=jobs, ws=ws)
    run = manager.start_run(db_session, user_id="a@x.com", request=_request())
    jobs.get_job_status.return_value = {"life_cycle_state": "TERMINATED", "result_state": "SUCCESS"}

    manager.handle_job_terminated(db_session, 321, "SUCCESS")  # the one-off notification fails
    db_session.refresh(run)
    assert run.status == "running"
    _backdate(db_session, run, minutes=2)
    sweep = jobs.register_poll_cycle_handler.call_args.args[0]
    sweep(db_session)  # next poller cycle, past the retry delay
    db_session.refresh(run)
    assert run.status == "completed"


def test_poller_success_ingests_on_the_executor_not_inline(db_session, installation):
    submitted = []
    ws = _ws_returning([["table", "main.sales.orders", None, None, "Orders."]])
    jobs = _jobs(job_run_id=444)
    manager = MetadataGenerationManager(
        settings=_settings(), jobs_manager=jobs, workspace_client_factory=lambda: ws,
        ingest_executor=SimpleNamespace(submit=lambda fn, *a: submitted.append((fn, a))),
    )
    run = manager.start_run(db_session, user_id="a@x.com", request=_request())

    manager.handle_job_terminated(db_session, 444, "SUCCESS")
    assert submitted == [(manager._run_queued_ingest, (run.id,))]
    ws.statement_execution.execute_statement.assert_not_called()


def test_cancelled_run_stays_cancelled_when_job_later_terminates(db_session, installation):
    ws = _ws_returning([["table", "main.sales.orders", None, None, "Orders."]])
    jobs = _jobs(job_run_id=900)
    manager = _manager(jobs=jobs, ws=ws)
    run = manager.start_run(db_session, user_id="a@x.com", request=_request())
    manager.cancel_run(db_session, run)

    for state in ("SUCCESS", "FAILED"):
        manager.handle_job_terminated(db_session, 900, state)
        assert run.status == "cancelled"
    ws.statement_execution.execute_statement.assert_not_called()


def test_retry_backoff_doubles_per_attempt(db_session, installation):
    jobs = _jobs()
    manager = _manager(jobs=jobs)
    run = manager.start_run(db_session, user_id="a@x.com", request=_request())
    jobs.get_job_status.return_value = {"life_cycle_state": "RUNNING", "result_state": None}
    run.ingest_attempts = 2  # second retry waits 2 minutes
    db_session.commit()

    _backdate(db_session, run, seconds=90)
    manager.refresh_run(db_session, run)
    jobs.get_job_status.assert_not_called()
    _backdate(db_session, run, seconds=150)
    manager.refresh_run(db_session, run)
    jobs.get_job_status.assert_called_once()


def test_fetch_results_pages_through_large_runs(db_session, installation, monkeypatch):
    monkeypatch.setattr("src.controller.metadata_generation_manager.RESULTS_PAGE_SIZE", 2)
    ws = MagicMock()
    ws.statement_execution.execute_statement.side_effect = [
        _statement(StatementState.SUCCEEDED, rows=[
            ["table", "main.sales.orders", None, None, "Orders."],
            ["column", "main.sales.orders", "amount", None, "Amount."],
        ]),
        _statement(StatementState.SUCCEEDED, rows=[["column", "main.sales.orders", "id", None, "Order id."]]),
    ]
    manager = _manager(ws=ws)
    run = manager.start_run(db_session, user_id="a@x.com", request=_request())

    assert manager.ingest_results(db_session, run) == 3
    statements = [c.kwargs["statement"] for c in ws.statement_execution.execute_statement.call_args_list]
    assert "ORDER BY table_fqn, column_name NULLS FIRST LIMIT 2 OFFSET 0" in statements[0]
    assert statements[1].endswith("LIMIT 2 OFFSET 2")


def test_list_and_count_suggestions_filter_by_status(db_session, installation):
    rows = [
        ["table", "main.sales.orders", None, None, "Orders."],
        ["column", "main.sales.orders", "id", None, "Order id."],
    ]
    manager = _manager(ws=_ws_returning(rows))
    run = manager.start_run(db_session, user_id="a@x.com", request=_request())
    manager.ingest_results(db_session, run)
    db_session.query(DescriptionSuggestionDb).filter_by(run_id=run.id, column_name="id").update({"status": "rejected"})
    db_session.commit()

    pending = manager.list_suggestions(db_session, run.id, status="pending")
    assert [s.column_name for s in pending] == [None]
    assert manager.count_suggestions(db_session, run.id, status="pending") == 1
    assert manager.count_suggestions(db_session, run.id, status="rejected") == 1
    assert manager.count_suggestions(db_session, run.id) == 2
    assert [s.column_name for s in manager.list_suggestions(db_session, run.id, limit=1, skip=1)] == ["id"]


def test_failed_commit_is_rolled_back_and_counted(db_session, installation, monkeypatch):
    ws = _ws_returning([["table", "main.sales.orders", None, None, "Orders."]])
    manager = _manager(ws=ws)
    run = manager.start_run(db_session, user_id="a@x.com", request=_request())
    real_commit = db_session.commit
    calls = {"n": 0}

    def flaky_commit():
        calls["n"] += 1
        if calls["n"] == 2:  # the commit after storing the suggestions
            raise RuntimeError("connection reset")
        return real_commit()

    monkeypatch.setattr(db_session, "commit", flaky_commit)
    monkeypatch.setattr(db_session, "refresh", MagicMock())

    manager.ingest_results(db_session, run)
    db_session.rollback.assert_called_once()
    assert (run.status, run.ingest_attempts) == ("running", 1)


def test_run_with_unavailable_job_status_is_given_up_only_after_a_while(db_session, installation):
    from datetime import datetime, timedelta, timezone

    jobs = _jobs()
    manager = _manager(jobs=jobs)
    run = manager.start_run(db_session, user_id="a@x.com", request=_request())
    run.started_at = datetime.now(timezone.utc) - timedelta(hours=3)
    db_session.commit()
    jobs.get_job_status.return_value = None  # purged run id / Jobs API failing

    manager.refresh_run(db_session, run)
    assert run.status == "running" and run.status_unavailable_since is not None  # could be a blip

    # A successful read in between resets the clock
    jobs.get_job_status.return_value = {"life_cycle_state": "RUNNING", "result_state": None}
    manager.refresh_run(db_session, run)
    assert run.status_unavailable_since is None

    jobs.get_job_status.return_value = None
    manager.refresh_run(db_session, run)
    run.status_unavailable_since = datetime.now(timezone.utc) - timedelta(minutes=45)
    db_session.commit()
    manager.refresh_run(db_session, run)
    assert run.status == "failed"
    assert run.error == "The background job's status is unavailable"


def test_unavailable_status_after_job_success_keeps_ingesting(db_session, installation):
    from datetime import datetime, timedelta, timezone

    ws = _ws_returning([["table", "main.sales.orders", None, None, "Orders."]])
    jobs = _jobs()
    manager = _manager(jobs=jobs, ws=ws)
    run = manager.start_run(db_session, user_id="a@x.com", request=_request())
    run.ingest_attempts = 1  # the job succeeded; one ingest attempt failed
    run.started_at = datetime.now(timezone.utc) - timedelta(hours=3)
    db_session.commit()
    _backdate(db_session, run, minutes=5)  # past the retry delay
    jobs.get_job_status.return_value = None

    manager.refresh_run(db_session, run)
    assert (run.status, run.suggestion_count) == ("completed", 1)


def test_unavailable_status_after_job_success_defers_from_requests(db_session, installation):
    ws = _ws_returning([["table", "main.sales.orders", None, None, "Orders."]])
    jobs = _jobs()
    manager = _manager(jobs=jobs, ws=ws)
    run = manager.start_run(db_session, user_id="a@x.com", request=_request())
    run.ingest_attempts = 1
    db_session.commit()
    _backdate(db_session, run, minutes=5)
    jobs.get_job_status.return_value = None
    deferred = []

    manager.refresh_run(db_session, run, defer_ingest=deferred.append)
    assert deferred == [run.id]
    assert run.status == "running"
    ws.statement_execution.execute_statement.assert_not_called()


def test_unavailable_status_on_stale_ingest_claim_ingests(db_session, installation):
    ws = _ws_returning([["table", "main.sales.orders", None, None, "Orders."]])
    jobs = _jobs()
    manager = _manager(jobs=jobs, ws=ws)
    run = manager.start_run(db_session, user_id="a@x.com", request=_request())
    run.status = "ingesting"  # claim abandoned, no failed attempt recorded
    db_session.commit()
    _backdate(db_session, run, hours=1)
    jobs.get_job_status.return_value = None

    manager.refresh_run(db_session, run)
    assert (run.status, run.suggestion_count) == ("completed", 1)
    assert run.status_unavailable_since is None


@pytest.mark.parametrize("started_ago,unavailable_for,expected", [
    ({"hours": 3}, {"minutes": 5}, "running"),       # brief outage on an old run
    ({"minutes": 30}, {"minutes": 45}, "running"),   # the job may still be running
    ({"hours": 3}, {"minutes": 45}, "failed"),
    (None, {"minutes": 45}, "failed"),               # no started_at: created_at decides
])
def test_give_up_needs_both_an_old_run_and_a_sustained_outage(
    db_session, installation, started_ago, unavailable_for, expected,
):
    from datetime import datetime, timedelta, timezone

    jobs = _jobs()
    manager = _manager(jobs=jobs)
    run = manager.start_run(db_session, user_id="a@x.com", request=_request())
    now = datetime.now(timezone.utc)
    if started_ago is None:
        run.started_at = None
        db_session.query(type(run)).filter_by(id=run.id).update(
            {"created_at": now - timedelta(hours=3)}, synchronize_session=False
        )
    else:
        run.started_at = now - timedelta(**started_ago)
    run.status_unavailable_since = now - timedelta(**unavailable_for)
    db_session.commit()
    db_session.refresh(run)
    jobs.get_job_status.return_value = None

    manager.refresh_run(db_session, run)
    assert run.status == expected


def test_deferrer_queues_each_run_once_until_it_finished():
    scheduled = []
    manager = _manager()
    defer = manager.make_deferrer(lambda fn, rid: scheduled.append((fn, rid)))

    defer("run-1")
    defer("run-1")  # poller, sweep and page polls racing
    defer("run-2")
    assert [rid for _, rid in scheduled] == ["run-1", "run-2"]

    fn, rid = scheduled[0]
    manager.ingest_run_by_id = MagicMock()
    fn(rid)  # the queued ingest ran
    defer("run-1")
    assert [rid for _, rid in scheduled] == ["run-1", "run-2", "run-1"]


def test_deferrer_releases_the_run_when_scheduling_fails():
    manager = _manager()

    def broken(fn, rid):
        raise RuntimeError("executor shut down")

    with pytest.raises(RuntimeError):
        manager.make_deferrer(broken)("run-1")
    scheduled = []
    manager.make_deferrer(lambda fn, rid: scheduled.append(rid))("run-1")
    assert scheduled == ["run-1"]


def test_cancel_is_rejected_while_results_are_loading(db_session, installation):
    jobs = _jobs()
    manager = _manager(jobs=jobs)
    run = manager.start_run(db_session, user_id="a@x.com", request=_request())
    run.status = "ingesting"
    db_session.commit()

    with pytest.raises(ValueError, match="being loaded"):
        manager.cancel_run(db_session, run)
    jobs.cancel_run.assert_not_called()


def test_queued_marker_expires_when_its_task_never_ran(monkeypatch):
    clock = {"now": 1000.0}
    monkeypatch.setattr("src.controller.metadata_generation_manager.time.monotonic", lambda: clock["now"])
    scheduled = []
    manager = _manager()
    defer = manager.make_deferrer(lambda fn, rid: scheduled.append(rid))

    defer("run-1")  # the request that deferred it then failed: the task never runs
    defer("run-1")
    assert scheduled == ["run-1"]
    clock["now"] += 16 * 60
    defer("run-1")
    assert scheduled == ["run-1", "run-1"]


def test_late_ingest_of_an_older_run_does_not_supersede_a_newer_run(db_session, installation):
    rows = [
        ["table", "main.sales.orders", None, None, "Orders."],
        ["column", "main.sales.orders", "id", None, "Order id."],
    ]
    manager = _manager(ws=_ws_returning(rows))
    older = manager.start_run(db_session, user_id="a@x.com", request=_request())
    _created_ago(db_session, older, minutes=10)
    older.status = "completed"  # its job finished; the ingest is still queued
    db_session.commit()
    newer = manager.start_run(
        db_session, user_id="a@x.com",
        request=StartRunRequest(selection=[SelectionItem(type="table", fqn="main.sales.orders")]),
    )
    manager._ws_factory = lambda: _ws_returning([["table", "main.sales.orders", None, None, "Newer orders."]])
    manager.ingest_results(db_session, newer)

    older.status = "running"
    db_session.commit()
    manager._ws_factory = lambda: _ws_returning(rows)
    manager.ingest_results(db_session, older)  # finishes last

    assert manager.counts(db_session, newer.id) == {"pending": 1}
    older_rows = {s.column_name: s.status for s in manager.list_suggestions(db_session, older.id)}
    assert older_rows == {None: "superseded", "id": "pending"}  # only what the newer run covered


def test_long_ingest_heartbeats_after_each_page(db_session, installation, monkeypatch):
    monkeypatch.setattr("src.controller.metadata_generation_manager.RESULTS_PAGE_SIZE", 1)
    ws = MagicMock()
    ws.statement_execution.execute_statement.side_effect = [
        _statement(StatementState.SUCCEEDED, rows=[["table", "main.sales.orders", None, None, "Orders."]]),
        _statement(StatementState.SUCCEEDED, rows=[]),
    ]
    manager = _manager(ws=ws)
    run = manager.start_run(db_session, user_id="a@x.com", request=_request())
    beats = []
    real_heartbeat = manager._heartbeat
    monkeypatch.setattr(manager, "_heartbeat", lambda db, r: (beats.append(r.status), real_heartbeat(db, r)))

    assert manager.ingest_results(db_session, run) == 1
    assert beats == ["ingesting", "ingesting"]


def test_heartbeat_refreshes_claim_and_queued_marker(db_session, installation, monkeypatch):
    clock = {"now": 1000.0}
    monkeypatch.setattr("src.controller.metadata_generation_manager.time.monotonic", lambda: clock["now"])
    manager = _manager()
    run = manager.start_run(db_session, user_id="a@x.com", request=_request())
    run.status = "ingesting"
    db_session.commit()
    _backdate(db_session, run, minutes=14)
    manager._queued_ingests[run.id] = 900.0

    manager._heartbeat(db_session, run)
    db_session.refresh(run)
    assert not manager._is_stale(run.updated_at)
    assert manager._queued_ingests[run.id] == 1000.0


def test_start_run_keeps_the_auto_submit_reviewer(db_session, installation):
    run = _manager().start_run(
        db_session, user_id="a@x.com", request=_request(auto_submit=True, reviewer_email="steward@x.com"),
    )
    assert run.options["auto_submit"] is True
    assert run.options["reviewer_email"] == "steward@x.com"


def test_start_run_rejects_auto_submitting_to_yourself(db_session, installation):
    jobs = _jobs()
    with pytest.raises(ValueError, match="your own"):
        _manager(jobs=jobs).start_run(
            db_session, user_id="a@x.com", request=_request(auto_submit=True, reviewer_email="A@x.com"),
        )
    jobs.run_job.assert_not_called()
