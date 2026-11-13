"""Saving the General settings checks the volume setting before anything is stored.

A volume that can't name a Unity Catalog volume used to be accepted and failed
later, when a document upload or the Git export first resolved it. The check is
about the value's form only (no workspace call), so it also works when the
workspace is unreachable. It runs only when the volume, catalog or schema
changes, so a stored legacy value never blocks saving other settings.
"""
from unittest.mock import MagicMock, patch

import pytest

from src.common.config import Settings, VolumeInvalidError
from src.controller.settings_manager import SettingsManager
from src.db_models.app_settings import AppSettingDb


@pytest.fixture
def manager(db_session):
    settings = MagicMock(spec=Settings)
    settings.job_cluster_id = None
    settings.enabled_jobs = []
    settings.sync_enabled = False
    settings.sync_repository = None
    settings.DATABRICKS_CATALOG = "app_ontos"
    settings.DATABRICKS_SCHEMA = "app_ontos"
    settings.DATABRICKS_VOLUME = "app_files"
    settings.to_dict.return_value = {}
    return SettingsManager(db=db_session, settings=settings, workspace_client=MagicMock())


def _save(manager, payload):
    with patch("src.common.git.reinitialize_git_service"):
        return manager.update_settings(payload)


@pytest.mark.parametrize("volume", ["a.b", "a.b.c.d", "/Volumes/a/b", "my vol", "a/b/c"])
def test_an_invalid_volume_is_rejected_with_a_code_and_params(manager, volume):
    with pytest.raises(VolumeInvalidError) as raised:
        _save(manager, {"databricks_volume": volume})

    assert raised.value.code == "volume_invalid"
    assert raised.value.params["value"] == volume


def test_a_rejected_save_stores_nothing(manager):
    with pytest.raises(VolumeInvalidError):
        _save(manager, {
            "databricks_catalog": "other_catalog",
            "databricks_volume": "a.b",
            "llm_enabled": True,
        })

    assert manager._settings.DATABRICKS_CATALOG == "app_ontos"
    assert manager._settings.DATABRICKS_VOLUME == "app_files"
    stored = manager._db.query(AppSettingDb).filter(AppSettingDb.key.like("DATABRICKS_%"))
    assert stored.count() == 0
    assert manager._db.query(AppSettingDb).filter(AppSettingDb.key == "LLM_ENABLED").count() == 0


def test_a_volume_name_needs_a_usable_catalog_and_schema(manager):
    with pytest.raises(VolumeInvalidError) as raised:
        _save(manager, {"databricks_catalog": "my.catalog", "databricks_volume": "app_files"})

    assert raised.value.code == "volume_invalid"
    assert raised.value.params["catalog"] == "my.catalog"


@pytest.mark.parametrize("volume", ["other_vol", "cat.sch.vol", "/Volumes/cat/sch/vol"])
def test_a_valid_volume_is_saved(manager, volume):
    _save(manager, {"databricks_volume": volume})

    assert manager._settings.DATABRICKS_VOLUME == volume


def test_an_unchanged_legacy_value_does_not_block_other_settings(manager):
    manager._settings.DATABRICKS_VOLUME = "a.b"

    # The General form always sends the three fields back, unchanged.
    _save(manager, {
        "databricks_catalog": "app_ontos",
        "databricks_schema": "app_ontos",
        "databricks_volume": "a.b",
        "llm_enabled": False,
    })

    assert manager._settings.DATABRICKS_VOLUME == "a.b"


def test_clearing_the_volume_leaves_memory_as_a_restart_would(manager, monkeypatch):
    monkeypatch.delenv("DATABRICKS_VOLUME", raising=False)

    _save(manager, {"databricks_volume": ""})

    stored = manager._db.query(AppSettingDb).filter(AppSettingDb.key == "DATABRICKS_VOLUME").one()
    assert stored.value is None
    assert manager._settings.DATABRICKS_VOLUME is None


def test_clearing_the_volume_falls_back_to_the_environment_value(manager, monkeypatch):
    monkeypatch.setenv("DATABRICKS_VOLUME", "/Volumes/c/s/env_vol")

    _save(manager, {"databricks_volume": ""})

    assert manager._settings.DATABRICKS_VOLUME == "/Volumes/c/s/env_vol"


def test_clearing_the_volume_checks_the_environment_value(manager, monkeypatch):
    monkeypatch.setenv("DATABRICKS_VOLUME", "a.b")

    with pytest.raises(VolumeInvalidError):
        _save(manager, {"databricks_volume": ""})
