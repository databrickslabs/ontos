"""Team role overrides combine with the user's other roles (#1245).

- A team override adds to the user's group and email roles, per feature by the
  highest level, instead of replacing them.
- Every team entry that applies to the user counts: their own entry, and the entries
  for their groups, also in teams they belong to only through a group.
- An applied role override ("act as role") still replaces everything.
- ``/api/user/permissions`` reports what ``PermissionChecker`` enforces.
- Assigning an override can't grant more than the actor holds.
"""
import itertools
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from src.common import authorization
from src.common.authorization import (
    PermissionChecker,
    get_user_details_from_sdk,
    resolve_effective_permissions,
)
from src.common.features import ACCESS_LEVEL_ORDER, FeatureAccessLevel, get_feature_config
from src.common.manager_dependencies import get_auth_manager, get_settings_manager
from src.common.team_role_override import team_role_overrides
from src.controller.authorization_manager import AuthorizationManager
from src.models.settings import AppRole
from src.models.users import UserInfo

L = FeatureAccessLevel
FEATURES = ["teams", "settings", "data-products", "data-contracts", "data-domains"]


def _role(name, groups=(), users=(), **perms):
    return AppRole(
        id=uuid.uuid4(), name=name, description=name,
        assigned_groups=list(groups), assigned_users=list(users),
        feature_permissions={k.replace("_", "-"): v for k, v in perms.items()},
        home_sections=[], approval_privileges={},
    )


ROLES = [
    _role("Admin", groups=["admins"], teams=L.ADMIN, settings=L.ADMIN, data_products=L.ADMIN,
          data_contracts=L.ADMIN, data_domains=L.ADMIN),
    _role("Data Steward", groups=["data-stewards"], teams=L.READ_ONLY, data_products=L.READ_WRITE,
          data_contracts=L.READ_WRITE, data_domains=L.READ_WRITE),
    _role("Data Producer", groups=["data-producers"], teams=L.READ_WRITE, data_products=L.READ_WRITE,
          data_contracts=L.READ_WRITE, data_domains=L.READ_ONLY),
    _role("Data Consumer", groups=["data-consumers"], teams=L.READ_ONLY, data_products=L.READ_ONLY,
          data_contracts=L.READ_ONLY, data_domains=L.READ_ONLY),
]


@pytest.fixture
def auth():
    settings = MagicMock()
    settings.list_app_roles.return_value = ROLES
    return AuthorizationManager(settings_manager=settings)


def _team(*members):
    return SimpleNamespace(members=[
        SimpleNamespace(member_identifier=i, app_role_override=o) for i, o in members
    ])


class TestMerge:
    def test_team_override_adds_to_group_roles(self, auth):
        perms = auth.get_user_effective_permissions(["data-producers"], ["Data Steward"])

        assert perms["data-domains"] == L.READ_WRITE   # from the team role
        assert perms["teams"] == L.READ_WRITE          # kept from the group role

    def test_lower_team_override_never_downgrades(self, auth):
        perms = auth.get_user_effective_permissions(["admins"], ["Data Consumer"])

        assert all(perms[f] == L.ADMIN for f in FEATURES)

    def test_several_overrides_merge_by_highest(self, auth):
        perms = auth.get_user_effective_permissions([], ["Data Consumer", "Data Producer", "Data Steward"])

        assert perms["teams"] == L.READ_WRITE
        assert perms["data-domains"] == L.READ_WRITE
        assert perms["data-products"] == L.READ_WRITE

    def test_override_alone_grants_its_role(self, auth):
        assert auth.get_user_effective_permissions([], "Admin")["settings"] == L.ADMIN

    def test_unknown_override_is_ignored(self, auth):
        perms = auth.get_user_effective_permissions(["data-consumers"], ["Nope"])

        assert perms["data-products"] == L.READ_ONLY

    def test_never_lower_than_before(self, auth):
        """The old resolution (override replaces groups) never yields a higher level."""
        def old(groups, override):
            if override and any(r.name == override for r in ROLES):
                return auth.get_user_effective_permissions([], [override])
            return auth.get_user_effective_permissions(groups, None)

        group_sets = [[], ["admins"], ["data-consumers"], ["data-producers", "data-stewards"]]
        for groups, override in itertools.product(group_sets, [None, "Admin", "Data Consumer", "Data Steward", "Nope"]):
            before, after = old(groups, override), auth.get_user_effective_permissions(groups, [override] if override else None)
            for feature in get_feature_config():
                assert ACCESS_LEVEL_ORDER[after[feature]] >= ACCESS_LEVEL_ORDER[before[feature]], (groups, override, feature)


