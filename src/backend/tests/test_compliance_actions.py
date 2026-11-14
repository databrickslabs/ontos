"""Unit tests for Compliance Action System."""

import pytest
from src.common.compliance_actions import (
    Action,
    ActionContext,
    ActionResult,
    PassAction,
    FailAction,
    AssignTagAction,
    RemoveTagAction,
    NotifyAction,
    ActionRegistry,
    ActionExecutor,
    get_action_registry,
    register_action,
)


class MockTagManager:
    """Mock tag manager for testing."""

    def __init__(self):
        self.assigned_tags = []
        self.removed_tags = []

    def assign_tag(self, entity_type: str, entity_id: str, key: str, value: str):
        self.assigned_tags.append({
            'entity_type': entity_type,
            'entity_id': entity_id,
            'key': key,
            'value': value
        })

    def remove_tag(self, entity_type: str, entity_id: str, key: str):
        self.removed_tags.append({
            'entity_type': entity_type,
            'entity_id': entity_id,
            'key': key
        })


class MockNotificationManager:
    """Mock notification manager for testing."""

    def __init__(self):
        self.notifications = []

    def send_notification(self, recipients: str, message: str, subject: str):
        self.notifications.append({
            'recipients': recipients,
            'message': message,
            'subject': subject
        })


class TestActions:
    """Test individual action classes."""

    def test_pass_action(self):
        """Test PassAction."""
        action = PassAction()
        context = ActionContext(
            entity={'name': 'test'},
            entity_type='table',
            entity_id='test_table',
            rule_id='rule1',
            rule_name='Test Rule',
            passed=True
        )

        result = action.execute(context)

        assert result.success is True
        assert result.action_type == 'PASS'

    def test_fail_action_with_message(self):
        """Test FailAction with custom message."""
        action = FailAction(message='Custom failure message')
        context = ActionContext(
            entity={'name': 'test'},
            entity_type='table',
            entity_id='test_table',
            rule_id='rule1',
            rule_name='Test Rule',
            passed=False
        )

        result = action.execute(context)

        assert result.success is False
        assert result.action_type == 'FAIL'
        assert 'Custom failure message' in result.message

    def test_fail_action_without_message(self):
        """Test FailAction without custom message."""
        action = FailAction()
        context = ActionContext(
            entity={'name': 'test'},
            entity_type='table',
            entity_id='test_table',
            rule_id='rule1',
            rule_name='Test Rule',
            passed=False,
            message='Context message'
        )

        result = action.execute(context)

        assert result.success is False
        assert 'Context message' in result.message

    def test_assign_tag_action(self):
        """Test AssignTagAction."""
        tag_manager = MockTagManager()
        action = AssignTagAction(key='compliance', value='passed')
        context = ActionContext(
            entity={'name': 'test'},
            entity_type='table',
            entity_id='test_table',
            rule_id='rule1',
            rule_name='Test Rule',
            passed=True,
            tag_manager=tag_manager
        )

        result = action.execute(context)

        assert result.success is True
        assert result.action_type == 'ASSIGN_TAG'
        assert len(tag_manager.assigned_tags) == 1
        assert tag_manager.assigned_tags[0]['key'] == 'compliance'
        assert tag_manager.assigned_tags[0]['value'] == 'passed'

    def test_assign_tag_action_no_manager(self):
        """Test AssignTagAction without tag manager."""
        action = AssignTagAction(key='compliance', value='passed')
        context = ActionContext(
            entity={'name': 'test'},
            entity_type='table',
            entity_id='test_table',
            rule_id='rule1',
            rule_name='Test Rule',
            passed=True
        )

        result = action.execute(context)

        assert result.success is False
        assert 'Tag manager not available' in result.error

    def test_remove_tag_action(self):
        """Test RemoveTagAction."""
        tag_manager = MockTagManager()
        action = RemoveTagAction(key='old_tag')
        context = ActionContext(
            entity={'name': 'test'},
            entity_type='table',
            entity_id='test_table',
            rule_id='rule1',
            rule_name='Test Rule',
            passed=True,
            tag_manager=tag_manager
        )

        result = action.execute(context)

        assert result.success is True
        assert result.action_type == 'REMOVE_TAG'
        assert len(tag_manager.removed_tags) == 1
        assert tag_manager.removed_tags[0]['key'] == 'old_tag'

    def test_notify_action(self):
        """Test NotifyAction."""
        notification_manager = MockNotificationManager()
        action = NotifyAction(recipients='admin@example.com')
        context = ActionContext(
            entity={'name': 'test'},
            entity_type='table',
            entity_id='test_table',
            rule_id='rule1',
            rule_name='Test Rule',
            passed=False,
            message='Check failed',
            notification_manager=notification_manager
        )

        result = action.execute(context)

        assert result.success is True
        assert result.action_type == 'NOTIFY'
        assert len(notification_manager.notifications) == 1
        assert notification_manager.notifications[0]['recipients'] == 'admin@example.com'
        assert 'Test Rule' in notification_manager.notifications[0]['subject']


