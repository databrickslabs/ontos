"""Errors with a stable code, sent to the UI as ``detail = {code, message, params}``.

Routes turn a ``ValueError`` into an ``HTTPException`` with ``detail=str(e)``.
For a ``CodedValueError`` that is still its English message, and
``coded_http_exception_handler`` sends the code and parameters along, so the
UI can show the error in the user's language (``message`` stays the
fallback). The routes don't change, and every other error is answered as
before.

Many routes also answer an unexpected failure with ``HTTPException(500,
detail=f"...: {e}")``, which sends the exception's text (SQL statements and
their parameters, file paths, workspace hosts) to the browser. The handler
answers such a server error with a generic message and an error id instead,
and logs the original text with that id. Server errors whose text doesn't come
from the exception they were raised from are left as they are.
"""
import logging
import uuid
from typing import Any, Dict, Iterator, Optional

from fastapi import Request
from fastapi.exception_handlers import http_exception_handler
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import JSONResponse, Response


logger = logging.getLogger(__name__)

INTERNAL_ERROR_CODE = 'internal_error'
INTERNAL_ERROR_MESSAGE = (
    'An unexpected error occurred. The details are in the server log (error id {errorId}).'
)


def new_error_id() -> str:
    """A short id that ties an error shown to a user to its log entry."""
    return uuid.uuid4().hex[:12]


class CodedValueError(ValueError):
    """A ``ValueError`` with a code and parameters for the UI."""

    code: str = ''

    def __init__(self, message: str, **params: Any):
        super().__init__(message)
        self.params: Dict[str, Any] = params


class InvalidStatusTransitionError(CodedValueError):
    """A status change that the entity's lifecycle doesn't allow."""

    code = 'invalid_status_transition'


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


def _causes(exc: BaseException) -> Iterator[BaseException]:
    """The exceptions an error was raised from (``raise ... from`` or inside ``except``)."""
    seen = set()
    cause = exc.__cause__ or exc.__context__
    while cause is not None and id(cause) not in seen:
        seen.add(id(cause))
        yield cause
        cause = cause.__cause__ or cause.__context__


def _texts(detail: Any) -> Iterator[str]:
    """The strings in an error detail (a string, or nested in a dict or list)."""
    if isinstance(detail, str):
        yield detail
    elif isinstance(detail, dict):
        for value in detail.values():
            yield from _texts(value)
    elif isinstance(detail, (list, tuple)):
        for value in detail:
            yield from _texts(value)


def _leaked_cause(exc: StarletteHTTPException) -> Optional[BaseException]:
    """The exception whose text a server error's detail repeats, if any."""
    if exc.status_code < 500:
        return None
    texts = list(_texts(getattr(exc, 'detail', None)))
    if not texts:
        return None
    for cause in _causes(exc):
        cause_text = str(cause).strip()
        if cause_text and any(cause_text in text for text in texts):
            return cause
    return None


def _internal_error_response(request: Request, exc: StarletteHTTPException, cause: BaseException) -> Response:
    """A server error without the exception's text; the text goes to the log with an error id."""
    error_id = new_error_id()
    logger.error(
        "Server error %s on %s %s (%s): %s",
        error_id, request.method, request.url.path, type(cause).__name__, exc.detail,
        exc_info=(type(cause), cause, cause.__traceback__),
    )
    # ``detail`` stays a string: many callers show it as text. The code and the
    # parameters travel next to it, so the UI can show it in the user's language.
    return JSONResponse(
        status_code=exc.status_code,
        content={
            'detail': INTERNAL_ERROR_MESSAGE.format(errorId=error_id),
            'code': INTERNAL_ERROR_CODE,
            'params': {'errorId': error_id},
        },
        headers=getattr(exc, 'headers', None),
    )


async def coded_http_exception_handler(request: Request, exc: StarletteHTTPException) -> Response:
    """Answer an HTTP error raised from a ``CodedValueError`` with its code and parameters.

    A server error that repeats the text of the exception it was raised from is
    answered with a generic message and an error id (see the module docstring).
    """
    cause = _coded_cause(exc)
    if cause is None:
        leaked = _leaked_cause(exc)
        if leaked is not None:
            return _internal_error_response(request, exc, leaked)
        return await http_exception_handler(request, exc)
    return JSONResponse(
        status_code=exc.status_code,
        content={'detail': {'code': cause.code, 'message': str(cause), 'params': cause.params}},
        headers=getattr(exc, 'headers', None),
    )
