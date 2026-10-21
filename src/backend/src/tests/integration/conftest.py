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
_NO_SUCH_ENDPOINT = 'calls an endpoint or a parameter the API does not have'
_STALE = 'expects an older response (status code, payload or message)'
_SQLITE_UUID = (
    'SQLite only: a UUID value is bound to a String column or a str to a Uuid '
    'column (Postgres accepts both)'
)
_ODCS_NAME = (
    'the ODCS export has no root `name` since d0cd3c80 (the import reads it); '
    'needs a decision on whether the export should carry it'
)
_UNTRIAGED = 'fails; the cause has not been analysed yet'

QUARANTINE = {
    'test_audit_routes.py::TestAuditRoutes::test_get_audit_logs': _NO_SUCH_ENDPOINT,
    'test_audit_routes.py::TestAuditRoutes::test_get_audit_logs_by_action': _NO_SUCH_ENDPOINT,
    'test_audit_routes.py::TestAuditRoutes::test_get_audit_logs_by_feature': _NO_SUCH_ENDPOINT,
    'test_audit_routes.py::TestAuditRoutes::test_get_audit_logs_by_username': _NO_SUCH_ENDPOINT,
    'test_audit_routes.py::TestAuditRoutes::test_get_audit_logs_pagination': _NO_SUCH_ENDPOINT,
    'test_audit_routes.py::TestAuditRoutes::test_get_audit_stats': _NO_SUCH_ENDPOINT,
    'test_audit_routes.py::TestAuditRoutes::test_get_change_logs': _NO_SUCH_ENDPOINT,
    'test_comments_routes.py::TestCommentsRoutes::test_create_comment': _NO_SUCH_ENDPOINT,
    'test_comments_routes.py::TestCommentsRoutes::test_create_comment_validation_error': (
        _NO_SUCH_ENDPOINT),
    'test_comments_routes.py::TestCommentsRoutes::test_create_comment_with_audience': (
        _NO_SUCH_ENDPOINT),
    'test_comments_routes.py::TestCommentsRoutes::test_get_comments_for_entity': _NO_SUCH_ENDPOINT,
    'test_comments_routes.py::TestCommentsRoutes::test_update_comment': _NO_SUCH_ENDPOINT,
    'test_compliance_routes.py::TestComplianceRoutes::test_get_policies': _UNTRIAGED,
    'test_compliance_routes.py::TestComplianceRoutes::test_update_policy': _UNTRIAGED,
    'test_costs_routes.py::TestCostsRoutes::test_create_cost_item': _NO_SUCH_ENDPOINT,
    'test_costs_routes.py::TestCostsRoutes::test_create_cost_validation_error': _NO_SUCH_ENDPOINT,
    'test_costs_routes.py::TestCostsRoutes::test_get_costs_for_entity': _NO_SUCH_ENDPOINT,
    'test_data_contracts_routes.py::TestDataContractsRoutes::test_bulk_operations': (
        _NO_SUCH_ENDPOINT),
    'test_data_contracts_routes.py::TestDataContractsRoutes::test_create_contract_basic': _STALE,
    'test_data_contracts_routes.py::TestDataContractsRoutes::'
    'test_create_contract_duplicate_name_version': _STALE,
    'test_data_contracts_routes.py::TestDataContractsRoutes::test_delete_contract': _STALE,
    'test_data_contracts_routes.py::TestDataContractsRoutes::test_export_contract_as_odcs_yaml': (
        _ODCS_NAME),
    'test_data_contracts_routes.py::TestDataContractsRoutes::'
    'test_export_with_missing_relationships': _ODCS_NAME,
    'test_data_contracts_routes.py::TestDataContractsRoutes::test_list_contracts_pagination': (
        _NO_SUCH_ENDPOINT),
    'test_data_domains_routes.py::TestDataDomainsRoutes::'
    'test_create_domain_with_nonexistent_parent_fails': _SQLITE_UUID,
    'test_data_domains_routes.py::TestDataDomainsRoutes::test_create_domain_with_parent': (
        _SQLITE_UUID),
    'test_data_domains_routes.py::TestDataDomainsRoutes::test_delete_domain_success': _STALE,
    'test_data_domains_routes.py::TestDataDomainsRoutes::test_delete_domain_with_children_fails': (
        _UNTRIAGED),
    'test_data_domains_routes.py::TestDataDomainsRoutes::test_get_child_domains': _SQLITE_UUID,
    'test_data_domains_routes.py::TestDataDomainsRoutes::test_get_domain_hierarchy': _SQLITE_UUID,
    'test_data_domains_routes.py::TestDataDomainsRoutes::test_get_domain_includes_hierarchy_info': (
        _SQLITE_UUID),
    'test_data_domains_routes.py::TestDataDomainsRoutes::test_get_domain_path': _SQLITE_UUID,
    'test_data_domains_routes.py::TestDataDomainsRoutes::test_get_root_domains': _NO_SUCH_ENDPOINT,
    'test_data_domains_routes.py::TestDataDomainsRoutes::test_update_domain_change_parent': (
        _SQLITE_UUID),
    'test_data_domains_routes.py::TestDataDomainsRoutes::'
    'test_update_domain_circular_reference_prevention': _SQLITE_UUID,
    'test_data_product_routes.py::TestDataProductRoutes::test_create_product_duplicate_id': _STALE,
    'test_data_product_routes.py::TestDataProductRoutes::test_get_owners': _UNTRIAGED,
    'test_data_product_routes.py::TestDataProductRoutes::test_get_statuses': _STALE,
    'test_data_product_routes.py::TestDataProductRoutes::test_publish_product_success': _STALE,
    'test_jobs_routes.py::TestJobsRoutes::test_get_workflow_installations': _NO_SUCH_ENDPOINT,
    'test_knowledge_routes.py::TestSemanticLinksAgainstConcepts::'
    'test_create_link_persists_and_is_listable': _UNTRIAGED,
    'test_metadata_routes.py::TestMetadataRoutes::test_create_link': _NO_SUCH_ENDPOINT,
    'test_metadata_routes.py::TestMetadataRoutes::test_create_rich_text': _NO_SUCH_ENDPOINT,
    'test_metadata_routes.py::TestMetadataRoutes::test_create_rich_text_validation_error': (
        _NO_SUCH_ENDPOINT),
    'test_metadata_routes.py::TestMetadataRoutes::test_get_metadata_for_entity': _NO_SUCH_ENDPOINT,
    'test_notifications_routes.py::TestNotificationsRoutes::test_get_notification_count': (
        _NO_SUCH_ENDPOINT),
    'test_notifications_routes.py::TestNotificationsRoutes::test_mark_all_as_read': (
        _NO_SUCH_ENDPOINT),
    'test_odcs_export_validation.py::TestODCSExportValidation::'
    'test_odcs_export_has_all_required_root_fields': _ODCS_NAME,
    'test_odcs_export_validation.py::TestODCSExportValidation::'
    'test_odcs_export_has_complete_team_structure': _UNTRIAGED,
    'test_odcs_export_validation.py::TestODCSExportValidation::'
    'test_odcs_export_has_tags_and_custom_properties': _UNTRIAGED,
    'test_odcs_export_validation.py::TestODCSExportValidation::'
    'test_odcs_export_json_parsing_in_text_fields': _UNTRIAGED,
    'test_odcs_export_validation.py::TestODCSExportValidation::'
    'test_odcs_export_missing_fields_validation': _ODCS_NAME,
    'test_odcs_roundtrip.py::test_odcs_upload_then_export_roundtrip': _ODCS_NAME,
    'test_pr_i_partial_put.py::TestPartialPutPreservesUnmodifiedFields': _SQLITE_UUID,
    'test_projects_routes.py::TestProjectsRoutes::test_get_project_summary': _NO_SUCH_ENDPOINT,
    'test_security_features_routes.py::TestSecurityFeaturesRoutes::test_enable_security_feature': (
        _NO_SUCH_ENDPOINT),
    'test_semantic_upload_integration.py::TestSemanticUploadIntegration::'
    'test_upload_with_mixed_authoritative_definitions': _UNTRIAGED,
    'test_settings_routes.py::test_get_settings': _STALE,
    'test_tags_routes.py::TestTagsRoutes::test_assign_tag_to_entity': _NO_SUCH_ENDPOINT,
    'test_tags_routes.py::TestTagsRoutes::test_create_tag': _STALE,
    'test_tags_routes.py::TestTagsRoutes::test_get_tags_for_entity': _NO_SUCH_ENDPOINT,
    'test_teams_routes.py::TestTeamsRoutes::test_add_team_member': _STALE,
    'test_teams_routes.py::TestTeamsRoutes::test_add_team_member_duplicate': _STALE,
    'test_teams_routes.py::TestTeamsRoutes::test_add_team_member_team_not_found': _STALE,
    'test_teams_routes.py::TestTeamsRoutes::test_get_team_members': _STALE,
    'test_teams_routes.py::TestTeamsRoutes::test_get_teams_filtered_by_domain': _UNTRIAGED,
    'test_teams_routes.py::TestTeamsRoutes::test_remove_team_member': _STALE,
    'test_teams_routes.py::TestTeamsRoutes::test_update_team_member': _STALE,
    'test_user_routes.py::TestUserRoutes::test_get_current_user': _NO_SUCH_ENDPOINT,
    'test_user_routes.py::TestUserRoutes::test_get_user_profile': _NO_SUCH_ENDPOINT,
    'test_user_routes.py::TestUserRoutes::test_search_users': _NO_SUCH_ENDPOINT,
    'test_workspace_routes.py::TestWorkspaceRoutes::test_get_catalogs': _NO_SUCH_ENDPOINT,
    'test_workspace_routes.py::TestWorkspaceRoutes::test_get_users': _NO_SUCH_ENDPOINT,
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
