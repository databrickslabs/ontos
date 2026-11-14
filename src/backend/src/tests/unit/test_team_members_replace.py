"""Atomic team member replacement, team role override resolution, and the self-lockout guard."""
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.common.errors import NotFoundError
from src.common.features import ACCESS_LEVEL_ORDER, FeatureAccessLevel
from src.common.team_role_override import team_role_overrides
from src.controller.teams_manager import InvalidMemberSetError, TeamsManager
from src.db_models.teams import TeamDb, TeamMemberDb
from src.models.teams import TeamMemberCreate
from src.models.users import UserInfo
from fastapi import HTTPException

from src.models.teams import MAX_TEAM_MEMBERS
from src.routes.teams_routes import (
    _ensure_override_within_caller_permissions,
    _would_lose_team_write_access,
)


def _team(db_session, name="Admin Team") -> TeamDb:
    team = TeamDb(
        id=str(uuid.uuid4()), name=name, created_by="t", updated_by="t", extra_metadata="{}"
    )
    db_session.add(team)
    db_session.commit()
    return team


def _member(db_session, team, identifier, member_type="user", override=None) -> TeamMemberDb:
    member = TeamMemberDb(
        team_id=team.id,
        member_type=member_type,
        member_identifier=identifier,
        app_role_override=override,
        added_by="seed",
    )
    db_session.add(member)
    db_session.commit()
    return member


def _create(identifier, member_type="user", override=None) -> TeamMemberCreate:
    return TeamMemberCreate(
        member_type=member_type, member_identifier=identifier, app_role_override=override
    )


@pytest.fixture
def manager():
    return TeamsManager()


class TestReplaceTeamMembers:
    def test_adding_a_member_keeps_existing_rows(self, manager, db_session):
        team = _team(db_session)
        alice = _member(db_session, team, "alice@example.com", override="Admin")
        admins = _member(db_session, team, "admins", member_type="group", override="Admin")

        result = manager.replace_team_members(
            db_session,
            team.id,
            [
                _create("alice@example.com", override="Admin"),
                _create("admins", member_type="group", override="Admin"),
                _create("bob@example.com"),
            ],
            current_user_id="alice@example.com",
        )
        db_session.commit()

        assert sorted(m.member_identifier for m in result) == [
            "admins", "alice@example.com", "bob@example.com",
        ]
        by_id = {m.member_identifier: m for m in result}
        # Unchanged members keep their row, so their id and added_by survive the save.
        assert by_id["alice@example.com"].id == alice.id
        assert by_id["admins"].id == admins.id
        bob = db_session.query(TeamMemberDb).filter_by(member_identifier="bob@example.com").one()
        assert bob.added_by == "alice@example.com"

    def test_removes_and_updates_only_what_changed(self, manager, db_session):
        team = _team(db_session)
        _member(db_session, team, "alice@example.com", override="Admin")
        _member(db_session, team, "bob@example.com")
        carol = _member(db_session, team, "carol@example.com")

        result = manager.replace_team_members(
            db_session,
            team.id,
            [_create("alice@example.com", override="Admin"), _create("carol@example.com", override="Data Steward")],
            current_user_id="alice@example.com",
        )
        db_session.commit()

        by_id = {m.member_identifier: m for m in result}
        assert set(by_id) == {"alice@example.com", "carol@example.com"}
        assert by_id["carol@example.com"].id == carol.id
        assert by_id["carol@example.com"].app_role_override == "Data Steward"

    def test_case_change_keeps_the_row(self, manager, db_session):
        team = _team(db_session)
        alice = _member(db_session, team, "Alice@Example.com", override="Admin")

        result = manager.replace_team_members(
            db_session, team.id, [_create("alice@example.com", override="Admin")], current_user_id="x"
        )

        assert [(m.id, m.member_identifier) for m in result] == [(alice.id, "alice@example.com")]

    def test_duplicate_rows_are_collapsed(self, manager, db_session):
        """A twin row must not keep a stale override after the set is replaced."""
        team = _team(db_session)
        _member(db_session, team, "alice@example.com", override="Admin")
        _member(db_session, team, "alice@example.com")

        result = manager.replace_team_members(
            db_session, team.id, [_create("alice@example.com")], current_user_id="x"
        )
        db_session.commit()

        assert len(result) == 1
        assert result[0].app_role_override is None
        assert db_session.query(TeamMemberDb).filter_by(team_id=team.id).count() == 1

    def test_blank_override_is_stored_as_none(self, manager, db_session):
        team = _team(db_session)
        _member(db_session, team, "alice@example.com", override="Admin")

        result = manager.replace_team_members(
            db_session, team.id, [_create("alice@example.com", override="  ")], current_user_id="x"
        )

        assert result[0].app_role_override is None

    def test_empty_set_clears_the_team(self, manager, db_session):
        team = _team(db_session)
        _member(db_session, team, "alice@example.com")

        assert manager.replace_team_members(db_session, team.id, [], current_user_id="x") == []

    def test_case_insensitive_duplicates_are_rejected(self, manager, db_session):
        team = _team(db_session)
        with pytest.raises(InvalidMemberSetError, match="more than once"):
            manager.replace_team_members(
                db_session,
                team.id,
                [_create("alice@example.com"), _create(" Alice@example.com ")],
                current_user_id="x",
            )

    def test_unknown_team_raises_not_found(self, manager, db_session):
        with pytest.raises(NotFoundError):
            manager.replace_team_members(db_session, "missing", [], current_user_id="x")


