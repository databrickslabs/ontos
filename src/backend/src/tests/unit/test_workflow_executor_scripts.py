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
# Python execution — disabled (in-process exec() cannot be sandboxed)
# =========================================================================

class TestPythonDisabled:
    """Python script steps are refused rather than exec()'d in-process."""

    def test_python_script_is_refused(self, db_session):
        code = "result = {'passed': True}"
        handler = ScriptStepHandler(db=db_session, config={'language': 'python', 'code': code})
        result = handler.execute(_make_context())

        assert result.passed is False
        assert 'disabled' in result.error.lower()

    def test_sandbox_escape_payload_does_not_run(self, db_session):
        """The subclass-walk escape that reached os.popen must not execute."""
        code = (
            "for c in ().__class__.__base__.__subclasses__():\n"
            "    if c.__name__ == '_wrap_close':\n"
            "        result = {'passed': True, 'message': c.__init__.__globals__['popen']('id').read()}\n"
        )
        handler = ScriptStepHandler(db=db_session, config={'language': 'python', 'code': code})
        with patch('os.popen') as mock_popen:
            result = handler.execute(_make_context())

        assert result.passed is False
        mock_popen.assert_not_called()

    def test_python_script_no_code_fails(self, db_session):
        """Empty code config should fail the step."""
        handler = ScriptStepHandler(db=db_session, config={'language': 'python', 'code': ''})
        result = handler.execute(_make_context())

        assert result.passed is False
        assert 'code' in result.error.lower()


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
        assert executed_sql == "SELECT * FROM audit WHERE name = :p0"
        params = call_kwargs.kwargs['parameters']
        assert [(p.name, p.value) for p in params] == [('p0', 'my_product')]

    def test_sql_injection_in_entity_name_is_bound_not_pasted(self, db_session):
        """A malicious entity name must travel as a parameter value, never as SQL text."""
        from src.db_models.app_settings import AppSettingDb
        db_session.add(AppSettingDb(key="sql_warehouse_id", value="wh-abc"))
        db_session.flush()

        mock_resp = MagicMock()
        mock_resp.status.state.value = "SUCCEEDED"
        mock_resp.manifest.total_row_count = 0
        evil = "x'; DROP TABLE cat.sch.t; --"

        with patch('src.common.workspace_client.get_workspace_client') as mock_get_ws:
            mock_ws = MagicMock()
            mock_get_ws.return_value = mock_ws
            mock_ws.statement_execution.execute_statement.return_value = mock_resp

            handler = ScriptStepHandler(
                db=db_session,
                config={'language': 'sql', 'code': (
                    "SELECT * FROM audit WHERE name = '${entity_name}' "
                    "AND owner = {{entity.owner}} AND x = '${entity.missing}'"
                )},
            )
            handler.execute(_make_context(entity_name=evil))

        call_kwargs = mock_ws.statement_execution.execute_statement.call_args
        executed_sql = call_kwargs.kwargs['statement']
        assert 'DROP' not in executed_sql
        # Unresolved placeholders are left visible (and will fail loudly at the warehouse).
        assert executed_sql == "SELECT * FROM audit WHERE name = :p0 AND owner = :p1 AND x = ${entity.missing}"
        params = call_kwargs.kwargs['parameters']
        assert [(p.name, p.value) for p in params] == [('p0', evil), ('p1', 'alice@co.com')]

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
