"""Errors of compliance runs that the UI can translate.

A failed run stores its error text (``compliance_runs.error_message``). For the
errors the app writes itself it also stores a stable code and parameters
(``error_code``, ``error_params``), which the UI translates; the text stays the
English fallback. Errors from the Databricks SDK or the database have no code
and are shown as they are.
"""
from typing import Any, Dict, Optional, Tuple

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
