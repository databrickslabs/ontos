"""The review paths change a status only through ``transition_status``.

Requesting a contract review, deciding it on the contract page, and the end of
a product review workflow used to write the status directly, so the
``before_status_change`` gates never ran on them. They now go through
``transition_status``: a blocking gate refuses them like any other change.

The gates are real workflows run by the real executor.
"""
import os
os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import json
import uuid
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.common.workflow_executor import TriggerContext, WorkflowExecutor
from src.common.workflow_triggers import StatusChangeBlockedError
from src.controller.data_contracts_manager import DataContractsManager
from src.db_models.data_contracts import DataContractDb, SchemaObjectDb
from src.db_models.data_products import DataProductDb
from src.db_models.process_workflows import ProcessWorkflowDb, WorkflowStepDb
from src.models.process_workflows import TriggerType


def _gate(db_session, *, fail=True, entity_types=('data_product', 'data_contract')):
    """An active before_status_change workflow that blocks (``fail``) or passes."""
    wf_id = str(uuid.uuid4())
    now = datetime.utcnow()
    db_session.add(ProcessWorkflowDb(
        id=wf_id, name='Blocking Gate', description='gate',
        trigger_config=json.dumps({'type': 'before_status_change', 'entity_types': list(entity_types)}),
        scope_config=json.dumps({'type': 'all'}), is_active=True, is_default=False,
        workflow_type='process', created_at=now, updated_at=now,
    ))
    db_session.flush()
    db_session.add(WorkflowStepDb(
        id=str(uuid.uuid4()), workflow_id=wf_id, step_id='gate', name='Gate',
        step_type='fail' if fail else 'pass',
        config=json.dumps({'message': 'The gate says no'} if fail else {}),
        order=0, created_at=now, updated_at=now,
    ))
    db_session.commit()
    return wf_id


@pytest.fixture
def contract_manager() -> DataContractsManager:
    mgr = DataContractsManager(data_dir=Path('/tmp'))
    mgr._update_search_index = lambda *a, **k: None
    mgr._queue_delivery = lambda *a, **k: None
    return mgr


def _contract(db_session, status='draft', with_schema=True) -> str:
    cid = str(uuid.uuid4())
    db_session.add(DataContractDb(id=cid, name=f'Contract {cid[:8]}', version='1.0.0', status=status))
    db_session.flush()
    if with_schema:
        db_session.add(SchemaObjectDb(id=str(uuid.uuid4()), contract_id=cid, name='orders'))
    db_session.commit()
    return cid


def _product(db_session, status='under_review') -> DataProductDb:
    pid = str(uuid.uuid4())
    product = DataProductDb(
        id=pid, name=f'Product {pid[:8]}', version='1.0.0', status=status,
        api_version='v1.0.0', kind='DataProduct',
    )
    db_session.add(product)
    db_session.commit()
    return product


def _contract_status(db_session, cid):
    db_session.expire_all()
    return db_session.get(DataContractDb, cid).status


def _gate_runs(db_session, wf_id):
    from src.db_models.process_workflows import WorkflowExecutionDb

    return db_session.query(WorkflowExecutionDb).filter(WorkflowExecutionDb.workflow_id == wf_id).count()


# --- Contract review request (draft -> proposed) ----------------------------


def test_a_blocking_gate_refuses_a_contract_review_request(db_session, contract_manager):
    gate = _gate(db_session)
    cid = _contract(db_session)

    with pytest.raises(StatusChangeBlockedError) as err:
        contract_manager.request_steward_review(
            db=db_session, notifications_manager=MagicMock(), contract_id=cid,
            requester_email='producer@example.com', current_user='producer@example.com',
        )

    assert err.value.code == 'status_change_blocked'
    assert err.value.params['toStatus'] == 'proposed'
    assert _contract_status(db_session, cid) == 'draft'
    assert _gate_runs(db_session, gate) == 1


def test_a_contract_review_request_passes_an_open_gate(db_session, contract_manager):
    gate = _gate(db_session, fail=False)
    cid = _contract(db_session)

    contract_manager.request_steward_review(
        db=db_session, notifications_manager=MagicMock(), contract_id=cid,
        requester_email='producer@example.com', current_user='producer@example.com',
    )

    assert _contract_status(db_session, cid) == 'proposed'
    assert _gate_runs(db_session, gate) == 1
    db_session.expire_all()
    assert db_session.get(DataContractDb, cid).draft_owner_id is None


