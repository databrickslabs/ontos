"""Conditional and Script steps: config checks, save, reload and execution.

The workflow designer had no form for these steps (#942, #943). These tests
pin the backend side the new forms rely on: what a valid config is, the
codes the designer translates, and that a saved config runs as configured.
"""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import asyncio
import json
import uuid
from unittest.mock import MagicMock

import pytest

from src.common.workflow_executor import WorkflowExecutor
from src.common.workflow_step_config import MAX_CONDITION_LENGTH, check_condition, check_script_config
from src.controller.workflows_manager import WorkflowsManager
from src.models.process_workflows import (
    ProcessWorkflowCreate,
    StepType,
    TriggerType,
    WorkflowStepCreate,
    WorkflowTrigger,
)
from src.routes.workflows_routes import check_condition as check_condition_route


# --- Condition checks ---------------------------------------------------------

@pytest.mark.parametrize('condition', [
    # The designer's examples (step-config-forms.tsx) and placeholder (workflows.json)
    "obj.status = 'active'",
    "obj.name CONTAINS 'email' OR obj.name CONTAINS 'phone'",
    "obj.status IN ['approved', 'active'] AND NOT HAS_TAG('pii')",
    "LENGTH(obj.description) > 20",
    "obj.status = 'active' AND NOT HAS_TAG('pii')",
    # Shipped conditions: the PII detection default workflow and the retail demo
    "obj.name CONTAINS 'email' OR obj.name CONTAINS 'phone' OR \n"
    "obj.name CONTAINS 'ssn' OR obj.name CONTAINS 'address' OR\n"
    "obj.name CONTAINS 'dob' OR obj.name CONTAINS 'birth'\n",
    "obj.permission_level != 'ADMIN' OR obj.reason != ''",
])
def test_a_valid_condition_has_no_issue(condition):
    assert check_condition(condition) is None


@pytest.mark.parametrize('condition', [None, '', '   \n'])
def test_a_missing_condition_is_required(condition):
    assert check_condition(condition)['code'] == 'condition_required'


def test_a_syntax_error_names_its_position():
    issue = check_condition("obj.status == 'active'")

    assert issue['code'] == 'condition_syntax_error'
    assert issue['params'] == {'line': 1, 'column': 13}
    assert 'column 13' in issue['message']


def test_an_unterminated_string_is_a_syntax_error():
    issue = check_condition("obj.status = 'active")

    assert issue['code'] == 'condition_syntax_error'
    assert issue['params']['line'] == 1


def test_input_after_the_condition_is_reported():
    # The handler would evaluate only "obj.status = 'active'" and ignore the rest.
    issue = check_condition("obj.status = 'active'\ngarbage")

    assert issue['code'] == 'condition_trailing_input'
    assert issue['params'] == {'line': 2, 'column': 1, 'token': 'garbage'}


def test_a_full_rule_is_not_a_condition():
    assert check_condition("ASSERT obj.status = 'active'")['code'] == 'condition_syntax_error'


def _nested(depth):
    return '(' * depth + "obj.status = 'active'" + ')' * depth


def test_a_deeply_nested_condition_is_reported_not_raised():
    # The parser is recursive: ~400 levels used to raise RecursionError (a 500).
    condition = _nested(1000)
    assert len(condition) <= MAX_CONDITION_LENGTH

    assert check_condition(condition)['code'] == 'condition_too_complex'


def test_moderate_nesting_still_parses():
    assert check_condition(_nested(50)) is None


def test_an_oversized_condition_is_too_long():
    condition = "obj.status = 'active' OR " * 500 + "obj.status = 'draft'"
    assert len(condition) > MAX_CONDITION_LENGTH

    issue = check_condition(condition)

    assert issue['code'] == 'condition_too_long'
    assert issue['params'] == {'maximum': MAX_CONDITION_LENGTH}


# --- Script checks ------------------------------------------------------------