class TestTeamRoleOverrides:
    def _teams(self, *members):
        return [SimpleNamespace(members=[
            SimpleNamespace(member_identifier=i, app_role_override=o, member_type="user" if "@" in i else "group")
            for i, o in members
        ])]

    def test_group_entry_in_users_team_grants_override(self):
        teams = self._teams(("alice@example.com", None), ("Admins", "Admin"))
        assert team_role_overrides(teams, "alice@example.com", ["admins"]) == ["Admin"]

    def test_every_applying_entry_counts(self):
        teams = self._teams(("admins", "Data Steward"), ("alice@example.com", "Admin"))
        assert set(team_role_overrides(teams, "alice@example.com", ["admins"])) == {"Admin", "Data Steward"}

    def test_members_without_override_are_ignored(self):
        teams = self._teams(("alice@example.com", None))
        assert team_role_overrides(teams, "alice@example.com", []) == []


class TestTeamRolesWithMembers:
    def test_group_only_membership_counts(self, manager, db_session):
        """#1245: a team's group entry applies to members of that group."""
        team = _team(db_session)
        _member(db_session, team, "admins", member_type="group", override="Admin")

        roles = manager.team_roles_with_members(
            db_session, team.id, [_create("admins", member_type="group", override="Admin")],
            user_identifier="alice@example.com", user_groups=["admins"],
        )

        assert roles == ["Admin"]

    def test_removing_own_entry_drops_override(self, manager, db_session):
        team = _team(db_session)
        _member(db_session, team, "alice@example.com", override="Admin")

        roles = manager.team_roles_with_members(
            db_session, team.id, [_create("bob@example.com")],
            user_identifier="alice@example.com", user_groups=[],
        )

        assert roles == []

    def test_joining_a_team_picks_up_its_override(self, manager, db_session):
        team = _team(db_session)

        roles = manager.team_roles_with_members(
            db_session, team.id, [_create("Alice@example.com", override="Admin")],
            user_identifier="alice@example.com", user_groups=[],
        )

        # Identifiers match ignoring case, like the team lookup.
        assert roles == ["Admin"]

    def test_override_from_another_team_is_kept(self, manager, db_session):
        team = _team(db_session)
        other = _team(db_session, name="Other Team")
        _member(db_session, team, "alice@example.com", override="Admin")
        _member(db_session, other, "data-stewards", member_type="group", override="Data Steward")

        roles = manager.team_roles_with_members(
            db_session, team.id, [],
            user_identifier="alice@example.com", user_groups=["data-stewards"],
        )

        assert roles == ["Data Steward"]


