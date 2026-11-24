"""Script steps over the workflow API: Python disabled, SQL values bound as parameters.

A Python script step ran ``exec()`` in the app's process behind a restricted
``__builtins__``, which attribute access escapes (subclass walk to ``os.popen``).
A SQL step pasted ``${...}`` values into the SQL text. Saving, activating and
running go through the routes here, not through patched helpers.
"""
import json
import uuid
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.db_models.app_settings import AppSettingDb
from src.db_models.process_workflows import ProcessWorkflowDb, WorkflowStepDb

# Reached os.popen through the restricted __builtins__ of the old Python steps
ESCAPE_PAYLOAD = (
    "for c in ().__class__.__base__.__subclasses__():\n"
    "    if c.__name__ == '_wrap_close':\n"
    "        result = {'passed': True,\n"
    "                  'message': c.__init__.__globals__['popen']('id').read()}\n"
)
EVIL_NAME = "x'; DROP TABLE main.sales.orders; --"


def _stored(db_session, script_config, active=False):
    """A manual workflow with one script step, written as an older version stored it."""
    wf_id = str(uuid.uuid4())
    now = datetime.utcnow()
    db_session.add(ProcessWorkflowDb(
        id=wf_id, name=f'script-{wf_id[:8]}', description='script',
        trigger_config=json.dumps({'type': 'manual', 'entity_types': ['table']}),
        scope_config=json.dumps({'type': 'all'}), is_active=active, is_default=False,
        version=1, created_at=now, updated_at=now,
    ))
    db_session.add(WorkflowStepDb(
        id=str(uuid.uuid4()), workflow_id=wf_id, step_id='script', name='Script',
        step_type='script', config=json.dumps(script_config), on_pass='done', on_fail='bad',
        order=0, created_at=now, updated_at=now,
    ))
    db_session.add(WorkflowStepDb(
        id=str(uuid.uuid4()), workflow_id=wf_id, step_id='done', name='Done',
        step_type='pass', config='{}', order=1, created_at=now, updated_at=now,
    ))
    db_session.add(WorkflowStepDb(
        id=str(uuid.uuid4()), workflow_id=wf_id, step_id='bad', name='Bad',
        step_type='fail', config='{}', order=2, created_at=now, updated_at=now,
    ))
    db_session.commit()
    return wf_id


def _body(script_config, active=False):
    return {
        'name': f'script-{uuid.uuid4().hex[:8]}',
        'trigger': {'type': 'manual', 'entity_types': ['table']},
        'is_active': active,
        'steps': [
            {'step_id': 'script', 'name': 'Script', 'step_type': 'script',
             'config': script_config, 'on_pass': 'done', 'on_fail': 'bad', 'order': 0},
            {'step_id': 'done', 'name': 'Done', 'step_type': 'pass', 'order': 1},
            {'step_id': 'bad', 'name': 'Bad', 'step_type': 'fail', 'order': 2},
        ],
    }


def _issues(response):
    assert response.status_code == 400, response.text
    detail = response.json()['detail']
    assert detail['code'] == 'workflow_invalid'
    return [(issue['code'], issue['params']) for issue in detail['params']['issues']]


@pytest.fixture
def warehouse(db_session, monkeypatch):
    """A configured SQL warehouse whose client records the statements it gets."""
    db_session.add(AppSettingDb(key='sql_warehouse_id', value='wh-1282'))
    db_session.commit()
    ws = MagicMock()
    ws.statement_execution.execute_statement.return_value = SimpleNamespace(
        status=SimpleNamespace(state=SimpleNamespace(value='SUCCEEDED'), error=None),
        manifest=SimpleNamespace(total_row_count=0),
    )
    monkeypatch.setattr('src.common.workspace_client.get_workspace_client', lambda: ws)
    return ws.statement_execution.execute_statement