def test_a_complete_script_config_has_no_issue():
    assert check_script_config({'language': 'sql', 'code': 'SELECT 1'}) == []
    assert check_script_config({'language': 'sql', 'code': 'SELECT * FROM ${entity_id}'}) == []


@pytest.mark.parametrize('timeout', [0, '60', True])
def test_a_sql_script_timeout_is_not_checked(timeout):
    # The SQL handler ignores timeout_seconds (an older step may still carry it).
    assert check_script_config({'language': 'sql', 'code': 'SELECT 1', 'timeout_seconds': timeout}) == []


@pytest.mark.parametrize('config', [
    {'language': 'python', 'code': "result = {'passed': True}"},
    # A step stored without a language was a Python step (the old default)
    {'code': "result = {'passed': True}"},
    {'language': '', 'code': 'x = 1'},
    {'language': None, 'code': 'x = 1', 'timeout_seconds': 30},
])
def test_a_python_script_is_disabled(config):
    [issue] = check_script_config(config)

    assert issue['code'] == 'script_python_disabled'
    assert issue['params'] == {}
    assert 'disabled' in issue['message']


@pytest.mark.parametrize('config, code', [
    ({'language': 'sql'}, 'script_code_required'),
    ({'language': 'sql', 'code': '  '}, 'script_code_required'),
    ({'language': 'sql', 'code': 7}, 'script_code_required'),
    ({'code': 'x = 1', 'language': 'bash'}, 'script_language_unsupported'),
    ({'language': 'sql', 'code': "SELECT '%${n}%'"}, 'script_sql_placeholder_in_quotes'),
    ({'language': 'sql', 'code': 'SELECT * FROM main.${n}'},
     'script_sql_placeholder_in_identifier'),
    ({'language': 'sql', 'code': 'SELECT 1 WHERE a IN (${n})'}, 'script_sql_placeholder_as_list'),
])
def test_script_config_issues(config, code):
    assert [issue['code'] for issue in check_script_config(config)] == [code]


def test_a_python_step_without_code_reports_both_issues():
    assert [issue['code'] for issue in check_script_config({})] == [
        'script_code_required', 'script_python_disabled',
    ]


def test_an_unsupported_language_names_what_is_supported():
    [issue] = check_script_config({'language': 'bash', 'code': 'ls'})

    assert issue['params'] == {'language': 'bash', 'supported': 'sql'}


def test_a_placeholder_issue_names_the_placeholder():
    [issue] = check_script_config({'language': 'sql', 'code': "SELECT '%${n}%'"})

    assert issue['params'] == {'placeholder': '${n}'}


# --- check-condition route ----------------------------------------------------

def _route(condition):
    return asyncio.run(check_condition_route(request=MagicMock(), body={'condition': condition}, _=True))


def test_the_route_accepts_a_valid_condition():
    assert _route("obj.status = 'active'") == {'valid': True, 'code': None, 'params': {}, 'message': None}


def test_the_route_returns_the_code_and_params_of_an_issue():
    result = _route("obj.status == 'active'")

    assert result['valid'] is False
    assert result['code'] == 'condition_syntax_error'
    assert result['params'] == {'line': 1, 'column': 13}


def test_the_route_treats_a_non_string_condition_as_missing():
    assert _route(42)['code'] == 'condition_required'


def test_the_route_answers_a_deeply_nested_condition():
    result = _route(_nested(1000))

    assert result['valid'] is False
    assert result['code'] == 'condition_too_complex'


# --- Save, reload and run -----------------------------------------------------

