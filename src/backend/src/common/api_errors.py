"""Errors with a stable code, sent to the UI as ``detail = {code, message, params}``.

Routes turn a ``ValueError`` into an ``HTTPException`` with ``detail=str(e)``.
For a ``CodedValueError`` that is still its English message, and
``coded_http_exception_handler`` sends the code and parameters along, so the
UI can show the error in the user's language (``message`` stays the
fallback). The routes don't change, and every other error is answered as
before.
"""
from typing import Any, Dict, Optional

from fastapi import Request
from fastapi.exception_handlers import http_exception_handler
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse, Response


class CodedValueError(ValueError):
    """A ``ValueError`` with a code and parameters for the UI."""

    code: str = ''

    def __init__(self, message: str, **params: Any):
        super().__init__(message)
        self.params: Dict[str, Any] = params


def _coded_cause(exc: BaseException) -> Optional[CodedValueError]:
    """The ``CodedValueError`` an HTTP error was raised from, if it carries its message."""
    seen = set()
    cause = exc.__cause__ or exc.__context__
    while cause is not None and id(cause) not in seen:
        if isinstance(cause, CodedValueError):
            return cause if getattr(exc, 'detail', None) == str(cause) else None
        seen.add(id(cause))
        cause = cause.__cause__ or cause.__context__
    return None


async def coded_http_exception_handler(request: Request, exc: StarletteHTTPException) -> Response:
    """Answer an HTTP error raised from a ``CodedValueError`` with its code and parameters."""
    cause = _coded_cause(exc)
    if cause is None:
        return await http_exception_handler(request, exc)
    return JSONResponse(
        status_code=exc.status_code,
        content={'detail': {'code': cause.code, 'message': str(cause), 'params': cause.params}},
        headers=getattr(exc, 'headers', None),
    )