def _personal_draft(db_session) -> str:
    cid = _contract(db_session)
    db_session.get(DataContractDb, cid).draft_owner_id = 'producer@example.com'
    db_session.commit()
    return cid


def test_a_refused_review_request_keeps_the_personal_draft(db_session, contract_manager):
    _gate(db_session)
    cid = _personal_draft(db_session)

    with pytest.raises(StatusChangeBlockedError):
        contract_manager.request_steward_review(
            db=db_session, notifications_manager=MagicMock(), contract_id=cid,
            requester_email='producer@example.com', current_user='producer@example.com',
        )
    # The gate runs commit their executions; the draft owner must not go with them
    db_session.expire_all()
    contract = db_session.get(DataContractDb, cid)
    assert (contract.status, contract.draft_owner_id) == ('draft', 'producer@example.com')


def test_a_review_request_writes_the_status_and_the_promotion_together(db_session, contract_manager):
    cid = _personal_draft(db_session)

    def fail_after_the_transition(*args, **kwargs):
        raise RuntimeError('search index down')

    contract_manager._update_search_index = fail_after_the_transition
    with pytest.raises(RuntimeError):
        contract_manager.request_steward_review(
            db=db_session, notifications_manager=MagicMock(), contract_id=cid,
            requester_email='producer@example.com', current_user='producer@example.com',
        )
    db_session.expire_all()
    contract = db_session.get(DataContractDb, cid)
    # Committed together: a proposed contract is never left as a personal draft
    assert (contract.status, contract.draft_owner_id) == ('proposed', None)


# --- Contract review decided on the contract page --------------------------


@pytest.mark.parametrize('decision,target', [('approve', 'approved'), ('reject', 'draft')])
def test_a_blocking_gate_refuses_a_contract_review_decision(db_session, contract_manager, decision, target):
    gate = _gate(db_session)
    cid = _contract(db_session, status='proposed')

    with pytest.raises(StatusChangeBlockedError) as err:
        contract_manager.handle_review_response(
            db=db_session, notifications_manager=MagicMock(), contract_id=cid,
            reviewer_email='steward@example.com', decision=decision,
            current_user='steward@example.com',
        )

    assert err.value.params['toStatus'] == target
    assert _contract_status(db_session, cid) == 'proposed'
    assert _gate_runs(db_session, gate) == 1


def test_a_contract_review_decision_passes_an_open_gate(db_session, contract_manager):
    _gate(db_session, fail=False)
    cid = _contract(db_session, status='under_review')

    contract_manager.handle_review_response(
        db=db_session, notifications_manager=MagicMock(), contract_id=cid,
        reviewer_email='steward@example.com', decision='approve',
        current_user='steward@example.com',
    )

    assert _contract_status(db_session, cid) == 'approved'


def test_the_handle_review_route_sends_the_gate_code(db_session):
    """The route turns the gate refusal into a coded 409, not 'Invalid review response'."""
    import asyncio

    from fastapi import HTTPException

    from src.routes import data_contracts_routes

    manager = MagicMock()
    manager.handle_review_response.side_effect = StatusChangeBlockedError(
        'proposed', 'approved', [],
    )
    with pytest.raises(HTTPException) as err:
        asyncio.run(data_contracts_routes.handle_steward_review_response(
            contract_id='c1', request=MagicMock(), db=db_session, audit_manager=MagicMock(),
            current_user=SimpleNamespace(email='s@example.com', username='s'),
            notifications=MagicMock(),
            payload=data_contracts_routes.HandleReviewPayload(decision='approve'),
            manager=manager, _=True,
        ))
    assert err.value.status_code == 409
    assert err.value.detail == str(manager.handle_review_response.side_effect)


# --- End of a product review workflow ---------------------------------------


