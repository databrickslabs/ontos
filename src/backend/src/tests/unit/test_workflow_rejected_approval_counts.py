"""A rejected approval is counted as a failure when the execution resumes.

The pause counted the approval as passed; a rejection moves it to the failures,
and the step a rejection routes to through ``on_fail`` is counted on its own.
"""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

from src.models.process_workflows import StepType, WorkflowStepCreate
from src.tests.unit.test_workflow_approval_last_step import (
    _approval,
    _decide,
    _paused,
    _workflow,
)


def test_a_rejection_moves_the_approval_to_the_failures(db_session):
    """The pause counted the approval as passed; a rejection moves it to the failures."""
    workflow = _workflow(db_session, [_approval()])
    execution = _paused(db_session, workflow)

    resumed = _decide(db_session, execution, approved=False)

    assert (resumed.success_count, resumed.failure_count) == (0, 1)


def test_a_rejection_sent_to_an_on_fail_step_counts_both(db_session):
    """The rejected approval is a failure and the step it routes to is a pass."""
    workflow = _workflow(db_session, [
        _approval(on_fail='fallback'),
        WorkflowStepCreate(step_id='fallback', step_type=StepType.PASS, order=1),
    ])
    execution = _paused(db_session, workflow)

    resumed = _decide(db_session, execution, approved=False)

    assert (resumed.success_count, resumed.failure_count) == (1, 1)
