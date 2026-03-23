# Set test environment variables BEFORE any app imports
import os
os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import pytest
from unittest.mock import MagicMock, patch

from src.common.workflow_executor import ScriptStepHandler, StepContext


def _make_context(**overrides) -> StepContext:
    """Build a minimal StepContext for testing."""
    defaults = dict(
        entity={'name': 'test_table', 'status': 'draft', 'owner': 'alice@co.com'},
        entity_type='table',
        entity_id='entity-123',
        entity_name='test_table',
        user_email='user@example.com',
        trigger_context=None,
        execution_id='exec-1',
        workflow_id='wf-1',
        workflow_name='Test Workflow',
        step_results={'validate': {'passed': True, 'score': 95}},
    )
    defaults.update(overrides)
    return StepContext(**defaults)


# =========================================================================
# Python execution — User Story 13
# =========================================================================

class TestPythonSafeBuiltins:
    """US13: Python scripts with basic builtins for custom validation."""

    def test_python_script_can_use_safe_builtins(self, db_session):
        """len(), str(), sorted(), min(), max() etc. must work."""
        code = "result = {'passed': True, 'data': {'length': len(entity['name']), 'type': str(type(entity))}}"
        handler = ScriptStepHandler(db=db_session, config={'language': 'python', 'code': code})
        result = handler.execute(_make_context())

        assert result.passed is True
        assert result.data['length'] == len('test_table')

    def test_python_script_has_entity_data_in_globals(self, db_session):
        """entity, entity_type, entity_id, entity_name, user_email, step_results must be accessible."""
        code = """
result = {
    'passed': True,
    'data': {
        'name': entity['name'],
        'etype': entity_type,
        'eid': entity_id,
        'ename': entity_name,
        'email': user_email,
        'prev_score': step_results['validate']['score'],
    }
}
"""
        handler = ScriptStepHandler(db=db_session, config={'language': 'python', 'code': code})
        result = handler.execute(_make_context())

        assert result.passed is True
        assert result.data['name'] == 'test_table'
        assert result.data['etype'] == 'table'
        assert result.data['eid'] == 'entity-123'
        assert result.data['ename'] == 'test_table'
        assert result.data['email'] == 'user@example.com'
        assert result.data['prev_score'] == 95

    def test_python_script_times_out_with_clear_error(self, db_session):
        """Scripts exceeding timeout_seconds return a clear timeout error."""
        code = """
import time
time.sleep(10)
result = {'passed': True}
"""
        # Note: 'time' is not in safe builtins, so this will fail with NameError
        # instead of timeout. Let's use a busy loop instead.
        code = """
while True:
    pass
"""
        handler = ScriptStepHandler(
            db=db_session,
            config={'language': 'python', 'code': code, 'timeout_seconds': 1},
        )
        result = handler.execute(_make_context())

        assert result.passed is False
        assert 'timed out' in result.error.lower()

    def test_python_script_cannot_import_os(self, db_session):
        """Sandbox must prevent importing dangerous modules."""
        code = "import os; result = {'passed': True, 'data': {'cwd': os.getcwd()}}"
        handler = ScriptStepHandler(db=db_session, config={'language': 'python', 'code': code})
        result = handler.execute(_make_context())

        assert result.passed is False
        # Should get an ImportError or NameError because __import__ is not in safe builtins
        assert result.error is not None

    def test_python_script_cannot_access_open(self, db_session):
        """Sandbox must prevent file system access via open()."""
        code = "f = open('/etc/passwd'); result = {'passed': True}"
        handler = ScriptStepHandler(db=db_session, config={'language': 'python', 'code': code})
        result = handler.execute(_make_context())

        assert result.passed is False

    def test_python_script_default_result_is_pass(self, db_session):
        """Script that doesn't set 'result' should default to passed=True."""
        code = "x = len(entity['name'])"
        handler = ScriptStepHandler(db=db_session, config={'language': 'python', 'code': code})
        result = handler.execute(_make_context())

        assert result.passed is True

    def test_python_script_can_fail_explicitly(self, db_session):
        """Script can set result = {'passed': False} to fail the step."""
        code = "result = {'passed': False, 'message': 'Validation failed: name too short'}"
        handler = ScriptStepHandler(db=db_session, config={'language': 'python', 'code': code})
        result = handler.execute(_make_context())

        assert result.passed is False
        assert 'too short' in result.message

    def test_python_script_no_code_fails(self, db_session):
        """Empty code config should fail the step."""
        handler = ScriptStepHandler(db=db_session, config={'language': 'python', 'code': ''})
        result = handler.execute(_make_context())

        assert result.passed is False
        assert 'code' in result.error.lower()

    def test_python_timeout_is_configurable(self, db_session):
        """timeout_seconds from config should be used, not hardcoded."""
        # A script that finishes in <1s should pass with timeout=2
        code = "result = {'passed': True}"
        handler = ScriptStepHandler(
            db=db_session,
            config={'language': 'python', 'code': code, 'timeout_seconds': 2},
        )
        result = handler.execute(_make_context())
        assert result.passed is True


