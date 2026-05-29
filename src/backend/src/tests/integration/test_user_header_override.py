"""Integration tests for the per-request test-user header override.

Covers the headers introduced for runtime persona switching:

  - ``X-Test-Token``            : shared-secret gate (matches ``TEST_USER_TOKEN``)
  - ``X-Test-User-Email``       : impersonated identity (required)
  - ``X-Test-User-Groups``      : optional explicit groups (JSON or CSV)
  - ``X-Test-User-{Username,Name,Ip}`` : optional refinements

These tests bypass the default ``get_user_details_from_sdk`` dependency override
so the real header-parsing path runs end-to-end.
"""
from __future__ import annotations

import json
from typing import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from src.app import app
from src.common.authorization import (
    TEST_TOKEN_HEADER,
    TEST_USER_EMAIL_HEADER,
    TEST_USER_GROUPS_HEADER,
    TEST_USER_USERNAME_HEADER,
    get_user_details_from_sdk,
)
from src.common.config import Settings, get_settings
from src.common.manager_dependencies import get_users_manager
from src.models.users import UserInfo


TEST_TOKEN = "integration-test-token-do-not-use-in-prod"


@pytest.fixture
def client_with_test_token(client: TestClient, test_settings: Settings) -> Iterator[TestClient]:
    """Yield a TestClient whose backend accepts X-Test-Token = TEST_TOKEN.

    Removes the default ``get_user_details_from_sdk`` override installed by the
    ``client`` fixture so the real resolver runs and the header path is
    exercised. Restores everything on teardown.
    """
    # Mutate the in-place test_settings so dependent code sees the token.
    object.__setattr__(test_settings, "TEST_USER_TOKEN", TEST_TOKEN)

    # Override get_settings so get_user_details_from_sdk sees TEST_USER_TOKEN.
    def _override_settings() -> Settings:
        return test_settings

    # Provide a stub UsersManager so SCIM fallback doesn't try to hit the wire
    # when X-Test-User-Groups is omitted. We don't exercise that path here;
    # tests below explicitly pass the groups header.
    class _StubUsersManager:
        def get_user_details_by_email(self, user_email: str, real_ip=None) -> UserInfo:
            return UserInfo(
                email=user_email,
                username=user_email,
                user=user_email,
                ip=real_ip,
                groups=["scim-fallback-group"],
            )

    def _override_users_manager() -> _StubUsersManager:
        return _StubUsersManager()

    prev_settings = app.dependency_overrides.get(get_settings)
    prev_users = app.dependency_overrides.get(get_users_manager)
    prev_user_details = app.dependency_overrides.pop(get_user_details_from_sdk, None)

    app.dependency_overrides[get_settings] = _override_settings
    app.dependency_overrides[get_users_manager] = _override_users_manager

    try:
        yield client
    finally:
        object.__setattr__(test_settings, "TEST_USER_TOKEN", None)
        if prev_settings is not None:
            app.dependency_overrides[get_settings] = prev_settings
        else:
            app.dependency_overrides.pop(get_settings, None)
        if prev_users is not None:
            app.dependency_overrides[get_users_manager] = prev_users
        else:
            app.dependency_overrides.pop(get_users_manager, None)
        if prev_user_details is not None:
            app.dependency_overrides[get_user_details_from_sdk] = prev_user_details