def _execute(client, wf_id, entity_id='main.sales.orders', entity_name='orders'):
    response = client.post(
        f'/api/workflows/{wf_id}/execute',
        params={'entity_type': 'table', 'entity_id': entity_id, 'entity_name': entity_name},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _step(execution, step_id):
    runs = [s for s in execution['step_executions'] if s.get('step_key') == step_id]
    assert runs, execution['step_executions']
    return runs[0]


# --- Python steps -------------------------------------------------------------

@pytest.mark.parametrize('config', [
    {'language': 'python', 'code': "result = {'passed': True}"},
    # The designer saved Python steps without a language (Python was the default)
    {'code': "result = {'passed': True}", 'timeout_seconds': 30},
])
def test_saving_a_python_step_is_refused_with_a_code(client, config):
    response = client.post('/api/workflows', json=_body(config))

    assert ('script_python_disabled', {'step': 'script'}) in _issues(response)


def test_validate_reports_a_python_step(client):
    response = client.post('/api/workflows/validate', json=_body({'code': 'x = 1'}))

    assert response.status_code == 200, response.text
    codes = [issue['code'] for issue in response.json()['issues']]
    assert 'script_python_disabled' in codes


def test_activating_a_stored_python_step_is_refused(client, db_session):
    wf_id = _stored(db_session, {'language': 'python', 'code': ESCAPE_PAYLOAD})

    toggled = client.post(f'/api/workflows/{wf_id}/toggle-active', params={'is_active': True})
    put = client.put(f'/api/workflows/{wf_id}', json={'is_active': True})

    assert ('script_python_disabled', {'step': 'script'}) in _issues(toggled)
    assert ('script_python_disabled', {'step': 'script'}) in _issues(put)
    db_session.expire_all()
    assert db_session.get(ProcessWorkflowDb, wf_id).is_active is False


def test_a_stored_python_step_fails_with_a_code_and_the_escape_does_not_run(
    client, db_session, monkeypatch,
):
    popen = MagicMock()
    monkeypatch.setattr('os.popen', popen)
    wf_id = _stored(db_session, {'language': 'python', 'code': ESCAPE_PAYLOAD}, active=True)

    execution = _execute(client, wf_id)

    popen.assert_not_called()
    assert execution['status'] == 'failed'
    script = _step(execution, 'script')
    assert script['passed'] is False
    assert script['result_data']['error_code'] == 'script_python_disabled'
    assert 'job step' not in (script['error_message'] or '')


# --- SQL steps ----------------------------------------------------------------

def test_a_value_reaches_the_warehouse_as_a_parameter(client, db_session, warehouse):
    wf_id = _stored(db_session, {
        'language': 'sql',
        'code': "SELECT * FROM audit WHERE name = '${entity_name}' AND by = ${user_email}",
    }, active=True)

    execution = _execute(client, wf_id, entity_name=EVIL_NAME)

    assert execution['status'] == 'succeeded', execution
    kwargs = warehouse.call_args.kwargs
    assert kwargs['statement'] == 'SELECT * FROM audit WHERE name = :p0 AND by = :p1'
    assert 'DROP' not in kwargs['statement']
    params = [(p.name, p.value) for p in kwargs['parameters']]
    assert [name for name, _ in params] == ['p0', 'p1']
    assert params[0] == ('p0', EVIL_NAME)


def test_a_table_placeholder_becomes_an_identifier_parameter(client, db_session, warehouse):
    # The designer's own placeholder text for SQL steps
    wf_id = _stored(db_session, {
        'language': 'sql', 'code': 'SELECT COUNT(*) FROM ${entity_id}',
    }, active=True)

    execution = _execute(client, wf_id, entity_id='main.sales.orders')

    assert execution['status'] == 'succeeded', execution
    kwargs = warehouse.call_args.kwargs
    assert kwargs['statement'] == 'SELECT COUNT(*) FROM IDENTIFIER(:p0)'
    assert [(p.name, p.value) for p in kwargs['parameters']] == [('p0', 'main.sales.orders')]


@pytest.mark.parametrize('code, issue', [
    ("SELECT * FROM t WHERE name LIKE '%${entity_name}%'", 'script_sql_placeholder_in_quotes'),
    ('SELECT * FROM `${entity_id}`', 'script_sql_placeholder_in_quotes'),
    ('SELECT * FROM t WHERE name = "${entity_name}"', 'script_sql_placeholder_in_quotes'),
    ('SELECT * FROM main.${entity_name}', 'script_sql_placeholder_in_identifier'),
    ('SELECT * FROM t WHERE id IN (${entity.ids})', 'script_sql_placeholder_as_list'),
])
def test_a_placeholder_that_cannot_be_bound_is_refused_on_save(client, code, issue):
    response = client.post('/api/workflows', json=_body({'language': 'sql', 'code': code}))

    codes = _issues(response)
    assert [c for c, _ in codes] == [issue]
    assert codes[0][1]['step'] == 'script' and codes[0][1]['placeholder'].startswith('${')


def test_a_stored_placeholder_in_quotes_fails_at_run_time_without_running(
    client, db_session, warehouse,
):
    wf_id = _stored(db_session, {
        'language': 'sql', 'code': "SELECT * FROM t WHERE name LIKE '%${entity_name}%'",
    }, active=True)

    execution = _execute(client, wf_id, entity_name=EVIL_NAME)

    warehouse.assert_not_called()
    assert execution['status'] == 'failed'
    script = _step(execution, 'script')
    assert script['passed'] is False
    assert script['result_data']['error_code'] == 'script_sql_placeholder_in_quotes'
    assert script['result_data']['error_params'] == {'placeholder': '${entity_name}'}


def test_a_valid_sql_step_saves_and_activates(client):
    body = _body({'language': 'sql',
                  'code': "SELECT * FROM ${entity_id} WHERE owner = '${user_email}'"})

    created = client.post('/api/workflows', json=body)
    assert created.status_code == 200, created.text
    toggled = client.post(
        f"/api/workflows/{created.json()['id']}/toggle-active", params={'is_active': True},
    )
    assert toggled.status_code == 200, toggled.text
