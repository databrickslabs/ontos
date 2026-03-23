# Set test environment variables BEFORE any app imports
import os
os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import pytest
from unittest.mock import MagicMock, patch
from uuid import uuid4

from src.common.workflow_executor import (
    AssignTagStepHandler,
    RemoveTagStepHandler,
    StepContext,
    StepResult,
)
from src.models.process_workflows import TriggerContext


def _make_context(**overrides) -> StepContext:
    """Build a minimal StepContext for testing."""
    defaults = dict(
        entity={'name': 'test_table', 'status': 'draft'},
        entity_type='table',
        entity_id='entity-123',
        entity_name='test_table',
        user_email='user@example.com',
        trigger_context=None,
        execution_id='exec-1',
        workflow_id='wf-1',
        workflow_name='Test Workflow',
        step_results={},
    )
    defaults.update(overrides)
    return StepContext(**defaults)


# =========================================================================
# AssignTagStepHandler
# =========================================================================

class TestAssignTagPersistence:
    """User Story 11: Tag assignment step persists to database."""

    def test_assign_tag_persists_to_database(self, db_session):
        """When TagsManager finds the tag by FQN, it should call add_tag_to_entity
        and return persisted=True."""
        mock_tag = MagicMock()
        mock_tag.id = uuid4()

        with patch('src.controller.tags_manager.TagsManager') as MockTM:
            mock_mgr = MagicMock()
            MockTM.return_value = mock_mgr
            mock_mgr.get_tag_by_fqn.return_value = mock_tag

            handler = AssignTagStepHandler(db=db_session, config={'key': 'ns.pii', 'value': 'true'})
            result = handler.execute(_make_context())

        assert result.passed is True
        assert result.data['persisted'] is True
        assert result.data['key'] == 'ns.pii'
        assert result.data['value'] == 'true'
        mock_mgr.add_tag_to_entity.assert_called_once()

    def test_assign_tag_falls_back_when_fqn_not_found(self, db_session):
        """When tag FQN doesn't exist, should still pass but persisted=False."""
        with patch('src.controller.tags_manager.TagsManager') as MockTM:
            mock_mgr = MagicMock()
            MockTM.return_value = mock_mgr
            mock_mgr.get_tag_by_fqn.return_value = None

            handler = AssignTagStepHandler(db=db_session, config={'key': 'ns.nonexistent', 'value': 'x'})
            result = handler.execute(_make_context())

        assert result.passed is True
        assert result.data['persisted'] is False
        mock_mgr.add_tag_to_entity.assert_not_called()

    def test_assign_tag_falls_back_on_tags_manager_error(self, db_session):
        """When TagsManager throws, should still pass with persisted=False."""
        with patch('src.controller.tags_manager.TagsManager') as MockTM:
            MockTM.side_effect = RuntimeError("DB unavailable")

            handler = AssignTagStepHandler(db=db_session, config={'key': 'ns.tag', 'value': 'v'})
            result = handler.execute(_make_context())

        assert result.passed is True
        assert result.data['persisted'] is False

    def test_assign_tag_updates_context_for_downstream(self, db_session):
        """In-memory context must be updated regardless of persistence."""
        with patch('src.controller.tags_manager.TagsManager') as MockTM:
            mock_mgr = MagicMock()
            MockTM.return_value = mock_mgr
            mock_mgr.get_tag_by_fqn.return_value = None  # FQN not found

            ctx = _make_context(entity={'name': 'tbl'})
            handler = AssignTagStepHandler(db=db_session, config={'key': 'owner', 'value': 'alice'})
            handler.execute(ctx)

        assert ctx.entity['tags']['owner'] == 'alice'

    def test_assign_tag_resolves_value_source(self, db_session):
        """value_source='current_user' should resolve to context.user_email."""
        with patch('src.controller.tags_manager.TagsManager') as MockTM:
            mock_mgr = MagicMock()
            MockTM.return_value = mock_mgr
            mock_mgr.get_tag_by_fqn.return_value = None

            handler = AssignTagStepHandler(
                db=db_session,
                config={'key': 'assigned_to', 'value_source': 'current_user'},
            )
            result = handler.execute(_make_context(user_email='bob@acme.com'))

        assert result.passed is True
        assert result.data['value'] == 'bob@acme.com'

    def test_assign_tag_fails_without_key(self, db_session):
        """Missing 'key' config should fail the step."""
        handler = AssignTagStepHandler(db=db_session, config={'value': 'x'})
        result = handler.execute(_make_context())

        assert result.passed is False
        assert 'key' in result.error.lower()


