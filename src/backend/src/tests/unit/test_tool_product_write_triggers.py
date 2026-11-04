"""The data product write tools fire the workflow triggers of the REST routes.

``POST /api/data-products``, ``PUT /api/data-products/{id}`` and ``DELETE
/api/data-products/{id}`` fire ``on_create``, ``on_update`` and ``on_delete`` once
the change succeeded (not blocking: a failing workflow doesn't undo the change).
The tools ``create_draft_data_product``, ``update_data_product`` and
``delete_data_product`` fire the same ones, for the caller, through Ask Ontos
(``ToolRegistry.execute``) and MCP (``check_tool_permission`` + ``tool.execute``,
as ``mcp_routes``). A status change goes through ``transition_status``: its
``before_status_change`` gates refuse it and ``on_status_change`` fires, as with
``change-status``; it fires no ``on_update``.
"""
import asyncio
import json
import uuid
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.common.features import FeatureAccessLevel
from src.controller import audit_manager
from src.controller.data_products_manager import DataProductsManager
from src.db_models.data_products import DataProductDb
from src.db_models.process_workflows import (
    ProcessWorkflowDb, WorkflowExecutionDb, WorkflowStepDb,
)
from src.tools.base import ToolCaller, ToolContext, check_tool_permission
from src.tools.registry import create_default_registry

RW = {'data-products': FeatureAccessLevel.READ_WRITE}
OWNER = ToolCaller(email='sue@example.com', auth_path='test', permissions=RW)
ADMIN = ToolCaller(email='ann@example.com', auth_path='test',
                   permissions={'data-products': FeatureAccessLevel.ADMIN},
                   products_admin=True)


def _ask_ontos(ctx, tool, args):
    return asyncio.run(create_default_registry().execute(tool, ctx, args))


def _mcp(ctx, tool, args):
    # What mcp_routes does for tools/call.
    impl = create_default_registry().get(tool)
    refusal = check_tool_permission(impl, ctx)
    return refusal or asyncio.run(impl.execute(ctx, **args))


PATHS = {'ask_ontos': _ask_ontos, 'mcp': _mcp}


@pytest.fixture(params=sorted(PATHS))
def run(request):
    return PATHS[request.param]


@pytest.fixture
def world(db_session, monkeypatch):
    """A published product owned by OWNER, and the product manager."""
    # The audit entry is written in its own session: keep it off the test's.
    monkeypatch.setattr(audit_manager, 'log_system_action', lambda **kw: None)
    row = DataProductDb(
        id=str(uuid.uuid4()), api_version='v1.0.0', kind='DataProduct',
        name='Published product', version='1.0.0', status='active',
        draft_owner_id=OWNER.email,
    )
    db_session.add(row)
    db_session.commit()
    products = DataProductsManager(db=db_session, ws_client=MagicMock(),
                                   notifications_manager=MagicMock(), tags_manager=MagicMock())
    products._update_search_index = lambda *a, **k: None
    return SimpleNamespace(db=db_session, row=row, products=products)


def _ctx(world, caller):
    return ToolContext(db=world.db, settings=MagicMock(), caller=caller,
                       data_products_manager=world.products)


def _workflow(db, trigger, *, step_type='pass', **trigger_extra):
    """An active workflow on ``trigger`` for data products, with one step."""
    now = datetime.utcnow()
    wf_id = str(uuid.uuid4())
    db.add(ProcessWorkflowDb(
        id=wf_id, name=f'{trigger} {wf_id[:6]}', description='test',
        trigger_config=json.dumps({'type': trigger, 'entity_types': ['data_product'],
                                   **trigger_extra}),
        scope_config=json.dumps({'type': 'all'}), is_active=True, is_default=False,
        workflow_type='process', created_at=now, updated_at=now,
    ))
    db.flush()
    db.add(WorkflowStepDb(
        id=str(uuid.uuid4()), workflow_id=wf_id, step_id='only', name='Only step',
        step_type=step_type, config='{}', on_pass=None, on_fail=None, order=0,
        created_at=now, updated_at=now,
    ))
    db.commit()
    return wf_id


