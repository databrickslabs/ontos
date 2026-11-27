"""Navigation presets (#1325): preview, apply and undo on the roles of a SettingsManager."""
import json
from unittest.mock import MagicMock

import pytest
import yaml

from src.common.config import Settings
from src.common.features import APP_FEATURES, NAV_MENU_ENTRIES, FeatureAccessLevel as L
from src.controller import navigation_presets_manager as npm
from src.controller.navigation_presets_manager import (
    LAST_APPLIED_SETTING_KEY,
    NavigationPresetNothingToUndoError,
    NavigationPresetsManager,
    NavigationPresetUnknownError,
    compute_hidden_entries,
    load_navigation_presets,
)
from src.controller.settings_manager import SettingsManager
from src.db_models.settings import AppRoleDb
from src.models.navigation_presets import NavigationPresetDef
from src.models.settings import AppRole, AppRoleCreate, HomeSection
from src.repositories.app_settings_repository import app_settings_repo

CONSUMER = 'Data Consumer'
STEWARD = 'Data Steward'
OFFICER = 'Data Governance Officer'

CONSUMER_PERMS = {
    'data-catalog': L.READ_ONLY, 'data-contracts': L.READ_ONLY, 'data-products': L.READ_ONLY,
}
STEWARD_PERMS = {
    'data-catalog': L.READ_WRITE, 'assets': L.READ_WRITE, 'semantic-models': L.READ_WRITE,
    'data-contracts': L.READ_WRITE, 'data-products': L.READ_WRITE,
    'data-asset-reviews': L.READ_WRITE, 'compliance': L.READ_ONLY,
}
OFFICER_PERMS = {**STEWARD_PERMS, 'compliance': L.ADMIN, 'master-data': L.ADMIN}


@pytest.fixture
def settings_manager(db_session):
    settings = MagicMock(spec=Settings)
    settings.to_dict.return_value = {}
    manager = SettingsManager(db=db_session, settings=settings, workspace_client=MagicMock())
    # No delivery mode in these tests; the queue call is checked where it matters.
    manager._queue_role_delivery = MagicMock(return_value=False)
    return manager


@pytest.fixture
def roles(settings_manager):
    def _create(name, perms, home=(), hidden=(), is_admin=False):
        return settings_manager.create_app_role(AppRoleCreate(
            name=name, feature_permissions=perms, home_sections=list(home),
            hidden_nav_features=list(hidden), is_admin=is_admin,
        ))

    return {
        CONSUMER: _create(CONSUMER, CONSUMER_PERMS, home=[HomeSection.DISCOVERY]),
        STEWARD: _create(STEWARD, STEWARD_PERMS, home=[HomeSection.REQUIRED_ACTIONS]),
        OFFICER: _create(
            OFFICER, OFFICER_PERMS, home=[HomeSection.DISCOVERY], hidden=['master-data'],
        ),
    }


@pytest.fixture
def manager(settings_manager, roles):
    return NavigationPresetsManager(settings_manager)


def _role(settings_manager, role) -> AppRole:
    return settings_manager.get_app_role(str(role.id))


def _permissions(settings_manager):
    return {
        r.name: {k: v.value for k, v in r.feature_permissions.items()}
        for r in settings_manager.list_app_roles()
    }


# --- Shipped presets --------------------------------------------------------------------

def test_every_shipped_preset_file_is_valid():
    files = sorted(npm.PRESETS_DIR.glob('*.yaml'))
    presets = load_navigation_presets()

    assert [f.stem for f in files] == ['data-consumer', 'essentials']
    assert sorted(presets) == [f.stem for f in files]
    for preset in presets.values():
        for definition in preset.roles.values():
            assert set(definition.shown) <= set(NAV_MENU_ENTRIES)


def test_shipped_presets_name_default_roles_and_never_admin():
    defaults = yaml.safe_load(
        (npm.PRESETS_DIR.parent.parent / 'settings.yaml').read_text(encoding='utf-8')
    )['roles']
    default_names = {r['name'] for r in defaults}

    for preset in load_navigation_presets().values():
        assert set(preset.roles) <= default_names - {'Admin'}


def test_invalid_files_are_skipped_not_fatal(tmp_path):
    (tmp_path / 'good.yaml').write_text('id: good\nroles:\n  R:\n    shown: [assets]\n')
    (tmp_path / 'bad-entry.yaml').write_text('id: bad-entry\nroles:\n  R:\n    shown: [nope]\n')
    (tmp_path / 'bad-section.yaml').write_text(
        'id: bad-section\nroles:\n  R:\n    shown: []\n    home_sections: [NOPE]\n'
    )
    (tmp_path / 'other-id.yaml').write_text('id: different\nroles: {}\n')
    (tmp_path / 'broken.yaml').write_text('id: [unclosed\n')

    assert list(load_navigation_presets(tmp_path)) == ['good']


