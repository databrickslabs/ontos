"""Errors of compliance runs that the UI can translate.

A failed run stores its error text (``compliance_runs.error_message``). For the
errors the app writes itself it also stores a stable code and parameters
(``error_code``, ``error_params``), which the UI translates; the text stays the
English fallback, kept for the logs. Errors from the Databricks SDK or the
database have no code of ours: the API sends ``run_failed`` for them
(``public_run_error``), never the stored text, which can name objects or hosts.
"""
from typing import Any, Dict, Optional, Tuple

# The run error codes the UI translates (compliance:runErrors.<code>)
RUN_FAILED_CODE = 'run_failed'
RUN_ERROR_CODES = frozenset({
    'entities_load_failed', 'rule_parse_failed', RUN_FAILED_CODE, 'tags_load_failed',
    'user_token_required', 'workspace_client_unavailable',
})

# Prefix of the error parse_rule raises for a rule that doesn't parse
_RULE_PARSE_PREFIX = 'Failed to parse rule: '


class ComplianceRunError(RuntimeError):
    """An error of the app that fails a compliance run, with a stable code."""

    def __init__(self, message: str, code: str, **params: Any):
        super().__init__(message)
        self.error_code = code
        self.error_params = params


def run_error_code(error: BaseException) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """Code and parameters for the error that failed a run, or (None, None)."""
    code = getattr(error, 'error_code', None)
    if isinstance(code, str) and code:
        params = getattr(error, 'error_params', None)
        return code, dict(params) if isinstance(params, dict) else {}
    message = str(error)
    if isinstance(error, ValueError) and message.startswith(_RULE_PARSE_PREFIX):
        return 'rule_parse_failed', {'detail': message[len(_RULE_PARSE_PREFIX):]}
    return None, None


def public_run_error(
    status: Optional[str], error_code: Optional[str], error_params: Optional[Dict[str, Any]],
) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """The error code and parameters a failed run shows readers, or (None, None).

    One of ``RUN_ERROR_CODES``; any other stored code (an SDK's ``error_code``,
    say) or none at all is ``run_failed`` without parameters.
    """
    if status != 'failed':
        return None, None
    if error_code in RUN_ERROR_CODES:
        return error_code, error_params
    return RUN_FAILED_CODE, None
