"""Write Unity Catalog comments: the descriptions of tables, views and their columns.

One statement builder and one runner for every flow that writes descriptions
to Unity Catalog, so they quote, escape and classify errors the same way. The
caller passes the workspace client, so Unity Catalog checks the permissions of
whoever that client belongs to (the user's on-behalf-of client, or the app's).
"""
import time
from typing import Any, Optional

# Why a comment could not be written (``CommentWriteError.reason``)
PERMISSION_DENIED = 'permission_denied'
NOT_FOUND = 'not_found'
FAILED = 'failed'

# Markers in Databricks SQL error messages
_PERMISSION_MARKERS = (
    'PERMISSION_DENIED', 'INSUFFICIENT_PERMISSIONS', 'does not have MODIFY', 'is not the owner',
)
_NOT_FOUND_MARKERS = (
    'TABLE_OR_VIEW_NOT_FOUND', 'SCHEMA_NOT_FOUND', 'CATALOG_NOT_FOUND', 'UNRESOLVED_COLUMN',
    'FIELD_NOT_FOUND', 'COLUMN_NOT_FOUND',
)

# A save waits at most this long for its comment statement
DEFAULT_TIMEOUT_SECONDS = 60


class StatementError(RuntimeError):
    """A SQL statement did not succeed; the message is the warehouse's error."""


class CommentWriteError(RuntimeError):
    """A comment was not written. ``reason`` is one of PERMISSION_DENIED, NOT_FOUND, FAILED."""

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


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


def classify_error(message: str) -> str:
    """PERMISSION_DENIED, NOT_FOUND or FAILED for a SQL error message."""
    if any(marker in message for marker in _PERMISSION_MARKERS):
        return PERMISSION_DENIED
    if any(marker in message for marker in _NOT_FOUND_MARKERS):
        return NOT_FOUND
    return FAILED


def execute_statement(
    ws: Any, warehouse_id: str, statement: str, *, timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> Any:
    """Run ``statement`` on ``warehouse_id`` and wait for it.

    Raises ``StatementError`` unless it succeeded, ``TimeoutError`` when it is
    still running after ``timeout_seconds``.
    """
    from databricks.sdk.service.sql import StatementState

    resp = ws.statement_execution.execute_statement(
        statement=statement,
        warehouse_id=warehouse_id,
        wait_timeout=f'{min(max(timeout_seconds, 5), 50)}s',
    )
    deadline = time.monotonic() + timeout_seconds
    while resp.status and resp.status.state in (StatementState.PENDING, StatementState.RUNNING):
        if time.monotonic() > deadline:
            raise TimeoutError('Timed out waiting for a SQL statement')
        time.sleep(1)
        resp = ws.statement_execution.get_statement(resp.statement_id)
    if not resp.status or resp.status.state != StatementState.SUCCEEDED:
        error = resp.status.error if resp.status else None
        raise StatementError(getattr(error, 'message', None) or 'unknown error')
    return resp


def set_comment(
    ws: Any, warehouse_id: str, table_fqn: str, column_name: Optional[str], text: Optional[str],
    *, timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> None:
    """Set (or, for an empty ``text``, remove) the comment of a table, view or column.

    Raises ``CommentWriteError`` with the reason when it isn't written.
    """
    from databricks.sdk.errors import PermissionDenied

    statement = comment_statement(table_fqn, column_name, text)
    try:
        execute_statement(ws, warehouse_id, statement, timeout_seconds=timeout_seconds)
    except StatementError as e:
        raise CommentWriteError(classify_error(str(e)), str(e)) from e
    except PermissionDenied as e:
        # Refused before the statement ran (e.g. no CAN USE on the warehouse)
        raise CommentWriteError(PERMISSION_DENIED, str(e)) from e
    except Exception as e:
        raise CommentWriteError(FAILED, str(e)) from e
