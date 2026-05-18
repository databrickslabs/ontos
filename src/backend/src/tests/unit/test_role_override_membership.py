"""
Unit tests for SettingsManager.set_applied_role_override_for_user membership validation.

Regression coverage for the role-switcher bug where users in multiple roles could not
switch between them, and the corresponding defense-in-depth backend hardening that
rejects non-admin attempts to override to a role they don't belong to.
"""
import json
import uuid

import pytest
from unittest.mock import MagicMock

from src.controller.settings_manager import SettingsManager
from src.db_models.settings import AppRoleDb
from src.common.config import Settings


def _make_role(db_session, name, assigned_groups, feature_permissions=None):
    role = AppRoleDb(
        id=str(uuid.uuid4()),
        name=name,
        description=f"{name} role",
        feature_permissions=json.dumps(feature_permissions or {}),
        assigned_groups=json.dumps(assigned_groups),
        home_sections='[]',
        approval_privileges='{}',
    )
    db_session.add(role)
    db_session.commit()
    db_session.refresh(role)
    return role


class TestRoleOverrideMembership:
    """Validation tests for the role-override entry point."""

    @pytest.fixture
    def mock_settings(self):
        mock = MagicMock(spec=Settings)
        mock.job_cluster_id = "test-cluster"
        mock.to_dict.return_value = {"job_cluster_id": "test-cluster"}
        return mock

    @pytest.fixture
    def mock_ws_client(self):
        return MagicMock()

    @pytest.fixture
    def manager(self, db_session, mock_settings, mock_ws_client):
        return SettingsManager(
            db=db_session,
            settings=mock_settings,
            workspace_client=mock_ws_client,
        )

    @pytest.fixture
    def producer_role(self, db_session):
        return _make_role(db_session, "Data Producer", ["data-producers"])

    @pytest.fixture
    def steward_role(self, db_session):
        return _make_role(db_session, "Data Steward", ["data-stewards"])

    @pytest.fixture
    def admin_role(self, db_session):
        return _make_role(db_session, "Admin", ["admins"])

    # ------------------------------------------------------------------
    # Admin path — impersonation power preserved (regression guard)
    # ------------------------------------------------------------------
    def test_admin_can_override_to_any_role(self, manager, admin_role, producer_role):
        manager.set_applied_role_override_for_user(
            "admin@example.com",
            producer_role.id,
            caller_groups=["admins"],
            caller_is_admin=True,
        )
        assert manager.get_applied_role_override_for_user("admin@example.com") == producer_role.id

    def test_admin_can_override_without_matching_groups(self, manager, producer_role):
        # Admin with no overlap on the target role should still succeed.
        manager.set_applied_role_override_for_user(
            "admin@example.com",
            producer_role.id,
            caller_groups=[],
            caller_is_admin=True,
        )
        assert manager.get_applied_role_override_for_user("admin@example.com") == producer_role.id

    # ------------------------------------------------------------------
    # Non-admin path — membership-scoped
    # ------------------------------------------------------------------
    def test_non_admin_can_override_to_role_they_belong_to(self, manager, producer_role, steward_role):
        manager.set_applied_role_override_for_user(
            "user@example.com",
            steward_role.id,
            caller_groups=["data-producers", "data-stewards"],
            caller_is_admin=False,
        )
        assert manager.get_applied_role_override_for_user("user@example.com") == steward_role.id

    def test_non_admin_cannot_override_to_role_outside_membership(self, manager, admin_role):
        # User not in admins must not be able to set the admin role override.
        with pytest.raises(PermissionError):
            manager.set_applied_role_override_for_user(
                "user@example.com",
                admin_role.id,
                caller_groups=["data-producers", "data-stewards"],
                caller_is_admin=False,
            )
        # No override should have been recorded.
        assert manager.get_applied_role_override_for_user("user@example.com") is None

    def test_non_admin_with_no_groups_is_rejected(self, manager, producer_role):
        with pytest.raises(PermissionError):
            manager.set_applied_role_override_for_user(
                "user@example.com",
                producer_role.id,
                caller_groups=[],
                caller_is_admin=False,
            )

    def test_group_match_is_case_insensitive(self, manager, producer_role):
        # User group casing differs from role.assigned_groups casing — should still match.
        manager.set_applied_role_override_for_user(
            "user@example.com",
            producer_role.id,
            caller_groups=["Data-Producers"],
            caller_is_admin=False,
        )
        assert manager.get_applied_role_override_for_user("user@example.com") == producer_role.id

    # ------------------------------------------------------------------
    # Clearing the override
    # ------------------------------------------------------------------
    def test_clearing_override_is_always_allowed_for_non_admin(self, manager, producer_role):
        # First set a legitimate override.
        manager.set_applied_role_override_for_user(
            "user@example.com",
            producer_role.id,
            caller_groups=["data-producers"],
            caller_is_admin=False,
        )
        # Then clear it without passing groups — must succeed.
        manager.set_applied_role_override_for_user(
            "user@example.com",
            None,
            caller_groups=None,
            caller_is_admin=False,
        )
        assert manager.get_applied_role_override_for_user("user@example.com") is None

    def test_clearing_override_is_always_allowed_for_admin(self, manager):
        manager.set_applied_role_override_for_user(
            "admin@example.com",
            None,
            caller_groups=None,
            caller_is_admin=True,
        )
        assert manager.get_applied_role_override_for_user("admin@example.com") is None

    # ------------------------------------------------------------------
    # Argument validation
    # ------------------------------------------------------------------
    def test_missing_user_email_raises(self, manager, producer_role):
        with pytest.raises(ValueError):
            manager.set_applied_role_override_for_user(
                None,
                producer_role.id,
                caller_groups=["data-producers"],
                caller_is_admin=False,
            )

    def test_unknown_role_id_raises(self, manager):
        with pytest.raises(ValueError):
            manager.set_applied_role_override_for_user(
                "user@example.com",
                "nonexistent-role-id",
                caller_groups=["data-producers"],
                caller_is_admin=False,
            )
