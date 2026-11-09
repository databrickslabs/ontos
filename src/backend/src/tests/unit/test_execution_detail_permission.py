"""An execution's details are gated like the executions list.

``GET /api/workflows/executions/{id}`` returns the trigger context and the
steps' raw errors (e.g. SQL error text). It checked ``process-workflows``
read access, which every default role has, while the list it is opened from
checks ``settings-workflows``.
"""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

from src.common.authorization import PermissionChecker
from src.routes.workflows_routes import router


def _permission(path, method='GET'):
    route = next(
        r for r in router.routes
        if r.path.endswith(path) and method in r.methods
    )
    checkers = [
        d.call for d in route.dependant.dependencies if isinstance(d.call, PermissionChecker)
    ]
    assert len(checkers) == 1
    return checkers[0].feature_id, checkers[0].required_level


def test_the_details_need_the_same_access_as_the_list():
    assert _permission('/executions/{execution_id}') == _permission('/executions')
    assert _permission('/executions/{execution_id}')[0] == 'settings-workflows'
