"""A ``before_status_change`` gate that errors no longer looks like one that passed (#1103).

A gate whose evaluation raised was dropped from the executions (or the error
was swallowed by ``transition_status``), so the transition went ahead. Now the
error is logged at error level and audited, and a gate whose trigger says
``on_error: fail_closed`` refuses the transition; ``fail_open`` (the default)
behaves as before. A gate that fails normally blocks in both modes.

The gates are real workflows run by the real executor; only the evaluation
of a gate named ``[raise] ...`` is made to raise.
"""
import os
os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import json
import logging
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.common import workflow_triggers
from src.common.workflow_executor import WorkflowExecutor
from src.common.workflow_triggers import (
    GateEvaluationError,
    StatusChangeBlockedError,
    run_status_gates,
)
from src.controller import audit_manager
from src.controller.data_contracts_manager import DataContractsManager
from src.controller.data_products_manager import DataProductsManager
from src.controller.workflows_manager import WorkflowsManager
from src.db_models.audit_log import AuditLogDb
from src.db_models.data_contracts import DataContractDb
from src.db_models.data_products import DataProductDb
from src.db_models.process_workflows import ProcessWorkflowDb, WorkflowStepDb
from src.models.process_workflows import (
    EntityType,
    GateErrorMode,
    ProcessWorkflowCreate,
    TriggerType,
    WorkflowExecution,
    WorkflowStepCreate,
    WorkflowTrigger,
)


def _gate(db_session, name, *, on_error=None, fail=False, entity_types=('data_product', 'data_contract')):
    """An active before_status_change workflow: a Pass step, or a Fail step when ``fail``."""
    trigger = {'type': 'before_status_change', 'entity_types': list(entity_types)}
    if on_error:
        trigger['on_error'] = on_error
    wf_id = str(uuid.uuid4())
    now = datetime.utcnow()
    db_session.add(ProcessWorkflowDb(
        id=wf_id, name=name, description='gate', trigger_config=json.dumps(trigger),
        scope_config=json.dumps({'type': 'all'}), is_active=True, is_default=False,
        workflow_type='process', created_at=now, updated_at=now,
    ))
    db_session.flush()
    db_session.add(WorkflowStepDb(
        id=str(uuid.uuid4()), workflow_id=wf_id, step_id='gate',
        name='Gate', step_type='fail' if fail else 'pass',
        config=json.dumps({'message': 'The gate says no'} if fail else {}),
        order=0, created_at=now, updated_at=now,
    ))
    db_session.commit()
    return wf_id


@pytest.fixture
def raising_gates(monkeypatch):
    """Evaluating a workflow named '[raise] ...' raises; the others run for real."""
    original = WorkflowExecutor.execute_workflow

    def execute(self, workflow, *args, **kwargs):
        if workflow.name.startswith('[raise]'):
            raise RuntimeError('database went away while evaluating the gate')
        return original(self, workflow, *args, **kwargs)

    monkeypatch.setattr(WorkflowExecutor, 'execute_workflow', execute)


@pytest.fixture
def audited(monkeypatch):
    """The audit entries the gate errors write."""
    entries = []
    monkeypatch.setattr(audit_manager, 'log_system_action', lambda **kw: entries.append(kw))
    return entries


@pytest.fixture
def product_manager(db_session) -> DataProductsManager:
    mgr = DataProductsManager(
        db=db_session, ws_client=MagicMock(),
        notifications_manager=MagicMock(), tags_manager=MagicMock(),
    )
    mgr._update_search_index = lambda *a, **k: None
    mgr._queue_delivery = lambda *a, **k: None
    return mgr


@pytest.fixture
def contract_manager() -> DataContractsManager:
    mgr = DataContractsManager(data_dir=Path('/tmp'))
    mgr._update_search_index = lambda *a, **k: None
    mgr._queue_delivery = lambda *a, **k: None
    return mgr


def _product(db_session, status='draft') -> str:
    pid = str(uuid.uuid4())
    db_session.add(DataProductDb(
        id=pid, name=f'Product {pid[:8]}', version='1.0.0', status=status,
        api_version='v1.0.0', kind='DataProduct',
    ))
    db_session.commit()
    return pid


def _contract(db_session, status='draft') -> str:
    cid = str(uuid.uuid4())
    db_session.add(DataContractDb(id=cid, name=f'Contract {cid[:8]}', version='1.0.0', status=status))
    db_session.commit()
    return cid


