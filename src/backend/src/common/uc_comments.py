"""Write Unity Catalog comments: the descriptions of tables, views and their columns.

One statement builder and one runner for every flow that writes descriptions
to Unity Catalog, so they quote, escape and classify errors the same way. The
caller passes the workspace client, so Unity Catalog checks the permissions of
whoever that client belongs to (the user's on-behalf-of client, or the app's).
"""
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Optional, Tuple

# Why a comment could not be written (``CommentWriteError.reason``)
PERMISSION_DENIED = 'permission_denied'
NOT_FOUND = 'not_found'
UNSUPPORTED_TEXT = 'unsupported_text'
# The caller's time (``timeout_seconds``) ran out before Unity Catalog answered
TIMED_OUT = 'timed_out'
FAILED = 'failed'

# Markers in Databricks SQL error messages
_PERMISSION_MARKERS = (
    'PERMISSION_DENIED', 'INSUFFICIENT_PERMISSIONS', 'does not have MODIFY',
    'does not have SELECT', 'is not the owner',
)
_NOT_FOUND_MARKERS = (
    'TABLE_OR_VIEW_NOT_FOUND', 'SCHEMA_NOT_FOUND', 'CATALOG_NOT_FOUND', 'UNRESOLVED_COLUMN',
    'FIELD_NOT_FOUND', 'COLUMN_NOT_FOUND',
)

# A save waits at most this long for its comment statement
DEFAULT_TIMEOUT_SECONDS = 60
# The shortest wait the Statement Execution API accepts, other than 0 (don't wait)
_MIN_WAIT_SECONDS = 5


class StatementError(RuntimeError):
    """A SQL statement did not succeed; the message is the warehouse's error."""


class CommentWriteError(RuntimeError):
    """A comment was not written. ``reason`` is a reason constant above (e.g. PERMISSION_DENIED)."""

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


def split_column_location(location: str) -> Optional[Tuple[str, str]]:
    """``(table_fqn, column_name)`` of a ``catalog.schema.table.column`` location, or None.

    Only the first three dots separate the parts: a column name may contain dots.
    """
    parts = (location or '').strip().split('.', 3)
    if len(parts) == 4 and all(parts):
        return '.'.join(parts[:3]), parts[3]
    return None


def quote_identifier(name: str) -> str:
    """A backquoted SQL identifier."""
    return '`' + name.replace('`', '``') + '`'


def quote_name(fqn: str) -> str:
    """``catalog.schema.table`` with every part backquoted."""
    return '.'.join(quote_identifier(part) for part in fqn.split('.'))


def string_literal(text: str) -> str:
    """A Databricks SQL string literal (backslash escapes are on by default)."""
    return "'" + text.replace('\\', '\\\\').replace("'", "\\'") + "'"


def comment_statement(table_fqn: str, column_name: Optional[str], text: Optional[str]) -> str:
    """``COMMENT ON TABLE`` (tables and views) or ``COMMENT ON COLUMN``.

    An empty ``text`` removes the comment (``IS NULL``).
    """
    if column_name:
        target = f'COLUMN {quote_name(table_fqn)}.{quote_identifier(column_name)}'
    else:
        target = f'TABLE {quote_name(table_fqn)}'
    value = string_literal(text) if text else 'NULL'
    return f'COMMENT ON {target} IS {value}'


def _call_with_timeout(call: Callable[[], Any], timeout_seconds: Optional[float]) -> Any:
    """``call()``, or ``TimeoutError`` when it has not returned after ``timeout_seconds``.

    The SDK call has no per-call timeout, so it runs on its own thread; on a
    timeout the caller goes on and the thread ends with the HTTP call.
    """
    if timeout_seconds is None:
        return call()
    if timeout_seconds <= 0:
        raise TimeoutError('No time left for the Unity Catalog call')
    executor = ThreadPoolExecutor(max_workers=1)
    try:
        return executor.submit(call).result(timeout=timeout_seconds)
    finally:
        executor.shutdown(wait=False)


