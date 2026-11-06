"""The UI edition setting: validation, the env fallback, loading and updating it."""
import logging
from unittest.mock import MagicMock

import pytest

from src.common.config import (
    Settings,
    UiEditionInvalidError,
    coerce_ui_edition,
    validate_ui_edition,
)
from src.controller.settings_manager import SettingsManager
from src.repositories.app_settings_repository import app_settings_repo


@pytest.mark.parametrize('value,expected', [
    ('full', 'full'), ('essentials', 'essentials'), (' Essentials ', 'essentials'),
])
def test_validate_ui_edition_accepts_known_editions(value, expected):
    assert validate_ui_edition(value) == expected


@pytest.mark.parametrize('value', ['pro', '', 'essential', 3, None])
def test_validate_ui_edition_refuses_unknown_with_a_code(value):
    with pytest.raises(UiEditionInvalidError) as raised:
        validate_ui_edition(value)
    assert raised.value.code == 'ui_edition_invalid'
    assert raised.value.params['allowed'] == ['full', 'essentials']


def test_coerce_ui_edition_falls_back_to_full_with_a_warning(caplog):
    with caplog.at_level(logging.WARNING):
        assert coerce_ui_edition('enterprise', source='database') == 'full'
    assert 'UI_EDITION' in caplog.text
    assert coerce_ui_edition(None, source='database') == 'full'
    assert coerce_ui_edition('  ', source='database') == 'full'
    assert coerce_ui_edition('ESSENTIALS', source='database') == 'essentials'


def test_settings_default_and_unknown_env_value(test_settings):
    assert test_settings.UI_EDITION == 'full'
    base = test_settings.model_dump(include={'DATABRICKS_HOST', 'APP_AUDIT_LOG_DIR', 'ENV'})
    assert Settings(**base, UI_EDITION='bogus').UI_EDITION == 'full'
    assert Settings(**base, UI_EDITION='essentials').UI_EDITION == 'essentials'


def _manager(db_session, settings):
    return SettingsManager(db=db_session, settings=settings, workspace_client=MagicMock())


@pytest.mark.parametrize('stored,expected', [
    ('essentials', 'essentials'), ('full', 'full'), ('bogus', 'full'),
])
def test_load_persisted_edition(db_session, test_settings, stored, expected):
    app_settings_repo.set(db_session, 'UI_EDITION', stored)
    manager = _manager(db_session, test_settings)
    assert manager._settings.UI_EDITION == expected
    assert manager.get_settings()['ui_edition'] == expected


def test_update_edition_round_trip(db_session, test_settings):
    manager = _manager(db_session, test_settings)
    manager.update_settings({'ui_edition': 'essentials'})
    assert app_settings_repo.get_by_key(db_session, 'UI_EDITION') == 'essentials'
    assert manager.get_settings()['ui_edition'] == 'essentials'
    # None resets to the default edition
    manager.update_settings({'ui_edition': None})
    assert manager._settings.UI_EDITION == 'full'


def test_update_unknown_edition_persists_nothing(db_session, test_settings):
    manager = _manager(db_session, test_settings)
    with pytest.raises(UiEditionInvalidError):
        manager.update_settings({'ui_custom_css': 'body {}', 'ui_edition': 'pro'})
    assert app_settings_repo.get_by_key(db_session, 'UI_EDITION') is None
    assert app_settings_repo.get_by_key(db_session, 'UI_CUSTOM_CSS') is None
    assert manager._settings.UI_EDITION == 'full'
