"""Navigation presets through the API (#1325): preview, apply, undo and the admin gate."""
import pytest
from fastapi.testclient import TestClient

from src.app import app
from src.common.authorization import get_user_details_from_sdk
from src.models.users import UserInfo

BASE = '/api/settings/navigation-presets'


@pytest.fixture(autouse=True)
def _recording_audit_manager(client: TestClient):
    """The preset routes log every apply and undo; keep the calls to check them.

    Depends on ``client`` so that it replaces the audit manager the app set up at startup."""
    class _Audit:
        def __init__(self):
            self.calls = []

        def log_action(self, **kwargs):
            return None

        def log_action_background(self, **kwargs):
            self.calls.append(kwargs)

    audit = _Audit()
    previous = getattr(app.state, 'audit_manager', None)
    app.state.audit_manager = audit
    yield audit
    if previous is not None:
        app.state.audit_manager = previous
    elif hasattr(app.state, 'audit_manager'):
        delattr(app.state, 'audit_manager')


@pytest.fixture
def as_user(client: TestClient):
    previous = app.dependency_overrides.get(get_user_details_from_sdk)

    def _switch(groups):
        async def _override():
            return UserInfo(
                username='nav_user', email='nav_user@example.com', user='nav_user',
                ip='127.0.0.1', groups=list(groups),
            )
        app.dependency_overrides[get_user_details_from_sdk] = _override
        return client

    yield _switch
    if previous is not None:
        app.dependency_overrides[get_user_details_from_sdk] = previous
    else:
        app.dependency_overrides.pop(get_user_details_from_sdk, None)


def _roles(client: TestClient):
    return {r['name']: r for r in client.get('/api/settings/roles').json()}


def _permissions(client: TestClient):
    return {name: role['feature_permissions'] for name, role in _roles(client).items()}


class TestPreview:
    def test_lists_both_presets_with_per_role_previews(self, client: TestClient):
        response = client.get(BASE)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body['last_applied'] is None
        presets = {p['id']: {r['role_name']: r for r in p['roles']} for p in body['presets']}
        assert set(presets) == {'essentials', 'data-consumer'}
        consumer = presets['essentials']['Data Consumer']
        assert consumer['found'] and consumer['changed']
        assert consumer['shown'] == ['data-catalog', 'assets', 'semantic-models']
        # The default consumer has no access to assets or concepts.
        assert consumer['no_access'] == ['assets', 'semantic-models']
        assert 'data-products' in consumer['hidden'] and 'assets' not in consumer['hidden']
        assert consumer['home_sections'] == ['JOURNEY']
        assert presets['data-consumer']['Data Consumer']['home_sections'] == ['MARKETPLACE']

    def test_preview_changes_nothing(self, client: TestClient):
        before = _roles(client)

        client.get(BASE)

        assert _roles(client) == before


