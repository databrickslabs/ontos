"""
Integration tests for issue #404 — decoupling "Ontos admin" from ``settings:ADMIN``.

These cover the three places where ``settings:ADMIN`` used to act as an
implicit admin proxy:

1. ``POST /api/user/role-override`` — admin impersonation gate.
2. ``GET /api/settings/roles`` — role catalog visibility.
3. ``GET /api/mcp-tokens`` (and siblings) — MCP token management.

After the fix, all three are gated on membership in an ``AppRole`` flagged
``is_admin=True``.
"""
import json
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from src.app import app
from src.common.authorization import get_user_details_from_sdk
from src.db_models.settings import AppRoleDb
from src.models.users import UserInfo


@pytest.fixture(autouse=True)
def _noop_audit_manager():
    """Install a no-op audit manager on ``app.state`` for routes that log actions.

    The role-override POST handler depends on AuditManagerDep, which 503s when
    ``app.state.audit_manager`` is missing — these tests don't care about the
    audit trail, so a no-op stub is sufficient.
    """
    class _NoopAudit:
        def log_action(self, **kwargs):
            return None

        def log_action_background(self, **kwargs):
            return None

    previous = getattr(app.state, "audit_manager", None)
    app.state.audit_manager = _NoopAudit()
    try:
        yield
    finally:
        if previous is not None:
            app.state.audit_manager = previous
        else:
            try:
                delattr(app.state, "audit_manager")
            except AttributeError:
                pass


def _add_role(db_session: Session, name: str, assigned_groups, is_admin: bool, feature_permissions=None) -> AppRoleDb:
    """Insert a role directly into the DB, bypassing seeding logic.

    Always uses a unique name suffix so tests can run alongside the seeded
    default roles (e.g. the seed already inserts "Data Producer").
    """
    unique_name = f"{name} (#404 test {uuid.uuid4().hex[:8]})"
    role = AppRoleDb(
        id=str(uuid.uuid4()),
        name=unique_name,
        description=f"{name} role",
        feature_permissions=json.dumps(feature_permissions or {}),
        assigned_groups=json.dumps(assigned_groups),
        home_sections="[]",
        approval_privileges="{}",
        is_admin=is_admin,
    )
    db_session.add(role)
    db_session.commit()
    db_session.refresh(role)
    return role


@pytest.fixture
def as_settings_admin(client: TestClient):
    """Swap the dependency override to a user with ONLY ``settings:ADMIN`` (no is_admin role).

    This is the exact bug scenario from #404: the user can administer Settings but
    should NOT have admin-style impersonation power.
    """
    async def _override():
        return UserInfo(
            username="settings_admin",
            email="settings_admin@example.com",
            user="settings_admin",
            ip="127.0.0.1",
            groups=["settings-admins"],
        )

    previous = app.dependency_overrides.get(get_user_details_from_sdk)
    app.dependency_overrides[get_user_details_from_sdk] = _override
    try:
        yield client
    finally:
        if previous is not None:
            app.dependency_overrides[get_user_details_from_sdk] = previous
        else:
            app.dependency_overrides.pop(get_user_details_from_sdk, None)


@pytest.fixture
def as_unprivileged(client: TestClient):
    """Override the dependency with a user who has no matching roles at all."""
    async def _override():
        return UserInfo(
            username="nobody",
            email="nobody@example.com",
            user="nobody",
            ip="127.0.0.1",
            groups=["randoms"],
        )

    previous = app.dependency_overrides.get(get_user_details_from_sdk)
    app.dependency_overrides[get_user_details_from_sdk] = _override
    try:
        yield client
    finally:
        if previous is not None:
            app.dependency_overrides[get_user_details_from_sdk] = previous
        else:
            app.dependency_overrides.pop(get_user_details_from_sdk, None)


