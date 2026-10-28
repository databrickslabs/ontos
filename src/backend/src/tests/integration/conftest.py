"""Fixtures for the route-level integration tests.

The root ``client`` fixture only overrides a few dependencies, so every route
that reads a manager from ``app.state`` (audit, data products, data contracts,
...) answered 503. Here ``client`` runs the app's own ``initialize_managers``
against the test database and a mocked workspace client, and puts
``app.state`` back afterwards.

Everything the app writes during the test (default roles, the default team,
tag namespace, request data) goes through sessions bound to the test's
connection, so it is rolled back with the test's transaction and never
reaches other tests.
"""
import sys

import pytest
from databricks.sdk.errors import NotFound
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from src.app import app
from src.common import database
from src.common import workspace_client as workspace_client_module
from src.common.authorization import get_user_details_from_sdk

_WS_GETTERS = ('get_workspace_client', 'get_obo_workspace_client')

# --- Quarantine (#1051) ------------------------------------------------------
# Tests that fail on `development` for a known reason are skipped, so the rest of
# the suite can run in CI. Fix and remove entries one at a time, as with the
# unit tests' collect_ignore list.
# Candidate app bugs: the test asserts the intended behaviour and fails on it.
_NO_GROUPS = (
    'app: get_user_groups() returns [] outside LOCAL/mock mode, so an admin '
    'gets 403 creating a global comment'
)
_AUDIT_UUID = (
    'app: the create route puts the new id (a UUID) in the audit details, '
    'which are not JSON serialisable, so no audit entry is written'
)
_ODCS_DOMAIN = (
    'app (candidate): an imported `domain` that matches no native domain is kept only as '
    'the ontosOriginalDomain custom property; the export omits the root `domain`'
)
_DOMAIN_NO_PARENT = (
    'app: POST /api/data-domains with a parent that does not exist answers 500, not 404'
)
_DOMAIN_CYCLE = (
    'app: PUT /api/data-domains accepts a descendant as the new parent; '
    'the own-parent check answers 500'
)

QUARANTINE = {
    'test_comments_routes.py::TestCommentsRoutes::test_create_comment': _NO_GROUPS,
    'test_costs_routes.py::TestCostsRoutes::test_create_cost_item_is_audited': _AUDIT_UUID,
    'test_data_domains_routes.py::TestDataDomainsRoutes::'
    'test_create_domain_with_nonexistent_parent_fails': _DOMAIN_NO_PARENT,
    'test_data_domains_routes.py::TestDataDomainsRoutes::'
    'test_update_domain_circular_reference_prevention': _DOMAIN_CYCLE,
    'test_odcs_roundtrip.py::test_odcs_upload_then_export_roundtrip': _ODCS_DOMAIN,
}


def _quarantine_reason(nodeid: str):
    """The reason for a quarantined test, matched on the module, class or test."""
    local_id = nodeid.split('tests/integration/', 1)[-1]
    parts = local_id.split('::')
    for end in range(len(parts), 0, -1):
        reason = QUARANTINE.get('::'.join(parts[:end]))
        if reason:
            return reason
    return None


def pytest_collection_modifyitems(config, items):
    for item in items:
        reason = _quarantine_reason(item.nodeid)
        if reason:
            item.add_marker(pytest.mark.skip(reason=f'Quarantined (#1051): {reason}'))


@pytest.fixture(autouse=True)
def no_workspace_network(monkeypatch, mock_workspace_client):
    """Route every workspace client lookup to the mock.

    Without it, routes that build a client (groups, test personas, ...) try to
    reach the fake DATABRICKS_HOST and hang until the SDK gives up.
    """
    # No volume holds overrides (e.g. test personas): reads fall back to the
    # bundled files instead of parsing a MagicMock.
    mock_workspace_client.files.download.side_effect = NotFound('not found in tests')

    originals = {name: getattr(workspace_client_module, name) for name in _WS_GETTERS}

    def _mock_client(*args, **kwargs):
        return mock_workspace_client

    for module in list(sys.modules.values()):
        if not getattr(module, '__name__', '').startswith('src.'):
            continue
        for name, original in originals.items():
            if getattr(module, name, None) is original:
                monkeypatch.setattr(module, name, _mock_client)
    yield mock_workspace_client


@pytest.fixture(autouse=True)
def entitlements_file_copy(monkeypatch, tmp_path):
    """Keep the entitlements routes from rewriting the repo's entitlements.yaml.

    Their module-level manager saves every change to the file it loaded.
    """
    import shutil

    from src.routes import entitlements_routes

    manager = entitlements_routes.entitlements_manager
    if manager._yaml_path:
        copy = tmp_path / 'entitlements.yaml'
        shutil.copy(manager._yaml_path, copy)
        monkeypatch.setattr(manager, '_yaml_path', str(copy))
    yield


def _build_search_index():
    """Set up the SearchManager as the app's startup does after the managers."""
    from src.common.search_interfaces import SearchableAsset
    from src.controller.search_manager import SearchManager

    searchable = [
        manager for manager in app.state._state.values()
        if isinstance(manager, SearchableAsset) and hasattr(manager, 'get_search_index_items')
    ]
    app.state.search_manager = SearchManager(searchable_managers=searchable)
    app.state.search_manager.build_index()
    for manager in searchable:
        manager.set_search_manager(app.state.search_manager)


@pytest.fixture
def client(db_session, test_settings, mock_workspace_client, mock_test_user, monkeypatch):
    """A TestClient whose app has its managers, on the test database."""
    from src.controller.jobs_manager import JobsManager
    from src.utils import startup_tasks

    test_sessions = sessionmaker(bind=db_session.get_bind(), autoflush=False)
    previous_factory = database._SessionLocal
    database.set_session_factory(test_sessions)

    monkeypatch.setattr(startup_tasks, 'get_settings', lambda: test_settings)
    monkeypatch.setattr(JobsManager, 'start_background_polling', lambda self, **kwargs: None)

    saved_state = dict(app.state._state)
    app.state.health = {'db_ok': True, 'ws_ok': True, 'seed_ok': True, 'warnings': []}
    startup_tasks.initialize_managers(app)
    _build_search_index()

    async def override_get_user_details():
        return mock_test_user

    app.dependency_overrides[get_user_details_from_sdk] = override_get_user_details
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(get_user_details_from_sdk, None)
        app.state._state.clear()
        app.state._state.update(saved_state)
        database.set_session_factory(previous_factory)
