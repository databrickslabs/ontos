"""The app starts the workflow scheduler with its settings and stops it (#941)."""
import os

os.environ['TESTING'] = 'true'

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src import app as app_module
from src.controller.workflow_scheduler import WorkflowScheduler
from src.utils.startup_tasks import start_workflow_scheduler


def _settings(**overrides):
    values = dict(
        WORKFLOW_SCHEDULER_ENABLED=True, WORKFLOW_SCHEDULER_CHANGE_CHECK_SECONDS=45,
        WORKFLOW_SCHEDULER_IDLE_RECHECK_SECONDS=0, WORKFLOW_SCHEDULER_MAX_WORKERS=2,
        WORKFLOW_SCHEDULER_DRAIN_SECONDS=5,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def _app():
    return SimpleNamespace(state=SimpleNamespace())


def test_the_scheduler_starts_with_its_settings():
    app = _app()
    with patch.object(WorkflowScheduler, 'start') as start:
        start_workflow_scheduler(app, _settings())
    start.assert_called_once()
    scheduler = app.state.workflow_scheduler
    assert scheduler._max_workers == 2 and scheduler._drain_seconds == 5
    assert scheduler._change_check.total_seconds() == 45


def test_a_turned_off_scheduler_is_not_created():
    app = _app()
    with patch.object(WorkflowScheduler, 'start') as start:
        start_workflow_scheduler(app, _settings(WORKFLOW_SCHEDULER_ENABLED=False))
    start.assert_not_called()
    assert not hasattr(app.state, 'workflow_scheduler')


def test_a_failing_start_does_not_stop_the_startup():
    with patch.object(WorkflowScheduler, 'start', side_effect=RuntimeError('boom')):
        start_workflow_scheduler(_app(), _settings())  # logged, not raised


class _FakeScheduler:
    def __init__(self):
        self.stopped = 0

    def stop(self):
        self.stopped += 1


@pytest.fixture
def fake_scheduler():
    state = app_module.app.state
    saved = {name: getattr(state, name, None) for name in ('workflow_scheduler', 'jobs_manager')}
    state.workflow_scheduler = _FakeScheduler()
    state.jobs_manager = None
    yield state.workflow_scheduler
    for name, value in saved.items():
        setattr(state, name, value)


def test_a_re_initialization_stops_the_old_scheduler(fake_scheduler):
    app_module._stop_job_polling()
    assert fake_scheduler.stopped == 1


@pytest.mark.asyncio
async def test_the_shutdown_stops_the_scheduler(fake_scheduler):
    await app_module.shutdown_event()
    assert fake_scheduler.stopped == 1