# =========================================================================
# SQL execution — User Story 14
# =========================================================================

class TestSQLExecution:
    """US14: SQL queries against Databricks SQL Warehouse in workflow steps."""

    def test_sql_executes_via_statement_execution_api(self, db_session):
        """SQL should call ws.statement_execution.execute_statement()."""
        # Set up warehouse ID in settings
        from src.db_models.app_settings import AppSettingDb
        db_session.add(AppSettingDb(key="sql_warehouse_id", value="wh-abc123"))
        db_session.flush()

        mock_resp = MagicMock()
        mock_resp.status.state.value = "SUCCEEDED"
        mock_resp.manifest.total_row_count = 42

        with patch('src.common.workspace_client.get_workspace_client') as mock_get_ws:
            mock_ws = MagicMock()
            mock_get_ws.return_value = mock_ws
            mock_ws.statement_execution.execute_statement.return_value = mock_resp

            handler = ScriptStepHandler(
                db=db_session,
                config={'language': 'sql', 'code': 'SELECT count(*) FROM my_table'},
            )
            result = handler.execute(_make_context())

        assert result.passed is True
        assert result.data['row_count'] == 42
        mock_ws.statement_execution.execute_statement.assert_called_once()
        call_kwargs = mock_ws.statement_execution.execute_statement.call_args
        assert call_kwargs.kwargs['warehouse_id'] == 'wh-abc123'

    def test_sql_supports_variable_substitution(self, db_session):
        """${entity_name} and other vars should be resolved before execution."""
        from src.db_models.app_settings import AppSettingDb
        db_session.add(AppSettingDb(key="sql_warehouse_id", value="wh-abc"))
        db_session.flush()

        mock_resp = MagicMock()
        mock_resp.status.state.value = "SUCCEEDED"
        mock_resp.manifest.total_row_count = 1

        with patch('src.common.workspace_client.get_workspace_client') as mock_get_ws:
            mock_ws = MagicMock()
            mock_get_ws.return_value = mock_ws
            mock_ws.statement_execution.execute_statement.return_value = mock_resp

            handler = ScriptStepHandler(
                db=db_session,
                config={'language': 'sql', 'code': "SELECT * FROM audit WHERE name = '${entity_name}'"},
            )
            result = handler.execute(_make_context(entity_name='my_product'))

        call_kwargs = mock_ws.statement_execution.execute_statement.call_args
        executed_sql = call_kwargs.kwargs['statement']
        assert 'my_product' in executed_sql
        assert '${entity_name}' not in executed_sql

    def test_sql_returns_clear_error_when_no_warehouse(self, db_session):
        """Missing sql_warehouse_id should return a clear error, not crash."""
        # Don't add any SettingDb row — warehouse not configured
        handler = ScriptStepHandler(
            db=db_session,
            config={'language': 'sql', 'code': 'SELECT 1'},
        )
        result = handler.execute(_make_context())

        assert result.passed is False
        assert 'warehouse' in result.error.lower()

    def test_sql_returns_fail_on_execution_error(self, db_session):
        """SQL that fails on the warehouse should return passed=False with error details."""
        from src.db_models.app_settings import AppSettingDb
        db_session.add(AppSettingDb(key="sql_warehouse_id", value="wh-abc"))
        db_session.flush()

        mock_resp = MagicMock()
        mock_resp.status.state.value = "FAILED"
        mock_resp.status.error.message = "Table not found: nonexistent"

        with patch('src.common.workspace_client.get_workspace_client') as mock_get_ws:
            mock_ws = MagicMock()
            mock_get_ws.return_value = mock_ws
            mock_ws.statement_execution.execute_statement.return_value = mock_resp

            handler = ScriptStepHandler(
                db=db_session,
                config={'language': 'sql', 'code': 'SELECT * FROM nonexistent'},
            )
            result = handler.execute(_make_context())

        assert result.passed is False
        assert 'FAILED' in result.error
        assert 'not found' in result.error.lower()

    def test_sql_handles_workspace_client_error(self, db_session):
        """If workspace client throws, should return clear error not crash."""
        from src.db_models.app_settings import AppSettingDb
        db_session.add(AppSettingDb(key="sql_warehouse_id", value="wh-abc"))
        db_session.flush()

        with patch('src.common.workspace_client.get_workspace_client') as mock_get_ws:
            mock_get_ws.side_effect = RuntimeError("Cannot connect to workspace")

            handler = ScriptStepHandler(
                db=db_session,
                config={'language': 'sql', 'code': 'SELECT 1'},
            )
            result = handler.execute(_make_context())

        assert result.passed is False
        assert 'connect' in result.error.lower()
