"""Turning on "write asset descriptions to Unity Catalog" needs an admin (#1477).

Saving the form sends the value as it is, so a READ_WRITE user who doesn't change
it is not refused; turning it off needs no admin either.
"""
import pytest
from fastapi import HTTPException

from src.app import app
from src.common.dependencies import get_settings
from src.common.features import FeatureAccessLevel
from src.routes import settings_routes


class _Checker:
    """Stands in for PermissionChecker: the test user is an admin only when ``admin`` says so."""
    admin = False

    def __init__(self, feature_id, required_level):
        self.required_level = required_level

    async def __call__(self, request, user_details, auth_manager):
        if self.required_level == FeatureAccessLevel.ADMIN and not _Checker.admin:
            raise HTTPException(status_code=403, detail="Admin required")
        return True


@pytest.fixture
def settings(test_settings, monkeypatch):
    monkeypatch.setattr(settings_routes, 'PermissionChecker', _Checker)
    test_settings.UC_DESCRIPTION_WRITEBACK_ENABLED = False
    app.dependency_overrides[get_settings] = lambda: test_settings
    yield test_settings
    app.dependency_overrides.pop(get_settings, None)
    test_settings.UC_DESCRIPTION_WRITEBACK_ENABLED = False


def _put(client, payload):
    return client.put('/api/settings', json=payload)


def test_a_non_admin_cannot_turn_the_write_back_on(client, settings):
    _Checker.admin = False
    try:
        response = _put(client, {'uc_description_writeback_enabled': True})
    finally:
        _Checker.admin = False

    assert response.status_code == 403
    assert settings.UC_DESCRIPTION_WRITEBACK_ENABLED is False


def test_an_admin_can_turn_the_write_back_on(client, settings):
    _Checker.admin = True
    try:
        response = _put(client, {'uc_description_writeback_enabled': True})
    finally:
        _Checker.admin = False

    assert response.status_code == 200, response.text
    assert settings.UC_DESCRIPTION_WRITEBACK_ENABLED is True


def test_a_non_admin_can_turn_it_off_and_save_it_unchanged(client, settings):
    settings.UC_DESCRIPTION_WRITEBACK_ENABLED = True
    _Checker.admin = False

    assert _put(client, {'uc_description_writeback_enabled': True}).status_code == 200
    assert _put(client, {'uc_description_writeback_enabled': False}).status_code == 200
    assert settings.UC_DESCRIPTION_WRITEBACK_ENABLED is False
