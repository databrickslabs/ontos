"""Unity Catalog comment statements: quoting, escaping, running and error reasons (#1477)."""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from databricks.sdk.errors import PermissionDenied
from databricks.sdk.service.sql import StatementState

from src.common import uc_comments
from src.common.uc_comments import (
    FAILED, NOT_FOUND, PERMISSION_DENIED, CommentWriteError, comment_statement, set_comment,
    string_literal,
)


def _response(state, message=None, statement_id='st-1'):
    error = SimpleNamespace(message=message) if message else None
    return SimpleNamespace(status=SimpleNamespace(state=state, error=error),
                           statement_id=statement_id)


def _ws(*responses):
    ws = MagicMock()
    ws.statement_execution.execute_statement.return_value = responses[0]
    ws.statement_execution.get_statement.side_effect = list(responses[1:])
    return ws


def test_a_table_comment_quotes_every_name_part():
    assert comment_statement('main.sales.orders', None, 'About orders') == \
        "COMMENT ON TABLE `main`.`sales`.`orders` IS 'About orders'"


def test_a_column_comment_names_the_column():
    assert comment_statement('main.sales.orders', 'id', 'The key') == \
        "COMMENT ON COLUMN `main`.`sales`.`orders`.`id` IS 'The key'"


def test_quotes_backquotes_and_backslashes_are_escaped():
    assert string_literal("a'b\\c") == "'a\\'b\\\\c'"
    assert comment_statement('main.s.we`ird', 'c`ol', "It's") == \
        "COMMENT ON COLUMN `main`.`s`.`we``ird`.`c``ol` IS 'It\\'s'"


@pytest.mark.parametrize('text', [None, ''])
def test_an_empty_description_removes_the_comment(text):
    assert comment_statement('main.sales.orders', None, text) == \
        'COMMENT ON TABLE `main`.`sales`.`orders` IS NULL'


def test_set_comment_runs_the_statement_on_the_warehouse():
    ws = _ws(_response(StatementState.SUCCEEDED))

    set_comment(ws, 'wh-1', 'main.sales.orders', None, 'About orders')

    kwargs = ws.statement_execution.execute_statement.call_args.kwargs
    assert kwargs['statement'] == "COMMENT ON TABLE `main`.`sales`.`orders` IS 'About orders'"
    assert kwargs['warehouse_id'] == 'wh-1'


def test_set_comment_waits_for_a_running_statement(monkeypatch):
    monkeypatch.setattr(uc_comments.time, 'sleep', lambda s: None)
    ws = _ws(_response(StatementState.RUNNING), _response(StatementState.SUCCEEDED))

    set_comment(ws, 'wh-1', 'main.sales.orders', 'id', 'x')

    ws.statement_execution.get_statement.assert_called_once_with('st-1')


@pytest.mark.parametrize('message, reason', [
    ('[INSUFFICIENT_PERMISSIONS] User does not have MODIFY on Table main.sales.orders',
     PERMISSION_DENIED),
    ('PERMISSION_DENIED: User is not the owner of the table', PERMISSION_DENIED),
    ('[TABLE_OR_VIEW_NOT_FOUND] The table or view `main`.`sales`.`gone` cannot be found',
     NOT_FOUND),
    ('[UNRESOLVED_COLUMN.WITH_SUGGESTION] A column `nope` cannot be resolved', NOT_FOUND),
    ('[PARSE_SYNTAX_ERROR] Syntax error', FAILED),
])
def test_a_failed_statement_has_its_reason(message, reason):
    ws = _ws(_response(StatementState.FAILED, message))

    with pytest.raises(CommentWriteError) as raised:
        set_comment(ws, 'wh-1', 'main.sales.orders', None, 'x')

    assert raised.value.reason == reason


def test_a_warehouse_the_user_may_not_use_is_permission_denied():
    ws = MagicMock()
    ws.statement_execution.execute_statement.side_effect = PermissionDenied('no CAN USE')

    with pytest.raises(CommentWriteError) as raised:
        set_comment(ws, 'wh-1', 'main.sales.orders', None, 'x')

    assert raised.value.reason == PERMISSION_DENIED


def test_any_other_error_is_a_failure():
    ws = MagicMock()
    ws.statement_execution.execute_statement.side_effect = ConnectionError('reset')

    with pytest.raises(CommentWriteError) as raised:
        set_comment(ws, 'wh-1', 'main.sales.orders', None, 'x')

    assert raised.value.reason == FAILED