def _product_status(db_session, pid):
    db_session.expire_all()
    return db_session.get(DataProductDb, pid).status


def _contract_status(db_session, cid):
    db_session.expire_all()
    return db_session.get(DataContractDb, cid).status


class TestProducts:
    def test_a_fail_closed_gate_that_errors_refuses_the_transition(
        self, product_manager, db_session, raising_gates, audited, caplog,
    ):
        _gate(db_session, '[raise] Enforcement gate', on_error='fail_closed')
        pid = _product(db_session)
        with caplog.at_level(logging.ERROR, logger=workflow_triggers.logger.name):
            with pytest.raises(GateEvaluationError) as err:
                product_manager.transition_status(pid, 'proposed', current_user='owner@example.com')
        assert err.value.code == 'status_change_gate_error'
        assert err.value.params == {
            'fromStatus': 'draft', 'toStatus': 'proposed', 'workflows': ['[raise] Enforcement gate'],
        }
        assert _product_status(db_session, pid) == 'draft'
        assert any(r.levelno == logging.ERROR and 'gate error' in r.getMessage() for r in caplog.records)
        assert audited[0]['action'] == 'GATE_ERROR'
        assert audited[0]['success'] is False
        assert audited[0]['username'] == 'owner@example.com'
        assert audited[0]['details']['workflow_name'] == '[raise] Enforcement gate'
        assert audited[0]['details']['on_error'] == 'fail_closed'
        assert audited[0]['details']['entity_type'] == 'data_product'
        assert 'database went away' in audited[0]['details']['error']

    @pytest.mark.parametrize('on_error', [None, 'fail_open'])
    def test_a_fail_open_or_unmarked_gate_that_errors_lets_it_through(
        self, product_manager, db_session, raising_gates, audited, on_error,
    ):
        _gate(db_session, '[raise] Advisory gate', on_error=on_error)
        pid = _product(db_session)
        product_manager.transition_status(pid, 'proposed', current_user='owner@example.com')
        assert _product_status(db_session, pid) == 'proposed'
        # Still visible: the error is audited
        assert [e['details']['on_error'] for e in audited] == ['fail_open']

    def test_a_gate_that_fails_blocks_in_fail_open_mode_with_a_real_execution(
        self, product_manager, db_session, audited,
    ):
        _gate(db_session, 'Fail gate', on_error='fail_open', fail=True)
        pid = _product(db_session)
        with pytest.raises(StatusChangeBlockedError) as err:
            product_manager.transition_status(pid, 'proposed')
        assert err.value.params['reasons'] == [{'workflow': 'Fail gate', 'text': 'The gate says no'}]
        assert _product_status(db_session, pid) == 'draft'
        assert audited == []

    def test_one_fail_closed_gate_that_errors_refuses_even_if_the_others_pass(
        self, product_manager, db_session, raising_gates, audited,
    ):
        _gate(db_session, 'Pass gate')
        _gate(db_session, '[raise] Enforcement gate', on_error='fail_closed')
        pid = _product(db_session)
        with pytest.raises(GateEvaluationError):
            product_manager.transition_status(pid, 'proposed')
        assert _product_status(db_session, pid) == 'draft'


class TestContracts:
    def test_a_fail_closed_gate_that_errors_refuses_the_transition(
        self, contract_manager, db_session, raising_gates, audited,
    ):
        _gate(db_session, '[raise] Enforcement gate', on_error='fail_closed')
        cid = _contract(db_session)
        with pytest.raises(GateEvaluationError) as err:
            contract_manager.transition_status(db_session, cid, 'proposed', current_user='owner@example.com')
        assert err.value.params['workflows'] == ['[raise] Enforcement gate']
        assert _contract_status(db_session, cid) == 'draft'
        assert audited[0]['details']['entity_type'] == 'data_contract'
        assert audited[0]['details']['on_error'] == 'fail_closed'

    @pytest.mark.parametrize('on_error', [None, 'fail_open'])
    def test_a_fail_open_or_unmarked_gate_that_errors_lets_it_through(
        self, contract_manager, db_session, raising_gates, audited, on_error,
    ):
        _gate(db_session, '[raise] Advisory gate', on_error=on_error)
        cid = _contract(db_session)
        contract_manager.transition_status(db_session, cid, 'proposed')
        assert _contract_status(db_session, cid) == 'proposed'
        assert len(audited) == 1

    def test_a_gate_that_fails_blocks_in_fail_open_mode_with_a_real_execution(
        self, contract_manager, db_session, audited,
    ):
        _gate(db_session, 'Fail gate', fail=True)
        cid = _contract(db_session)
        with pytest.raises(StatusChangeBlockedError):
            contract_manager.transition_status(db_session, cid, 'proposed')
        assert _contract_status(db_session, cid) == 'draft'


