"""Unit tests for the per-trigger wizard permission dispatch.

Locks down the wiring between ``WIZARD_PERMISSION_DISPATCH`` (the table in
``workflows_routes.py``) and the runtime helper
``enforce_wizard_permission``. The table itself is a semantic contract —
which feature each wizard belongs to — and these tests guard against
either silently dropping a trigger row or silently widening a gate.
"""
from __future__ import annotations

import asyncio
from typing import Dict, List, Optional, Tuple
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from src.common.features import FeatureAccessLevel
from src.models.process_workflows import TriggerType
from src.models.users import UserInfo
from src.routes.workflows_routes import (
    APP_ACTION_TRIGGER_TYPES,
    WIZARD_PERMISSION_DISPATCH,
    enforce_wizard_permission,
)


# ---------------------------------------------------------------------------
# Static shape tests — guard the dispatch table itself.
# ---------------------------------------------------------------------------


def test_dispatch_covers_every_app_action_trigger() -> None:
    """Every trigger the FE can request via ``/for-trigger/`` must have an
    entry in the dispatch table, otherwise the endpoint 400s for that
    wizard even though it's a known app action."""
    missing = APP_ACTION_TRIGGER_TYPES - set(WIZARD_PERMISSION_DISPATCH)
    assert not missing, f"Triggers without a dispatch entry: {missing}"


def test_dispatch_includes_on_first_access() -> None:
    """``on_first_access`` is NOT in APP_ACTION_TRIGGER_TYPES (it's served by
    a separate user endpoint), but session creation for first-access wizards
    still flows through the dispatch — verify it's wired as authenticated-only.
    """
    assert TriggerType.ON_FIRST_ACCESS.value in WIZARD_PERMISSION_DISPATCH
    assert WIZARD_PERMISSION_DISPATCH[TriggerType.ON_FIRST_ACCESS.value] is None


def test_dispatch_keys_use_lowercase_string_values() -> None:
    """Defensive: keys must be the string values of the enum, not the
    enum members themselves, so dict.get(trigger_type_str) works."""
    for key in WIZARD_PERMISSION_DISPATCH:
        assert isinstance(key, str)
        assert key.islower() or key.startswith("for_") or key.startswith("on_")


def test_dispatch_expected_features() -> None:
    """Lock the table to its intended semantic shape so accidental
    "fix one customer issue" edits don't broaden gates without review.
    See the comment on ``WIZARD_PERMISSION_DISPATCH`` for rationale.
    """
    expected: Dict[str, Optional[Tuple[str, FeatureAccessLevel]]] = {
        TriggerType.FOR_REQUEST_ACCESS.value:        ("access-grants",  FeatureAccessLevel.READ_ONLY),
        TriggerType.FOR_SUBSCRIBE.value:             ("data-products",  FeatureAccessLevel.READ_ONLY),
        TriggerType.FOR_REQUEST_REVIEW.value:        ("data-contracts", FeatureAccessLevel.READ_ONLY),
        TriggerType.FOR_REQUEST_PUBLISH.value:       ("data-products",  FeatureAccessLevel.READ_WRITE),
        TriggerType.FOR_REQUEST_CERTIFY.value:       ("data-contracts", FeatureAccessLevel.READ_WRITE),
        TriggerType.FOR_REQUEST_STATUS_CHANGE.value: ("data-products",  FeatureAccessLevel.READ_WRITE),
        TriggerType.ON_FIRST_ACCESS.value:           None,
        # PR L — relaxed further from PR K's notifications:READ_WRITE
        # down to notifications:READ_ONLY. The outer gate's only job is
        # to confirm the caller is part of the notification system at
        # all (rejects users with notifications:None). Approving a
        # notification routed to you is read + respond, not a separate
        # "write" action on the notifications feature itself. Real
        # authorization remains the per-execution check inside
        # POST /handle-approval.
        TriggerType.FOR_APPROVAL_RESPONSE.value:     ("notifications",  FeatureAccessLevel.READ_ONLY),
    }
    assert WIZARD_PERMISSION_DISPATCH == expected


