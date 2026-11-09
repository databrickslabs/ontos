"""Rules shipped in default_workflows.yaml must be valid compliance DSL."""
from functools import lru_cache
from pathlib import Path

import pytest
import yaml

from src.common.compliance_dsl import evaluate_rule_on_object, parse_rule

WORKFLOWS_PATH = Path(__file__).resolve().parents[2] / 'data' / 'default_workflows.yaml'


@lru_cache(maxsize=1)
def _workflows():
    return yaml.safe_load(WORKFLOWS_PATH.read_text())['workflows']


def _rule_steps():
    return [
        pytest.param(step['config']['rule'], id=f"{wf['id']}/{step['id']}")
        for wf in _workflows()
        for step in wf.get('steps', [])
        if (step.get('config') or {}).get('rule')
    ]


def test_publication_review_rule_is_collected():
    # Guards against the collection silently matching nothing.
    assert any(p.id == 'publication-request-review/validate-status' for p in _rule_steps())


@pytest.mark.parametrize('rule', _rule_steps())
def test_default_workflow_rule_parses(rule):
    parse_rule(rule)


def _publication_review_rule():
    [workflow] = [wf for wf in _workflows() if wf['id'] == 'publication-request-review']
    [step] = [s for s in workflow['steps'] if s['id'] == 'validate-status']
    return step['config']['rule']


# The rule runs against the request payload, which carries the entity status as
# `current_status` (data contracts are requested from `approved`, products from `active`).
@pytest.mark.parametrize('status', ['approved', 'active'])
def test_publication_request_review_accepts_publishable_statuses(status):
    passed, message = evaluate_rule_on_object(
        _publication_review_rule(), {'current_status': status}
    )

    assert passed is True, message


def test_publication_request_review_lets_any_status_unpublish():
    passed, message = evaluate_rule_on_object(
        _publication_review_rule(), {'current_status': 'deprecated', 'requested_scope': 'none'}
    )

    assert passed is True, message


@pytest.mark.parametrize('payload', [
    {'current_status': 'draft'}, {},
    {'current_status': 'deprecated', 'requested_scope': 'organization'},
])
def test_publication_request_review_rejects_other_statuses(payload):
    passed, _ = evaluate_rule_on_object(_publication_review_rule(), payload)

    assert passed is False


def _approval_steps():
    return [
        pytest.param(step, id=f"{wf['id']}/{step['id']}")
        for wf in _workflows()
        for step in wf.get('steps', [])
        if step.get('type') == 'approval'
    ]


@pytest.mark.parametrize('step', _approval_steps())
def test_default_approval_steps_configure_approvers(step):
    # Defaults must use `approvers`. ApprovalStepHandler only falls back to
    # `approver_role` for databases that loaded older defaults.
    config = step.get('config') or {}

    assert config.get('approvers'), f"approval step without `approvers`: {sorted(config)}"
    assert 'approver_role' not in config
    # The handler reads `timeout_days`; `timeout_hours` would be ignored.
    assert 'timeout_hours' not in config