class TestBeforeTheGatesAreKnown:
    """Errors raised before any workflow ran (listing the gates, building the message)."""

    @pytest.fixture
    def listing_raises(self, monkeypatch):
        def boom(self, *args, **kwargs):
            raise RuntimeError('could not list the gates')
        monkeypatch.setattr(WorkflowsManager, 'get_workflows_for_trigger', boom)

    def _run(self, db_session, entity_type=EntityType.DATA_PRODUCT):
        run_status_gates(
            db_session, entity_type=entity_type, entity_id='e-1',
            from_status='draft', to_status='proposed', entity_name='E', user_email='u@example.com',
        )

    def test_listing_fails_and_a_matching_gate_is_fail_closed(self, db_session, listing_raises, audited):
        _gate(db_session, 'Enforcement gate', on_error='fail_closed')
        with pytest.raises(GateEvaluationError) as err:
            self._run(db_session)
        assert err.value.params['workflows'] == ['Enforcement gate']
        assert audited[0]['details']['workflow_name'] is None
        assert audited[0]['details']['on_error'] is None

    def test_listing_fails_and_no_gate_is_fail_closed(self, db_session, listing_raises, audited):
        _gate(db_session, 'Advisory gate')
        _gate(db_session, 'Closed gate for another type', on_error='fail_closed', entity_types=('dataset',))
        self._run(db_session)  # proceeds
        assert len(audited) == 1

    def test_an_inactive_fail_closed_gate_is_ignored(self, db_session, listing_raises, audited):
        wf_id = _gate(db_session, 'Enforcement gate', on_error='fail_closed')
        db_session.get(ProcessWorkflowDb, wf_id).is_active = False
        db_session.commit()
        self._run(db_session)

    def test_a_failed_gate_still_blocks_when_its_message_cannot_be_built(self, db_session, monkeypatch, audited):
        # The #1012 failure: describing the blocking execution raised, and the transition went ahead
        _gate(db_session, 'Fail gate', fail=True)

        def broken(executions):
            raise AttributeError("'WorkflowExecution' object has no attribute 'step_results'")

        monkeypatch.setattr(workflow_triggers, 'describe_failed_executions', broken)
        with pytest.raises(StatusChangeBlockedError) as err:
            self._run(db_session)
        assert err.value.params['reasons'] == []


class TestSetting:
    def test_on_error_is_stored_with_the_trigger_and_defaults_to_fail_open(self, db_session):
        mgr = WorkflowsManager(db_session)
        created = mgr.create_workflow(ProcessWorkflowCreate(
            name='Enforcement gate', is_active=True,
            trigger=WorkflowTrigger(
                type=TriggerType.BEFORE_STATUS_CHANGE, entity_types=[EntityType.DATA_PRODUCT],
                on_error=GateErrorMode.FAIL_CLOSED,
            ),
            steps=[WorkflowStepCreate(step_id='ok', name='OK', step_type='pass', config={}, order=0)],
        ))
        assert mgr.get_workflow(created.id).trigger.on_error == GateErrorMode.FAIL_CLOSED
        assert json.loads(db_session.get(ProcessWorkflowDb, created.id).trigger_config)['on_error'] == 'fail_closed'
        # A workflow saved before the setting existed has no key: fail_open
        old_id = _gate(db_session, 'Old gate')
        assert mgr.get_workflow(old_id).trigger.on_error == GateErrorMode.FAIL_OPEN
        assert WorkflowTrigger(type=TriggerType.BEFORE_STATUS_CHANGE).on_error == GateErrorMode.FAIL_OPEN

    def test_the_audit_entry_is_written_to_the_audit_log(self, db_session, monkeypatch):
        @contextmanager
        def factory():
            yield db_session

        monkeypatch.setattr(audit_manager, 'get_session_factory', lambda: factory)
        audit_manager.log_system_action(
            username='owner@example.com', feature='process-workflows', action='GATE_ERROR',
            success=False, details={'workflow_name': 'Enforcement gate'},
        )
        row = db_session.query(AuditLogDb).filter(AuditLogDb.action == 'GATE_ERROR').one()
        assert row.username == 'owner@example.com'
        assert row.success is False
        assert row.ip_address is None
