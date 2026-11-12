"""The "write asset descriptions to Unity Catalog" setting: off by default, saved, reloaded (#1477)."""
from unittest.mock import MagicMock, patch

from src.common.config import Settings
from src.controller.settings_manager import SettingsManager
from src.repositories.app_settings_repository import app_settings_repo


def _settings():
    return Settings(DATABRICKS_HOST='https://x', DATABRICKS_WAREHOUSE_ID='wh', ENV='TEST',
                    PGHOST='localhost')


def _manager(db, settings):
    manager = SettingsManager(db=db, settings=settings, workspace_client=MagicMock())
    manager._jobs = MagicMock()
    manager._jobs.list_available_workflows.return_value = []
    return manager


def test_the_setting_is_off_by_default(db_session):
    manager = _manager(db_session, _settings())

    assert manager.get_settings()['uc_description_writeback_enabled'] is False


def test_saving_the_setting_stores_it_and_a_new_manager_loads_it(db_session):
    manager = _manager(db_session, _settings())

    with patch('src.common.git.reinitialize_git_service'):
        manager.update_settings({'uc_description_writeback_enabled': True})

    assert manager.get_settings()['uc_description_writeback_enabled'] is True
    assert app_settings_repo.get_by_key(db_session, 'UC_DESCRIPTION_WRITEBACK_ENABLED') == 'true'
    reloaded = _settings()
    _manager(db_session, reloaded)
    assert reloaded.UC_DESCRIPTION_WRITEBACK_ENABLED is True
