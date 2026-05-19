"""Unit tests for ``is_user_feature_admin``.

Covers the cascade-bypass admin check used by data-products listing
(and any other PR D-style ownership scope). The helper must:

1. Short-circuit True when the user belongs to a workspace admin group.
2. Return True when the user's effective Ontos-role permissions grant
   ``FeatureAccessLevel.ADMIN`` on the named feature, even when they
   are *not* a workspace admin (the Daimler regression case).
3. Return False otherwise.
4. Honor applied-role overrides (the role-switcher path) when set.
5. Fail-closed on auth-manager errors — i.e., a transient resolution
   failure never flips a non-admin into admin.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.common.features import FeatureAccessLevel


def _make_request(*, auth_manager=None, settings_manager=None):
    """Construct a minimal FastAPI ``Request`` stand-in.

    The helper only reads ``request.app.state.authorization_manager`` and
    ``request.app.state.settings_manager`` — everything else is irrelevant.
    """
    request = MagicMock()
    request.app.state.authorization_manager = auth_manager
    request.app.state.settings_manager = settings_manager
    return request


@pytest.fixture
def mock_settings(monkeypatch):
    """Patch ``get_settings`` so ``is_user_admin`` reads a deterministic
    ``APP_ADMIN_DEFAULT_GROUPS`` value (the default ``["admins"]``)."""
    settings = MagicMock()
    settings.APP_ADMIN_DEFAULT_GROUPS = '["admins"]'
    monkeypatch.setattr(
        "src.common.authorization.get_settings", lambda: settings
    )
    return settings


@pytest.mark.asyncio
async def test_workspace_admin_short_circuits_true(mock_settings):
    """User in workspace ``admins`` group → True, no auth_manager call."""
    from src.common.authorization import is_user_feature_admin

    auth_manager = MagicMock()
    result = await is_user_feature_admin(
        user_email="someone@example.com",
        user_groups=["admins", "users"],
        feature_id="data-products",
        request=_make_request(auth_manager=auth_manager),
    )

    assert result is True
    # Short-circuit: auth manager must not be consulted at all.
    auth_manager.get_user_effective_permissions.assert_not_called()


@pytest.mark.asyncio
async def test_ontos_role_admin_grants_bypass(mock_settings):
    """Not a workspace admin, but role permissions grant ADMIN → True.

    This is the Daimler / FEVM-Mikhail regression case: the Ontos
    ``Admin`` role is assigned to a non-``admins`` workspace group
    (or via email-as-group), and the user's effective permissions
    include ``ADMIN`` on data-products.
    """
    from src.common.authorization import is_user_feature_admin

    auth_manager = MagicMock()
    auth_manager.get_user_effective_permissions.return_value = {
        "data-products": FeatureAccessLevel.ADMIN,
        "data-contracts": FeatureAccessLevel.READ_WRITE,
    }
    with patch(
        "src.common.authorization.get_user_team_role_overrides",
        new=AsyncMock(return_value=None),
    ):
        result = await is_user_feature_admin(
            user_email="mikhail@example.com",
            user_groups=["099_Treasure_DataProducer", "users"],
            feature_id="data-products",
            request=_make_request(auth_manager=auth_manager),
        )

    assert result is True
    auth_manager.get_user_effective_permissions.assert_called_once()


@pytest.mark.asyncio
async def test_read_write_role_does_not_grant_bypass(mock_settings):
    """User has READ_WRITE (Data Producer) — not ADMIN → False.

    Ensures Data Producers, who PR D *intentionally* restricts via the
    ownership cascade, are not accidentally promoted to admin.
    """
    from src.common.authorization import is_user_feature_admin

    auth_manager = MagicMock()
    auth_manager.get_user_effective_permissions.return_value = {
        "data-products": FeatureAccessLevel.READ_WRITE,
    }
    with patch(
        "src.common.authorization.get_user_team_role_overrides",
        new=AsyncMock(return_value=None),
    ):
        result = await is_user_feature_admin(
            user_email="producer@example.com",
            user_groups=["099_Treasure_DataProducer"],
            feature_id="data-products",
            request=_make_request(auth_manager=auth_manager),
        )

    assert result is False


@pytest.mark.asyncio
async def test_no_email_returns_false_for_non_workspace_admin(mock_settings):
    """No email + not a workspace admin → False (can't resolve role)."""
    from src.common.authorization import is_user_feature_admin

    auth_manager = MagicMock()
    result = await is_user_feature_admin(
        user_email=None,
        user_groups=["random-group"],
        feature_id="data-products",
        request=_make_request(auth_manager=auth_manager),
    )

    assert result is False
    auth_manager.get_user_effective_permissions.assert_not_called()


@pytest.mark.asyncio
async def test_auth_manager_failure_falls_back_to_false(mock_settings, caplog):
    """Auth-manager exception → False; the workspace-admin signal is the
    only thing that could have flipped it True, and it didn't."""
    from src.common.authorization import is_user_feature_admin

    auth_manager = MagicMock()
    auth_manager.get_user_effective_permissions.side_effect = RuntimeError("db down")
    with patch(
        "src.common.authorization.get_user_team_role_overrides",
        new=AsyncMock(return_value=None),
    ):
        result = await is_user_feature_admin(
            user_email="user@example.com",
            user_groups=["users"],
            feature_id="data-products",
            request=_make_request(auth_manager=auth_manager),
        )

    assert result is False
    # Failure was logged (not silently swallowed).
    assert any(
        "is_user_feature_admin" in rec.message for rec in caplog.records
    )


@pytest.mark.asyncio
async def test_applied_role_override_path_uses_override(mock_settings):
    """When a session-scoped role override is active, the helper uses
    the override's permissions (matches ``enforce_feature_permission``).

    Override grants ADMIN → True.
    """
    from src.common.authorization import is_user_feature_admin

    auth_manager = MagicMock()
    # Permanent permissions only grant READ_WRITE — the override is what
    # should flip the answer.
    auth_manager.get_user_effective_permissions.return_value = {
        "data-products": FeatureAccessLevel.READ_WRITE,
    }

    settings_manager = MagicMock()
    settings_manager.get_applied_role_override_for_user.return_value = "admin-role-id"
    settings_manager.get_feature_permissions_for_role_id.return_value = {
        "data-products": FeatureAccessLevel.ADMIN,
    }

    with patch(
        "src.common.authorization.get_user_team_role_overrides",
        new=AsyncMock(return_value=None),
    ):
        result = await is_user_feature_admin(
            user_email="role-switcher@example.com",
            user_groups=["users"],
            feature_id="data-products",
            request=_make_request(
                auth_manager=auth_manager, settings_manager=settings_manager
            ),
        )

    assert result is True
    # Override path used — group-based resolution must not be consulted.
    auth_manager.get_user_effective_permissions.assert_not_called()
    settings_manager.get_feature_permissions_for_role_id.assert_called_once_with(
        "admin-role-id"
    )


@pytest.mark.asyncio
async def test_no_auth_manager_returns_false(mock_settings):
    """Defensive: ``authorization_manager`` missing from app state → False
    (no way to resolve Ontos-role permissions)."""
    from src.common.authorization import is_user_feature_admin

    result = await is_user_feature_admin(
        user_email="user@example.com",
        user_groups=["users"],
        feature_id="data-products",
        request=_make_request(auth_manager=None),
    )

    assert result is False
