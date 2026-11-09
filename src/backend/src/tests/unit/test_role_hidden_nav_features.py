"""Per-role "show in navigation" flag (#1325, slice 1).

The role stores the feature ids it hides from the menus (``hidden_nav_features``),
and the viewer's hidden list follows the same role resolution as the permissions.
"""
import importlib.util
import json
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from src.common.config import Settings
from src.common.features import FeatureAccessLevel as L
from src.controller.authorization_manager import AuthorizationManager
from src.controller.settings_manager import RoleNavFeatureUnknownError, SettingsManager
from src.db_models.settings import AppRoleDb
from src.file_models.roles import RoleFileModel
from src.models.settings import AppRole, AppRoleCreate, AppRoleUpdate


# --- Role storage (SettingsManager) ---------------------------------------------------

@pytest.fixture
def settings_manager(db_session):
    settings = MagicMock(spec=Settings)
    settings.to_dict.return_value = {}
    return SettingsManager(db=db_session, settings=settings, workspace_client=MagicMock())


def _create(manager, name='Nav Role', **kwargs):
    return manager.create_app_role(AppRoleCreate(
        name=f'{name} {uuid.uuid4().hex[:6]}',
        feature_permissions={'data-contracts': L.READ_ONLY, 'assets': L.READ_WRITE},
        **kwargs,
    ))


def test_hidden_nav_features_round_trip_on_create_and_get(settings_manager):
    created = _create(settings_manager, hidden_nav_features=['data-contracts', 'assets'])

    assert created.hidden_nav_features == ['data-contracts', 'assets']
    fetched = settings_manager.get_app_role(str(created.id))
    assert fetched.hidden_nav_features == ['data-contracts', 'assets']


def test_hidden_nav_features_default_to_empty(settings_manager):
    created = _create(settings_manager)

    assert created.hidden_nav_features == []
    row = settings_manager._db.get(AppRoleDb, str(created.id))
    assert json.loads(row.hidden_nav_features) == []


def test_update_replaces_and_partial_update_keeps_hidden_list(settings_manager):
    created = _create(settings_manager, hidden_nav_features=['data-contracts'])

    updated = settings_manager.update_app_role(
        str(created.id), AppRoleUpdate(hidden_nav_features=['assets']),
    )
    assert updated.hidden_nav_features == ['assets']

    # A partial update without the field leaves it unchanged.
    renamed = settings_manager.update_app_role(
        str(created.id), AppRoleUpdate(description='new text'),
    )
    assert renamed.hidden_nav_features == ['assets']

    cleared = settings_manager.update_app_role(
        str(created.id), AppRoleUpdate(hidden_nav_features=[]),
    )
    assert cleared.hidden_nav_features == []


def test_duplicate_ids_are_stored_once():
    role = AppRoleCreate(name='x', hidden_nav_features=['assets', ' assets', 'assets '])
    assert role.hidden_nav_features == ['assets']


@pytest.mark.parametrize('bad_id', ['not-a-feature', 'search', 'my-requests'])
def test_unknown_feature_ids_are_refused_with_a_code_on_create(settings_manager, bad_id):
    with pytest.raises(RoleNavFeatureUnknownError) as exc_info:
        _create(settings_manager, hidden_nav_features=['assets', bad_id])

    assert exc_info.value.code == 'role_nav_feature_unknown'
    assert exc_info.value.params == {'feature_ids': [bad_id]}


def test_unknown_feature_ids_are_refused_on_update(settings_manager):
    created = _create(settings_manager, hidden_nav_features=['assets'])

    with pytest.raises(RoleNavFeatureUnknownError) as exc_info:
        settings_manager.update_app_role(
            str(created.id), AppRoleUpdate(hidden_nav_features=['nope']),
        )
    assert exc_info.value.params == {'feature_ids': ['nope']}
    assert settings_manager.get_app_role(str(created.id)).hidden_nav_features == ['assets']


def test_ids_of_removed_features_are_not_returned(settings_manager):
    created = _create(settings_manager)
    row = settings_manager._db.get(AppRoleDb, str(created.id))
    row.hidden_nav_features = json.dumps(['assets', 'feature-removed-later'])
    settings_manager._db.commit()

    assert settings_manager.get_app_role(str(created.id)).hidden_nav_features == ['assets']


def test_unparseable_column_reads_as_empty(settings_manager):
    created = _create(settings_manager)
    row = settings_manager._db.get(AppRoleDb, str(created.id))
    row.hidden_nav_features = '{not json'
    settings_manager._db.commit()

    assert settings_manager.get_app_role(str(created.id)).hidden_nav_features == []


# --- Role YAML export -----------------------------------------------------------------

def test_role_yaml_carries_hidden_features_only_when_set():
    # to_yaml_dict reads an ``entity.permissions`` attribute AppRoleDb doesn't have, so
    # the rows are stand-ins with the attributes it reads.
    with_hidden = SimpleNamespace(
        name='r', description=None, permissions=None, assigned_groups='[]',
        hidden_nav_features='["assets"]',
    )
    without = SimpleNamespace(
        name='r', description=None, permissions=None, assigned_groups='[]',
        hidden_nav_features='[]',
    )

    assert RoleFileModel.to_yaml_dict(with_hidden)['hiddenNavFeatures'] == ['assets']
    assert 'hiddenNavFeatures' not in RoleFileModel.to_yaml_dict(without)


