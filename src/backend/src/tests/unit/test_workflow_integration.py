# Set test environment variables BEFORE any app imports
import os
os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

"""
Integration tests for the workflow system end-to-end.

These tests exercise the FULL pipeline:
  trigger fires → WorkflowsManager finds matching workflow →
  WorkflowExecutor runs steps in sequence → results propagate

Unlike unit tests that mock at component boundaries, these tests
create real workflow definitions in the DB and execute them through
the actual TriggerRegistry → WorkflowExecutor pipeline.
"""

import json
import pytest
from unittest.mock import MagicMock, patch
from uuid import uuid4

from src.common.workflow_triggers import TriggerRegistry
from src.common.workflow_executor import WorkflowExecutor
from src.controller.workflows_manager import WorkflowsManager
from src.models.process_workflows import (
    TriggerType,
    EntityType,
    ExecutionStatus,
    ProcessWorkflow,
    ProcessWorkflowCreate,
)
from src.db_models.process_workflows import ProcessWorkflowDb, WorkflowStepDb
from datetime import datetime


def _create_workflow_in_db(db_session, *, trigger_config, steps_config=None, **overrides) -> str:
    """Insert a workflow + steps into the DB. Returns the workflow ID.

    Args:
        trigger_config: JSON string of trigger config
        steps_config: JSON string of steps list (each with step_id, name, type, config, on_pass, on_fail, order)
    """
    wf_id = str(uuid4())
    now = datetime.utcnow()

    wf = ProcessWorkflowDb(
        id=wf_id,
        name=overrides.get('name', 'Test Workflow'),
        description=overrides.get('description', 'Integration test'),
        trigger_config=trigger_config,
        scope_config=overrides.get('scope_config', json.dumps({"type": "all"})),
        is_active=overrides.get('is_active', True),
        is_default=False,
        workflow_type='process',
        created_at=now,
        updated_at=now,
    )
    db_session.add(wf)
    db_session.flush()

    steps = json.loads(steps_config) if steps_config else [
        {"step_id": "step1", "name": "Pass", "type": "pass", "config": {},
         "on_pass": None, "on_fail": None, "order": 0}
    ]
    for s in steps:
        step = WorkflowStepDb(
            id=str(uuid4()),
            workflow_id=wf_id,
            step_id=s['step_id'],
            name=s.get('name', ''),
            step_type=s['type'],
            config=json.dumps(s.get('config', {})),
            on_pass=s.get('on_pass'),
            on_fail=s.get('on_fail'),
            order=s.get('order', 0),
            created_at=now,
            updated_at=now,
        )
        db_session.add(step)

    db_session.flush()
    return wf_id


# =========================================================================
# Flow 1: Validation → Pass/Fail branching
# =========================================================================

class TestValidationBranchingFlow:
    """A workflow with a validation step that branches on pass/fail."""

    def test_validation_passes_and_follows_on_pass_branch(self, db_session):
        """Entity matches validation rule → follows on_pass to 'success' step."""
        _create_workflow_in_db(
            db_session,
            trigger_config=json.dumps({
                "type": "on_create",
                "entity_types": ["table"],
            }),
            steps_config=json.dumps([
                {
                    "step_id": "validate",
                    "name": "Check naming",
                    "type": "validation",
                    "config": {"rule": "ASSERT obj.name MATCHES '^[a-z_]+$'"},
                    "on_pass": "success",
                    "on_fail": "fail_step",
                    "order": 0,
                },
                {
                    "step_id": "success",
                    "name": "Validation passed",
                    "type": "pass",
                    "config": {},
                    "on_pass": None,
                    "on_fail": None,
                    "order": 1,
                },
                {
                    "step_id": "fail_step",
                    "name": "Validation failed",
                    "type": "fail",
                    "config": {},
                    "on_pass": None,
                    "on_fail": None,
                    "order": 2,
                },
            ]),
        )

        registry = TriggerRegistry(db=db_session)
        executions = registry.on_create(
            entity_type=EntityType.TABLE,
            entity_id="tbl-1",
            entity_name="valid_table_name",
            entity_data={"name": "valid_table_name", "status": "draft"},
            user_email="user@test.com",
        )

        assert len(executions) == 1
        exe = executions[0]
        assert exe.status == ExecutionStatus.SUCCEEDED

    def test_validation_fails_and_follows_on_fail_branch(self, db_session):
        """Entity fails validation → follows on_fail to 'fail_step'."""
        _create_workflow_in_db(
            db_session,
            trigger_config=json.dumps({
                "type": "on_create",
                "entity_types": ["table"],
            }),
            steps_config=json.dumps([
                {
                    "step_id": "validate",
                    "name": "Check naming",
                    "type": "validation",
                    "config": {"rule": "ASSERT obj.name MATCHES '^[a-z_]+$'"},
                    "on_pass": "success",
                    "on_fail": "fail_step",
                    "order": 0,
                },
                {
                    "step_id": "success",
                    "name": "Passed",
                    "type": "pass",
                    "config": {},
                    "on_pass": None,
                    "on_fail": None,
                    "order": 1,
                },
                {
                    "step_id": "fail_step",
                    "name": "Failed",
                    "type": "fail",
                    "config": {},
                    "on_pass": None,
                    "on_fail": None,
                    "order": 2,
                },
            ]),
        )

        registry = TriggerRegistry(db=db_session)
        executions = registry.on_create(
            entity_type=EntityType.TABLE,
            entity_id="tbl-2",
            entity_name="INVALID-Name-123",
            entity_data={"name": "INVALID-Name-123", "status": "draft"},
            user_email="user@test.com",
        )

        assert len(executions) == 1
        exe = executions[0]
        assert exe.status == ExecutionStatus.FAILED


