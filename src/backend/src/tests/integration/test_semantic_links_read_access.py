"""The three semantic-link reads need Read-only on ``semantic-models``.

GET /api/semantic-links/entity/..., /entity-prefix/... and /by-iri had no
PermissionChecker; they now use the level of the other semantic-links routes
(``mapping-status`` reads, writes need Read/Write on the same feature).
"""
import pytest

from src.app import app
from src.common.features import FeatureAccessLevel
from src.models.settings import AppRoleCreate

NO_CONCEPTS = 'Links without semantic-models'
READER = 'Links semantic-models reader'

READS = [
    '/api/semantic-links/entity/data_product/p1',
    '/api/semantic-links/entity-prefix/data_contract_property/c1%23s%23',
    '/api/semantic-links/by-iri?iri=http%3A%2F%2Fexample.com%2Fonto%23Customer',
]


@pytest.fixture
def act_as(client, mock_test_user):
    settings_manager = app.state.settings_manager

    def _act_as(name, levels):
        role = settings_manager.get_app_role_by_name(name) or settings_manager.create_app_role(
            AppRoleCreate(name=name, feature_permissions=levels))
        settings_manager.set_applied_role_override_for_user(
            mock_test_user.email, str(role.id), caller_is_admin=True)

    yield _act_as
    settings_manager.set_applied_role_override_for_user(mock_test_user.email, None)


@pytest.mark.parametrize('url', READS)
def test_without_semantic_models_the_read_is_403(client, act_as, url):
    act_as(NO_CONCEPTS, {'data-products': FeatureAccessLevel.ADMIN})
    response = client.get(url)
    assert response.status_code == 403, response.text


@pytest.mark.parametrize('url', READS)
def test_with_read_only_on_semantic_models_the_read_is_allowed(client, act_as, url):
    act_as(READER, {'semantic-models': FeatureAccessLevel.READ_ONLY})
    response = client.get(url)
    assert response.status_code == 200, response.text
    assert response.json() == []
