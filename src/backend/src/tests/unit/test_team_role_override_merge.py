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
    effective_permissions_for_request,
    get_user_details_from_sdk,
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
    """A team whose entries are users when the identifier has an ``@``, else groups."""
    return SimpleNamespace(members=[
        SimpleNamespace(member_identifier=i, app_role_override=o, member_type="user" if "@" in i else "group")
        for i, o in members
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

    def test_a_user_entry_named_like_a_group_does_not_apply_to_the_group(self):
        team = SimpleNamespace(members=[
            SimpleNamespace(member_identifier="data-consumers", app_role_override="Admin", member_type="user"),
        ])

        assert team_role_overrides([team], "alice@example.com", ["data-consumers"]) == []

    def test_a_group_entry_named_like_the_user_does_not_apply_as_the_users_own(self):
        team = SimpleNamespace(members=[
            SimpleNamespace(member_identifier="alice@example.com", app_role_override="Admin", member_type="group"),
        ])

        assert team_role_overrides([team], "alice@example.com", []) == []

    def test_member_type_enum_values_are_understood(self):
        from src.models.teams import MemberType

        team = SimpleNamespace(members=[
            SimpleNamespace(member_identifier="data-consumers", app_role_override="Data Steward", member_type=MemberType.GROUP),
        ])

        assert team_role_overrides([team], "alice@example.com", ["data-consumers"]) == ["Data Steward"]

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

        perms = effective_permissions_for_request(request, "alice@example.com", ["data-consumers"], auth)

        assert perms["data-domains"] == L.READ_WRITE

    def test_applied_role_override_still_replaces(self, auth):
        team = _team(("alice@example.com", "Admin"))
        consumer = next(r for r in ROLES if r.name == "Data Consumer")
        request = _request({"alice@example.com": [team]}, applied=str(consumer.id))

        perms = effective_permissions_for_request(request, "alice@example.com", ["admins"], auth)

        assert perms.get("settings", L.NONE) == L.NONE
        assert perms["teams"] == L.READ_ONLY

    def test_without_applied_override_option(self, auth):
        team = _team(("alice@example.com", "Admin"))
        consumer = next(r for r in ROLES if r.name == "Data Consumer")
        request = _request({"alice@example.com": [team]}, applied=str(consumer.id))

        perms = effective_permissions_for_request(
            request, "alice@example.com", [], auth, apply_role_override=False,
        )

        assert perms["settings"] == L.ADMIN

    def test_resolved_once_per_request(self, auth):
        request = _request({})
        first = effective_permissions_for_request(request, "alice@example.com", ["data-consumers"], auth)
        second = effective_permissions_for_request(request, "alice@example.com", ["data-consumers"], auth)

        assert first is second
        assert request.app.state.teams_manager.get_team_rows_for_user.call_count == 1

    def test_a_dangling_applied_override_falls_back_to_the_merged_roles(self, auth):
        request = _request({"alice@example.com": [_team(("alice@example.com", "Data Steward"))]}, applied="gone")
        request.app.state.settings_manager.get_feature_permissions_for_role_id.side_effect = ValueError("not found")

        perms = effective_permissions_for_request(request, "alice@example.com", ["data-consumers"], auth)

        assert perms["data-domains"] == L.READ_WRITE

    def test_team_lookup_failure_grants_nothing_extra(self, auth):
        request = _request({})
        request.app.state.teams_manager.get_team_rows_for_user.side_effect = RuntimeError("db down")

        perms = effective_permissions_for_request(request, "alice@example.com", ["data-consumers"], auth)

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


class TestInHandlerAdminChecks:
    """The asset and data-product admin checks resolve like PermissionChecker, team roles included."""

    def _req(self, auth, teams_by_user, applied=None):
        request = _request(teams_by_user, applied=applied)
        request.app.state.authorization_manager = auth
        return request

    def _user(self, groups):
        return UserInfo(email="u@example.com", username="u", user="U", ip="127.0.0.1", groups=groups)

    def test_assets_gate_counts_team_roles(self, auth):
        from src.routes.assets_routes import _user_has_assets_feature

        settings = MagicMock()
        settings.list_app_roles.return_value = ROLES + [_role("Asset Editor", assets=L.READ_WRITE)]
        auth_with_assets = AuthorizationManager(settings_manager=settings)
        team = _team(("u@example.com", "Asset Editor"))

        assert not _user_has_assets_feature(self._req(auth_with_assets, {}), self._user(["data-consumers"]), L.READ_WRITE)
        assert _user_has_assets_feature(
            self._req(auth_with_assets, {"u@example.com": [team]}), self._user(["data-consumers"]), L.READ_WRITE,
        )

    def test_assets_gate_follows_an_applied_override(self, auth):
        from src.routes.assets_routes import _user_has_assets_feature

        settings = MagicMock()
        editor = _role("Asset Editor", assets=L.READ_WRITE)
        settings.list_app_roles.return_value = ROLES + [editor]
        auth_with_assets = AuthorizationManager(settings_manager=settings)
        consumer = next(r for r in ROLES if r.name == "Data Consumer")
        request = self._req(auth_with_assets, {"u@example.com": [_team(("u@example.com", "Asset Editor"))]},
                            applied=str(consumer.id))

        assert not _user_has_assets_feature(request, self._user([]), L.READ_WRITE)

    def test_data_product_admin_bypass_counts_team_roles(self, auth):
        from src.routes.data_product_routes import _caller_owns_product

        team = _team(("u@example.com", "Admin"))
        product = SimpleNamespace(id="p1", draft_owner_id=None, owner_team_id=None, project_id=None)

        assert _caller_owns_product(
            self._req(auth, {"u@example.com": [team]}), MagicMock(), self._user(["data-consumers"]), product,
        ) is True

    def test_product_read_admin_rule_counts_team_roles(self, auth):
        # The assistant tools (tools/caller.py) use this rule directly.
        from src.common.product_read_rule import is_product_read_admin

        team = _team(("u@example.com", "Admin"))

        assert not is_product_read_admin(self._req(auth, {}), self._user(["data-consumers"]))
        assert is_product_read_admin(self._req(auth, {"u@example.com": [team]}), self._user(["data-consumers"]))


class TestUserHasFeatureLevel:
    def test_sees_team_roles(self, auth):
        from src.common.authorization import user_has_feature_level

        request = _request({"u@example.com": [_team(("u@example.com", "Data Steward"))]})
        request.app.state.authorization_manager = auth
        user = UserInfo(email="u@example.com", username="u", user="U", ip="127.0.0.1", groups=["data-consumers"])

        assert user_has_feature_level(auth, user, "data-domains", L.READ_WRITE, request)
        assert not user_has_feature_level(auth, user, "settings", L.ADMIN, request)

    def test_fails_closed(self, auth):
        from src.common.authorization import user_has_feature_level

        request = _request({})
        broken = MagicMock()
        broken.get_user_effective_permissions.side_effect = RuntimeError("boom")
        user = UserInfo(email="u@example.com", username="u", user="U", ip="127.0.0.1", groups=["admins"])

        assert not user_has_feature_level(broken, user, "teams", L.READ_ONLY, request)


class TestAdoptEntityIdsStaysGroupBased:
    """``user_can_adopt_entity_ids_for`` uses the roles matching the user's groups only."""

    def _user(self, groups):
        return UserInfo(email="u@example.com", username="u", user="U", ip="127.0.0.1", groups=groups)

    def test_group_role_with_feature_admin_allows(self, auth):
        from src.common.authorization import user_can_adopt_entity_ids_for

        auth.user_can_adopt_entity_ids = MagicMock(return_value=False)
        assert user_can_adopt_entity_ids_for(auth, self._user(["admins"]), "data-products")

    def test_team_roles_do_not_count(self, auth, monkeypatch):
        from src.common.authorization import user_can_adopt_entity_ids_for

        monkeypatch.setattr(authorization, "lookup_user_team_roles", lambda *a: ["Admin"])
        auth.user_can_adopt_entity_ids = MagicMock(return_value=False)
        assert not user_can_adopt_entity_ids_for(auth, self._user(["data-consumers"]), "data-products")

    def test_fails_closed(self):
        from src.common.authorization import user_can_adopt_entity_ids_for

        broken = MagicMock()
        broken.user_can_adopt_entity_ids.return_value = False
        broken.get_user_effective_permissions.side_effect = RuntimeError("boom")
        assert not user_can_adopt_entity_ids_for(broken, self._user(["admins"]), "data-products")


class TestSearchRouteUsesResolvedPermissions:
    def _client(self, auth, teams_by_user, applied=None):
        from src.common.dependencies import get_auth_manager as dep_auth, get_settings_manager as dep_settings
        from src.routes import search_routes

        request_like = _request(teams_by_user, applied=applied)
        app = FastAPI()
        app.state.teams_manager = request_like.app.state.teams_manager
        app.state.settings_manager = request_like.app.state.settings_manager
        app.state.authorization_manager = auth
        search_manager = MagicMock()
        search_manager.search.return_value = []
        app.state.search_manager = search_manager
        app.include_router(search_routes.router)

        async def _user():
            return UserInfo(email="u@example.com", username="u", user="U", ip="127.0.0.1", groups=["data-consumers"])

        app.dependency_overrides[get_user_details_from_sdk] = _user
        app.dependency_overrides[dep_auth] = lambda: auth
        app.dependency_overrides[dep_settings] = lambda: app.state.settings_manager
        app.dependency_overrides[search_routes.get_search_manager] = lambda: search_manager
        return TestClient(app), search_manager

    def test_team_roles_reach_the_search_filter(self, auth):
        client, search_manager = self._client(auth, {"u@example.com": [_team(("u@example.com", "Data Steward"))]})

        assert client.get("/api/search?search_term=x").status_code == 200
        permissions = search_manager.search.call_args.kwargs["effective_permissions"]
        assert permissions["data-domains"] == L.READ_WRITE

    def test_an_applied_override_replaces_them(self, auth):
        consumer = next(r for r in ROLES if r.name == "Data Consumer")
        client, search_manager = self._client(
            auth, {"u@example.com": [_team(("u@example.com", "Admin"))]}, applied=str(consumer.id),
        )

        assert client.get("/api/search?search_term=x").status_code == 200
        permissions = search_manager.search.call_args.kwargs["effective_permissions"]
        assert permissions.get("settings", L.NONE) == L.NONE
        assert permissions["data-domains"] == L.READ_ONLY