class TestSelfLockoutGuard:
    def _request(self, applied_role=None):
        auth_manager = MagicMock()
        auth_manager.get_user_effective_permissions.side_effect = (
            lambda groups, team_roles, user_email=None: {
                "teams": FeatureAccessLevel.ADMIN
                if "Admin" in (team_roles or []) or "team-admins" in groups
                else FeatureAccessLevel.READ_ONLY
            }
        )
        auth_manager.has_permission.side_effect = (
            lambda perms, feature, level:
            ACCESS_LEVEL_ORDER[perms.get(feature, FeatureAccessLevel.NONE)] >= ACCESS_LEVEL_ORDER[level]
        )
        settings_manager = MagicMock()
        settings_manager.get_applied_role_override_for_user.return_value = applied_role
        state = SimpleNamespace(authorization_manager=auth_manager, settings_manager=settings_manager)
        return SimpleNamespace(app=SimpleNamespace(state=state))

    def _user(self):
        return UserInfo(email="alice@example.com", username="alice", user="Alice", ip="127.0.0.1", groups=[])

    def test_refuses_removing_own_admin_entry(self, manager, db_session):
        team = _team(db_session)
        _member(db_session, team, "alice@example.com", override="Admin")

        assert _would_lose_team_write_access(
            self._request(), db_session, manager, team.id, [_create("bob@example.com")], self._user(),
        ) is True

    def test_refuses_deleting_the_team_that_grants_access(self, manager, db_session):
        team = _team(db_session)
        _member(db_session, team, "alice@example.com", override="Admin")

        assert _would_lose_team_write_access(
            self._request(), db_session, manager, team.id, [], self._user(),
        ) is True

    def test_allows_adding_members_while_keeping_own_entry(self, manager, db_session):
        team = _team(db_session)
        _member(db_session, team, "alice@example.com", override="Admin")

        assert _would_lose_team_write_access(
            self._request(), db_session, manager, team.id,
            [_create("alice@example.com", override="Admin"), _create("bob@example.com")], self._user(),
        ) is False

    def test_applied_role_override_skips_the_guard(self, manager, db_session):
        team = _team(db_session)
        _member(db_session, team, "alice@example.com", override="Admin")

        assert _would_lose_team_write_access(
            self._request(applied_role="role-1"), db_session, manager, team.id, [], self._user(),
        ) is False


class TestSelfLockoutGuardMerged:
    """Under max-merge, removing a team entry only locks out when nothing else grants teams Read/Write."""

    def _request(self):
        return TestSelfLockoutGuard()._request()

    def _user(self, groups):
        return UserInfo(email="alice@example.com", username="alice", user="Alice", ip="127.0.0.1", groups=groups)

    def test_allows_removing_own_entry_when_a_group_role_still_grants_access(self, manager, db_session):
        team = _team(db_session)
        _member(db_session, team, "alice@example.com", override="Admin")

        assert _would_lose_team_write_access(
            self._request(), db_session, manager, team.id, [], self._user(["team-admins"]),
        ) is False

    def test_refuses_removing_the_group_entry_that_grants_access(self, manager, db_session):
        team = _team(db_session)
        _member(db_session, team, "admins", member_type="group", override="Admin")

        assert _would_lose_team_write_access(
            self._request(), db_session, manager, team.id, [_create("bob@example.com")], self._user(["admins"]),
        ) is True

    def test_another_team_keeps_access(self, manager, db_session):
        team = _team(db_session)
        other = _team(db_session, name="Other Team")
        _member(db_session, team, "alice@example.com", override="Admin")
        _member(db_session, other, "admins", member_type="group", override="Admin")

        assert _would_lose_team_write_access(
            self._request(), db_session, manager, team.id, [], self._user(["admins"]),
        ) is False