class TestTeamRoleOverrides:
    def test_group_entry_applies_to_group_members(self):
        teams = [_team(("data-consumers", "Data Steward"))]

        assert team_role_overrides(teams, "alice@example.com", ["data-consumers"]) == ["Data Steward"]

    def test_every_matching_entry_counts(self):
        teams = [
            _team(("Alice@Example.com", "Data Producer"), ("data-consumers", "Data Steward")),
            _team(("data-consumers", "Data Producer"), ("bob@example.com", "Admin")),
        ]

        # The user's own entries first, then the group entries.
        assert team_role_overrides(teams, "alice@example.com", ["Data-Consumers"]) == ["Data Producer", "Data Steward"]

    def test_own_entry_comes_before_group_entries(self):
        teams = [_team(("eng", "Data Consumer")), _team(("alice@example.com", "Data Steward"))]

        assert team_role_overrides(teams, "alice@example.com", ["eng"]) == ["Data Steward", "Data Consumer"]

    def test_entries_without_override_or_for_others_are_ignored(self):
        teams = [_team(("alice@example.com", None), ("other-group", "Admin"), ("bob@example.com", "Admin"))]

        assert team_role_overrides(teams, "alice@example.com", ["data-consumers"]) == []


def _request(teams_by_user, applied=None):
    """A request whose app state resolves teams from ``teams_by_user``: {identifier/group: [team, ...]}."""
    teams_manager = MagicMock()

    def get_teams_for_user(db, identifier, groups=None):
        keys = [identifier.lower()] + [g.lower() for g in groups or []]
        seen, out = set(), []
        for key in keys:
            for team in teams_by_user.get(key, []):
                if id(team) not in seen:
                    seen.add(id(team))
                    out.append(team)
        return out

    teams_manager.get_team_rows_for_user.side_effect = get_teams_for_user
    settings_manager = MagicMock()
    settings_manager.get_applied_role_override_for_user.return_value = applied
    settings_manager.get_feature_permissions_for_role_id.side_effect = (
        lambda role_id: next(r.feature_permissions for r in ROLES if str(r.id) == role_id)
    )
    state = SimpleNamespace(teams_manager=teams_manager, settings_manager=settings_manager)
    return SimpleNamespace(app=SimpleNamespace(state=state), state=SimpleNamespace())


@pytest.fixture(autouse=True)
def _no_real_db(monkeypatch):
    def fake_get_db():
        yield MagicMock()
    monkeypatch.setattr(authorization, "get_db", fake_get_db)


class TestResolver:
    def test_group_only_team_membership_grants_the_override(self, auth):
        team = _team(("data-consumers", "Data Steward"))
        request = _request({"data-consumers": [team]})

        perms = resolve_effective_permissions(request, "alice@example.com", ["data-consumers"], auth)

        assert perms["data-domains"] == L.READ_WRITE

    def test_applied_role_override_still_replaces(self, auth):
        team = _team(("alice@example.com", "Admin"))
        consumer = next(r for r in ROLES if r.name == "Data Consumer")
        request = _request({"alice@example.com": [team]}, applied=str(consumer.id))

        perms = resolve_effective_permissions(request, "alice@example.com", ["admins"], auth)

        assert perms.get("settings", L.NONE) == L.NONE
        assert perms["teams"] == L.READ_ONLY

    def test_without_applied_override_option(self, auth):
        team = _team(("alice@example.com", "Admin"))
        consumer = next(r for r in ROLES if r.name == "Data Consumer")
        request = _request({"alice@example.com": [team]}, applied=str(consumer.id))

        perms = resolve_effective_permissions(
            request, "alice@example.com", [], auth, apply_role_override=False,
        )

        assert perms["settings"] == L.ADMIN

    def test_resolved_once_per_request(self, auth):
        request = _request({})
        first = resolve_effective_permissions(request, "alice@example.com", ["data-consumers"], auth)
        second = resolve_effective_permissions(request, "alice@example.com", ["data-consumers"], auth)

        assert first is second
        assert request.app.state.teams_manager.get_team_rows_for_user.call_count == 1

    def test_team_lookup_failure_grants_nothing_extra(self, auth):
        request = _request({})
        request.app.state.teams_manager.get_team_rows_for_user.side_effect = RuntimeError("db down")

        perms = resolve_effective_permissions(request, "alice@example.com", ["data-consumers"], auth)

        assert perms["data-products"] == L.READ_ONLY