# =========================================================================
# RemoveTagStepHandler
# =========================================================================

class TestRemoveTagPersistence:
    """User Story 12: Tag removal step persists to database."""

    def test_remove_tag_persists_to_database(self, db_session):
        """When TagsManager finds the tag, it should call remove_tag_from_entity
        and return persisted=True."""
        mock_tag = MagicMock()
        mock_tag.id = uuid4()

        with patch('src.controller.tags_manager.TagsManager') as MockTM:
            mock_mgr = MagicMock()
            MockTM.return_value = mock_mgr
            mock_mgr.get_tag_by_fqn.return_value = mock_tag
            mock_mgr.remove_tag_from_entity.return_value = True

            ctx = _make_context(entity={'name': 'tbl', 'tags': {'ns.pii': 'true'}})
            handler = RemoveTagStepHandler(db=db_session, config={'key': 'ns.pii'})
            result = handler.execute(ctx)

        assert result.passed is True
        assert result.data['persisted'] is True
        mock_mgr.remove_tag_from_entity.assert_called_once()

    def test_remove_tag_falls_back_when_fqn_not_found(self, db_session):
        """When tag FQN doesn't exist, should still pass but persisted=False."""
        with patch('src.controller.tags_manager.TagsManager') as MockTM:
            mock_mgr = MagicMock()
            MockTM.return_value = mock_mgr
            mock_mgr.get_tag_by_fqn.return_value = None

            ctx = _make_context(entity={'name': 'tbl', 'tags': {'ns.gone': 'x'}})
            handler = RemoveTagStepHandler(db=db_session, config={'key': 'ns.gone'})
            result = handler.execute(ctx)

        assert result.passed is True
        assert result.data['persisted'] is False

    def test_remove_tag_updates_context_for_downstream(self, db_session):
        """In-memory context must have the tag removed."""
        with patch('src.controller.tags_manager.TagsManager') as MockTM:
            mock_mgr = MagicMock()
            MockTM.return_value = mock_mgr
            mock_mgr.get_tag_by_fqn.return_value = None

            ctx = _make_context(entity={'name': 'tbl', 'tags': {'ns.old': 'v'}})
            handler = RemoveTagStepHandler(db=db_session, config={'key': 'ns.old'})
            handler.execute(ctx)

        assert 'ns.old' not in ctx.entity.get('tags', {})

    def test_remove_tag_fails_without_key(self, db_session):
        """Missing 'key' config should fail the step."""
        handler = RemoveTagStepHandler(db=db_session, config={})
        result = handler.execute(_make_context())

        assert result.passed is False
        assert 'key' in result.error.lower()

    def test_remove_tag_result_includes_persisted_boolean(self, db_session):
        """Acceptance criterion: step result data must include 'persisted' field."""
        with patch('src.controller.tags_manager.TagsManager') as MockTM:
            mock_mgr = MagicMock()
            MockTM.return_value = mock_mgr
            mock_mgr.get_tag_by_fqn.return_value = None

            handler = RemoveTagStepHandler(db=db_session, config={'key': 'ns.x'})
            result = handler.execute(_make_context())

        assert 'persisted' in result.data, "RemoveTag result must include 'persisted' boolean"