def _workflow(condition, script_config=None):
    script_config = script_config or {
        'language': 'sql',
        'code': "SELECT * FROM ${entity_id} WHERE name = '${entity_name}'",
    }
    return ProcessWorkflowCreate(
        name=f'wf-{uuid.uuid4().hex[:8]}',
        trigger=WorkflowTrigger(type=TriggerType.MANUAL, entity_types=['table']),
        steps=[
            WorkflowStepCreate(step_id='check', name='Check', step_type=StepType.CONDITIONAL,
                               config={'condition': condition}, on_pass='script', on_fail='rejected', order=0),
            WorkflowStepCreate(step_id='script', name='Script', step_type=StepType.SCRIPT,
                               config=script_config, on_pass='done', on_fail='rejected', order=1),
            WorkflowStepCreate(step_id='done', name='Done', step_type=StepType.PASS, order=2),
            WorkflowStepCreate(step_id='rejected', name='Rejected', step_type=StepType.FAIL,
                               config={'message': 'Not matched'}, order=3),
        ],
    )


def test_validation_rejects_a_condition_that_does_not_parse(db_session):
    result = WorkflowsManager(db_session).validate_workflow(_workflow("obj.name == 'x'"))

    assert not result.valid
    assert any("Step 'check'" in e and 'column 11' in e for e in result.errors)


def test_validation_rejects_a_deeply_nested_condition(db_session):
    result = WorkflowsManager(db_session).validate_workflow(_workflow(_nested(1000)))

    assert not result.valid
    assert any("Step 'check'" in e and 'nested too deeply' in e for e in result.errors)


@pytest.mark.parametrize('config', [
    {'language': 'python', 'code': 'x = 1'},
    {'code': 'x = 1', 'timeout_seconds': 30},
])
def test_validation_rejects_a_python_script_step(db_session, config):
    result = WorkflowsManager(db_session).validate_workflow(_workflow("obj.name = 'x'", config))

    assert not result.valid
    assert any("Step 'script'" in e and 'Python' in e and 'disabled' in e for e in result.errors)
    assert [(i.code, i.params) for i in result.issues if i.code == 'script_python_disabled'] == [
        ('script_python_disabled', {'step': 'script'}),
    ]


def test_validation_rejects_a_sql_placeholder_that_cannot_be_bound(db_session):
    result = WorkflowsManager(db_session).validate_workflow(_workflow(
        "obj.name = 'x'", {'language': 'sql', 'code': "SELECT * FROM t WHERE a LIKE '%${n}%'"},
    ))

    assert not result.valid
    assert [(i.code, i.params) for i in result.issues] == [
        ('script_sql_placeholder_in_quotes', {'step': 'script', 'placeholder': '${n}'}),
    ]


def test_the_script_step_type_schema_is_sql_only(db_session):
    schema = {t.type: t for t in WorkflowsManager(db_session).get_step_type_schemas()}[
        StepType.SCRIPT
    ]
    properties = schema.config_schema['properties']

    assert properties['language']['enum'] == ['sql']
    assert properties['language']['default'] == 'sql'
    assert 'timeout_seconds' not in properties
    assert schema.config_schema['required'] == ['code']


def test_conditional_and_script_configs_survive_save_and_reload(db_session):
    manager = WorkflowsManager(db_session)
    created = manager.create_workflow(_workflow("obj.name CONTAINS 'email'"))

    reloaded = {s.step_id: s for s in manager.get_workflow(created.id).steps}

    assert reloaded['check'].config == {'condition': "obj.name CONTAINS 'email'"}
    assert reloaded['check'].on_pass == 'script' and reloaded['check'].on_fail == 'rejected'
    assert reloaded['script'].config == {
        'language': 'sql',
        'code': "SELECT * FROM ${entity_id} WHERE name = '${entity_name}'",
    }


def _run(db, workflow, entity_name):
    return WorkflowExecutor(db).execute_workflow(
        workflow, {'name': entity_name},
        entity_type='table', entity_id=f'main.sales.{entity_name}', entity_name=entity_name,
        user_email='author@example.com',
    )


def _ran(execution):
    return [s.step_id for s in sorted(execution.step_executions, key=lambda s: s.started_at)]


def _step_id_of(db, workflow):
    return {s.id: s.step_id for s in workflow.steps}