class TestOverrideChangesWithinCallerPermissions:
    """Role override changes are validated against the caller's permissions.

    - A new override may grant at most the caller's levels.
    - Changing or removing an override whose role grants more than the caller holds
      needs the caller to hold all of that role's levels, or admin access to teams.
    - Group entries need admin access to teams to set, change or remove an override.
    """

    L = FeatureAccessLevel
    ROLE_PERMS = {
        "Admin": {"teams": L.ADMIN, "settings": L.ADMIN, "data-products": L.ADMIN},
        "Team Admin": {"teams": L.ADMIN, "settings": L.NONE, "data-products": L.READ_ONLY},
        "Data Producer": {"teams": L.READ_WRITE, "settings": L.NONE, "data-products": L.READ_WRITE},
        "Data Consumer": {"teams": L.READ_ONLY, "settings": L.NONE, "data-products": L.READ_ONLY},
    }

    def _request(self, caller_role):
        auth_manager = MagicMock()
        auth_manager.get_role_permissions_by_name.side_effect = (
            lambda names: {n: self.ROLE_PERMS.get(n) for n in names}
        )
        auth_manager.get_user_effective_permissions.side_effect = (
            lambda groups, team_roles, user_email=None: dict(self.ROLE_PERMS[caller_role])
        )
        settings_manager = MagicMock()
        settings_manager.get_applied_role_override_for_user.return_value = None
        state = SimpleNamespace(authorization_manager=auth_manager, settings_manager=settings_manager, teams_manager=None)
        return SimpleNamespace(app=SimpleNamespace(state=state), state=SimpleNamespace())

    def _user(self):
        return UserInfo(email="pat@example.com", username="pat", user="Pat", ip="127.0.0.1", groups=["data-producers"])

    def _check(self, manager, db_session, team, members, caller_role):
        _ensure_override_within_caller_permissions(
            self._request(caller_role), db_session, manager, team.id, members, self._user(), {},
        )

    def _refused(self, manager, db_session, team, members, caller_role, status=403):
        with pytest.raises(HTTPException) as exc:
            self._check(manager, db_session, team, members, caller_role)
        assert exc.value.status_code == status

    # New overrides
    def test_a_role_above_the_callers_levels_is_refused(self, manager, db_session):
        self._refused(manager, db_session, _team(db_session), [_create("pat@example.com", override="Admin")], "Data Producer")

    def test_a_role_within_the_callers_levels_is_allowed(self, manager, db_session):
        self._check(manager, db_session, _team(db_session), [
            _create("bob@example.com", override="Data Consumer"),
            _create("carol@example.com", override="Data Producer"),
        ], "Data Producer")

    def test_unknown_role_is_refused(self, manager, db_session):
        self._refused(manager, db_session, _team(db_session), [_create("x@example.com", override="Super")], "Admin", 422)

    # Changing or removing an existing override
    def test_lowering_a_higher_override_needs_its_levels(self, manager, db_session):
        team = _team(db_session)
        _member(db_session, team, "boss@example.com", override="Admin")

        self._refused(manager, db_session, team, [_create("boss@example.com", override="Data Consumer")], "Data Producer")

    def test_removing_a_higher_override_needs_its_levels(self, manager, db_session):
        team = _team(db_session)
        _member(db_session, team, "boss@example.com", override="Admin")

        self._refused(manager, db_session, team, [], "Data Producer")

    def test_teams_admin_may_lower_or_remove_a_higher_override(self, manager, db_session):
        team = _team(db_session)
        _member(db_session, team, "boss@example.com", override="Admin")
        _member(db_session, team, "kim@example.com", override="Admin")

        self._check(manager, db_session, team, [_create("boss@example.com", override="Data Consumer")], "Team Admin")

    def test_changing_an_override_within_the_callers_levels_is_allowed(self, manager, db_session):
        team = _team(db_session)
        _member(db_session, team, "bob@example.com", override="Data Consumer")

        self._check(manager, db_session, team, [_create("bob@example.com", override="Data Producer")], "Data Producer")
        self._check(manager, db_session, team, [], "Data Producer")

    def test_unchanged_entries_are_not_checked(self, manager, db_session):
        team = _team(db_session)
        _member(db_session, team, "boss@example.com", override="Admin")

        self._check(manager, db_session, team, [
            _create("boss@example.com", override="Admin"), _create("new@example.com"),
        ], "Data Producer")

    # Group entries
    def test_group_override_needs_teams_admin(self, manager, db_session):
        team = _team(db_session)

        self._refused(manager, db_session, team,
                      [_create("data-consumers", member_type="group", override="Data Consumer")], "Data Producer")
        self._check(manager, db_session, team,
                    [_create("data-consumers", member_type="group", override="Data Consumer")], "Team Admin")

    def test_removing_the_admin_teams_group_override_needs_teams_admin(self, manager, db_session):
        team = _team(db_session)
        _member(db_session, team, "admins", member_type="group", override="Admin")

        self._refused(manager, db_session, team, [], "Data Producer")
        self._refused(manager, db_session, team,
                      [_create("admins", member_type="group", override="Data Consumer")], "Data Producer")
        self._check(manager, db_session, team, [], "Admin")

    def test_group_entry_without_override_needs_no_admin(self, manager, db_session):
        self._check(manager, db_session, _team(db_session),
                    [_create("data-consumers", member_type="group")], "Data Producer")

    def test_changing_the_entry_type_counts_as_a_change(self, manager, db_session):
        team = _team(db_session)
        _member(db_session, team, "eng", member_type="user", override="Data Consumer")

        self._refused(manager, db_session, team,
                      [_create("eng", member_type="group", override="Data Consumer")], "Data Producer")


