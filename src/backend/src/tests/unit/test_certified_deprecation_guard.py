"""The certified deprecation guard's edges (the routes are in the integration tests).

- An approval accepts the deprecation of its own entity only.
- A Status Change Request run without an approver's decision doesn't count.
- A decision with a refusal reason (not an admin's, no pending request, the
  requester's own) is refused with that reason.
- A workflow approval counts only through handle-approval (``eligible_approver``)
  and not by the requester.
- A stored switch that can't be read leaves the guard on.
- Only the move to ``deprecated`` is guarded.
- A transition closes the open requests with its own status write.
"""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.common.workflow_executor import WorkflowExecutor
from src.controller import audit_manager
from src.controller.certified_deprecation_guard import (
    GUARD_SETTING_KEY,
    CertifiedDeprecationApprovalRefusedError,
    CertifiedDeprecationRequiresApprovalError,
    approved_status_change,
    close_open_requests,
    eligible_approver,
    pending_request_id,
    workflow_approval_refusal,
    guard_exemptions,
)
from src.controller.change_log_manager import change_log_manager
from src.controller.data_contracts_manager import DataContractsManager
from src.controller.data_products_manager import DataProductsManager
from src.db_models.data_contracts import DataContractDb
from src.db_models.data_products import DataProductDb
from src.models.process_workflows import TriggerContext, TriggerType
from src.repositories.app_settings_repository import app_settings_repo


def _product(db, status='active', certified=True) -> DataProductDb:
    product = DataProductDb(
        id=str(uuid.uuid4()), api_version='v1.0.0', kind='DataProduct', status=status,
        name=f'p-{uuid.uuid4().hex[:8]}', version='1.0.0',
        certification_level=2 if certified else None,
    )
    db.add(product)
    db.commit()
    return product


def _contract(db, certified=True) -> DataContractDb:
    contract = DataContractDb(
        id=str(uuid.uuid4()), name=f'c-{uuid.uuid4().hex[:8]}', version='1.0.0',
        status='active', certification_level=2 if certified else None,
    )
    db.add(contract)
    db.commit()
    return contract


def _status(db, model, entity_id):
    db.expire_all()
    return db.get(model, entity_id).status


@pytest.fixture(autouse=True)
def audited(monkeypatch):
    entries = []
    monkeypatch.setattr(audit_manager, 'log_system_action', lambda **kw: entries.append(kw))
    return entries


@pytest.fixture
def products(db_session) -> DataProductsManager:
    mgr = DataProductsManager(
        db=db_session, ws_client=MagicMock(),
        notifications_manager=MagicMock(), tags_manager=MagicMock(),
    )
    mgr._update_search_index = lambda *a, **k: None
    mgr._queue_delivery = lambda *a, **k: None
    return mgr


@pytest.fixture
def contracts() -> DataContractsManager:
    mgr = DataContractsManager(data_dir=Path('/tmp'))
    mgr._update_search_index = lambda *a, **k: None
    mgr._queue_delivery = lambda *a, **k: None
    return mgr


def test_an_approval_accepts_its_own_product_only(products, db_session):
    approved, other = _product(db_session), _product(db_session)

    with approved_status_change('data_product', approved.id):
        products.transition_status(approved.id, 'deprecated', 'approver@example.com')
        with pytest.raises(CertifiedDeprecationRequiresApprovalError) as refused:
            products.transition_status(other.id, 'deprecated', 'approver@example.com')

    assert _status(db_session, DataProductDb, approved.id) == 'deprecated'
    assert _status(db_session, DataProductDb, other.id) == 'active'
    assert refused.value.params['entityId'] == other.id


def test_the_approval_ends_with_its_block(products, db_session):
    product = _product(db_session)
    with approved_status_change('data_product', product.id):
        pass

    with pytest.raises(CertifiedDeprecationRequiresApprovalError):
        products.transition_status(product.id, 'deprecated')


def test_a_decision_that_does_not_count_is_refused_with_its_reason(
    products, contracts, db_session,
):
    product, contract = _product(db_session), _contract(db_session)

    with approved_status_change('data_product', product.id, 'not_admin'):
        with pytest.raises(CertifiedDeprecationApprovalRefusedError) as refused_product:
            products.transition_status(product.id, 'deprecated')
    with approved_status_change('data_contract', contract.id, 'self_approval'):
        with pytest.raises(CertifiedDeprecationApprovalRefusedError) as refused:
            contracts.transition_status(db_session, contract.id, 'deprecated')

    assert refused_product.value.params['reason'] == 'not_admin'
    assert refused.value.code == 'certified_deprecation_approval_refused'
    assert refused.value.params['reason'] == 'self_approval'
    assert refused.value.params['entityType'] == 'data_contract'
    assert _status(db_session, DataProductDb, product.id) == 'active'
    assert _status(db_session, DataContractDb, contract.id) == 'active'


