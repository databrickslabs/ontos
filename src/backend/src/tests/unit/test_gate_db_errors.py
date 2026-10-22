"""A database error while the status gates run doesn't break the transition (#1103).

A failed statement leaves the session's transaction unusable: before, the
fallback lookup of the gates' ``on_error`` mode and the status write then
failed too, so the request ended in a 500 whatever the mode. The session is
now rolled back first: ``fail_closed`` refuses with its code, ``fail_open``
lets the transition through.

A failed flush (a duplicate primary key) puts the session in the same state
on SQLite as a failed query does on Postgres. The tests use a session of their
own, which commits for real like a request's session: the shared test session
runs inside an outer transaction that a rollback would undo entirely.
"""
import os
os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import json
import uuid
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.common import workflow_triggers
from src.common.workflow_executor import WorkflowExecutor
from src.common.workflow_triggers import GateEvaluationError
from src.common.database import Base
from src.controller import audit_manager
from src.controller.data_contracts_manager import DataContractsManager
from src.controller.data_products_manager import DataProductsManager
from src.db_models.data_contracts import DataContractDb
from src.db_models.data_products import DataProductDb
from src.db_models.process_workflows import ProcessWorkflowDb, WorkflowStepDb


def _gate(db_session, name, *, on_error=None):
    trigger = {'type': 'before_status_change', 'entity_types': ['data_product', 'data_contract']}
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
        id=str(uuid.uuid4()), workflow_id=wf_id, step_id='gate', name='Gate',
        step_type='pass', config='{}', order=0, created_at=now, updated_at=now,
    ))
    db_session.commit()


def _break_the_session(db):
    """A failed flush: the session must be rolled back before it can be used again."""
    existing = db.query(DataProductDb).first()
    db.add(DataProductDb(id=existing.id, name='duplicate', version='1', status='draft'))
    db.flush()


@pytest.fixture
def db_session():
    """A session that commits for real (an in-memory database of its own)."""
    engine = create_engine(
        'sqlite://', poolclass=StaticPool, connect_args={'check_same_thread': False},
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture(autouse=True)
def quiet_audit(monkeypatch):
    monkeypatch.setattr(audit_manager, 'log_system_action', lambda **kw: None)


@pytest.fixture
def db_breaking_gates(monkeypatch):
    """Running a workflow named '[db] ...' fails on the database; the others run for real."""
    original = WorkflowExecutor.execute_workflow

    def execute(self, workflow, *args, **kwargs):
        if workflow.name.startswith('[db]'):
            _break_the_session(self._db)
        return original(self, workflow, *args, **kwargs)

    monkeypatch.setattr(WorkflowExecutor, 'execute_workflow', execute)


@pytest.fixture
def db_breaking_listing(monkeypatch):
    """Listing the gates fails on the database."""
    def before_status_change(self, **kwargs):
        _break_the_session(self._db)

    monkeypatch.setattr(workflow_triggers.TriggerRegistry, 'before_status_change', before_status_change)


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


def _product(db_session) -> str:
    pid = str(uuid.uuid4())
    db_session.add(DataProductDb(
        id=pid, name=f'Product {pid[:8]}', version='1.0.0', status='draft',
        api_version='v1.0.0', kind='DataProduct',
    ))
    db_session.commit()
    return pid


def _contract(db_session) -> str:
    cid = str(uuid.uuid4())
    db_session.add(DataContractDb(id=cid, name=f'Contract {cid[:8]}', version='1.0.0', status='draft'))
    db_session.commit()
    return cid


def _status(db_session, model, entity_id):
    db_session.expire_all()
    return db_session.get(model, entity_id).status


# --- A gate's run fails on the database --------------------------------------


def test_fail_closed_refuses_with_its_code_after_a_db_error(db_session, product_manager, db_breaking_gates):
    _gate(db_session, '[db] Closed Gate', on_error='fail_closed')
    pid = _product(db_session)

    with pytest.raises(GateEvaluationError) as err:
        product_manager.transition_status(pid, 'proposed', 'owner@example.com')

    assert err.value.code == 'status_change_gate_error'
    assert _status(db_session, DataProductDb, pid) == 'draft'


def test_fail_open_lets_the_transition_through_after_a_db_error(db_session, product_manager, db_breaking_gates):
    _gate(db_session, '[db] Open Gate')
    pid = _product(db_session)

    product_manager.transition_status(pid, 'proposed', 'owner@example.com')

    assert _status(db_session, DataProductDb, pid) == 'proposed'


def test_a_contract_with_a_fail_open_gate_moves_after_a_db_error(db_session, contract_manager, db_breaking_gates):
    _gate(db_session, '[db] Open Gate')
    cid = _contract(db_session)

    contract_manager.transition_status(db=db_session, contract_id=cid, new_status='proposed')

    assert _status(db_session, DataContractDb, cid) == 'proposed'


# --- Listing the gates fails on the database ---------------------------------


def test_listing_failure_still_honours_fail_closed(db_session, contract_manager, db_breaking_listing):
    _gate(db_session, 'Closed Gate', on_error='fail_closed')
    _product(db_session)  # a row for the failing flush to duplicate
    cid = _contract(db_session)

    with pytest.raises(GateEvaluationError) as err:
        contract_manager.transition_status(db=db_session, contract_id=cid, new_status='proposed')

    assert err.value.params['workflows'] == ['Closed Gate']
    assert _status(db_session, DataContractDb, cid) == 'draft'


def test_listing_failure_with_only_open_gates_lets_the_transition_through(
    db_session, product_manager, db_breaking_listing,
):
    _gate(db_session, 'Open Gate')
    pid = _product(db_session)

    product_manager.transition_status(pid, 'proposed', 'owner@example.com')

    assert _status(db_session, DataProductDb, pid) == 'proposed'