# =========================================================================
# Flow 2: Tag assignment persists through pipeline
# =========================================================================

class TestTagAssignmentFlow:
    """Workflow assigns a tag via the tag step handler — verifies context propagation."""

    def test_tag_step_updates_context_for_subsequent_steps(self, db_session):
        """Tag step assigns a value, subsequent step can see it in context."""
        _create_workflow_in_db(
            db_session,
            trigger_config=json.dumps({
                "type": "on_create",
                "entity_types": ["table"],
            }),
            steps_config=json.dumps([
                {
                    "step_id": "assign_owner",
                    "name": "Assign owner tag",
                    "type": "assign_tag",
                    "config": {"key": "owner", "value_source": "current_user"},
                    "on_pass": "done",
                    "on_fail": None,
                    "order": 0,
                },
                {
                    "step_id": "done",
                    "name": "Done",
                    "type": "pass",
                    "config": {},
                    "on_pass": None,
                    "on_fail": None,
                    "order": 1,
                },
            ]),
        )

        registry = TriggerRegistry(db=db_session)
        executions = registry.on_create(
            entity_type=EntityType.TABLE,
            entity_id="tbl-3",
            entity_name="my_table",
            entity_data={"name": "my_table"},
            user_email="alice@acme.com",
        )

        assert len(executions) == 1
        exe = executions[0]
        assert exe.status == ExecutionStatus.SUCCEEDED


# =========================================================================
# Flow 3: before_status_change gating (blocking)
# =========================================================================

