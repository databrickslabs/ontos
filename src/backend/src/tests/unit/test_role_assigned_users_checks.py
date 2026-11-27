"""Role checks that must count a role assigned by user, not only by group (#1713 review).

``role_matches`` is the one rule: groups intersect, or the email is in ``assigned_users``
(stripped, case-insensitive). The approval privileges, the deployment policy, the chat role
label and the canonical role follow it.
"""
import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest
from fastapi import HTTPException

from src.common.authorization import ApprovalChecker
from src.controller.authorization_manager import normalize_email, role_matches
from src.controller.deployment_policy_manager import DeploymentPolicyManager
from src.controller.settings_manager import SettingsManager
from src.models.settings import AppRole, DeploymentPolicy
from src.models.users import UserInfo
from src.routes.llm_search_routes import _derive_effective_role_label

BOSS = "boss@example.com"


def _user(email=BOSS, groups=None):
    return UserInfo(email=email, username="u", user="u", ip="127.0.0.1", groups=groups or [])


def _ns_role(users, groups=(), **extra):
    return SimpleNamespace(
        id=uuid.uuid4(), name="R", assigned_groups=list(groups), assigned_users=users, **extra
    )


class TestRoleMatches:
    @pytest.mark.parametrize(
        "stored", ["boss@example.com", "  Boss@Example.com ", "BOSS@EXAMPLE.COM"]
    )
    def test_user_assignment_is_stripped_and_case_insensitive(self, stored):
        email = normalize_email(" Boss@example.com")
        assert role_matches(_ns_role([stored]), set(), email) is True

    def test_other_email_and_missing_email_do_not_match(self):
        role = _ns_role([BOSS])
        assert role_matches(role, set(), normalize_email("other@example.com")) is False
        assert role_matches(role, set(), normalize_email(None)) is False

    def test_dirty_entries_are_ignored(self):
        assert role_matches(_ns_role([None, " "]), set(), normalize_email(BOSS)) is False


class TestApprovalChecker:
    @staticmethod
    def _check(roles, user):
        settings_manager = Mock()
        settings_manager.get_applied_role_override_for_user.return_value = None
        settings_manager.list_app_roles.return_value = roles
        return asyncio.run(ApprovalChecker("CONTRACTS")(MagicMock(), user, settings_manager))

    def test_approval_privilege_of_a_role_assigned_by_user(self):
        role = _ns_role(["Boss@Example.com "], approval_privileges={"CONTRACTS": True})
        assert self._check([role], _user()) is None

    def test_other_user_is_still_refused(self):
        role = _ns_role([BOSS], approval_privileges={"CONTRACTS": True})
        with pytest.raises(HTTPException) as exc:
            self._check([role], _user("other@example.com"))
        assert exc.value.status_code == 403


class TestDeploymentPolicy:
    def test_policy_of_a_role_assigned_by_user(self):
        settings_manager = Mock()
        settings_manager.get_applied_role_override_for_user.return_value = None
        policy = DeploymentPolicy(
            allowed_catalogs=["dev_catalog"], allowed_schemas=["*"],
            require_approval=False, can_approve_deployments=False,
        )
        settings_manager.list_app_roles.return_value = [
            _ns_role(["Boss@Example.com "], deployment_policy=policy)
        ]

        effective = DeploymentPolicyManager(settings_manager).get_effective_policy(_user())

        assert effective.allowed_catalogs == ["dev_catalog"]


class TestChatRoleLabel:
    def test_label_of_a_role_assigned_by_user(self):
        request = MagicMock()
        role = SimpleNamespace(
            id=uuid.uuid4(), name="Steward", assigned_groups=[],
            assigned_users=[" Boss@example.com"],
        )
        request.app.state.settings_manager.list_app_roles.return_value = [role]
        request.app.state.settings_manager.get_applied_role_override_for_user.return_value = None

        assert _derive_effective_role_label(request, _user()) == "Steward"


class TestCanonicalRole:
    def test_canonical_role_of_a_user_holding_a_role_only_by_user(self):
        by_user = AppRole(
            id=uuid.uuid4(), name="Steward", description=None, assigned_groups=["x"],
            assigned_users=[BOSS], feature_permissions={"data-contracts": "Read/Write"},
            home_sections=[], approval_privileges={},
        )
        other = AppRole(
            id=uuid.uuid4(), name="Other", description=None, assigned_groups=["y"],
            assigned_users=[], feature_permissions={}, home_sections=[], approval_privileges={},
        )
        manager = SettingsManager.__new__(SettingsManager)
        manager.list_app_roles = lambda: [other, by_user]

        assert manager.get_canonical_role_for_groups(["z"], BOSS).name == "Steward"
        assert manager.get_canonical_role_for_groups(["z"]).name == "Other"
        assert manager.get_canonical_role_for_groups([]) is None
