"""The data contract write tools run the workflows and audit of the REST routes.

``POST /api/data-contracts``, ``PUT /api/data-contracts/{id}`` and ``DELETE
/api/data-contracts/{id}`` fire ``on_create``, ``on_update`` and ``on_delete`` once
the change succeeded (not blocking: a failing workflow doesn't undo the change),
and ``PUT`` first runs the blocking ``before_update`` gates (a failing gate
answers 400 and nothing is written). Each route writes its data-contracts audit
entry (CREATE / UPDATE / DELETE, and CHANGE_STATUS for ``change-status``).
The tools ``create_draft_data_contract``, ``update_data_contract`` and
``delete_data_contract`` do the same, for the caller, through Ask Ontos
(``ToolRegistry.execute``) and MCP (``check_tool_permission`` + ``tool.execute``,
as ``mcp_routes``). A status change goes through ``transition_status``: its
``before_status_change`` gates and ``on_status_change`` see the caller.
"""
import asyncio
import json
import uuid
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from unittest.mock import MagicMock

from src.common.features import FeatureAccessLevel
from src.controller import audit_manager
from src.controller.data_contracts_manager import DataContractsManager
from src.db_models.data_contracts import DataContractDb
from src.db_models.process_workflows import (
    ProcessWorkflowDb, WorkflowExecutionDb, WorkflowStepDb,
)
from src.tools.base import ToolCaller, ToolContext, check_tool_permission
from src.tools.registry import create_default_registry

# Spelled out so the tests run (and fail) on a tree without the constant.
UPDATE_BLOCKED_CODE = 'update_blocked'
RW = {'data-contracts': FeatureAccessLevel.READ_WRITE}
SUE = ToolCaller(email='sue@example.com', auth_path='test', permissions=RW)


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
    """A published contract, the contract manager and the audit entries written."""
    # The audit entry is written in its own session: keep it off the test's.
    audit = []
    monkeypatch.setattr(audit_manager, 'log_system_action', lambda **kw: audit.append(kw))
    row = DataContractDb(
        id=str(uuid.uuid4()), name='Published contract', version='1.0.0', status='active',
    )
    db_session.add(row)
    db_session.commit()
    contracts = DataContractsManager(data_dir=Path('/tmp'))
    contracts._update_search_index = lambda *a, **k: None
    contracts._queue_delivery = lambda *a, **k: None
    return SimpleNamespace(db=db_session, row=row, contracts=contracts, audit=audit)


def _ctx(world, caller=SUE):
    return ToolContext(db=world.db, settings=MagicMock(), caller=caller,
                       data_contracts_manager=world.contracts)


