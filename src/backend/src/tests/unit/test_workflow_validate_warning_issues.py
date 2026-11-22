"""POST /api/workflows/validate keeps the codes of its warnings (#1438).

The designer reads ``warning_issues`` to show each warning on its step, so a result the
route rebuilds must carry them on as coded issues, not as plain strings.
"""
from src.models.process_workflows import CodedMessage, WorkflowValidationResult
from src.routes.workflows_routes import _with_policy_errors, _with_policy_warnings


class _FakeManager:
    def __init__(self, missing):
        self._missing = missing

    def policy_reference_errors(self, steps):
        return list(self._missing)


def _missing_policy():
    return [CodedMessage(
        "Step 'p' uses policy 'x', which doesn't exist",
        'policy_check_policy_missing', step='p', policyId='x',
    )]


def _terminal_warning():
    return CodedMessage(
        "Step 'done' ends the workflow; its link to 'other' is ignored and removed on save",
        'terminal_step_has_next', step='done', target='other',
    )


def test_an_inactive_workflow_keeps_the_codes_of_its_warnings_and_adds_the_policy_warning():
    validation = WorkflowValidationResult(valid=True, warnings=[_terminal_warning()])

    result = _with_policy_warnings(_FakeManager(_missing_policy()), validation, steps=[])

    assert [w.code for w in result.warning_issues] == [
        'terminal_step_has_next', 'policy_check_policy_missing',
    ]
    assert result.warning_issues[0].params == {'step': 'done', 'target': 'other'}
    assert len(result.warnings) == 2
    assert result.valid is True


def test_an_inactive_workflow_without_missing_policies_is_unchanged():
    validation = WorkflowValidationResult(valid=True, warnings=[_terminal_warning()])

    assert _with_policy_warnings(_FakeManager([]), validation, steps=[]) is validation


def test_an_active_workflow_keeps_the_codes_of_its_warnings():
    validation = WorkflowValidationResult(valid=True, warnings=[_terminal_warning()])

    result = _with_policy_errors(_FakeManager(_missing_policy()), validation, steps=[], is_active=True)

    assert result.valid is False
    assert [w.code for w in result.warning_issues] == ['terminal_step_has_next']
    assert [i.code for i in result.issues] == ['policy_check_policy_missing']
