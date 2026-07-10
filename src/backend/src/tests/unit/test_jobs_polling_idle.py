"""Regression test: job-polling thread must not touch the DB when there are
zero installed workflows.

The background poller opened a fresh DB session every interval and queried
``workflow_installation_repo.get_all_installed`` unconditionally — even with no
workflows installed. On Databricks Apps that keeps Lakebase compute permanently
warm (the reported "compute always active"), because a query every 5 minutes
never lets the instance reach its idle window. The poller now caches a presence
flag and skips the DB entirely once it has confirmed zero installations, so a
workflow-free deployment lets Lakebase idle down.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.controller.jobs_manager import JobsManager


def _make_manager() -> JobsManager:
    return JobsManager(db=MagicMock(), ws_client=MagicMock())


def test_poll_skips_db_after_confirming_zero_installations():
    mgr = _make_manager()

    # get_db yields a session; get_all_installed reports zero workflows.
    fake_session = MagicMock()
    get_db_calls = {"n": 0}

    def fake_get_db():
        get_db_calls["n"] += 1
        yield fake_session

    # Stop after the loop has run enough cycles to prove the skip path is taken.
    cycle = {"n": 0}

    def counting_wait(timeout=None):
        cycle["n"] += 1
        # Cycle 1: DB checked (zero) → flag set False.
        # Cycles 2-3: must be skipped (no DB session opened).
        if cycle["n"] >= 3:
            mgr._stop_polling.set()
        return True

    with patch("src.common.database.get_db", fake_get_db), \
         patch.object(mgr._stop_polling, "wait", side_effect=counting_wait), \
         patch(
             "src.controller.jobs_manager.workflow_installation_repo.get_all_installed",
             return_value=[],
         ) as mock_get_all:
        mgr._poll_job_states(interval_seconds=0)

    # DB session opened exactly once (cycle 1); cycles 2-3 short-circuited.
    assert get_db_calls["n"] == 1, f"expected 1 DB session, got {get_db_calls['n']}"
    assert mock_get_all.call_count == 1
    assert mgr._has_installations is False


def test_unknown_flag_triggers_db_recheck():
    """After install resets the flag to None, the next cycle must query the DB
    again (so a newly installed workflow is actually picked up)."""
    mgr = _make_manager()
    mgr._has_installations = None  # state install_workflow leaves behind

    fake_session = MagicMock()

    def fake_get_db():
        yield fake_session

    def stop_after_first(timeout=None):
        mgr._stop_polling.set()
        return True

    with patch("src.common.database.get_db", fake_get_db), \
         patch.object(mgr._stop_polling, "wait", side_effect=stop_after_first), \
         patch(
             "src.controller.jobs_manager.workflow_installation_repo.get_all_installed",
             return_value=[],
         ) as mock_get_all:
        mgr._poll_job_states(interval_seconds=0)

    # None must NOT short-circuit: the DB is re-checked.
    assert mock_get_all.call_count == 1
    assert mgr._has_installations is False


def test_nonzero_installations_keeps_polling_db():
    """When workflows exist, the poller must keep querying every cycle (no skip)."""
    mgr = _make_manager()
    fake_session = MagicMock()
    get_db_calls = {"n": 0}

    def fake_get_db():
        get_db_calls["n"] += 1
        yield fake_session

    cycle = {"n": 0}

    def counting_wait(timeout=None):
        cycle["n"] += 1
        if cycle["n"] >= 3:
            mgr._stop_polling.set()
        return True

    # A non-empty installations list whose per-item processing is harmless: the
    # job lookup raises, which the loop catches and cleans up (removing the
    # stale record), so we don't need a full Databricks run fixture here.
    fake_install = MagicMock(job_id=1, workflow_id="wf", id="row1")
    mgr._client.jobs.get.side_effect = Exception("job gone")

    with patch("src.common.database.get_db", fake_get_db), \
         patch.object(mgr._stop_polling, "wait", side_effect=counting_wait), \
         patch(
             "src.controller.jobs_manager.workflow_installation_repo.get_all_installed",
             return_value=[fake_install],
         ) as mock_get_all, \
         patch(
             "src.controller.jobs_manager.workflow_installation_repo.remove",
             return_value=None,
         ):
        mgr._poll_job_states(interval_seconds=0)

    # Every cycle opened a DB session and queried — no skipping while non-empty.
    assert get_db_calls["n"] == 3
    assert mock_get_all.call_count == 3
    assert mgr._has_installations is True
