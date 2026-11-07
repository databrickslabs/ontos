"""PermissionChecker, enforce_feature_permission and is_user_feature_admin resolve
a caller's feature level the same way (one resolve_effective_permissions).

Precedence: an applied role override wins, else the team role override and the
roles matching the groups or the email are merged. The expectations are the
REST behaviour before the three were made to share one resolver.
"""
import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.common import authorization
from src.common.authorization import (
    PermissionChecker,
    enforce_feature_permission,
    is_user_feature_admin,
)
from src.common.features import ACCESS_LEVEL_ORDER, FeatureAccessLevel
from src.models.users import UserInfo

RO = FeatureAccessLevel.READ_ONLY
RW = FeatureAccessLevel.READ_WRITE
ADMIN = FeatureAccessLevel.ADMIN
NONE = FeatureAccessLevel.NONE
FEATURE = 'data-products'


class _Auth:
    """Group/email/team roles: producers -> RW, team role 'Team Admin' -> Admin,
    direct@example.com assigned by email -> Admin."""

    def get_user_effective_permissions(self, groups, team_role_override=None, user_email=None):
        if team_role_override == 'Team Admin':
            return {FEATURE: ADMIN}
        if 'producers' in (groups or []):
            return {FEATURE: RW}
        if user_email == 'direct@example.com':
            return {FEATURE: ADMIN}
        return {}

    def has_permission(self, eff, feature_id, required_level):
        level = eff.get(feature_id, NONE)
        return ACCESS_LEVEL_ORDER[level] >= ACCESS_LEVEL_ORDER[required_level]


class _Settings:
    def get_applied_role_override_for_user(self, email):
        return 'role-ro' if email == 'override@example.com' else None

    def get_feature_permissions_for_role_id(self, role_id):
        return {FEATURE: RO}


CASES = [
    # email, groups, team role override, expected level
    ('override@example.com', ['producers'], 'Team Admin', RO),  # role override wins
    ('team@example.com', ['nobody'], 'Team Admin', ADMIN),       # team role
    ('prod@example.com', ['producers'], None, RW),               # groups
    ('direct@example.com', ['nobody'], None, ADMIN),             # email assignment
    ('none@example.com', ['nobody'], None, NONE),
]


def _run(coro):
    return asyncio.run(coro)


@pytest.mark.parametrize('email, groups, team_role, expected', CASES)
def test_the_three_checks_agree(monkeypatch, email, groups, team_role, expected):
    async def _team(user_identifier, user_groups, request):
        return team_role

    monkeypatch.setattr(authorization, 'get_user_team_role_overrides', _team)
    auth = _Auth()
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        authorization_manager=auth, settings_manager=_Settings())))
    user = UserInfo(email=email, username=email, user=email, ip=None, groups=groups)

    for required in (RO, RW, ADMIN):
        allowed = ACCESS_LEVEL_ORDER[expected] >= ACCESS_LEVEL_ORDER[required]
        checker = PermissionChecker(FEATURE, required)
        for check in (
            lambda: checker(request, user_details=user, auth_manager=auth),
            lambda: enforce_feature_permission(FEATURE, required, user, request),
        ):
            if allowed:
                _run(check())
            else:
                with pytest.raises(HTTPException) as exc_info:
                    _run(check())
                assert exc_info.value.status_code == 403

    is_admin = _run(is_user_feature_admin(email, groups, FEATURE, request))
    assert is_admin is (expected == ADMIN)