# --- Hidden computation -----------------------------------------------------------------

def _plain_role(perms) -> AppRole:
    return AppRole(name='r', feature_permissions=perms, id='00000000-0000-0000-0000-000000000001')


def test_hidden_is_every_other_entry_the_role_can_access_in_menu_order():
    role = _plain_role({
        'data-products': L.READ_ONLY, 'data-contracts': L.READ_WRITE, 'assets': L.NONE,
        'data-catalog': L.READ_ONLY, 'compliance': L.FILTERED,
    })

    hidden = compute_hidden_entries(role, ['data-catalog'])

    # Marketplace and My Products follow Products; assets has no access, so it isn't listed.
    assert hidden == ['marketplace', 'data-contracts', 'data-products', 'my-products', 'compliance']
    assert list(NAV_MENU_ENTRIES) == [e for e in NAV_MENU_ENTRIES]  # menu order is stable


def test_a_shown_entry_is_never_hidden_and_none_means_not_hidden():
    role = _plain_role({'data-products': L.READ_WRITE, 'assets': L.NONE})

    assert compute_hidden_entries(role, ['marketplace', 'my-products']) == ['data-products']
    assert compute_hidden_entries(role, ['data-products']) == ['marketplace', 'my-products']
    assert compute_hidden_entries(_plain_role({}), []) == []


def test_preview_reports_hidden_no_access_and_changed(manager, roles):
    response = manager.get_presets()

    essentials = next(p for p in response.presets if p.id == 'essentials')
    by_name = {r.role_name: r for r in essentials.roles}
    consumer = by_name[CONSUMER]
    assert consumer.found and consumer.role_id == str(roles[CONSUMER].id)
    assert consumer.shown == ['data-catalog', 'assets', 'semantic-models']
    # The consumer has no access to assets and concepts: shown, but absent from the menu.
    assert consumer.no_access == ['assets', 'semantic-models']
    assert consumer.hidden == ['marketplace', 'data-contracts', 'data-products', 'my-products']
    assert consumer.home_sections == [HomeSection.JOURNEY]
    assert consumer.current_hidden == []
    assert consumer.current_home_sections == [HomeSection.DISCOVERY]
    assert consumer.changed
    assert response.last_applied is None


def test_preview_marks_a_missing_role_and_never_changes_it(manager, settings_manager, roles):
    settings_manager.delete_app_role(str(roles[OFFICER].id))

    essentials = next(p for p in manager.get_presets().presets if p.id == 'essentials')
    officer = next(r for r in essentials.roles if r.role_name == OFFICER)

    assert not officer.found and officer.role_id is None and not officer.changed


# --- Apply ------------------------------------------------------------------------------

def test_apply_changes_only_menu_and_home_never_permissions(manager, settings_manager, roles):
    before = _permissions(settings_manager)

    result = manager.apply('essentials', user='admin@x.io')

    assert [r.role_name for r in result.changed_roles] == [CONSUMER, STEWARD, OFFICER]
    assert result.unchanged_roles == [] and result.missing_roles == []
    assert _permissions(settings_manager) == before
    consumer = _role(settings_manager, roles[CONSUMER])
    assert consumer.home_sections == [HomeSection.JOURNEY]
    assert consumer.hidden_nav_features == [
        'marketplace', 'data-contracts', 'data-products', 'my-products',
    ]
    officer = _role(settings_manager, roles[OFFICER])
    # The preset replaces the list: master-data was hidden before and still is.
    assert officer.hidden_nav_features == [
        'marketplace', 'data-contracts', 'data-products', 'my-products', 'master-data',
    ]
    assert 'compliance' not in officer.hidden_nav_features


def test_apply_leaves_other_role_fields_alone(manager, settings_manager, roles):
    row = settings_manager._db.get(AppRoleDb, str(roles[CONSUMER].id))
    columns = {
        c.name: getattr(row, c.name) for c in AppRoleDb.__table__.columns
        if c.name not in ('hidden_nav_features', 'home_sections', 'updated_at')
    }

    manager.apply('essentials')

    settings_manager._db.refresh(row)
    for name, value in columns.items():
        assert getattr(row, name) == value, name


def test_apply_without_home_sections_leaves_them(settings_manager, roles):
    preset = NavigationPresetDef.model_validate(
        {'id': 'menu-only', 'roles': {CONSUMER: {'shown': ['data-catalog']}}}
    )
    manager = NavigationPresetsManager(settings_manager, presets={'menu-only': preset})

    manager.apply('menu-only')

    consumer = _role(settings_manager, roles[CONSUMER])
    assert consumer.home_sections == [HomeSection.DISCOVERY]
    assert 'data-products' in consumer.hidden_nav_features


