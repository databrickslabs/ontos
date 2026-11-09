"""
Unit tests for individual-user (assigned_users) role matching (#196/#760).

A role matches a user if the user's groups intersect assigned_groups OR the
user's email is in assigned_users (case-insensitive, OR-combined).
"""
import uuid
from unittest.mock import Mock

import pytest

from src.controller.authorization_manager import AuthorizationManager
from src.models.settings import AppRole
from src.common.features import FeatureAccessLevel


@pytest.fixture
def manager():
    return AuthorizationManager(settings_manager=Mock())


def _role(**kwargs):
    base = dict(
        id=uuid.uuid4(),
        name="Steward",
        description=None,
        assigned_groups=[],
        assigned_users=[],
        feature_permissions={"data-contracts": FeatureAccessLevel.READ_WRITE},
        home_sections=[],
        approval_privileges={},
    )
    base.update(kwargs)
    return AppRole(**base)


def test_email_only_match_grants_permissions(manager):
    role = _role(assigned_users=["alice@example.com"])
    manager._settings_manager.list_app_roles.return_value = [role]

    result = manager.get_user_effective_permissions([], user_email="alice@example.com")
    assert result["data-contracts"] == FeatureAccessLevel.READ_WRITE


def test_email_match_is_case_insensitive(manager):
    role = _role(assigned_users=["alice@example.com"])
    manager._settings_manager.list_app_roles.return_value = [role]

    result = manager.get_user_effective_permissions([], user_email="Alice@Example.COM")
    assert result["data-contracts"] == FeatureAccessLevel.READ_WRITE


def test_group_only_still_matches(manager):
    role = _role(assigned_groups=["stewards"], assigned_users=[])
    manager._settings_manager.list_app_roles.return_value = [role]

    result = manager.get_user_effective_permissions(["stewards"], user_email="nobody@example.com")
    assert result["data-contracts"] == FeatureAccessLevel.READ_WRITE


def test_no_group_and_no_email_match_yields_none(manager):
    role = _role(assigned_groups=["stewards"], assigned_users=["alice@example.com"])
    manager._settings_manager.list_app_roles.return_value = [role]

    result = manager.get_user_effective_permissions(["other"], user_email="bob@example.com")
    assert all(level == FeatureAccessLevel.NONE for level in result.values())


def test_effective_role_ids_includes_email_assignment(manager):
    role = _role(assigned_users=["alice@example.com"])
    manager._settings_manager.list_app_roles.return_value = [role]

    ids = manager.get_user_effective_role_ids([], user_email="alice@example.com")
    assert ids == {str(role.id)}


def test_effective_role_ids_empty_without_group_or_email(manager):
    role = _role(assigned_users=["alice@example.com"])
    manager._settings_manager.list_app_roles.return_value = [role]

    assert manager.get_user_effective_role_ids([], user_email=None) == set()