# ---------------------------------------------------------------------------
# Runtime behavior — enforce_wizard_permission.
# ---------------------------------------------------------------------------


def _user(groups: List[str], email: str = "u@example.com") -> UserInfo:
    return UserInfo(email=email, username="u", user="U", ip="127.0.0.1", groups=groups)


def _request_with_perms(
    *,
    effective: Dict[str, FeatureAccessLevel],
    applied_role_id: Optional[str] = None,
) -> MagicMock:
    """Build a mock ``Request`` whose ``app.state`` is wired to return the
    given effective permissions from ``AuthorizationManager``. Mirrors what
    PermissionChecker reads at runtime.
    """
    request = MagicMock()
    auth_manager = MagicMock()
    auth_manager.get_user_effective_permissions.return_value = effective

    def has_permission(perms, feature_id, required_level):
        level = perms.get(feature_id, FeatureAccessLevel.NONE)
        # Treat level ordering as in the production enum: ADMIN > READ_WRITE > READ_ONLY > NONE.
        order = {
            FeatureAccessLevel.NONE: 0,
            FeatureAccessLevel.READ_ONLY: 1,
            FeatureAccessLevel.READ_WRITE: 2,
            FeatureAccessLevel.ADMIN: 3,
        }
        return order.get(level, 0) >= order.get(required_level, 0)

    auth_manager.has_permission.side_effect = has_permission

    settings_manager = MagicMock()
    settings_manager.get_applied_role_override_for_user.return_value = applied_role_id
    settings_manager.get_feature_permissions_for_role_id.return_value = effective

    request.app.state.authorization_manager = auth_manager
    request.app.state.settings_manager = settings_manager
    request.app.state.teams_manager = None  # disables team-role-override path
    return request


def _run(coro):
    """Sync entry point for the async helper — avoids depending on
    ``pytest-asyncio`` which is not installed in the dev environment."""
    return asyncio.run(coro)


def test_for_request_access_consumer_with_access_grants_read_only_allowed() -> None:
    request = _request_with_perms(effective={"access-grants": FeatureAccessLevel.READ_ONLY})
    _run(enforce_wizard_permission(
        TriggerType.FOR_REQUEST_ACCESS.value, _user(["consumers"]), request
    ))


def test_for_request_access_consumer_without_access_grants_denied() -> None:
    request = _request_with_perms(effective={"access-grants": FeatureAccessLevel.NONE})
    with pytest.raises(HTTPException) as exc:
        _run(enforce_wizard_permission(
            TriggerType.FOR_REQUEST_ACCESS.value, _user(["consumers"]), request
        ))
    assert exc.value.status_code == 403


def test_for_request_certify_producer_without_contracts_denied() -> None:
    """Data Producer who has data-products:READ_WRITE but no data-contracts
    perms cannot trigger a certification wizard. Same lever a customer
    Admin would flip in the Settings UI.
    """
    request = _request_with_perms(effective={
        "data-products": FeatureAccessLevel.READ_WRITE,
        "data-contracts": FeatureAccessLevel.NONE,
    })
    with pytest.raises(HTTPException) as exc:
        _run(enforce_wizard_permission(
            TriggerType.FOR_REQUEST_CERTIFY.value, _user(["producers"]), request
        ))
    assert exc.value.status_code == 403


def test_for_request_certify_steward_allowed() -> None:
    request = _request_with_perms(effective={
        "data-contracts": FeatureAccessLevel.READ_WRITE,
    })
    _run(enforce_wizard_permission(
        TriggerType.FOR_REQUEST_CERTIFY.value, _user(["stewards"]), request
    ))


def test_on_first_access_any_authenticated_user_allowed() -> None:
    """``on_first_access`` is the first-login disclaimer — must work even
    for users with zero feature permissions. Sentinel value ``None`` in the
    dispatch table encodes this.
    """
    request = _request_with_perms(effective={})
    _run(enforce_wizard_permission(
        TriggerType.ON_FIRST_ACCESS.value, _user(["any-group"]), request
    ))


