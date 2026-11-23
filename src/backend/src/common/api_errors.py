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

from fastapi import HTTPException, Request
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


def log_failure(tag: str, exc: BaseException) -> str:
    """Log an unexpected failure once, with an error id, and return that id.

    The id is kept on the exception as ``error_id``. A later caller that answers
    the same failure (a route, then the run row it failed) reuses the id and does
    not log the failure again.
    """
    existing = getattr(exc, 'error_id', None)
    if existing:
        return existing
    error_id = new_error_id()
    logger.error(
        "[%s] failed (error id %s): %s: %s", tag, error_id, type(exc).__name__, exc, exc_info=exc,
    )
    try:
        exc.error_id = error_id
    except AttributeError:
        pass
    return error_id


def client_failure(tag: str, exc: BaseException, *, code: str, message: str) -> Dict[str, Any]:
    """The coded client payload for an unexpected failure: ``{code, message, params}``.

    ``message`` may contain ``{errorId}``, which is filled with the error id that
    ``log_failure`` logged. The exception's text stays in the server log.
    """
    error_id = log_failure(tag, exc)
    return {'code': code, 'message': message.format(errorId=error_id), 'params': {'errorId': error_id}}


class CodedValueError(ValueError):
    """A ``ValueError`` with a code and parameters for the UI.

    ``http_status`` (optional) is the status a route answers the refusal with.
    """

    code: str = ''
    http_status: Optional[int] = None

    def __init__(self, message: str, **params: Any):
        super().__init__(message)
        self.message: str = message
        self.params: Dict[str, Any] = params


REQUEST_FAILED_CODE = 'request_failed'
REQUEST_FAILED_MESSAGE = 'The request failed (error id {errorId}). See the server log.'


def coded_http_error(
    tag: str,
    exc: BaseException,
    *,
    coded_status: int = 400,
    unexpected_status: int = 500,
    failure_code: str = REQUEST_FAILED_CODE,
    message: str = REQUEST_FAILED_MESSAGE,
) -> HTTPException:
    """The HTTP answer for an exception raised while handling a request.

    A ``CodedValueError`` keeps its code and message: the refusal is logged (at info),
    answered with ``coded_status`` (or its own ``http_status``, e.g. 403 for a
    permission refusal, 409 for a conflict), and its detail is built from the
    exception's attributes. Any other exception is logged once with an error id and
    answered generically with ``failure_code`` and ``message`` (``{errorId}`` is filled
    in). Raise the result outside the ``except`` block where it is built.
    """
    if isinstance(exc, CodedValueError):
        logger.info("[%s] refused: %s", tag, exc.code)
        # The detail is the coded message; the handler matches it to the exception and sends the code.
        error = HTTPException(status_code=exc.http_status or coded_status, detail=exc.message)
        error.__cause__ = exc
        return error
    payload = client_failure(tag, exc, code=failure_code, message=message)
    return HTTPException(status_code=unexpected_status, detail=payload)


class InvalidStatusTransitionError(CodedValueError):
    """A status change that the entity's lifecycle doesn't allow."""

    code = 'invalid_status_transition'


class UserTokenRequiredError(CodedValueError):
    """The request has no user (on-behalf-of) token to call Databricks with."""

    code = 'user_token_required'


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


PERMISSION_CHECK_FAILED_CODE = 'permission_check_failed'


def permission_check_failure(feature_id: str, exc: BaseException) -> StarletteHTTPException:
    """The 500 for a permission check that raised (not a denial).

    The exception's type and text go to the server log with an error id, which
    the client gets with the code; the check's feature id is in the parameters.
    Raise the result outside the ``except`` block, so the text is not chained.
    """
    payload = client_failure(
        f"permission check for '{feature_id}'", exc,
        code=PERMISSION_CHECK_FAILED_CODE,
        message='Could not check your permissions (error id {errorId}). See the server log.',
    )
    payload['params']['feature'] = feature_id
    return StarletteHTTPException(status_code=500, detail=payload)


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