def _runs(db, wf_id):
    """(entity_id, trigger_type, triggered_by) of each execution of the workflow."""
    db.expire_all()
    rows = db.query(WorkflowExecutionDb).filter_by(workflow_id=wf_id).all()
    out = []
    for r in rows:
        context = json.loads(r.trigger_context or '{}')
        out.append((context.get('entity_id'), context.get('trigger_type'), r.triggered_by))
    return out


class TestOnTriggers:
    def test_create_fires_on_create(self, world, run):
        wf = _workflow(world.db, 'on_create')
        res = run(_ctx(world, OWNER), 'create_draft_data_product',
                  {'name': 'Chat draft', 'description': 'made by the assistant',
                   'domain': 'Sales'})
        assert res.success is True, res.error
        assert _runs(world.db, wf) == [(res.data['product_id'], 'on_create', OWNER.email)]

    def test_update_fires_on_update(self, world, run):
        wf = _workflow(world.db, 'on_update')
        res = run(_ctx(world, OWNER), 'update_data_product',
                  {'product_id': world.row.id, 'description': 'changed'})
        assert res.success is True, res.error
        assert _runs(world.db, wf) == [(world.row.id, 'on_update', OWNER.email)]

    def test_delete_fires_on_delete(self, world, run):
        wf = _workflow(world.db, 'on_delete')
        res = run(_ctx(world, ADMIN), 'delete_data_product', {'product_id': world.row.id})
        assert res.success is True, res.error
        assert _runs(world.db, wf) == [(world.row.id, 'on_delete', ADMIN.email)]

    def test_a_refused_update_fires_nothing(self, world, run):
        # A Read/Write caller who isn't an owner: refused before any write, as PUT (403).
        wf = _workflow(world.db, 'on_update')
        stranger = ToolCaller(email='carl@example.com', auth_path='test', permissions=RW)
        res = run(_ctx(world, stranger), 'update_data_product',
                  {'product_id': world.row.id, 'description': 'changed'})
        assert res.success is False
        assert _runs(world.db, wf) == []

    def test_a_status_change_alone_fires_on_status_change_not_on_update(self, world, run):
        on_update = _workflow(world.db, 'on_update')
        on_status = _workflow(world.db, 'on_status_change')
        res = run(_ctx(world, OWNER), 'update_data_product',
                  {'product_id': world.row.id, 'status': 'deprecated'})
        assert res.success is True, res.error
        assert _runs(world.db, on_update) == []
        assert _runs(world.db, on_status) == [(world.row.id, 'on_status_change', OWNER.email)]

    def test_a_failing_on_create_workflow_keeps_the_product(self, world, run):
        # As the route: on_* workflows run after the change and don't undo it.
        wf = _workflow(world.db, 'on_create', step_type='fail')
        res = run(_ctx(world, OWNER), 'create_draft_data_product',
                  {'name': 'Kept draft', 'description': 'd', 'domain': 'Sales'})
        assert res.success is True, res.error
        assert len(_runs(world.db, wf)) == 1
        assert world.db.get(DataProductDb, res.data['product_id']) is not None


class TestBlockingGate:
    def test_a_before_status_change_gate_refuses_the_tool(self, world, run):
        gate = _workflow(world.db, 'before_status_change', step_type='fail',
                         from_status='active', to_status='deprecated')
        res = run(_ctx(world, OWNER), 'update_data_product',
                  {'product_id': world.row.id, 'status': 'deprecated'})
        assert res.success is False
        assert res.error_code == 'status_change_blocked'
        assert len(_runs(world.db, gate)) == 1
        world.db.expire_all()
        assert world.db.get(DataProductDb, world.row.id).status == 'active'

