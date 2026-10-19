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


@pytest.fixture(autouse=True)
def _no_audit_session(monkeypatch):
    # An approved deprecation is audited in its own session; in tests that
    # session would commit outside the per-test transaction
    from src.controller import audit_manager
    monkeypatch.setattr(audit_manager, 'log_system_action', lambda **kw: None)


def _product(db, status='active'):
    product = DataProductDb(
        id=str(uuid.uuid4()), api_version='v1.0.0', kind='DataProduct',
        status=status, name=f'p-{uuid.uuid4().hex[:8]}', version='1.0.0',
    )
    db.add(product)
    db.flush()
    return product


def _complete(db, product, approved, target='deprecated', succeeded=None,
              justification='Moving to v2'):
    context = TriggerContext(
        entity_type='data_product', entity_id=product.id, entity_name=product.name,
        trigger_type=TriggerType.ON_REQUEST_STATUS_CHANGE, user_email='requester@example.com',
        from_status=product.status, to_status=target,
        entity_data={'target_status': target, 'justification': justification},
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
    import json
    i18n = json.loads(notes[0].data)['i18n']
    assert i18n['description'] == 'notifications:statusChangeNotApplied.refused'
    assert i18n['params']['toStatus'] == 'active' and i18n['params']['reason']


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
    call = manager_cls.return_value.transition_status.call_args
    assert call.args == (product.id, 'deprecated', 'approver@example.com')
    assert call.kwargs['deprecation'].reason == 'Moving to v2'


def test_an_approved_deprecation_uses_the_requests_justification_as_reason(db_session):
    product = _product(db_session)

    _complete(db_session, product, True)

    db_session.refresh(product)
    assert product.status == 'deprecated'
    assert product.deprecation_reason == 'Moving to v2'


def test_the_justification_falls_back_to_the_logged_request(db_session):
    from src.controller.change_log_manager import change_log_manager

    product = _product(db_session)
    change_log_manager.log_change_with_details(
        db_session, entity_type='data_product', entity_id=product.id,
        action='status_change_requested', username='requester@example.com',
        details={'target_status': 'deprecated', 'justification': 'Replaced by v2'},
    )

    _complete(db_session, product, True, justification=None)

    db_session.refresh(product)
    assert product.deprecation_reason == 'Replaced by v2'


def _notes_for(db, product):
    from src.db_models.notifications import NotificationDb

    return db.query(NotificationDb).filter(NotificationDb.subtitle == product.name).all()


def test_a_request_made_from_another_status_is_not_applied(db_session):
    # Requested proposed -> draft; while it waited, the product moved to sandbox,
    # from where 'draft' is also allowed. The approval was about 'proposed'.
    product = _product(db_session, status='proposed')
    context_status = product.status
    product.status = 'sandbox'
    db_session.flush()

    context = TriggerContext(
        entity_type='data_product', entity_id=product.id, entity_name=product.name,
        trigger_type=TriggerType.ON_REQUEST_STATUS_CHANGE, user_email='requester@example.com',
        from_status=context_status, to_status='draft',
        entity_data={'from_status': context_status, 'target_status': 'draft'},
    )
    workflow = SimpleNamespace(
        name='Status Change Request',
        trigger=SimpleNamespace(type=TriggerType.ON_REQUEST_STATUS_CHANGE),
    )
    WorkflowExecutor(db_session)._handle_workflow_completion(
        trigger_context=context, workflow=workflow, succeeded=True,
        responded_by='approver@example.com', approved=True,
    )

    db_session.refresh(product)
    assert product.status == 'sandbox'
    notes = _notes_for(db_session, product)
    assert {n.recipient for n in notes} == {'requester@example.com', 'approver@example.com'}
    assert all("is now 'sandbox'" in n.description for n in notes)
    # The UI translates it from these keys (notifications namespace)
    import json
    assert all(json.loads(n.data)['i18n'] == {
        'title': 'notifications:statusChangeNotApplied.title',
        'description': 'notifications:statusChangeNotApplied.statusChanged',
        'params': {'fromStatus': 'proposed', 'toStatus': 'draft', 'currentStatus': 'sandbox'},
        # The product status labels translate the three statuses
        'statusNamespace': 'data-products',
    } for n in notes)


def test_completing_twice_applies_once_and_warns_nobody(db_session):
    product = _product(db_session)

    _complete(db_session, product, True)
    _complete(db_session, product, True)

    db_session.refresh(product)
    assert product.status == 'deprecated'
    assert _notes_for(db_session, product) == []


def test_a_deprecation_without_any_justification_is_not_applied(db_session):
    from src.db_models.notifications import NotificationDb

    product = _product(db_session)

    _complete(db_session, product, True, justification=None)

    db_session.refresh(product)
    assert product.status == 'active'
    notes = db_session.query(NotificationDb).filter(
        NotificationDb.subtitle == product.name
    ).all()
    assert len(notes) == 1
    assert 'deprecation reason is required' in notes[0].description


def test_an_approved_deprecation_is_audited_as_deprecate_with_the_request(db_session, monkeypatch):
    from src.controller import audit_manager
    from src.controller.change_log_manager import change_log_manager
    entries = []
    monkeypatch.setattr(audit_manager, 'log_system_action', lambda **kw: entries.append(kw))
    product = _product(db_session)
    request = change_log_manager.log_change_with_details(
        db_session, entity_type='data_product', entity_id=product.id,
        action='status_change_requested', username='requester',
        details={'target_status': 'deprecated', 'justification': 'Moving to v2'},
    )
    db_session.flush()

    _complete(db_session, product, True)

    assert [e['action'] for e in entries] == ['DEPRECATE']
    details = entries[0]['details']
    assert entries[0]['username'] == 'approver@example.com'
    assert details['product_id'] == product.id
    assert (details['from'], details['to']) == ('active', 'deprecated')
    assert details['request_id'] == str(request.id)
    assert details['deprecation_reason'] == 'Moving to v2'


def test_the_audit_carries_the_request_id_of_the_trigger(db_session, monkeypatch):
    from src.controller import audit_manager
    entries = []
    monkeypatch.setattr(audit_manager, 'log_system_action', lambda **kw: entries.append(kw))
    product = _product(db_session)
    context = TriggerContext(
        entity_type='data_product', entity_id=product.id, entity_name=product.name,
        trigger_type=TriggerType.ON_REQUEST_STATUS_CHANGE, user_email='requester@example.com',
        from_status='active', to_status='deprecated',
        entity_data={'target_status': 'deprecated', 'justification': 'v2',
                     'request_id': 'req-123'},
    )
    workflow = SimpleNamespace(
        name='Status Change Request',
        trigger=SimpleNamespace(type=TriggerType.ON_REQUEST_STATUS_CHANGE),
    )
    WorkflowExecutor(db_session)._handle_workflow_completion(
        trigger_context=context, workflow=workflow, succeeded=True,
        responded_by='approver@example.com', approved=True,
    )

    assert entries[0]['details']['request_id'] == 'req-123'


def test_a_refused_approval_writes_no_lifecycle_audit(db_session, monkeypatch):
    from src.controller import audit_manager
    entries = []
    monkeypatch.setattr(audit_manager, 'log_system_action', lambda **kw: entries.append(kw))
    product = _product(db_session)

    _complete(db_session, product, True, justification=None)  # no reason: refused

    assert entries == []


def test_an_approved_deprecation_applies_the_requested_sunset_date_and_replacement(db_session):
    from datetime import timedelta

    from src.controller.lifecycle_fields import utc_today

    product, replacement = _product(db_session), _product(db_session)
    sunset = (utc_today() + timedelta(days=20)).isoformat()
    context = TriggerContext(
        entity_type='data_product', entity_id=product.id, entity_name=product.name,
        trigger_type=TriggerType.ON_REQUEST_STATUS_CHANGE, user_email='requester@example.com',
        from_status='active', to_status='deprecated',
        entity_data={'target_status': 'deprecated', 'justification': 'Moving to v2',
                     'sunset_date': sunset, 'replacement_id': replacement.id},
    )
    workflow = SimpleNamespace(
        name='Status Change Request',
        trigger=SimpleNamespace(type=TriggerType.ON_REQUEST_STATUS_CHANGE),
    )
    WorkflowExecutor(db_session)._handle_workflow_completion(
        trigger_context=context, workflow=workflow, succeeded=True,
        responded_by='approver@example.com', approved=True,
    )

    db_session.refresh(product)
    assert product.status == 'deprecated'
    assert product.deprecation_reason == 'Moving to v2'
    assert product.sunset_date.isoformat() == sunset
    assert product.replacement_product_id == replacement.id
