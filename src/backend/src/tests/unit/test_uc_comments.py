"""Unity Catalog comment statements: quoting, escaping, running and error reasons (#1477)."""
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from databricks.sdk.errors import PermissionDenied
from databricks.sdk.service.sql import StatementState

from src.common import uc_comments
from src.common.uc_comments import (
    FAILED, NOT_FOUND, PERMISSION_DENIED, TIMED_OUT, UNSUPPORTED_TEXT, CommentWriteError,
    comment_statement,
    read_comment, set_comment, split_column_location, string_literal,
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
    # As measured: COMMENT ON by a principal with MODIFY but no SELECT
    ('User does not have SELECT on Table main.sales.orders', PERMISSION_DENIED),
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


def test_a_statement_still_running_at_the_timeout_is_cancelled(monkeypatch):
    clock = iter([0, 0, 100])
    monkeypatch.setattr(uc_comments.time, 'monotonic', lambda: next(clock))
    monkeypatch.setattr(uc_comments.time, 'sleep', lambda s: None)
    ws = _ws(_response(StatementState.RUNNING), _response(StatementState.RUNNING))

    with pytest.raises(CommentWriteError) as raised:
        set_comment(ws, 'wh-1', 'main.sales.orders', None, 'x', timeout_seconds=10)

    assert raised.value.reason == TIMED_OUT
    ws.statement_execution.cancel_execution.assert_called_once_with('st-1')


def test_no_time_left_runs_no_statement():
    ws = _ws(_response(StatementState.SUCCEEDED))

    with pytest.raises(CommentWriteError) as raised:
        set_comment(ws, 'wh-1', 'main.sales.orders', None, 'x', timeout_seconds=0)

    assert raised.value.reason == TIMED_OUT
    ws.statement_execution.execute_statement.assert_not_called()


@pytest.mark.parametrize('timeout, wait', [(3, '0s'), (30, '30s'), (120, '50s')])
def test_the_statement_waits_no_longer_than_the_time_left(timeout, wait):
    ws = _ws(_response(StatementState.SUCCEEDED))

    set_comment(ws, 'wh-1', 'main.sales.orders', None, 'x', timeout_seconds=timeout)

    assert ws.statement_execution.execute_statement.call_args.kwargs['wait_timeout'] == wait


def test_a_read_slower_than_its_timeout_times_out():
    release = threading.Event()
    ws = MagicMock()
    ws.tables.get.side_effect = lambda **kwargs: release.wait(5)

    try:
        with pytest.raises(CommentWriteError) as raised:
            read_comment(ws, 'main.sales.orders', None, timeout_seconds=0.05)
    finally:
        release.set()

    assert raised.value.reason == TIMED_OUT


def test_a_read_with_no_time_left_is_not_sent():
    ws = MagicMock()

    with pytest.raises(CommentWriteError) as raised:
        read_comment(ws, 'main.sales.orders', None, timeout_seconds=0)

    assert raised.value.reason == TIMED_OUT
    ws.tables.get.assert_not_called()


@pytest.mark.parametrize('text, literal', [
    ('line one\nline two', "'line one\nline two'"),
    ('Preço: 5 € – “aspas”', "'Preço: 5 € – “aspas”'"),
    ('ends with a backslash \\', "'ends with a backslash \\\\'"),
    ("it's", "'it\\'s'"),
])
def test_text_keeps_newlines_unicode_and_backslashes(text, literal):
    assert string_literal(text) == literal


def test_a_view_comment_is_a_table_statement():
    assert comment_statement('main.sales.orders_v', None, 'x') == \
        "COMMENT ON TABLE `main`.`sales`.`orders_v` IS 'x'"


def test_a_nul_character_is_refused_before_any_statement():
    ws = MagicMock()

    with pytest.raises(CommentWriteError) as raised:
        set_comment(ws, 'wh-1', 'main.sales.orders', None, 'bad\x00text')

    assert raised.value.reason == UNSUPPORTED_TEXT
    ws.statement_execution.execute_statement.assert_not_called()


def test_a_column_location_splits_at_the_third_dot():
    assert split_column_location('main.sales.orders.a.b') == ('main.sales.orders', 'a.b')
    assert split_column_location('main.sales.orders') is None
    assert split_column_location('main..orders.col') is None


def test_read_comment_of_a_table_and_of_a_column():
    ws = MagicMock()
    ws.tables.get.return_value = SimpleNamespace(
        table_type=SimpleNamespace(value='MANAGED'), comment='Orders',
        columns=[SimpleNamespace(name='id', comment='Key')])

    assert read_comment(ws, 'main.sales.orders', None) == ('MANAGED', 'Orders')
    assert read_comment(ws, 'main.sales.orders', 'id') == ('MANAGED', 'Key')
    ws.tables.get.assert_called_with(full_name='main.sales.orders')


@pytest.mark.parametrize('error, reason', [
    (PermissionDenied('no BROWSE'), PERMISSION_DENIED),
    (RuntimeError('boom'), FAILED),
])
def test_read_comment_reports_the_reason(error, reason):
    ws = MagicMock()
    ws.tables.get.side_effect = error

    with pytest.raises(CommentWriteError) as raised:
        read_comment(ws, 'main.sales.orders', None)

    assert raised.value.reason == reason


def test_a_missing_column_is_not_found():
    ws = MagicMock()
    ws.tables.get.return_value = SimpleNamespace(table_type=None, comment=None, columns=[])

    with pytest.raises(CommentWriteError) as raised:
        read_comment(ws, 'main.sales.orders', 'gone')

    assert raised.value.reason == NOT_FOUND


@pytest.mark.parametrize('text, expected', [
    (None, None), ('', None), ('  \r\n ', None), ('a', 'a'),
    ('a \r\nb\t\n', 'a\nb'), ('a\rb', 'a\nb'), ('  a b  ', 'a b'),
    ('a\u00a0', 'a'), ('\u00a0a\u2028', 'a'),
])
def test_normalize_comment_ignores_line_endings_and_trailing_blanks(text, expected):
    assert uc_comments.normalize_comment(text) == expected


def _table_info(comment, columns, table_type=None):
    return SimpleNamespace(
        table_type=table_type, comment=comment,
        columns=[SimpleNamespace(name=n, comment=c) for n, c in columns.items()])


def test_one_read_returns_the_table_and_every_column_comment():
    ws = MagicMock()
    ws.tables.get.return_value = _table_info(
        'About orders', {'id': 'The key', 'note': '', 'other': None}, table_type='MANAGED')

    comments = uc_comments.read_table_comments(ws, 'main.sales.orders')

    ws.tables.get.assert_called_once_with(full_name='main.sales.orders')
    assert comments.table_type == 'MANAGED' and comments.comment == 'About orders'
    assert comments.columns == {'id': 'The key', 'note': None, 'other': None}


def test_the_single_comment_read_agrees_with_the_full_one():
    ws = MagicMock()
    ws.tables.get.return_value = _table_info('T', {'id': 'C'})

    assert read_comment(ws, 'main.sales.orders', None) == (None, 'T')
    assert read_comment(ws, 'main.sales.orders', 'id') == (None, 'C')
    with pytest.raises(CommentWriteError) as e:
        read_comment(ws, 'main.sales.orders', 'missing')
    assert e.value.reason == NOT_FOUND


def test_a_table_that_cannot_be_read_says_why():
    from databricks.sdk.errors import NotFound

    ws = MagicMock()
    for error, reason in ((NotFound('x'), NOT_FOUND), (PermissionDenied('x'), PERMISSION_DENIED),
                          (RuntimeError('x'), FAILED)):
        ws.tables.get.side_effect = error
        with pytest.raises(CommentWriteError) as e:
            uc_comments.read_table_comments(ws, 'main.sales.orders')
        assert e.value.reason == reason