def _workflow(db, trigger, *, step_type='pass', **trigger_extra):
    """An active workflow on ``trigger`` for data contracts, with one step."""
    now = datetime.utcnow()
    wf_id = str(uuid.uuid4())
    db.add(ProcessWorkflowDb(
        id=wf_id, name=f'{trigger} {wf_id[:6]}', description='test',
        trigger_config=json.dumps({'type': trigger, 'entity_types': ['data_contract'],
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


def _stored(world):
    world.db.expire_all()
    return world.db.get(DataContractDb, world.row.id)


def _actions(world):
    return [(e['action'], e['success']) for e in world.audit]


class TestOnTriggers:
    def test_create_fires_on_create(self, world, run):
        wf = _workflow(world.db, 'on_create')
        res = run(_ctx(world), 'create_draft_data_contract',
                  {'name': 'Chat contract', 'description': 'made by the assistant',
                   'domain': 'Sales'})
        assert res.success is True, res.error
        assert _runs(world.db, wf) == [(res.data['contract_id'], 'on_create', SUE.email)]

    def test_update_fires_on_update(self, world, run):
        wf = _workflow(world.db, 'on_update')
        res = run(_ctx(world), 'update_data_contract',
                  {'contract_id': world.row.id, 'description': 'changed'})
        assert res.success is True, res.error
        assert _runs(world.db, wf) == [(world.row.id, 'on_update', SUE.email)]

    def test_delete_fires_on_delete(self, world, run):
        wf = _workflow(world.db, 'on_delete')
        res = run(_ctx(world), 'delete_data_contract', {'contract_id': world.row.id})
        assert res.success is True, res.error
        assert _runs(world.db, wf) == [(world.row.id, 'on_delete', SUE.email)]

    def test_a_status_change_alone_fires_on_status_change_not_on_update(self, world, run):
        on_update = _workflow(world.db, 'on_update')
        on_status = _workflow(world.db, 'on_status_change')
        res = run(_ctx(world), 'update_data_contract',
                  {'contract_id': world.row.id, 'status': 'deprecated',
                   'deprecation_reason': 'Replaced'})
        assert res.success is True, res.error
        assert _runs(world.db, on_update) == []
        assert _runs(world.db, on_status) == [(world.row.id, 'on_status_change', SUE.email)]

    def test_a_failing_on_create_workflow_keeps_the_contract(self, world, run):
        # As the route: on_* workflows run after the change and don't undo it.
        wf = _workflow(world.db, 'on_create', step_type='fail')
        res = run(_ctx(world), 'create_draft_data_contract',
                  {'name': 'Kept contract', 'description': 'd', 'domain': 'Sales'})
        assert res.success is True, res.error
        assert len(_runs(world.db, wf)) == 1
        assert world.db.get(DataContractDb, res.data['contract_id']) is not None


class TestBlockingGates:
    def test_a_failing_before_update_gate_refuses_the_update(self, world, run):
        gate = _workflow(world.db, 'before_update', step_type='fail')
        on_update = _workflow(world.db, 'on_update')
        res = run(_ctx(world), 'update_data_contract',
                  {'contract_id': world.row.id, 'description': 'changed'})
        assert res.success is False
        assert res.error_code == UPDATE_BLOCKED_CODE
        assert _runs(world.db, gate) == [(world.row.id, 'before_update', SUE.email)]
        assert _runs(world.db, on_update) == []
        stored = _stored(world)
        assert stored.description_purpose is None
        assert _actions(world) == [('UPDATE', False)]
        assert world.audit[0]['details']['error_code'] == UPDATE_BLOCKED_CODE

    def test_a_refused_update_with_a_status_writes_nothing(self, world, run):
        _workflow(world.db, 'before_update', step_type='fail')
        res = run(_ctx(world), 'update_data_contract',
                  {'contract_id': world.row.id, 'description': 'changed',
                   'status': 'deprecated'})
        assert res.error_code == UPDATE_BLOCKED_CODE
        stored = _stored(world)
        assert stored.status == 'active'
        assert stored.description_purpose is None

    def test_a_passing_before_update_gate_lets_the_update_through(self, world, run):
        gate = _workflow(world.db, 'before_update')
        res = run(_ctx(world), 'update_data_contract',
                  {'contract_id': world.row.id, 'description': 'changed'})
        assert res.success is True, res.error
        assert _runs(world.db, gate) == [(world.row.id, 'before_update', SUE.email)]
        assert _stored(world).description_purpose == 'changed'

    def test_a_status_change_alone_runs_no_before_update_gate(self, world, run):
        # As change-status, which runs the before_status_change gates only.
        gate = _workflow(world.db, 'before_update', step_type='fail')
        res = run(_ctx(world), 'update_data_contract',
                  {'contract_id': world.row.id, 'status': 'deprecated',
                   'deprecation_reason': 'Replaced'})
        assert res.success is True, res.error
        assert _runs(world.db, gate) == []

    def test_a_before_status_change_gate_sees_the_caller(self, world, run):
        gate = _workflow(world.db, 'before_status_change', step_type='fail',
                         from_status='active', to_status='deprecated')
        res = run(_ctx(world), 'update_data_contract',
                  {'contract_id': world.row.id, 'status': 'deprecated',
                   'deprecation_reason': 'Replaced'})
        assert res.success is False
        assert res.error_code == 'status_change_blocked'
        assert _runs(world.db, gate) == [(world.row.id, 'before_status_change', SUE.email)]
        assert _stored(world).status == 'active'


class TestAuditAndCaller:
    def test_a_create_is_audited_and_owned_by_the_caller(self, world, run):
        res = run(_ctx(world), 'create_draft_data_contract',
                  {'name': 'Chat contract', 'description': 'd', 'domain': 'Sales'})
        assert res.success is True, res.error
        cid = res.data['contract_id']
        world.db.expire_all()
        created = world.db.get(DataContractDb, cid)
        # As POST /data-contracts: the creator owns the personal draft.
        assert created.draft_owner_id == SUE.email
        assert created.created_by == SUE.email
        assert _actions(world) == [('CREATE', True)]
        entry = world.audit[0]
        assert entry['username'] == SUE.email
        assert entry['feature'] == 'data-contracts'
        assert entry['details']['created_resource_id'] == cid
        assert entry['details']['params'] == {'contract_name': 'Chat contract'}
        assert entry['details']['tool_name'] == 'create_draft_data_contract'
        assert entry['details']['auth_path'] == 'test'

    def test_an_update_is_audited_and_names_the_caller(self, world, run):
        res = run(_ctx(world), 'update_data_contract',
                  {'contract_id': world.row.id, 'domain': 'Finance'})
        assert res.success is True, res.error
        assert _stored(world).updated_by == SUE.email
        assert _actions(world) == [('UPDATE', True)]
        assert world.audit[0]['username'] == SUE.email
        assert world.audit[0]['details']['updated_resource_id'] == world.row.id

    def test_a_status_change_is_audited_as_change_status(self, world, run):
        res = run(_ctx(world), 'update_data_contract',
                  {'contract_id': world.row.id, 'status': 'deprecated',
                   'deprecation_reason': 'Replaced'})
        assert res.success is True, res.error
        assert _stored(world).updated_by == SUE.email
        assert _actions(world) == [('CHANGE_STATUS', True)]
        details = world.audit[0]['details']
        assert (details['contract_id'], details['from'], details['to']) == (
            world.row.id, 'active', 'deprecated')

    def test_a_delete_is_audited_and_names_the_caller(self, world, run, monkeypatch):
        seen = {}
        delete = world.contracts.delete_contract_from_db

        def _delete(db, contract_id, current_user=None):
            seen['user'] = current_user
            return delete(db=db, contract_id=contract_id, current_user=current_user)

        monkeypatch.setattr(world.contracts, 'delete_contract_from_db', _delete)
        res = run(_ctx(world), 'delete_data_contract', {'contract_id': world.row.id})
        assert res.success is True, res.error
        assert seen['user'] == SUE.email
        assert _actions(world) == [('DELETE', True)]
        assert world.audit[0]['username'] == SUE.email
        assert world.audit[0]['details']['deleted_resource_id_attempted'] == world.row.id
