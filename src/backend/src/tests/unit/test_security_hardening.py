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


def test_test_identity_allowed_outside_prod():
    assert _settings(ENV="DEV", TEST_USER_TOKEN="secret", MOCK_USER_DETAILS=True).TEST_USER_TOKEN == "secret"