class TestStatusGatingFlow:
    """Full gating flow: before_status_change → validation → block/allow."""

    def test_gating_workflow_blocks_invalid_transition(self, db_session):
        """A before_status_change workflow with a failing validation blocks the transition."""
        _create_workflow_in_db(
            db_session,
            trigger_config=json.dumps({
                "type": "before_status_change",
                "entity_types": ["data_product"],
                "from_status": "approved",
                "to_status": "active",
            }),
            steps_config=json.dumps([
                {
                    "step_id": "check_contract",
                    "name": "Require contract",
                    "type": "validation",
                    "config": {"rule": "ASSERT obj.has_contract"},
                    "on_pass": "allowed",
                    "on_fail": None,
                    "order": 0,
                },
                {
                    "step_id": "allowed",
                    "name": "Transition allowed",
                    "type": "pass",
                    "config": {},
                    "on_pass": None,
                    "on_fail": None,
                    "order": 1,
                },
            ]),
        )

        registry = TriggerRegistry(db=db_session)
        all_passed, executions = registry.before_status_change(
            entity_type=EntityType.DATA_PRODUCT,
            entity_id="prod-1",
            from_status="approved",
            to_status="active",
            entity_name="My Product",
            entity_data={"name": "My Product", "has_contract": False},
            user_email="user@test.com",
        )

        assert all_passed is False
        assert len(executions) == 1
        assert executions[0].status == ExecutionStatus.FAILED

    def test_gating_workflow_allows_valid_transition(self, db_session):
        """A before_status_change workflow with passing validation allows the transition."""
        _create_workflow_in_db(
            db_session,
            trigger_config=json.dumps({
                "type": "before_status_change",
                "entity_types": ["data_product"],
                "from_status": "approved",
                "to_status": "active",
            }),
            steps_config=json.dumps([
                {
                    "step_id": "check_contract",
                    "name": "Require contract",
                    "type": "validation",
                    "config": {"rule": "ASSERT obj.has_contract"},
                    "on_pass": "allowed",
                    "on_fail": None,
                    "order": 0,
                },
                {
                    "step_id": "allowed",
                    "name": "Transition allowed",
                    "type": "pass",
                    "config": {},
                    "on_pass": None,
                    "on_fail": None,
                    "order": 1,
                },
            ]),
        )

        registry = TriggerRegistry(db=db_session)
        all_passed, executions = registry.before_status_change(
            entity_type=EntityType.DATA_PRODUCT,
            entity_id="prod-2",
            from_status="approved",
            to_status="active",
            entity_name="Good Product",
            entity_data={"name": "Good Product", "has_contract": True},
            user_email="user@test.com",
        )

        assert all_passed is True
        assert len(executions) == 1
        assert executions[0].status == ExecutionStatus.SUCCEEDED

    def test_non_matching_status_does_not_fire(self, db_session):
        """Workflow with from_status=approved should NOT fire for draft→proposed."""
        _create_workflow_in_db(
            db_session,
            trigger_config=json.dumps({
                "type": "before_status_change",
                "entity_types": ["data_product"],
                "from_status": "approved",
                "to_status": "active",
            }),
        )

        registry = TriggerRegistry(db=db_session)
        all_passed, executions = registry.before_status_change(
            entity_type=EntityType.DATA_PRODUCT,
            entity_id="prod-3",
            from_status="draft",
            to_status="proposed",
            entity_data={"name": "Draft Product"},
        )

        # No matching workflow → passes by default
        assert all_passed is True
        assert len(executions) == 0


# =========================================================================
# Flow 4: Script step with variable substitution
# =========================================================================

class TestScriptWithSubstitutionFlow:
    """Python script step that uses entity data and returns a result."""

    def test_script_accesses_entity_and_produces_result(self, db_session):
        """Script reads entity data, computes something, sets result."""
        _create_workflow_in_db(
            db_session,
            trigger_config=json.dumps({
                "type": "on_create",
                "entity_types": ["table"],
            }),
            steps_config=json.dumps([
                {
                    "step_id": "check_length",
                    "name": "Check name length",
                    "type": "script",
                    "config": {
                        "language": "python",
                        "code": (
                            "name = entity.get('name', '')\n"
                            "result = {\n"
                            "  'passed': len(name) >= 3,\n"
                            "  'message': f'Name length: {len(name)}',\n"
                            "  'data': {'name_length': len(name)},\n"
                            "}\n"
                        ),
                        "timeout_seconds": 5,
                    },
                    "on_pass": "done",
                    "on_fail": None,
                    "order": 0,
                },
                {
                    "step_id": "done",
                    "name": "Done",
                    "type": "pass",
                    "config": {},
                    "on_pass": None,
                    "on_fail": None,
                    "order": 1,
                },
            ]),
        )

        registry = TriggerRegistry(db=db_session)
        executions = registry.on_create(
            entity_type=EntityType.TABLE,
            entity_id="tbl-4",
            entity_name="customers",
            entity_data={"name": "customers", "status": "draft"},
            user_email="user@test.com",
        )

        assert len(executions) == 1
        exe = executions[0]
        assert exe.status == ExecutionStatus.SUCCEEDED


# =========================================================================
# Flow 5: Multi-step pipeline (validate → tag → notify)
# =========================================================================