class TestActionRegistry:
    """Test action registry."""

    def test_create_action_pass(self):
        """Test creating PASS action."""
        registry = ActionRegistry()
        action_def = {'type': 'PASS'}

        action = registry.create_action(action_def)

        assert isinstance(action, PassAction)

    def test_create_action_fail(self):
        """Test creating FAIL action."""
        registry = ActionRegistry()
        action_def = {'type': 'FAIL', 'message': 'Test failure'}

        action = registry.create_action(action_def)

        assert isinstance(action, FailAction)
        assert action.custom_message == 'Test failure'

    def test_create_action_assign_tag(self):
        """Test creating ASSIGN_TAG action."""
        registry = ActionRegistry()
        action_def = {'type': 'ASSIGN_TAG', 'key': 'status', 'value': 'reviewed'}

        action = registry.create_action(action_def)

        assert isinstance(action, AssignTagAction)
        assert action.key == 'status'
        assert action.value == 'reviewed'

    def test_create_action_unknown_type(self):
        """Test creating action with unknown type."""
        registry = ActionRegistry()
        action_def = {'type': 'UNKNOWN'}

        with pytest.raises(ValueError):
            registry.create_action(action_def)

    def test_register_custom_action(self):
        """Test registering custom action."""
        class CustomAction(Action):
            def execute(self, context):
                return ActionResult(success=True, action_type='CUSTOM')

        registry = ActionRegistry()
        registry.register('CUSTOM', CustomAction)

        action_def = {'type': 'CUSTOM'}
        action = registry.create_action(action_def)

        assert isinstance(action, CustomAction)

    def test_list_actions(self):
        """Test listing registered actions."""
        registry = ActionRegistry()
        actions = registry.list_actions()

        assert 'PASS' in actions
        assert 'FAIL' in actions
        assert 'ASSIGN_TAG' in actions
        assert 'REMOVE_TAG' in actions
        assert 'NOTIFY' in actions


class TestActionExecutor:
    """Test action executor."""

    def test_execute_single_action(self):
        """Test executing single action."""
        executor = ActionExecutor()
        action_defs = [{'type': 'PASS'}]
        context = ActionContext(
            entity={'name': 'test'},
            entity_type='table',
            entity_id='test_table',
            rule_id='rule1',
            rule_name='Test Rule',
            passed=True
        )

        results = executor.execute_actions(action_defs, context)

        assert len(results) == 1
        assert results[0].success is True
        assert results[0].action_type == 'PASS'

    def test_execute_multiple_actions(self):
        """Test executing multiple actions."""
        tag_manager = MockTagManager()
        notification_manager = MockNotificationManager()

        executor = ActionExecutor()
        action_defs = [
            {'type': 'FAIL', 'message': 'Check failed'},
            {'type': 'ASSIGN_TAG', 'key': 'status', 'value': 'failed'},
            {'type': 'NOTIFY', 'recipients': 'admin@example.com'}
        ]
        context = ActionContext(
            entity={'name': 'test'},
            entity_type='table',
            entity_id='test_table',
            rule_id='rule1',
            rule_name='Test Rule',
            passed=False,
            tag_manager=tag_manager,
            notification_manager=notification_manager
        )

        results = executor.execute_actions(action_defs, context)

        assert len(results) == 3
        assert results[0].action_type == 'FAIL'
        assert results[1].action_type == 'ASSIGN_TAG'
        assert results[2].action_type == 'NOTIFY'
        assert len(tag_manager.assigned_tags) == 1
        assert len(notification_manager.notifications) == 1

    def test_execute_actions_with_error(self):
        """Test executing actions with error."""
        executor = ActionExecutor()
        action_defs = [
            {'type': 'UNKNOWN'}  # Invalid action type
        ]
        context = ActionContext(
            entity={'name': 'test'},
            entity_type='table',
            entity_id='test_table',
            rule_id='rule1',
            rule_name='Test Rule',
            passed=True
        )

        results = executor.execute_actions(action_defs, context)

        assert len(results) == 1
        assert results[0].success is False
        assert results[0].error is not None
        assert results[0].code == 'action_failed'
        assert 'UNKNOWN' not in results[0].error


class TestGlobalRegistry:
    """Test global action registry."""

    def test_get_global_registry(self):
        """Test getting global registry."""
        registry1 = get_action_registry()
        registry2 = get_action_registry()

        # Should be the same instance
        assert registry1 is registry2

    def test_register_global_action(self):
        """Test registering action globally."""
        class GlobalCustomAction(Action):
            def execute(self, context):
                return ActionResult(success=True, action_type='GLOBAL_CUSTOM')

        register_action('GLOBAL_CUSTOM', GlobalCustomAction)

        registry = get_action_registry()
        actions = registry.list_actions()

        assert 'GLOBAL_CUSTOM' in actions


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