# --- Viewer's hidden list (AuthorizationManager) --------------------------------------

def _role(name, groups, perms, hidden=(), is_admin=False, users=()):
    return AppRole(
        id=uuid.uuid4(), name=name, assigned_groups=list(groups), assigned_users=list(users),
        feature_permissions=perms, hidden_nav_features=list(hidden), is_admin=is_admin,
    )


def _auth(*roles):
    settings_manager = Mock()
    settings_manager.list_app_roles.return_value = list(roles)
    return AuthorizationManager(settings_manager=settings_manager)


def test_single_role_hides_its_features_at_read_only_and_read_write():
    consumer = _role(
        'Consumer', ['consumers'],
        {'data-contracts': L.READ_ONLY, 'assets': L.READ_WRITE, 'data-catalog': L.READ_ONLY},
        hidden=['data-contracts', 'assets'],
    )

    # In feature-config order; data-catalog stays shown.
    assert _auth(consumer).get_user_hidden_nav_features(['consumers']) == [
        'data-contracts', 'assets',
    ]


def test_feature_is_shown_when_any_role_granting_it_shows_it():
    hides = _role('Hides', ['a'], {'data-contracts': L.READ_ONLY}, hidden=['data-contracts'])
    shows = _role('Shows', ['b'], {'data-contracts': L.READ_WRITE})

    assert _auth(hides, shows).get_user_hidden_nav_features(['a', 'b']) == []


def test_role_without_access_does_not_unhide_a_feature():
    hides = _role('Hides', ['a'], {'data-contracts': L.READ_ONLY}, hidden=['data-contracts'])
    no_access = _role('No access', ['b'], {'data-contracts': L.NONE, 'assets': L.READ_ONLY})

    assert _auth(hides, no_access).get_user_hidden_nav_features(['a', 'b']) == ['data-contracts']


def test_feature_hidden_by_every_granting_role_stays_hidden():
    one = _role('One', ['a'], {'assets': L.READ_ONLY}, hidden=['assets'])
    two = _role('Two', ['b'], {'assets': L.READ_WRITE}, hidden=['assets'])

    assert _auth(one, two).get_user_hidden_nav_features(['a', 'b']) == ['assets']


def test_admin_role_hides_nothing():
    admin = _role('Admin', ['admins'], {'assets': L.ADMIN}, hidden=['assets'], is_admin=True)
    hides = _role('Hides', ['admins'], {'assets': L.READ_ONLY}, hidden=['assets'])

    assert _auth(admin, hides).get_user_hidden_nav_features(['admins']) == []


def test_role_override_pins_the_switched_role():
    admin = _role('Admin', ['admins'], {'assets': L.ADMIN}, is_admin=True)
    consumer = _role('Consumer', ['consumers'], {'assets': L.READ_ONLY}, hidden=['assets'])
    auth = _auth(admin, consumer)

    assert auth.get_user_hidden_nav_features(['admins']) == []
    assert auth.get_user_hidden_nav_features(
        ['admins'], applied_role_override_id=str(consumer.id),
    ) == ['assets']
    assert auth.get_user_hidden_nav_features(
        ['consumers'], applied_role_override_id=str(admin.id),
    ) == []


def test_email_assigned_role_counts():
    by_email = _role('Direct', [], {'assets': L.READ_ONLY}, hidden=['assets'], users=['u@x.io'])

    assert _auth(by_email).get_user_hidden_nav_features([], user_email='U@x.io') == ['assets']


def test_user_without_roles_has_nothing_hidden():
    hides = _role('Hides', ['a'], {'assets': L.READ_ONLY}, hidden=['assets'])

    assert _auth(hides).get_user_hidden_nav_features(['other']) == []


# --- Migration ------------------------------------------------------------------------

@pytest.fixture
def migration():
    path = (
        Path(__file__).resolve().parents[3]
        / 'alembic' / 'versions' / 'r1_role_hidden_nav_features.py'
    )
    spec = importlib.util.spec_from_file_location('r1_role_hidden_nav_features', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_upgrade_adds_empty_list_and_downgrade_drops_it(migration):
    engine = create_engine('sqlite://', poolclass=StaticPool)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE app_roles (id TEXT PRIMARY KEY, name TEXT NOT NULL)"))
        conn.execute(text("INSERT INTO app_roles (id, name) VALUES ('r1', 'Existing')"))

    def run(fn):
        with engine.begin() as conn:
            with Operations.context(MigrationContext.configure(conn)):
                fn()

    assert migration.down_revision == 'b10_compliance_run_warning_code'
    run(migration.upgrade)
    run(migration.upgrade)  # idempotent
    with engine.connect() as conn:
        value = conn.execute(text("SELECT hidden_nav_features FROM app_roles")).scalar()
    assert value == '[]'

    run(migration.downgrade)
    with engine.connect() as conn:
        columns = {c['name'] for c in sa.inspect(conn).get_columns('app_roles')}
    assert 'hidden_nav_features' not in columns
