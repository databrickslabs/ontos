"""Per-role "show in navigation" flag through the API (#1325, slice 1).

Roles API: ``hidden_nav_features`` round-trips and unknown ids get a coded 400.
``GET /api/user/navigation``: the viewer's hidden list follows the permissions'
role resolution (groups, role switcher, admin).
"""
import json
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from src.app import app
from src.common.authorization import get_user_details_from_sdk
from src.db_models.settings import AppRoleDb
from src.models.users import UserInfo


@pytest.fixture(autouse=True)
def _noop_audit_manager():
    """The role and role-override routes log actions; these tests don't need the trail."""
    class _NoopAudit:
        def log_action(self, **kwargs):
            return None

        def log_action_background(self, **kwargs):
            return None

    previous = getattr(app.state, 'audit_manager', None)
    app.state.audit_manager = _NoopAudit()
    yield
    if previous is not None:
        app.state.audit_manager = previous
    elif hasattr(app.state, 'audit_manager'):
        delattr(app.state, 'audit_manager')


def _add_role(db_session: Session, groups, perms, hidden=(), is_admin=False) -> AppRoleDb:
    role = AppRoleDb(
        id=str(uuid.uuid4()),
        name=f'Nav test {uuid.uuid4().hex[:8]}',
        feature_permissions=json.dumps(perms),
        assigned_groups=json.dumps(list(groups)),
        home_sections='[]',
        approval_privileges='{}',
        hidden_nav_features=json.dumps(list(hidden)),
        is_admin=is_admin,
    )
    db_session.add(role)
    db_session.commit()
    return role


@pytest.fixture
def as_user(client: TestClient):
    """Switch the request user to one with the given groups."""
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


def _role_payload(**overrides):
    payload = {
        'name': f'Nav API {uuid.uuid4().hex[:8]}',
        'feature_permissions': {'data-contracts': 'Read-only', 'assets': 'Read/Write'},
        'assigned_groups': ['nav-api'],
    }
    payload.update(overrides)
    return payload


class TestRolesApi:
    def test_hidden_features_round_trip(self, client: TestClient):
        created = client.post('/api/settings/roles', json=_role_payload(
            hidden_nav_features=['data-contracts', 'assets'],
        ))
        assert created.status_code == 201, created.text
        role = created.json()
        assert role['hidden_nav_features'] == ['data-contracts', 'assets']

        fetched = client.get(f"/api/settings/roles/{role['id']}").json()
        assert fetched['hidden_nav_features'] == ['data-contracts', 'assets']

        role['hidden_nav_features'] = ['assets']
        updated = client.put(f"/api/settings/roles/{role['id']}", json=role)
        assert updated.status_code == 200, updated.text
        assert updated.json()['hidden_nav_features'] == ['assets']

        listed = {r['id']: r for r in client.get('/api/settings/roles').json()}
        assert listed[role['id']]['hidden_nav_features'] == ['assets']

    def test_role_created_without_the_field_shows_everything(self, client: TestClient):
        created = client.post('/api/settings/roles', json=_role_payload())
        assert created.status_code == 201, created.text
        assert created.json()['hidden_nav_features'] == []

    def test_default_roles_hide_nothing(self, client: TestClient):
        roles = client.get('/api/settings/roles').json()
        defaults = {'Admin', 'Data Consumer', 'Data Producer', 'Data Steward'}
        assert defaults <= {r['name'] for r in roles}
        assert all(r['hidden_nav_features'] == [] for r in roles)

    def test_unknown_ids_are_refused_with_a_code_on_create(self, client: TestClient):
        response = client.post('/api/settings/roles', json=_role_payload(
            hidden_nav_features=['assets', 'search', 'no-such-feature'],
        ))
        assert response.status_code == 400
        detail = response.json()['detail']
        assert detail['code'] == 'role_nav_feature_unknown'
        assert detail['params'] == {'feature_ids': ['search', 'no-such-feature']}

    def test_unknown_ids_are_refused_with_a_code_on_update(self, client: TestClient):
        role = client.post('/api/settings/roles', json=_role_payload()).json()
        role['hidden_nav_features'] = ['my-requests']

        response = client.put(f"/api/settings/roles/{role['id']}", json=role)
        assert response.status_code == 400
        detail = response.json()['detail']
        assert detail['code'] == 'role_nav_feature_unknown'
        assert detail['params'] == {'feature_ids': ['my-requests']}


class TestJourneyHomeSection:
    """The journey home (#1347) is a role home section: the roles API carries it."""

    def test_journey_home_section_round_trips(self, client: TestClient):
        created = client.post('/api/settings/roles', json=_role_payload(
            home_sections=['JOURNEY'],
        ))
        assert created.status_code == 201, created.text
        role = created.json()
        assert role['home_sections'] == ['JOURNEY']

        role['home_sections'] = ['JOURNEY', 'DISCOVERY']
        updated = client.put(f"/api/settings/roles/{role['id']}", json=role)
        assert updated.status_code == 200, updated.text
        assert updated.json()['home_sections'] == ['JOURNEY', 'DISCOVERY']


class TestUserNavigation:
    def test_admin_sees_everything(self, client: TestClient, db_session: Session):
        # The default test user is in test_admins, the seeded is_admin role's group.
        _add_role(db_session, ['test_admins'], {'assets': 'Read-only'}, hidden=['assets'])

        response = client.get('/api/user/navigation')
        assert response.status_code == 200
        assert response.json() == {'hidden_features': []}

    def test_role_switcher_applies_the_switched_role(
        self, client: TestClient, db_session: Session,
    ):
        consumer = _add_role(
            db_session, ['consumers'],
            {'data-contracts': 'Read-only', 'assets': 'Read/Write', 'data-catalog': 'Read-only'},
            hidden=['data-contracts', 'assets'],
        )

        switched = client.post('/api/user/role-override', json={'role_id': consumer.id})
        assert switched.status_code == 200, switched.text
        assert client.get('/api/user/navigation').json() == {
            'hidden_features': ['data-contracts', 'assets'],
        }
        # Access is unchanged: the hidden features keep their levels.
        permissions = client.get('/api/user/permissions').json()
        assert permissions['data-contracts'] == 'Read-only'
        assert permissions['assets'] == 'Read/Write'

        client.post('/api/user/role-override', json={'role_id': None})
        assert client.get('/api/user/navigation').json() == {'hidden_features': []}

    def test_multi_role_shows_a_feature_any_granting_role_shows(
        self, as_user, db_session: Session,
    ):
        _add_role(
            db_session, ['nav-a'], {'data-contracts': 'Read-only', 'assets': 'Read-only'},
            hidden=['data-contracts', 'assets'],
        )
        _add_role(db_session, ['nav-b'], {'data-contracts': 'Read/Write', 'assets': 'None'})

        response = as_user(['nav-a', 'nav-b']).get('/api/user/navigation')
        assert response.status_code == 200
        # nav-b grants and shows contracts; it has no access to assets, so it can't unhide them.
        assert response.json() == {'hidden_features': ['assets']}

    def test_user_without_roles_hides_nothing(self, as_user):
        response = as_user(['nobody-group']).get('/api/user/navigation')
        assert response.status_code == 200
        assert response.json() == {'hidden_features': []}
