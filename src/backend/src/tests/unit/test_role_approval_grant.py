"""
Tests for #760/#311: approving a role access request actually grants the role.

Approval appends the requester's email to the target role's assigned_users so the
requester immediately resolves to the role's permissions; denial changes nothing.
"""
import json
import uuid
from unittest.mock import MagicMock

import pytest

from src.controller.settings_manager import SettingsManager
from src.controller.authorization_manager import AuthorizationManager
from src.db_models.settings import AppRoleDb
from src.models.settings import HandleRoleRequest
from src.common.features import FeatureAccessLevel
from src.common.config import Settings


@pytest.fixture
def manager(db_session):
    return SettingsManager(
        db=db_session,
        settings=MagicMock(spec=Settings),
        workspace_client=MagicMock(),
    )


@pytest.fixture
def consumer_role(db_session):
    """A role granting data-products READ_ONLY, with no groups/users assigned."""
    role = AppRoleDb(
        id=str(uuid.uuid4()),
        name="Data Consumer",
        description="Consumer",
        assigned_groups="[]",
        assigned_users="[]",
        feature_permissions=json.dumps({"data-products": FeatureAccessLevel.READ_ONLY.value}),
        home_sections="[]",
        approval_privileges="{}",
    )
    db_session.add(role)
    db_session.commit()
    db_session.refresh(role)
    return role


def _handle(manager, role_id, email, approved):
    return manager.handle_role_request_decision(
        db=manager._db,
        request_data=HandleRoleRequest(requester_email=email, role_id=role_id, approved=approved),
        notifications_manager=MagicMock(),
        change_log_manager=MagicMock(),
    )


def test_approval_adds_requester_to_assigned_users(manager, db_session, consumer_role):
    _handle(manager, consumer_role.id, "newuser@example.com", approved=True)

    db_session.refresh(consumer_role)
    assert json.loads(consumer_role.assigned_users) == ["newuser@example.com"]


def test_approved_user_then_resolves_to_role_permissions(manager, db_session, consumer_role):
    # Before approval: user with no groups has no access.
    auth = AuthorizationManager(settings_manager=manager)
    before = auth.get_user_effective_permissions([], user_email="newuser@example.com")
    assert before.get("data-products", FeatureAccessLevel.NONE) == FeatureAccessLevel.NONE

    _handle(manager, consumer_role.id, "newuser@example.com", approved=True)

    after = auth.get_user_effective_permissions([], user_email="newuser@example.com")
    assert after["data-products"] == FeatureAccessLevel.READ_ONLY


def test_approval_is_idempotent(manager, db_session, consumer_role):
    _handle(manager, consumer_role.id, "dup@example.com", approved=True)
    _handle(manager, consumer_role.id, "DUP@example.com", approved=True)  # different case, same user

    db_session.refresh(consumer_role)
    assert json.loads(consumer_role.assigned_users) == ["dup@example.com"]


def test_denial_does_not_grant(manager, db_session, consumer_role):
    _handle(manager, consumer_role.id, "denied@example.com", approved=False)

    db_session.refresh(consumer_role)
    assert json.loads(consumer_role.assigned_users) == []