class TestPositivePath:
    """Headers carry through and shape the resolved user identity."""

    def test_groups_in_header_used_verbatim(self, client_with_test_token: TestClient):
        response = client_with_test_token.get(
            "/api/user/details",
            headers={
                TEST_TOKEN_HEADER: TEST_TOKEN,
                TEST_USER_EMAIL_HEADER: "producer@test.local",
                TEST_USER_GROUPS_HEADER: '["data-producers","another-group"]',
                TEST_USER_USERNAME_HEADER: "producer",
            },
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["email"] == "producer@test.local"
        assert payload["username"] == "producer"
        # Order doesn't matter, but contents must match.
        assert sorted(payload["groups"]) == sorted(["data-producers", "another-group"])

    def test_groups_header_csv_form(self, client_with_test_token: TestClient):
        response = client_with_test_token.get(
            "/api/user/details",
            headers={
                TEST_TOKEN_HEADER: TEST_TOKEN,
                TEST_USER_EMAIL_HEADER: "csv@test.local",
                TEST_USER_GROUPS_HEADER: "alpha, beta,  gamma",
            },
        )
        assert response.status_code == 200
        assert sorted(response.json()["groups"]) == ["alpha", "beta", "gamma"]

    def test_no_groups_header_falls_back_to_scim(self, client_with_test_token: TestClient):
        # X-Test-User-Groups omitted -> backend calls UsersManager.get_user_details_by_email,
        # which our stub returns with groups=["scim-fallback-group"].
        response = client_with_test_token.get(
            "/api/user/details",
            headers={
                TEST_TOKEN_HEADER: TEST_TOKEN,
                TEST_USER_EMAIL_HEADER: "scim@test.local",
            },
        )
        assert response.status_code == 200
        assert response.json()["groups"] == ["scim-fallback-group"]

    def test_personas_endpoint_returns_yaml(self, client_with_test_token: TestClient):
        response = client_with_test_token.get("/api/test/personas")
        assert response.status_code == 200
        body = response.json()
        ids = {p["id"] for p in body["personas"]}
        assert {"admin", "consumer", "producer"}.issubset(ids)
        assert body["headers"]["token"] == TEST_TOKEN_HEADER
        assert body["headers"]["email"] == TEST_USER_EMAIL_HEADER


class TestPermissionsRespectOverride:
    """Persona's groups should drive role-based permissions for the same session."""

    def test_admin_persona_gets_admin_perms(self, client_with_test_token: TestClient):
        # The seeded "Admin" role in tests is assigned to APP_ADMIN_DEFAULT_GROUPS,
        # which test_settings sets to ["test_admins"]. So sending that group as the
        # persona's groups should yield non-empty permissions including Admin level.
        response = client_with_test_token.get(
            "/api/user/permissions",
            headers={
                TEST_TOKEN_HEADER: TEST_TOKEN,
                TEST_USER_EMAIL_HEADER: "header-admin@test.local",
                TEST_USER_GROUPS_HEADER: '["test_admins"]',
            },
        )
        assert response.status_code == 200
        perms = response.json()
        # Admin role should grant ADMIN access to at least one feature
        # (the seeding logic generally gives Admin everything).
        assert any(level == "Admin" for level in perms.values()), perms

    def test_unknown_groups_yield_empty_perms(self, client_with_test_token: TestClient):
        response = client_with_test_token.get(
            "/api/user/permissions",
            headers={
                TEST_TOKEN_HEADER: TEST_TOKEN,
                TEST_USER_EMAIL_HEADER: "nobody@test.local",
                TEST_USER_GROUPS_HEADER: '["totally-unmatched-group"]',
            },
        )
        assert response.status_code == 200
        # PermissionChecker returns {} for users with groups but no matching role.
        # /api/user/permissions itself returns {} when groups list is empty,
        # so the only thing we strictly require is a successful 200 with no
        # ADMIN entry leaking through.
        perms = response.json()
        assert "Admin" not in perms.values()


class TestNegativePath:
    """Misuse must fail loudly rather than silently bypass auth."""

    def test_missing_email_returns_400(self, client_with_test_token: TestClient):
        response = client_with_test_token.get(
            "/api/user/details",
            headers={TEST_TOKEN_HEADER: TEST_TOKEN},
        )
        # Token matched but email missing -> 400 (caller clearly intended to
        # override and we don't want to silently fall through to mock-user mode).
        assert response.status_code == 400
        assert TEST_USER_EMAIL_HEADER in response.json()["detail"]

    def test_wrong_token_is_ignored(self, client_with_test_token: TestClient):
        # With a wrong token, the override helper returns None and the resolver
        # falls through to the normal identity path. The CRITICAL property here
        # is security: the X-Test-User-Email value must NOT become the
        # resolved identity. The status code is incidental — the resolver may
        # 400 (missing X-Forwarded-Email) or 200 (synthesized from stub), but
        # in no case may the email match the attempted impersonation.
        response = client_with_test_token.get(
            "/api/user/details",
            headers={
                TEST_TOKEN_HEADER: "definitely-not-the-real-token",
                TEST_USER_EMAIL_HEADER: "tricky@test.local",
                TEST_USER_GROUPS_HEADER: '["admins"]',
            },
        )
        if response.status_code == 200:
            assert response.json().get("email") != "tricky@test.local"
        else:
            # Any non-200 is also acceptable — it means the wrong-token
            # request was rejected by some downstream check rather than
            # being silently honored.
            assert response.status_code in (400, 401, 403, 404, 500)


class TestFeatureDisabled:
    """When TEST_USER_TOKEN is unset, the headers must be inert."""

    def test_personas_endpoint_404_when_token_unset(self, client: TestClient):
        # The default client fixture doesn't set TEST_USER_TOKEN; the endpoint must 404.
        response = client.get("/api/test/personas")
        assert response.status_code == 404

    def test_headers_ignored_when_token_unset(self, client: TestClient):
        # Default client still has the get_user_details_from_sdk override active,
        # but even if it didn't, the helper would refuse to honor any header
        # when TEST_USER_TOKEN is None. The user should remain the seeded
        # mock_test_user from conftest.
        response = client.get(
            "/api/user/details",
            headers={
                TEST_TOKEN_HEADER: "anything",
                TEST_USER_EMAIL_HEADER: "should-be-ignored@test.local",
                TEST_USER_GROUPS_HEADER: '["admins"]',
            },
        )
        assert response.status_code == 200
        # Identity must NOT be the impersonated one.
        assert response.json()["email"] != "should-be-ignored@test.local"
