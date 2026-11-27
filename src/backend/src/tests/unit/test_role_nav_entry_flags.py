"""Marketplace and My Products have their own "show in navigation" flag (#1325).

They aren't features: the flag is stored in ``hidden_nav_features`` next to the feature ids,
and the Products level decides whether the entry can show at all.
"""
import uuid
from unittest.mock import MagicMock, Mock

import pytest

from src.common.config import Settings
from src.common.features import (
    APP_FEATURES, FeatureAccessLevel as L, NAV_ENTRY_FEATURES, NAV_MENU_ENTRIES,
)
from src.controller.authorization_manager import AuthorizationManager
from src.controller.settings_manager import RoleNavFeatureUnknownError, SettingsManager
from src.models.settings import AppRole, AppRoleCreate


@pytest.fixture
def settings_manager(db_session):
    settings = MagicMock(spec=Settings)
    settings.to_dict.return_value = {}
    return SettingsManager(db=db_session, settings=settings, workspace_client=MagicMock())


def _role(name, groups, perms, hidden=(), is_admin=False):
    return AppRole(
        id=uuid.uuid4(), name=name, assigned_groups=list(groups),
        feature_permissions=perms, hidden_nav_features=list(hidden), is_admin=is_admin,
    )


def _auth(*roles):
    manager = Mock()
    manager.list_app_roles.return_value = list(roles)
    return AuthorizationManager(settings_manager=manager)


def test_menu_entries_depend_on_known_features():
    assert set(NAV_ENTRY_FEATURES) == {'marketplace', 'my-products'}
    assert set(NAV_ENTRY_FEATURES.values()) <= set(APP_FEATURES)
    assert set(NAV_MENU_ENTRIES.values()) <= set(APP_FEATURES)
    # Every entry is either a feature or an entry with its own flag.
    assert all(e in APP_FEATURES or e in NAV_ENTRY_FEATURES for e in NAV_MENU_ENTRIES)
    assert NAV_MENU_ENTRIES['marketplace'] == 'data-products'


def test_role_stores_menu_entry_flags(settings_manager):
    created = settings_manager.create_app_role(AppRoleCreate(
        name=f'Entries {uuid.uuid4().hex[:6]}',
        feature_permissions={'data-products': L.READ_ONLY},
        hidden_nav_features=['marketplace', 'my-products', 'data-products'],
    ))

    assert created.hidden_nav_features == ['marketplace', 'my-products', 'data-products']
    fetched = settings_manager.get_app_role(str(created.id))
    assert fetched.hidden_nav_features == ['marketplace', 'my-products', 'data-products']


def test_unknown_entry_is_still_refused(settings_manager):
    with pytest.raises(RoleNavFeatureUnknownError) as exc_info:
        settings_manager.create_app_role(AppRoleCreate(
            name=f'Bad {uuid.uuid4().hex[:6]}', hidden_nav_features=['marketplace', 'my-requests'],
        ))
    assert exc_info.value.params['feature_ids'] == ['my-requests']


def test_marketplace_hides_without_hiding_products():
    consumer = _role(
        'Consumer', ['c'], {'data-products': L.READ_ONLY}, hidden=['marketplace'],
    )

    hidden = _auth(consumer).get_user_hidden_nav_features(['c'])

    assert hidden == ['marketplace']


def test_products_hide_without_hiding_marketplace_and_my_products():
    consumer = _role('Consumer', ['c'], {'data-products': L.READ_ONLY}, hidden=['data-products'])

    assert _auth(consumer).get_user_hidden_nav_features(['c']) == ['data-products']


def test_entry_is_hidden_only_when_every_role_granting_products_hides_it():
    hides = _role('Hides', ['a'], {'data-products': L.READ_ONLY}, hidden=['marketplace'])
    shows = _role('Shows', ['b'], {'data-products': L.READ_WRITE})
    no_access = _role('No access', ['c'], {'data-products': L.NONE})

    assert _auth(hides, shows).get_user_hidden_nav_features(['a', 'b']) == []
    # A role without Products access doesn't count as showing the entry.
    assert _auth(hides, no_access).get_user_hidden_nav_features(['a', 'c']) == ['marketplace']


def test_entry_without_products_access_is_not_listed():
    hides = _role('Hides', ['a'], {'data-products': L.NONE}, hidden=['marketplace'])

    assert _auth(hides).get_user_hidden_nav_features(['a']) == []


def test_admin_role_hides_no_entry():
    admin = _role('Admin', ['x'], {'data-products': L.ADMIN}, hidden=['marketplace'], is_admin=True)

    assert _auth(admin).get_user_hidden_nav_features(['x']) == []