def test_an_approved_contract_request_is_accepted(contracts, db_session):
    contract = _contract(db_session)

    with approved_status_change('data_contract', contract.id):
        contracts.transition_status(db_session, contract.id, 'deprecated')

    assert _status(db_session, DataContractDb, contract.id) == 'deprecated'


def _complete(db, product, approved, succeeded=True, approver=None):
    """End a Status Change Request run; ``approver`` decides it through handle-approval."""
    context = TriggerContext(
        entity_type='data_product', entity_id=product.id, entity_name=product.name,
        trigger_type=TriggerType.ON_REQUEST_STATUS_CHANGE, user_email='requester@example.com',
        from_status=product.status, to_status='deprecated',
        entity_data={'target_status': 'deprecated', 'justification': 'Moving to v2'},
    )
    workflow = SimpleNamespace(
        name='Status Change Request',
        trigger=SimpleNamespace(type=TriggerType.ON_REQUEST_STATUS_CHANGE),
    )
    def run():
        WorkflowExecutor(db)._handle_workflow_completion(
            trigger_context=context, workflow=workflow, succeeded=succeeded,
            responded_by='approver@example.com', approved=approved,
        )

    if approver:
        with eligible_approver(approver, None):
            run()
    else:
        run()


def test_an_approvers_decision_deprecates_a_certified_product(db_session):
    product = _product(db_session)

    _complete(db_session, product, approved=True, approver='approver@example.com')

    assert _status(db_session, DataProductDb, product.id) == 'deprecated'


def test_an_approval_not_given_through_handle_approval_does_not_count(db_session):
    product = _product(db_session)

    _complete(db_session, product, approved=True)

    assert _status(db_session, DataProductDb, product.id) == 'active'


def test_the_requester_approving_does_not_count(db_session):
    product = _product(db_session)

    _complete(db_session, product, approved=True, approver='Requester@Example.com')

    assert _status(db_session, DataProductDb, product.id) == 'active'


@pytest.mark.parametrize('approved, approver, requester, expected', [
    (True, 'a@x.com', 'r@x.com', None),
    (True, 'r@x.com', 'r@x.com', 'self_approval'),
    (True, None, 'r@x.com', 'no_approver'),
    (None, 'a@x.com', 'r@x.com', 'no_approver'),
    (False, 'a@x.com', 'r@x.com', 'no_approver'),
])
def test_workflow_approval_refusal(approved, approver, requester, expected):
    if approver:
        with eligible_approver(approver):
            assert workflow_approval_refusal(approved, requester) == expected
    else:
        assert workflow_approval_refusal(approved, requester) == expected


def test_a_request_run_without_an_approval_step_does_not_count(db_session):
    # The run succeeded, but nobody approved: the guard still refuses, and the
    # requester is told the change wasn't applied
    from src.db_models.notifications import NotificationDb

    product = _product(db_session)

    _complete(db_session, product, approved=None, succeeded=True)

    assert _status(db_session, DataProductDb, product.id) == 'active'
    notes = db_session.query(NotificationDb).filter(
        NotificationDb.subtitle == product.name
    ).all()
    assert [n.recipient for n in notes] == ['requester@example.com']


def test_an_uncertified_product_needs_no_approval_in_a_request_run(db_session):
    product = _product(db_session, certified=False)

    _complete(db_session, product, approved=None, succeeded=True)

    assert _status(db_session, DataProductDb, product.id) == 'deprecated'


def test_a_switch_that_cannot_be_read_leaves_the_guard_on(products, db_session, caplog):
    app_settings_repo.set(db_session, GUARD_SETTING_KEY, '{not json')
    product = _product(db_session)

    assert guard_exemptions(db_session).is_empty()
    with pytest.raises(CertifiedDeprecationRequiresApprovalError):
        products.transition_status(product.id, 'deprecated')
    assert "can't be read" in caplog.text


def test_only_the_move_to_deprecated_is_guarded(products, db_session, audited):
    product = _product(db_session, status='deprecated')

    products.transition_status(product.id, 'retired')

    assert _status(db_session, DataProductDb, product.id) == 'retired'
    assert audited == []


def test_a_transition_closes_the_open_requests_with_its_status_write(db_session):
    product = _product(db_session)
    change_log_manager.log_change_with_details(
        db_session, entity_type='data_product', entity_id=product.id,
        action='status_change_requested', username='requester@example.com',
        details={'request_id': 'r1', 'from_status': 'active', 'target_status': 'deprecated'},
    )
    assert pending_request_id(db_session, 'data_product', product.id) == 'r1'

    # The status write fails after the gates: the request stays open
    failed_write = db_session.begin_nested()
    close_open_requests(db_session, 'data_product', product.id, 'retired', 'someone')
    failed_write.rollback()
    assert pending_request_id(db_session, 'data_product', product.id) == 'r1'

    # It succeeds: the closure is committed with it
    close_open_requests(db_session, 'data_product', product.id, 'retired', 'someone')
    db_session.commit()
    assert pending_request_id(db_session, 'data_product', product.id) is None
