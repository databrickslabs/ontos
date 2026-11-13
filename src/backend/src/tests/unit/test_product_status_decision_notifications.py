"""Requester identity handling for product status-change decisions."""

import uuid
from unittest.mock import MagicMock

import pytest

from src.controller.change_log_manager import change_log_manager
from src.controller.data_products_manager import DataProductsManager
from src.db_models.data_products import DataProductDb


def _product(db, status='draft'):
    product = DataProductDb(
        id=str(uuid.uuid4()), name='Notification Test Product', version='1.0.0',
        status=status, version_family_id=str(uuid.uuid4()),
    )
    db.add(product)
    db.flush()
    return product


def _request(db, product, requester='stored@example.com'):
    change_log_manager.log_change_with_details(
        db, entity_type='data_product', entity_id=product.id,
        action='status_change_requested', username=requester,
        details={'requester_email': requester, 'target_status': 'proposed'},
    )


def _decide(db, product, decision):
    notifications = MagicMock()
    DataProductsManager(db=db).handle_status_change_response(
        db=db, notifications_manager=notifications, product_id=product.id,
        approver_email='steward@example.com', decision=decision,
        target_status='proposed', current_user='steward@example.com',
    )
    return notifications.create_notification.call_args.kwargs['notification']


@pytest.mark.parametrize('decision', ['approve', 'deny', 'clarify'])
def test_decisions_notify_the_persisted_requester(db_session, decision):
    product = _product(db_session)
    _request(db_session, product)

    notification = _decide(db_session, product, decision)

    assert notification.recipient == 'stored@example.com'
    expected_title = {
        'approve': 'Product Status Change Approved',
        'deny': 'Product Status Change Denied',
        'clarify': 'Product Status Change - Clarification Needed',
    }
    assert notification.title == expected_title[decision]


def test_lookup_failure_is_logged_and_notification_is_skipped(
    db_session, monkeypatch, caplog,
):
    product = _product(db_session)

    def fail_lookup(*_args, **_kwargs):
        raise RuntimeError('lookup unavailable')

    monkeypatch.setattr(change_log_manager, 'get_changes_for_entity', fail_lookup)

    notifications = MagicMock()
    DataProductsManager(db=db_session).handle_status_change_response(
        db=db_session, notifications_manager=notifications, product_id=product.id,
        approver_email='steward@example.com', decision='clarify',
        target_status='proposed', current_user='steward@example.com',
    )

    notifications.create_notification.assert_not_called()
    assert 'Failed to read requester' in caplog.text


def test_missing_requester_is_logged_and_notification_is_skipped(
    db_session, caplog,
):
    product = _product(db_session)
    notifications = MagicMock()

    DataProductsManager(db=db_session).handle_status_change_response(
        db=db_session, notifications_manager=notifications, product_id=product.id,
        approver_email='steward@example.com', decision='deny',
        target_status='proposed', current_user='steward@example.com',
    )

    notifications.create_notification.assert_not_called()
    assert 'No requester found' in caplog.text
