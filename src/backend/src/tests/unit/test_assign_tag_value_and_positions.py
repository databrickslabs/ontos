"""Assign-tag step values (#1423, designer part) and step positions (#1419).

- An assign_tag step without a value assigns the tag key-only. It used to fail
  with "Could not resolve tag value", so a key-only tag couldn't be assigned.
- A value source that resolves to nothing is still an error.
- Step positions the designer saves come back unchanged on read and survive a
  steps update, so the designer can show the user's layout instead of
  auto-arranging it.
"""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import uuid
from unittest.mock import MagicMock, patch

import pytest

from src.common.workflow_executor import AssignTagStepHandler, StepContext
from src.controller.workflows_manager import WorkflowsManager
from src.models.process_workflows import (
    EntityType,
    ProcessWorkflowCreate,
    ProcessWorkflowUpdate,
    StepPosition,
    StepType,
    TriggerType,
    WorkflowStepCreate,
    WorkflowTrigger,
)


def _context(**overrides) -> StepContext:
    defaults = dict(
        entity={'name': 'orders'}, entity_type='data_product', entity_id='p-1', entity_name='orders',
        user_email='user@example.com', trigger_context=None, execution_id='exec-1',
        workflow_id='wf-1', workflow_name='wf', step_results={},
    )
    defaults.update(overrides)
    return StepContext(**defaults)


@pytest.fixture
def tags_manager():
    with patch('src.controller.tags_manager.TagsManager') as cls:
        mgr = MagicMock()
        mgr.get_tag_by_fqn.return_value = MagicMock(id=uuid.uuid4())
        cls.return_value = mgr
        yield mgr


class TestAssignTagValues:
    @pytest.mark.parametrize('config', [
        {'key': 'governance/pii'},
        {'key': 'governance/pii', 'value': None},
        {'key': 'governance/pii', 'value': ''},
    ])
    def test_no_value_assigns_the_tag_key_only(self, db_session, tags_manager, config):
        context = _context()

        result = AssignTagStepHandler(db=db_session, config=config).execute(context)

        assert result.passed is True, result.error
        kwargs = tags_manager.add_tag_to_entity.call_args.kwargs
        # None, not '': the tag store keeps a value already stored when none is sent.
        assert kwargs['assigned_value'] is None
        assert result.data == {'key': 'governance/pii', 'value': None, 'persisted': True}
        # Later rule steps see a key-only tag as true, like the compliance loader.
        assert context.entity['tags']['governance/pii'] is True

    def test_fixed_value_is_assigned(self, db_session, tags_manager):
        result = AssignTagStepHandler(
            db=db_session, config={'key': 'governance/classification', 'value': 'confidential'},
        ).execute(_context())

        assert result.passed is True
        assert tags_manager.add_tag_to_entity.call_args.kwargs['assigned_value'] == 'confidential'

    def test_value_source_wins_over_a_fixed_value(self, db_session, tags_manager):
        result = AssignTagStepHandler(
            db=db_session, config={'key': 'owner', 'value': 'ignored', 'value_source': 'current_user'},
        ).execute(_context())

        assert result.passed is True
        assert tags_manager.add_tag_to_entity.call_args.kwargs['assigned_value'] == 'user@example.com'

    @pytest.mark.parametrize('source', ['project_name', 'unknown_source'])
    def test_a_value_source_that_resolves_to_nothing_still_fails(self, db_session, tags_manager, source):
        result = AssignTagStepHandler(
            db=db_session, config={'key': 'owner', 'value_source': source},
        ).execute(_context())

        assert result.passed is False
        assert result.error == 'Could not resolve tag value'
        tags_manager.add_tag_to_entity.assert_not_called()

    def test_entity_name_source(self, db_session, tags_manager):
        result = AssignTagStepHandler(
            db=db_session, config={'key': 'source', 'value_source': 'entity_name'},
        ).execute(_context())

        assert result.passed is True
        assert tags_manager.add_tag_to_entity.call_args.kwargs['assigned_value'] == 'orders'


def _step(step_id, step_type, position=None, **kw):
    return WorkflowStepCreate(
        step_id=step_id, step_type=step_type,
        position=StepPosition(**position) if position else None, **kw,
    )


class TestStepPositions:
    def test_positions_round_trip_through_create_get_and_update(self, db_session):
        manager = WorkflowsManager(db_session)
        created = manager.create_workflow(ProcessWorkflowCreate(
            name=f'wf-{uuid.uuid4().hex[:6]}',
            trigger=WorkflowTrigger(type=TriggerType.MANUAL, entity_types=[EntityType.DATA_PRODUCT]),
            steps=[
                _step('check', StepType.CONDITIONAL, {'x': 40, 'y': 150}, config={'condition': '1 = 1'},
                      on_pass='ok', on_fail='stop', order=0),
                _step('ok', StepType.PASS, {'x': -120, 'y': 300}, order=1),
                _step('stop', StepType.FAIL, {'x': 260, 'y': 310}, order=2),
            ],
        ))
        db_session.commit()

        loaded = manager.get_workflow(created.id)
        assert {s.step_id: (s.position.x, s.position.y) for s in loaded.steps} == {
            'check': (40, 150), 'ok': (-120, 300), 'stop': (260, 310),
        }

        # The designer sends every step back with its (moved) position.
        moved = [
            _step('check', StepType.CONDITIONAL, {'x': 40, 'y': 150}, config={'condition': '1 = 1'},
                  on_pass='ok', on_fail='stop', order=0),
            _step('ok', StepType.PASS, {'x': -300, 'y': 420}, order=1),
            _step('stop', StepType.FAIL, {'x': 260, 'y': 310}, order=2),
        ]
        manager.update_workflow(created.id, ProcessWorkflowUpdate(steps=moved))
        db_session.commit()

        reloaded = manager.get_workflow(created.id)
        assert {s.step_id: (s.position.x, s.position.y) for s in reloaded.steps}['ok'] == (-300, 420)

    def test_steps_without_positions_stay_without(self, db_session):
        manager = WorkflowsManager(db_session)
        created = manager.create_workflow(ProcessWorkflowCreate(
            name=f'wf-{uuid.uuid4().hex[:6]}',
            trigger=WorkflowTrigger(type=TriggerType.MANUAL, entity_types=[EntityType.DATA_PRODUCT]),
            steps=[_step('ok', StepType.PASS, order=0)],
        ))
        db_session.commit()

        assert manager.get_workflow(created.id).steps[0].position is None


class TestAssignTagValidation:
    def _validate(self, db_session, config):
        return WorkflowsManager(db_session).validate_workflow(ProcessWorkflowCreate(
            name='wf',
            trigger=WorkflowTrigger(type=TriggerType.MANUAL, entity_types=[EntityType.DATA_PRODUCT]),
            steps=[WorkflowStepCreate(step_id='tag', step_type=StepType.ASSIGN_TAG, config=config, order=0)],
        ))

    def test_a_key_only_step_is_valid(self, db_session):
        result = self._validate(db_session, {'key': 'governance/pii'})

        assert result.valid is True, result.errors

    def test_the_key_is_still_required(self, db_session):
        result = self._validate(db_session, {'value': 'x'})

        assert result.valid is False
        assert len(result.errors) == 1 and "requires 'key'" in str(result.errors[0])