def read_comment(
    ws: Any, table_fqn: str, column_name: Optional[str],
    *, timeout_seconds: Optional[float] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """``(table_type, comment)`` of a table or view, or of one of its columns, as read.

    ``table_type`` is the Unity Catalog type name (e.g. ``METRIC_VIEW``). Raises
    ``CommentWriteError`` (NOT_FOUND, PERMISSION_DENIED, TIMED_OUT or FAILED) when it
    can't be read; TIMED_OUT when ``timeout_seconds`` (None: the client's own timeout)
    passes first.
    """
    from databricks.sdk.errors import NotFound, PermissionDenied

    try:
        info = _call_with_timeout(lambda: ws.tables.get(full_name=table_fqn), timeout_seconds)
    except TimeoutError as e:
        raise CommentWriteError(TIMED_OUT, str(e)) from e
    except NotFound as e:
        raise CommentWriteError(NOT_FOUND, str(e)) from e
    except PermissionDenied as e:
        raise CommentWriteError(PERMISSION_DENIED, str(e)) from e
    except Exception as e:
        raise CommentWriteError(FAILED, str(e)) from e
    table_type = getattr(info.table_type, 'value', info.table_type)
    table_type = str(table_type) if table_type is not None else None
    if not column_name:
        return table_type, info.comment or None
    for column in info.columns or []:
        if column.name == column_name:
            return table_type, column.comment or None
    raise CommentWriteError(NOT_FOUND, f'Column {column_name} not found')


def classify_error(message: str) -> str:
    """PERMISSION_DENIED, NOT_FOUND or FAILED for a SQL error message."""
    if any(marker in message for marker in _PERMISSION_MARKERS):
        return PERMISSION_DENIED
    if any(marker in message for marker in _NOT_FOUND_MARKERS):
        return NOT_FOUND
    return FAILED


def execute_statement(
    ws: Any, warehouse_id: str, statement: str,
    *, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> Any:
    """Run ``statement`` on ``warehouse_id`` and wait for it.

    Raises ``StatementError`` unless it succeeded, ``TimeoutError`` when it is
    still running after ``timeout_seconds`` (then it is cancelled).
    """
    from databricks.sdk.service.sql import StatementState

    if timeout_seconds <= 0:
        raise TimeoutError('No time left for the SQL statement')
    deadline = time.monotonic() + timeout_seconds
    # Below the API's shortest wait, don't wait in the call: the loop below polls instead
    wait = int(timeout_seconds) if timeout_seconds >= _MIN_WAIT_SECONDS else 0
    resp = ws.statement_execution.execute_statement(
        statement=statement,
        warehouse_id=warehouse_id,
        wait_timeout=f'{min(wait, 50)}s',
    )
    while resp.status and resp.status.state in (StatementState.PENDING, StatementState.RUNNING):
        if time.monotonic() > deadline:
            try:
                ws.statement_execution.cancel_execution(resp.statement_id)
            except Exception:
                pass  # Best effort: the timeout is what the caller hears about
            raise TimeoutError('Timed out waiting for a SQL statement')
        time.sleep(1)
        resp = ws.statement_execution.get_statement(resp.statement_id)
    if not resp.status or resp.status.state != StatementState.SUCCEEDED:
        error = resp.status.error if resp.status else None
        raise StatementError(getattr(error, 'message', None) or 'unknown error')
    return resp


def set_comment(
    ws: Any, warehouse_id: str, table_fqn: str, column_name: Optional[str], text: Optional[str],
    *, timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> None:
    """Set (or, for an empty ``text``, remove) the comment of a table, view or column.

    Raises ``CommentWriteError`` with the reason when it isn't written (TIMED_OUT
    when the statement is still running after ``timeout_seconds``).
    """
    from databricks.sdk.errors import PermissionDenied

    if text and '\x00' in text:
        # Unity Catalog stores no NUL characters; the statement would not be valid SQL
        raise CommentWriteError(UNSUPPORTED_TEXT, 'The text contains a NUL character')
    statement = comment_statement(table_fqn, column_name, text)
    try:
        execute_statement(ws, warehouse_id, statement, timeout_seconds=timeout_seconds)
    except TimeoutError as e:
        raise CommentWriteError(TIMED_OUT, str(e)) from e
    except StatementError as e:
        raise CommentWriteError(classify_error(str(e)), str(e)) from e
    except PermissionDenied as e:
        # Refused before the statement ran (e.g. no CAN USE on the warehouse)
        raise CommentWriteError(PERMISSION_DENIED, str(e)) from e
    except Exception as e:
        raise CommentWriteError(FAILED, str(e)) from e