class TestPermissionsEndpointMatchesEnforcement:
    """``/api/user/permissions`` must report exactly what ``PermissionChecker`` enforces."""

    SETUPS = {
        "admin only through a team (the #1245 repro)": (["data-consumers"], {"u@example.com": [_team(("u@example.com", "Admin"))]}),
        "group-only team member": (["data-consumers"], {"data-consumers": [_team(("data-consumers", "Data Steward"))]}),
        "admin with a lower team role": (["admins"], {"u@example.com": [_team(("u@example.com", "Data Consumer"))]}),
        "two teams": (["data-producers"], {"u@example.com": [_team(("u@example.com", "Data Consumer"))],
                                            "data-producers": [_team(("data-producers", "Data Steward"))]}),
        "no team": (["data-consumers"], {}),
    }

    @pytest.mark.parametrize("setup", list(SETUPS))
    def test_matrix(self, auth, setup):
        from src.routes import user_routes

        groups, teams = self.SETUPS[setup]
        request_like = _request(teams)
        app = FastAPI()
        app.state.teams_manager = request_like.app.state.teams_manager
        app.state.settings_manager = request_like.app.state.settings_manager
        app.state.authorization_manager = auth
        app.include_router(user_routes.router)

        for feature, level in itertools.product(FEATURES, [L.READ_ONLY, L.READ_WRITE, L.ADMIN]):
            app.add_api_route(
                f"/probe/{feature}/{level.name}", lambda: {"ok": True},
                dependencies=[Depends(PermissionChecker(feature, level))],
            )

        async def _user():
            return UserInfo(email="u@example.com", username="u", user="U", ip="127.0.0.1", groups=groups)

        app.dependency_overrides[get_user_details_from_sdk] = _user
        app.dependency_overrides[get_auth_manager] = lambda: auth
        app.dependency_overrides[get_settings_manager] = lambda: app.state.settings_manager
        client = TestClient(app)

        reported = client.get("/api/user/permissions").json()
        for feature, level in itertools.product(FEATURES, [L.READ_ONLY, L.READ_WRITE, L.ADMIN]):
            allowed = client.get(f"/probe/{feature}/{level.name}").status_code == 200
            expected = ACCESS_LEVEL_ORDER[L(reported[feature])] >= ACCESS_LEVEL_ORDER[level]
            assert allowed == expected, (setup, feature, level, reported[feature])

        if setup.startswith("admin only"):
            assert reported["settings"] == L.ADMIN.value


class TestNavigation:
    """Menus follow the same role set, so a team role can show what a group role hides."""

    def test_team_role_shows_a_feature_the_group_role_hides(self):
        consumer = _role("Data Consumer", groups=["data-consumers"], data_products=L.READ_ONLY)
        consumer.hidden_nav_features = ["data-products"]
        steward = _role("Data Steward", data_products=L.READ_WRITE)
        settings = MagicMock()
        settings.list_app_roles.return_value = [consumer, steward]
        auth = AuthorizationManager(settings_manager=settings)

        assert "data-products" in auth.get_user_hidden_nav_features(["data-consumers"])
        assert "data-products" not in auth.get_user_hidden_nav_features(
            ["data-consumers"], team_role_names=["Data Steward"],
        )

    def test_team_admin_role_hides_nothing(self):
        consumer = _role("Data Consumer", groups=["data-consumers"], data_products=L.READ_ONLY)
        consumer.hidden_nav_features = ["data-products"]
        admin = _role("Admin", settings=L.ADMIN)
        admin.is_admin = True
        settings = MagicMock()
        settings.list_app_roles.return_value = [consumer, admin]
        auth = AuthorizationManager(settings_manager=settings)

        assert auth.get_user_hidden_nav_features(["data-consumers"], team_role_names=["Admin"]) == []
