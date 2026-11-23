"""Databricks SQL statement execution for the ADM reader (#1294 slice 4).

Statements run with ``wait_timeout="0s"`` and are polled with
``statement_execution.get_statement`` until a terminal state, so a slow warehouse never
holds a request open on one blocking call. The deadline, poll interval and sleep are
injectable, so the polling is tested without a warehouse.

Failures raise :class:`AdmQueryError` with a code only. The server-side message is logged
(by the caller, with the statement's state), never sent to a client.
"""
from __future__ import annotations

import time
from typing import Any, Callable, Dict, List, Optional

from src.common.adm import typed_rows
from src.common.api_errors import CodedValueError
from src.common.logging import get_logger

logger = get_logger(__name__)

ADM_QUERY_FAILED = "adm_query_failed"
ADM_QUERY_TIMEOUT = "adm_query_timeout"
ADM_NO_WAREHOUSE = "adm_no_warehouse"

_TERMINAL_FAILURES = ("FAILED", "CANCELED", "CLOSED")


class AdmQueryError(CodedValueError):
    """A statement that failed, timed out or had no warehouse. ``code`` is safe to show."""

    http_status = 502

    def __init__(self, message: str, *, code: str = ADM_QUERY_FAILED, **params: Any):
        super().__init__(message, **params)
        self.code = code


def _state_name(state: Any) -> str:
    value = getattr(state, "value", state)
    return str(value or "").upper()


def run_query(
    sql: str,
    *,
    ws: Any,
    warehouse_id: Optional[str],
    timeout_s: float = 60.0,
    poll_s: float = 1.0,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> List[Dict[str, Any]]:
    """Run ``sql`` on the warehouse and return its rows as typed dicts (manifest types).

    A statement without a result set (DDL) returns an empty list.
    """
    if not warehouse_id:
        raise AdmQueryError("No SQL warehouse is configured for the ADM schema.", code=ADM_NO_WAREHOUSE)
    stmt = ws.statement_execution
    resp = stmt.execute_statement(warehouse_id=warehouse_id, statement=sql, wait_timeout="0s")
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
        resp = stmt.get_statement(statement_id)
    manifest = getattr(resp, "manifest", None)
    result = getattr(resp, "result", None)
    data = getattr(result, "data_array", None) or []
    if manifest is None or not getattr(manifest, "schema", None):
        return []
    columns = [(c.name, _type_name(c)) for c in manifest.schema.columns]
    return typed_rows(columns, data)


def _type_name(column: Any) -> str:
    type_name = getattr(column, "type_name", None)
    return str(getattr(type_name, "value", type_name) or "STRING")


def _cancel(stmt: Any, statement_id: Optional[str]) -> None:
    try:
        stmt.cancel_execution(statement_id)
    except Exception:  # best effort: the warehouse times the statement out anyway
        logger.debug("ADM statement %s could not be cancelled", statement_id, exc_info=True)
