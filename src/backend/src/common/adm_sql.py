"""Databricks SQL statement execution for the ADM reader (#1294 slice 4).

Statements run with ``wait_timeout="0s"`` and are polled with
``statement_execution.get_statement`` until a terminal state, so a slow warehouse never
holds a request open on one blocking call. Result chunks are followed with
``get_statement_result_chunk_n`` up to an explicit row cap; a read that hits the cap says so
(``AdmRows.truncated``) instead of passing a partial result off as complete.

Every SDK failure (permission, not found, network, timeout) is logged once with an error id
and raised as :class:`AdmQueryError` with a code. The server text never reaches a client. The
deadline, poll interval and sleep are injectable, so the polling is tested without a warehouse.
"""
from __future__ import annotations

import time
from typing import Any, Callable, Dict, List, Optional

from src.common.adm import typed_rows
from src.common.api_errors import CodedValueError, log_failure
from src.common.logging import get_logger

logger = get_logger(__name__)

ADM_QUERY_FAILED = "adm_query_failed"
ADM_QUERY_TIMEOUT = "adm_query_timeout"
ADM_NO_WAREHOUSE = "adm_no_warehouse"
ADM_RESULT_TRUNCATED = "adm_result_truncated"

DEFAULT_MAX_ROWS = 5000
_TERMINAL_FAILURES = ("FAILED", "CANCELED", "CLOSED")


class AdmQueryError(CodedValueError):
    """A statement that failed, timed out, was truncated or had no warehouse. ``code`` is safe to show."""

    http_status = 502

    def __init__(self, message: str, *, code: str = ADM_QUERY_FAILED, **params: Any):
        super().__init__(message, **params)
        self.code = code


class AdmRows(list):
    """Typed result rows. ``truncated`` is True when the row cap cut the result short."""

    truncated: bool = False


def _state_name(state: Any) -> str:
    value = getattr(state, "value", state)
    return str(value or "").upper()


def _sdk_failure(stage: str, exc: BaseException) -> AdmQueryError:
    """The coded error for an SDK exception. The detail is logged with an error id, never returned."""
    error_id = log_failure(f"ADM statement {stage}", exc)
    return AdmQueryError("The ADM statement failed.", code=ADM_QUERY_FAILED, error_id=error_id)


def run_query(
    sql: str,
    *,
    ws: Any,
    warehouse_id: Optional[str],
    timeout_s: float = 60.0,
    poll_s: float = 1.0,
    max_rows: int = DEFAULT_MAX_ROWS,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> AdmRows:
    """Run ``sql`` on the warehouse and return its rows as typed dicts (manifest types).

    A statement without a result set (DDL) returns no rows. Chunks are followed until the
    result ends or ``max_rows`` is reached; the returned rows then carry ``truncated=True``.
    """
    if not warehouse_id:
        raise AdmQueryError("No SQL warehouse is configured for the ADM schema.", code=ADM_NO_WAREHOUSE)
    stmt = ws.statement_execution
    try:
        resp = stmt.execute_statement(warehouse_id=warehouse_id, statement=sql, wait_timeout="0s")
    except Exception as exc:
        raise _sdk_failure("execute", exc)
    deadline = clock() + timeout_s
    statement_id = getattr(resp, "statement_id", None)
    while True:
        state = _state_name(getattr(getattr(resp, "status", None), "state", None))
        if state == "SUCCEEDED":
            break
        if state in _TERMINAL_FAILURES:
            error = getattr(getattr(resp, "status", None), "error", None)
            logger.warning("ADM statement %s ended %s: %s", statement_id, state, getattr(error, "message", None))
            raise AdmQueryError("The ADM statement failed.", state=state.lower())
        if clock() >= deadline:
            logger.warning("ADM statement %s still %s after %.0fs", statement_id, state, timeout_s)
            _cancel(stmt, statement_id)
            raise AdmQueryError("The ADM statement timed out.", code=ADM_QUERY_TIMEOUT)
        sleep(poll_s)
        try:
            resp = stmt.get_statement(statement_id)
        except Exception as exc:
            raise _sdk_failure("poll", exc)

    manifest = getattr(resp, "manifest", None)
    result = getattr(resp, "result", None)
    if manifest is None or not getattr(manifest, "schema", None):
        return AdmRows()
    columns = [(c.name, _type_name(c)) for c in manifest.schema.columns]
    data: List[Any] = list(getattr(result, "data_array", None) or [])
    next_index = getattr(result, "next_chunk_index", None)
    while next_index is not None and len(data) < max_rows:
        try:
            chunk = stmt.get_statement_result_chunk_n(statement_id, next_index)
        except Exception as exc:
            raise _sdk_failure("chunk", exc)
        data.extend(getattr(chunk, "data_array", None) or [])
        next_index = getattr(chunk, "next_chunk_index", None)
    truncated = next_index is not None or len(data) > max_rows
    if len(data) > max_rows:
        data = data[:max_rows]
    if truncated:
        logger.warning("ADM statement %s truncated at %d rows", statement_id, max_rows)
    rows = AdmRows(typed_rows(columns, data))
    rows.truncated = truncated
    return rows


def _type_name(column: Any) -> str:
    type_name = getattr(column, "type_name", None)
    return str(getattr(type_name, "value", type_name) or "STRING")


def _cancel(stmt: Any, statement_id: Optional[str]) -> None:
    try:
        stmt.cancel_execution(statement_id)
    except Exception:  # best effort: the warehouse times the statement out anyway
        logger.debug("ADM statement %s could not be cancelled", statement_id, exc_info=True)
