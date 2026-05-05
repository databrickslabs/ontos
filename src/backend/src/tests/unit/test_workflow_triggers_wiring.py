# Set test environment variables BEFORE any app imports
import os
os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

"""
Tests for workflow trigger wiring — verifies that trigger registry methods
are called with correct entity types and parameters.

Part of issue #200: wire missing trigger types across entity lifecycle.
"""

import pytest
from unittest.mock import MagicMock, patch, call
from uuid import uuid4

from src.common.workflow_triggers import TriggerRegistry
from src.models.process_workflows import TriggerType, EntityType


class TestTriggerWiringDataContract:
    """Verify that data_contract triggers fire with correct EntityType."""

    def test_on_create_fires_for_data_contract(self):
        """on_create should fire with EntityType.DATA_CONTRACT."""
        db = MagicMock()
        registry = TriggerRegistry(db)
        registry.fire_trigger = MagicMock(return_value=[])

        registry.on_create(
            entity_type=EntityType.DATA_CONTRACT,
            entity_id="contract-123",
            entity_name="Test Contract",
            entity_data={"name": "Test Contract"},
            user_email="user@example.com",
            blocking=False,
        )

        registry.fire_trigger.assert_called_once()
        event = registry.fire_trigger.call_args[0][0]
        assert event.trigger_type == TriggerType.ON_CREATE
        assert event.entity_type == EntityType.DATA_CONTRACT
        assert event.entity_id == "contract-123"

    def test_on_update_fires_for_data_contract(self):
        """on_update should fire with EntityType.DATA_CONTRACT."""
        db = MagicMock()
        registry = TriggerRegistry(db)
        registry.fire_trigger = MagicMock(return_value=[])

        registry.on_update(
            entity_type=EntityType.DATA_CONTRACT,
            entity_id="contract-123",
            entity_name="Test Contract",
            entity_data={"name": "Updated"},
            user_email="user@example.com",
            blocking=False,
        )

        event = registry.fire_trigger.call_args[0][0]
        assert event.trigger_type == TriggerType.ON_UPDATE
        assert event.entity_type == EntityType.DATA_CONTRACT

    def test_on_delete_fires_for_data_contract(self):
        """on_delete should fire with EntityType.DATA_CONTRACT."""
        db = MagicMock()
        registry = TriggerRegistry(db)
        registry.fire_trigger = MagicMock(return_value=[])

        registry.on_delete(
            entity_type=EntityType.DATA_CONTRACT,
            entity_id="contract-123",
            blocking=False,
        )

        event = registry.fire_trigger.call_args[0][0]
        assert event.trigger_type == TriggerType.ON_DELETE
        assert event.entity_type == EntityType.DATA_CONTRACT

    def test_before_update_fires_for_data_contract(self):
        """before_update should fire with EntityType.DATA_CONTRACT and return tuple."""
        db = MagicMock()
        registry = TriggerRegistry(db)
        registry.fire_trigger = MagicMock(return_value=[])

        all_passed, executions = registry.before_update(
            entity_type=EntityType.DATA_CONTRACT,
            entity_id="contract-123",
            entity_name="Test",
            entity_data={"name": "Updated"},
            user_email="user@example.com",
        )

        assert all_passed is True  # No workflows = pass
        assert executions == []
        event = registry.fire_trigger.call_args[0][0]
        assert event.trigger_type == TriggerType.BEFORE_UPDATE

    def test_on_status_change_fires_for_data_contract(self):
        """on_status_change should fire with from/to status."""
        db = MagicMock()
        registry = TriggerRegistry(db)
        registry.fire_trigger = MagicMock(return_value=[])

        registry.on_status_change(
            entity_type=EntityType.DATA_CONTRACT,
            entity_id="contract-123",
            from_status="draft",
            to_status="active",
            entity_name="Test",
            blocking=False,
        )

        event = registry.fire_trigger.call_args[0][0]
        assert event.trigger_type == TriggerType.ON_STATUS_CHANGE
        assert event.entity_type == EntityType.DATA_CONTRACT
        assert event.from_status == "draft"
        assert event.to_status == "active"


class TestTriggerWiringDataProduct:
    """Verify that data_product triggers fire with correct EntityType."""

    def test_on_create_fires_for_data_product(self):
        db = MagicMock()
        registry = TriggerRegistry(db)
        registry.fire_trigger = MagicMock(return_value=[])

        registry.on_create(
            entity_type=EntityType.DATA_PRODUCT,
            entity_id="product-123",
            entity_name="Test Product",
            blocking=False,
        )

        event = registry.fire_trigger.call_args[0][0]
        assert event.trigger_type == TriggerType.ON_CREATE
        assert event.entity_type == EntityType.DATA_PRODUCT

    def test_on_update_fires_for_data_product(self):
        db = MagicMock()
        registry = TriggerRegistry(db)
        registry.fire_trigger = MagicMock(return_value=[])

        registry.on_update(
            entity_type=EntityType.DATA_PRODUCT,
            entity_id="product-123",
            blocking=False,
        )

        event = registry.fire_trigger.call_args[0][0]
        assert event.trigger_type == TriggerType.ON_UPDATE
        assert event.entity_type == EntityType.DATA_PRODUCT

    def test_on_delete_fires_for_data_product(self):
        db = MagicMock()
        registry = TriggerRegistry(db)
        registry.fire_trigger = MagicMock(return_value=[])

        registry.on_delete(
            entity_type=EntityType.DATA_PRODUCT,
            entity_id="product-123",
            blocking=False,
        )

        event = registry.fire_trigger.call_args[0][0]
        assert event.trigger_type == TriggerType.ON_DELETE
        assert event.entity_type == EntityType.DATA_PRODUCT

    def test_on_status_change_fires_for_data_product(self):
        db = MagicMock()
        registry = TriggerRegistry(db)
        registry.fire_trigger = MagicMock(return_value=[])

        registry.on_status_change(
            entity_type=EntityType.DATA_PRODUCT,
            entity_id="product-123",
            from_status="draft",
            to_status="published",
            blocking=False,
        )

        event = registry.fire_trigger.call_args[0][0]
        assert event.trigger_type == TriggerType.ON_STATUS_CHANGE
        assert event.entity_type == EntityType.DATA_PRODUCT
        assert event.from_status == "draft"
        assert event.to_status == "published"