@pytest.fixture
def warehouse(db_session, monkeypatch):
    """A configured SQL warehouse whose client records the statements it gets."""
    from types import SimpleNamespace

    from src.db_models.app_settings import AppSettingDb

    db_session.add(AppSettingDb(key='sql_warehouse_id', value='wh-123'))
    db_session.flush()
    ws = MagicMock()
    ws.statement_execution.execute_statement.return_value = SimpleNamespace(
        status=SimpleNamespace(state=SimpleNamespace(value='SUCCEEDED'), error=None),
        manifest=SimpleNamespace(total_row_count=1),
    )
    monkeypatch.setattr('src.common.workspace_client.get_workspace_client', lambda: ws)
    return ws.statement_execution.execute_statement


def test_a_true_condition_follows_the_pass_branch_and_runs_the_script(db_session, warehouse):
    manager = WorkflowsManager(db_session)
    workflow = manager.get_workflow(manager.create_workflow(_workflow("obj.name CONTAINS 'email'")).id)

    execution = _run(db_session, workflow, 'customer_email')

    names = _step_id_of(db_session, workflow)
    results = {names.get(s.step_id, s.step_id): s for s in execution.step_executions}
    assert execution.status.value == 'succeeded'
    assert set(results) == {'check', 'script', 'done'}
    assert results['check'].passed is True
    assert results['script'].passed is True
    warehouse.assert_called_once()


def test_a_false_condition_follows_the_fail_branch(db_session, warehouse):
    manager = WorkflowsManager(db_session)
    workflow = manager.get_workflow(manager.create_workflow(_workflow("obj.name CONTAINS 'email'")).id)

    execution = _run(db_session, workflow, 'orders')

    names = _step_id_of(db_session, workflow)
    results = {names.get(s.step_id, s.step_id): s for s in execution.step_executions}
    assert execution.status.value == 'failed'
    assert set(results) == {'check', 'rejected'}
    # The condition was evaluated: the step succeeded and took its false branch (#1418)
    assert results['check'].passed is True
    assert results['check'].result_data['branch'] == 'false'
    warehouse.assert_not_called()


def test_a_sql_script_saved_from_the_designer_runs_on_the_configured_warehouse(
    db_session, warehouse,
):
    manager = WorkflowsManager(db_session)
    workflow = manager.get_workflow(manager.create_workflow(_workflow(
        "obj.name CONTAINS 'email'",
        {'language': 'sql', 'code': "SELECT * FROM ${entity_id} LIMIT 1"},
    )).id)

    execution = _run(db_session, workflow, 'customer_email')

    assert execution.status.value == 'succeeded'
    warehouse.assert_called_once()
    kwargs = warehouse.call_args.kwargs
    assert kwargs['statement'] == 'SELECT * FROM IDENTIFIER(:p0) LIMIT 1'
    assert [(p.name, p.value) for p in kwargs['parameters']] == [
        ('p0', 'main.sales.customer_email'),
    ]
    assert kwargs['warehouse_id'] == 'wh-123'


def test_a_python_script_stored_without_a_language_fails_without_running(db_session, warehouse):
    from src.common.workflow_executor import WorkflowExecutor
    from src.db_models.process_workflows import WorkflowStepDb

    manager = WorkflowsManager(db_session)
    created = manager.create_workflow(_workflow("obj.name CONTAINS 'email'"))
    # Stored as an older version saved it: no language, a timeout
    row = db_session.query(WorkflowStepDb).filter_by(
        workflow_id=created.id, step_id='script',
    ).one()
    row.config = json.dumps({'code': "result = {'passed': True}", 'timeout_seconds': 30})
    db_session.flush()
    workflow = manager.get_workflow(created.id)

    execution = _run(db_session, workflow, 'customer_email')

    results = {s.step_key: s for s in execution.step_executions}
    assert execution.status.value == 'failed'
    assert results['script'].passed is False
    assert results['script'].result_data['error_code'] == 'script_python_disabled'
    warehouse.assert_not_called()
