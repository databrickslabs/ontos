"""Route-level tests for Metadata Generation: run visibility and error mapping.

Route functions are called directly with a mocked manager and a patched
``is_user_feature_admin`` (HTTP clients hit the audit-service 503 in fresh
worktrees). Owners see their runs, feature admins see all, everyone else gets
404 for reads and mutations; manager errors map to the documented statuses
and the audit record carries the outcome.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from src.common.errors import ConflictError
from src.controller.metadata_generation_manager import ActiveRunLimitError
from src.models.metadata_generation import SelectionItem, StartRunRequest
from src.routes import metadata_generation_routes as routes

OWNER = SimpleNamespace(email="owner@x.com", username="owner", groups=[])
OTHER = SimpleNamespace(email="other@x.com", username="other", groups=[])


def _run(user_id="owner@x.com", status="completed"):
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        id="run-1", user_id=user_id, status=status, progress_message=None, error=None,
        selection=[{"type": "schema", "fqn": "main.sales"}], options={}, job_run_id="1",
        suggestion_count=0, created_at=now, updated_at=now, started_at=now, completed_at=now,
    )


def _request(manager):
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(metadata_generation_manager=manager)),
                           client=SimpleNamespace(host="127.0.0.1"))


def _manager(run=None):
    manager = MagicMock()
    manager.get_run.return_value = run if run is not None else _run()
    manager.refresh_run.side_effect = lambda db, r, **kwargs: r
    manager.cancel_run.side_effect = lambda db, r: r
    manager.counts.return_value = {}
    manager.list_suggestions.return_value = []
    manager.count_suggestions.return_value = 0
    return manager


def _admin(is_admin: bool):
    return patch.object(routes, "is_user_feature_admin", AsyncMock(return_value=is_admin))


@pytest.mark.asyncio
async def test_owner_sees_own_run():
    manager = _manager()
    with _admin(False):
        detail = await routes.get_run("run-1", _request(manager), MagicMock(), db=MagicMock(), current_user=OWNER)
    assert detail.run_id == "run-1"


@pytest.mark.asyncio
@pytest.mark.parametrize("call", ["get", "suggestions", "cancel", "delete"])
async def test_non_owner_non_admin_gets_404(call):
    manager = _manager(_run(status="running"))
    request, db = _request(manager), MagicMock()
    with _admin(False), pytest.raises(HTTPException) as exc:
        if call == "get":
            await routes.get_run("run-1", request, MagicMock(), db=db, current_user=OTHER)
        elif call == "suggestions":
            await routes.list_suggestions("run-1", request, db=db, current_user=OTHER, status_filter=None, limit=10, skip=0)
        elif call == "cancel":
            await routes.cancel_run("run-1", request, db=db, audit_manager=MagicMock(), current_user=OTHER)
        else:
            await routes.delete_run("run-1", request, db=db, audit_manager=MagicMock(), current_user=OTHER)
    assert exc.value.status_code == 404
    manager.cancel_run.assert_not_called()
    manager.delete_run.assert_not_called()


@pytest.mark.asyncio
async def test_admin_can_see_and_cancel_others_runs():
    manager = _manager(_run(status="running"))
    with _admin(True):
        await routes.get_run("run-1", _request(manager), MagicMock(), db=MagicMock(), current_user=OTHER)
        await routes.cancel_run("run-1", _request(manager), db=MagicMock(), audit_manager=MagicMock(), current_user=OTHER)
    manager.cancel_run.assert_called_once()


@pytest.mark.asyncio
async def test_unknown_run_is_404():
    manager = _manager()
    manager.get_run.return_value = None
    with _admin(True), pytest.raises(HTTPException) as exc:
        await routes.get_run("nope", _request(manager), MagicMock(), db=MagicMock(), current_user=OWNER)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("is_admin,expected", [(True, None), (False, "owner@x.com")])
async def test_list_runs_scopes_to_caller_unless_admin(is_admin, expected):
    manager = _manager()
    manager.list_runs.return_value = []
    db = MagicMock()
    with _admin(is_admin):
        await routes.list_runs(_request(manager), db=db, current_user=OWNER, limit=50)
    manager.list_runs.assert_called_once_with(db, expected, limit=50)


@pytest.mark.parametrize("error,status", [
    (ActiveRunLimitError("busy"), 429),
    (ValueError("bad name"), 400),
    (ConflictError("job not enabled"), 409),
    (RuntimeError("boom"), 500),
])
def test_start_run_error_mapping_and_audit(error, status):
    manager = _manager()
    manager.start_run.side_effect = error
    audit = MagicMock()
    body = StartRunRequest(selection=[SelectionItem(type="schema", fqn="main.sales")])
    with pytest.raises(HTTPException) as exc:
        routes.start_run(_request(manager), body, MagicMock(), db=MagicMock(), audit_manager=audit, current_user=OWNER)
    assert exc.value.status_code == status
    assert audit.log_action.call_args.kwargs["success"] is False
    if status == 500:
        assert "boom" not in exc.value.detail  # internals stay in the log


def test_start_run_success_is_audited():
    manager = _manager()
    manager.start_run.return_value = _run(status="running")
    audit = MagicMock()
    body = StartRunRequest(selection=[SelectionItem(type="schema", fqn="main.sales")])
    resp = routes.start_run(_request(manager), body, MagicMock(), db=MagicMock(), audit_manager=audit, current_user=OWNER)
    assert resp.status == "running"
    assert audit.log_action.call_args.kwargs["success"] is True
    assert audit.log_action.call_args.kwargs["details"]["run_id"] == "run-1"


@pytest.mark.asyncio
@pytest.mark.parametrize("call", ["cancel", "delete"])
async def test_cancel_and_delete_conflicts_map_to_409(call):
    manager = _manager(_run(status="running"))
    manager.cancel_run.side_effect = ValueError("already completed")
    manager.delete_run.side_effect = ValueError("open review")
    audit = MagicMock()
    with _admin(False), pytest.raises(HTTPException) as exc:
        if call == "cancel":
            await routes.cancel_run("run-1", _request(manager), db=MagicMock(), audit_manager=audit, current_user=OWNER)
        else:
            await routes.delete_run("run-1", _request(manager), db=MagicMock(), audit_manager=audit, current_user=OWNER)
    assert exc.value.status_code == 409
    assert audit.log_action.call_args.kwargs["success"] is False


@pytest.mark.asyncio
async def test_get_run_defers_ingest_to_a_background_task():
    manager = _manager(_run(status="running"))

    def refresh(db, run, defer_ingest=None):
        defer_ingest(run.id)
        return run

    manager.refresh_run.side_effect = refresh
    background_tasks = MagicMock()
    with _admin(False):
        await routes.get_run("run-1", _request(manager), background_tasks, db=MagicMock(), current_user=OWNER)
    manager.make_deferrer.assert_called_once_with(background_tasks.add_task)
    manager.make_deferrer.return_value.assert_called_once_with("run-1")
    manager.ingest_results.assert_not_called()


def test_start_run_defers_ingest_of_finished_runs_to_background():
    manager = _manager()

    def start(db, *, user_id, request, defer_ingest):
        defer_ingest("finished-run")
        return _run(status="running")

    manager.start_run.side_effect = start
    background_tasks = MagicMock()
    body = StartRunRequest(selection=[SelectionItem(type="schema", fqn="main.sales")])
    routes.start_run(_request(manager), body, background_tasks, db=MagicMock(), audit_manager=MagicMock(), current_user=OWNER)
    manager.make_deferrer.assert_called_once_with(background_tasks.add_task)
    manager.make_deferrer.return_value.assert_called_once_with("finished-run")