class TestRolesEndpointScoping:
    """``GET /api/settings/roles`` returns admin's full catalog vs scoped membership."""

    def test_admin_sees_full_role_catalog(self, client: TestClient, db_session: Session):
        # Default test user has groups=["test_admins"] and the seeded "Admin" role is
        # is_admin=True with assigned_groups=["test_admins"] — i.e., they're an Ontos admin.
        producer = _add_role(db_session, "Producer Visible", ["data-producers"], is_admin=False)

        response = client.get("/api/settings/roles")
        assert response.status_code == 200
        names = {role["name"] for role in response.json()}
        # Both the seeded Admin role and the just-added test-only role must be visible.
        assert "Admin" in names
        assert producer.name in names

    def test_non_admin_sees_only_membership_matched_roles(self, as_settings_admin: TestClient, db_session: Session):
        # settings_admin is in "settings-admins" only. Create one matching role plus
        # one non-overlapping role. They must only see the matching one.
        own_role = _add_role(
            db_session,
            "Settings Admin Only",
            ["settings-admins"],
            is_admin=False,
            feature_permissions={"settings": "Admin"},
        )
        outsider = _add_role(db_session, "Outsider", ["data-producers"], is_admin=False)

        response = as_settings_admin.get("/api/settings/roles")
        assert response.status_code == 200
        names = {role["name"] for role in response.json()}
        assert names == {own_role.name}
        # Crucial: the seeded "Admin" role (assigned to test_admins) and the outsider
        # role are NOT visible to a settings-admins-only user.
        assert "Admin" not in names
        assert outsider.name not in names

    def test_user_with_no_groups_sees_empty_list(self, db_session: Session, client: TestClient):
        # Override to a user with no groups at all.
        async def _override():
            return UserInfo(
                username="groupless",
                email="groupless@example.com",
                user="groupless",
                ip="127.0.0.1",
                groups=[],
            )
        previous = app.dependency_overrides.get(get_user_details_from_sdk)
        app.dependency_overrides[get_user_details_from_sdk] = _override
        try:
            response = client.get("/api/settings/roles")
            assert response.status_code == 200
            assert response.json() == []
        finally:
            if previous is not None:
                app.dependency_overrides[get_user_details_from_sdk] = previous
            else:
                app.dependency_overrides.pop(get_user_details_from_sdk, None)


class TestRoleOverrideAdminGate:
    """``POST /api/user/role-override`` — caller_is_admin is now driven by is_admin role."""

    def test_settings_admin_cannot_impersonate_non_member_role(self, as_settings_admin: TestClient, db_session: Session):
        # User in "settings-admins" with settings:ADMIN but NOT in any is_admin role.
        # Adding the role they belong to (so the role exists) plus a target they don't.
        _add_role(
            db_session,
            "Settings Admin",
            ["settings-admins"],
            is_admin=False,
            feature_permissions={"settings": "Admin"},
        )
        target = _add_role(db_session, "Foreign Producer", ["data-producers"], is_admin=False)

        response = as_settings_admin.post(
            "/api/user/role-override",
            json={"role_id": str(target.id)},
        )
        # Before the fix, this would have returned 200 because settings:ADMIN bypassed
        # membership validation. After the fix, the user must be in an is_admin role.
        assert response.status_code == 403

    def test_ontos_admin_can_impersonate_any_role(self, client: TestClient, db_session: Session):
        # Default user (groups=["test_admins"]) is in the seeded is_admin Admin role.
        target = _add_role(db_session, "Producer Target", ["data-producers"], is_admin=False)

        response = client.post(
            "/api/user/role-override",
            json={"role_id": str(target.id)},
        )
        assert response.status_code == 200

    def test_clearing_override_is_always_allowed(self, as_unprivileged: TestClient):
        # Even users with no privileges may clear their own override.
        response = as_unprivileged.post(
            "/api/user/role-override",
            json={"role_id": None},
        )
        assert response.status_code == 200


class TestMcpTokensAdminGate:
    """MCP token management is gated on Ontos admin (is_admin role membership)."""

    def test_admin_can_list_tokens(self, client: TestClient):
        response = client.get("/api/mcp-tokens")
        assert response.status_code == 200

    def test_settings_admin_cannot_list_tokens(self, as_settings_admin: TestClient, db_session: Session):
        _add_role(
            db_session,
            "Settings Admin MCP",
            ["settings-admins"],
            is_admin=False,
            feature_permissions={"settings": "Admin"},
        )
        response = as_settings_admin.get("/api/mcp-tokens")
        assert response.status_code == 403

    def test_unprivileged_user_cannot_list_tokens(self, as_unprivileged: TestClient):
        response = as_unprivileged.get("/api/mcp-tokens")
        assert response.status_code == 403