def _complete_product_review(db_session, product, succeeded):
    context = TriggerContext(
        entity_type='data_product', entity_id=product.id, entity_name=product.name,
        trigger_type=TriggerType.ON_REQUEST_REVIEW, user_email='producer@example.com',
    )
    workflow = SimpleNamespace(
        name='Data Product Review', trigger=SimpleNamespace(type=TriggerType.ON_REQUEST_REVIEW),
    )
    WorkflowExecutor(db_session)._handle_workflow_completion(
        trigger_context=context, workflow=workflow, succeeded=succeeded,
        responded_by='steward@example.com',
    )
    db_session.expire_all()
    return db_session.get(DataProductDb, product.id).status


def test_an_approved_product_review_goes_active_through_the_lifecycle(db_session):
    gate = _gate(db_session, fail=False, entity_types=('data_product',))
    product = _product(db_session)

    assert _complete_product_review(db_session, product, True) == 'active'
    # under_review -> approved -> active: one gate run per step
    assert _gate_runs(db_session, gate) == 2


def _status_change_workflow(db_session, name, from_status=None, to_status=None):
    """An active on_status_change workflow (one pass step) for data products."""
    wf_id = str(uuid.uuid4())
    now = datetime.utcnow()
    trigger = {'type': 'on_status_change', 'entity_types': ['data_product']}
    if from_status:
        trigger['from_status'] = from_status
    if to_status:
        trigger['to_status'] = to_status
    db_session.add(ProcessWorkflowDb(
        id=wf_id, name=name, description=name,
        trigger_config=json.dumps(trigger),
        scope_config=json.dumps({'type': 'all'}), is_active=True, is_default=False,
        workflow_type='process', created_at=now, updated_at=now,
    ))
    db_session.flush()
    db_session.add(WorkflowStepDb(
        id=str(uuid.uuid4()), workflow_id=wf_id, step_id='ok', name='Ok',
        step_type='pass', config=json.dumps({}), order=0, created_at=now, updated_at=now,
    ))
    db_session.commit()
    return wf_id


def _runs(db_session, wf_id):
    from src.db_models.process_workflows import WorkflowExecutionDb

    db_session.expire_all()
    return db_session.query(WorkflowExecutionDb).filter(WorkflowExecutionDb.workflow_id == wf_id).all()


def test_a_product_review_fires_on_status_change_once_for_the_whole_change(db_session):
    # Like the default Data Product Publish Approval: approved -> active
    publish = _status_change_workflow(db_session, 'Publish', 'approved', 'active')
    any_change = _status_change_workflow(db_session, 'Any change')
    product = _product(db_session)

    assert _complete_product_review(db_session, product, True) == 'active'
    # The intermediate approved -> active step doesn't start the publish approval
    assert _runs(db_session, publish) == []
    # A workflow on any change runs once, for under_review -> active
    runs = _runs(db_session, any_change)
    assert len(runs) == 1
    context = json.loads(runs[0].trigger_context)
    assert (context['from_status'], context['to_status']) == ('under_review', 'active')


def test_a_refused_review_step_fires_on_status_change_for_the_applied_part(db_session):
    # The gate refuses only approved -> active
    wf_id = str(uuid.uuid4())
    now = datetime.utcnow()
    db_session.add(ProcessWorkflowDb(
        id=wf_id, name='Activation Gate', description='gate',
        trigger_config=json.dumps({
            'type': 'before_status_change', 'entity_types': ['data_product'],
            'from_status': 'approved', 'to_status': 'active',
        }),
        scope_config=json.dumps({'type': 'all'}), is_active=True, is_default=False,
        workflow_type='process', created_at=now, updated_at=now,
    ))
    db_session.flush()
    db_session.add(WorkflowStepDb(
        id=str(uuid.uuid4()), workflow_id=wf_id, step_id='gate', name='Gate', step_type='fail',
        config=json.dumps({'message': 'No activation'}), order=0, created_at=now, updated_at=now,
    ))
    db_session.commit()
    any_change = _status_change_workflow(db_session, 'Any change')
    product = _product(db_session)

    assert _complete_product_review(db_session, product, True) == 'approved'
    runs = _runs(db_session, any_change)
    assert len(runs) == 1
    context = json.loads(runs[0].trigger_context)
    assert (context['from_status'], context['to_status']) == ('under_review', 'approved')