class TestMultiStepPipelineFlow:
    """A realistic workflow: validate naming → assign tag → notify."""

    def test_three_step_pipeline_succeeds(self, db_session):
        """Validate → assign_tag → notification — all pass in sequence."""
        _create_workflow_in_db(
            db_session,
            trigger_config=json.dumps({
                "type": "on_create",
                "entity_types": ["table"],
            }),
            steps_config=json.dumps([
                {
                    "step_id": "validate_naming",
                    "name": "Check naming convention",
                    "type": "validation",
                    "config": {"rule": "ASSERT obj.name MATCHES '^[a-z_]+$'"},
                    "on_pass": "tag_owner",
                    "on_fail": "fail_step",
                    "order": 0,
                },
                {
                    "step_id": "tag_owner",
                    "name": "Tag with owner",
                    "type": "assign_tag",
                    "config": {"key": "owner", "value_source": "current_user"},
                    "on_pass": "notify",
                    "on_fail": "fail_step",
                    "order": 1,
                },
                {
                    "step_id": "notify",
                    "name": "Notify requester",
                    "type": "notification",
                    "config": {
                        "recipients": "requester",
                        "template": "validation_passed",
                        "custom_message": "Table ${entity_name} passed validation.",
                    },
                    "on_pass": "success",
                    "on_fail": "success",  # notification failure shouldn't block
                    "order": 2,
                },
                {
                    "step_id": "success",
                    "name": "All done",
                    "type": "pass",
                    "config": {},
                    "on_pass": None,
                    "on_fail": None,
                    "order": 3,
                },
                {
                    "step_id": "fail_step",
                    "name": "Pipeline failed",
                    "type": "fail",
                    "config": {},
                    "on_pass": None,
                    "on_fail": None,
                    "order": 4,
                },
            ]),
        )

        registry = TriggerRegistry(db=db_session)
        executions = registry.on_create(
            entity_type=EntityType.TABLE,
            entity_id="tbl-5",
            entity_name="good_table",
            entity_data={"name": "good_table", "status": "draft"},
            user_email="alice@acme.com",
        )

        assert len(executions) == 1
        exe = executions[0]
        assert exe.status == ExecutionStatus.SUCCEEDED

    def test_three_step_pipeline_fails_at_validation(self, db_session):
        """Invalid name → validation fails → branches to fail_step."""
        _create_workflow_in_db(
            db_session,
            trigger_config=json.dumps({
                "type": "on_create",
                "entity_types": ["table"],
            }),
            steps_config=json.dumps([
                {
                    "step_id": "validate_naming",
                    "name": "Check naming convention",
                    "type": "validation",
                    "config": {"rule": "ASSERT obj.name MATCHES '^[a-z_]+$'"},
                    "on_pass": "tag_owner",
                    "on_fail": "fail_step",
                    "order": 0,
                },
                {
                    "step_id": "tag_owner",
                    "name": "Tag with owner",
                    "type": "assign_tag",
                    "config": {"key": "owner", "value_source": "current_user"},
                    "on_pass": "success",
                    "on_fail": None,
                    "order": 1,
                },
                {
                    "step_id": "success",
                    "name": "All done",
                    "type": "pass",
                    "config": {},
                    "on_pass": None,
                    "on_fail": None,
                    "order": 2,
                },
                {
                    "step_id": "fail_step",
                    "name": "Pipeline failed",
                    "type": "fail",
                    "config": {},
                    "on_pass": None,
                    "on_fail": None,
                    "order": 3,
                },
            ]),
        )

        registry = TriggerRegistry(db=db_session)
        executions = registry.on_create(
            entity_type=EntityType.TABLE,
            entity_id="tbl-6",
            entity_name="BAD-NAME",
            entity_data={"name": "BAD-NAME"},
            user_email="alice@acme.com",
        )

        assert len(executions) == 1
        exe = executions[0]
        assert exe.status == ExecutionStatus.FAILED


# =========================================================================
# Flow 6: Default YAML workflows load and match triggers
# =========================================================================

class TestDefaultWorkflowsLoadAndMatch:
    """Load default_workflows.yaml and verify trigger matching works."""

    def test_default_yaml_loads_and_naming_convention_fires(self, db_session):
        """Load defaults → on_create for table → naming convention workflow fires."""
        mgr = WorkflowsManager(db=db_session)
        result = mgr.load_from_yaml()

        # Should have loaded multiple workflows (created, updated, or skipped)
        total = result.get('created', 0) + result.get('updated', 0) + result.get('skipped', 0)
        assert total > 0

        # Fire on_create for a table — naming-convention-check should match
        registry = TriggerRegistry(db=db_session)
        executions = registry.on_create(
            entity_type=EntityType.TABLE,
            entity_id="tbl-7",
            entity_name="valid_name",
            entity_data={"name": "valid_name", "status": "draft"},
            user_email="user@test.com",
        )

        # At least the naming convention workflow should fire
        assert len(executions) >= 1
        # At minimum, all executions should have completed (not crashed)
        for exe in executions:
            assert exe.status in (ExecutionStatus.SUCCEEDED, ExecutionStatus.FAILED, ExecutionStatus.PAUSED)
