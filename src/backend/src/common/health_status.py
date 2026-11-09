"""Startup problems reported by ``GET /api/health``, as codes the UI translates.

``GET /api/health`` and the maintenance responses are served to anyone who
reaches the app, before permissions can be checked, so they carry a code and a
generic English text for each problem, never the exception's text (which may
hold hosts, file paths or SQL). The exception goes to the server log.
"""

from typing import Any, Dict

HEALTH_MESSAGES: Dict[str, str] = {
    'workspace_client_unavailable': (
        'The Databricks workspace client could not be created. '
        'The cause is in the server logs.'
    ),
    'manager_init_failed': (
        'Some services could not be initialized. The cause is in the server logs.'
    ),
    'seeding_failed': (
        'Default roles, teams or projects could not be created. '
        'The cause is in the server logs.'
    ),
    'database_unavailable': (
        'The metadata database could not be initialized. '
        'The cause is in the server logs.'
    ),
}


def health_issue(code: str, **params: Any) -> Dict[str, Any]:
    """``{code, message, params}`` for a problem, ``message`` being the English fallback."""
    return {'code': code, 'message': HEALTH_MESSAGES[code], 'params': params}


def add_health_warning(health: Dict[str, Any], code: str, **params: Any) -> None:
    """Record a soft startup problem.

    ``warnings`` keeps the English text, ``warning_details`` the code.
    """
    issue = health_issue(code, **params)
    health.setdefault('warnings', []).append(issue['message'])
    health.setdefault('warning_details', []).append(issue)


def set_db_error(health: Dict[str, Any]) -> None:
    health['db_error'] = HEALTH_MESSAGES['database_unavailable']
    health['db_error_code'] = 'database_unavailable'


def set_seed_error(health: Dict[str, Any]) -> None:
    health['seed_error'] = HEALTH_MESSAGES['seeding_failed']
    health['seed_error_code'] = 'seeding_failed'
