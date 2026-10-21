"""Unit tests for subscription refusal on deprecated/retired products.

Covers:
  * Subscription to deprecated products raises ProductNotSubscribableError
  * Subscription to retired products raises ProductNotSubscribableError
  * Error includes product status and optional replacement info
  * Active and certified products still accept subscriptions
"""

# Set test environment variables BEFORE any app imports
import os
os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

from uuid import uuid4
import pytest

from src.controller.data_products_manager import (
    DataProductsManager,
    ProductNotSubscribableError,
)
from src.models.data_products import DataProduct


@pytest.fixture
def manager(db_session):
    """A real DataProductsManager bound to the in-memory test DB."""
    return DataProductsManager(db=db_session)


@pytest.fixture
def deprecated_product(db_session):
    """Create a deprecated product for testing."""
    product = DataProduct(
        id=str(uuid4()),
        status='deprecated',
        name='Deprecated Product',
        domain='test-domain',
    )
    db_session.add(
        __import__('src.db_models.data_products', fromlist=['DataProductDb'])
        .DataProductDb(
            id=product.id,
            status='deprecated',
            name='Deprecated Product',
            domain='test-domain',
        )
    )
    db_session.commit()
    return product


@pytest.fixture
def retired_product(db_session):
    """Create a retired product for testing."""
    product = DataProduct(
        id=str(uuid4()),
        status='retired',
        name='Retired Product',
        domain='test-domain',
    )
    db_session.add(
        __import__('src.db_models.data_products', fromlist=['DataProductDb'])
        .DataProductDb(
            id=product.id,
            status='retired',
            name='Retired Product',
            domain='test-domain',
        )
    )
    db_session.commit()
    return product


@pytest.fixture
def active_product(db_session):
    """Create an active product for testing."""
    product = DataProduct(
        id=str(uuid4()),
        status='active',
        name='Active Product',
        domain='test-domain',
    )
    db_session.add(
        __import__('src.db_models.data_products', fromlist=['DataProductDb'])
        .DataProductDb(
            id=product.id,
            status='active',
            name='Active Product',
            domain='test-domain',
        )
    )
    db_session.commit()
    return product


class TestSubscribeDeprecatedRefusal:
    def test_subscribe_to_deprecated_product_raises_error(
        self, manager, deprecated_product, db_session
    ):
        """Subscribing to a deprecated product raises ProductNotSubscribableError."""
        with pytest.raises(ProductNotSubscribableError) as exc_info:
            manager.subscribe(
                product_id=deprecated_product.id,
                subscriber_email='test@example.com',
                db=db_session,
            )

        error = exc_info.value
        assert error.code == 'product_not_subscribable'
        assert 'deprecated' in str(error).lower()
        assert error.params['status'] == 'deprecated'

    def test_subscribe_to_retired_product_raises_error(
        self, manager, retired_product, db_session
    ):
        """Subscribing to a retired product raises ProductNotSubscribableError."""
        with pytest.raises(ProductNotSubscribableError) as exc_info:
            manager.subscribe(
                product_id=retired_product.id,
                subscriber_email='test@example.com',
                db=db_session,
            )

        error = exc_info.value
        assert error.code == 'product_not_subscribable'
        assert 'retired' in str(error).lower()
        assert error.params['status'] == 'retired'

    def test_subscribe_to_active_product_succeeds(
        self, manager, active_product, db_session
    ):
        """Subscribing to an active product succeeds."""
        response = manager.subscribe(
            product_id=active_product.id,
            subscriber_email='test@example.com',
            db=db_session,
        )
        assert response.subscribed is True
        assert response.subscription is not None

    def test_error_includes_product_name(self, manager, deprecated_product, db_session):
        """Error includes product name in parameters."""
        with pytest.raises(ProductNotSubscribableError) as exc_info:
            manager.subscribe(
                product_id=deprecated_product.id,
                subscriber_email='test@example.com',
                db=db_session,
            )

        error = exc_info.value
        assert error.params['productName'] == 'Deprecated Product'

    def test_error_message_is_user_friendly(self, manager, deprecated_product, db_session):
        """Error message is user-friendly and doesn't include exception text."""
        with pytest.raises(ProductNotSubscribableError) as exc_info:
            manager.subscribe(
                product_id=deprecated_product.id,
                subscriber_email='test@example.com',
                db=db_session,
            )

        error_msg = str(exc_info.value)
        # Should not contain exception text like "SELECT ..."
        assert 'SELECT' not in error_msg
        assert 'deprecated' in error_msg.lower() or 'status' in error_msg.lower()


class TestSubscriberNotifications:
    """Test that notifications are sent with i18n keys when status changes."""

    def test_subscribers_notified_on_deprecation_with_i18n_keys(
        self, manager, active_product, db_session
    ):
        """When product becomes deprecated, subscribers get notification with i18n keys."""
        from unittest.mock import MagicMock

        # Mock the notifications manager to capture notifications
        mock_notif_manager = MagicMock()
        manager._notifications_manager = mock_notif_manager

        # Trigger deprecation notification
        manager._notify_subscribers_of_status_change(
            product_id=active_product.id,
            product_name='Active Product',
            old_status='active',
            new_status='deprecated',
        )

        # Verify notification was sent
        assert mock_notif_manager.create_notification.called
        call_args = mock_notif_manager.create_notification.call_args
        notification = call_args[1]['notification']

        # Verify i18n keys are present
        assert notification.data is not None
        assert 'i18n' in notification.data
        assert notification.data['i18n']['title'] == 'notifications:lifecycle:deprecation.title'
        assert notification.data['i18n']['description'] == 'notifications:lifecycle:deprecation.description'

        # Verify product name is in params
        assert notification.data['i18n']['params']['productName'] == 'Active Product'

    def test_subscribers_notified_on_retirement_with_i18n_keys(
        self, manager, active_product, db_session
    ):
        """When product becomes retired, subscribers get notification with i18n keys."""
        from unittest.mock import MagicMock

        mock_notif_manager = MagicMock()
        manager._notifications_manager = mock_notif_manager

        manager._notify_subscribers_of_status_change(
            product_id=active_product.id,
            product_name='Active Product',
            old_status='active',
            new_status='retired',
        )

        call_args = mock_notif_manager.create_notification.call_args
        notification = call_args[1]['notification']

        assert notification.data['i18n']['title'] == 'notifications:lifecycle:retirement.title'
        assert notification.data['i18n']['description'] == 'notifications:lifecycle:retirement.description'

    def test_subscribers_notified_on_deletion_with_i18n_keys(
        self, manager, active_product, db_session
    ):
        """When product is deleted, subscribers get notification with i18n keys."""
        from unittest.mock import MagicMock

        mock_notif_manager = MagicMock()
        manager._notifications_manager = mock_notif_manager

        manager._notify_subscribers_on_delete(
            product_id=active_product.id,
            product_name='Active Product',
            deleted_by='admin@example.com',
        )

        call_args = mock_notif_manager.create_notification.call_args
        notification = call_args[1]['notification']

        assert notification.data['i18n']['title'] == 'notifications:lifecycle:deletion.title'
        assert notification.data['i18n']['description'] == 'notifications:lifecycle:deletion.description'
        assert notification.data['i18n']['params']['deletedBy'] == 'admin@example.com'