class TestTriggerWiringDomain:
    """Verify that domain triggers fire with correct EntityType."""

    def test_on_create_fires_for_domain(self):
        db = MagicMock()
        registry = TriggerRegistry(db)
        registry.fire_trigger = MagicMock(return_value=[])

        registry.on_create(
            entity_type=EntityType.DOMAIN,
            entity_id="domain-123",
            entity_name="Customer Analytics",
            blocking=False,
        )

        event = registry.fire_trigger.call_args[0][0]
        assert event.trigger_type == TriggerType.ON_CREATE
        assert event.entity_type == EntityType.DOMAIN

    def test_on_update_fires_for_domain(self):
        db = MagicMock()
        registry = TriggerRegistry(db)
        registry.fire_trigger = MagicMock(return_value=[])

        registry.on_update(
            entity_type=EntityType.DOMAIN,
            entity_id="domain-123",
            blocking=False,
        )

        event = registry.fire_trigger.call_args[0][0]
        assert event.trigger_type == TriggerType.ON_UPDATE
        assert event.entity_type == EntityType.DOMAIN

    def test_on_delete_fires_for_domain(self):
        db = MagicMock()
        registry = TriggerRegistry(db)
        registry.fire_trigger = MagicMock(return_value=[])

        registry.on_delete(
            entity_type=EntityType.DOMAIN,
            entity_id="domain-123",
            blocking=False,
        )

        event = registry.fire_trigger.call_args[0][0]
        assert event.trigger_type == TriggerType.ON_DELETE
        assert event.entity_type == EntityType.DOMAIN


class TestTriggerWiringSubscription:
    """Verify that subscription triggers fire with correct EntityType."""

    def test_on_subscribe_fires_for_subscription(self):
        db = MagicMock()
        registry = TriggerRegistry(db)
        registry.fire_trigger = MagicMock(return_value=[])

        registry.on_subscribe(
            entity_type=EntityType.SUBSCRIPTION,
            entity_id="sub-123",
            entity_name="product-456",
            entity_data={"product_id": "product-456", "subscriber_email": "user@test.com"},
            user_email="user@test.com",
            blocking=False,
        )

        event = registry.fire_trigger.call_args[0][0]
        assert event.trigger_type == TriggerType.ON_SUBSCRIBE
        assert event.entity_type == EntityType.SUBSCRIPTION
        assert event.entity_data["subscriber_email"] == "user@test.com"

    def test_on_unsubscribe_fires_for_subscription(self):
        db = MagicMock()
        registry = TriggerRegistry(db)
        registry.fire_trigger = MagicMock(return_value=[])

        registry.on_unsubscribe(
            entity_type=EntityType.SUBSCRIPTION,
            entity_id="product-456",
            user_email="user@test.com",
            blocking=False,
        )

        event = registry.fire_trigger.call_args[0][0]
        assert event.trigger_type == TriggerType.ON_UNSUBSCRIBE
        assert event.entity_type == EntityType.SUBSCRIPTION


class TestTriggerWiringCertification:
    """Verify decertify trigger for data_contract (newly wired)."""

    def test_on_decertify_fires_for_data_contract(self):
        db = MagicMock()
        registry = TriggerRegistry(db)
        registry.fire_trigger = MagicMock(return_value=[])

        registry.on_decertify(
            entity_type=EntityType.DATA_CONTRACT,
            entity_id="contract-123",
            entity_name="Test Contract",
            user_email="admin@test.com",
            blocking=False,
        )

        event = registry.fire_trigger.call_args[0][0]
        assert event.trigger_type == TriggerType.ON_DECERTIFY
        assert event.entity_type == EntityType.DATA_CONTRACT

    def test_on_unpublish_fires_for_data_contract(self):
        db = MagicMock()
        registry = TriggerRegistry(db)
        registry.fire_trigger = MagicMock(return_value=[])

        registry.on_unpublish(
            entity_type=EntityType.DATA_CONTRACT,
            entity_id="contract-123",
            entity_name="Test Contract",
            user_email="admin@test.com",
            blocking=False,
        )

        event = registry.fire_trigger.call_args[0][0]
        assert event.trigger_type == TriggerType.ON_UNPUBLISH
        assert event.entity_type == EntityType.DATA_CONTRACT