def test_reapply_changes_nothing_and_keeps_the_snapshot(manager, settings_manager, roles):
    manager.apply('essentials', user='first@x.io')
    snapshot = app_settings_repo.get_by_key(settings_manager._db, LAST_APPLIED_SETTING_KEY)

    again = manager.apply('essentials', user='second@x.io')

    assert again.changed_roles == []
    assert sorted(again.unchanged_roles) == sorted([CONSUMER, STEWARD, OFFICER])
    assert app_settings_repo.get_by_key(settings_manager._db, LAST_APPLIED_SETTING_KEY) == snapshot
    assert json.loads(snapshot)['applied_by'] == 'first@x.io'


def test_apply_reports_a_missing_role_and_changes_the_others(manager, settings_manager, roles):
    settings_manager.delete_app_role(str(roles[OFFICER].id))

    result = manager.apply('essentials')

    assert result.missing_roles == [OFFICER]
    assert [r.role_name for r in result.changed_roles] == [CONSUMER, STEWARD]


def test_an_admin_role_is_never_changed(settings_manager):
    admin = settings_manager.create_app_role(AppRoleCreate(
        name='Admin', feature_permissions={'data-products': L.ADMIN, 'assets': L.ADMIN},
        home_sections=[HomeSection.DISCOVERY], is_admin=True,
    ))
    preset = NavigationPresetDef.model_validate(
        {'id': 'p', 'roles': {'Admin': {'shown': [], 'home_sections': ['JOURNEY']}}}
    )
    manager = NavigationPresetsManager(settings_manager, presets={'p': preset})

    preview = manager.get_presets().presets[0].roles[0]
    result = manager.apply('p')

    assert preview.found and not preview.changed and preview.hidden == []
    assert result.unchanged_roles == ['Admin'] and result.changed_roles == []
    after = _role(settings_manager, admin)
    assert after.hidden_nav_features == []
    assert after.home_sections == [HomeSection.DISCOVERY]
    assert app_settings_repo.get_by_key(settings_manager._db, LAST_APPLIED_SETTING_KEY) is None


def test_unknown_preset_is_a_coded_error(manager):
    with pytest.raises(NavigationPresetUnknownError) as exc_info:
        manager.apply('no-such-preset')

    assert exc_info.value.code == 'navigation_preset_unknown'
    assert exc_info.value.params == {'preset_id': 'no-such-preset'}


def test_apply_queues_delivery_for_each_changed_role_only(manager, settings_manager, roles):
    settings_manager._queue_role_delivery.reset_mock()

    manager.apply('data-consumer', user='a@x.io', background_tasks='bg')

    calls = settings_manager._queue_role_delivery.call_args_list
    assert len(calls) == 1
    assert calls[0].kwargs['change_type_name'] == 'ROLE_UPDATE'
    assert calls[0].kwargs['user'] == 'a@x.io'
    assert calls[0].kwargs['background_tasks'] == 'bg'
    assert str(calls[0].kwargs['entity'].id) == str(roles[CONSUMER].id)


def test_a_failure_while_saving_the_snapshot_rolls_back_the_transaction(
    manager, settings_manager, monkeypatch,
):
    # The test session wraps everything in one outer transaction, so the effect of the
    # rollback on the roles can't be read back here: check that it happens, and that no
    # delivery is queued for roles whose change didn't commit.
    rollbacks = []
    real_rollback = settings_manager._db.rollback
    monkeypatch.setattr(
        settings_manager._db, 'rollback', lambda: (rollbacks.append(1), real_rollback())[1],
    )

    def fail(*args, **kwargs):
        raise RuntimeError('snapshot failed')

    monkeypatch.setattr(npm.app_settings_repo, 'set', fail)
    settings_manager._queue_role_delivery.reset_mock()

    with pytest.raises(RuntimeError):
        manager.apply('essentials')

    assert rollbacks == [1]
    assert settings_manager._queue_role_delivery.call_count == 0


def test_the_snapshot_and_the_roles_are_committed_together(manager, settings_manager, monkeypatch):
    events = []
    real_commit = settings_manager._db.commit
    real_set = npm.app_settings_repo.set
    monkeypatch.setattr(
        settings_manager._db, 'commit', lambda: (events.append('commit'), real_commit())[1],
    )

    def spy_set(*args, **kwargs):
        events.append(('set', kwargs.get('commit')))
        return real_set(*args, **kwargs)

    monkeypatch.setattr(npm.app_settings_repo, 'set', spy_set)
    manager.get_presets()
    events.clear()

    manager.apply('essentials')

    # The snapshot is staged without its own commit; one commit then saves it with the roles.
    assert events == [('set', False), 'commit']


# --- Undo -------------------------------------------------------------------------------

