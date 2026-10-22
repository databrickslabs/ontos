"""Unit tests for the lifecycle notices to subscribers (I-23, #998).

Covers:
  * Subscribing to a deprecated or retired product is refused with the coded
    error ``product_not_subscribable`` (status and product name as params)
  * Active and certified products still accept subscriptions
  * Subscribers get a translatable notification (``data.i18n``) when a product
    is deprecated, retired or deleted, and only those
  * The deletion notice is sent only after the delete is committed: a failed
    delete (repository or commit error) notifies nobody
"""

# Set test environment variables BEFORE any app imports
import os
os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.exc import OperationalError

from src.controller.data_products_manager import (
    DataProductsManager,
    ProductNotSubscribableError,
)
from src.db_models.data_products import DataProductDb

SUBSCRIBER = 'sub@example.com'


@pytest.fixture
def manager(db_session):
    """A real DataProductsManager bound to the in-memory test DB."""
    return DataProductsManager(db=db_session)


@pytest.fixture
def make_product(db_session):
    def _make(status: str, name: str) -> str:
        product_id = str(uuid4())
        db_session.add(DataProductDb(id=product_id, status=status, name=name))
        db_session.commit()
        return product_id
    return _make


def _sent(notifications_manager):
    """The notifications handed to ``create_notification``."""
    calls = notifications_manager.create_notification.call_args_list
    return [c.kwargs['notification'] for c in calls]


class TestSubscribeRefusal:
    @pytest.mark.parametrize('status', ['deprecated', 'retired'])
    def test_refused_with_coded_error(self, manager, make_product, db_session, status):
        product_id = make_product(status, 'Old Product')
        with pytest.raises(ProductNotSubscribableError) as exc_info:
            manager.subscribe(product_id=product_id, subscriber_email=SUBSCRIBER, db=db_session)

        error = exc_info.value
        assert error.code == 'product_not_subscribable'
        assert error.params['status'] == status
        assert error.params['productName'] == 'Old Product'
        assert status in str(error)

    def test_refusal_is_a_value_error(self, manager, make_product, db_session):
        # The route turns a ValueError into a 400 whose detail carries code and params.
        product_id = make_product('deprecated', 'Old Product')
        with pytest.raises(ValueError):
            manager.subscribe(product_id=product_id, subscriber_email=SUBSCRIBER, db=db_session)

    @pytest.mark.parametrize('status', ['active', 'certified'])
    def test_active_and_certified_accept_subscriptions(
        self, manager, make_product, db_session, status
    ):
        product_id = make_product(status, 'Good Product')
        response = manager.subscribe(
            product_id=product_id, subscriber_email=SUBSCRIBER, db=db_session
        )
        assert response.subscribed is True


