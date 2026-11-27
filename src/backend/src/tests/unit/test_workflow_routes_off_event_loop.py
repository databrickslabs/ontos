"""A manual run or a retry runs the workflow off the event loop (#1414 follow-up).

An ``evaluate_asset_maturity`` step waits for its bulk run, which can take minutes. The
async routes must not hold the event loop meanwhile: here the fake executor waits for a
coroutine on the loop to run; while the loop is held it never does.
"""
import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.models.process_workflows import EntityType
from src.routes import workflows_routes as routes


class _SlowExecutor:
    """Stands for a long step: returns whether the loop ran while it was executing."""

    def __init__(self, loop_ran: threading.Event):
        self._loop_ran = loop_ran
        self.saw_loop_run = None

    def execute_workflow(self, *args, **kwargs):
        self.saw_loop_run = self._loop_ran.wait(timeout=2)
        return SimpleNamespace(id='exec-1', status=SimpleNamespace(value='succeeded'))


async def _run_with_ticker(route_call, loop_ran: threading.Event):
    async def ticker():
        await asyncio.sleep(0.05)
        loop_ran.set()

    tick = asyncio.ensure_future(ticker())
    result = await route_call
    await tick
    return result


def _request():
    return SimpleNamespace(client=SimpleNamespace(host='127.0.0.1'))


@pytest.mark.asyncio
async def test_a_manual_run_does_not_hold_the_event_loop():
    loop_ran = threading.Event()
    executor = _SlowExecutor(loop_ran)
    manager = MagicMock()
    manager.get_workflow.return_value = SimpleNamespace(id='wf-1', steps=[])

    await _run_with_ticker(routes.execute_workflow(
        request=_request(), workflow_id='wf-1', db=MagicMock(), audit_manager=MagicMock(),
        current_user=SimpleNamespace(email='a@example.com', username='a'),
        entity_type=EntityType.TABLE, entity_id='t-1', entity_name=None,
        manager=manager, executor=executor, auth_manager=MagicMock(), _=True,
    ), loop_ran)

    assert executor.saw_loop_run is True


@pytest.mark.asyncio
async def test_a_retry_does_not_hold_the_event_loop(monkeypatch):
    loop_ran = threading.Event()
    executor = _SlowExecutor(loop_ran)
    execution = SimpleNamespace(workflow_id='wf-1', trigger_context=None)
    monkeypatch.setattr(routes.workflow_execution_repo, 'get', lambda db, eid: execution)
    monkeypatch.setattr(routes.workflow_execution_repo, 'reset_for_retry',
                        lambda db, eid: execution)
    monkeypatch.setattr(routes.process_workflow_repo, 'get',
                        lambda db, wid: SimpleNamespace(id=wid, steps=[]))

    result = await _run_with_ticker(routes.retry_execution(
        execution_id='exec-1', request=_request(), db=MagicMock(),
        audit_manager=MagicMock(), current_user=SimpleNamespace(email='a@example.com',
                                                                username='a'),
        executor=executor, auth_manager=MagicMock(), _=True,
    ), loop_ran)

    assert executor.saw_loop_run is True
    assert result['status'] == 'succeeded'