def test_undo_without_an_application_is_a_coded_error(manager):
    with pytest.raises(NavigationPresetNothingToUndoError) as exc_info:
        manager.undo()

    assert exc_info.value.code == 'navigation_preset_nothing_to_undo'


def test_undo_restores_the_previous_menus_and_forgets_the_snapshot(
    manager, settings_manager, roles,
):
    before = {name: _role(settings_manager, role) for name, role in roles.items()}
    manager.apply('essentials')

    result = manager.undo()

    assert result.preset_id == 'essentials'
    assert [r.role_name for r in result.restored_roles] == [CONSUMER, STEWARD, OFFICER]
    for name, role in roles.items():
        after = _role(settings_manager, role)
        assert after.hidden_nav_features == before[name].hidden_nav_features
        assert after.home_sections == before[name].home_sections
    assert manager.get_presets().last_applied is None
    with pytest.raises(NavigationPresetNothingToUndoError):
        manager.undo()


def test_applying_another_preset_replaces_the_snapshot(manager, settings_manager, roles):
    manager.apply('essentials')
    after_a = _role(settings_manager, roles[CONSUMER])

    manager.apply('data-consumer')
    assert manager.get_presets().last_applied.preset_id == 'data-consumer'
    consumer = _role(settings_manager, roles[CONSUMER])
    assert consumer.home_sections == [HomeSection.MARKETPLACE]
    assert 'marketplace' not in consumer.hidden_nav_features
    assert 'data-products' in consumer.hidden_nav_features

    result = manager.undo()

    # Undo goes back to A's state, not to the state before A.
    assert result.preset_id == 'data-consumer'
    assert [r.role_name for r in result.restored_roles] == [CONSUMER]
    restored = _role(settings_manager, roles[CONSUMER])
    assert restored.hidden_nav_features == after_a.hidden_nav_features
    assert restored.home_sections == [HomeSection.JOURNEY]
    # The steward keeps what A set.
    assert _role(settings_manager, roles[STEWARD]).home_sections == [HomeSection.JOURNEY]


def test_undo_reports_roles_deleted_since(manager, settings_manager, roles):
    manager.apply('essentials')
    settings_manager.delete_app_role(str(roles[STEWARD].id))

    result = manager.undo()

    assert result.missing_roles == [STEWARD]
    assert [r.role_name for r in result.restored_roles] == [CONSUMER, OFFICER]


def test_undo_drops_ids_that_no_longer_exist_and_ignores_unreadable_snapshots(
    manager, settings_manager, roles,
):
    db = settings_manager._db
    app_settings_repo.set(db, LAST_APPLIED_SETTING_KEY, json.dumps({
        'preset_id': 'essentials', 'applied_at': 'x', 'applied_by': None,
        'roles': {str(roles[CONSUMER].id): {
            'name': CONSUMER, 'hidden_nav_features': ['assets', 'gone-feature'],
            'home_sections': ['DISCOVERY', 'GONE_SECTION'],
        }},
    }))

    manager.undo()

    consumer = _role(settings_manager, roles[CONSUMER])
    assert consumer.hidden_nav_features == ['assets']
    assert consumer.home_sections == [HomeSection.DISCOVERY]

    app_settings_repo.set(db, LAST_APPLIED_SETTING_KEY, '{not json')
    assert manager.get_presets().last_applied is None
    with pytest.raises(NavigationPresetNothingToUndoError):
        manager.undo()


def test_preset_feature_ids_are_registered_features_or_entries():
    for entry, feature_id in NAV_MENU_ENTRIES.items():
        assert feature_id in APP_FEATURES, entry


# --- Ids that aren't menu entries ---------------------------------------------------------

def _set_hidden(settings_manager, role, hidden):
    row = settings_manager._db.get(AppRoleDb, str(role.id))
    row.hidden_nav_features = json.dumps(hidden)
    settings_manager._db.commit()


def test_apply_keeps_hidden_ids_that_are_not_menu_entries_and_undo_restores_the_list(
    manager, settings_manager, roles,
):
    assert 'term-mapping' in APP_FEATURES and 'term-mapping' not in NAV_MENU_ENTRIES
    _set_hidden(settings_manager, roles[CONSUMER], ['term-mapping', 'master-data'])
    before = _role(settings_manager, roles[CONSUMER]).hidden_nav_features

    manager.apply('essentials')

    hidden = _role(settings_manager, roles[CONSUMER]).hidden_nav_features
    assert 'term-mapping' in hidden
    assert hidden.count('term-mapping') == 1
    # The menu entries are the preset's: Products is now hidden, the old list's own entry
    # (Master Data, no access for this role) isn't kept.
    assert 'data-products' in hidden
    assert 'master-data' not in hidden

    manager.undo()

    assert _role(settings_manager, roles[CONSUMER]).hidden_nav_features == before
    assert before == ['term-mapping', 'master-data']