def _review_context(product):
    return TriggerContext(
        entity_type='data_product', entity_id=product.id, entity_name=product.name,
        trigger_type=TriggerType.ON_REQUEST_REVIEW, user_email='producer@example.com',
    )


def _fail_the_activation(monkeypatch, error):
    """transition_status applies under_review -> approved, then raises on -> active."""
    from src.controller.data_products_manager import DataProductsManager

    original = DataProductsManager.transition_status

    def transition_status(self, product_id, new_status, *args, **kwargs):
        if new_status == 'active':
            raise error
        self._update_search_index = lambda *a, **k: None
        return original(self, product_id, new_status, *args, **kwargs)

    monkeypatch.setattr(DataProductsManager, 'transition_status', transition_status)


def test_an_error_in_a_later_review_step_fires_on_status_change_for_the_applied_part(
    db_session, monkeypatch,
):
    any_change = _status_change_workflow(db_session, 'Any change')
    product = _product(db_session)
    _fail_the_activation(monkeypatch, RuntimeError('search index down'))

    with pytest.raises(RuntimeError):
        WorkflowExecutor(db_session)._apply_product_review_outcome(
            _review_context(product), product.id, True, 'steward@example.com',
        )

    runs = _runs(db_session, any_change)
    assert len(runs) == 1
    context = json.loads(runs[0].trigger_context)
    assert (context['from_status'], context['to_status']) == ('under_review', 'approved')


def test_a_database_error_in_a_later_review_step_rolls_back_before_the_trigger(
    db_session, monkeypatch,
):
    from sqlalchemy.exc import OperationalError

    from src.controller.data_products_manager import DataProductsManager

    product = _product(db_session)
    _fail_the_activation(monkeypatch, OperationalError('UPDATE', {}, Exception('db down')))
    calls = []
    # Recorded only: the test session's rollback would drop the test's own data
    monkeypatch.setattr(db_session, 'rollback', lambda: calls.append('rollback'))
    monkeypatch.setattr(
        DataProductsManager, 'fire_status_change_trigger',
        lambda self, pid, name, from_status, to_status, user=None, **kw: calls.append(
            ('trigger', from_status, to_status),
        ),
    )

    with pytest.raises(OperationalError):
        WorkflowExecutor(db_session)._apply_product_review_outcome(
            _review_context(product), product.id, True, 'steward@example.com',
        )

    assert calls == ['rollback', ('trigger', 'under_review', 'approved')]


def test_a_direct_status_change_still_fires_on_status_change(db_session):
    from src.controller.data_products_manager import DataProductsManager

    any_change = _status_change_workflow(db_session, 'Any change')
    product = _product(db_session, status='approved')
    manager = DataProductsManager(db=db_session)
    manager._update_search_index = lambda *a, **k: None

    manager.transition_status(product.id, 'active', 'owner@example.com')
    assert len(_runs(db_session, any_change)) == 1


def test_a_rejected_product_review_returns_to_draft(db_session):
    product = _product(db_session)

    assert _complete_product_review(db_session, product, False) == 'draft'


def test_a_blocking_gate_stops_a_product_review_and_tells_requester_and_approver(db_session):
    from src.db_models.notifications import NotificationDb

    _gate(db_session, entity_types=('data_product',))
    product = _product(db_session)

    assert _complete_product_review(db_session, product, True) == 'under_review'
    notes = db_session.query(NotificationDb).filter(NotificationDb.subtitle == product.name).all()
    assert sorted(n.recipient for n in notes) == ['producer@example.com', 'steward@example.com']
    for note in notes:
        i18n = json.loads(note.data)['i18n']
        assert i18n['description'] == 'notifications:statusChangeNotApplied.reviewNotApplied'
        assert i18n['statusNamespace'] == 'data-products'
        # The gate's refusal, coded, for the bell to translate
        assert i18n['error']['code'] == 'status_change_blocked'
        assert i18n['error']['params']['reasons'][0]['workflow'] == 'Blocking Gate'


def test_a_product_no_longer_in_review_is_left_alone(db_session):
    product = _product(db_session, status='deprecated')

    assert _complete_product_review(db_session, product, True) == 'deprecated'
