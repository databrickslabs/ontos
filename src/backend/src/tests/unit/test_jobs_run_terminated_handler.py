"""The job poller must hand finished runs to the registered per-workflow handler.

Features that keep their own run records (Metadata Generation) rely on this
backstop to finish runs nobody has open in the UI. Covers TERMINATED as well
as SKIPPED / INTERNAL_ERROR (which have no result state), and that running or
already-notified runs are not handed over.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from databricks.sdk.service.jobs import RunLifeCycleState, RunResultState

from src.controller.jobs_manager import JobsManager


def _poll_once(life_cycle_state, result_state, *, notified_at=None, cycle_handlers=()):
    mgr = JobsManager(db=MagicMock(), ws_client=MagicMock())
    handler = MagicMock()
    mgr.register_run_terminated_handler("metagen_generate", handler)
    for cycle_handler in cycle_handlers:
        mgr.register_poll_cycle_handler(cycle_handler)

    installation = SimpleNamespace(
        id="inst-1", workflow_id="metagen_generate", name="Metadata Generation", job_id=42, last_polled_at=None,
    )
    run = SimpleNamespace(
        run_id=777,
        run_name="metagen",
        start_time=0,
        end_time=0,
        state=SimpleNamespace(life_cycle_state=life_cycle_state, result_state=result_state, state_message=""),
    )
    mgr._client.jobs.list_runs.return_value = [run]
    session = MagicMock()

    def fake_get_db():
        yield session

    def stop_after_first(timeout=None):
        mgr._stop_polling.set()
        return True

    with patch("src.common.database.get_db", fake_get_db), \
         patch.object(mgr._stop_polling, "wait", side_effect=stop_after_first), \
         patch("src.controller.jobs_manager.workflow_installation_repo") as inst_repo, \
         patch("src.controller.jobs_manager.workflow_job_run_repo") as run_repo, \
         patch.object(mgr, "_create_job_failure_notification"), \
         patch.object(mgr, "_create_job_success_notification"):
        inst_repo.get_all_installed.return_value = [installation]
        run_repo.upsert_run.return_value = SimpleNamespace(notified_at=notified_at)
        mgr._poll_job_states(interval_seconds=0)
    return handler, session


def test_terminated_success_run_is_handed_to_handler():
    handler, session = _poll_once(RunLifeCycleState.TERMINATED, RunResultState.SUCCESS)
    handler.assert_called_once_with(session, 777, "SUCCESS")


@pytest.mark.parametrize("state", [RunLifeCycleState.SKIPPED, RunLifeCycleState.INTERNAL_ERROR])
def test_runs_without_result_state_pass_their_life_cycle_state(state):
    handler, session = _poll_once(state, None)
    handler.assert_called_once_with(session, 777, state.value)


def test_running_run_is_not_handed_over():
    handler, _ = _poll_once(RunLifeCycleState.RUNNING, None)
    handler.assert_not_called()


def test_already_notified_run_is_not_handed_over_again():
    handler, _ = _poll_once(RunLifeCycleState.TERMINATED, RunResultState.SUCCESS, notified_at="2026-10-24")
    handler.assert_not_called()


def test_poll_cycle_handlers_run_every_cycle_and_failures_are_contained():
    failing = MagicMock(side_effect=RuntimeError("boom"))
    sweep = MagicMock()
    _, session = _poll_once(RunLifeCycleState.RUNNING, None, cycle_handlers=(failing, sweep))
    failing.assert_called_once_with(session)
    sweep.assert_called_once_with(session)  # still runs after the failing one
    session.rollback.assert_called()


def _poll_with_sessions(installations, cycle_handler, *, runs=(), run_handler=None):
    """Poll once with a distinct session per get_db() call and a shared call log."""
    mgr = JobsManager(db=MagicMock(), ws_client=MagicMock())
    mgr.register_poll_cycle_handler(cycle_handler)
    if run_handler is not None:
        mgr.register_run_terminated_handler("w", run_handler)
    mgr._client.jobs.list_runs.return_value = list(runs)
    log, sessions = [], []

    def fake_get_db():
        session = MagicMock(name=f"session{len(sessions)}")
        session.commit.side_effect = lambda: log.append(("commit", session))
        session.close.side_effect = lambda: log.append(("close", session))
        sessions.append(session)
        yield session

    def stop_after_first(timeout=None):
        mgr._stop_polling.set()
        return True

    with patch("src.common.database.get_db", fake_get_db), \
         patch.object(mgr._stop_polling, "wait", side_effect=stop_after_first), \
         patch("src.controller.jobs_manager.workflow_installation_repo") as inst_repo, \
         patch("src.controller.jobs_manager.workflow_job_run_repo") as run_repo, \
         patch.object(mgr, "_create_job_failure_notification"), \
         patch.object(mgr, "_create_job_success_notification"):
        inst_repo.get_all_installed.return_value = installations
        run_repo.upsert_run.return_value = SimpleNamespace(notified_at=None)
        mgr._poll_job_states(interval_seconds=0)
    return log, sessions


def test_poll_cycle_handlers_use_their_own_session_after_the_commit():
    log = []
    handler = MagicMock(side_effect=lambda db: log.append(("handler", db)))
    installation = SimpleNamespace(id="i", workflow_id="w", name="w", job_id=1, last_polled_at=None)
    events, sessions = _poll_with_sessions([installation], handler)

    poll_session, handler_session = sessions
    handler.assert_called_once_with(handler_session)
    order = [name for name, s in events if s is poll_session]
    assert order == ["commit", "close"]  # poller finished before the handler started
    assert ("close", handler_session) in events


def test_poll_cycle_handlers_skip_when_nothing_is_installed():
    handler = MagicMock()
    _, sessions = _poll_with_sessions([], handler)
    handler.assert_not_called()
    assert len(sessions) == 1


def test_failure_opening_the_handler_session_does_not_end_polling():
    mgr = JobsManager(db=MagicMock(), ws_client=MagicMock())
    mgr.register_poll_cycle_handler(MagicMock())
    mgr._client.jobs.list_runs.return_value = []
    installation = SimpleNamespace(id="i", workflow_id="w", name="w", job_id=1, last_polled_at=None)
    calls = {"n": 0}

    def fake_get_db():
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("db unreachable")
        yield MagicMock()

    cycles = {"n": 0}

    def wait(timeout=None):
        cycles["n"] += 1
        if cycles["n"] >= 2:
            mgr._stop_polling.set()
        return True

    with patch("src.common.database.get_db", fake_get_db), \
         patch.object(mgr._stop_polling, "wait", side_effect=wait), \
         patch("src.controller.jobs_manager.workflow_installation_repo") as inst_repo:
        inst_repo.get_all_installed.return_value = [installation]
        mgr._poll_job_states(interval_seconds=0)
    assert cycles["n"] == 2  # the loop survived the failure and polled again


def test_run_terminated_handlers_get_their_own_session_after_the_commit():
    run_handler = MagicMock()
    installation = SimpleNamespace(id="i", workflow_id="w", name="w", job_id=1, last_polled_at=None)
    run = SimpleNamespace(
        run_id=9, run_name="r", start_time=0, end_time=0,
        state=SimpleNamespace(life_cycle_state=RunLifeCycleState.TERMINATED,
                              result_state=RunResultState.SUCCESS, state_message=""),
    )
    events, sessions = _poll_with_sessions([installation], MagicMock(), runs=[run], run_handler=run_handler)

    poll_session, handler_session = sessions
    run_handler.assert_called_once_with(handler_session, 9, "SUCCESS")
    assert [name for name, s in events if s is poll_session] == ["commit", "close"]
