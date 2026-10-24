"""Stored roles drop the retired Entitlements features instead of mapping them (P4 of #1083)."""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

from types import SimpleNamespace  # noqa: E402
from unittest.mock import MagicMock  # noqa: E402

from src.common.config import Settings  # noqa: E402
from src.controller.settings_manager import SettingsManager  # noqa: E402


def test_retired_feature_keys_are_dropped_not_escalated():
    manager = SettingsManager(db=MagicMock(), settings=MagicMock(spec=Settings), workspace_client=MagicMock())
    role = SimpleNamespace(
        id='3f0b7a1e-0000-4000-8000-000000000001', name='Security Officer', description=None, assigned_groups='[]', assigned_users='[]',
        feature_permissions='{"entitlements": "Admin", "entitlements-sync": "Admin", "compliance": "Read-only"}',
        home_sections='[]', approval_privileges='{}', deployment_policy=None, home_layout=None,
    )
    out = manager._map_db_to_api(role)
    perms = {k: getattr(v, 'value', v) for k, v in out.feature_permissions.items()}
    assert 'entitlements' not in perms and 'entitlements-sync' not in perms
    # The mockup's Admin level never turns into real Access Policies rights.
    assert 'access-policies' not in perms and perms['compliance'] == 'Read-only'