class TestMemberRoutesValidateOverrides:
    """The member routes validate override changes and answer 403/404/409/422, not 500."""

    @pytest.fixture
    def client(self, db_session, monkeypatch):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from src.common import authorization
        from src.common.authorization import get_user_details_from_sdk
        from src.common.dependencies import get_current_user_details_for_audit, get_db
        from src.common.manager_dependencies import get_audit_manager, get_auth_manager
        from src.controller.authorization_manager import AuthorizationManager
        from src.models.settings import AppRole
        from src.routes import teams_routes

        L = FeatureAccessLevel
        roles = [
            AppRole(id=uuid.uuid4(), name="Admin", description="", assigned_groups=["admins"],
                    feature_permissions={"teams": L.ADMIN, "settings": L.ADMIN}, home_sections=[], approval_privileges={}),
            AppRole(id=uuid.uuid4(), name="Data Producer", description="", assigned_groups=["data-producers"],
                    feature_permissions={"teams": L.READ_WRITE}, home_sections=[], approval_privileges={}),
        ]
        settings = MagicMock()
        settings.list_app_roles.return_value = roles
        settings.get_applied_role_override_for_user.return_value = None
        auth = AuthorizationManager(settings_manager=settings)

        app = FastAPI()
        app.state.authorization_manager = auth
        app.state.settings_manager = settings
        app.state.teams_manager = TeamsManager()
        app.include_router(teams_routes.router)
        self.user = UserInfo(email="pat@example.com", username="pat", user="Pat", ip="127.0.0.1", groups=["data-producers"])

        async def _user():
            return self.user

        def _db():
            yield db_session

        monkeypatch.setattr(authorization, "get_db", _db)
        app.dependency_overrides[get_user_details_from_sdk] = _user
        app.dependency_overrides[get_current_user_details_for_audit] = _user
        app.dependency_overrides[get_auth_manager] = lambda: auth
        app.dependency_overrides[get_db] = _db
        app.dependency_overrides[get_audit_manager] = lambda: MagicMock()
        return TestClient(app)

    # The routes roll back on refusal, which in the test session also undoes the
    # fixture's rows, so these tests check the response only.
    def test_adding_a_role_above_the_callers_levels_gets_403(self, client, db_session):
        team_id = _team(db_session).id

        resp = client.post(f"/api/teams/{team_id}/members", json={
            "member_type": "user", "member_identifier": "pat@example.com", "app_role_override": "Admin",
        })

        assert resp.status_code == 403

    def test_adding_a_group_override_without_teams_admin_gets_403(self, client, db_session):
        team_id = _team(db_session).id

        resp = client.post(f"/api/teams/{team_id}/members", json={
            "member_type": "group", "member_identifier": "data-consumers", "app_role_override": "Data Producer",
        })

        assert resp.status_code == 403

    def test_replacing_with_a_role_above_the_callers_levels_gets_403(self, client, db_session):
        team = _team(db_session)
        _member(db_session, team, "pat@example.com")
        team_id = team.id

        resp = client.put(f"/api/teams/{team_id}/members", json={"members": [
            {"member_type": "user", "member_identifier": "pat@example.com", "app_role_override": "Admin"},
        ]})

        assert resp.status_code == 403

    def test_a_member_within_the_callers_levels_can_be_added(self, client, db_session):
        team_id = _team(db_session).id

        resp = client.post(f"/api/teams/{team_id}/members", json={
            "member_type": "user", "member_identifier": "bob@example.com", "app_role_override": "Data Producer",
        })

        assert resp.status_code == 201

    def test_updating_an_override_to_a_role_above_the_callers_levels_gets_403(self, client, db_session):
        team = _team(db_session)
        member_id = _member(db_session, team, "pat@example.com").id
        team_id = team.id

        resp = client.put(f"/api/teams/{team_id}/members/{member_id}", json={"app_role_override": "Admin"})

        assert resp.status_code == 403

    def test_removing_the_admin_teams_group_entry_without_teams_admin_gets_403(self, client, db_session):
        team = _team(db_session)
        _member(db_session, team, "admins", member_type="group", override="Admin")
        _member(db_session, team, "pat@example.com")
        team_id = team.id

        resp = client.delete(f"/api/teams/{team_id}/members/admins")

        assert resp.status_code == 403

    def test_removing_a_higher_user_override_without_its_levels_gets_403(self, client, db_session):
        team = _team(db_session)
        _member(db_session, team, "boss@example.com", override="Admin")
        team_id = team.id

        resp = client.delete(f"/api/teams/{team_id}/members/boss@example.com")

        assert resp.status_code == 403

    def test_an_admin_can_remove_the_admin_teams_group_entry(self, client, db_session):
        team = _team(db_session)
        _member(db_session, team, "admins", member_type="group", override="Admin")
        team_id = team.id
        self.user = UserInfo(email="root@example.com", username="root", user="Root", ip="127.0.0.1", groups=["admins"])

        resp = client.delete(f"/api/teams/{team_id}/members/admins")

        assert resp.status_code == 204

    def test_duplicate_member_ignoring_case_is_409(self, client, db_session):
        team = _team(db_session)
        _member(db_session, team, "bob@example.com")
        team_id = team.id

        resp = client.post(f"/api/teams/{team_id}/members", json={
            "member_type": "user", "member_identifier": " Bob@Example.com ",
        })

        assert resp.status_code == 409

    def test_blank_identifier_is_422(self, client, db_session):
        team_id = _team(db_session).id

        resp = client.post(f"/api/teams/{team_id}/members", json={
            "member_type": "user", "member_identifier": "   ",
        })

        assert resp.status_code == 422

    def test_missing_team_is_404(self, client):
        resp = client.post("/api/teams/missing/members", json={
            "member_type": "user", "member_identifier": "x@example.com", "app_role_override": "Typo",
        })

        assert resp.status_code == 404

    def test_replace_on_a_missing_team_is_404(self, client):
        resp = client.put("/api/teams/missing/members", json={"members": [
            {"member_type": "group", "member_identifier": "eng", "app_role_override": "Typo"},
        ]})

        assert resp.status_code == 404

    def test_more_than_the_member_cap_is_422(self, client, db_session):
        team_id = _team(db_session).id
        members = [{"member_type": "user", "member_identifier": f"u{i}@example.com"} for i in range(MAX_TEAM_MEMBERS + 1)]

        resp = client.put(f"/api/teams/{team_id}/members", json={"members": members})

        assert resp.status_code == 422


