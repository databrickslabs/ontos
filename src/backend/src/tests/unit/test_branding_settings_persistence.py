"""Unit tests: branding settings saved in the database are loaded again at startup.

Covers the tagline, dark logo, theme colors and the "powered by" switch through
``SettingsManager.update_settings`` and a fresh ``SettingsManager`` (a restart).
No ``client`` fixture is used.
"""
import pytest

from src.common.config import Settings
from src.controller.settings_manager import SettingsManager


def make_settings(tmp_path) -> Settings:
    # _env_file=None keeps a developer's local .env out of the test.
    return Settings(
        _env_file=None,
        DATABRICKS_HOST="https://test.example.com",
        DATABRICKS_WAREHOUSE_ID="wh",
        APP_AUDIT_LOG_DIR=str(tmp_path),
        ENV="TEST",
    )


@pytest.fixture
def manager(db_session, tmp_path):
    return SettingsManager(db=db_session, settings=make_settings(tmp_path), workspace_client=None)


def _restart(db_session, tmp_path) -> Settings:
    fresh = make_settings(tmp_path)
    SettingsManager(db=db_session, settings=fresh, workspace_client=None)
    return fresh


def test_defaults_keep_todays_look(tmp_path):
    s = make_settings(tmp_path)
    assert s.UI_APP_TAGLINE is None
    assert s.UI_CUSTOM_LOGO_DARK_URL is None
    assert s.UI_THEME_PRIMARY is None and s.UI_THEME_ACCENT_DARK is None
    assert s.UI_SHOW_POWERED_BY is True


def test_saved_branding_survives_restart(manager, db_session, tmp_path):
    manager.update_settings({
        "ui_app_tagline": "  Ontology of Acme ",
        "ui_custom_logo_dark_url": "/branding/acme/logo-dark.svg",
        "ui_theme_primary": "#ABC",
        "ui_theme_primary_dark": "#93c5fd",
        "ui_theme_accent": "#2563EB",
        "ui_theme_accent_dark": "#1e293b",
        "ui_show_powered_by": False,
    })
    fresh = _restart(db_session, tmp_path)
    assert fresh.UI_APP_TAGLINE == "Ontology of Acme"
    assert fresh.UI_CUSTOM_LOGO_DARK_URL == "/branding/acme/logo-dark.svg"
    assert fresh.UI_THEME_PRIMARY == "#aabbcc"
    assert fresh.UI_THEME_PRIMARY_DARK == "#93c5fd"
    assert fresh.UI_THEME_ACCENT == "#2563eb"
    assert fresh.UI_THEME_ACCENT_DARK == "#1e293b"
    assert fresh.UI_SHOW_POWERED_BY is False


def test_powered_by_true_survives_restart(manager, db_session, tmp_path):
    manager.update_settings({"ui_show_powered_by": False})
    manager.update_settings({"ui_show_powered_by": True})
    assert _restart(db_session, tmp_path).UI_SHOW_POWERED_BY is True


@pytest.mark.parametrize("value", ["yes", 1, "false"])
def test_powered_by_must_be_a_boolean(manager, value):
    with pytest.raises(ValueError):
        manager.update_settings({"ui_show_powered_by": value})


def test_cleared_branding_is_not_loaded_back(manager, db_session, tmp_path):
    manager.update_settings({"ui_app_tagline": "T", "ui_theme_primary": "#2563eb"})
    manager.update_settings({"ui_app_tagline": "", "ui_theme_primary": None})
    fresh = _restart(db_session, tmp_path)
    assert fresh.UI_APP_TAGLINE is None
    assert fresh.UI_THEME_PRIMARY is None
