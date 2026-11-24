"""A database error while the status gates run doesn't break the transition (#1103).

A failed statement leaves the session's transaction unusable: before, the
fallback lookup of the gates' ``on_error`` mode and the status write then
failed too, so the request ended in a 500 whatever the mode. Each gate now
runs in a savepoint, rolled back first: ``fail_closed`` refuses with its code,
``fail_open`` lets the transition through.

The same holds for the workflows that fire after a change (``on_create`` of
each product of an ODPS import): each runs in a savepoint, so a database error
undoes only its own writes, not the caller's change, and the import goes on.

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


# --- A workflow fired after the change fails on the database -----------------


def _on_create_workflow(db_session):
    now = datetime.utcnow()
    wf_id = str(uuid.uuid4())
    db_session.add(ProcessWorkflowDb(
        id=wf_id, name='On create', description='after the change',
        trigger_config=json.dumps({'type': 'on_create', 'entity_types': ['data_product']}),
        scope_config=json.dumps({'type': 'all'}), is_active=True, is_default=False,
        workflow_type='process', created_at=now, updated_at=now,
    ))
    db_session.flush()
    db_session.add(WorkflowStepDb(
        id=str(uuid.uuid4()), workflow_id=wf_id, step_id='only', name='Only step',
        step_type='pass', config='{}', order=0, created_at=now, updated_at=now,
    ))
    db_session.commit()


def _import_two_products(product_manager):
    content = json.dumps([
        {'apiVersion': 'v1.0.0', 'kind': 'DataProduct', 'id': str(uuid.uuid4()),
         'name': name, 'version': '0.1.0', 'status': 'draft'}
        for name in ('Imported A', 'Imported B')
    ]).encode()
    return product_manager.create_products_from_files(
        [('p.json', content)], user='sue', workflow_user='sue@example.com',
    )


def _stored_names(db_session, ids):
    db_session.expire_all()
    return sorted(db_session.get(DataProductDb, i).name for i in ids
                  if db_session.get(DataProductDb, i) is not None)


def test_a_workflow_db_error_keeps_the_imported_products(db_session, product_manager, monkeypatch):
    # The first product's on_create run fails on the database; both products
    # are still created and stored, the second one's workflow runs.
    _on_create_workflow(db_session)
    original = WorkflowExecutor.execute_workflow
    calls = []

    def execute(self, workflow, *args, **kwargs):
        calls.append(workflow.name)
        if len(calls) == 1:
            _break_the_session(self._db)
        return original(self, workflow, *args, **kwargs)

    monkeypatch.setattr(WorkflowExecutor, 'execute_workflow', execute)

    result = _import_two_products(product_manager)

    assert (result.created, result.failed) == (2, 0)
    assert len(calls) == 2
    assert _stored_names(db_session, result.created_ids) == ['Imported A', 'Imported B']


def test_a_failing_trigger_keeps_the_imported_products(db_session, product_manager, monkeypatch):
    # The registry itself fails on the database (e.g. listing the workflows)
    calls = []

    def on_create(self, **kwargs):
        calls.append(kwargs['entity_id'])
        if len(calls) == 1:
            _break_the_session(self._db)

    monkeypatch.setattr(workflow_triggers.TriggerRegistry, 'on_create', on_create)

    result = _import_two_products(product_manager)

    assert (result.created, result.failed) == (2, 0)
    assert _stored_names(db_session, result.created_ids) == ['Imported A', 'Imported B']


def _flushed_product(db_session) -> str:
    """A product written but not yet committed, as a manager leaves it when its triggers fire."""
    pid = str(uuid.uuid4())
    db_session.add(DataProductDb(
        id=pid, name='Not committed yet', version='1.0.0', status='draft',
        api_version='v1.0.0', kind='DataProduct',
    ))
    db_session.flush()
    return pid


def test_a_workflow_db_error_undoes_only_the_workflow_writes(db_session, db_breaking_gates):
    from src.models.process_workflows import EntityType

    _product(db_session)  # a row for the failing flush to duplicate
    _on_create_workflow(db_session)
    db_session.query(ProcessWorkflowDb).update({'name': '[db] On create'})
    db_session.commit()
    pid = _flushed_product(db_session)

    workflow_triggers.TriggerRegistry(db_session).on_create(
        entity_type=EntityType.DATA_PRODUCT, entity_id=pid, entity_name='x', blocking=True,
    )
    db_session.commit()

    assert _stored_names(db_session, [pid]) == ['Not committed yet']


def test_a_failing_trigger_undoes_only_its_own_writes(db_session, monkeypatch):
    from src.models.process_workflows import EntityType

    _product(db_session)

    def on_create(self, **kwargs):
        _break_the_session(self._db)

    monkeypatch.setattr(workflow_triggers.TriggerRegistry, 'on_create', on_create)
    pid = _flushed_product(db_session)

    workflow_triggers.fire_trigger_safe(
        db_session, 'on_create', entity_type=EntityType.DATA_PRODUCT, entity_id=pid,
    )
    db_session.commit()

    assert _stored_names(db_session, [pid]) == ['Not committed yet']


def test_a_workflow_that_fails_after_committing_leaves_a_usable_session(
    db_session, product_manager, monkeypatch,
):
    # The commit ends the workflow's savepoint: the session is recovered, which
    # drops only what was written after that commit
    from sqlalchemy import text

    _on_create_workflow(db_session)
    original = WorkflowExecutor.execute_workflow
    calls = []

    def execute(self, workflow, *args, **kwargs):
        calls.append(workflow.name)
        if len(calls) == 1:
            self._db.commit()
            _break_the_session(self._db)
        return original(self, workflow, *args, **kwargs)

    monkeypatch.setattr(WorkflowExecutor, 'execute_workflow', execute)

    result = _import_two_products(product_manager)

    assert (result.created, result.failed) == (2, 0)
    assert len(calls) == 2
    assert _stored_names(db_session, result.created_ids) == ['Imported A', 'Imported B']
    assert db_session.execute(text('SELECT 1')).scalar() == 1


def test_a_db_error_the_trigger_caught_itself_is_rolled_back(db_session, monkeypatch):
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError
    from src.models.process_workflows import EntityType

    _product(db_session)

    def on_create(self, **kwargs):
        try:
            _break_the_session(self._db)
        except IntegrityError:
            pass

    monkeypatch.setattr(workflow_triggers.TriggerRegistry, 'on_create', on_create)
    pid = _flushed_product(db_session)

    workflow_triggers.fire_trigger_safe(
        db_session, 'on_create', entity_type=EntityType.DATA_PRODUCT, entity_id=pid,
    )
    db_session.commit()

    assert _stored_names(db_session, [pid]) == ['Not committed yet']
    assert db_session.execute(text('SELECT 1')).scalar() == 1


def test_a_query_error_the_trigger_caught_itself_is_rolled_back_on_postgres(
    db_session, monkeypatch
):
    # On Postgres a failed query aborts the transaction without deactivating the
    # savepoint: releasing it then fails too, and only a rollback to it recovers
    from sqlalchemy import text
    from src.models.process_workflows import EntityType
    from src.tests.unit.test_review_access import postgres_aborts

    _product(db_session)

    def on_create(self, **kwargs):
        try:
            self._db.execute(text('SELECT * FROM no_such_table'))
        except Exception:
            pass

    monkeypatch.setattr(workflow_triggers.TriggerRegistry, 'on_create', on_create)
    pid = _flushed_product(db_session)

    with postgres_aborts(db_session):
        workflow_triggers.fire_trigger_safe(
            db_session, 'on_create', entity_type=EntityType.DATA_PRODUCT, entity_id=pid,
        )
        assert db_session.execute(text('SELECT 1')).scalar() == 1
    db_session.commit()

    assert _stored_names(db_session, [pid]) == ['Not committed yet']


def test_a_caller_change_that_cannot_be_written_still_fails_its_commit(db_session):
    # The savepoint flushes the caller's pending change first: when that flush
    # fails, the session is left for the caller's commit to fail loudly, not
    # rolled back into an empty commit
    from src.models.process_workflows import EntityType

    existing = _product(db_session)
    db_session.add(DataProductDb(id=existing, name='duplicate', version='1', status='draft'))

    workflow_triggers.fire_trigger_safe(
        db_session, 'on_create', entity_type=EntityType.DATA_PRODUCT, entity_id=existing,
    )

    with pytest.raises(Exception):
        db_session.commit()
