"""Regression tests for the PROD test-identity guard."""
import os
os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import pytest
from pydantic import ValidationError

from src.common.config import Settings


def _settings(**overrides):
    return Settings(_env_file=None, APP_AUDIT_LOG_DIR="/tmp", **overrides)


@pytest.mark.parametrize("overrides", [
    {"TEST_USER_TOKEN": "secret"},
    {"MOCK_USER_DETAILS": True},
])
def test_test_identity_rejected_in_prod(overrides):
    with pytest.raises(ValidationError, match="must not be set when ENV=PROD"):
        _settings(ENV="PROD", **overrides)


@pytest.mark.parametrize("env, shown", [
    ("PRODUCTION", "PRODUCTION"),
    ("production", "PRODUCTION"),
    (" prod ", "PROD"),
    ("Production\n", "PRODUCTION"),
    ("prod", "PROD"),
])
@pytest.mark.parametrize("overrides", [
    {"TEST_USER_TOKEN": "secret"},
    {"MOCK_USER_DETAILS": True},
])
def test_test_identity_rejected_for_every_spelling_of_prod(env, shown, overrides):
    with pytest.raises(ValidationError, match=f"must not be set when ENV={shown} "):
        _settings(ENV=env, **overrides)


def test_the_rejection_names_every_setting_that_is_on():
    with pytest.raises(ValidationError, match="TEST_USER_TOKEN, MOCK_USER_DETAILS must not"):
        _settings(ENV="PRODUCTION", TEST_USER_TOKEN="secret", MOCK_USER_DETAILS=True)


@pytest.mark.parametrize("env", ["DEV", "LOCAL", "LOCAL-TEST", "STAGING"])
def test_test_identity_allowed_in_other_environments(env):
    settings = _settings(ENV=env, TEST_USER_TOKEN="secret", MOCK_USER_DETAILS=True)

    assert settings.TEST_USER_TOKEN == "secret"
    assert settings.MOCK_USER_DETAILS is True


@pytest.mark.parametrize("env", ["PROD", "PRODUCTION"])
def test_prod_without_test_identity_is_allowed(env):
    assert _settings(ENV=env).ENV == env


def test_the_guard_runs_for_settings_read_from_the_environment(monkeypatch):
    monkeypatch.setenv("ENV", "PRODUCTION")
    monkeypatch.setenv("TEST_USER_TOKEN", "x")
    monkeypatch.setenv("APP_AUDIT_LOG_DIR", "/tmp")

    with pytest.raises(
        ValidationError, match="TEST_USER_TOKEN must not be set when ENV=PRODUCTION",
    ):
        Settings(_env_file=None)


def test_test_identity_allowed_outside_prod():
    assert _settings(ENV="DEV", TEST_USER_TOKEN="secret", MOCK_USER_DETAILS=True).TEST_USER_TOKEN == "secret"