def test_for_approval_response_user_without_notifications_denied() -> None:
    """PR L — outer gate is `notifications:READ_ONLY`. A user with
    `notifications:None` is rejected at the outer gate before reaching
    the per-execution check inside POST /handle-approval. Defense-in-
    depth: a recipient-matching bug in the per-execution check still
    can't be probed by users with zero notification access."""
    request = _request_with_perms(effective={"notifications": FeatureAccessLevel.NONE})
    with pytest.raises(HTTPException) as exc:
        _run(enforce_wizard_permission(
            TriggerType.FOR_APPROVAL_RESPONSE.value, _user(["consumers"]), request
        ))
    assert exc.value.status_code == 403


def test_for_approval_response_business_owner_with_read_only_allowed() -> None:
    """PR L — non-admin Business Owner with only `notifications:READ_ONLY`
    (the typical Data Consumer / dtag-shaped role) clears the outer
    gate. Real authorization (caller is the assigned recipient of this
    execution's approval notification) happens INSIDE POST
    /handle-approval (see test_handle_approval_per_execution_check)."""
    request = _request_with_perms(effective={"notifications": FeatureAccessLevel.READ_ONLY})
    _run(enforce_wizard_permission(
        TriggerType.FOR_APPROVAL_RESPONSE.value, _user(["business-owners"]), request
    ))


def test_for_approval_response_read_write_allowed() -> None:
    """READ_WRITE still passes — strictly more permissive than the
    relaxed READ_ONLY gate. Preserves PR K's behavior for users who
    happen to have stronger notifications access."""
    request = _request_with_perms(effective={"notifications": FeatureAccessLevel.READ_WRITE})
    _run(enforce_wizard_permission(
        TriggerType.FOR_APPROVAL_RESPONSE.value, _user(["business-owners"]), request
    ))


def test_for_approval_response_admin_allowed() -> None:
    """Admin still has `notifications:ADMIN` > READ_ONLY → clears outer
    gate. Per-execution check has an admin bypass for rescue/manual
    intervention (intentional per PR K design)."""
    request = _request_with_perms(effective={"notifications": FeatureAccessLevel.ADMIN})
    _run(enforce_wizard_permission(
        TriggerType.FOR_APPROVAL_RESPONSE.value, _user(["admins"]), request
    ))


def test_for_subscribe_consumer_allowed() -> None:
    request = _request_with_perms(effective={"data-products": FeatureAccessLevel.READ_ONLY})
    _run(enforce_wizard_permission(
        TriggerType.FOR_SUBSCRIBE.value, _user(["consumers"]), request
    ))


def test_unknown_trigger_raises_400_by_default() -> None:
    request = _request_with_perms(effective={})
    with pytest.raises(HTTPException) as exc:
        _run(enforce_wizard_permission("not_a_real_trigger", _user(["any"]), request))
    assert exc.value.status_code == 400


def test_unknown_trigger_silent_when_raise_on_unknown_false() -> None:
    """Session handlers pass raise_on_unknown=False so that a 404 from the
    underlying manager surfaces instead of a misleading 400 from the
    permission layer.
    """
    request = _request_with_perms(effective={})
    # Must not raise.
    _run(enforce_wizard_permission(
        "not_a_real_trigger", _user(["any"]), request, raise_on_unknown=False
    ))


def test_user_with_no_groups_denied() -> None:
    """Same as PermissionChecker: empty groups → 403 before we touch perms."""
    request = _request_with_perms(effective={"access-grants": FeatureAccessLevel.ADMIN})
    with pytest.raises(HTTPException) as exc:
        _run(enforce_wizard_permission(
            TriggerType.FOR_REQUEST_ACCESS.value, _user(groups=[]), request
        ))
    assert exc.value.status_code == 403
