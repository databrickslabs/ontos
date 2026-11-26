"""Regression tests for the test-identity guard (allow-list: DEV and LOCAL*)."""
import os
import re
os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import pytest
from pydantic import ValidationError

from src.common.config import Settings


def _settings(**overrides):
    return Settings(_env_file=None, APP_AUDIT_LOG_DIR="/tmp", **overrides)


IDENTITY = [
    {"TEST_USER_TOKEN": "secret"},
    {"MOCK_USER_DETAILS": True},
]


@pytest.mark.parametrize("overrides", IDENTITY)
@pytest.mark.parametrize("env, shown", [
    ("PROD", "PROD"),
    ("PRODUCTION", "PRODUCTION"),
    ("production", "PRODUCTION"),
    (" prod ", "PROD"),
    ("STAGING", "STAGING"),
    ("QA", "QA"),
    ("DEVELOPMENT", "DEVELOPMENT"),
    ("TEST", "TEST"),
    ("NOT-LOCAL", "NOT-LOCAL"),
    ("", "(empty)"),
])
def test_test_identity_rejected_outside_dev_and_local(env, shown, overrides):
    with pytest.raises(ValidationError, match=f"must not be set when ENV={re.escape(shown)} "):
        _settings(ENV=env, **overrides)


def test_the_rejection_names_both_variables_and_the_allowed_values():
    with pytest.raises(ValidationError) as exc:
        _settings(ENV="STAGING", TEST_USER_TOKEN="secret")

    message = str(exc.value)
    assert "TEST_USER_TOKEN and MOCK_USER_DETAILS are allowed only when ENV=DEV" in message
    assert "starts with LOCAL" in message


def test_the_rejection_names_every_setting_that_is_on():
    with pytest.raises(ValidationError, match="TEST_USER_TOKEN, MOCK_USER_DETAILS must not"):
        _settings(ENV="PRODUCTION", TEST_USER_TOKEN="secret", MOCK_USER_DETAILS=True)


@pytest.mark.parametrize(
    "env", ["DEV", "dev", " Dev ", "LOCAL", "local", "LOCAL-TEST", "LOCALHOST"],
)
def test_test_identity_allowed_in_dev_and_local(env):
    settings = _settings(ENV=env, TEST_USER_TOKEN="secret", MOCK_USER_DETAILS=True)

    assert settings.TEST_USER_TOKEN == "secret"
    assert settings.MOCK_USER_DETAILS is True


@pytest.mark.parametrize("env", ["PROD", "PRODUCTION", "STAGING", "DEV", "LOCAL"])
def test_no_test_identity_is_allowed_in_every_environment(env):
    assert _settings(ENV=env).ENV == env


def test_unset_env_defaults_to_prod_and_refuses_test_identity(monkeypatch):
    monkeypatch.delenv("ENV", raising=False)

    assert _settings().ENV == "PROD"
    with pytest.raises(ValidationError, match="must not be set when ENV=PROD "):
        _settings(TEST_USER_TOKEN="secret")


def test_the_guard_runs_for_settings_read_from_the_environment(monkeypatch):
    monkeypatch.setenv("ENV", "STAGING")
    monkeypatch.setenv("TEST_USER_TOKEN", "x")
    monkeypatch.setenv("APP_AUDIT_LOG_DIR", "/tmp")

    with pytest.raises(
        ValidationError, match="TEST_USER_TOKEN must not be set when ENV=STAGING",
    ):
        Settings(_env_file=None)