class TestApplyAndUndo:
    def test_essentials_changes_menus_and_home_but_never_permissions(self, client: TestClient):
        before_permissions = _permissions(client)
        before = _roles(client)

        response = client.post(f'{BASE}/essentials/apply')

        assert response.status_code == 200, response.text
        body = response.json()
        assert body['preset_id'] == 'essentials'
        assert {r['role_name'] for r in body['changed_roles']} == {
            'Data Consumer', 'Data Steward', 'Data Governance Officer',
        }
        assert body['missing_roles'] == []
        assert _permissions(client) == before_permissions
        after = _roles(client)
        assert after['Data Consumer']['home_sections'] == ['JOURNEY']
        assert after['Data Consumer']['hidden_nav_features'] == [
            'marketplace', 'data-contracts', 'data-products', 'my-products',
            'catalog-commander',
        ]
        steward = after['Data Steward']['hidden_nav_features']
        assert 'data-asset-reviews' not in steward and 'compliance' in steward
        officer = after['Data Governance Officer']['hidden_nav_features']
        assert 'compliance' not in officer and 'master-data' in officer
        # Roles the preset doesn't name stay as they were.
        for name in ('Admin', 'Data Producer', 'Security Officer'):
            assert after[name]['hidden_nav_features'] == before[name]['hidden_nav_features']
            assert after[name]['home_sections'] == before[name]['home_sections']

    def test_reapply_changes_nothing(self, client: TestClient):
        client.post(f'{BASE}/essentials/apply')
        snapshot = client.get(BASE).json()['last_applied']

        again = client.post(f'{BASE}/essentials/apply')

        assert again.status_code == 200
        assert again.json()['changed_roles'] == []
        assert sorted(again.json()['unchanged_roles']) == [
            'Data Consumer', 'Data Governance Officer', 'Data Steward',
        ]
        assert client.get(BASE).json()['last_applied'] == snapshot
        preview = client.get(BASE).json()['presets']
        assert not any(r['changed'] for p in preview if p['id'] == 'essentials' for r in p['roles'])

    def test_undo_restores_the_state_before_the_preset(self, client: TestClient):
        before = _roles(client)
        client.post(f'{BASE}/essentials/apply')
        last = client.get(BASE).json()['last_applied']
        assert last['preset_id'] == 'essentials' and last['applied_by']
        assert {r['role_name'] for r in last['roles']} == {
            'Data Consumer', 'Data Steward', 'Data Governance Officer',
        }

        response = client.post(f'{BASE}/undo')

        assert response.status_code == 200, response.text
        assert response.json()['preset_id'] == 'essentials'
        assert response.json()['missing_roles'] == []
        after = _roles(client)
        for name, role in before.items():
            assert after[name]['hidden_nav_features'] == role['hidden_nav_features'], name
            assert after[name]['home_sections'] == role['home_sections'], name
        assert client.get(BASE).json()['last_applied'] is None

    def test_undo_again_is_a_coded_conflict(self, client: TestClient):
        client.post(f'{BASE}/essentials/apply')
        client.post(f'{BASE}/undo')

        response = client.post(f'{BASE}/undo')

        assert response.status_code == 409
        detail = response.json()['detail']
        assert detail['code'] == 'navigation_preset_nothing_to_undo'

    def test_unknown_preset_is_a_coded_404(self, client: TestClient):
        response = client.post(f'{BASE}/no-such-preset/apply')

        assert response.status_code == 404
        detail = response.json()['detail']
        assert detail['code'] == 'navigation_preset_unknown'
        assert detail['params'] == {'preset_id': 'no-such-preset'}

    def test_apply_and_undo_are_audited(self, client: TestClient, _recording_audit_manager):
        client.post(f'{BASE}/essentials/apply')
        client.post(f'{BASE}/undo')
        client.post(f'{BASE}/undo')
        client.post(f'{BASE}/no-such-preset/apply')

        calls = _recording_audit_manager.calls
        assert [(c['action'], c['success']) for c in calls] == [
            ('APPLY_NAVIGATION_PRESET', True),
            ('UNDO_NAVIGATION_PRESET', True),
            ('UNDO_NAVIGATION_PRESET', False),
            ('APPLY_NAVIGATION_PRESET', False),
        ]
        assert all(c['feature'] == 'settings' for c in calls)
        assert calls[0]['details']['preset_id'] == 'essentials'
        assert len(calls[0]['details']['changed_role_ids']) == 3
        assert len(calls[1]['details']['restored_role_ids']) == 3
        assert 'exception' in calls[2]['details'] and 'exception' in calls[3]['details']


class TestDataConsumerPreset:
    def test_consumer_keeps_marketplace_and_my_products_and_loses_products(
        self, client: TestClient, as_user,
    ):
        response = client.post(f'{BASE}/data-consumer/apply')
        assert response.status_code == 200, response.text
        assert [r['role_name'] for r in response.json()['changed_roles']] == ['Data Consumer']

        navigation = as_user(['data-consumers']).get('/api/user/navigation')

        assert navigation.status_code == 200
        hidden = navigation.json()['hidden_features']
        assert 'data-products' in hidden and 'data-contracts' in hidden
        assert 'marketplace' not in hidden and 'my-products' not in hidden
        # Access is unchanged: the consumer still reads Products.
        permissions = as_user(['data-consumers']).get('/api/user/permissions').json()
        assert permissions['data-products'] == 'Read-only'

    def test_consumer_home_is_the_marketplace(self, client: TestClient):
        client.post(f'{BASE}/data-consumer/apply')

        assert _roles(client)['Data Consumer']['home_sections'] == ['MARKETPLACE']


class TestAdminGate:
    @pytest.mark.parametrize('method,path', [
        ('get', BASE),
        ('post', f'{BASE}/essentials/apply'),
        ('post', f'{BASE}/undo'),
    ])
    def test_non_admin_is_refused(self, client: TestClient, as_user, method, path):
        before = _roles(client)

        # A data consumer has no access to the roles settings.
        response = getattr(as_user(['data-consumers']), method)(path)

        assert response.status_code == 403
        assert _roles(as_user(['test_admins'])) == before