class TestGroupOverrideScan:
    def test_lists_group_entries_with_an_override(self, manager, db_session):
        team = _team(db_session)
        _member(db_session, team, "admins", member_type="group", override="Admin")
        _member(db_session, team, "eng", member_type="group")
        _member(db_session, team, "alice@example.com", override="Admin")

        assert manager.group_role_override_entries(db_session) == [("Admin Team", "admins", "Admin")]

    def test_lists_user_entries_with_an_override_and_no_email(self, manager, db_session):
        team = _team(db_session)
        _member(db_session, team, "data-stewards", override="Data Steward")
        _member(db_session, team, "alice@example.com", override="Admin")

        assert manager.user_role_override_entries_without_email(db_session) == [
            ("Admin Team", "data-stewards", "Data Steward"),
        ]


class TestReviewFollowUps:
    """Rows that differ only in the identifier's case, a stale applied override, and 404 first."""

    def test_rows_differing_in_case_are_each_compared(self, manager, db_session):
        team = _team(db_session)
        _member(db_session, team, "Bob@example.com")
        _member(db_session, team, "bob@example.com")
        guard = TestOverrideChangesWithinCallerPermissions()
        members_after = [
            _create("Bob@example.com", override="Admin"),
            _create("bob@example.com"),
        ]

        with pytest.raises(HTTPException) as exc:
            guard._check(manager, db_session, team, members_after, "Data Producer")

        assert exc.value.status_code == 403

    def test_lockout_guard_runs_when_the_applied_role_no_longer_exists(self, manager, db_session):
        team = _team(db_session)
        _member(db_session, team, "alice@example.com", override="Admin")
        request = TestSelfLockoutGuard()._request(applied_role="gone")
        request.app.state.settings_manager.get_feature_permissions_for_role_id.side_effect = ValueError("not found")
        user = UserInfo(email="alice@example.com", username="alice", user="Alice", ip="127.0.0.1", groups=[])

        assert _would_lose_team_write_access(request, db_session, manager, team.id, [], user) is True