class TestSubscriberNotices:
    @pytest.fixture
    def notifications(self, manager):
        notifications_manager = MagicMock()
        manager._notifications_manager = notifications_manager
        return notifications_manager

    def _subscribed(self, manager, make_product, db_session, name='Active Product'):
        product_id = make_product('active', name)
        manager.subscribe(product_id=product_id, subscriber_email=SUBSCRIBER, db=db_session)
        return product_id

    @pytest.mark.parametrize('new_status,key,kind', [
        ('deprecated', 'deprecation', 'WARNING'),
        ('retired', 'retirement', 'ACTION_REQUIRED'),
        ('active', 'activation', 'INFO'),
        ('certified', 'certification', 'SUCCESS'),
    ])
    def test_status_change_notifies_with_i18n_keys(
        self, manager, make_product, db_session, notifications, new_status, key, kind
    ):
        product_id = self._subscribed(manager, make_product, db_session)

        manager._notify_subscribers_of_status_change(
            product_id=product_id, product_name='Active Product',
            old_status='draft', new_status=new_status,
        )

        (notification,) = _sent(notifications)
        assert notification.recipient == SUBSCRIBER
        assert notification.type.name == kind
        i18n = notification.data['i18n']
        assert i18n['title'] == f'notifications:lifecycle.{key}.title'
        assert i18n['description'] == f'notifications:lifecycle.{key}.description'
        assert i18n['params']['productName'] == 'Active Product'

    @pytest.mark.parametrize('new_status', ['draft', 'proposed', 'under_review', 'approved'])
    def test_other_status_changes_do_not_notify(
        self, manager, make_product, db_session, notifications, new_status
    ):
        product_id = self._subscribed(manager, make_product, db_session)
        manager._notify_subscribers_of_status_change(
            product_id=product_id, product_name='Active Product',
            old_status='deprecated', new_status=new_status,
        )
        assert _sent(notifications) == []

    def test_delete_notifies_subscribers_read_before_the_rows_cascade(
        self, manager, make_product, db_session, notifications
    ):
        product_id = self._subscribed(manager, make_product, db_session, 'Doomed Product')

        assert manager.delete_product(product_id, user='admin@example.com') is True

        (notification,) = _sent(notifications)
        assert notification.recipient == SUBSCRIBER
        i18n = notification.data['i18n']
        assert i18n['title'] == 'notifications:lifecycle.deletion.title'
        assert i18n['description'] == 'notifications:lifecycle.deletion.description'
        assert i18n['params']['productName'] == 'Doomed Product'
        assert i18n['params']['deletedBy'] == 'admin@example.com'
        assert manager.get_product(product_id) is None

    def test_delete_still_succeeds_when_notifying_fails(
        self, manager, make_product, db_session, notifications
    ):
        product_id = self._subscribed(manager, make_product, db_session)
        notifications.create_notification.side_effect = RuntimeError('boom')
        assert manager.delete_product(product_id) is True


class TestDeletionNoticeAfterCommit:
    """The deletion notice goes out only once the delete is persisted (#1173 review)."""

    @pytest.fixture
    def notifications(self, manager):
        notifications_manager = MagicMock()
        manager._notifications_manager = notifications_manager
        return notifications_manager

    @pytest.fixture
    def subscribed(self, manager, make_product, db_session):
        product_id = make_product('active', 'Doomed Product')
        manager.subscribe(product_id=product_id, subscriber_email=SUBSCRIBER, db=db_session)
        return product_id

    def test_failed_repository_delete_sends_no_notice(
        self, manager, db_session, notifications, subscribed, monkeypatch
    ):
        def failing_remove(*args, **kwargs):
            raise OperationalError('DELETE FROM data_products', {}, Exception('db down'))

        monkeypatch.setattr(manager._repo, 'remove', failing_remove)

        with pytest.raises(OperationalError):
            manager.delete_product(subscribed, user='admin@example.com')

        assert _sent(notifications) == []

    def test_failed_commit_sends_no_notice(
        self, manager, db_session, notifications, subscribed, monkeypatch
    ):
        def failing_commit():
            raise OperationalError('COMMIT', {}, Exception('connection lost'))

        monkeypatch.setattr(db_session, 'commit', failing_commit)

        with pytest.raises(OperationalError):
            manager.delete_product(subscribed, user='admin@example.com')

        assert _sent(notifications) == []

    def test_successful_delete_notifies_once_after_the_commit(
        self, manager, db_session, notifications, subscribed, monkeypatch
    ):
        events = []
        real_commit = db_session.commit
        real_remove = manager._repo.remove

        def recording_commit():
            events.append('commit')
            real_commit()

        def recording_remove(*args, **kwargs):
            events.append('remove')
            return real_remove(*args, **kwargs)

        monkeypatch.setattr(db_session, 'commit', recording_commit)
        monkeypatch.setattr(manager._repo, 'remove', recording_remove)
        notifications.create_notification.side_effect = (
            lambda **kwargs: events.append('notify')
        )

        assert manager.delete_product(subscribed, user='admin@example.com') is True

        (notification,) = _sent(notifications)
        assert notification.recipient == SUBSCRIBER
        assert notification.data['i18n']['params']['productName'] == 'Doomed Product'
        assert events.count('notify') == 1
        remove_at, notify_at = events.index('remove'), events.index('notify')
        assert remove_at < notify_at
        assert 'commit' in events[remove_at:notify_at], events
        # The notices are committed too (the delete's commit came before them).
        assert events[-1] == 'commit', events
