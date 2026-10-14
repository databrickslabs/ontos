"""An approved status change request applies the requested status.

The default Status Change Request workflow (on_request_status_change) only
asks for approval; nothing applied the transition afterwards, so approving
it left the product where it was.
"""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import uuid
from types import SimpleNamespace

import pytest

from src.common.workflow_executor import WorkflowExecutor
from src.db_models.data_products import DataProductDb
from src.models.process_workflows import TriggerContext, TriggerType


def _product(db, status='active'):
    product = DataProductDb(
        id=str(uuid.uuid4()), api_version='v1.0.0', kind='DataProduct',
        status=status, name=f'p-{uuid.uuid4().hex[:8]}', version='1.0.0',
    )
    db.add(product)
    db.flush()
    return product


def _complete(db, product, approved, target='deprecated', succeeded=None):
    context = TriggerContext(
        entity_type='data_product', entity_id=product.id, entity_name=product.name,
        trigger_type=TriggerType.ON_REQUEST_STATUS_CHANGE, user_email='requester@example.com',
        from_status=product.status, to_status=target,
        entity_data={'target_status': target, 'justification': 'Moving to v2'},
    )
    workflow = SimpleNamespace(
        name='Status Change Request',
        trigger=SimpleNamespace(type=TriggerType.ON_REQUEST_STATUS_CHANGE),
    )
    WorkflowExecutor(db)._handle_workflow_completion(
        trigger_context=context, workflow=workflow,
        succeeded=approved if succeeded is None else succeeded,
        responded_by='approver@example.com', approved=approved,
    )


@pytest.mark.parametrize('approved, expected', [(True, 'deprecated'), (False, 'active')])
def test_the_requested_status_is_applied_only_when_approved(db_session, approved, expected):
    product = _product(db_session)

    _complete(db_session, product, approved)

    db_session.refresh(product)
    assert product.status == expected


def test_the_approvers_decision_counts_not_the_run_outcome(db_session):
    # Approved, but a later step failed the run: the transition still applies.
    product = _product(db_session)

    _complete(db_session, product, approved=True, succeeded=False)

    db_session.refresh(product)
    assert product.status == 'deprecated'


def test_an_invalid_requested_transition_changes_nothing(db_session):
    product = _product(db_session, status='retired')

    _complete(db_session, product, True, target='active')

    db_session.refresh(product)
    assert product.status == 'retired'


def test_a_refused_transition_tells_the_requester(db_session):
    from src.db_models.notifications import NotificationDb

    product = _product(db_session, status='retired')

    _complete(db_session, product, True, target='active')

    notes = db_session.query(NotificationDb).filter(
        NotificationDb.subtitle == product.name
    ).all()
    assert len(notes) == 1
    assert 'could not be applied' in notes[0].description


def test_the_app_notifications_and_search_managers_are_used(db_session):
    from unittest.mock import MagicMock, patch

    from src.common.app_state import set_app_state_manager

    notifications, search = MagicMock(), MagicMock()
    set_app_state_manager('notifications_manager', notifications)
    set_app_state_manager('search_manager', search)
    product = _product(db_session)
    try:
        with patch('src.controller.data_products_manager.DataProductsManager') as manager_cls:
            _complete(db_session, product, True)
    finally:
        set_app_state_manager('notifications_manager', None)
        set_app_state_manager('search_manager', None)

    assert manager_cls.call_args.kwargs['notifications_manager'] is notifications
    manager_cls.return_value.set_search_manager.assert_called_once_with(search)
    manager_cls.return_value.transition_status.assert_called_once_with(
        product.id, 'deprecated', 'approver@example.com'
    )
